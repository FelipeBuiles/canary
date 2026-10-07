"""Live pilot admission checks are entirely provider-free."""
import importlib.util
import json
from pathlib import Path
import sys

import pytest

from .test_crop_ocr import setup_case


@pytest.fixture
def pilot(monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('textract_crop_pilot', scripts / 'textract_crop_pilot.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    async def forbidden(**kwargs):
        pytest.fail('unapproved pilot called provider')
    monkeypatch.setattr(module.textract_ocr, 'run_checks', forbidden)
    return module


def manifest(tmp_path, count=1):
    case = setup_case(tmp_path / 'source')
    entries = [{'id': f'fixture-{i}', 'image': str(case[3].render_path(34, 1)),
        'box': [.1, .1, .8, .2], 'expected': 'Correct text.', 'primary': 'Correet text.'} for i in range(count)]
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(entries))
    return path


def test_pilot_prepares_without_paid_permission(pilot, tmp_path, monkeypatch, capsys):
    path = manifest(tmp_path)
    monkeypatch.setattr(sys, 'argv', ['pilot', '--manifest', str(path), '--output', str(tmp_path / 'out')])
    pilot.main()
    assert '"new_requests_upper_bound": 1' in capsys.readouterr().out


def test_pilot_fails_before_spend_when_budget_is_exceeded(pilot, tmp_path, monkeypatch):
    path = manifest(tmp_path, 2)
    monkeypatch.setattr(sys, 'argv', ['pilot', '--manifest', str(path), '--output', str(tmp_path / 'out'),
        '--allow-paid', '--max-requests', '1'])
    with pytest.raises(SystemExit, match='2'):
        pilot.main()


def test_pilot_rejects_directory_escape(pilot, tmp_path, monkeypatch):
    path = manifest(tmp_path)
    entries = json.loads(path.read_text())
    entries[0]['id'] = '../escape'
    path.write_text(json.dumps(entries))
    monkeypatch.setattr(sys, 'argv', ['pilot', '--manifest', str(path), '--output', str(tmp_path / 'out')])
    with pytest.raises(SystemExit, match='2'):
        pilot.main()
