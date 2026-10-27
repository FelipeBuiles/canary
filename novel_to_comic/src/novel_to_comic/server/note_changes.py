"""Preview, check, apply and undo an author's note carried beyond its page.

The owning layers stay the authority: Story Bible edits go through the
revision-checked editor, script changes become ``AdaptationAmendment``s that
the Adapt validator and narrative review accept, and page changes are new
ComicPage revisions the Plan validator and review accept. Apply writes all of
it or none of it. Nothing here redraws: the author redraws the listed pages.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from novel_to_comic import artifacts as series_artifacts
from novel_to_comic import note_scope
from novel_to_comic.config import Config
from novel_to_comic.models.adaptation import BookAdaptation
from novel_to_comic.models.note_change import FactCheck, NoteChange, NoteStamp
from novel_to_comic.models.page import ApprovedPageRange, ApprovedVisualReferenceInventory, BookPlan, ComicPage
from novel_to_comic.note_scope import BeatClaim, LineClaim, LookClaim, NoteScopeError
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts


class NoteRefused(ValueError):
    """The note can't be applied as previewed; nothing was changed."""


class StaleNote(NoteRefused):
    """The book changed since this step was shown."""


@dataclass(frozen=True)
class _Book:
    target: TargetArtifacts
    adaptation: BookAdaptation
    plan: BookPlan
    pages: tuple[ComicPage, ...]
    inventory: ApprovedVisualReferenceInventory
    drawn: frozenset[int]
    bible_revision: int

    def stamp(self) -> NoteStamp:
        return NoteStamp(adaptation_sha256=self.adaptation.content_sha256, plan_sha256=self.plan.content_sha256,
                         story_bible_revision=self.bible_revision)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _book(project_dir: Path) -> _Book:
    from novel_to_comic.stages.s5_plan import approved_visual_inventory

    target = TargetArtifacts(project_dir)
    try:
        adaptation = target.read_adaptation()
        plan = target.read_plan()
        pages = tuple(target.read_page_revision(entry.page_number, entry.revision) for entry in plan.pages)
    except (ArtifactMissing, ArtifactInvalid) as exc:
        raise NoteRefused("This part has no accepted page plan yet.") from exc
    drawn = frozenset(page.page_number for page in pages if target.active_render_revision(page.page_number))
    bible = series_artifacts.read_story_bible(project_dir)
    return _Book(target, adaptation, plan, pages, approved_visual_inventory(project_dir), drawn, bible.revision)


def _scope(book: _Book, claim) -> note_scope.NoteScope:
    if isinstance(claim, LineClaim):
        return note_scope.line_scope(book.adaptation, book.pages, claim, book.drawn)
    if isinstance(claim, BeatClaim):
        return note_scope.beat_scope(book.adaptation, book.pages, claim, book.drawn)
    return note_scope.look_scope(book.adaptation, book.pages, claim, book.inventory, book.drawn)


def preview(project_dir: Path, page_number: int, note: str, claim) -> NoteChange:
    """Resolve the pages a note touches. Writes only the record; spends nothing."""

    book = _book(project_dir)
    try:
        scope = _scope(book, claim)
    except NoteScopeError as exc:
        raise NoteRefused(str(exc)) from exc
    if not scope.pages:
        raise NoteRefused("No page shows what this note is about.")
    change = NoteChange(
        id=f"note_{uuid.uuid4().hex[:12]}", page_number=page_number, note=note.strip(), claim=claim,
        scope=scope, previewed=book.stamp(), created_at=_now(),
    )
    book.target.write_note_change(change)
    return change


def _require(change: NoteChange, status: str) -> None:
    if change.status != status:
        raise NoteRefused(f"This change is already {change.status}.")


def _require_current(book: _Book, stamp: NoteStamp) -> None:
    if book.stamp() != stamp:
        raise StaleNote("The book changed since this was shown. Check the note again.")


# --- Checking art against a look fact -------------------------------------------------

