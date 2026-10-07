"""Promoted Gemini behavior remains local to its requests and experiment context."""
import asyncio
from copy import deepcopy

import pytest

from novel_to_comic.ai.gemini_schema import gemini_output_schema
from novel_to_comic.extraction_schema import extraction_schema
from novel_to_comic.gemini_tuning import (
    ADDENDA, gemini_tuning_enabled, gemini_tuning_override, tuned_request, tuned_user_content,
)


@pytest.mark.parametrize("feature", ADDENDA)
def test_checklists_follow_context_once_and_leave_other_providers_unchanged(feature):
    context = "Author's exact words and protected visual anchors."
    tuned = tuned_user_content("gemini-3.8-flash", feature, context)
    assert tuned == context + ADDENDA[feature]
    assert tuned_user_content("gemini-3.8-flash", feature, tuned) == tuned
    for model in ("gpt-6.1-sol", "claude-opus-5-5", "mimo-v2.6-pro", "deepseek-v4.1-flash"):
        assert tuned_user_content(model, feature, context) == context


def test_review_and_uncovered_features_retain_their_original_prompt():
    for feature in ("plan.narrative_review", "extract.source_review", "ocr.page", "text.generate"):
        assert tuned_user_content("gemini-3.8-flash", feature, "Review.") == "Review."


def test_labs_control_does_not_disable_a_concurrent_production_request():
    async def run():
        async def control():
            with gemini_tuning_override(False):
                await asyncio.sleep(0)
                return gemini_tuning_enabled("gemini-3.8-flash")

        async def production():
            await asyncio.sleep(0)
            return gemini_tuning_enabled("gemini-3.8-flash")

        return await asyncio.gather(control(), production())

    assert asyncio.run(run()) == [False, True]
    assert gemini_tuning_enabled("gemini-3.8-flash")


def _objects(node):
    if isinstance(node, dict):
        if isinstance(node.get("properties"), dict):
            yield node
        for value in node.values():
            yield from _objects(value)
    elif isinstance(node, list):
        for value in node:
            yield from _objects(value)


def test_gemini_schema_requires_every_declared_property_and_keeps_nullability():
    # Vertex's decoder often omits optional fields: an empty Brief, 2026-10-03.
    schema = {"type": "object", "$defs": {"PageNumber": {"type": "integer", "enum": [7]}},
              "properties": {"default": {"type": "string", "default": "local default"},
                             "note": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
                             "page": {"$ref": "#/$defs/PageNumber"}}, "required": ["page"]}
    original = deepcopy(schema)
    actual = gemini_output_schema(schema)
    assert actual["required"] == ["default", "note", "page"]
    assert actual["properties"]["default"] == {"type": "string"}
    assert actual["properties"]["note"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert actual["properties"]["page"] == {"$ref": "#/$defs/PageNumber"}
    assert actual["$defs"]["PageNumber"] == {"type": "integer", "minimum": 7, "maximum": 7}
    assert schema == original
    assert gemini_output_schema(actual) == actual


def test_every_object_in_real_stage_schemas_requires_all_its_properties():
    from novel_to_comic.briefing import brief_inference_schema

    for schema in (brief_inference_schema(), extraction_schema(), _registry_section_schema()):
        for node in _objects(gemini_output_schema(schema)):
            assert node["required"] == list(node["properties"])


def test_every_gemini_structured_request_carries_its_compiled_schema_as_json_mode_instructions():
    import json

    request = {"system_prompt": "Rules.", "user_content": "Source.",
               "feature": "extract.story_bible", "json_schema": extraction_schema()}
    for model in ("gpt-6.1-sol", "claude-opus-5-5", "mimo-v2.6-pro", "deepseek-v4.1-flash"):
        assert tuned_request(model, request) is request
    for model in ("gemini-3.8-flash", "claude-haiku-5-5", "bedrock-claude-haiku-5-5"):
        for feature in ("extract.story_bible", "extract.sequences", "brief.infer", "plan.detail", "text.generate"):
            tuned = tuned_request(model, {**request, "feature": feature})
            assert tuned["json_schema"] is None and tuned["json_mode"] is True
            assert tuned["system_prompt"].startswith("Rules.\n\nOUTPUT CONTRACT:")
            assert json.loads(tuned["system_prompt"].split("\n")[-1]) == gemini_output_schema(request["json_schema"])
            if model.startswith("claude") or model.startswith("bedrock"):
                assert tuned["user_content"] == "Source."
        plain = tuned_request(model, {**request, "json_schema": None})
        assert plain["system_prompt"] == "Rules." and "json_mode" not in plain


def _registry_section_schema():
    from novel_to_comic.extraction_sections import section_schema
    from novel_to_comic.models.story_bible import Character, Location, StoryBible

    registry = StoryBible.model_construct(
        characters=[Character.model_construct(id="part0001_char_carl")],
        locations=[Location.model_construct(id="part0001_loc_street")], props=[],
    )
    return section_schema(registry, "part0002_", continuable=True)


def test_registry_section_keeps_its_domain_variants_and_id_references():
    schema = _registry_section_schema()
    actual = gemini_output_schema(schema)
    assert len(actual["properties"]["characters"]["items"]["anyOf"]) == len(
        schema["properties"]["characters"]["items"]["anyOf"])
    assert actual["$defs"]["KnownCharacterId"] == schema["$defs"]["KnownCharacterId"]
    assert actual["$defs"]["Scene"]["properties"]["location_id"] == schema["$defs"]["Scene"]["properties"]["location_id"]
