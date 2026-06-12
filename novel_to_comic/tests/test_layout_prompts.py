"""Layout-aware regional prompting: schema, LLM pass gating, provider wire format."""

import asyncio
import base64
import json

import pytest

from novel_to_comic.ai.providers.base import RefImage
from novel_to_comic.ai.providers.litellm_http import LitellmHttpProvider
from novel_to_comic.ai.providers.reve_layout import ReveLayoutProvider
from novel_to_comic.ai.providers.selector import pick
from novel_to_comic.config import Config
from novel_to_comic.models.prompt import (
    ImagePrompt,
    LayoutBbox,
    LayoutRegion,
    PromptLayout,
)
from novel_to_comic.prompt_assembly import (
    ensure_layout,
    generate_layout,
    layout_pass_applies,
)

_PNG_BYTES = b"\x89PNG\r\n\x1a\nfakepng"


def _prompt(**overrides) -> ImagePrompt:
    base = dict(
        scene_id="scene_001",
        panel_number=1,
        composition="wide shot, eye-level camera",
        setting="rainy street at night",
        subjects=[
            {
                "character_id": "char_carl",
                "name": "Carl",
                "identity": "young man, curly dark hair, wire glasses",
                "position": "left foreground",
            }
        ],
        width=1024,
        height=683,
        steps=4,
    )
    base.update(overrides)
    return ImagePrompt(**base)


def _layout() -> PromptLayout:
    return PromptLayout(
        prompt="Carl on a rainy street",
        regions=[
            LayoutRegion(
                label="street",
                prompt="rain-slick asphalt street at night, neon reflections",
                bbox=LayoutBbox(x0=0.0, y0=0.3, x1=1.0, y1=1.0),
            ),
            LayoutRegion(
                label="carl",
                prompt="young man with curly dark hair and wire glasses, walking",
                bbox=LayoutBbox(x0=0.05, y0=0.1, x1=0.45, y1=0.95),
                reference_key="char_carl",
            ),
        ],
    )


# ── schema sanitization ──────────────────────────────────────────────────────


class TestPromptLayoutSanitized:
    def test_clamps_out_of_range_boxes(self):
        layout = PromptLayout(regions=[
            LayoutRegion(label="a", prompt="x", bbox=LayoutBbox(x0=-0.5, y0=0.0, x1=1.7, y1=0.8)),
        ])
        bbox = layout.sanitized().regions[0].bbox
        assert (bbox.x0, bbox.y0, bbox.x1, bbox.y1) == (0.0, 0.0, 1.0, 0.8)

    def test_orders_swapped_corners(self):
        layout = PromptLayout(regions=[
            LayoutRegion(label="a", prompt="x", bbox=LayoutBbox(x0=0.9, y0=0.8, x1=0.1, y1=0.2)),
        ])
        bbox = layout.sanitized().regions[0].bbox
        assert (bbox.x0, bbox.y0, bbox.x1, bbox.y1) == (0.1, 0.2, 0.9, 0.8)

    def test_drops_degenerate_empty_and_blank_regions(self):
        layout = PromptLayout(regions=[
            LayoutRegion(label="dot", prompt="x", bbox=LayoutBbox(x0=0.5, y0=0.5, x1=0.5, y1=0.9)),
            LayoutRegion(label="", prompt="x"),
            LayoutRegion(label="ok", prompt="   "),
            LayoutRegion(label="kept", prompt="visible thing"),
        ])
        regions = layout.sanitized().regions
        assert [r.label for r in regions] == ["kept"]

    def test_deduplicates_labels(self):
        layout = PromptLayout(regions=[
            LayoutRegion(label="face", prompt="one"),
            LayoutRegion(label="face", prompt="two"),
        ])
        assert [r.label for r in layout.sanitized().regions] == ["face", "face_2"]

    def test_preserves_reference_key(self):
        sanitized = _layout().sanitized()
        assert sanitized.regions[1].reference_key == "char_carl"


# ── gating ───────────────────────────────────────────────────────────────────


class TestLayoutPassApplies:
    def test_applies_for_reve_model(self):
        assert layout_pass_applies(Config(image_model="image-reve"))

    def test_applies_for_image_quality_alias(self):
        assert layout_pass_applies(Config(image_model="image-quality"))

    def test_skips_non_reve_models(self):
        assert not layout_pass_applies(Config(image_model="image-balanced"))

    def test_skips_when_disabled(self):
        config = Config(image_model="image-reve", layout_prompts_enabled=False)
        assert not layout_pass_applies(config)

    def test_skips_prompt_with_existing_layout(self):
        config = Config(image_model="image-reve")
        assert not layout_pass_applies(config, _prompt(layout=_layout()))

    def test_ensure_layout_is_noop_for_non_reve(self):
        prompt = _prompt()
        result = asyncio.run(ensure_layout(Config(image_model="image-balanced"), prompt))
        assert result is prompt


# ── LLM pass output handling ─────────────────────────────────────────────────


