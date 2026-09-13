from copy import deepcopy

import pytest
from pydantic import BaseModel, Field, ValidationError

from novel_to_comic.ai.anthropic_schema import anthropic_output_schema
from novel_to_comic.book_adaptation import _BlueprintDraft
from novel_to_comic.page_planning import _BookPlanDraft, _BookPageMap


class BoundedValue(BaseModel):
    minimum: int = Field(ge=1, le=10)
    label: str = Field(min_length=2, max_length=20)
    entries: list[int] = Field(min_length=2, max_length=4)


def test_bounds_become_instructions_without_weakening_local_validation():
    schema = BoundedValue.model_json_schema()
    original = deepcopy(schema)
    prepared = anthropic_output_schema(schema)
    assert schema == original
    number = prepared["properties"]["minimum"]
    assert "minimum" not in number
    assert '"minimum": 1' in number["description"]
    assert '"maximum": 10' in number["description"]
    assert "minLength" not in prepared["properties"]["label"]
    assert "minItems" not in prepared["properties"]["entries"]
    assert prepared["required"] == schema["required"]
    with pytest.raises(ValidationError):
        BoundedValue(minimum=0, label="x", entries=[])


@pytest.mark.parametrize("model", [_BlueprintDraft, _BookPlanDraft, _BookPageMap])
def test_real_adapt_and_plan_schemas_have_no_unsupported_bounds(model):
    schema = model.model_json_schema()
    original = deepcopy(schema)
    prepared = anthropic_output_schema(schema)
    assert schema == original
    def check(node):
        if not isinstance(node, dict):
            return
        assert not {"minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                    "multipleOf", "minLength", "maxLength", "maxItems", "uniqueItems"}.intersection(node)
        assert node.get("minItems", 0) in (0, 1)
        for key in ("properties", "$defs", "definitions"):
            for child in node.get(key, {}).values():
                check(child)
        check(node.get("items"))
        for key in ("anyOf", "allOf"):
            for child in node.get(key, []):
                check(child)
    check(prepared)


def test_refs_unions_and_supported_array_minimum_are_preserved():
    schema = {"$defs": {"Value": BoundedValue.model_json_schema()}, "anyOf": [
        {"type": "null"}, {"type": "array", "minItems": 1, "items": {"$ref": "#/$defs/Value"}},
    ]}
    prepared = anthropic_output_schema(schema)
    assert prepared["anyOf"] == schema["anyOf"]
    assert "minimum" not in prepared["$defs"]["Value"]["properties"]["minimum"]
