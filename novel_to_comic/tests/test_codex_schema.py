from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest
from pydantic import ValidationError

from novel_to_comic.book_adaptation import _BlueprintDraft, _BookDraft, _LetteringDraft
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


@pytest.mark.parametrize("model", [
    _BlueprintDraft, _BookDraft, _LetteringDraft, BookAdaptation, _BookPageMap, _BookPlanDraft,
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
