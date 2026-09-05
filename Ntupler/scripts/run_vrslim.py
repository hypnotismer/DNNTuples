#!/usr/bin/env python3
"""Process one Condor file-list row, retry each MiniAOD, merge with rebasing.

Run inside an initialized CMSSW environment, using Python 3 with vrslim_io's
dependencies. inputFiles/outputFile/writeReference are managed by this driver.
"""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from vrslim_io import merge, validate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-files', required=True, help='Comma-separated MiniAODs (one existing Condor Infiles row)')
    parser.add_argument('--output', required=True, help='Local final ROOT; existing files are never overwritten')
    parser.add_argument('--config', default=str(Path(__file__).resolve().parents[1] / 'test' / 'DeepNtuplizerVRslim.py'))
    parser.add_argument('--retries', type=int, default=5)
    parser.add_argument('cmsrun_args', nargs='*', help='e.g. era=UL17 jetRadii=0.1,0.2,0.8,1.5')
    args = parser.parse_args()
    inputs = [x.strip() for x in args.input_files.split(',')]
    if any(not x for x in inputs) or len(set(inputs)) != len(inputs) or args.retries < 1:
        parser.error('Inputs must be distinct and nonempty; retries must be positive')
    for value in args.cmsrun_args:
        if value.split('=', 1)[0] in {'inputFiles', 'outputFile', 'writeReference'}:
            parser.error('Driver manages inputFiles/outputFile/writeReference')
    config = Path(args.config).resolve()
    output = Path(args.output).resolve()
    manifest = output.with_name(output.name + '.inputs.json')
    if output.exists() or manifest.exists():
        raise FileExistsError('Output or input manifest already exists: ' + str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    # These are task-owned temporary files only; cleanup never touches inputs.
    with tempfile.TemporaryDirectory(prefix='vrslim-', dir=output.parent) as scratch:
        products = []
        for i, source in enumerate(inputs):
            # Relative local file inputs must not change meaning in the scratch cwd.
            if source.startswith('file:') and not source.startswith('file:/'):
                source = 'file:' + str(Path(source[5:]).resolve())
            product = Path(scratch) / ('raw%d.root' % i)
            log = Path(scratch) / ('raw%d.log' % i)
            command = ['cmsRun', str(config), 'inputFiles=' + source,
                       'outputFile=' + str(product), 'writeReference=False'] + args.cmsrun_args
            for attempt in range(args.retries):
                product.unlink(missing_ok=True)
                print('Input %d/%d, attempt %d: %s' % (i + 1, len(inputs), attempt + 1, source), flush=True)
                with log.open('w') as stream:
                    result = subprocess.run(command, cwd=scratch, stdout=stream, stderr=subprocess.STDOUT)
                try:
                    if result.returncode:
                        raise RuntimeError('cmsRun exit code %d' % result.returncode)
                    validate(product)
                    break
                except Exception:
                    if attempt + 1 == args.retries:
                        # Save the final diagnostic log outside the temporary directory.
                        with tempfile.NamedTemporaryFile(mode='w', prefix=output.name + '.failed.',
                                                         suffix='.log', dir=output.parent, delete=False) as dest, log.open() as src:
                            for line in src:
                                dest.write(line)
                            print('Failure log:', dest.name, flush=True)
                        raise
            products.append(product)
        counts = merge(products, output)
    # Manifest preserves original input provenance; do not rely on MC event IDs
    # being unique across separate generated samples.
    with manifest.open('x') as stream:
        json.dump({'inputs': inputs, 'cmsrun_args': args.cmsrun_args, 'counts': counts}, stream, indent=2)
    print(counts)


if __name__ == '__main__':
    main()
