"""Slice 14 deterministic golden corpus and release-blocker gates.

The fixture is intentionally semantic: anchors, ownership, reference roles,
diagnostics, and hash effects are reviewable without storing generated project
directories or provider output.  No test in this module crosses a paid/model
transport boundary.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from novel_to_comic.compiled_request import compile_generation_request
from novel_to_comic.config import Config
from novel_to_comic.frozen_requests import (
    load_frozen_request,
    submit_frozen_request,
)
from novel_to_comic.generation_request_preview import (
    compiled_request_context,
    frozen_request_preview,
)
from novel_to_comic.image_models import (
    GATEWAY_IMAGE_BALANCED,
    GATEWAY_IMAGE_FAST,
    GATEWAY_IMAGE_REVE,
    ImageRoute,
    describe_image_model,
    image_model_profile,
)
from novel_to_comic.image_provenance import common_image_provenance
from novel_to_comic.image_references import (
    AuthorityScope,
    DropReason,
    DroppedReference,
    ReferenceAsset,
    ReferencePlan,
    SemanticCandidate,
    build_reference_plan,
    selection_fingerprint_hex,
)
from novel_to_comic.models.prompt import (
    ImagePrompt,
    LayoutRegion,
    PromptAnchor,
    PromptLayout,
    PromptOverlayOp,
    PromptSubject,
)
from novel_to_comic.non_panel_generation import reference_plan_for_assets
from novel_to_comic.panel_store import apply_prompt_patch
from novel_to_comic.prompt_assembly import reapply_overlays
from novel_to_comic.prompt_instructions import (
    PanelPatchOperation,
    PromptInstructionPatch,
    apply_instruction_patch,
)
from novel_to_comic.provider_wire import compile_provider_wire_request
from novel_to_comic.ai.providers.litellm_http import serialize_wire_request
from litellm_handlers.provider_wire import exact_vertex_contents, parse_provider_wire
from test_image_references import (
    TestContinuity,
    TestAuthorityScopes,
    TestLineage,
    TestLocationStateAuthority,
    TestProps,
)
from test_prompt_lineage import TestStateAwareOverlayDrops
from test_state_asset_lifecycle import (
    test_location_state_wins_over_mutable_canonical_facets,
)


CORPUS_PATH = Path(__file__).with_name("fixtures") / "golden_prompt_corpus.json"
CORPUS = json.loads(CORPUS_PATH.read_text())
SCENARIOS = {item["id"]: item for item in CORPUS["scenarios"]}

_REQUIRED_SCENARIOS = {
    "canonical_one_character_location",
    "two_characters_plus_location",
    "three_characters_constrained_context",
    "four_characters_location_overflow",
    "subject_count_beyond_route_cap",
    "minor_wardrobe_only_state",
    "major_age_anatomy_hair_injury_state",
    "restored_canonical_equivalent_state",
    "location_time_weather_damage_collapse_water",
    "missing_unverified_stale_state_assets",
    "recurring_critical_and_noncritical_props",
    "dynamic_story_text_is_not_image_text",
    "compatible_match_cut_continuity",
    "incompatible_match_cut_continuity",
    "manual_semantic_edit",
    "manual_layout_only_edit",
    "instructed_edit",
    "selected_reference_replaced_same_path",
    "equivalent_aliases_same_route",
}

_EXECUTABLE_GATE_BY_SCENARIO = {
    "canonical_one_character_location": "test_long_corpus_anchors_survive_compilation_and_dynamic_text_is_removed",
    "two_characters_plus_location": "test_order_and_wire_snapshot_are_one_owner",
    "three_characters_constrained_context": "test_reference_overflow_is_named_instead_of_silently_omitted",
    "four_characters_location_overflow": "test_reference_overflow_is_named_instead_of_silently_omitted",
    "subject_count_beyond_route_cap": "test_reference_overflow_is_named_instead_of_silently_omitted",
    "minor_wardrobe_only_state": "test_state_corpus_keeps_active_state_authority_explicit",
    "major_age_anatomy_hair_injury_state": "test_state_corpus_keeps_active_state_authority_explicit",
    "restored_canonical_equivalent_state": "test_character_and_location_state_corpus_executes_authority_matrix",
    "location_time_weather_damage_collapse_water": "test_character_and_location_state_corpus_executes_authority_matrix",
    "missing_unverified_stale_state_assets": "test_missing_unverified_and_stale_asset_corpus_executes",
    "recurring_critical_and_noncritical_props": "test_prop_and_continuity_corpus_executes_selection_policy",
    "dynamic_story_text_is_not_image_text": "test_long_corpus_anchors_survive_compilation_and_dynamic_text_is_removed",
    "compatible_match_cut_continuity": "test_prop_and_continuity_corpus_executes_selection_policy",
    "incompatible_match_cut_continuity": "test_prop_and_continuity_corpus_executes_selection_policy",
    "manual_semantic_edit": "test_manual_semantic_layout_and_instructed_edit_matrix",
    "manual_layout_only_edit": "test_manual_semantic_layout_and_instructed_edit_matrix",
    "instructed_edit": "test_manual_semantic_layout_and_instructed_edit_matrix",
    "selected_reference_replaced_same_path": "test_selected_bytes_invalidate_identity_but_diagnostics_do_not",
    "equivalent_aliases_same_route": "test_route_aliases_are_truthful_and_capabilities_are_not_label_inferred",
}


def _prompt(
    *,
    subjects: list[PromptSubject] | None = None,
    anchors: list[PromptAnchor] | None = None,
    visual_brief: str | None = None,
    layout: PromptLayout | None = None,
    full_prompt: str = "",
    composition: str = "medium shot",
    setting: str | None = None,
    location_state_id: str | None = None,
) -> ImagePrompt:
    return ImagePrompt(
        prompt_version=23,
        planned_panel_id="scene_001:panel_001",
        scene_id="scene_001",
        panel_number=1,
        composition=composition,
        setting=setting,
        full_prompt=full_prompt,
        visual_brief=visual_brief,
        layout=layout,
        subjects=subjects or [],
        anchors=anchors or [],
        location_id="loc_tavern",
        location_state_id=location_state_id,
        width=768,
        height=1344,
        steps=20,
    )


def _asset(tmp_path: Path, *, role: str, entity_id: str, payload: str) -> ReferenceAsset:
    path = tmp_path / "refs" / entity_id / f"{role}.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = payload.encode()
    path.write_bytes(data)
    return ReferenceAsset(
        path=path,
        role=role,
        entity_id=entity_id,
        appearance_state_id=None,
        authority_scope=(
            AuthorityScope.FULL_APPEARANCE
            if role == "subject"
            else AuthorityScope.CONTEXTUAL
        ),
        preserve_facets=("face", "hair", "build") if role == "subject" else (),
        ignore_facets=(),
        pose="front" if role == "subject" else None,
        content_sha256=hashlib.sha256(data).hexdigest(),
        lineage_parent_sha256=None,
        label=entity_id,
    )


def _plan(assets: tuple[ReferenceAsset, ...], *, dropped: tuple = ()) -> ReferencePlan:
    return ReferencePlan(
        expected_route=ImageRoute.REVE,
        selected=assets,
        dropped=dropped,
        selection_fingerprint=selection_fingerprint_hex(assets),
    )


def _compile(prompt: ImagePrompt, plan: ReferencePlan):
    return compile_generation_request(
        prompt=prompt,
        reference_plan=plan,
        route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
        requested_alias=GATEWAY_IMAGE_REVE,
        configured_provider_model="reve/create",
        selected_style_text="ink wash",
    )


def test_fixture_corpus_is_complete_and_reviewable():
    assert CORPUS["schema_version"] == 1
    assert _REQUIRED_SCENARIOS <= SCENARIOS.keys()
    assert len(CORPUS["review_findings"]) >= 10
    assert set(_EXECUTABLE_GATE_BY_SCENARIO) == _REQUIRED_SCENARIOS
    defaults = CORPUS["expectation_defaults"]
    assert set(defaults) == {
        "active_entity_ids", "active_state_ids", "overlay_compatibility",
        "selected_references", "dropped_references", "warnings", "errors",
        "prompt_section_ownership", "effective_geometry", "effective_controls",
        "hash_effects",
    }
    for scenario in CORPUS["scenarios"]:
        assert scenario["id"]
        assert "required_anchors" in scenario
        assert "selected_roles" in scenario
        assert "required_concepts" in scenario
        assert "forbidden_concepts" in scenario
        assert _EXECUTABLE_GATE_BY_SCENARIO[scenario["id"]] in globals()


@pytest.mark.parametrize("scenario_id", sorted(_REQUIRED_SCENARIOS))
def test_every_corpus_scenario_has_explicit_anchor_and_hash_semantics(scenario_id: str):
    scenario = SCENARIOS[scenario_id]
    assert isinstance(scenario["required_anchors"], list)
    if scenario_id == "selected_reference_replaced_same_path":
        assert scenario["hash_effects"] == {
            "compiled": "changes",
            "execution": "changes",
            "provenance": "changes",
        }


def test_long_corpus_anchors_survive_compilation_and_dynamic_text_is_removed():
    subjects = [
        PromptSubject(
            character_id="char_mara",
            name="Mara",
            identity="CHAR_MARA_CANONICAL_SENTINEL with a silver braid",
        )
    ]
    location = PromptAnchor(
        kind="location",
        entity_id="loc_tavern",
        name="Tavern",
        text="LOC_TAVERN_CANONICAL_SENTINEL with oak beams",
    )
    prompt = _prompt(
        subjects=subjects,
        anchors=[location],
        composition='A sign reading "OPEN NOW" hangs behind her; Mara says "wait". SFX KRAK.',
        setting="The tavern interior.",
        visual_brief="Caption: Mara enters. Keep the readable sign text.",
    )
    request = _compile(prompt, _plan(()))
    final = request.final_prompt
    assert "CHAR_MARA_CANONICAL_SENTINEL with a silver braid" in final
    assert "LOC_TAVERN_CANONICAL_SENTINEL with oak beams" in final
    for forbidden in ("OPEN NOW", "KRAK", "Mara says", "Caption:"):
        assert forbidden not in final
    assert any("no text" in line.lower() for section in request.sections for line in section.lines)


def test_state_corpus_keeps_active_state_authority_explicit():
    state = PromptSubject(
        character_id="char_mara",
        name="Mara",
        identity="STATE_MARA_MAJOR_SENTINEL, adult with cropped white hair and an injured left arm",
        appearance_state_id="battle_wounded_adult",
        appearance_locked=True,
    )
    asset = ReferenceAsset(
        path=Path("refs/char_mara/states/battle_wounded_adult/front.png"),
        role="subject",
        entity_id="char_mara",
        appearance_state_id="battle_wounded_adult",
        authority_scope=AuthorityScope.FULL_APPEARANCE,
        preserve_facets=("face", "hair", "build", "wardrobe", "anatomy"),
        ignore_facets=(),
        pose="front",
        content_sha256="a" * 64,
        lineage_parent_sha256="b" * 64,
        label="Mara",
    )
    request = _compile(_prompt(subjects=[state]), _plan((asset,)))
    assert "STATE_MARA_MAJOR_SENTINEL" in request.final_prompt
    assert request.reference_instructions[0].authority_scope is AuthorityScope.FULL_APPEARANCE
    instruction = request.reference_instructions[0].semantic_instruction
    assert "match face, hair, build, wardrobe and anatomy" in instruction
    assert "do not copy its pose or background" in instruction
    assert "default outfit" not in request.final_prompt.lower()


def test_state_aware_overlay_rejection_is_deterministic():
    prompt = _prompt(
        subjects=[PromptSubject(
            character_id="char_mara", name="Mara", identity="CHAR_MARA_CANONICAL_SENTINEL",
            appearance_state_id="restored",
        )]
    )
    warnings = reapply_overlays(prompt, [PromptOverlayOp(
        field="action", value="holds the key", subject_character_id="char_mara",
        appearance_state_id="battle_wounded_adult",
    )])
    assert [warning.code for warning in warnings] == ["state_incompatible"]


def test_character_and_location_state_corpus_executes_authority_matrix(tmp_path: Path):
    subject = TestAuthorityScopes()
    subject.test_missing_significant_state_ref_omits_contradictory_canonical(tmp_path / "missing-subject")
    subject.test_explicit_canonical_equivalent_state_allows_full_canonical_ref(tmp_path / "restored")

    minor_dir = tmp_path / "minor-wardrobe"
    base_ref = minor_dir / "refs" / "char_mara" / "full_body.png"
    base_ref.parent.mkdir(parents=True, exist_ok=True)
    base_ref.write_bytes(b"canonical-mara")
    minor_prompt = _prompt(subjects=[PromptSubject(
        character_id="char_mara",
        name="Mara",
        identity="STATE_MARA_RAINCOAT_SENTINEL",
        appearance_state_id="raincoat",
        appearance_locked=False,
    )])
    minor_plan = build_reference_plan(
        route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
        project_dir=minor_dir,
        prompt=minor_prompt,
    )
    minor_ref = next(ref for ref in minor_plan.selected if ref.role == "subject")
    assert minor_ref.authority_scope is AuthorityScope.IDENTITY_ONLY
    assert {"wardrobe", "anatomy"} <= set(minor_ref.ignore_facets)

    location = TestLocationStateAuthority()
    location.test_active_location_state_outranks_redundant_style_sample(tmp_path / "active-location")
    location.test_missing_location_state_no_canonical_substitution(tmp_path / "missing-location")
    test_location_state_wins_over_mutable_canonical_facets(tmp_path / "location-facets")

    flooded = _prompt(
        anchors=[PromptAnchor(
            kind="location",
            entity_id="loc_tavern",
            name="Tavern",
            appearance_state_id="collapsed_storm_flooded_night",
            text=(
                "LOC_TAVERN_COLLAPSED_STORM_FLOODED_NIGHT_SENTINEL; night; "
                "violent storm; collapsed roof; waist-high flood water"
            ),
        )],
        location_state_id="collapsed_storm_flooded_night",
        setting="Inside the active location state.",
    )
    flooded_request = _compile(flooded, _plan(()))
    assert "LOC_TAVERN_COLLAPSED_STORM_FLOODED_NIGHT_SENTINEL" in flooded_request.final_prompt
    for facet in ("night", "violent storm", "collapsed roof", "waist-high flood water"):
        assert facet in flooded_request.final_prompt
    assert "intact sunny dry tavern" not in flooded_request.final_prompt


def test_missing_unverified_and_stale_asset_corpus_executes(tmp_path: Path):
    lineage = TestLineage()
    lineage.test_stale_lineage_excluded_when_parent_hash_mismatches(tmp_path / "stale-subject")
    lineage.test_absent_lineage_treated_as_unverified_safety_policy(tmp_path / "unverified-subject")
    lineage.test_stale_location_state_lineage_is_excluded(tmp_path / "stale-location")
    lineage.test_unverified_location_state_is_selected_with_warning(tmp_path / "unverified-location")


def test_prop_and_continuity_corpus_executes_selection_policy(tmp_path: Path):
    props = TestProps()
    props.test_critical_prop_selected(tmp_path / "critical-prop")
    props.test_close_shot_critical_prop_policy(tmp_path / "scarce-critical", True, "prop")
    props.test_close_shot_critical_prop_policy(tmp_path / "scarce-noncritical", False, "location_plate")

    continuity = TestContinuity()
    continuity.test_state_change_suppresses_incompatible_continuity(tmp_path / "incompatible")
    continuity.test_compatible_match_cut_keeps_continuity(tmp_path / "compatible")


def test_overlay_corpus_executes_character_and_location_compatibility():
    overlays = TestStateAwareOverlayDrops()
    overlays.test_uses_both_hands_overlay_dropped_in_no_hands_state()
    overlays.test_location_sensitive_overlay_revalidated_on_state_change()


def test_manual_semantic_layout_and_instructed_edit_matrix():
    layout = PromptLayout(regions=[LayoutRegion(label="Mara", prompt="standing")])
    prompt = _prompt(
        subjects=[PromptSubject(
            character_id="char_mara", name="Mara", identity="CHAR_MARA_CANONICAL_SENTINEL",
        )],
        visual_brief="fresh brief",
        layout=layout,
    )
    semantic = apply_prompt_patch(prompt, {"composition": "close-up"})
    assert semantic.visual_brief is None
    assert semantic.layout is None

    layout_edit = apply_prompt_patch(prompt, {"layout": layout.model_dump()})
    assert layout_edit.visual_brief == "fresh brief"
    assert layout_edit.layout == layout

    instructed = apply_instruction_patch(prompt, PromptInstructionPatch(
        operations=[PanelPatchOperation(field="mood", value="storm-lit")]
    ))
    assert instructed.visual_brief is None
    assert instructed.layout is None
    assert "CHAR_MARA_CANONICAL_SENTINEL" in instructed.full_prompt


def test_reference_overflow_is_named_instead_of_silently_omitted(tmp_path: Path):
    config = Config(image_model=GATEWAY_IMAGE_REVE)
    assets = [_asset(tmp_path, role="subject", entity_id=f"char_{i}", payload=f"{i}") for i in range(5)]
    plan = reference_plan_for_assets(config, assets)
    assert len(plan.selected) == 4
    assert len(plan.dropped) == 1
    assert plan.dropped[0].reason is DropReason.PROVIDER_CAP
    assert plan.dropped[0].candidate.entity_id == "char_4"

    # A required subject may lose its image slot, but never its text identity.
    prompt = _prompt(subjects=[
        PromptSubject(
            character_id=f"char_{index}",
            name=f"Person {index}",
            identity=f"CHAR_{index}_OVERFLOW_SENTINEL",
        )
        for index in range(5)
    ])
    request = compile_generation_request(
        prompt=prompt,
        reference_plan=plan,
        route_profile=image_model_profile(GATEWAY_IMAGE_REVE),
        requested_alias=GATEWAY_IMAGE_REVE,
        configured_provider_model="reve/create",
        selected_style_text="ink wash",
    )
    for index in range(5):
        assert f"CHAR_{index}_OVERFLOW_SENTINEL" in request.final_prompt


def test_order_and_wire_snapshot_are_one_owner(tmp_path: Path):
    assets = (
        _asset(tmp_path, role="subject", entity_id="char_mara", payload="mara"),
        _asset(tmp_path, role="prop", entity_id="prop_key", payload="key"),
        _asset(tmp_path, role="location_plate", entity_id="loc_tavern", payload="tavern"),
    )
    prompt = _prompt(
        subjects=[PromptSubject(
            character_id="char_mara", name="Mara", identity="CHAR_MARA_CANONICAL_SENTINEL",
        )],
        anchors=[PromptAnchor(
            kind="location", entity_id="loc_tavern", name="Tavern",
            text="LOC_TAVERN_CANONICAL_SENTINEL",
        )],
    )
    wire = compile_provider_wire_request(_compile(prompt, _plan(assets)))
    assert [reference.role for reference in wire.references] == ["subject", "prop", "location_plate"]
    assert [reference.index for reference in wire.references] == [0, 1, 2]
    assert wire.prompt_parts[0].count("<frame>0</frame>") == 1
    assert wire.prompt_parts[0].count("<frame>1</frame>") == 1
    assert wire.prompt_parts[0].count("<frame>2</frame>") == 1

    snapshot = json.loads((CORPUS_PATH.parent / "golden_provider_wire_reve.json").read_text())
    actual = json.loads(wire.to_json())
    actual["references"] = [
        {key: value for key, value in reference.items()
         if key != "source_path"}
        for reference in actual["references"]
    ]
    assert actual == snapshot


def test_selected_bytes_invalidate_identity_but_diagnostics_do_not(tmp_path: Path):
    asset = _asset(tmp_path, role="subject", entity_id="char_mara", payload="before")
    base = _plan((asset,))
    changed_asset = replace(asset, content_sha256="f" * 64)
    changed = _plan((changed_asset,))
    diagnostic_only = replace(base, dropped=(DroppedReference(
        candidate=SemanticCandidate(path=Path("unused"), role="style"),
        reason=DropReason.LOWER_PRIORITY,
        detail="diagnostic only",
    ),))
    assert base.selection_fingerprint != changed.selection_fingerprint
    assert base.selection_fingerprint == diagnostic_only.selection_fingerprint
    base_compiled = _compile(_prompt(), base)
    changed_compiled = _compile(_prompt(), changed)
    diagnostic_compiled = _compile(_prompt(), diagnostic_only)
    assert base_compiled.compiled_request_sha256 != changed_compiled.compiled_request_sha256
    assert base_compiled.compiled_request_sha256 == diagnostic_compiled.compiled_request_sha256
    assert (
        compile_provider_wire_request(base_compiled).execution_fingerprint
        != compile_provider_wire_request(changed_compiled).execution_fingerprint
    )
    assert (
        compile_provider_wire_request(base_compiled).execution_fingerprint
        == compile_provider_wire_request(diagnostic_compiled).execution_fingerprint
    )

    asset.path.write_bytes(b"after")
    replaced_at_same_path = replace(
        asset, content_sha256=hashlib.sha256(b"after").hexdigest()
    )
    assert replaced_at_same_path.path == asset.path
    assert _compile(_prompt(), _plan((asset,))).compiled_request_sha256 != _compile(
        _prompt(), _plan((replaced_at_same_path,))
    ).compiled_request_sha256


def test_frozen_wire_and_submitted_preview_are_byte_equivalent(tmp_path: Path):
    source = tmp_path / "ref.png"
    source.write_bytes(b"mara")
    asset = _asset(tmp_path, role="subject", entity_id="char_mara", payload="mara")
    compiled = _compile(
        _prompt(subjects=[PromptSubject(
            character_id="char_mara", name="Mara", identity="CHAR_MARA_CANONICAL_SENTINEL",
        )]),
        _plan((replace(asset, path=source),)),
    )
    wire = compile_provider_wire_request(compiled)
    frozen = submit_frozen_request(
        tmp_path,
        wire,
        status="prepared",
        request_context=compiled_request_context(compiled),
    )
    loaded = load_frozen_request(tmp_path, frozen.request_id)
    preview = frozen_request_preview(loaded, include_dev_content=True)
    preview_wire = dict(preview["provider_wire"])
    manifest_wire = json.loads(loaded.wire.to_json())
    for key in ("references",):
        for item in preview_wire[key]:
            item.pop("source_path", None)
        for item in manifest_wire[key]:
            item.pop("source_path", None)
    assert preview_wire == manifest_wire
    assert preview["execution_fingerprint"] == loaded.execution_fingerprint
    assert preview["semantic_prompt"]["final_prompt"] == compiled.final_prompt

    # The isolated adapter consumes the same manifest prompt, instructions, and
    # order; it is not allowed to author a second semantic request.
    params, files = serialize_wire_request(loaded.wire)
    submitted_manifest = json.loads(params["canary_wire_request"])
    adapter_manifest = parse_provider_wire(params["canary_wire_request"])
    assert adapter_manifest == submitted_manifest
    image_parts = [object() for _ in files]
    assert exact_vertex_contents(adapter_manifest, image_parts) == [
        *[
            value
            for reference, image_part in zip(loaded.wire.references, image_parts, strict=True)
            for value in (image_part, reference.instruction)
        ],
        loaded.wire.prompt_parts[0],
    ]


def test_common_provenance_separates_configured_actual_and_dimensions(tmp_path: Path):
    asset = _asset(tmp_path, role="subject", entity_id="char_mara", payload="mara")
    compiled = _compile(_prompt(), _plan((asset,)))
    wire = compile_provider_wire_request(compiled)
    record = common_image_provenance(
        asset_kind="panel",
        asset_identity="scene_001:panel_001",
        compiled_sha256=compiled.compiled_request_sha256,
        prompt_source_sha256="s" * 64,
        wire=wire,
        reference_plan=_plan((asset,)),
        request_id="request-1",
        actual_provider_model="provider/actual-v2",
        actual_width=640,
        actual_height=832,
        project_dir=tmp_path,
    )
    assert record["configured_provider_model"] == "reve/create"
    assert record["actual_provider_model"] == "provider/actual-v2"
    assert record["effective_dimensions"] == {"width": wire.width, "height": wire.height}
    assert record["actual_dimensions"] == {"width": 640, "height": 832}
    assert str(tmp_path) not in json.dumps(record)


@pytest.mark.parametrize(
    "asset_kind",
    ["panel", "style_sample", "character_ref", "location_plate", "prop_ref", "project_cover"],
)
def test_provenance_envelope_covers_every_asset_kind(tmp_path: Path, asset_kind: str):
    asset = _asset(tmp_path, role="subject", entity_id="char_mara", payload="mara")
    compiled = _compile(_prompt(), _plan((asset,)))
    wire = compile_provider_wire_request(compiled)
    record = common_image_provenance(
        asset_kind=asset_kind,
        asset_identity=f"{asset_kind}:fixture",
        compiled_sha256=compiled.compiled_request_sha256,
        prompt_source_sha256=None,
        wire=wire,
        reference_plan=_plan((asset,)),
        request_id="fixture-request",
        actual_provider_model="provider/actual",
        project_dir=tmp_path,
    )
    assert record["asset_kind"] == asset_kind
    assert record["configured_provider_model"] == "reve/create"
    assert record["actual_provider_model"] == "provider/actual"
    assert record["selected_references"][0]["content_sha256"] == asset.content_sha256


def test_route_aliases_are_truthful_and_capabilities_are_not_label_inferred():
    fast = describe_image_model(GATEWAY_IMAGE_FAST)
    balanced = describe_image_model(GATEWAY_IMAGE_BALANCED)
    assert fast.route is ImageRoute.GEMINI_FLASH_LITE
    assert balanced.route is ImageRoute.GEMINI_FLASH_LITE
    assert fast.provider_model == balanced.provider_model
    assert image_model_profile(GATEWAY_IMAGE_REVE).max_references == 4
    assert image_model_profile(GATEWAY_IMAGE_BALANCED).max_references == 10
    assert "GPT Image 2" not in fast.display_name


def test_architecture_contract_has_no_raw_production_caller_or_second_selector():
    production_modules = (
        "novel_to_comic.stages.s2_style",
        "novel_to_comic.stages.s3_cast",
        "novel_to_comic.stages.s7_draw",
        "novel_to_comic.server.routers.pipeline",
        "novel_to_comic.server.routers.projects",
        "novel_to_comic.labs.providers.litellm",
    )
    for module_name in production_modules:
        module = importlib.import_module(module_name)
        tree = ast.parse(Path(module.__file__).read_text())
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"generate_image", "generate"}
        }
        assert not calls, f"{module_name} still calls a raw provider interface: {calls}"

    repo_root = Path(__file__).resolve().parents[2]
    handler_tree = ast.parse(
        (repo_root / "litellm_handlers" / "provider_wire.py").read_text()
    )
    imports = {
        alias.name
        for node in ast.walk(handler_tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imports |= {
        alias.name
        for node in ast.walk(handler_tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert not any(name.startswith("novel_to_comic") for name in imports)
