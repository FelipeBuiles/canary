"""Adapt's lettering-economy guidance and its advisory long-item note.

See docs/research/2026-10-10-adapt-plan-comics-craft.md. The note never blocks:
length is an editorial judgment, while exact protected wording stays enforced.
"""

from __future__ import annotations

from novel_to_comic.book_adaptation import (
    _BlueprintDraft,
    _LETTERING_ECONOMY_GUIDANCE,
    _long_lettering_issues,
    build_adaptation_blueprint_prompt,
    build_book_adaptation_prompt,
    build_locked_lettering_prompt,
    validate_book_adaptation,
)
from novel_to_comic.models.adaptation import LetteringItem
from novel_to_comic.protected_language import protected_language_key

from .test_book_adaptation import (
    _approved_brief,
    _blueprint_response,
    _book_adaptation,
    _source_document,
    _story_bible,
)


def _item(item_id: str, words: int, **fields) -> LetteringItem:
    values = {"kind": "caption", "delivery": "narration", "source_unit_ids": ["source_000002"], **fields}
    return LetteringItem(id=item_id, text=" ".join(["rain"] * words) + ".", **values)


def _issues(items: list[LetteringItem]):
    wordings = tuple(protected_language_key(item.text) for item in items)
    return _long_lettering_issues(items, wordings, _approved_brief())


def test_balloons_well_past_the_budget_get_one_note() -> None:
    items = [_item("lettering_a", 12), _item("lettering_b", 31), _item("lettering_c", 44)]

    issues = _issues(items)

    assert [issue.code for issue in issues] == ["long_lettering_items"]
    assert issues[0].artifact_ids == ("lettering_b", "lettering_c")
    assert issues[0].evidence[0].startswith("2 balloons or captions run past 30 words")


def test_quoted_documents_and_sound_effects_keep_their_length() -> None:
    items = [
        _item("lettering_a", 40, delivery="quoted_text"),
        _item("lettering_b", 40, kind="sfx", delivery="display"),
    ]

    assert _issues(items) == []


def test_short_protected_passage_does_not_exempt_surrounding_copy() -> None:
    long_protected = "I saw the door open. " + " ".join(["slowly"] * 30)
    item = LetteringItem(id="lettering_a", kind="caption", delivery="narration",
                         text=long_protected, source_unit_ids=["source_000001"])

    assert [issue.code for issue in _issues([item])] == ["long_lettering_items"]


def test_a_wholly_protected_long_passage_is_exempt() -> None:
    item = _item("lettering_a", 40)
    brief = _approved_brief().model_copy(update={"protected_language": (item.text,)})
    assert _long_lettering_issues([item], (protected_language_key(item.text),), brief) == []


def test_protected_dialogue_with_source_attribution_is_exempt() -> None:
    item = _item("lettering_a", 40)
    brief = _approved_brief().model_copy(update={"protected_language": (f'"{item.text}" he said.',)})
    assert _long_lettering_issues([item], (protected_language_key(item.text),), brief) == []


def test_long_items_are_editorial_in_validation() -> None:
    source, brief, adaptation = _source_document(), _approved_brief(), _book_adaptation()
    beats = list(adaptation.beats)
    lettering = [*beats[0].lettering, _item("lettering_long", 40)]
    beats[0] = beats[0].model_copy(update={"lettering": lettering})
    adaptation = adaptation.model_copy(update={"beats": tuple(beats)})

    validation = validate_book_adaptation(source, brief, adaptation)

    assert "long_lettering_items" in {issue.code for issue in validation.editorial_issues}
    assert "long_lettering_items" not in {failure.code for failure in validation.invariant_failures}


def test_every_lettering_pass_carries_the_economy_guidance() -> None:
    source, bible, brief = _source_document(), _story_bible(), _approved_brief()
    expected = _book_adaptation()
    source_ids = tuple(unit.id for unit in source.units)
    blueprint = _BlueprintDraft.model_validate(_blueprint_response(expected.beats))

    writes_words = [
        build_book_adaptation_prompt(source, bible, brief, expected.treatment),
        build_locked_lettering_prompt(
            source, bible, brief, expected.treatment, blueprint,
            primary_source_unit_ids=source_ids, shard_index=1, shard_count=1,
        ),
    ]
    structure_only = build_adaptation_blueprint_prompt(
        source, bible, brief, expected.treatment,
        primary_source_unit_ids=source_ids, owned_requirement_ids=(), shard_index=1, shard_count=1,
    )

    assert all(_LETTERING_ECONOMY_GUIDANCE in prompt for prompt in writes_words)
    # The blueprint pass writes no words, so it is not told how to trim them.
    assert _LETTERING_ECONOMY_GUIDANCE not in structure_only
