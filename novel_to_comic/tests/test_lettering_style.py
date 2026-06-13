import asyncio
import types

import pytest
from fastapi import HTTPException

from novel_to_comic.assembly.lettering_style import (
    lettering_style_path,
    load_lettering_style,
    save_lettering_style,
)
from novel_to_comic.models.lettering import LetteringStyle
from novel_to_comic.server.routers import pages as P


# ── Model + persistence ───────────────────────────────────────────────────


def test_default_when_missing(tmp_path):
    ls = load_lettering_style(tmp_path)
    assert ls.theme == "default"
    assert ls.font_pair == "golden-age"
    assert ls.mode == "auto"


def test_round_trip(tmp_path):
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


# ── Fallback keyword mapping + hashing ────────────────────────────────────


def test_fallback_theme_and_pair():
    assert P._fallback_theme_and_pair("gritty noir detective") == ("noir", "golden-age")
    assert P._fallback_theme_and_pair("creepy gothic horror") == ("noir", "horror")
    assert P._fallback_theme_and_pair("shonen manga ink") == ("manga", "manga")
    assert P._fallback_theme_and_pair("retro pulp poster") == ("vintage", "golden-age")
    assert P._fallback_theme_and_pair("soft watercolor painterly") == ("painted", "painterly")
    assert P._fallback_theme_and_pair("cute cartoon for kids") == ("default", "kids")
    assert P._fallback_theme_and_pair("neon cyberpunk future") == ("default", "sci-fi")
    assert P._fallback_theme_and_pair("") == ("default", "golden-age")


def test_style_hash():
    h = P._style_hash("abc")
    assert len(h) == 16
    assert h == P._style_hash("abc")
    assert h != P._style_hash("abd")
    assert P._style_hash("") == P._style_hash(None)  # tolerant of empty/None


# ── AI generation: validation + fallback ──────────────────────────────────


def _cfg(style_template: str):
    return types.SimpleNamespace(
        style_template=style_template,
        effective_prompt_model=lambda: "test-model",
    )


def test_generate_validates_unknown_ids(monkeypatch):
    async def fake_generate_json(**kwargs):
        return types.SimpleNamespace(
            value={
                "theme": "bogus",
                "font_pair": "bogus",
                "vars": {"--bubble-bg": "#FFFFFF", "--evil": "url(x)"},
                "label": "X",
                "rationale": "Y",
            },
            usage=None,
        )

    monkeypatch.setattr("novel_to_comic.clients.text.generate_json", fake_generate_json)
    out, usage = asyncio.run(P._generate_lettering_style(_cfg("plain manga ink")))
    # Unknown theme/font_pair fall back via keyword; vars sanitized.
    assert out["theme"] == "manga"
    assert out["font_pair"] == "manga"
    assert out["source"] == "ai"
    assert out["vars"]["--bubble-bg"] == "#FFFFFF"
    assert "--evil" not in out["vars"]


def test_generate_keeps_valid_ids(monkeypatch):
    async def fake_generate_json(**kwargs):
        return types.SimpleNamespace(
            value={
                "theme": "noir",
                "font_pair": "horror",
                "vars": {},
                "label": "Noir Lettering",
                "rationale": "Pale captions on heavy ink.",
            },
            usage=None,
        )

    monkeypatch.setattr("novel_to_comic.clients.text.generate_json", fake_generate_json)
    out, _ = asyncio.run(P._generate_lettering_style(_cfg("anything")))
    assert out["theme"] == "noir"
    assert out["font_pair"] == "horror"
    assert out["label"] == "Noir Lettering"


def test_generate_fallback_on_error(monkeypatch):
    async def boom(**kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr("novel_to_comic.clients.text.generate_json", boom)
    out, usage = asyncio.run(P._generate_lettering_style(_cfg("manga ink")))
    assert out["source"] == "fallback"
    assert out["theme"] == "manga"
    assert out["font_pair"] == "manga"
    assert usage is None


# ── Preset endpoint (no AI) ───────────────────────────────────────────────


def test_set_lettering_preset(tmp_path):
    cfg = _cfg("anything")
    out = P.set_lettering_style({"mode": "preset", "preset": "noir"}, project=(tmp_path, cfg, None))
    assert out["mode"] == "preset"
    assert out["theme"] == "noir"
    assert out["font_pair"] == "golden-age"
    assert out["source"] == "preset"
    assert load_lettering_style(tmp_path).preset == "noir"


def test_set_lettering_preset_invalid(tmp_path):
    cfg = _cfg("x")
    with pytest.raises(HTTPException):
        P.set_lettering_style({"mode": "preset", "preset": "bogus"}, project=(tmp_path, cfg, None))
