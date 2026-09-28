from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from novel_to_comic.book_adaptation import _BlueprintDraft, _BookDraft, _LetteringDraft
from novel_to_comic.book_adaptation import _lettering_response_schema, _LetteringResponse
from novel_to_comic.models.adaptation import BookAdaptation, LetteringItem, NarrativeTreatment
from novel_to_comic.page_planning import _BookPageMap, _BookPlanDraft


def _assert_strict_contract(schema: dict[str, Any]) -> None:
    """Offline checker for the documented strict subset used by Adapt, not an API emulator."""
    assert schema.get("type") == "object"
    assert "anyOf" not in schema

    def visit(node: dict[str, Any]) -> None:
        assert not {"allOf", "oneOf", "not", "if", "then", "else"}.intersection(node)
        if "$ref" in node:
            assert len(node) == 1
            reference = node["$ref"]
            assert reference == "#" or reference.startswith("#/")
            target = schema
            for part in reference[2:].split("/") if reference != "#" else []:
                target = target[part.replace("~1", "/").replace("~0", "~")]
            assert isinstance(target, dict)
        if node.get("type") == "object":
            properties = node.get("properties", {})
            assert node.get("additionalProperties") is False, "objects must be closed"
            assert set(node.get("required", [])) == set(properties), "all properties must be required"
            for child in properties.values():
                visit(child)
        if node.get("type") == "array":
            assert isinstance(node.get("items"), dict)
            visit(node["items"])
        for keyword in ("$defs", "definitions"):
            for child in node.get(keyword, {}).values():
                visit(child)
        for child in node.get("anyOf", []):
            visit(child)

    visit(schema)


def test_narrative_treatment_strict_schema_accepts_actual_contract_without_mutation() -> None:
    from novel_to_comic.ai.codex_schema import strict_output_schema

    source = NarrativeTreatment.model_json_schema()
    original = deepcopy(source)
    converted = strict_output_schema(source)
    _assert_strict_contract(converted)
    assert source == original
    # Strengthen only the request: defaults still work in local artifact validation.
    treatment = NarrativeTreatment.model_validate({"causal_spine": ["A choice has consequences."]})
    assert treatment.character_arcs == ()
    converted["properties"]["causal_spine"]["items"]["type"] = "number"
    assert source == original


@pytest.mark.parametrize("model", [_LetteringDraft, _BookDraft, _LetteringResponse])
def test_generation_schema_constrains_lettering_delivery_and_speaker(model):
    from novel_to_comic.ai.codex_schema import strict_output_schema

    definition = "_LetteringCopy" if model is _LetteringResponse else "LetteringItem"
    field = "presentation" if model is _LetteringResponse else "delivery"
    schema = strict_output_schema(_lettering_response_schema(model, {"char_001"}))
    _assert_strict_contract(schema)
    variants = schema["$defs"][definition]["anyOf"]
    if model is _LetteringResponse:
        assert all("id" not in variant["properties"] for variant in variants)
    pairs = {(kind, delivery) for variant in variants
             for kind in variant["properties"]["kind"]["enum"]
             for delivery in variant["properties"][field]["enum"]}
    assert pairs == {("dialogue", "onscreen"), ("dialogue", "offscreen"),
                     ("thought", "onscreen"), ("thought", "offscreen"),
                     ("caption", "narration"), ("caption", "quoted_text"), ("sfx", "display")}
    onscreen = next(v["properties"] for v in variants if v["properties"][field]["enum"] == ["onscreen"])
    assert onscreen["speaker"] == {"type": "string", "minLength": 1}
    assert onscreen["speaker_entity_id"] == {"type": "string", "enum": ["char_001"]}
    no_characters = strict_output_schema(_lettering_response_schema(model, set()))
    _assert_strict_contract(no_characters)
    assert all("onscreen" not in v["properties"][field]["enum"]
               for v in no_characters["$defs"][definition]["anyOf"])


