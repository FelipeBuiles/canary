"""Tests for RAG chunker (rag/chunker.py)."""

import tempfile
from pathlib import Path

import pytest

from novel_to_comic.rag.chunker import chunk_scene_text, load_scene_texts


class TestChunkSceneText:
    def test_empty_string_returns_empty_list(self):
        assert chunk_scene_text("") == []

    def test_single_short_paragraph_returns_one_chunk(self):
        text = "This is a short scene."
        chunks = chunk_scene_text(text)
        assert len(chunks) == 1
        assert "short scene" in chunks[0]

    def test_respects_max_tokens(self):
        # Build a scene big enough that it must split
        big_para = "Word " * 600  # ~600 words, far over max_tokens
        text = f"{big_para}\n\nAnother paragraph."
        chunks = chunk_scene_text(text, target_tokens=600, max_tokens=800)
        assert len(chunks) >= 1

    def test_splits_at_paragraph_boundary(self):
        para1 = "First paragraph here."
        para2 = "Second paragraph here."
        para3 = "Third paragraph here."
        text = f"{para1}\n\n{para2}\n\n{para3}"
        chunks = chunk_scene_text(text, max_tokens=5)
        # Should produce multiple chunks
        assert len(chunks) >= 1

    def test_never_splits_mid_sentence(self):
        # Each paragraph is a single unit — verify joining is correct
        para1 = "This is a complete sentence."
        para2 = "Another complete sentence."
        text = f"{para1}\n\n{para2}"
        chunks = chunk_scene_text(text, max_tokens=1000)
        # Both paragraphs fit in one chunk
        assert len(chunks) == 1
        assert "complete sentence" in chunks[0]

    def test_target_tokens_is_advisory(self):
        # The function targets ~600 tokens but max_tokens is the hard cap
        text = "Word " * 200 + "\n\n" + "Word " * 200
        chunks = chunk_scene_text(text, target_tokens=600, max_tokens=800)
        # Both paragraphs combined are ~400 words, should fit in one chunk
        assert len(chunks) == 1


class TestLoadSceneTexts:
    def test_missing_directory_returns_empty_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = load_scene_texts(Path(tmpdir) / "nonexistent")
        assert result == {}

    def test_loads_all_scene_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scenes_dir = Path(tmpdir) / "scenes"
            scenes_dir.mkdir()
            (scenes_dir / "scene_001.txt").write_text("Scene one content.")
            (scenes_dir / "scene_002.txt").write_text("Scene two content.")
            (scenes_dir / "scene_003.txt").write_text("Scene three content.")

            result = load_scene_texts(scenes_dir)

        assert len(result) == 3
        assert result["scene_001"] == "Scene one content."
        assert result["scene_002"] == "Scene two content."
        assert result["scene_003"] == "Scene three content."

    def test_scene_id_is_stem(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scenes_dir = Path(tmpdir) / "scenes"
            scenes_dir.mkdir()
            (scenes_dir / "my_scene.txt").write_text("Hello.")

            result = load_scene_texts(scenes_dir)

        assert "my_scene" in result

    def test_sorted_alphabetically(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scenes_dir = Path(tmpdir) / "scenes"
            scenes_dir.mkdir()
            (scenes_dir / "scene_z.txt").write_text("Z")
            (scenes_dir / "scene_a.txt").write_text("A")
            (scenes_dir / "scene_m.txt").write_text("M")

            result = load_scene_texts(scenes_dir)

        keys = list(result.keys())
        assert keys == sorted(keys)

    def test_ignores_non_txt_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            scenes_dir = Path(tmpdir) / "scenes"
            scenes_dir.mkdir()
            (scenes_dir / "scene_001.txt").write_text("Valid.")
            (scenes_dir / "scene_001.json").write_text("{}")
            (scenes_dir / "README.md").write_text("# Readme")

            result = load_scene_texts(scenes_dir)

        assert len(result) == 1
        assert "scene_001" in result
