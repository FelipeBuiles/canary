import asyncio
import json

import pytest

from novel_to_comic.config import Config
from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.image_models import image_model_profile_for_config
from novel_to_comic.image_references import ReferencePlan
from novel_to_comic.models.prompt import PromptAnchor
from novel_to_comic.non_panel_generation import (
    AbstractStyleProofInput,
    CanonicalLocationPlateInput,
    compile_non_panel_request,
    common_image_provenance,
    submit_non_panel_request,
)
from novel_to_comic.panel_versions import record_asset_version, restore_asset_version
from novel_to_comic.usage import ApiResult


def _empty_plan(config: Config) -> ReferencePlan:
    profile = image_model_profile_for_config(config)
    return ReferencePlan(
        expected_route=profile.route,
        selected=(),
        dropped=(),
        selection_fingerprint="0" * 64,
    )


def test_non_panel_prompt_has_no_panel_identity_fields():
    prompt = GenerationPromptInput(
        visual_brief="An abstract field of cobalt and warm light.",
        width=819,
        height=1024,
        generation_shape="portrait",
    )

    assert not hasattr(prompt, "scene_id")
    assert not hasattr(prompt, "panel_number")


def test_abstract_style_proof_does_not_invent_entity_anchor():
    config = Config(image_model="image-balanced", style_template="Woodblock print")
    request = compile_non_panel_request(
        config,
        AbstractStyleProofInput(
            asset_identity="style_sample:1",
            prompt=GenerationPromptInput(
                visual_brief="A quiet abstract arrangement of indigo and ochre shapes.",
                width=819,
                height=1024,
                generation_shape="portrait",
            ),
            selected_style_text=config.style_template,
        ),
        reference_plan=_empty_plan(config),
    )

    assert request.compiled.protected_anchors == ()
    assert "Mara" not in request.compiled.final_prompt
    assert "LOCATION-SENTINEL" not in request.compiled.final_prompt
    assert request.wire.width == 819
    assert request.wire.height == 1024


def test_entity_specific_style_proof_preserves_supplied_anchor_verbatim():
    config = Config(image_model="image-balanced", style_template="Ink wash")
    sentinel = "CHARACTER-SENTINEL: cobalt eyes, brass prosthetic hand, scarlet scarf"
    request = compile_non_panel_request(
        config,
        AbstractStyleProofInput(
            asset_identity="style_sample:entity:char_001",
            prompt=GenerationPromptInput(
                anchors=(PromptAnchor(
                    kind="character",
                    entity_id="char_001",
                    name="Mara",
                    text=sentinel,
                ),),
                visual_brief="A three-quarter figure against a quiet field.",
                width=819,
                height=1024,
                generation_shape="portrait",
            ),
            selected_style_text=config.style_template,
        ),
        reference_plan=_empty_plan(config),
    )

    assert sentinel in request.compiled.final_prompt
    assert request.compiled.protected_anchors[0].text == sentinel


def test_location_plate_uses_verified_landscape_geometry():
    config = Config(image_model="image-balanced", style_template="Ink wash")
    request = compile_non_panel_request(
        config,
        CanonicalLocationPlateInput(
            asset_identity="location_plate:loc_001",
            prompt=GenerationPromptInput(
                anchors=(PromptAnchor(
                    kind="location",
                    entity_id="loc_001",
                    name="Lake House",
                    text="LOCATION-SENTINEL: stone house beside a flooded lake",
                ),),
                visual_brief="A clean wide environment design plate.",
                width=1344,
                height=768,
                generation_shape="landscape",
            ),
            selected_style_text=config.style_template,
        ),
        reference_plan=_empty_plan(config),
    )

    assert (request.wire.width, request.wire.height) == (1344, 768)
    assert "LOCATION-SENTINEL" in request.wire.prompt_parts[0]


def test_common_non_panel_provenance_has_asset_identity_and_wire_fields():
    config = Config(image_model="image-balanced")
    request = compile_non_panel_request(
        config,
        AbstractStyleProofInput(
            asset_identity="style_sample:1",
            prompt=GenerationPromptInput(
                visual_brief="abstract color field",
                width=819,
                height=1024,
                generation_shape="portrait",
            ),
            selected_style_text="Ink wash",
        ),
        reference_plan=_empty_plan(config),
    )
    record = common_image_provenance(
        asset_kind=request.input.asset_kind,
        asset_identity=request.input.asset_identity,
        compiled_sha256=request.compiled.compiled_request_sha256,
        prompt_source_sha256=request.compiled.prompt_source_sha256,
        wire=request.wire,
        reference_plan=request.reference_plan,
        request_id="request-1",
        actual_width=800,
        actual_height=1000,
        actual_provider_model="provider/model-v2",
        provider_request_id="provider-request-1",
        cost_usd=0.12,
    )

    assert record["asset_kind"] == "style_sample"
    assert record["asset_identity"] == "style_sample:1"
    assert record["compiled_request_sha256"] == request.compiled.compiled_request_sha256
    assert record["execution_fingerprint"] == request.wire.execution_fingerprint
    assert record["actual_dimensions"] == {"width": 800, "height": 1000}
    assert len(record["provenance_record_hash"]) == 64


