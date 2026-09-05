"""Synthetic multi-file tests of the actual lossless reader/merger."""
import sys
from pathlib import Path

import awkward as ak
import numpy as np
import pytest
import uproot

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from vrslim_io import EVENTS, JETS, SCHEMA, iter_jets, merge, validate, compare_reference
from vrslim_config import parse_radii, validate_thresholds


def jagged(rows, dtype):
    return ak.values_astype(ak.Array(rows), dtype)


def fixture(path, corrupt=False, config='same', empty=False):
    # Multiple jets at the same radius, shared objects across R, and an empty
    # neutral/SV collection in one event. Include signed zero in shared values.
    events = {
        'run_no': np.array([1, 1], np.uint32),
        'lumi_no': np.array([1, 1], np.uint32),
        'event_no': np.array([17, 18], np.uint64),
        'rho': np.array([3.25, 4.5], np.float32),
        'cpfcandlt_px': jagged([[10., -0., 3.], [4.]], np.float32),
        'cpfcandlt_isLostTrack': jagged([[0., 0., 1.], [0.]], np.float32),
        'npfcand_px': jagged([[8.], []], np.float32),
        'sv_mass': jagged([[1.5], []], np.float32),
    }
    jets = {
        'run_no': np.array([1, 1, 1, 1], np.uint32),
        'lumi_no': np.array([1, 1, 1, 1], np.uint32),
        'event_no': np.array([17, 17, 17, 18], np.uint64),
        'event_idx': np.array([0, 0, 0, 1], np.uint64),
        'radius_idx': np.array([0, 0, 1, 1], np.uint32),
        'jet_radius': np.array([0.2, 0.2, 0.8, 0.8], np.float64),
        'jet_no': np.array([0, 1, 0, 0], np.uint32),
        'fj_jetR': np.array([0.2, 0.2, 0.8, 0.8], np.float32),
        'cpf_indices': jagged([[0, 1, 2], [2], [1, 0, 2], [0]], np.uint32),
        'npf_indices': jagged([[0], [], [0], []], np.uint32),
        'sv_indices': jagged([[0], [0], [0], []], np.uint32),
        'cpfcandlt_btagSip3dVal': jagged([[0.1, -0.2, 0.3], [0.4], [-0.5, 0.6, 0.7], [0.8]], np.float32),
        'npfcand_etarel': jagged([[0.01], [], [0.1], []], np.float32),
        'sv_etarel': jagged([[0.2], [0.4], [-0.1], []], np.float32),
    }
    if corrupt:
        jets['event_idx'][-1] = 4
    with uproot.recreate(path) as root:
        root[SCHEMA] = '1'
        root['vrslim/VRslimConfig'] = config
        for name, values in [(EVENTS, events), (JETS, jets)]:
            root.mktree(name, {k: ak.type(v).content for k, v in values.items()})
            if not empty:
                root[name].extend(values)
    return events, jets


def test_gather_keeps_order_bits_and_associations(tmp_path):
    path = tmp_path / 'one.root'
    fixture(path)
    assert validate(path, 2) == {'events': 2, 'jets': 4}
    rows = list(iter_jets(path, 2))
    actual = ak.concatenate([r['cpfcandlt_px'] for r in rows])
    expected = jagged([[10., -0., 3.], [3.], [-0., 10., 3.], [4.]], np.float32)
    assert ak.to_numpy(ak.flatten(actual)).tobytes() == ak.to_numpy(ak.flatten(expected)).tobytes()
    assert ak.to_list(rows[0]['sv_mass']) == [[1.5], [1.5]]
    assert ak.to_list(rows[1]['npfcand_px']) == [[8.], []]
    assert ak.to_list(rows[0]['rho']) == [3.25, 3.25]


def test_merge_rebases_without_collapsing_reused_mc_ids(tmp_path):
    a, b, empty, out = [tmp_path / n for n in ['a.root', 'b.root', 'empty.root', 'out.root']]
    fixture(a)
    fixture(b)  # Deliberately identical run/lumi/event in a different input.
    fixture(empty, empty=True)
    assert merge([empty, a, b], out, 2) == {'events': 4, 'jets': 8}
    with uproot.open(out) as root:
        assert ak.to_list(root[JETS]['event_idx'].array()) == [0, 0, 0, 1, 2, 2, 2, 3]
        assert root[JETS]['jet_radius'].interpretation.numpy_dtype == np.dtype('float64')
    before = [x for p in (a, b) for x in iter_jets(p, 2)]
    after = list(iter_jets(out, 2))
    for old, new in zip(before, after):
        assert set(old) == set(new)
        for key in old:
            assert ak.to_numpy(ak.flatten(old[key], axis=None)).tobytes() == ak.to_numpy(ak.flatten(new[key], axis=None)).tobytes()
    with pytest.raises(FileExistsError):
        merge([a], out)