def check_pages(change: NoteChange) -> tuple[int, ...]:
    """Drawn pages in a look's run, other than the one the author flagged."""

    if not isinstance(change.claim, LookClaim):
        return ()
    return tuple(page.page_number for page in change.scope.pages
                 if page.drawn and page.page_number != change.page_number)


def _entity_name(book: _Book, entity_id: str) -> str:
    return next((reference.label for reference in book.inventory.references
                 if reference.entity_id == entity_id and reference.appearance_state_id is None and reference.label),
                entity_id)


def _prepared_check(book: _Book, config: Config, change: NoteChange, page_number: int):
    from novel_to_comic.note_calls import check_fact, estimate_fact_check_cost, fact_prompt
    from novel_to_comic.server.render_checks import _check_inputs

    page, render, image = _check_inputs(book.target, page_number)
    name = _entity_name(book, change.claim.entity_id)
    cost = estimate_fact_check_cost(config, fact_prompt(page=page, entity_name=name, fact=change.claim.fact))

    def work():
        return check_fact(config=config, page=page, image=image, entity_name=name, fact=change.claim.fact)

    return render, cost, work


def quote_checks(project_dir: Path, config: Config, change: NoteChange) -> dict:
    from novel_to_comic.server.codex_admission import correction_interpret_operations
    from novel_to_comic.server.render_checks import _quote

    book = _book(project_dir)
    pages = check_pages(change)
    cost = sum(_prepared_check(book, config, change, number)[1] for number in pages)
    return {**_quote(cost, correction_interpret_operations(config) if pages else ()), "pages": list(pages)}


async def run_checks(project_dir: Path, config: Config, change: NoteChange, *, user_id: str,
                     project_id: str) -> NoteChange:
    """Ask, page by page, whether the current art breaks the fact. Each page is its own paid check."""

    from novel_to_comic.server.codex_admission import correction_interpret_operations
    from novel_to_comic.server.credited_job import run_credited_page_check

    _require(change, "proposed")
    book = _book(project_dir)
    _require_current(book, change.previewed)
    checks = []
    for number in check_pages(change):
        render, cost, work = _prepared_check(book, config, change, number)
        result = await run_credited_page_check(
            user_id=user_id, project_id=project_id, project_dir=project_dir, page_number=number,
            estimated_cost_usd=cost, operations=correction_interpret_operations(config), work=work,
        )
        checks.append(FactCheck(page_number=number, render_revision=render.revision,
                                breaks_fact=result.value.breaks_fact, panels=result.value.panels,
                                evidence=result.value.evidence))
    checked = change.model_copy(update={"checks": tuple(checks)})
    book.target.write_note_change(checked)
    return checked


# --- Applying ---------------------------------------------------------------------------

def default_pages(change: NoteChange) -> tuple[int, ...]:
    """The pages a look change rewrites unless the author picks others.

    The flagged page, every page whose art broke the fact, and pages not
    drawn yet. Line and story changes always rewrite every page they touch.
    """

    if not isinstance(change.claim, LookClaim):
        return tuple(page.page_number for page in change.scope.pages)
    broken = {check.page_number for check in change.checks if check.breaks_fact}
    unchecked = set(check_pages(change)) - {check.page_number for check in change.checks}
    return tuple(page.page_number for page in change.scope.pages
                 if page.page_number == change.page_number or not page.drawn
                 or page.page_number in broken or page.page_number in unchecked)


def _generator(config: Config, model: str):
    from novel_to_comic.clients.text import generate_json

    async def generate(**kwargs):
        return await generate_json(config=config, model=model, temperature=0.25, **kwargs)

    return generate


def _changes_script(change: NoteChange) -> bool:
    return not isinstance(change.claim, LookClaim)