def test_non_panel_submission_freezes_before_transport_and_persists_provenance(tmp_path, monkeypatch):
    config = Config(image_model="image-balanced")
    request = compile_non_panel_request(
        config,
        AbstractStyleProofInput(
            asset_identity="style_sample:1",
            prompt=GenerationPromptInput(
                visual_brief="A deterministic proof.", width=819, height=1024,
                generation_shape="portrait",
            ),
            selected_style_text="Ink wash",
        ),
        reference_plan=_empty_plan(config),
    )
    output_path = tmp_path / "samples" / "style_1.png"

    async def fake_execute_frozen_request(*, project_dir, request_id, config, output_path, feature):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"image-bytes")
        return ApiResult(value=output_path)

    monkeypatch.setattr(
        "novel_to_comic.non_panel_generation.execute_frozen_request",
        fake_execute_frozen_request,
    )
    submission = asyncio.run(submit_non_panel_request(
        config=config, project_dir=tmp_path, request=request,
        output_path=output_path, feature="style.sample", kind="style_sample",
    ))

    assert submission.request_id
    assert (tmp_path / "requests" / submission.request_id / "manifest.json").exists()
    metadata = json.loads(output_path.with_suffix(".png.meta.json").read_text())
    assert metadata["provenance"]["request_id"] == submission.request_id
    assert metadata["provenance"]["compiled_request_sha256"] == request.compiled_request_sha256
    assert metadata["provenance"]["execution_fingerprint"] == request.execution_fingerprint


def test_non_panel_failure_persists_request_provenance_without_provider_result(tmp_path, monkeypatch):
    config = Config(image_model="image-balanced")
    request = compile_non_panel_request(
        config,
        AbstractStyleProofInput(
            asset_identity="style_sample:failed",
            prompt=GenerationPromptInput(
                visual_brief="A deterministic proof.", width=819, height=1024,
                generation_shape="portrait",
            ),
        ),
        reference_plan=_empty_plan(config),
    )
    output_path = tmp_path / "samples" / "failed.png"

    async def fake_execute_frozen_request(**kwargs):
        raise RuntimeError(f"provider failed for {kwargs['output_path']}")

    monkeypatch.setattr(
        "novel_to_comic.non_panel_generation.execute_frozen_request",
        fake_execute_frozen_request,
    )
    with pytest.raises(RuntimeError):
        asyncio.run(submit_non_panel_request(
            config=config, project_dir=tmp_path, request=request,
            output_path=output_path, feature="style.sample", kind="style_sample",
        ))

    failure = json.loads(output_path.with_suffix(".png.failure.json").read_text())
    assert failure["provenance"]["request_id"]
    assert failure["provenance"]["compiled_request_sha256"] == request.compiled_request_sha256
    assert str(tmp_path) not in json.dumps(failure)


def test_asset_restore_only_reactivates_archived_bytes_and_metadata(tmp_path, monkeypatch):
    output_path = tmp_path / "refs" / "props" / "prop_001" / "ref.png"
    output_path.parent.mkdir(parents=True)
    output_path.write_bytes(b"archived-image")
    output_path.with_suffix(".png.meta.json").write_text(json.dumps({
        "kind": "prop_ref",
        "provenance": {"request_id": "original-request", "execution_fingerprint": "f" * 64},
    }))
    record_asset_version(output_path, tmp_path, reason="before_regenerate")
    output_path.write_bytes(b"new-image")
    output_path.with_suffix(".png.meta.json").write_text(json.dumps({"kind": "prop_ref"}))

    def _paid_call(*args, **kwargs):
        raise AssertionError("restore must not compile, freeze, or call a provider")

    monkeypatch.setattr("novel_to_comic.non_panel_generation.compile_non_panel_request", _paid_call)
    monkeypatch.setattr("novel_to_comic.non_panel_generation.submit_frozen_request", _paid_call)
    monkeypatch.setattr("novel_to_comic.non_panel_generation.execute_frozen_request", _paid_call)

    restore_asset_version(output_path, tmp_path, 1)

    assert output_path.read_bytes() == b"archived-image"
    restored = json.loads(output_path.with_suffix(".png.meta.json").read_text())
    assert restored["provenance"]["request_id"] == "original-request"
