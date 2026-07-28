"""The prompt's description of a model must come from the model.

Adapt's treatment prompt described its output in prose and never named a key.
A model returned a coherent narrative treatment under eleven field names of its
own invention, the parse failed with sixteen errors, and the retry — which
re-sent the same key-less prose — failed the same way.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.json_contract import describe_json_contract


class _Child(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(min_length=1)
    weight: int = Field(ge=1)


class _Parent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    mode: Literal["fast", "slow"]
    flag: Literal[False] = False
    note: str | None = None
    tags: tuple[str, ...] = ()
    children: tuple[_Child, ...] = Field(min_length=1)


def test_every_field_is_named_with_its_type() -> None:
    contract = describe_json_contract(_Parent)

    assert '"name": string' in contract
    assert '"tags": [string, ...]' in contract
    assert '"children": [<_Child>, ...]' in contract


def test_nested_models_are_defined_rather_than_only_referenced() -> None:
    contract = describe_json_contract(_Parent)

    assert "<_Child> = {" in contract
    assert '"label": string' in contract
    assert '"weight": integer' in contract


def test_literals_are_rendered_in_json_vocabulary_not_python() -> None:
    # A writer reading `'fast'` or `False` is being shown Python.
    contract = describe_json_contract(_Parent)

    assert '"mode": "fast" | "slow"' in contract
    assert '"flag": false' in contract
    assert "'fast'" not in contract
    assert "False" not in contract


def test_optional_fields_admit_null() -> None:
    assert '"note": string | null' in describe_json_contract(_Parent)


def test_constraints_a_writer_can_act_on_are_stated() -> None:
    contract = describe_json_contract(_Parent)

    assert '"children": [<_Child>, ...]  // at least 1, required' in contract
    assert '"weight": integer  // >= 1, required' in contract


def test_the_contract_forbids_inventing_keys() -> None:
    contract = describe_json_contract(_Parent)

    assert "exactly these keys" in contract
    assert "Do not add, rename, or omit keys" in contract


def test_a_self_referencing_model_terminates() -> None:
    class _Node(BaseModel):
        name: str
        children: tuple["_Node", ...] = ()

    _Node.model_rebuild()
    contract = describe_json_contract(_Node)

    assert '"children": [<_Node>, ...]' in contract
