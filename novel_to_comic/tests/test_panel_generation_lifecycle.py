"""Slice 11 panel lifecycle regressions.

These tests deliberately stop at the provider-wire/frozen-request boundary:
they never make a paid provider call.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from novel_to_comic.config import Config
from novel_to_comic.image_models import GATEWAY_IMAGE_REVE, image_model_profile
from novel_to_comic.image_references import AuthorityScope, ReferenceAsset, ReferencePlan
from novel_to_comic.models.prompt import ImagePrompt, PromptSubject
from novel_to_comic.panel_generation import (
    compile_panel_request,
    estimate_panel_request,
    panel_provenance,
    submit_panel_request,
)


def _prompt() -> ImagePrompt:
    return ImagePrompt(
        prompt_version=23,
        planned_panel_id="scene_001:panel_001",
        scene_id="scene_001",
        panel_number=1,
        full_prompt="A sentinel scene.",
        composition="medium shot",
        subjects=[
            PromptSubject(
                character_id="char_001",
                name="Milla",
                identity="SENTINEL CHARACTER ANCHOR",
                action="standing",
                position="center",
            )
        ],
        width=768,
        height=1344,
        generation_width=768,
        generation_height=1344,
        generation_aspect_ratio=2 / 3,
        steps=20,
    )


def _plan(tmp_path: Path) -> ReferencePlan:
    ref = tmp_path / "refs" / "char_001" / "front.png"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_bytes(b"selected reference bytes")
    import hashlib

    return ReferencePlan(
        expected_route=image_model_profile(GATEWAY_IMAGE_REVE).route,
        selected=(
            ReferenceAsset(
                path=ref,
                role="subject",
                entity_id="char_001",
                appearance_state_id=None,
                authority_scope=AuthorityScope.FULL_APPEARANCE,
                preserve_facets=("face", "hair", "build", "wardrobe", "anatomy"),
                ignore_facets=(),
                pose="front",
                content_sha256=hashlib.sha256(ref.read_bytes()).hexdigest(),
                lineage_parent_sha256=None,
                label="Milla",
            ),
        ),
        dropped=(),
        selection_fingerprint="a" * 64,
    )


def test_compile_panel_request_is_one_compiled_and_wire_projection(tmp_path: Path):
    config = Config(image_model=GATEWAY_IMAGE_REVE, style_template="ink")
    request = compile_panel_request(config, tmp_path, _prompt(), reference_plan=_plan(tmp_path))

    assert request.compiled.final_prompt == request.wire.prompt_parts[0].replace(
        "<img>0</img>", "Reference 0"
    ) or request.compiled.final_prompt == request.wire.prompt_parts[0]
    assert request.wire.execution_fingerprint == request.wire.recompute_execution_fingerprint()
    assert request.wire.references[0].content_sha256 == request.reference_plan.selected[0].content_sha256


def test_unprepared_estimate_is_provisional_without_visual_brief_or_layout_call(
    tmp_path: Path, monkeypatch
):
    config = Config(image_model=GATEWAY_IMAGE_REVE, style_template="ink")

    async def fail_if_called(*args, **kwargs):  # pragma: no cover - assertion helper
        raise AssertionError("estimate must not prepare a prompt")

    monkeypatch.setattr("novel_to_comic.panel_generation.prepare_panel_prompt", fail_if_called)
    estimate = estimate_panel_request(
        config,
        tmp_path,
        _prompt(),
        reference_plan=_plan(tmp_path),
        prepared=False,
    )

    assert estimate.status == "provisional"
    assert estimate.execution_fingerprint is None
    assert estimate.cost_usd >= 0


def test_prepared_estimate_exposes_execution_fingerprint(tmp_path: Path):
    config = Config(image_model=GATEWAY_IMAGE_REVE, style_template="ink")
    estimate = estimate_panel_request(
        config,
        tmp_path,
        _prompt(),
        reference_plan=_plan(tmp_path),
        prepared=True,
    )

    assert estimate.status == "prepared"
    assert estimate.execution_fingerprint
    assert estimate.wire is not None


def test_explicit_experiment_input_changes_attributable_wire_identity(tmp_path: Path):
    config = Config(image_model=GATEWAY_IMAGE_REVE, style_template="ink")
    base = compile_panel_request(config, tmp_path, _prompt(), reference_plan=_plan(tmp_path))
    variant = compile_panel_request(
        config,
        tmp_path,
        _prompt(),
        reference_plan=_plan(tmp_path),
        experiment_inputs={"variant": "B"},
    )

    assert base.wire.execution_fingerprint != variant.wire.execution_fingerprint


def test_panel_provenance_hash_excludes_timestamps_but_keeps_diagnostics():
    base = panel_provenance(
        compiled_sha256="c" * 64,
        wire=SimpleNamespace(
            execution_fingerprint="e" * 64,
            requested_alias="image-reve",
            expected_route="reve",
            configured_provider_model="reve/create",
            width=768,
            height=1344,
            references=(),
        ),
        reference_plan=SimpleNamespace(selected=(), dropped=(), warnings=("warn",)),
        request_id="request-1",
        actual_width=768,
        actual_height=1344,
        started_at="2026-07-12T00:00:00+00:00",
    )
    changed_time = panel_provenance(
        compiled_sha256="c" * 64,
        wire=SimpleNamespace(
            execution_fingerprint="e" * 64,
            requested_alias="image-reve",
            expected_route="reve",
            configured_provider_model="reve/create",
            width=768,
            height=1344,
            references=(),
        ),
        reference_plan=SimpleNamespace(selected=(), dropped=(), warnings=("warn",)),
        request_id="request-1",
        actual_width=768,
        actual_height=1344,
        started_at="2026-07-12T01:00:00+00:00",
    )
    assert base["provenance_record_hash"] == changed_time["provenance_record_hash"]
    assert base["warnings"] == ["warn"]


def test_submit_panel_request_freezes_before_execution(tmp_path: Path, monkeypatch):
    config = Config(image_model=GATEWAY_IMAGE_REVE, style_template="ink")
    request = compile_panel_request(config, tmp_path, _prompt(), reference_plan=_plan(tmp_path))
    calls: list[str] = []

    async def fake_execute(**kwargs):
        calls.append(kwargs["request_id"])
        return SimpleNamespace(value=kwargs["output_path"], usage=None)

    monkeypatch.setattr("novel_to_comic.panel_generation.execute_frozen_request", fake_execute)
    submission = asyncio.run(
        submit_panel_request(
            config=config,
            project_dir=tmp_path,
            request=request,
            output_path=tmp_path / "draw" / "scene_001" / "panel_001.png",
        )
    )

    assert submission.request_id
    assert submission.execution_fingerprint == request.wire.execution_fingerprint
    assert calls == [submission.request_id]
    manifest = (tmp_path / "requests" / submission.request_id / "manifest.json").read_text()
    assert request.wire.execution_fingerprint in manifest