def test_repair_schema_limits_all_source_citations_but_allows_external_compression_targets():
    from novel_to_comic.ai.codex_schema import strict_output_schema

    schema = strict_output_schema(_lettering_response_schema(
        _BookDraft, {"char_001"}, source_unit_ids=("source_000361", "source_000362"),
    ))
    _assert_strict_contract(schema)
    definitions = schema["$defs"]
    items = [definitions["AdaptedBeat"], *definitions["_LedgerException"]["anyOf"],
             *definitions["LetteringItem"]["anyOf"]]
    assert definitions["_ScopedSourceUnitId"] == {
        "type": "string", "enum": ["source_000361", "source_000362"],
    }
    for item in items:
        assert item["properties"]["source_unit_ids"]["items"] == {
            "$ref": "#/$defs/_ScopedSourceUnitId",
        }
    assert all("enum" not in variant["properties"]["adapted_beat_ids"]["items"]
               for variant in definitions["_LedgerException"]["anyOf"])


def test_plan_schema_binds_states_to_their_approved_entity():
    from novel_to_comic.ai.codex_schema import strict_output_schema
    from novel_to_comic.models.page import ApprovedVisualReference, ApprovedVisualReferenceInventory
    from novel_to_comic.page_planning import _plan_response_schema, _reference_view

    inventory = ApprovedVisualReferenceInventory(references=[
        ApprovedVisualReference(id="sailor_base", entity_id="sailor", visual_anchor="coat"),
        ApprovedVisualReference(id="sailor_wet", entity_id="sailor", appearance_state_id="wet", visual_anchor="wet coat"),
        ApprovedVisualReference(id="ship_night", entity_id="ship", appearance_state_id="night", visual_anchor="night deck"),
    ])
    view = _reference_view(inventory)
    assert all("id" not in entry for entry in view)
    assert [(entry["entity_id"], entry["appearance_state_id"]) for entry in view] == [
        ("sailor", None), ("sailor", "wet"), ("ship", "night"),
    ]
    assert [entry["visual_anchor"] for entry in view] == [r.visual_anchor for r in inventory.references]
    schema = strict_output_schema(_plan_response_schema(inventory))
    _assert_strict_contract(schema)
    assert schema["$defs"]["_PageContentDraft"]["properties"]["entity_ids"]["items"]["enum"] == ["sailor", "ship"]
    choices = schema["$defs"]["_AppearanceStateBinding"]["anyOf"]
    assert {(entity, state) for c in choices for entity in c["properties"]["entity_id"]["enum"]
            for state in c["properties"]["state_id"]["enum"]} == {("sailor", "wet"), ("ship", "night")}
    main_only = ApprovedVisualReferenceInventory(references=[inventory.references[0]])
    schema = strict_output_schema(_plan_response_schema(main_only))
    _assert_strict_contract(schema)
    assert schema["$defs"]["_PageContentDraft"]["properties"]["appearance_states"]["maxItems"] == 0
    empty = strict_output_schema(_plan_response_schema(ApprovedVisualReferenceInventory()))
    _assert_strict_contract(empty)
    assert empty["$defs"]["_PageContentDraft"]["properties"]["entity_ids"]["maxItems"] == 0


def test_plan_detail_schema_keeps_lettering_on_its_allocated_page():
    from novel_to_comic.ai.codex_schema import strict_output_schema
    from novel_to_comic.models.page import ApprovedVisualReferenceInventory
    from novel_to_comic.page_planning import _PageMapEntry, _plan_response_schema

    pages = tuple(_PageMapEntry(
        page_number=n, beat_ids=("shared_beat",), lettering_ids=ids,
        emphasis="initial", density_intent="standard", rhythm_intent="Continue the event.",
    ) for n, ids in ((15, ("lettering_0068",)), (16, ("lettering_0069",)), (17, ())))
    schema = strict_output_schema(_plan_response_schema(ApprovedVisualReferenceInventory(), pages))
    _assert_strict_contract(schema)
    assert schema["properties"]["pages"]["minItems"] == schema["properties"]["pages"]["maxItems"] == 3
    variants = schema["$defs"]["_PageDetailDraft"]["anyOf"]
    allowed = {}
    for variant in variants:
        number = variant["properties"]["page_number"]["enum"][0]
        panel = variant["properties"]["content"]["items"]["properties"]
        assert panel["beat_ids"]["items"]["enum"] == ["shared_beat"]
        assert "lettering_ids" not in panel
        placements = variant["properties"]["lettering_placements"]
        assert placements["additionalProperties"] is False
        assert placements["required"] == list(placements["properties"])
        allowed[number] = placements["required"]
    assert allowed == {15: ["lettering_0068"], 16: ["lettering_0069"], 17: []}