def test_reject_corrupt_and_incompatible_files(tmp_path):
    a, b, c = [tmp_path / n for n in ['a.root', 'b.root', 'c.root']]
    fixture(a)
    fixture(b, corrupt=True)
    fixture(c, config='different R')
    with pytest.raises(ValueError, match='event_idx'):
        validate(b)
    dest = tmp_path / 'bad.root'
    with pytest.raises(ValueError, match='Incompatible'):
        merge([a, c], dest)
    assert not dest.exists()


def test_exact_reference_comparison(tmp_path):
    path = tmp_path / 'pilot.root'
    fixture(path)
    rows = next(iter_jets(path, 100, include_internal=True))
    with uproot.update(path) as root:
        for r, label in [(0.2, '0p2'), (0.8, '0p8')]:
            values = {k: v[rows['jet_radius'] == r] for k, v in rows.items()
                      if k not in {'event_idx', 'radius_idx', 'jet_radius', 'cpf_indices', 'npf_indices', 'sv_indices'}}
            name = 'referenceAKr' + label + '/tree'
            root.mktree(name, {k: ak.type(v).content for k, v in values.items()})
            root[name].extend(values)
    assert compare_reference(path, 2) == {'referenceAKr0p2/tree': 2, 'referenceAKr0p8/tree': 2}


def test_arbitrary_radius_and_threshold_validation():
    assert parse_radii('0.05,0.25,0.8,1.5') == [0.05, 0.25, 0.8, 1.5]
    for bad in ['', '0.2,0.20', '-0.1', 'nan', 'inf', '0', '0.12345678901231,0.12345678901232']:
        with pytest.raises(ValueError):
            parse_radii(bad)
    validate_thresholds(100., 170., 200.)
    for values in [(170., 100., 200.), (100., 170., float('nan'))]:
        with pytest.raises(ValueError):
            validate_thresholds(*values)


@pytest.mark.parametrize('damage', ['index', 'association', 'identity'])
def test_corrupt_relation_rejected(tmp_path, damage):
    path = tmp_path / 'broken.root'
    events, jets = fixture(path)
    if damage == 'index':
        jets['cpf_indices'] = jagged([[99], [2], [1, 0, 2], [0]], np.uint32)
    elif damage == 'association':
        jets['cpfcandlt_btagSip3dVal'] = jagged([[0.1], [0.4], [-0.5, 0.6, 0.7], [0.8]], np.float32)
    else:
        jets['event_no'][0] = 999
    with uproot.recreate(path) as root:
        root[SCHEMA] = '1'
        for name, values in [(EVENTS, events), (JETS, jets)]:
            root.mktree(name, {k: ak.type(v).content for k, v in values.items()})
            root[name].extend(values)
    with pytest.raises(ValueError):
        validate(path)


def test_all_empty_merge(tmp_path):
    path, output = tmp_path / 'empty.root', tmp_path / 'merged.root'
    fixture(path, empty=True)
    assert merge([path], output) == {'events': 0, 'jets': 0}
    assert list(iter_jets(output)) == []


def test_driver_retries_then_merges_and_cleans_scratch(tmp_path, monkeypatch):
    import json
    import types
    import run_vrslim
    output = tmp_path / 'job.root'
    attempts = {}
    products = []

    def fake_cmsrun(command, **kwargs):
        assert command[0] == 'cmsRun'
        product = Path(next(x.split('=', 1)[1] for x in command if x.startswith('outputFile=')))
        attempts[product] = attempts.get(product, 0) + 1
        if attempts[product] == 1:
            kwargs['stdout'].write('Transient simulated failure\n')
            return types.SimpleNamespace(returncode=1)
        fixture(product)
        products.append(product)
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(run_vrslim.subprocess, 'run', fake_cmsrun)
    monkeypatch.setattr(sys, 'argv', ['run_vrslim.py', '--input-files', 'file:a.root,file:b.root',
                                    '--output', str(output), '--retries', '2', 'era=UL17'])
    run_vrslim.main()
    assert validate(output) == {'events': 4, 'jets': 8}
    assert list(attempts.values()) == [2, 2]
    assert all(not p.exists() for p in products)
    manifest = json.loads(output.with_name('job.root.inputs.json').read_text())
    assert manifest['inputs'] == ['file:a.root', 'file:b.root']


def test_driver_failure_does_not_publish_partial_job(tmp_path, monkeypatch):
    import types
    import run_vrslim
    output = tmp_path / 'failed.root'

    def fake_cmsrun(command, **kwargs):
        kwargs['stdout'].write('Terminal simulated failure\n')
        return types.SimpleNamespace(returncode=1)

    monkeypatch.setattr(run_vrslim.subprocess, 'run', fake_cmsrun)
    monkeypatch.setattr(sys, 'argv', ['run_vrslim.py', '--input-files', 'file:a.root',
                                    '--output', str(output), '--retries', '2'])
    with pytest.raises(RuntimeError):
        run_vrslim.main()
    assert not output.exists()
    logs = list(tmp_path.glob('failed.root.failed.*.log'))
    assert len(logs) == 1 and 'Terminal simulated failure' in logs[0].read_text()
