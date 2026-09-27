"""Prepare native Claude JSON output without changing local validation schemas.

https://platform.claude.com/docs/en/build-with-claude/structured-outputs
Unsupported value constraints become field instructions, as in Anthropic's SDK.
"""

from copy import deepcopy
import json
from typing import Any


_VALUE_CONSTRAINTS = frozenset({
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "maxItems", "uniqueItems",
})


def anthropic_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Copy the schema and move unsupported bounds into descriptions.

    Require explicit values for declared object fields to avoid the exponential
    grammar cost of nested optional fields. Defaults and nullable types remain
    unchanged; this only tightens the wire schema, not local artifact validation.
    Visit schema positions only: property names and annotation data are not
    schema keywords. Enums, types, and references stay intact.
    """
    result = deepcopy(schema)

    def visit(node: Any) -> None:
        if not isinstance(node, dict):
            return
        if "properties" in node:
            node["required"] = list(node["properties"])
        removed = {}
        for key in sorted(_VALUE_CONSTRAINTS):
            if key in node:
                removed[key] = node.pop(key)
        if "minItems" in node and node["minItems"] not in (0, 1):
            removed["minItems"] = node.pop("minItems")
        if removed:
            guidance = "Required value constraints: " + json.dumps(removed, sort_keys=True)
            node["description"] = (node.get("description", "") + " " + guidance).strip()
        for key in ("properties", "$defs", "definitions", "patternProperties"):
            for child in node.get(key, {}).values():
                visit(child)
        for key in ("items", "additionalProperties"):
            visit(node.get(key))
        for key in ("anyOf", "allOf", "oneOf", "prefixItems"):
            for child in node.get(key, []):
                visit(child)

    visit(result)
    return result
