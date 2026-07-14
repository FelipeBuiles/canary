"""Layout-aware regional prompting: schema, LLM pass gating, provider wire format."""

import asyncio
import base64
import hashlib
import json
from dataclasses import replace

import pytest

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
from novel_to_comic.provider_wire import ProviderWireReference, ProviderWireRequest
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

    def test_normalizes_hierarchy_types_and_frame(self):
        layout = PromptLayout(
            width=4096,
            height=2720,
            regions=[
                LayoutRegion(
                    label="person",
                    prompt="standing person",
                    region_type="coarse_detail",
                ),
                LayoutRegion(
                    label="face",
                    prompt="visible face",
                    parent="person",
                    region_type="face",
                    image_region_index=-1,
                ),
            ],
        )
        sanitized = layout.sanitized()
        assert (sanitized.width, sanitized.height) == (4096, 2720)
        assert sanitized.regions[1].parent == "person"
        assert sanitized.regions[1].region_type == "face"
        assert sanitized.regions[1].image_region_index is None

    def test_clears_parent_when_child_is_outside_parent_box(self):
        layout = PromptLayout(regions=[
            LayoutRegion(
                label="person",
                prompt="person",
                bbox=LayoutBbox(x0=0.1, y0=0.1, x1=0.5, y1=0.5),
            ),
            LayoutRegion(
                label="face",
                prompt="face",
                bbox=LayoutBbox(x0=0.4, y0=0.4, x1=0.8, y1=0.8),
                parent="person",
                region_type="face",
            ),
        ])
        assert layout.sanitized().regions[1].parent is None


# ── gating ───────────────────────────────────────────────────────────────────


class TestLayoutPassApplies:
    def test_applies_for_reve_model_when_enabled(self):
        assert layout_pass_applies(Config(image_model="image-reve", layout_prompts_enabled=True))

    def test_applies_for_image_quality_alias_when_enabled(self):
        assert layout_pass_applies(Config(image_model="image-quality", layout_prompts_enabled=True))

    def test_disabled_by_default_for_experimental_rollout(self):
        # The live endpoint is available but still documented as experimental;
        # production rollout remains an explicit config choice.
        assert not layout_pass_applies(Config(image_model="image-reve"))

    def test_skips_non_reve_models(self):
        assert not layout_pass_applies(Config(image_model="image-balanced", layout_prompts_enabled=True))

    def test_skips_when_disabled(self):
        config = Config(image_model="image-reve", layout_prompts_enabled=False)
        assert not layout_pass_applies(config)

    def test_skips_prompt_with_existing_layout(self):
        config = Config(image_model="image-reve", layout_prompts_enabled=True)
        assert not layout_pass_applies(config, _prompt(layout=_layout()))

    def test_ensure_layout_is_noop_for_non_reve(self):
        prompt = _prompt()
        result = asyncio.run(ensure_layout(Config(image_model="image-balanced", layout_prompts_enabled=True), prompt))
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
    @pytest.mark.parametrize("model", ["image-reve", "image-quality", "reve/create"])
    def test_layout_on_reve_picks_layout_provider(self, model: str):
        provider = pick(
            model,
            Config(image_model=model, layout_prompts_enabled=True),
            layout=_layout(),
        )
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


def _wire(*, reference_count: int = 0, prompt: str = "a panel", layout: dict | None = None):
    references = tuple(
        ProviderWireReference(
            index=index,
            source_path=f"ref-{index}.png",
            content_sha256=hashlib.sha256(_PNG_BYTES).hexdigest(),
            role="subject" if index == 0 else "style",
            role_label="subject:Carl" if index == 0 else "style:Selected",
            instruction=(
                "Character identity reference for Carl — match face, hair, build, and wardrobe; "
                "do not copy its pose or background."
                if index == 0
                else "style reference — preserve medium, mark-making and palette; ignore depicted content"
            ),
            provider_binding=str(index),
            entity_id="char_carl" if index == 0 else None,
            appearance_state_id=None,
            authority_scope="full_appearance" if index == 0 else "contextual",
            preserve_facets=("face", "hair", "build") if index == 0 else (),
            ignore_facets=(),
        )
        for index in range(reference_count)
    )
    layout = layout or {
        "prompt": "Carl on a rainy street",
        "normalized_edit_instruction": prompt,
        "width": 4096,
        "height": 2720,
        "regions": [
            {
                "label": "street",
                "prompt": "rain-slick asphalt street at night, neon reflections",
                "bbox": {"x0": 0.0, "y0": 0.3, "x1": 1.0, "y1": 1.0},
                "region_type": "coarse_detail",
            },
            {
                "label": "carl",
                "prompt": "young man with curly dark hair and wire glasses, walking",
                "bbox": {"x0": 0.05, "y0": 0.1, "x1": 0.45, "y1": 0.95},
                "region_type": "coarse_detail",
                **({"image_index": 0} if reference_count else {}),
            },
        ],
    }
    wire = ProviderWireRequest(
        discriminator="canary.provider-wire/1",
        schema_version=1,
        requested_alias="image-reve",
        expected_route="reve",
        configured_provider_model="reve/create",
        prompt_parts=(prompt,),
        references=references,
        width=1024,
        height=683,
        structured_aspect="3:2",
        controls=(),
        compiled_request_sha256="c" * 64,
        execution_fingerprint="",
        layout=layout,
    )
    return replace(wire, execution_fingerprint=wire.recompute_execution_fingerprint())


