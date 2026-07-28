"""Render a model's JSON shape as prompt text, derived from the model itself.

A stage that describes its output in prose is describing it twice — once in the
Pydantic model the parser enforces, once in the sentence the writer reads — and
the two drift. Adapt asked for "the causal spine, motifs, narrator voice, and
relative narrative emphasis" without ever naming a key, and got back a
well-written treatment under eleven invented field names.

Rendering the contract from the model keeps one source of truth: change the
model and the instruction changes with it.

The gateway path cannot carry this for us. ``response_format`` with a JSON
schema is not wired end to end, and the nested drafts here compile to
``$ref``/``$defs`` that provider-side structured output does not accept, so the
contract travels in the prompt.
"""

from __future__ import annotations

import json
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from pydantic.fields import FieldInfo

_INDENT = "  "


def _is_model(annotation: Any) -> bool:
    return isinstance(annotation, type) and issubclass(annotation, BaseModel)


def _constraint_note(field: FieldInfo) -> str:
    """Summarize the constraints a writer can actually act on."""
    notes: list[str] = []
    for meta in field.metadata:
        minimum = getattr(meta, "min_length", None)
        if minimum:
            notes.append(f"at least {minimum}")
        ge = getattr(meta, "ge", None)
        if ge is not None:
            notes.append(f">= {ge}")
    if field.is_required():
        notes.append("required")
    return f"  // {', '.join(notes)}" if notes else ""


def _render_type(annotation: Any, nested: list[type[BaseModel]]) -> str:
    """Return a one-line type description, collecting nested models to define."""
    origin = get_origin(annotation)

    if origin is Literal:
        # json.dumps so the writer sees JSON vocabulary (true/false/null,
        # double-quoted strings) rather than Python reprs.
        return " | ".join(json.dumps(value) for value in get_args(annotation))

    if origin in (Union, UnionType):
        parts = [arg for arg in get_args(annotation) if arg is not type(None)]
        rendered = " | ".join(_render_type(part, nested) for part in parts)
        return f"{rendered} | null" if len(parts) < len(get_args(annotation)) else rendered

    if origin in (tuple, list, set, frozenset):
        args = [arg for arg in get_args(annotation) if arg is not Ellipsis]
        inner = _render_type(args[0], nested) if args else "string"
        return f"[{inner}, ...]"

    if origin is dict:
        return "object"

    if _is_model(annotation):
        if annotation not in nested:
            nested.append(annotation)
        return f"<{annotation.__name__}>"

    return {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
    }.get(annotation, "value")


def _render_model(model: type[BaseModel], nested: list[type[BaseModel]]) -> str:
    lines = ["{"]
    for name, field in model.model_fields.items():
        rendered = _render_type(field.annotation, nested)
        lines.append(f'{_INDENT}"{name}": {rendered}{_constraint_note(field)}')
    lines.append("}")
    return "\n".join(lines)


def describe_json_contract(model: type[BaseModel]) -> str:
    """Describe the exact JSON object a model accepts, nested types included."""
    nested: list[type[BaseModel]] = []
    root = _render_model(model, nested)

    definitions: list[str] = []
    seen: set[type[BaseModel]] = set()
    # _render_model appends to `nested` as it goes, so iterate by index.
    while nested:
        child = nested.pop(0)
        if child in seen:
            continue
        seen.add(child)
        definitions.append(f"<{child.__name__}> = {_render_model(child, nested)}")

    body = "\n\n".join([root, *definitions])
    return (
        "REQUIRED JSON SHAPE. Return exactly these keys with exactly these "
        "types. Do not add, rename, or omit keys, and do not wrap the object "
        "in another object:\n" + body
    )