def quote_apply(project_dir: Path, config: Config, change: NoteChange) -> dict:
    """Price every model call apply makes: script revision, re-plans and both reviews."""

    from novel_to_comic.codex_dev import classify_operations
    from novel_to_comic.narrative_review import adaptation_context, estimate_narrative_review, planning_context
    from novel_to_comic.note_calls import beat_prompt, estimate_beat_revision_cost
    from novel_to_comic.page_planning import estimate_page_replan_cost
    from novel_to_comic.server.credits import credit_estimate_for_provider_cost

    book = _book(project_dir)
    cost = estimate_narrative_review(config.effective_plan_model(), planning_context(book.adaptation, book.pages))
    if _changes_script(change):
        cost += estimate_narrative_review(config.effective_adapt_model(), adaptation_context(
            book.target.read_source(), book.target.read_brief(), book.adaptation))
    if isinstance(change.claim, BeatClaim):
        cost += estimate_beat_revision_cost(config, beat_prompt(
            adaptation=book.adaptation, source=book.target.read_source(), beat_ids=change.claim.beat_ids,
            note=change.claim.note, inventory=book.inventory), len(change.claim.beat_ids))
        for scoped in change.scope.pages:
            try:
                cost += estimate_page_replan_cost(book.target, book.inventory, scoped.page_number,
                                                  model=config.effective_plan_model(), author_request=change.note)
            except ValueError:
                pass
    operations = _operations(config)
    estimate = credit_estimate_for_provider_cost(cost, "plan", reserve=True, funding=classify_operations(operations))
    return {**estimate, "pages": list(default_pages(change)), "provider_cost_usd": cost}


def _operations(config: Config):
    return (("text", config.effective_plan_model()), ("text", config.effective_adapt_model()))


async def _review(book_target: TargetArtifacts, phase: str, context: dict, *, config: Config, model: str, sink) -> None:
    from novel_to_comic.page_planning import PlanValidation
    from novel_to_comic.validation_round import review_clean_candidate

    try:
        previous = book_target.read_narrative_review(phase)
    except (ArtifactMissing, ArtifactInvalid):
        previous = None
    validation = await review_clean_candidate(
        PlanValidation(), context, generate=_generator(config, model), ctx=sink, artifacts=book_target,
        model=model, instruction=previous.instruction if previous is not None else "",
    )
    if validation.invariant_failures:
        raise NoteRefused("The story check found a problem with this change: "
                          + "; ".join(failure.message for failure in validation.invariant_failures[:3]))


def _plan_failures(book: _Book, adaptation, pages, inventory=None):
    from novel_to_comic.page_planning import validate_book_plan

    target_range = ApprovedPageRange(minimum=book.plan.target_page_min, maximum=book.plan.target_page_max)
    return validate_book_plan(adaptation, inventory or book.inventory, target_range, tuple(pages)).invariant_failures


def _adapt_failures(book: _Book, adaptation):
    from novel_to_comic.book_adaptation import validate_book_adaptation

    return validate_book_adaptation(book.target.read_source(), book.target.read_brief(), adaptation,
                                    story_bible=series_artifacts.read_story_bible(book.target.project_dir),
                                    ).invariant_failures


def _refuse_new(kind: str, before, after) -> None:
    introduced = note_scope.new_failures(before, after)
    if introduced:
        raise NoteRefused(f"The {kind} would no longer pass its checks: "
                          + "; ".join(failure.message for failure in introduced[:3]))


def _bible_kind(book: _Book, entity_id: str) -> str:
    kind = next(reference.kind for reference in book.inventory.references if reference.entity_id == entity_id)
    return {"character": "characters", "location": "locations", "prop": "props"}.get(kind, "characters")


def _start_scene(book: _Book, beat_id: str) -> str | None:
    beat = next(beat for beat in book.adaptation.beats if beat.id == beat_id)
    source = book.target.read_source()
    for scene in source.scenes:
        if set(beat.source_unit_ids) & set(scene.unit_ids(source)):
            return scene.id
    return None


def _look_change(action: str, kind: str, entity_id: str):
    """Describe the look edit for the Story Bible's own Undo, as its editor does."""
    from novel_to_comic.server.routers.story_bible import _change

    def describe(before, after):
        def looks(bible):
            entity = next(item for item in getattr(bible, kind) if item.id == entity_id)
            return {state.id for state in entity.appearance_states}
        state_id = next(iter(looks(after) ^ looks(before)))
        return _change(action, kind, entity_id, state_id=state_id)(before, after)

    return describe