def test_plan_detail_shared_panel_schema_defines_one_panel_for_the_batch():
    from novel_to_comic.models.page import ApprovedVisualReferenceInventory
    from novel_to_comic.page_planning import _PageMapEntry, _plan_response_schema

    pages = tuple(_PageMapEntry(
        page_number=n, beat_ids=beats, lettering_ids=ids,
        emphasis="initial", density_intent="standard", rhythm_intent="Continue the event.",
    ) for n, beats, ids in ((15, ("b1", "b2"), ("lettering_0068",)), (16, ("b2", "b3"), ())))
    schema = _plan_response_schema(ApprovedVisualReferenceInventory(), pages, shared_panel=True)
    panel_ref = {"$ref": "#/$defs/_PanelCompositionDraft"}
    variants = schema["$defs"]["_PageDetailDraft"]["anyOf"]
    assert [v["properties"]["content"]["items"] for v in variants] == [panel_ref, panel_ref]
    beats = schema["$defs"]["_PanelCompositionDraft"]["properties"]["beat_ids"]["items"]["enum"]
    assert beats == ["b1", "b2", "b3"]
    assert [v["properties"]["lettering_placements"]["required"] for v in variants] == [
        ["lettering_0068"], [],
    ]


@pytest.mark.parametrize("model", [
    _BlueprintDraft, _BookDraft, _LetteringDraft, _LetteringResponse, BookAdaptation, _BookPageMap, _BookPlanDraft,
])
def test_nested_adapt_and_page_map_schemas_satisfy_strict_contract(model: Any) -> None:
    from novel_to_comic.ai.codex_schema import strict_output_schema

    source = model.model_json_schema()
    original = deepcopy(source)
    converted = strict_output_schema(source)
    _assert_strict_contract(converted)
    assert source == original
    if "LetteringItem" in converted["$defs"]:
        speaker = converted["$defs"]["LetteringItem"]["properties"]["speaker"]
        assert speaker["anyOf"] == [{"type": "string"}, {"type": "null"}]
        assert "default" not in speaker
        assert LetteringItem(id="l1", kind="dialogue", text="Hello", speaker=None).speaker is None
        with pytest.raises(ValidationError):
            LetteringItem(id="l1", kind="dialogue", text="Hello", speaker=[])


@pytest.mark.parametrize("definitions_key", ["$defs", "definitions"])
def test_nullable_recursive_refs_and_sibling_constraints_are_preserved(definitions_key: str) -> None:
    from novel_to_comic.ai.codex_schema import strict_output_schema

    reference = f"#/{definitions_key}/node~1value"
    source = {
        "type": "object",
        "properties": {
            "value": {"$ref": reference, "description": "The selected node"},
            "label": {"allOf": [{"type": "string", "minLength": 1}], "title": "Label"},
        },
        definitions_key: {
            "node/value": {
                "type": "object",
                "properties": {
                    "next": {"anyOf": [{"$ref": reference}, {"type": "null"}], "default": None},
                },
            },
        },
    }
    original = deepcopy(source)
    converted = strict_output_schema(source)
    _assert_strict_contract(converted)
    assert source == original
    value = converted["properties"]["value"]
    assert value["description"] == "The selected node"
    assert value["properties"]["next"]["anyOf"] == [{"$ref": reference}, {"type": "null"}]
    assert converted["properties"]["label"]["minLength"] == 1


@pytest.mark.parametrize("additional", [True, {"type": "string"}, {}])
def test_arbitrary_maps_are_rejected_without_erasing_value_type(additional: Any) -> None:
    from novel_to_comic.ai.codex_schema import strict_output_schema

    source = {"type": "object", "additionalProperties": additional}
    original = deepcopy(source)
    with pytest.raises(ValueError, match="additionalProperties"):
        strict_output_schema(source)
    assert source == original


