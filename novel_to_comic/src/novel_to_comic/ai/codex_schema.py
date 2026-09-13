"""Request normalization for gateway and Codex strict structured output.

Rules: https://developers.openai.com/api/docs/guides/structured-outputs
Traversal follows OpenAI's public Python SDK schema conversion strategy, without
importing its private helpers. Domain schemas and local validation stay unchanged.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any


_ANNOTATIONS = frozenset({"title", "description", "default", "examples", "$comment"})
_UNSUPPORTED = frozenset({
    "oneOf", "not", "if", "then", "else", "dependentRequired", "dependentSchemas",
    "patternProperties", "propertyNames", "unevaluatedProperties", "prefixItems",
    "contains", "unevaluatedItems", "$dynamicRef", "$recursiveRef",
})


def strict_output_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Return an independent strict request schema, preserving declared value types.

    All declared object fields become required and objects become closed. Existing
    nullable unions remain nullable; defaulted non-nullable fields do not acquire
    null as a new value. As in OpenAI's converter, only null defaults are removed.

    Open maps cannot be represented by strict output without changing their data
    contract, so they raise ValueError rather than silently becoming empty objects.
    Single-member allOf and local refs with compatible siblings are expanded;
    unsupported intersections or conflicting siblings fail explicitly. This is a
    normalizer for the repository's schemas, not a complete provider validator.
    """
    root = deepcopy(schema)

    def fail(path: str, reason: str) -> ValueError:
        return ValueError(f"Unsupported strict output schema at {path}: {reason}")

    def resolve(reference: Any, path: str) -> dict[str, Any]:
        if not isinstance(reference, str) or not (
            reference == "#" or reference.startswith("#/")
        ):
            raise fail(path, "$ref must be a local JSON pointer")
        target: Any = root
        if reference != "#":
            for token in reference[2:].split("/"):
                key = token.replace("~1", "/").replace("~0", "~")
                if not isinstance(target, dict) or key not in target:
                    raise fail(path, "$ref target does not exist")
                target = target[key]
        if not isinstance(target, dict):
            raise fail(path, "$ref target must be a schema object")
        return target

    def merge(base: dict[str, Any], siblings: dict[str, Any], path: str) -> dict[str, Any]:
        # Overwriting assertions can loosen a ref/intersection rather than
        # strengthen it. Only annotations may override different existing values.
        for key, value in siblings.items():
            if key in base and base[key] != value and key not in _ANNOTATIONS:
                raise fail(path, f"conflicting {key} constraints")
        return {**base, **siblings}

    def normalize(node: Any, path: str, expanding: tuple[str, ...] = ()) -> dict[str, Any]:
        if not isinstance(node, dict):
            raise fail(path, "expected a schema object")
        node = dict(node)
        unsupported = _UNSUPPORTED.intersection(node)
        if unsupported:
            raise fail(path, f"unsupported keyword {sorted(unsupported)[0]}")
        if "allOf" in node:
            members = node.pop("allOf")
            if not isinstance(members, list) or len(members) != 1:
                raise fail(path, "allOf must have exactly one member")
            member = members[0]
            if not isinstance(member, dict):
                raise fail(path, "allOf member must be a schema object")
            return normalize(merge(member, node, path), path, expanding)
        if node.get("default", False) is None:
            del node["default"]
        if "$ref" in node:
            reference = node["$ref"]
            target = resolve(reference, path)
            if len(node) == 1:
                return node
            if reference in expanding:
                raise fail(path, "recursive $ref siblings cannot be expanded")
            del node["$ref"]
            return normalize(merge(target, node, path), path, (*expanding, reference))

        for keyword in ("$defs", "definitions"):
            if keyword in node:
                definitions = node[keyword]
                if not isinstance(definitions, dict):
                    raise fail(path, f"{keyword} must be an object")
                node[keyword] = {
                    name: normalize(child, f"{path}/{keyword}/{name}", expanding)
                    for name, child in definitions.items()
                }
        kind = node.get("type")
        if kind == "object" or (isinstance(kind, list) and "object" in kind):
            if "additionalProperties" in node and node["additionalProperties"] is not False:
                raise fail(path, "additionalProperties maps cannot be represented by strict output")
            properties = node.get("properties", {})
            if not isinstance(properties, dict):
                raise fail(path, "properties must be an object")
            required = node.get("required", [])
            if not isinstance(required, list) or any(name not in properties for name in required):
                raise fail(path, "required must name declared properties")
            node["additionalProperties"] = False
            node["required"] = list(properties)
            node["properties"] = {
                name: normalize(child, f"{path}/properties/{name}", expanding)
                for name, child in properties.items()
            }
        elif "properties" in node or "additionalProperties" in node:
            raise fail(path, "object keywords require an explicit object type")
        if kind == "array" or (isinstance(kind, list) and "array" in kind):
            if not isinstance(node.get("items"), dict):
                raise fail(path, "arrays require a single items schema")
            node["items"] = normalize(node["items"], f"{path}/items", expanding)
        if "anyOf" in node:
            members = node["anyOf"]
            if not isinstance(members, list) or not members:
                raise fail(path, "anyOf must contain schemas")
            node["anyOf"] = [
                normalize(child, f"{path}/anyOf/{index}", expanding)
                for index, child in enumerate(members)
            ]
        elif kind is None:
            raise fail(path, "unconstrained values require an explicit type")
        return node

    result = normalize(root, "#")
    if result.get("type") != "object" or "anyOf" in result:
        raise fail("#", "root must be an object, not a union")
    return result
