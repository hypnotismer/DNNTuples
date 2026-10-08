"""Coverage and driver provenance tests for input-event segmentation."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import uproot
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'python'))
from vrslim_chunks import count_input_events, event_ranges, input_range
import run_vrslim
from test_vrslim_io import fixture


@pytest.mark.parametrize('total,size', [(1, 10000), (84000, 10000), (20000, 10000), (0, 10000)])
def test_exact_input_coverage(total, size):
    ranges = event_ranges(total, size)
    covered = [event for start, count in ranges for event in range(start, start + count)]
    assert covered == list(range(total))
    assert all(0 < count <= size for _, count in ranges)


@pytest.mark.parametrize('arguments', [ ['skipEvents=-1'], ['maxEvents=0'],
                                      ['maxEvents=-2'], ['skipEvents=0', 'skipEvents=10'] ])
def test_invalid_range(arguments):
    with pytest.raises(ValueError):
        input_range(arguments)


def test_count_entries(tmp_path):
    source = tmp_path / 'mini.root'
    with uproot.recreate(source) as root:
        root.mktree('Events', {'event': 'int64'})
        root['Events'].extend({'event': np.arange(17)})
    assert count_input_events(str(source)) == 17


def test_driver_records_input_range_and_keeps_source_id(tmp_path, monkeypatch):
    output = tmp_path / 'segment.root'
    source = 'root://host//store/sample.root'
    captured = []
    def fake_cmsrun(command, **kwargs):
        captured.extend(command)
        product = next(value.split('=', 1)[1] for value in command if value.startswith('outputFile='))
        source_id = int(next(value.split('=', 1)[1] for value in command if value.startswith('sourceFileId=')))
        fixture(Path(product), source_id=source_id)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(run_vrslim.subprocess, 'run', fake_cmsrun)
    monkeypatch.setattr(sys, 'argv', ['run_vrslim.py', '--input-files', source,
                                    '--output', str(output), 'skipEvents=10000', 'maxEvents=10000'])
    run_vrslim.main()
    manifest = json.loads(Path(str(output) + '.inputs.json').read_text())
    assert manifest['input_event_range'] == {'skipEvents': 10000, 'maxEvents': 10000}
    assert 'skipEvents=10000' in captured and 'maxEvents=10000' in captured
    assert manifest['inputs'][0]['source_file_id'] == str(run_vrslim.stable_source_id(source))


def test_driver_rejects_range_for_multiple_files(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['run_vrslim.py', '--input-files', 'a.root,b.root',
                                    '--output', str(tmp_path / 'bad.root'), 'maxEvents=10000'])
    with pytest.raises(SystemExit):
        run_vrslim.main()
    assert not (tmp_path / 'bad.root').exists()