def _add_look(book: _Book, change: NoteChange) -> str:
    from novel_to_comic.story_bible_edits import EditRejected, add_state, apply_edit

    claim = change.claim
    kind = _bible_kind(book, claim.entity_id)
    details = {"label": claim.look_label.strip(), "visual_anchor": claim.look_anchor.strip()}
    scene = _start_scene(book, change.scope.beat_ids[0])

    def save(at):
        _bible, state_id = apply_edit(book.target.project_dir, book.bible_revision,
                                      lambda current: add_state(current, kind, claim.entity_id, details, at),
                                      change=_look_change("add_look", kind, claim.entity_id))
        return state_id

    try:
        return save(scene)
    except EditRejected:
        if scene is None:
            raise
        # Another look already starts in that scene: keep the look, skip the timeline.
        return save(None)


def _remove_look(project_dir: Path, kind: str, entity_id: str, state_id: str) -> None:
    from novel_to_comic.story_bible_edits import apply_edit, remove_state

    bible = series_artifacts.read_story_bible(project_dir)
    apply_edit(project_dir, bible.revision, lambda current: remove_state(current, kind, entity_id, state_id),
               change=_look_change("remove_look", kind, entity_id))


async def apply(project_dir: Path, config: Config, change: NoteChange, *, pages: tuple[int, ...] | None,
                user_id: str, project_id: str) -> NoteChange:
    """Write the change through every owning layer, reviewed like a stage run, or nothing."""

    from novel_to_comic.server.credited_job import run_credited_call

    _require(change, "proposed")
    book = _book(project_dir)
    _require_current(book, change.previewed)
    chosen = tuple(sorted(set(pages if pages is not None else default_pages(change))))
    if not chosen or not set(chosen) <= {page.page_number for page in change.scope.pages}:
        raise NoteRefused("Choose pages from the ones this change touches.")
    cost = quote_apply(project_dir, config, change)["provider_cost_usd"]
    book.target.snapshot_for_note(change.id)
    added: dict[str, str] = {}
    try:
        await run_credited_call(
            user_id=user_id, project_id=project_id, project_dir=project_dir, stage="plan",
            estimated_cost_usd=cost, operations=_operations(config),
            work=lambda: _apply_work(book, config, change, chosen, added),
        )
    except BaseException:
        book.target.restore_note_snapshot(change.id)
        if added:
            _remove_look(project_dir, _bible_kind(book, change.claim.entity_id), change.claim.entity_id,
                         added["state_id"])
        raise
    after = _book(project_dir)
    redraw = tuple(number for number in after.drawn
                   if after.target.read_provenance(number, after.target.active_render_revision(number))
                   .render.is_stale_for(after.target.read_page(number))
                   and number in {page.page_number for page in change.scope.pages})
    applied = change.model_copy(update={
        "status": "applied", "pages": chosen, "state_id": added.get("state_id") or getattr(change.claim, "state_id", None),
        "added_state": bool(added), "redraw_pages": tuple(sorted(redraw)), "applied": after.stamp(),
        "applied_at": _now(),
    })
    after.target.write_note_change(applied)
    return applied


