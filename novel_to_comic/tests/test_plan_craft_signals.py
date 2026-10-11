"""Plan's advisory comics-craft signals and page-side derivation.

See docs/research/2026-10-10-adapt-plan-comics-craft.md. Every signal here is
an editorial note: none may become a blocking failure or trigger a repair.
"""

from __future__ import annotations

import json

import pytest

from novel_to_comic.models.adaptation import ContinuityTransition, LetteringItem
from novel_to_comic.models.page import (
    ApprovedPageRange,
    ApprovedVisualReferenceInventory,
    ComicPage,
    PageContent,
    PanelCamera,
)
from novel_to_comic.page_planning import (
    _BookPageMap,
    _build_page_map_prompt,
    _canonicalize_page_map,
    _crowded_lettering_issues,
    _detail_batch_prompt,
    _page_turn_side_issues,
    _planning_view,
    _unestablished_location_issues,
    _uniform_panel_count_issues,
    build_book_plan_prompt,
    page_side,
    validate_book_plan,
)

from .test_page_planning import _adaptation


def _page(number: int, beat_ids: tuple[str, ...], *, turn: str = "none", panels: int = 1,
          shot: str = "medium", lettering: tuple[LetteringItem, ...] = ()) -> ComicPage:
    content = [
        PageContent(
            id=f"page_{number:03d}_content_{order:03d}",
            order=order,
            beat_ids=list(beat_ids),
            camera=PanelCamera(shot=shot, angle="eye_level"),
            visual_intent="A drawn moment.",
            lettering=list(lettering) if order == 1 else [],
        )
        for order in range(1, panels + 1)
    ]
    return ComicPage(
        page_number=number,
        revision=1,
        adaptation_revision=2,
        adaptation_sha256="c" * 64,
        page_turn_role=turn,
        spread_role=page_side(number),
        emphasis="prolongation",
        density_intent="standard",
        layout_intent="Panels in order.",
        content=content,
        reading_order=[
            item for panel in content for item in (panel.id, *(entry.id for entry in panel.lettering))
        ],
    )


def _reveal_adaptation():
    adaptation = _adaptation()
    beats = list(adaptation.beats)
    beats[1] = beats[1].model_copy(update={"narrative_function": "peak", "story_functions": ["reveal"]})
    return adaptation.model_copy(update={"beats": tuple(beats)})


def test_page_one_is_a_right_hand_page_and_sides_alternate() -> None:
    assert [page_side(number) for number in range(1, 6)] == ["right", "left", "right", "left", "right"]


def test_a_model_authored_page_side_is_dropped_before_validation() -> None:
    page_map = _canonicalize_page_map({"rhythm_summary": "Brisk.", "pages": [{
        "beat_ids": ["beat_0001", "beat_0002"], "lettering_ids": ["lettering_0001", "lettering_0002"],
        "spread_role": "left", "emphasis": "initial", "density_intent": "standard",
        "rhythm_intent": "Approach and escape.",
    }]})

    assert page_map.pages[0].page_number == 1


def test_reveal_on_a_right_hand_page_is_seen_beside_its_setup() -> None:
    adaptation = _reveal_adaptation()
    pages = [
        _page(1, ("beat_0001",)),
        _page(2, ("beat_0001",), turn="setup"),
        _page(3, ("beat_0002",), turn="reveal"),
    ]

    issues = {issue.code: issue for issue in _page_turn_side_issues(adaptation, pages)}

    assert issues["reveal_on_right_page"].artifact_ids == ("page_003",)
    assert issues["turn_setup_on_left_page"].artifact_ids == ("page_002",)


def test_reveal_after_a_turn_needs_no_note() -> None:
    adaptation = _reveal_adaptation()
    pages = [_page(1, ("beat_0001",), turn="setup"), _page(2, ("beat_0002",), turn="reveal")]

    assert _page_turn_side_issues(adaptation, pages) == []


