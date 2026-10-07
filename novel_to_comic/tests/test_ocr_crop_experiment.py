"""The operator replay must follow the same mismatch selection as validation."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

from PIL import Image
import pytest

from novel_to_comic.models.crop_ocr import CropOCRLine


def load_script(monkeypatch, name):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(name, scripts / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fixture(tmp_path):
    image = tmp_path / "source.png"
    Image.new("RGB", (160, 80), "white").save(image)
    return {
        "id": "caption",
        "image": str(image),
        "box": [0.1, 0.1, 0.8, 0.8],
        "expected": "Jimmy Robbons climbed.",
        "primary": "Jimmy Robbins climbed.",
    }


class Reader:
    fingerprint = "fixture-reader"

    def __init__(self, *args):
        self.calls = 0
        self._process = None

    def read(self, image, *, timeout):
        self.calls += 1
        return (
            CropOCRLine(
                text="Jimmy Robbons climbed.", confidence=0.99, box=(0, 0, 100, 30)
            ),
        )

    def close(self):
        pass


def test_replay_reads_only_mismatches_and_reuses_evidence(tmp_path, monkeypatch):
    script = load_script(monkeypatch, "ocr_crop_experiment")
    entry = fixture(tmp_path)
    original = Path(entry["image"]).read_bytes()
    matching = {**entry, "id": "matching", "primary": entry["expected"]}
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([entry, matching]))
    reader = Reader()
    monkeypatch.setattr(script, "PaddleCropReader", lambda *args: reader)
    output = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "replay",
            "--manifest",
            str(manifest),
            "--models",
            "unused",
            "--python",
            "unused",
            "--output",
            str(output),
        ],
    )
    script.main()
    results = json.loads((output / "results.json").read_text())
    assert results[0]["assessment"] == "disagrees"
    assert results[0]["transcription_correct"] is True
    assert results[1]["crop_count"] == 0
    assert reader.calls == 1
    script.main()
    assert reader.calls == 1
    assert Path(entry["image"]).read_bytes() == original


def test_contention_fixture_exercises_six_real_reader_calls(tmp_path, monkeypatch):
    benchmark = load_script(monkeypatch, "ocr_crop_benchmark")
    reader = Reader()
    row = benchmark.run_case(fixture(tmp_path), reader, tmp_path / "output", crops=6)
    assert row["complete"] is True
    assert row["status"] == "disagrees"
    assert row["crops"] == reader.calls == row["correct_reads"] == 6


def test_failed_native_startup_stops_before_load_testing(tmp_path, monkeypatch):
    benchmark = load_script(monkeypatch, "ocr_crop_benchmark")

    class UnavailableReader(Reader):
        def read(self, image, *, timeout):
            self.calls += 1
            raise RuntimeError("Missing native library")

    reader = UnavailableReader()
    monkeypatch.setattr(benchmark, "PaddleCropReader", lambda *args: reader)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps([fixture(tmp_path)]))
    output = tmp_path / "output"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "benchmark",
            "--manifest",
            str(manifest),
            "--models",
            "unused",
            "--python",
            "unused",
            "--output",
            str(output),
        ],
    )
    with pytest.raises(RuntimeError, match="Native OCR failed"):
        benchmark.main()
    phases = json.loads((output / "phases.json").read_text())
    assert [phase["phase"] for phase in phases] == ["matching-cold", "pilot"]
    assert reader.calls == 1
    assert (output / "metrics.json").exists()
