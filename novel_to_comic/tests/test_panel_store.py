"""Tests for panel_store — validates that save_breakdown / save_prompt enforce invariants."""

import json
from pathlib import Path

import pytest

from novel_to_comic.panel_store import load_breakdown, load_prompt, save_breakdown, save_prompt


def _breakdown_body() -> dict:
    return {
        "scene_id": "scene_01",
        "panel_number": 1,
        "description": "A tense close-up.",
        "characters_present": [],
        "character_actions": {},
        "character_expressions": {},
        "key_objects": [],
        "character_positions": {},
        "dialogue": [],
        "shot_type": "close-up",
        "camera_angle": "eye level",
        "background_description": "Office interior",
        "lighting": "natural",
        "mood": "tense",
    }


def _panel_dir(project_dir: Path, scene_id: str) -> Path:
    d = project_dir / "storyboard" / scene_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _prompt_dir(project_dir: Path, scene_id: str) -> Path:
    d = project_dir / "direct" / scene_id
    d.mkdir(parents=True, exist_ok=True)
    return d


class TestSaveBreakdown:
    def test_writes_file_on_success(self, tmp_path: Path):
        _panel_dir(tmp_path, "scene_01")
        result = save_breakdown(tmp_path, "scene_01", 1, _breakdown_body())
        path = tmp_path / "storyboard" / "scene_01" / "panel_001.json"
        assert path.exists()
        assert result.scene_id == "scene_01"

    def test_raises_on_invalid_data(self, tmp_path: Path):
        _panel_dir(tmp_path, "scene_01")
        with pytest.raises(Exception):
            save_breakdown(tmp_path, "scene_01", 1, {"completely": "wrong"})

    def test_roundtrip_matches(self, tmp_path: Path):
        _panel_dir(tmp_path, "scene_01")
        save_breakdown(tmp_path, "scene_01", 1, _breakdown_body())
        loaded = load_breakdown(tmp_path, "scene_01", 1)
        assert loaded is not None
        assert loaded.scene_id == "scene_01"
        assert loaded.panel_number == 1

    def test_load_returns_none_when_missing(self, tmp_path: Path):
        result = load_breakdown(tmp_path, "scene_01", 99)
        assert result is None


class TestSavePrompt:
    def _prompt_body(self) -> dict:
        return {
            "prompt_version": 1,
            "planned_panel_id": "scene_01_panel_001",
            "scene_id": "scene_01",
            "panel_number": 1,
            "generation_mode": "standard",
            "shape_intent": "landscape",
            "full_prompt": "old prompt text",
            "style": "test-style",
            "composition": "close-up shot",
            "setting": "office interior",
            "lighting": "natural",
            "mood": "tense",
            "constraints": "exactly 1 character; no text",
            "has_narration_caption": False,
            "width": 1024,
            "height": 576,
            "steps": 20,
        }

    def test_rerenders_full_prompt_on_save(self, tmp_path: Path):
        _prompt_dir(tmp_path, "scene_01")
        body = self._prompt_body()
        body["full_prompt"] = "stale old prompt"
        result = save_prompt(tmp_path, "scene_01", 1, body)
        # full_prompt should be re-derived from fields, not preserved as-is
        assert result.full_prompt != "stale old prompt"

    def test_writes_file(self, tmp_path: Path):
        _prompt_dir(tmp_path, "scene_01")
        save_prompt(tmp_path, "scene_01", 1, self._prompt_body())
        path = tmp_path / "direct" / "scene_01" / "panel_001.json"
        assert path.exists()

    def test_load_returns_none_when_missing(self, tmp_path: Path):
        result = load_prompt(tmp_path, "scene_01", 99)
        assert result is None

    def test_roundtrip_preserves_scene_id(self, tmp_path: Path):
        _prompt_dir(tmp_path, "scene_01")
        save_prompt(tmp_path, "scene_01", 1, self._prompt_body())
        loaded = load_prompt(tmp_path, "scene_01", 1)
        assert loaded is not None
        assert loaded.scene_id == "scene_01"

    def test_raises_on_invalid_data(self, tmp_path: Path):
        _prompt_dir(tmp_path, "scene_01")
        with pytest.raises(Exception):
            save_prompt(tmp_path, "scene_01", 1, {"bad": "data"})
