"""An author's note carried to every page it touches, and no further."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from novel_to_comic import note_scope
from novel_to_comic.correction_interpreter import ChangeReading, claim_for
from novel_to_comic.models.adaptation import AdaptationBrief, LetteringItem
from novel_to_comic.models.page import (
    ApprovedPageRange,
    ApprovedVisualReference,
    ApprovedVisualReferenceInventory,
    BookPlan,
    PlannedPageRevision,
)
from novel_to_comic.note_scope import BeatClaim, LineClaim, LookClaim, NoteScopeError
from novel_to_comic.page_planning import validate_book_plan
from novel_to_comic.target_artifacts import TargetArtifacts

from .test_page_planning import _adaptation, _pages_from

ENTITIES = ("location_alert", "character_johansen")


def _inventory(*, with_look: bool = False) -> ApprovedVisualReferenceInventory:
    references = [
        ApprovedVisualReference(id="ref_johansen", entity_id="character_johansen", kind="character",
                                label="Johansen", visual_anchor="gaunt Norwegian sailor; rain-dark pea coat"),
        ApprovedVisualReference(id="ref_alert", entity_id="location_alert", kind="location", label="The Alert",
                                visual_anchor="small steam yacht; black hull; single funnel"),
    ]
    if with_look:
        references.append(ApprovedVisualReference(
            id="ref_johansen_bare", entity_id="character_johansen", appearance_state_id="bareheaded",
            kind="character", label="Johansen", visual_anchor="gaunt Norwegian sailor; pea coat; no cap"))
    return ApprovedVisualReferenceInventory(references=references)


def _book():
    adaptation = _adaptation()
    pages = _pages_from(adaptation, [["beat_0001"], ["beat_0002"]], entity_ids=ENTITIES)
    return adaptation, pages


def _failures(adaptation, pages, inventory=None):
    return validate_book_plan(adaptation, inventory or _inventory(), ApprovedPageRange(minimum=2, maximum=2),
                              pages).invariant_failures


def test_an_amendment_keeps_pages_whose_beats_did_not_change_valid() -> None:
    adaptation, pages = _book()
    claim = LineClaim(lettering_item_id="lettering_0002", text="“Hard about!”")
    amended, revised = note_scope.line_amendment(adaptation, pages, claim, _inventory(), "note_aaaaaaaaaaaa")

    assert amended.revision == adaptation.revision + 1
    assert amended.amendments[-1].changed_beat_ids == ("beat_0002",)
    assert sorted(revised) == [2]
    assert pages[0].cites_adaptation(amended)
    assert not pages[1].cites_adaptation(amended)
    assert revised[2].cites_adaptation(amended)
    assert revised[2].content[0].lettering[0].text == "“Hard about!”"
    assert note_scope.new_failures(_failures(adaptation, pages),
                                   _failures(amended, [pages[0], revised[2]])) == ()


def test_an_adaptation_without_amendments_keeps_its_hash() -> None:
    adaptation = _adaptation()
    assert "amendments" not in adaptation.model_dump(mode="json")
    assert type(adaptation).model_validate(adaptation.model_dump(mode="json")).content_sha256 == \
        adaptation.content_sha256


def test_a_full_adapt_run_does_not_inherit_earlier_pins() -> None:
    adaptation, pages = _book()
    rerun = adaptation.model_copy(update={"revision": adaptation.revision + 1, "content_sha256": ""})
    rerun = type(adaptation).model_validate(rerun.model_dump(mode="json"))
    assert not pages[0].cites_adaptation(rerun)


def test_a_line_change_refuses_what_it_cannot_say() -> None:
    adaptation, pages = _book()
    with pytest.raises(NoteScopeError, match="already reads"):
        note_scope.line_amendment(adaptation, pages, LineClaim(lettering_item_id="lettering_0002",
                                                               text="“Hard to port!”"), _inventory(), "note_x")
    with pytest.raises(NoteScopeError, match="Only dialogue"):
        note_scope.line_amendment(adaptation, pages, LineClaim(lettering_item_id="lettering_0001",
                                                               speaker_entity_id="character_johansen"),
                                  _inventory(), "note_x")
    with pytest.raises(NoteScopeError, match="not a character"):
        note_scope.line_amendment(adaptation, pages, LineClaim(lettering_item_id="lettering_0002",
                                                               speaker_entity_id="location_alert"),
                                  _inventory(), "note_x")


def test_a_new_speaker_keeps_its_name_from_the_story_bible() -> None:
    adaptation, pages = _book()
    payload = adaptation.model_dump(mode="json")
    payload["content_sha256"] = ""
    payload["beats"][1]["lettering"][0]["speaker"] = "A sailor"
    adaptation = type(adaptation).model_validate(payload)
    pages = _pages_from(adaptation, [["beat_0001"], ["beat_0002"]], entity_ids=ENTITIES)
    amended, revised = note_scope.line_amendment(
        adaptation, pages, LineClaim(lettering_item_id="lettering_0002", speaker_entity_id="character_johansen"),
        _inventory(), "note_x")
    item = revised[2].content[0].lettering[0]
    assert (item.speaker, item.speaker_entity_id) == ("Johansen", "character_johansen")


def test_a_look_runs_until_the_script_changes_it_and_rebinds_only_chosen_pages() -> None:
    adaptation, pages = _book()
    claim = LookClaim(entity_id="character_johansen", fact="He lost his cap.", start_page=1,
                      state_id="bareheaded")
    scope = note_scope.look_scope(adaptation, pages, claim, _inventory(with_look=True), frozenset({1, 2}))
    assert [(page.page_number, page.panels) for page in scope.pages] == [(1, (1,)), (2, (1,))]
    assert scope.end_page == 2 and scope.from_state_id is None

    # Page 2's art already shows him bareheaded: only page 1 changes.
    revised = note_scope.look_amendment(pages, claim, scope, "bareheaded", frozenset({1}))
    assert sorted(revised) == [1]
    assert revised[1].content[0].appearance_states == {"character_johansen": "bareheaded"}
    assert revised[1].adaptation_sha256 == adaptation.content_sha256
    after = [revised[1], pages[1]]
    assert note_scope.new_failures(_failures(adaptation, pages, _inventory(with_look=True)),
                                   _failures(adaptation, after, _inventory(with_look=True))) == ()


def test_a_look_is_refused_where_nothing_shows_it() -> None:
    adaptation = _adaptation()
    pages = _pages_from(adaptation, [["beat_0001"], ["beat_0002"]], entity_ids=("location_alert",))
    with pytest.raises(NoteScopeError, match="Nobody draws"):
        note_scope.look_scope(adaptation, pages, LookClaim(entity_id="character_johansen", fact="No cap.",
                                                           start_page=1), _inventory())


def test_revised_beats_keep_their_place_and_new_lines_land_on_the_beats_last_page() -> None:
    adaptation = _adaptation()
    pages = _pages_from(adaptation, [["beat_0001"], ["beat_0001", "beat_0002"]], entity_ids=ENTITIES)
    beat = adaptation.beats[0]
    new_line = LetteringItem(id="beat_0001_note_02", kind="caption", delivery="narration",
                             text="The city waited.", source_unit_ids=beat.source_unit_ids)
    revised = beat.model_copy(update={"summary": "The city looms.", "lettering": (*beat.lettering, new_line)})
    amended = note_scope.beat_amendment(adaptation, (revised,), "note_bbbbbbbbbbbb")
    assert amended.amendments[-1].changed_beat_ids == ("beat_0001",)
    assert note_scope.lettering_after_revision(pages, adaptation, amended, ("beat_0001",)) == {
        1: ("lettering_0001",),
        2: ("beat_0001_note_02", "lettering_0002"),
    }
    with pytest.raises(NoteScopeError, match="keep its place"):
        note_scope.beat_amendment(adaptation, (beat.model_copy(update={"source_unit_ids": ("source_000002",)}),),
                                  "note_x")


def test_readings_become_claims_and_page_local_ones_stay_none() -> None:
    adaptation, pages = _book()
    page = pages[1]

    def reading(**fields):
        return ChangeReading(change_id="c", instruction="Do it.", reason="Because.", **fields)

    assert claim_for(reading(route="draw"), page) is None
    assert claim_for(reading(route="script", lettering_item_id="lettering_0002", new_text="Hard about!"), page) \
        == LineClaim(lettering_item_id="lettering_0002", text="Hard about!")
    assert claim_for(reading(route="script", panel=1), page) == BeatClaim(beat_ids=("beat_0002",), note="Do it.")
    look = claim_for(reading(route="draw", reach="beyond_page", entity_id="character_johansen",
                             fact="He lost his cap.", look_label="Bareheaded", look_anchor="no cap"), page)
    assert look == LookClaim(entity_id="character_johansen", fact="He lost his cap.", start_page=2,
                             look_label="Bareheaded", look_anchor="no cap")
    assert claim_for(reading(route="draw", reach="beyond_page", entity_id="someone_else", fact="x"), page) is None


# --- Apply and undo through the service ------------------------------------------------

def _workspace(tmp_path: Path) -> TargetArtifacts:
    from novel_to_comic.artifacts import write_story_bible
    from novel_to_comic.models.source import SourceDocument, SourceScene, SourceUnit
    from novel_to_comic.models.story_bible import Character, Location, Scene, StoryBible

    from novel_to_comic.state import PipelineState, save_state

    adaptation, pages = _book()
    target = TargetArtifacts(tmp_path / "project")
    target.project_dir.mkdir(parents=True)
    save_state(PipelineState(project_name="Reef", novel_path="input/reef.txt",
                             created_at="2026-01-01T00:00:00Z"), target.project_dir)
    text = "The reef rose before us. Hard to port!"
    target.write_source(SourceDocument(text=text, units=[
        SourceUnit(id="source_000001", ordinal=1, start_offset=0, end_offset=25, text=text[:25]),
        SourceUnit(id="source_000002", ordinal=2, start_offset=25, end_offset=len(text), text=text[25:]),
    ], scenes=[SourceScene(id="scene_001", title="Reef", first_unit_id="source_000001",
                           last_unit_id="source_000002")]))
    target.write_brief(AdaptationBrief(
        status="approved", revision=3, story_promises=("Escape",), themes=("dread",), point_of_view="close third",
        narrator_treatment="captions", tone="dark", essential_events=("Escape",), character_turns=("Flight",),
        desired_emphasis=("reef",), motifs=("reef",), transformation_level="faithful",
        target_page_min=2, target_page_max=2,
    ))
    write_story_bible(target.project_dir, StoryBible(
        title="Reef", author="Test", total_scenes=1, sequences=[],
        scenes=[Scene(id="scene_001", part_id="part_0001", chapter=1, title="Reef", location_id="location_alert",
                      character_ids=["character_johansen"], summary="They flee.", scene_type="action",
                      narrative_beat="climax", source_start_quote="The reef", source_start_offset=0)],
        characters=[Character(id="character_johansen", name="Johansen", visual_anchor="gaunt sailor",
                              age_range="adult", gender="male", distinguishing_features=[],
                              default_outfit="pea coat", first_appearance_scene="scene_001")],
        locations=[Location(id="location_alert", name="The Alert", visual_anchor="steam yacht", mood="tense")],
    ))
    target.write_adaptation(adaptation)
    for page in pages:
        target.write_page(page)
    target.write_plan(BookPlan(
        revision=1, adaptation_revision=adaptation.revision, adaptation_sha256=adaptation.content_sha256,
        target_page_min=2, target_page_max=2,
        pages=[PlannedPageRevision(page_number=page.page_number, revision=page.revision,
                                   content_sha256=page.content_sha256) for page in pages],
    ))
    return target


@pytest.fixture
def free_calls(monkeypatch):
    from novel_to_comic.server import credited_job

    from .narrative_review_support import accept_narrative

    monkeypatch.setattr("novel_to_comic.validation_round.review_narrative", accept_narrative)

    async def run_now(*, work, **_kwargs):
        return await work()

    monkeypatch.setattr(credited_job, "run_credited_call", run_now)
    monkeypatch.setattr("novel_to_comic.server.note_changes.quote_apply",
                        lambda *_args, **_kwargs: {"provider_cost_usd": 0.0})


def test_a_line_change_applies_through_script_and_page_then_undoes(tmp_path: Path, free_calls) -> None:
    from novel_to_comic.config import Config
    from novel_to_comic.server import note_changes

    target = _workspace(tmp_path)
    before_adaptation = target.read_adaptation()
    before_page_1 = target.read_page(1)
    change = note_changes.preview(target.project_dir, 2, "Make it 'Hard about!'",
                                  LineClaim(lettering_item_id="lettering_0002", text="“Hard about!”"))
    assert [page.page_number for page in change.scope.pages] == [2]
    assert target.read_adaptation() == before_adaptation  # preview writes only the record

    applied = asyncio.run(note_changes.apply(target.project_dir, Config(), change, pages=None,
                                             user_id="u", project_id="p"))
    assert applied.status == "applied" and applied.pages == (2,)
    assert target.read_page(1) == before_page_1
    assert target.read_page(2).content[0].lettering[0].text == "“Hard about!”"
    assert target.read_adaptation().revision == before_adaptation.revision + 1
    assert target.read_plan().adaptation_sha256 == target.read_adaptation().content_sha256

    undone = note_changes.undo(target.project_dir, target.read_note_change(change.id))
    assert undone.status == "undone"
    assert target.read_adaptation() == before_adaptation
    assert target.read_page(2).content[0].lettering[0].text == "“Hard to port!”"


def test_a_stale_preview_is_refused_and_nothing_is_written(tmp_path: Path, free_calls) -> None:
    from novel_to_comic.config import Config
    from novel_to_comic.server import note_changes

    target = _workspace(tmp_path)
    change = note_changes.preview(target.project_dir, 2, "x",
                                  LineClaim(lettering_item_id="lettering_0002", text="“Hard about!”"))
    other = note_changes.preview(target.project_dir, 2, "y",
                                 LineClaim(lettering_item_id="lettering_0002", text="“Turn!”"))
    asyncio.run(note_changes.apply(target.project_dir, Config(), other, pages=None, user_id="u", project_id="p"))
    after = target.read_adaptation()
    with pytest.raises(note_changes.StaleNote):
        asyncio.run(note_changes.apply(target.project_dir, Config(), change, pages=None, user_id="u",
                                       project_id="p"))
    assert target.read_adaptation() == after


def test_a_failed_review_puts_everything_back(tmp_path: Path, free_calls, monkeypatch) -> None:
    from novel_to_comic.config import Config
    from novel_to_comic.server import note_changes

    target = _workspace(tmp_path)
    before = (target.read_adaptation(), target.read_plan(), target.read_page(2))

    async def reject(*_args, **_kwargs):
        raise note_changes.NoteRefused("The story check found a problem with this change: no.")

    monkeypatch.setattr(note_changes, "_review", reject)
    change = note_changes.preview(target.project_dir, 2, "x",
                                  LineClaim(lettering_item_id="lettering_0002", text="“Hard about!”"))
    with pytest.raises(note_changes.NoteRefused, match="story check"):
        asyncio.run(note_changes.apply(target.project_dir, Config(), change, pages=None, user_id="u",
                                       project_id="p"))
    assert (target.read_adaptation(), target.read_plan(), target.read_page(2)) == before
    assert target.read_note_change(change.id).status == "proposed"


def test_a_new_look_is_added_bound_and_removed_again_on_undo(tmp_path: Path, free_calls) -> None:
    from novel_to_comic import artifacts as series
    from novel_to_comic.config import Config
    from novel_to_comic.server import note_changes

    target = _workspace(tmp_path)
    claim = LookClaim(entity_id="character_johansen", fact="He lost his cap overboard.", start_page=1,
                      look_label="Bareheaded", look_anchor="gaunt sailor, pea coat, no cap")
    change = note_changes.preview(target.project_dir, 1, "his cap blew off", claim)
    applied = asyncio.run(note_changes.apply(target.project_dir, Config(), change, pages=None,
                                             user_id="u", project_id="p"))
    johansen = series.read_story_bible(target.project_dir).characters[0]
    assert applied.added_state and applied.state_id == "bareheaded"
    assert [state.id for state in johansen.appearance_states] == ["bareheaded"]
    assert johansen.appearance_timeline[0].at.scene_id == "scene_001"
    assert target.read_page(1).content[0].appearance_states == {"character_johansen": "bareheaded"}
    assert target.read_adaptation().amendments == ()

    note_changes.undo(target.project_dir, target.read_note_change(change.id))
    assert series.read_story_bible(target.project_dir).characters[0].appearance_states == []
    assert target.read_page(1).content[0].appearance_states == {}