@pytest.mark.parametrize("unsupported", [
    {"allOf": [{"type": "string"}, {"minLength": 1}]},
    {"$ref": "https://example.invalid/schema"},
    {"type": "array", "prefixItems": [{"type": "string"}]},
    {},
])
def test_unsupported_schema_constructs_fail_explicitly(unsupported: dict[str, Any]) -> None:
    from novel_to_comic.ai.codex_schema import strict_output_schema

    with pytest.raises(ValueError):
        strict_output_schema({"type": "object", "properties": {"value": unsupported}})


def test_conflicting_ref_siblings_do_not_silently_replace_constraints() -> None:
    from novel_to_comic.ai.codex_schema import strict_output_schema

    with pytest.raises(ValueError, match="conflicting"):
        strict_output_schema({
            "type": "object",
            "properties": {"value": {"$ref": "#/$defs/value", "type": "number"}},
            "$defs": {"value": {"type": "string"}},
        })


def test_blueprint_source_enum_uses_the_same_strict_scope_as_lettering_and_repairs():
    from novel_to_comic.ai.codex_schema import strict_output_schema
    from novel_to_comic.book_adaptation import _constrain_source_schema

    schema = _BlueprintDraft.model_json_schema()
    _constrain_source_schema(schema, ("source_000001", "source_000002"))
    schema = strict_output_schema(schema)
    _assert_strict_contract(schema)
    assert schema["$defs"]["_ScopedSourceUnitId"]["enum"] == ["source_000001", "source_000002"]
    assert schema["$defs"]["_BlueprintBeat"]["properties"]["source_unit_ids"]["items"] == {"$ref": "#/$defs/_ScopedSourceUnitId"}


@pytest.mark.parametrize("model", [_BlueprintDraft, _BookDraft])
def test_generation_ledger_schema_expresses_every_disposition_contract(model):
    from novel_to_comic.ai.codex_schema import strict_output_schema
    from novel_to_comic.book_adaptation import _ledger_response_schema

    raw = model.model_json_schema()
    schema = strict_output_schema(
        _ledger_response_schema(model) if model is _BlueprintDraft
        else _lettering_response_schema(model, {"char_001"})
    )
    _assert_strict_contract(schema)
    assert model.model_json_schema() == raw
    variants = {
        branch["properties"]["disposition"]["enum"][0]: branch
        for branch in schema["$defs"]["_LedgerException"]["anyOf"]
    }
    assert set(variants) == {"compressed_into", "visual_motif", "intentionally_omitted"}
    for disposition, branch in variants.items():
        properties = branch["properties"]
        assert set(branch["required"]) == set(properties)
        ids = properties["adapted_beat_ids"]
        if disposition == "intentionally_omitted":
            assert ids["maxItems"] == 0
        else:
            assert ids["minItems"] == 1
        assert ids["items"] == {"type": "string", "minLength": 1}
        if disposition != "visual_motif":
            assert properties["reason"] == {"type": "string", "minLength": 1}
        assert properties["preserved_function"]["minLength"] == 1


@pytest.mark.parametrize("owner", ["adapt", "plan"])
@pytest.mark.parametrize("signals", [set(), {"silent_beat_1", "concentration_beat_2"}])
def test_review_request_schema_limits_assessments_and_evidence_to_window(owner, signals):
    from novel_to_comic.ai.codex_schema import strict_output_schema
    from novel_to_comic.narrative_review import _review_response_schema
    schema = strict_output_schema(_review_response_schema(owner=owner, signals=signals, anchors={"beat_0001", "source_000001"}))
    _assert_strict_contract(schema)
    assessments = schema["properties"]["signal_assessments"]
    assert assessments["minItems"] == assessments["maxItems"] == len(signals)
    if signals:
        assert set(schema["$defs"]["SignalAssessment"]["properties"]["signal_id"]["enum"]) == signals
    finding = schema["$defs"]["NarrativeFinding"]["properties"]
    assert set(finding["artifact_ids"]["items"]["enum"]) == {"beat_0001", "source_000001"}
    assert finding["repair_stage"]["enum"] == (["adapt"] if owner == "adapt" else ["adapt", "plan"])
