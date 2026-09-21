import asyncio
import json

import pytest

from novel_to_comic.config import Config
from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.image_models import image_model_profile_for_config
from novel_to_comic.image_references import ReferencePlan
from novel_to_comic.models.generation import PromptAnchor
from novel_to_comic.asset_generation import (
    AbstractStyleProofInput,
    CanonicalLocationPlateInput,
    compile_non_panel_request,
    common_image_provenance,
    submit_non_panel_request,
)
from novel_to_comic.asset_versions import record_asset_version, restore_asset_version
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
    config = Config(image_model="image-gemini-pro", style_template="Woodblock print")
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
    config = Config(image_model="image-gemini-pro", style_template="Ink wash")
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
    config = Config(image_model="image-gemini-pro", style_template="Ink wash")
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


def test_non_page_style_omits_production_contract_but_proof_retains_it():
    from novel_to_comic.asset_generation import PropReferenceInput
    from novel_to_comic.style_contract import page_style_template, LETTERING_MARKER, FRAMING_MARKER

    config = Config(image_model="image-gemini-pro")
    style = page_style_template("Watercolor rendering")
    for input_type, page in ((PropReferenceInput, False), (AbstractStyleProofInput, True)):
        request = compile_non_panel_request(config, input_type(
            asset_identity="style-scope",
            prompt=GenerationPromptInput(constraints="No text, labels, or captions."),
            selected_style_text=style,
        ))
        rendered = request.compiled.final_prompt
        assert (LETTERING_MARKER in rendered) is page
        assert (FRAMING_MARKER in rendered) is page
        assert "No text, labels, or captions." in rendered
        if page:
            assert "no sub-panels" not in rendered


def test_guard_survives_sanitizing_and_budget_while_subject_direction_is_emitted_once():
    from novel_to_comic.models.generation import PromptSubject
    from novel_to_comic.prompt_hygiene import apply_prompt_budget

    guard = "Guard: inscribed NEVER restore this wing. captions remain absent! END_GUARD"
    identity = "A young winged creature with one cobalt wing."
    request = compile_non_panel_request(Config(image_model="image-gemini-pro"), AbstractStyleProofInput(
        asset_identity="guard-proof",
        prompt=GenerationPromptInput(
            subjects=(PromptSubject(character_id="bird", name="Bird", identity=identity,
                                    action="ACTION_SENTINEL", position="POSITION_SENTINEL",
                                    appearance_guard=guard),),
            anchors=(PromptAnchor(kind="character", entity_id="bird", name="Bird", text=identity),),
        ),
    ))
    rendered = request.compiled.final_prompt
    assert rendered.count(identity) == 1
    assert rendered.count("ACTION_SENTINEL") == 1
    assert rendered.count("POSITION_SENTINEL") == 1
    sections = [(section.kind, section.body) for section in request.compiled.sections]
    budgeted = apply_prompt_budget(sections, char_limit=1)
    assert guard in budgeted.final_prompt


def test_location_state_path_is_entity_scoped(tmp_path):
    from novel_to_comic.artifacts import location_state_plate_path

    first = location_state_plate_path(tmp_path, "house", "night")
    second = location_state_plate_path(tmp_path, "forest", "night")
    assert first != second
    assert first.parent != second.parent


def test_prop_state_reference_emits_only_compatible_parent_facets(tmp_path):
    from novel_to_comic.compiled_request import compile_reference_instruction
    from novel_to_comic.image_references import AuthorityScope, ReferenceAsset

    reference = ReferenceAsset(
        path=tmp_path / "prop.png", role="prop", entity_id="coat", appearance_state_id="torn",
        authority_scope=AuthorityScope.CONTEXTUAL, preserve_facets=("material",),
        ignore_facets=("shape", "color"), pose=None, content_sha256="a" * 64,
        lineage_parent_sha256=None, label="coat / torn",
    )
    instruction = compile_reference_instruction(reference, 0)
    assert instruction.preserve_facets == ("material",)
    assert {"shape", "color"} <= set(instruction.ignore_facets)
    assert "shape" in instruction.semantic_instruction
    assert "color" in instruction.semantic_instruction



def test_character_requests_preserve_nonhuman_canonical_anatomy():
    from novel_to_comic.models.story_bible import Character, StoryBible
    from novel_to_comic.stages.s3_cast import _character_generation_input

    config = Config(image_model="image-gemini-pro")
    anchor = "adult tortoiseshell cat, four short legs, round amber eyes, long fluffy tail"
    cat = Character(
        id="char_cat", name="Moss", visual_anchor=anchor, age_range="adult",
        gender="female", distinguishing_features=["amber eyes"], default_outfit="none",
        first_appearance_scene="scene_001",
    )
    bible = StoryBible(
        title="Test", author="Test", total_scenes=0, characters=[cat],
        locations=[], scenes=[], narrative_arcs=[],
    )
    for input_data in (_character_generation_input(config, bible, cat),):
        request = compile_non_panel_request(config, input_data)
        assert anchor in "\n\n".join(request.wire.prompt_parts)
        assert anchor in [protected.text for protected in request.compiled.protected_anchors]