def test_page_side_notes_are_editorial_not_blocking() -> None:
    adaptation = _adaptation()
    beats = adaptation.beats
    pages = [
        _page(1, (beats[0].id,), lettering=tuple(beats[0].lettering)),
        _page(2, (beats[1].id,), turn="cliffhanger", lettering=tuple(beats[1].lettering)),
    ]
    pages = [page.model_copy(update={"adaptation_sha256": adaptation.content_sha256,
                                      "adaptation_revision": adaptation.revision}) for page in pages]

    validation = validate_book_plan(
        adaptation, ApprovedVisualReferenceInventory(), ApprovedPageRange(minimum=2, maximum=2), pages,
    )

    assert "turn_setup_on_left_page" in {issue.code for issue in validation.editorial_issues}
    assert not any("turn" in failure.code or "spread" in failure.code
                   for failure in validation.invariant_failures)


def _words(item_id: str, count: int) -> LetteringItem:
    return LetteringItem(id=item_id, kind="dialogue", text=" ".join(["word"] * count),
                         speaker="Johansen", source_unit_ids=["source_000002"])


def test_crowded_hybrid_page_names_its_word_load() -> None:
    crowded = _page(1, ("beat_0001",), panels=4,
                    lettering=(_words("lettering_a", 45), _words("lettering_b", 30)))
    light = _page(2, ("beat_0002",), panels=3, lettering=(_words("lettering_c", 40),))

    issues = _crowded_lettering_issues([crowded, light])

    assert [issue.code for issue in issues] == ["crowded_lettering"]
    assert issues[0].artifact_ids == ("page_001",)
    assert issues[0].evidence[1] == "Page 1: 75 words across 4 panels; panels [1] each hold more than 50."


def test_a_long_page_without_a_crowded_panel_is_still_crowded() -> None:
    page = _page(1, ("beat_0001",), panels=5)
    page = page.model_copy(update={"content": tuple(
        panel.model_copy(update={"lettering": (_words(f"l_{panel.order}", 45),)}) for panel in page.content
    )})

    issues = _crowded_lettering_issues([page])

    assert issues[0].evidence[1] == "Page 1: 225 words across 5 panels."


def test_four_pages_with_one_panel_count_read_as_a_grid() -> None:
    pages = [_page(number, ("beat_0001",), panels=2) for number in range(1, 5)]
    pages.append(_page(5, ("beat_0002",), panels=4))

    issues = _uniform_panel_count_issues(pages)

    assert len(issues) == 1
    assert issues[0].artifact_ids == ("page_001", "page_002", "page_003", "page_004")
    assert _uniform_panel_count_issues(pages[:3]) == []


def _moving_adaptation():
    adaptation = _adaptation()
    beats = list(adaptation.beats)
    beats[1] = beats[1].model_copy(update={"transitions": [ContinuityTransition(
        dimension="place", scope_id="thread_voyage", from_state="Deck", to_state="Reef",
        description="The yacht reaches the reef.",
    )]})
    return adaptation.model_copy(update={"beats": tuple(beats)})


def test_scene_change_shown_only_in_close_ups_is_unestablished() -> None:
    adaptation = _moving_adaptation()
    pages = [_page(1, ("beat_0001",)), _page(2, ("beat_0002",), panels=2, shot="close_up")]

    issues = _unestablished_location_issues(adaptation, pages)

    assert issues[0].code == "unestablished_location_change"
    assert issues[0].artifact_ids == ("beat_0002", "page_002")


def test_scene_change_with_a_wide_panel_is_established() -> None:
    adaptation = _moving_adaptation()
    pages = [_page(1, ("beat_0001",)), _page(2, ("beat_0002",), panels=2, shot="wide")]

    assert _unestablished_location_issues(adaptation, pages) == []


def test_plan_prompts_teach_page_sides_and_panel_density_to_every_model() -> None:
    adaptation = _adaptation()
    target = ApprovedPageRange(minimum=2, maximum=2)
    page_map = _BookPageMap.model_validate({"rhythm_summary": "Brisk.", "pages": [{
        "page_number": 1, "beat_ids": ["beat_0001", "beat_0002"],
        "lettering_ids": ["lettering_0001", "lettering_0002"], "emphasis": "initial",
        "density_intent": "standard", "rhythm_intent": "Approach and escape.",
    }]})

    map_prompt = _build_page_map_prompt(adaptation, target)
    book_prompt = build_book_plan_prompt(adaptation, ApprovedVisualReferenceInventory(), target)
    detail_prompt = _detail_batch_prompt(adaptation, ApprovedVisualReferenceInventory(), page_map,
                                         start=0, stop=1)

    for prompt in (map_prompt, book_prompt):
        assert "page 1 is a right-hand page" in prompt
    for prompt in (book_prompt, detail_prompt):
        assert "Comics average about five panels a page" in prompt
    assert '"page_side":"right"' in detail_prompt
    assert "spreads, emphasis" not in map_prompt