class TestGenerateLayout:
    def _run(self, monkeypatch, value, *, raises=None):
        async def fake_structured(**kwargs):
            if raises is not None:
                raise raises
            from novel_to_comic.usage import ApiResult
            return ApiResult(value=value, usage=None)

        monkeypatch.setattr(
            "novel_to_comic.ai.client.generate_structured_object", fake_structured
        )
        return asyncio.run(generate_layout(Config(image_model="image-reve"), _prompt()))

    def test_parses_and_sanitizes_llm_output(self, monkeypatch):
        layout = self._run(monkeypatch, {
            "prompt": "scene",
            "regions": [
                {"label": "bg", "prompt": "street", "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1.4}},
                {"label": "carl", "prompt": "the man", "bbox": {"x0": 0.1, "y0": 0.1, "x1": 0.5, "y1": 0.9},
                 "reference_key": "char_carl"},
            ],
        })
        assert layout is not None
        assert [r.label for r in layout.regions] == ["bg", "carl"]
        assert layout.regions[0].bbox.y1 == 1.0
        assert layout.regions[1].reference_key == "char_carl"

    def test_rejects_fewer_than_two_usable_regions(self, monkeypatch):
        layout = self._run(monkeypatch, {
            "regions": [
                {"label": "only", "prompt": "thing", "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1}},
                {"label": "broken", "prompt": "", "bbox": {"x0": 0, "y0": 0, "x1": 1, "y1": 1}},
            ],
        })
        assert layout is None

    def test_returns_none_on_llm_failure(self, monkeypatch):
        assert self._run(monkeypatch, None, raises=RuntimeError("gateway down")) is None


# ── provider selection ───────────────────────────────────────────────────────


class TestSelector:
    def test_layout_on_reve_picks_layout_provider(self):
        provider = pick("image-reve", Config(image_model="image-reve"), layout=_layout())
        assert isinstance(provider, ReveLayoutProvider)

    def test_layout_on_non_reve_stays_on_gateway(self):
        provider = pick("image-balanced", Config(), layout=_layout())
        assert isinstance(provider, LitellmHttpProvider)

    def test_no_layout_stays_on_gateway_even_for_reve(self):
        provider = pick("image-reve", Config(image_model="image-reve"), layout=None)
        assert isinstance(provider, LitellmHttpProvider)

    def test_empty_layout_stays_on_gateway(self):
        provider = pick("image-reve", Config(image_model="image-reve"), layout=PromptLayout())
        assert isinstance(provider, LitellmHttpProvider)


# ── provider wire format ─────────────────────────────────────────────────────


class _MockResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.headers = {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _capture_post(monkeypatch, payload: dict):
    captured: dict = {}

    async def fake_post(client, url, headers=None, json=None, **kwargs):
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = json
        return _MockResponse(payload)

    monkeypatch.setattr("httpx.AsyncClient.post", fake_post)
    return captured


def _run_provider(monkeypatch, tmp_path, response_payload, *, refs=None, prompt="a panel"):
    monkeypatch.setenv("REVE_API_KEY", "test-key")
    monkeypatch.delenv("REVE_API_HOST", raising=False)
    captured = _capture_post(monkeypatch, response_payload)
    provider = ReveLayoutProvider()
    params = provider.request_params(
        model_alias="image-reve", width=1024, height=683, config=Config(),
    )
    params["layout"] = _layout().model_dump()
    result = asyncio.run(provider.generate(
        model_alias="image-reve",
        prompt=prompt,
        refs=refs or [],
        width=1024,
        height=683,
        params=params,
        config=Config(),
        event_id="evt",
        metadata={},
    ))
    return captured, result


def _ok_response(**extra) -> dict:
    return {
        "image": base64.b64encode(_PNG_BYTES).decode("ascii"),
        "request_id": "req_123",
        "credits_used": 4,
        "credits_remaining": 96,
        "version": "latest",
        **extra,
    }


class TestReveLayoutProvider:
    def test_posts_v2_create_with_description(self, monkeypatch, tmp_path):
        captured, result = _run_provider(monkeypatch, tmp_path, _ok_response())
        assert captured["url"] == "https://api.reve.com/v2/image/create"
        assert captured["headers"]["Authorization"] == "Bearer test-key"
        payload = captured["payload"]
        assert payload["instruction"] == "a panel"
        assert payload["aspect_ratio"] == "3:2"
        labels = [r["label"] for r in payload["description"]["regions"]]
        assert labels == ["street", "carl"]
        assert payload["description"]["prompt"] == "Carl on a rainy street"
        assert "references" not in payload
        assert result.image_bytes == _PNG_BYTES
        assert result.provider_request_id == "req_123"

    def test_binds_character_reference_to_region(self, monkeypatch, tmp_path):
        char_ref = tmp_path / "refs" / "char_carl" / "front.png"
        char_ref.parent.mkdir(parents=True)
        char_ref.write_bytes(_PNG_BYTES)
        style_ref = tmp_path / "style.png"
        style_ref.write_bytes(_PNG_BYTES)
        refs = [
            # Style listed first on purpose — upload order must put subject first.
            RefImage(path=style_ref, role="style", label="selected style"),
            RefImage(path=char_ref, role="subject", label="Carl"),
        ]
        captured, _ = _run_provider(monkeypatch, tmp_path, _ok_response(), refs=refs)
        payload = captured["payload"]
        assert len(payload["references"]) == 2
        assert payload["references"][0]["prompt"] == "Character reference for Carl."
        regions = {r["label"]: r for r in payload["description"]["regions"]}
        assert regions["carl"]["image_index"] == 0
        assert "image_index" not in regions["street"]

    def test_truncates_instruction_to_4000_chars(self, monkeypatch, tmp_path):
        captured, _ = _run_provider(
            monkeypatch, tmp_path, _ok_response(), prompt="x" * 5000,
        )
        assert len(captured["payload"]["instruction"]) == 4000

    def test_extracts_layout_echo(self, monkeypatch, tmp_path):
        echo = {"regions": [{"label": "carl", "prompt": "p", "bbox": {"x0": 0, "y0": 0, "x1": 0.5, "y1": 1}}]}
        _, result = _run_provider(monkeypatch, tmp_path, _ok_response(description=echo))
        assert result.layout_echo == echo
        assert "image" not in (result.raw_response or {})
        assert result.raw_response["request_id"] == "req_123"

    def test_content_violation_raises_refusal(self, monkeypatch, tmp_path):
        from novel_to_comic.ai.errors import AIRefusalError

        with pytest.raises(AIRefusalError):
            _run_provider(monkeypatch, tmp_path, _ok_response(content_violation=True))

    def test_missing_api_key_raises(self, monkeypatch, tmp_path):
        monkeypatch.delenv("REVE_API_KEY", raising=False)
        monkeypatch.delenv("REVE_API_TOKEN", raising=False)
        _capture_post(monkeypatch, _ok_response())
        provider = ReveLayoutProvider()
        with pytest.raises(ValueError, match="REVE_API_KEY"):
            asyncio.run(provider.generate(
                model_alias="image-reve",
                prompt="p",
                refs=[],
                width=1024,
                height=683,
                params={"layout": _layout().model_dump()},
                config=Config(),
                event_id="evt",
                metadata={},
            ))

    def test_requires_layout_in_params(self, monkeypatch, tmp_path):
        monkeypatch.setenv("REVE_API_KEY", "test-key")
        provider = ReveLayoutProvider()
        with pytest.raises(ValueError, match="layout"):
            asyncio.run(provider.generate(
                model_alias="image-reve",
                prompt="p",
                refs=[],
                width=1024,
                height=683,
                params={},
                config=Config(),
                event_id="evt",
                metadata={},
            ))


# ── end-to-end client wiring ─────────────────────────────────────────────────


def test_generate_image_with_layout_hits_v2_and_writes_echo_sidecar(monkeypatch, tmp_path):
    from novel_to_comic import artifacts
    from novel_to_comic.ai import client

    monkeypatch.setenv("REVE_API_KEY", "test-key")
    monkeypatch.delenv("REVE_API_HOST", raising=False)
    monkeypatch.setattr(client, "_insert_event", lambda **kwargs: None)
    monkeypatch.setattr(client, "_finalize_event", lambda **kwargs: None)
    echo = {"regions": [{"label": "carl", "prompt": "p", "bbox": {"x0": 0, "y0": 0, "x1": 0.5, "y1": 1}}]}
    captured = _capture_post(monkeypatch, _ok_response(description=echo))

    output_path = tmp_path / "draw" / "scene_001" / "panel_001.png"
    result = asyncio.run(client.generate_image(
        config=Config(image_model="image-reve"),
        model="image-reve",
        prompt="a panel",
        output_path=output_path,
        width=1024,
        height=683,
        layout=_layout(),
        feature="draw.panel_image",
    ))

    assert captured["url"] == "https://api.reve.com/v2/image/create"
    assert result.value == output_path
    assert output_path.read_bytes() == _PNG_BYTES
    sidecar = artifacts.asset_layout_echo_path(output_path)
    assert json.loads(sidecar.read_text()) == echo


# ── prompt JSON round-trip ───────────────────────────────────────────────────


def test_image_prompt_layout_round_trip():
    prompt = _prompt(layout=_layout())
    parsed = ImagePrompt.model_validate_json(prompt.model_dump_json())
    assert parsed.layout is not None
    assert [r.label for r in parsed.layout.regions] == ["street", "carl"]
    assert parsed.layout.regions[1].bbox.x1 == 0.45


def test_image_prompt_without_layout_still_parses():
    raw = json.loads(_prompt().model_dump_json())
    raw.pop("layout", None)
    parsed = ImagePrompt.model_validate(raw)
    assert parsed.layout is None