def _run_provider(monkeypatch, response_payload, *, reference_bytes=None, prompt="a panel", layout=None):
    monkeypatch.setenv("REVE_API_KEY", "test-key")
    monkeypatch.delenv("REVE_API_HOST", raising=False)
    captured = _capture_post(monkeypatch, response_payload)
    provider = ReveLayoutProvider()
    reference_bytes = tuple(reference_bytes or ())
    wire = _wire(reference_count=len(reference_bytes), prompt=prompt, layout=layout)
    result = asyncio.run(provider.generate_wire(
        wire=wire,
        reference_bytes=reference_bytes,
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
    def test_posts_v2_render_layout(self, monkeypatch):
        captured, result = _run_provider(monkeypatch, _ok_response())
        assert captured["url"] == "https://api.reve.com/v2/image/render_layout"
        assert captured["headers"]["Authorization"] == "Bearer test-key"
        payload = captured["payload"]
        assert payload["layout"]["normalized_edit_instruction"] == "a panel"
        assert "instruction" not in payload
        assert "description" not in payload
        assert "aspect_ratio" not in payload
        assert payload["postprocessing"] == [{"process": "fit_image", "max_dim": 2048}]
        labels = [r["label"] for r in payload["layout"]["regions"]]
        assert labels == ["street", "carl"]
        assert payload["layout"]["prompt"] == "Carl on a rainy street"
        assert "references" not in payload
        assert result.image_bytes == _PNG_BYTES
        assert result.provider_request_id == "req_123"

    def test_sends_compound_references_and_region_binding(self, monkeypatch):
        captured, _ = _run_provider(
            monkeypatch, _ok_response(), reference_bytes=[_PNG_BYTES, _PNG_BYTES]
        )
        payload = captured["payload"]
        assert len(payload["references"]) == 2
        assert payload["references"][0]["image"]["data"] == base64.b64encode(_PNG_BYTES).decode("ascii")
        assert payload["references"][0]["prompt"].startswith("Character identity reference for Carl")
        regions = {r["label"]: r for r in payload["layout"]["regions"]}
        assert regions["carl"]["image_index"] == 0
        assert "image_index" not in regions["street"]

    def test_preserves_wire_instruction_without_provider_rewrite(self, monkeypatch):
        prompt = "x" * 5000
        captured, _ = _run_provider(monkeypatch, _ok_response(), prompt=prompt)
        assert captured["payload"]["layout"]["normalized_edit_instruction"] == prompt

    def test_extracts_layout_echo(self, monkeypatch):
        echo = {"regions": [{"label": "carl", "prompt": "p", "bbox": {"x0": 0, "y0": 0, "x1": 0.5, "y1": 1}}]}
        _, result = _run_provider(monkeypatch, _ok_response(layout=echo))
        assert result.layout_echo == echo
        assert "image" not in (result.raw_response or {})
        assert result.raw_response["request_id"] == "req_123"

    def test_content_violation_raises_refusal(self, monkeypatch):
        from novel_to_comic.ai.errors import AIRefusalError

        with pytest.raises(AIRefusalError):
            _run_provider(monkeypatch, _ok_response(content_violation=True))

    def test_missing_api_key_raises(self, monkeypatch):
        monkeypatch.delenv("REVE_API_KEY", raising=False)
        monkeypatch.delenv("REVE_API_TOKEN", raising=False)
        wire = _wire()
        provider = ReveLayoutProvider()
        with pytest.raises(ValueError, match="REVE_API_TOKEN|REVE_API_KEY"):
            asyncio.run(provider.generate_wire(
                wire=wire,
                reference_bytes=(),
                config=Config(),
                event_id="evt",
                metadata={},
            ))

    def test_requires_layout_in_wire(self, monkeypatch):
        monkeypatch.setenv("REVE_API_KEY", "test-key")
        provider = ReveLayoutProvider()
        wire = replace(_wire(), layout=None, execution_fingerprint="")
        wire = replace(wire, execution_fingerprint=wire.recompute_execution_fingerprint())
        with pytest.raises(ValueError, match="layout"):
            asyncio.run(provider.generate_wire(
                wire=wire,
                reference_bytes=(),
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
    captured = _capture_post(monkeypatch, _ok_response(layout=echo))

    output_path = tmp_path / "draw" / "scene_001" / "panel_001.png"
    result = asyncio.run(client.generate_wire_image(
        config=Config(image_model="image-reve", layout_prompts_enabled=True),
        wire=_wire(prompt="a panel"),
        output_path=output_path,
        feature="draw.panel_image",
    ))

    assert captured["url"] == "https://api.reve.com/v2/image/render_layout"
    assert result.value == output_path
    assert output_path.read_bytes() == _PNG_BYTES
    sidecar = artifacts.asset_layout_echo_path(output_path)
    assert json.loads(sidecar.read_text()) == echo


def test_render_layout_failure_falls_back_to_flat_v2_create(monkeypatch, tmp_path):
    from novel_to_comic.ai import client
    from novel_to_comic.ai.providers.base import ProviderRawResult

    monkeypatch.setattr(client, "_insert_event", lambda **kwargs: None)
    monkeypatch.setattr(client, "_finalize_event", lambda **kwargs: None)
    captured: dict = {}

    async def fail_layout(self, **kwargs):
        captured["layout_wire"] = kwargs["wire"]
        raise RuntimeError("render_layout unavailable")

    async def fake_gateway(self, **kwargs):
        captured["fallback_wire"] = kwargs["wire"]
        return ProviderRawResult(
            image_bytes=_PNG_BYTES,
            raw_response={"model": "reve/create"},
        )

    monkeypatch.setattr(ReveLayoutProvider, "generate_wire", fail_layout)
    monkeypatch.setattr(LitellmHttpProvider, "generate_wire", fake_gateway)
    monkeypatch.setattr(
        "novel_to_comic.provider_wire.materialize_wire_references",
        lambda wire: (),
    )

    output_path = tmp_path / "panel.png"
    asyncio.run(client.generate_wire_image(
        config=Config(image_model="image-reve", layout_prompts_enabled=True),
        wire=_wire(prompt="a panel"),
        output_path=output_path,
    ))

    assert captured["layout_wire"].layout is not None
    assert captured["fallback_wire"].layout is None
    assert output_path.read_bytes() == _PNG_BYTES


def test_render_layout_refusal_does_not_fall_back(monkeypatch, tmp_path):
    from novel_to_comic.ai import client
    from novel_to_comic.ai.errors import AIRefusalError

    monkeypatch.setattr(client, "_insert_event", lambda **kwargs: None)
    monkeypatch.setattr(client, "_finalize_event", lambda **kwargs: None)
    called = {"fallback": False}

    async def refuse_layout(self, **kwargs):
        raise AIRefusalError("provider refusal", response_data={"content_violation": True})

    async def fail_gateway(self, **kwargs):
        called["fallback"] = True
        raise AssertionError("content refusals must not be retried through create")

    monkeypatch.setattr(ReveLayoutProvider, "generate_wire", refuse_layout)
    monkeypatch.setattr(LitellmHttpProvider, "generate_wire", fail_gateway)
    monkeypatch.setattr(
        "novel_to_comic.provider_wire.materialize_wire_references",
        lambda wire: (),
    )

    with pytest.raises(AIRefusalError):
        asyncio.run(client.generate_wire_image(
            config=Config(image_model="image-reve", layout_prompts_enabled=True),
            wire=_wire(prompt="a panel"),
            output_path=tmp_path / "panel.png",
        ))
    assert called["fallback"] is False


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
