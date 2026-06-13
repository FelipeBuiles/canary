from pathlib import Path

from novel_to_comic.assembly.lettering_style import (
    lettering_style_path,
    load_lettering_style,
    save_lettering_style,
)
from novel_to_comic.models.lettering import LetteringStyle


def test_default_when_missing(tmp_path: Path):
    ls = load_lettering_style(tmp_path)
    assert ls.theme == "default"
    assert ls.font_pair == "golden-age"
    assert ls.mode == "auto"


def test_round_trip(tmp_path: Path):
    ls = LetteringStyle(
        mode="auto",
        theme="noir",
        font_pair="horror",
        vars={"--bubble-bg": "#F0F0F0"},
        label="Noir Lettering",
        rationale="Cream captions against heavy inks.",
        source="ai",
        style_template_hash="abc123",
    )
    save_lettering_style(tmp_path, ls)
    assert lettering_style_path(tmp_path).exists()

    loaded = load_lettering_style(tmp_path)
    assert loaded.theme == "noir"
    assert loaded.font_pair == "horror"
    assert loaded.vars["--bubble-bg"] == "#F0F0F0"
    assert loaded.source == "ai"
