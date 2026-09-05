#!/usr/bin/env python3
"""Read, validate, merge and losslessly expand VRslim ROOT files.

Requires Python 3, uproot >= 5, awkward >= 2, numpy. No CMSSW dependency.
The default training interface is iter_jets(): expanded arrays exist only in RAM.
"""
import argparse
import os
from pathlib import Path
import tempfile

import awkward as ak
import numpy as np
import uproot

EVENTS = 'vrslim/Events'
JETS = 'vrslim/Jets'
SCHEMA = 'vrslim/VRslimSchema'
INDEX = {'cpfcandlt_': 'cpf_indices', 'npfcand_': 'npf_indices', 'sv_': 'sv_indices'}
INTERNAL = {'event_idx', 'radius_idx', 'jet_radius'} | set(INDEX.values())


def names(tree):
    """Ignore automatic count leaves made by uproot when writing jagged TTrees."""
    counters = {b.count_branch.name for b in tree.values()
                if getattr(b, 'count_branch', None) is not None}
    return [name for name in tree.keys() if name not in counters]


def arrays(tree, start=0, stop=None):
    return tree.arrays(names(tree), entry_start=start, entry_stop=stop, library='ak', how=dict)


def schema(tree):
    return {name: ak.type(value).content for name, value in arrays(tree, 0, 0).items()}


def check_schema(root):
    obj = root[SCHEMA]
    version = obj.member('fTitle') if obj.classname == 'TNamed' else str(obj)
    if version != '1':
        raise ValueError('Unsupported VRslim schema: ' + version)
    for path in (EVENTS, JETS):
        if root[path].classname != 'TTree':
            raise ValueError(path + ' must be a TTree')


def _group(name):
    return next((idx for prefix, idx in INDEX.items() if name.startswith(prefix)), None)


def _references(root, jets):
    ids = ak.to_numpy(jets['event_idx'])
    if len(ids) == 0:
        return {}, np.array([], dtype=np.int64)
    if ids.dtype.kind not in 'ui' or np.any(ids >= root[EVENTS].num_entries) or np.any(ids < 0):
        raise ValueError('Jet event_idx out of range or non-integer')
    if np.any(ids[1:] < ids[:-1]):
        raise ValueError('Jets must be ordered by event_idx for bounded event reads')
    first, last = int(ids[0]), int(ids[-1])
    events = arrays(root[EVENTS], first, last + 1)
    local = (ids - first).astype(np.int64)
    for name in ('run_no', 'lumi_no', 'event_no'):
        if not np.array_equal(ak.to_numpy(jets[name]), ak.to_numpy(events[name][local])):
            raise ValueError('Jet/event identity mismatch: ' + name)
    return events, local


def _check_objects(events, jets, local):
    sizes = {}
    for name, values in events.items():
        idx = _group(name)
        if idx:
            count = ak.num(values, axis=1)
            if idx in sizes and not bool(ak.all(count == sizes[idx])):
                raise ValueError('Shared object feature length mismatch: ' + name)
            sizes[idx] = count
    for idx in INDEX.values():
        if idx not in sizes:
            raise ValueError('Missing shared object group: ' + idx)
        ids = jets[idx]
        flat_ids = ak.to_numpy(ak.flatten(ids))
        if flat_ids.dtype.kind not in 'iu' or bool(ak.any((ids < 0) | (ids >= sizes[idx][local]))):
            raise ValueError('Constituent index out of range or non-integer: ' + idx)
    for name, values in jets.items():
        idx = _group(name)
        if idx and not bool(ak.all(ak.num(values, axis=1) == ak.num(jets[idx], axis=1))):
            raise ValueError('Association feature length mismatch: ' + name)


def iter_jets(path, step_size=1024, include_internal=False):
    """Yield legacy-named arrays, one row per jet, preserving values and order.

    Read sequential event groups, then let the training pipeline shuffle jets
    within/across chunks. Split train/validation/test by input event identity,
    including dataset provenance, never independently by jet or radius.
    """
    with uproot.open(path) as root:
        check_schema(root)
        for jets in root[JETS].iterate(names(root[JETS]), step_size=step_size, library='ak', how=dict):
            events, local = _references(root, jets)
            _check_objects(events, jets, local)
            result = {k: v for k, v in jets.items() if include_internal or k not in INTERNAL}
            for name, values in events.items():
                idx = _group(name)
                if idx:
                    # First select events (with repetition), then select each
                    # jet's jagged constituent list; preserve the filler order.
                    result[name] = values[local][jets[idx]]
                elif name not in result:
                    result[name] = values[local]
            yield result


