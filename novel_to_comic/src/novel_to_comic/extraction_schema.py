"""Extraction request schemas, distinct from the persisted Story Bible.

Code owns counts, provenance, and registry hydration. The model supplies new
story facts; it never needs to reproduce an established identity's fields.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.extraction_review import ExtractionReview, constrain_review_schema
from novel_to_comic.models.story_bible import StoryBible


class CharacterParticipation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: str
    scene_id: str
    classification: Literal["direct_action", "staged_recollection", "background_only"]
    source_quote: str = Field(min_length=1)


class ExtractionParticipation(BaseModel):
    character_participation: list[CharacterParticipation]


class _ExtractionOutput(StoryBible):
    character_participation: list[CharacterParticipation]
    source_review: ExtractionReview = Field(default_factory=ExtractionReview)


def _omit(schema: dict, *fields: str) -> None:
    for field in fields:
        schema["properties"].pop(field, None)
    schema["required"] = [field for field in schema.get("required", []) if field not in fields]


def _close_objects(schema: dict) -> None:
    """Keep constraints explicit for runtimes with different schema adapters."""
    if schema.get("type") == "object":
        schema["additionalProperties"] = False
    for field in ("properties", "$defs"):
        for child in schema.get(field, {}).values():
            _close_objects(child)
    if isinstance(schema.get("items"), dict):
        _close_objects(schema["items"])
    for child in schema.get("anyOf", []):
        _close_objects(child)


def _prune_definitions(schema: dict) -> None:
    """Do not resend the final-review DTOs in every section request."""
    definitions = schema["$defs"]

    def references(value):
        if isinstance(value, dict):
            ref = value.get("$ref", "")
            if ref.startswith("#/$defs/"):
                yield ref.removeprefix("#/$defs/")
            for child in value.values():
                yield from references(child)
        elif isinstance(value, list):
            for child in value:
                yield from references(child)

    pending = set(references({key: value for key, value in schema.items() if key != "$defs"}))
    used = set()
    while pending:
        name = pending.pop()
        if name not in used:
            used.add(name)
            pending.update(set(references(definitions[name])) - used)
    schema["$defs"] = {name: value for name, value in definitions.items() if name in used}


def extraction_schema(*, registry: StoryBible | None = None, prefix: str | None = None) -> dict:
    """Constrain section IDs and allow known entities to emit changes only.

    No source-derived facts are required just to satisfy formatting conventions.
    Semantic reference and continuity checks still run after local hydration.
    """
    schema = _ExtractionOutput.model_json_schema()
    _omit(schema, "revision", "excluded_entities", "total_scenes")
    definitions = schema["$defs"]
    for kind in ("Character", "Location", "Prop"):
        _omit(definitions[kind], "origin")
    _omit(definitions["Scene"], "part_id", "source_start_offset")
    _omit(definitions["StorySequence"], "part_id")
    if prefix is not None:
        _omit(schema, "source_review")  # the final source/organization pass owns this review
        _omit(schema, "sequences")  # the organization call owns the part's sequences
        if registry is not None:
            _omit(schema, "title", "author", "style_notes")
        new_id = {"type": "string", "pattern": f"^{re.escape(prefix)}[A-Za-z0-9_-]+$"}
        definitions["Scene"]["properties"]["id"] = deepcopy(new_id)

        # Reuse ID definitions instead of repeating enums on every citation.
        # Large series use an exact regex union to stay within provider enum
        # budgets without dropping a single registered identity.
        registry_size = sum(len(getattr(registry, kind)) for kind in ("characters", "locations", "props")) if registry else 0
        known_references: dict[str, dict] = {}
        for field, kind in (("characters", "Character"), ("locations", "Location"), ("props", "Prop")):
            ids = [entity.id for entity in getattr(registry, field)] if registry else []
            if not ids:
                continue
            definition = f"Known{kind}Id"
            use_pattern = registry_size > 900 or (len(ids) > 250 and sum(map(len, ids)) > 15000)
            constraint = ({"pattern": "^(?:" + "|".join(re.escape(value) for value in ids) + ")$"}
                          if use_pattern else {"enum": ids})
            definitions[definition] = {"type": "string", **constraint}
            known_references[field] = {"$ref": f"#/$defs/{definition}"}

        def reference(field: str) -> dict:
            known = known_references.get(field)
            return {"anyOf": [deepcopy(known), deepcopy(new_id)]} if known else deepcopy(new_id)

        scene = definitions["Scene"]["properties"]
        scene["character_ids"]["items"] = reference("characters")
        scene["location_id"] = reference("locations")
        definitions["CharacterRelationship"]["properties"]["character_id"] = reference("characters")
        participation = definitions["CharacterParticipation"]["properties"]
        participation["character_id"] = reference("characters")
        participation["scene_id"] = deepcopy(new_id)
        definitions["StoryPosition"]["properties"]["scene_id"] = deepcopy(new_id)

        for field, kind in (("characters", "Character"), ("locations", "Location"), ("props", "Prop")):
            definitions[kind]["properties"]["id"] = deepcopy(new_id)
            if kind == "Character":
                definitions[kind]["properties"]["first_appearance_scene"] = deepcopy(new_id)
            elif kind == "Prop":
                definitions[kind]["properties"]["first_appearance_scene"] = {
                    "anyOf": [deepcopy(new_id), {"type": "null"}],
                }
            if field not in known_references:
                continue
            # A minimal reference avoids retyping identity and cannot drift in
            # name, gender, anchor, or other established physical identity.
            identity = {"id": deepcopy(known_references[field])}
            minimal = {"type": "object", "properties": identity, "required": ["id"]}
            fields = ["appearance_states", "appearance_timeline", "aliases"]
            if field == "characters":
                fields.extend(["relationships", "distinguishing_features", "cast_required"])
            updates = {name: deepcopy(definitions[kind]["properties"][name]) for name in fields}
            delta = {"type": "object", "properties": {**identity, **updates}, "required": ["id", *fields]}
            schema["properties"][field]["items"] = {
                "anyOf": [minimal, delta, {"$ref": f"#/$defs/{kind}"}],
            }
    else:
        constrain_review_schema(schema)
    _close_objects(schema)
    _prune_definitions(schema)
    return schema
