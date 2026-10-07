"""The schema-instructions output contract: a compiled schema carried as JSON-mode instructions.

Routes with ``TextModel.schema_instructions`` use it: Vertex Gemini (below) and
Claude Haiku 5.5, whose native grammar rejects full-size stage schemas such as
Extract's Story Bible ("compiled grammar is too large", 2026-10-07).

Every Gemini structured call goes through ``gemini_output_schema`` and
``schema_instructions`` (applied by ``gemini_tuning.tuned_request``); no feature
has its own transport rule. Vertex's native constrained decoding
(``responseJsonSchema``) failed three ways in direct probes on 2026-10-03:

- It often omits optional properties: four of six identical Brief calls
  returned only the required page range, which validated as an empty brief.
- It rejects schemas over an unpredictable grammar budget before generation
  (400 INVALID_ARGUMENT, no detail). Cost grows with properties after ``$ref``
  expansion, nesting depth and bounded arrays, which unroll their items;
  property kinds weigh differently, so no count predicts acceptance.
- An accepted registry-backed Extract section schema looped, repeating known
  entities until the output cap, whether fields were optional or required.

JSON mode with this schema in the instructions returned complete Brief (3/3),
registry-backed section and whole-source Extract responses. It does not enforce
the schema, so local typed validators and the bounded correction path decide
acceptance, as they do for every provider. The compiled schema requires every
declared property so the instructions ask for complete objects.
"""
from __future__ import annotations

from copy import deepcopy
import json
from typing import Any


def schema_instructions(system_prompt: str, schema: dict[str, Any]) -> str:
    """The compiled schema as JSON-mode output instructions."""
    return system_prompt + (
        "\n\nOUTPUT CONTRACT: Return one JSON object conforming to the complete schema below. "
        "Include every property it declares, with its type and constraints. Resolve local $ref "
        "entries from $defs. Return JSON only, without Markdown or commentary.\n"
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    )


def gemini_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Require every declared property; drop defaults; fixed integer enums become bounds."""
    def normalize(value: dict[str, Any]) -> dict[str, Any]:
        result = dict(value)
        result.pop("default", None)
        for key in ("properties", "$defs", "definitions"):
            if key in result:
                result[key] = {name: normalize(child) for name, child in result[key].items()}
        for key in ("items", "additionalProperties"):
            if isinstance(result.get(key), dict):
                result[key] = normalize(result[key])
        for key in ("anyOf", "oneOf", "allOf"):
            if key in result:
                result[key] = [normalize(child) for child in result[key]]
        enum = result.get("enum")
        if result.get("type") == "integer" and isinstance(enum, list) and len(enum) == 1:
            result.pop("enum")
            result["minimum"] = result["maximum"] = enum[0]
        if isinstance(result.get("properties"), dict):
            result["required"] = list(result["properties"])
        return result

    return normalize(deepcopy(schema))