def test_cover_style_lookup_never_substitutes_an_unselected_sample(tmp_path):
    from novel_to_comic.server.routers.projects import _find_style_ref
    from novel_to_comic.style_contract import style_template_for_suggestion

    samples = tmp_path / "samples"
    samples.mkdir()
    suggestion = {"template": "Graphite drawing"}
    (samples / "style_suggestions.json").write_text(json.dumps({"suggestions": [suggestion]}))
    image = samples / "style_1.png"
    image.write_bytes(b"existing-reference")
    assert _find_style_ref(tmp_path, "Watercolor") is None
    assert _find_style_ref(tmp_path, style_template_for_suggestion(suggestion)) == image


def test_editable_sanitizer_does_not_match_caption_prefix_inside_words():
    from novel_to_comic.prompt_hygiene import sanitize_dynamic_text

    assert sanitize_dynamic_text("A captioner stands quietly.") == "A captioner stands quietly."


def test_location_guard_is_protected_in_final_asset_prompt():
    guard = "NIGHT_GUARD: inscribed words are absent. Never restore the roof!"
    request = compile_non_panel_request(Config(image_model="image-gemini-pro"), CanonicalLocationPlateInput(
        asset_identity="house:night",
        prompt=GenerationPromptInput(anchors=(PromptAnchor(
            kind="location", entity_id="house", name="House", appearance_state_id="night",
            text="Roofless house under moonlight.", continuity_guard=guard,
        ),)),
    ))
    protected = next(section for section in request.compiled.sections if section.kind == "protected_anchors")
    assert guard in protected.body

def test_common_non_panel_provenance_has_asset_identity_and_wire_fields():
    config = Config(image_model="image-gemini-pro")
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
    config = Config(image_model="image-gemini-pro")
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
        "novel_to_comic.asset_generation.execute_frozen_request",
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
    config = Config(image_model="image-gemini-pro")
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
        "novel_to_comic.asset_generation.execute_frozen_request",
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


def test_non_panel_gateway_failure_persists_retryable_service_classification(
    tmp_path, monkeypatch,
):
    config = Config(image_model="image-gemini-pro")
    request = compile_non_panel_request(
        config,
        AbstractStyleProofInput(
            asset_identity="style_sample:gateway-failed",
            prompt=GenerationPromptInput(
                visual_brief="A deterministic proof.", width=819, height=1024,
                generation_shape="portrait",
            ),
        ),
        reference_plan=_empty_plan(config),
    )
    output_path = tmp_path / "samples" / "gateway-failed.png"

    async def fake_execute_frozen_request(**kwargs):
        raise RuntimeError(
            "wire image transport failed: gateway connection could not be established"
        )

    monkeypatch.setattr(
        "novel_to_comic.asset_generation.execute_frozen_request",
        fake_execute_frozen_request,
    )
    with pytest.raises(RuntimeError):
        asyncio.run(submit_non_panel_request(
            config=config, project_dir=tmp_path, request=request,
            output_path=output_path, feature="style.sample", kind="style_sample",
        ))

    failure = json.loads(output_path.with_suffix(".png.failure.json").read_text())
    assert failure["classification"] == "service_unavailable"
    assert failure["recoverable"] is True
    assert failure["user_message"] == (
        "We could not reach the image service. "
        "Check your connection and try this panel again."
    )


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

    monkeypatch.setattr("novel_to_comic.asset_generation.compile_non_panel_request", _paid_call)
    monkeypatch.setattr("novel_to_comic.asset_generation.submit_frozen_request", _paid_call)
    monkeypatch.setattr("novel_to_comic.asset_generation.execute_frozen_request", _paid_call)

    restore_asset_version(output_path, tmp_path, 1)

    assert output_path.read_bytes() == b"archived-image"
    restored = json.loads(output_path.with_suffix(".png.meta.json").read_text())
    assert restored["provenance"]["request_id"] == "original-request"


@pytest.mark.parametrize("kind", ["location", "character_state"])
def test_owner_direction_wins_in_image_wire_but_source_anchors_stay_verbatim(kind):
    from novel_to_comic.asset_generation import _meta_payload
    from novel_to_comic.models.generation import PromptSubject
    config = Config(image_model="image-gemini-pro", style_template="Ink wash")
    anchor = "gas lamp beside an oak desk" if kind == "location" else "white hair, hollow face"
    direction = "Replace the gas lamp with a brass pendant." if kind == "location" else "Make his hair black and his face rugged, with a haunted sailor's stare."
    prompt = GenerationPromptInput(
        anchors=(PromptAnchor(kind="location", entity_id="loc_001", name="Office", text=anchor),) if kind == "location" else (),
        subjects=(PromptSubject(character_id="char_001", name="Sailor", identity=anchor,
                                appearance_locked=True, appearance_state_id="haunted",
                                appearance_guard="His hair must stay entirely white."),) if kind == "character_state" else (),
        editorial_addendum=direction, width=1344, height=768, generation_shape="landscape",
    )
    request = compile_non_panel_request(config, CanonicalLocationPlateInput(
        asset_identity="location_plate:loc_001", prompt=prompt,
    ), reference_plan=_empty_plan(config))
    wire = request.wire.prompt_parts[0]
    assert anchor in wire
    assert direction in wire
    assert "explicit visual direction takes precedence" in wire
    assert "Only these editable facets" not in wire
    assert "fixed altered appearance" not in wire
    assert _meta_payload(request, {})["art_direction"] == direction