def test_planning_view_counts_each_beats_words() -> None:
    view = _planning_view(_adaptation())

    assert [beat["lettering_words"] for beat in view["beats"]] == [5, 3]



@pytest.mark.parametrize("cross_page", [False, True])
def test_establishing_panel_can_belong_to_the_next_beat(cross_page) -> None:
    adaptation = _moving_adaptation()
    next_beat = adaptation.beats[-1].model_copy(update={"id": "beat_0003", "order": 3, "transitions": ()})
    adaptation = adaptation.model_copy(update={"beats": (*adaptation.beats, next_beat)})
    close = _page(2, ("beat_0002",), shot="close_up")
    wide = _page(3, ("beat_0003",), shot="wide")
    pages = [close, wide] if cross_page else [close.model_copy(update={"content": (
        close.content[0], wide.content[0].model_copy(update={"order": 2}),
    )})]

    assert _unestablished_location_issues(adaptation, pages) == []


def test_establishing_panel_in_another_location_does_not_clear_the_previous_move() -> None:
    adaptation = _moving_adaptation()
    next_beat = adaptation.beats[-1].model_copy(update={"id": "beat_0003", "order": 3})
    adaptation = adaptation.model_copy(update={"beats": (*adaptation.beats, next_beat)})
    pages = [_page(2, ("beat_0002",), shot="close_up"), _page(3, ("beat_0003",), shot="wide")]

    issues = _unestablished_location_issues(adaptation, pages)
    assert issues[0].artifact_ids == ("beat_0002", "page_002")


@pytest.mark.parametrize("integrated,budget", [(True, "110 words and 10 lettering items"), (False, "210 words")])
def test_allocation_uses_edition_budget_and_approved_tone(integrated, budget) -> None:
    from novel_to_comic.gemini_tuning import tuned_user_content

    adaptation = _adaptation()
    target = ApprovedPageRange(minimum=2, maximum=2)
    for feature, prompt in (
        ("plan.map", _build_page_map_prompt(adaptation, target, integrated_lettering=integrated,
                                           story_tone="Quiet, restrained dread.")),
        ("plan.book", build_book_plan_prompt(adaptation, ApprovedVisualReferenceInventory(), target,
                                            integrated_lettering=integrated, story_tone="Quiet, restrained dread.")),
    ):
        assert budget in prompt
        assert json.loads(prompt.split("\n", 1)[1])["approved_story_tone"] == "Quiet, restrained dread."
        effective = tuned_user_content("gemini-3.8-flash", feature, prompt)
        assert "Never use the same panel count" not in effective
        assert "not a rotation or quota" in effective


def test_detail_batches_share_the_layout_vocabulary_and_tone() -> None:
    from novel_to_comic.page_planning import _page_map_entry

    pages = [_page(number, ("beat_0001",), panels=3) for number in range(1, 5)]
    page_map = _BookPageMap(rhythm_summary="Steady rectangular tiers for restrained dread.",
                           pages=tuple(_page_map_entry(page) for page in pages))
    for start, stop in ((0, 2), (2, 4)):
        prompt = _detail_batch_prompt(_adaptation(), ApprovedVisualReferenceInventory(), page_map,
                                      start=start, stop=stop, story_tone="Restrained dread.")
        context = json.loads(prompt.split("\n", 1)[1])
        assert context["global_rhythm_summary"] == page_map.rhythm_summary
        assert context["approved_story_tone"] == "Restrained dread."
        assert context["target_page_numbers"] == list(range(start + 1, stop + 1))
        assert "Preserve author-pinned geometry, panel sequence and lettering order" in prompt
        assert "not a rotation or quota" in prompt