async def _apply_work(book: _Book, config: Config, change: NoteChange, chosen: tuple[int, ...],
                      added: dict[str, str]) -> None:
    from novel_to_comic.narrative_review import adaptation_context, planning_context
    from novel_to_comic.page_planning import _UsageSink
    from novel_to_comic.stages.s5_plan import approved_visual_inventory

    target, claim, sink = book.target, change.claim, _UsageSink()
    plan_before = _plan_failures(book, book.adaptation, book.pages)
    adaptation = book.adaptation
    if isinstance(claim, LookClaim):
        state_id = claim.state_id
        if state_id is None:
            if not claim.adds_look:
                raise NoteRefused("This note keeps the current look; correct the pages that break it instead.")
            state_id = _add_look(book, change)
            added["state_id"] = state_id
        inventory = approved_visual_inventory(target.project_dir)
        revised = note_scope.look_amendment(book.pages, claim, change.scope, state_id, frozenset(chosen))
        pages = [revised.get(page.page_number, page) for page in book.pages]
        _refuse_new("page plan", plan_before, _plan_failures(book, adaptation, pages, inventory))
        for page in revised.values():
            target.write_page(page)
        target.write_plan(note_scope.next_plan(book.plan, adaptation, revised))
    elif isinstance(claim, LineClaim):
        adapt_before = _adapt_failures(book, adaptation)
        adaptation, revised = note_scope.line_amendment(adaptation, book.pages, claim, book.inventory, change.id)
        _refuse_new("script", adapt_before, _adapt_failures(book, adaptation))
        pages = [revised.get(page.page_number, page) for page in book.pages]
        _refuse_new("page plan", plan_before, _plan_failures(book, adaptation, pages))
        target.write_adaptation(adaptation)
        for page in revised.values():
            target.write_page(page)
        target.write_plan(note_scope.next_plan(book.plan, adaptation, revised))
    else:
        adaptation = await _revise_story(book, config, change, sink)
    pages = [target.read_page(entry.page_number) for entry in target.read_plan().pages]
    if _changes_script(change):
        await _review(target, "adapt", adaptation_context(target.read_source(), target.read_brief(), adaptation),
                      config=config, model=config.effective_adapt_model(), sink=sink)
    await _review(target, "plan", planning_context(adaptation, pages), config=config,
                  model=config.effective_plan_model(), sink=sink)


async def _revise_story(book: _Book, config: Config, change: NoteChange, sink):
    """Rewrite the named beats, then re-plan only the pages that carry them."""

    from novel_to_comic.lettering.service import is_hybrid
    from novel_to_comic.note_calls import revise_beats
    from novel_to_comic.page_planning import PlanInvariantError, replan_page

    target, claim = book.target, change.claim
    adapt_before = _adapt_failures(book, book.adaptation)
    plan_before = _plan_failures(book, book.adaptation, book.pages)
    result = await revise_beats(config=config, adaptation=book.adaptation, source=target.read_source(),
                                beat_ids=claim.beat_ids, note=claim.note, inventory=book.inventory)
    sink.record_api_usage(result.usage)
    try:
        adaptation = note_scope.beat_amendment(book.adaptation, result.value, change.id)
    except NoteScopeError as exc:
        raise NoteRefused(str(exc)) from exc
    _refuse_new("script", adapt_before, _adapt_failures(book, adaptation))
    lettering = note_scope.lettering_after_revision(book.pages, book.adaptation, adaptation,
                                                     adaptation.amendments[-1].changed_beat_ids)
    target.write_adaptation(adaptation)
    target.write_plan(note_scope.next_plan(book.plan, adaptation, {}))
    generate = _generator(config, config.effective_plan_model())
    for number, lettering_ids in sorted(lettering.items()):
        try:
            await replan_page(target, book.inventory, number, generate=generate,
                              model=config.effective_plan_model(), author_request=change.note,
                              editable_lettering=is_hybrid(target), lettering_ids=lettering_ids, review=False)
        except PlanInvariantError as exc:
            raise NoteRefused(f"Page {number} couldn't be re-planned for this change.") from exc
    pages = [target.read_page(entry.page_number) for entry in target.read_plan().pages]
    _refuse_new("page plan", plan_before, _plan_failures(book, adaptation, pages))
    return adaptation


# --- Undo -------------------------------------------------------------------------------

def undo(project_dir: Path, change: NoteChange) -> NoteChange:
    """Put the script and page plan back as they were; drawn art stays in each page's history."""

    _require(change, "applied")
    book = _book(project_dir)
    if change.applied is None or (book.adaptation.content_sha256, book.plan.content_sha256) != (
            change.applied.adaptation_sha256, change.applied.plan_sha256):
        raise StaleNote("The script or page plan changed after this note. Undo those later changes first.")
    book.target.restore_note_snapshot(change.id)
    if change.added_state and change.state_id is not None:
        _remove_look(project_dir, _bible_kind(book, change.claim.entity_id), change.claim.entity_id, change.state_id)
    undone = change.model_copy(update={"status": "undone", "undone_at": _now()})
    book.target.write_note_change(undone)
    return undone