def validate(path, step_size=1024):
    with uproot.open(path) as root:
        check_schema(root)
        event_count, jet_count = root[EVENTS].num_entries, root[JETS].num_entries
        expected = 0
        previous = None
        radii = {}
        for jets in root[JETS].iterate(names(root[JETS]), step_size=step_size, library='ak', how=dict):
            events, local = _references(root, jets)
            _check_objects(events, jets, local)
            for idx in ak.to_numpy(jets['event_idx']):
                idx = int(idx)
                if idx != previous:
                    if idx != expected:
                        raise ValueError('Unreferenced or out-of-order Events entry')
                    expected += 1
                    previous = idx
            for ir, r in zip(ak.to_numpy(jets['radius_idx']), ak.to_numpy(jets['jet_radius'])):
                if not np.isfinite(r) or r <= 0 or (int(ir) in radii and radii[int(ir)] != r):
                    raise ValueError('Inconsistent radius index/physical radius')
                radii[int(ir)] = r
        if expected != event_count:
            raise ValueError('Unreferenced Events entries')
        return {'events': event_count, 'jets': jet_count}


def _destination(output):
    dest = Path(output).resolve()
    if dest.exists():
        raise FileExistsError('Refusing to overwrite ' + str(dest))
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.' + dest.name + '.', suffix='.root', dir=dest.parent)
    os.close(fd)
    return dest, Path(temporary)


def merge(inputs, output, step_size=1024):
    """Concatenate with file-local event_idx rebasing; no physics dedup by ID.

    Independent MC samples can reuse run/lumi/event, so equal IDs in distinct
    inputs MUST NOT collapse. All files must use the same production config.
    """
    if not inputs or len(set(map(str, inputs))) != len(inputs):
        raise ValueError('Provide a non-empty list of distinct inputs')
    dest, temporary = _destination(output)
    try:
        event_offset = 0
        expected = None
        config = None
        with uproot.recreate(temporary, compression=uproot.LZ4(4)) as out:
            out[SCHEMA] = '1'
            for source in inputs:
                validate(source, step_size)
                with uproot.open(source) as root:
                    cfg_obj = root['vrslim/VRslimConfig']
                    current_config = cfg_obj.member('fTitle') if cfg_obj.classname == 'TNamed' else str(cfg_obj)
                    current = {path: schema(root[path]) for path in (EVENTS, JETS)}
                    if expected is None:
                        expected, config = current, current_config
                        out['vrslim/VRslimConfig'] = config
                        for path in (EVENTS, JETS):
                            out.mktree(path, expected[path])
                    elif current != expected or current_config != config:
                        raise ValueError('Incompatible schema or reconstruction configuration: ' + str(source))
                    for path in (EVENTS, JETS):
                        for chunk in root[path].iterate(names(root[path]), step_size=step_size, library='ak', how=dict):
                            if path == JETS:
                                chunk['event_idx'] = chunk['event_idx'] + np.uint64(event_offset)
                            out[path].extend(chunk)
                    event_offset += root[EVENTS].num_entries
            out['vrslim/MergeInputs'] = '\n'.join(map(str, inputs))
        counts = validate(temporary, step_size)
        # Atomic no-clobber publication on the destination filesystem.
        os.link(temporary, dest)
        return counts
    finally:
        temporary.unlink(missing_ok=True)


def compare_reference(path, step_size=1024):
    """Compare every legacy branch bit-for-bit against writeReference=True."""
    with uproot.open(path) as root:
        validate(path, step_size)
        offsets = {}
        for expanded in iter_jets(path, step_size, include_internal=True):
            for radius in np.unique(ak.to_numpy(expanded['jet_radius'])):
                # Match the CMSSW label convention without importing CMSSW.
                token = ('%.12g' % radius).lower().replace('.', 'p').replace('-', 'm').replace('+', '')
                refname = 'referenceAKr' + token + '/tree'
                mask = expanded['jet_radius'] == radius
                count = int(ak.sum(mask))
                start = offsets.get(refname, 0)
                reference = arrays(root[refname], start, start + count)
                if set(reference) != set(expanded) - INTERNAL:
                    raise ValueError('Legacy branch set differs')
                for name, expected in reference.items():
                    actual = expanded[name][mask]
                    if ak.type(actual).content != ak.type(expected).content:
                        raise ValueError('Type mismatch: ' + name)
                    if actual.ndim > 1 and not bool(ak.all(ak.num(actual) == ak.num(expected))):
                        raise ValueError('Array length mismatch: ' + name)
                    a, b = ak.to_numpy(ak.flatten(actual, axis=None)), ak.to_numpy(ak.flatten(expected, axis=None))
                    if a.tobytes() != b.tobytes():
                        raise ValueError('Bitwise mismatch: ' + name + ' in ' + refname)
                offsets[refname] = start + count
        for key in root.keys(recursive=True, cycle=False):
            if key.startswith('referenceAKr') and key.endswith('/tree'):
                if offsets.get(key, 0) != root[key].num_entries:
                    raise ValueError('Reference jet count mismatch: ' + key)
        if not offsets:
            raise ValueError('No selected jets/reference comparison; run a larger pilot')
        return offsets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('validate', 'compare'):
        p = sub.add_parser(command)
        p.add_argument('input')
    p = sub.add_parser('merge')
    p.add_argument('output')
    p.add_argument('inputs', nargs='+')
    args = parser.parse_args()
    if args.command == 'merge':
        print(merge(args.inputs, args.output))
    elif args.command == 'compare':
        print(compare_reference(args.input))
    else:
        print(validate(args.input))


if __name__ == '__main__':
    main()
