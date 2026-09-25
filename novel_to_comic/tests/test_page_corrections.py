"""Explicit page-correction requests: editable changes, notes, annotations, context."""

from __future__ import annotations

from .plan_detail_support import with_reservations

import asyncio
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from novel_to_comic.config import Config
from novel_to_comic.models.adaptation import (
    AdaptedBeat,
    AdaptationLedgerEntry,
    AppearanceChange,
    BookAdaptation,
    ContinuityTransition,
    LetteringItem,
    NarrativeTreatment,
)
from novel_to_comic.models.draw import (
    BookEdition,
    CompletePageProviderResult,
    CorrectionAnnotation,
    CorrectionChange,
    ObservedRegion,
    PageCapabilityProfile,
    PageGenerationProvenance,
    PageIssue,
    PageRenderRevision,
    RenderAnalysis,
    RetryProvenance,
)
from novel_to_comic.models.page import (
    ApprovedVisualReferenceInventory,
    ComicPage,
    PageContent,
)
from novel_to_comic.models.source import SourceDocument, SourceScene, SourceUnit
from novel_to_comic.page_drawing import (
    VertexCompletePageAdapter,
    compile_page_generation_request,
    correct_complete_page,
    correction_credit_estimate,
    prepare_page_correction,
    production_page_capability_profile,
)
from novel_to_comic.page_review import (
    InvalidCorrectionError,
    StaleCorrectionError,
    build_aggregated_correction_request,
    build_correction_context,
    deterministic_manual_issue_id,
    ensure_correction_issues,
)
from novel_to_comic.page_visual_review import (
    PageVisualReview,
    VisualFinding,
    finding_issue_links,
    reference_display_for_render,
    validated_saved_visual_review,
    visual_review_input_digest,
)
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts
from novel_to_comic.usage import UsageRecord



def _source() -> SourceDocument:
    text = "The door opened. Nothing moved."
    return SourceDocument(
        text=text,
        units=[
            SourceUnit(id="source-1", ordinal=1, start_offset=0, end_offset=17, text="The door opened. "),
            SourceUnit(id="source-2", ordinal=2, start_offset=17, end_offset=len(text), text="Nothing moved."),
        ],
        scenes=[SourceScene(id="scene-1", title="The door", first_unit_id="source-1", last_unit_id="source-2")],
    )


def _adaptation(source: SourceDocument) -> BookAdaptation:
    return BookAdaptation(
        revision=1,
        source_sha256=source.source_sha256,
        brief_revision=1,
        brief_sha256="b" * 64,
        treatment=NarrativeTreatment(
            causal_spine=["The door opens, then stillness."],
            essential_events=["The chamber answers with stillness."],
        ),
        beats=[
            AdaptedBeat(
                id="beat-1",
                order=1,
                summary="Johansen opens the idol chamber door.",
                narrative_function="initial",
                source_unit_ids=["source-1"],
                lettering=[
                    LetteringItem(
                        id="letter-1",
                        kind="caption",
                        text="The door opened.",
                        source_unit_ids=["source-1"],
                    )
                ],
                appearance_changes=[
                    AppearanceChange(
                        entity_id="johansen",
                        from_state_id=None,
                        to_state_id="drenched",
                        description="Rain soaks his coat before he enters.",
                    )
                ],
            ),
            AdaptedBeat(
                id="beat-2",
                order=2,
                summary="Stillness answers from the dark.",
                narrative_function="prolongation",
                source_unit_ids=["source-2"],
                transitions=[
                    ContinuityTransition(
                        dimension="place",
                        scope_id="thread-1",
                        from_state="harbor",
                        to_state="chamber",
                        description="The action moves indoors and stays there.",
                    )
                ],
            ),
        ],
        ledger=[
            AdaptationLedgerEntry(
                source_unit_id="source-1",
                disposition="caption",
                adapted_beat_ids=["beat-1"],
                preserved_function="The opening stays explicit.",
            ),
            AdaptationLedgerEntry(
                source_unit_id="source-2",
                disposition="depicted",
                adapted_beat_ids=["beat-2"],
                preserved_function="The stillness is shown, not told.",
            ),
        ],
    )


def _page() -> ComicPage:
    return with_reservations(ComicPage(
        revision=1,
        page_number=1,
        adaptation_revision=1,
        adaptation_sha256="a" * 64,
        emphasis="initial",
        density_intent="standard",
        content=[
            PageContent(
                id="content-1",
                order=1,
                beat_ids=["beat-1"],
                visual_intent="Johansen opens the idol chamber.",
                lettering=[
                    LetteringItem(
                        id="letter-1",
                        kind="caption",
                        text="The door opened.",
                        source_unit_ids=["source-1"],
                    )
                ],
            )
        ],
        reading_order=["content-1", "letter-1"],
    ))


def _profile() -> PageCapabilityProfile:
    return production_page_capability_profile()


def _edition(profile: PageCapabilityProfile | None = None) -> BookEdition:
    return BookEdition(revision=1, id="edition-1", capability_profile=profile or _profile())


def _issue(issue_id: str, **updates: object) -> PageIssue:
    payload: dict[str, object] = {
        "id": issue_id,
        "issue_type": "visual_composition",
        "classification": "editorial_issue",
        "correction_kind": "render_fidelity",
        "correction_owner": "draw",
        "page_number": 1,
        "render_revision": 1,
        "evidence": ["The chamber reads too bright for the reveal."],
        "requested_correction": "Darken the chamber while keeping the door readable.",
        "status": "open",
    }
    payload.update(updates)
    return PageIssue(**payload)


def _change(change_id: str, instruction: str = "Do the fix.", **updates: object) -> CorrectionChange:
    payload: dict[str, object] = {"id": change_id, "instruction": instruction}
    payload.update(updates)
    return CorrectionChange(**payload)


def _setup(tmp_path: Path, *, issues: tuple[PageIssue, ...] = ()) -> tuple[TargetArtifacts, ComicPage, PageRenderRevision]:
    artifacts = TargetArtifacts(tmp_path / "project")
    from .style_reference_support import write_style_proof
    write_style_proof(artifacts.project_dir)
    source = _source()
    artifacts.write_source(source)
    artifacts.write_adaptation(_adaptation(source))
    page = _page()
    artifacts.write_page(page)
    edition = _edition()
    artifacts.write_book_edition(edition)
    producing = compile_page_generation_request(
        page, edition, ApprovedVisualReferenceInventory(references=()), {},
        retry=RetryProvenance(attempt=1),
    ).request
    artifacts.write_request(producing, request_revision=1)
    image = b"parent-page-png"
    artifacts.write_render(page_number=1, render_revision=1, image=image)
    render = PageRenderRevision(
        page_number=1,
        revision=1,
        parent_revision=None,
        comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256,
        request_sha256=producing.request_sha256,
        image_sha256=hashlib.sha256(image).hexdigest(),
        width=edition.capability_profile.output_width,
        height=edition.capability_profile.output_height,
        provider=producing.provider,
        model=producing.model,
        latency_ms=10,
        cost_usd="0.5",
    )
    artifacts.write_provenance(
        PageGenerationProvenance(
            render=render,
            usage=UsageRecord(
                provider="fixture",
                model="fixture-page-model",
                operation="image",
                image_count=1,
                cost_usd=0.5,
                cost_source="provider",
            ),
        )
    )
    if issues:
        artifacts.write_issues(1, issues)
    return artifacts, page, render


def _usage() -> UsageRecord:
    return UsageRecord(
        provider="fixture",
        model="gemini-3-pro-image",
        operation="image",
        image_count=1,
        cost_usd=0.5,
        cost_source="provider",
    )


def _advance(
    artifacts: TargetArtifacts, page: ComicPage, *, revision: int, image: bytes,
) -> PageRenderRevision:
    """Append a real render revision so revised issues carry valid lineage."""
    edition = artifacts.read_book_edition()
    parent = artifacts.read_provenance(page.page_number, revision - 1).render
    producing = compile_page_generation_request(
        page, edition, ApprovedVisualReferenceInventory(references=()), {},
        retry=RetryProvenance(attempt=revision, retries_request_sha256=parent.request_sha256),
    ).request
    artifacts.write_request(producing, request_revision=revision)
    artifacts.write_render(page_number=1, render_revision=revision, image=image)
    render = PageRenderRevision(
        page_number=1,
        revision=revision,
        parent_revision=revision - 1,
        comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256,
        request_sha256=producing.request_sha256,
        image_sha256=hashlib.sha256(image).hexdigest(),
        width=edition.capability_profile.output_width,
        height=edition.capability_profile.output_height,
        provider=producing.provider,
        model=producing.model,
        latency_ms=10,
        cost_usd="0.5",
    )
    artifacts.write_provenance(PageGenerationProvenance(render=render, usage=_usage()))
    return render


def _prepare(
    artifacts: TargetArtifacts,
    page: ComicPage,
    render: PageRenderRevision,
    profile: PageCapabilityProfile | None = None,
    **kwargs: object,
):
    defaults: dict[str, object] = {
        "changes": (),
        "note": "",
        "context_source_unit_ids": (),
    }
    defaults.update(kwargs)
    return prepare_page_correction(
        page=page,
        edition=_edition(profile),
        inventory=ApprovedVisualReferenceInventory(references=()),
        reference_files={},
        retry=RetryProvenance(attempt=1),
        parent=render,
        artifacts=artifacts,
        style_template="",
        **defaults,  # type: ignore[arg-type]
    )


def test_edited_change_aggregates_one_request_and_leaves_rest_open(tmp_path: Path) -> None:
    artifacts, page, render = _setup(
        tmp_path, issues=(_issue("issue-dark"), _issue("issue-hand", requested_correction="Fix the extra finger."))
    )

    correction = build_aggregated_correction_request(
        changes=(_change("c-dark", "Edited: darken much deeper.", issue_id="issue-dark"),),
        page=page,
        parent=render,
        profile=_profile(),
        artifacts=artifacts,
    )

    assert correction.issue_ids == ("issue-dark",)
    assert correction.changes[0].issue_id == "issue-dark"
    assert "Edited: darken much deeper." in correction.instruction
    assert "extra finger" not in correction.instruction
    assert [issue.status for issue in artifacts.read_issues(1)] == ["open", "open"]


def test_manual_change_gets_deterministic_identity_without_writes(tmp_path: Path) -> None:
    artifacts, page, render = _setup(tmp_path)

    prepared = _prepare(
        artifacts, page, render,
        changes=(_change("c-shadow", "Push the idol deeper into shadow."),),
    )
    manual_id = deterministic_manual_issue_id(page_number=1, parent_revision=1, change_id="c-shadow")
    assert manual_id == "page-issue-manual-1-1-c-shadow"
    assert prepared.correction.issue_ids == (manual_id,)
    assert prepared.correction.changes[0].issue_id == manual_id
    try:
        artifacts.read_issues(1)
        persisted = True
    except ArtifactMissing:
        persisted = False
    assert not persisted

    # Preview and submission compile the identical frozen request.
    again = _prepare(
        artifacts, page, render,
        changes=(_change("c-shadow", "Push the idol deeper into shadow."),),
    )
    assert again.compiled.request.request_sha256 == prepared.compiled.request.request_sha256


def test_manual_issues_are_created_inside_the_job_idempotently(tmp_path: Path) -> None:
    artifacts, page, render = _setup(tmp_path)
    prepared = _prepare(
        artifacts, page, render,
        changes=(_change("c-shadow", "Push the idol deeper into shadow."),),
    )

    ensured = ensure_correction_issues(artifacts, correction=prepared.correction)

    assert [issue.id for issue in ensured] == ["page-issue-manual-1-1-c-shadow"]
    created = artifacts.read_issues(1)[0]
    assert created.issue_type == "manual_change"
    assert created.status == "open"
    assert created.requested_correction == "Push the idol deeper into shadow."
    assert created.render_revision == 1
    assert ensure_correction_issues(artifacts, correction=prepared.correction)[0] == created

    # Rebuilding after submission points at the tracked issue instead.
    with pytest.raises(InvalidCorrectionError, match="already submitted"):
        build_aggregated_correction_request(
            changes=(_change("c-shadow", "Push the idol deeper into shadow."),),
            page=page, parent=render, profile=_profile(), artifacts=artifacts,
        )


def test_note_only_request_compiles_without_changes(tmp_path: Path) -> None:
    artifacts, page, render = _setup(tmp_path)

    prepared = _prepare(artifacts, page, render, note="Hold the reveal for one beat.")

    assert prepared.correction.issue_ids == ()
    assert prepared.correction.changes == ()
    assert prepared.correction.note == "Hold the reveal for one beat."
    assert "Hold the reveal for one beat." in prepared.compiled.request.prompt
    assert prepared.compiled.request.correction == prepared.correction


def test_annotations_and_novel_context_reach_prompt_and_provenance(tmp_path: Path) -> None:
    artifacts, page, render = _setup(tmp_path, issues=(_issue("issue-dark"),))

    prepared = _prepare(
        artifacts, page, render,
        changes=(
            CorrectionChange(
                id="c-door", issue_id="issue-dark", instruction="Keep the reveal.",
                annotations=(
                    CorrectionAnnotation(
                        id="mark-2", kind="arrow",
                        points=({"x": 0.5, "y": 0.5}, {"x": 0.6, "y": 0.6}),
                        label="door", note="Keep this edge readable.",
                    ),
                ),
            ),
        ),
    )

    prompt = prepared.compiled.request.prompt
    assert "Keep this edge readable." in prompt
    producing = artifacts.read_request(page.page_number, 1)
    assert producing.prompt in prepared.correction.retained_instructions
    assert producing.prompt not in prompt  # Current Plan/references already carry its authority.
    # Bookwide spine travels, not just the page's own beat.
    assert "beat-1" in prompt and "beat-2" in prompt
    assert "The door opens, then stillness." in prompt
    assert "The chamber answers with stillness." in prompt
    # Appearance chronology and remote continuity facts travel in beat order.
    assert "drenched" in prompt
    assert "harbor" in prompt
    # Full prose is limited to the page's adapted units.
    assert "The door opened." not in prompt  # Canonical copy is withheld from hybrid Draw.
    assert prepared.context.treatment_spine[:1] == ("The door opens, then stillness.",)
    assert prepared.context.appearance_chronology != ()
    assert prepared.context.beat_transitions != ()
    assert prepared.context.omitted_source_unit_ids == ()
    assert not prepared.context.truncated
    assert prepared.correction.context_beat_ids == ("beat-1", "beat-2")
    assert prepared.correction.context_source_unit_ids == ("source-1",)
    assert prepared.correction.context_digest == prepared.context.digest
    assert prepared.correction.context_adaptation_revision == 1
    # Source copy remains canonical; hybrid provider requests carry reservations only.
    assert prepared.compiled.request.lettering == ()


def test_long_book_context_focuses_prompt_without_losing_saved_provenance(tmp_path: Path) -> None:
    artifacts, page, render = _setup(tmp_path)
    prepared = _prepare(artifacts, page, render, note="Make the jacket crimson.")
    context = prepared.context
    remote = tuple(f"Remote beat {i}: " + "unrelated history " * 35 for i in range(3, 90))
    long_context = context.model_copy(update={
        "beat_ids": (*context.beat_ids, *(f"remote-{i}" for i in range(3, 90))),
        "beat_summaries": (*context.beat_summaries, *remote),
        "beat_transitions": (*context.beat_transitions, *(f"Beat remote-{i} [{i}]: old state" for i in range(3, 90))),
    })
    compiled = compile_page_generation_request(
        page, _edition(), ApprovedVisualReferenceInventory(references=()), {},
        retry=RetryProvenance(attempt=1), correction=prepared.correction,
        correction_context=long_context, edit_source_bytes=artifacts.read_render(page.page_number, render.revision),
    )
    assert len(compiled.request.prompt) <= _edition().capability_profile.max_prompt_characters
    assert "Remote beat 89" not in compiled.request.prompt
    assert "The door opens, then stillness." in compiled.request.prompt
    assert prepared.correction.context_digest == context.digest
    assert len(long_context.beat_summaries) == 89
    estimate = correction_credit_estimate(prepared.compiled, config=Config(), reserve=True)
    assert estimate["estimate_credits"] > 0
    assert estimate["reserved_credits"] is not None and estimate["reserved_credits"] >= estimate["estimate_credits"]


def test_explicitly_selected_remote_passage_reaches_context(tmp_path: Path) -> None:
    artifacts, page, render = _setup(tmp_path)

    prepared = _prepare(
        artifacts, page, render, note="Mind the stillness.",
        context_source_unit_ids=("source-2",),
    )

    assert prepared.context.selected_source_unit_ids == ("source-2",)
    assert "Nothing moved." in prepared.compiled.request.prompt
    assert prepared.correction.context_selected_source_unit_ids == ("source-2",)

    with pytest.raises(InvalidCorrectionError, match="unknown source"):
        _prepare(artifacts, page, render, note="Mind it.", context_source_unit_ids=("source-9",))


def test_stale_parent_render_rejects_before_spend(tmp_path: Path) -> None:
    artifacts, page, render = _setup(tmp_path, issues=(_issue("issue-dark"),))
    superseded = render.model_copy(update={"revision": 99})

    with pytest.raises(StaleCorrectionError, match="render"):
        build_aggregated_correction_request(
            changes=(_change("c-dark", "Fix it.", issue_id="issue-dark"),),
            page=page, parent=superseded, profile=_profile(), artifacts=artifacts,
        )

    with pytest.raises(StaleCorrectionError, match="ComicPage"):
        build_aggregated_correction_request(
            changes=(_change("c-dark", "Fix it.", issue_id="issue-dark"),),
            page=page.model_copy(update={"revision": 2}),
            parent=render, profile=_profile(), artifacts=artifacts,
        )


def test_revised_finding_can_be_refixed_against_its_resolution_revision(tmp_path: Path) -> None:
    from novel_to_comic.page_review import resolve_page_issue

    artifacts, page, _render1 = _setup(tmp_path, issues=(_issue("issue-dark"),))
    render2 = _advance(artifacts, page, revision=2, image=b"parent-page-png-2")
    resolve_page_issue(artifacts, issue_id="issue-dark", page_number=1, resolution_revision=2, verified=False)
    assert artifacts.read_issues(1)[0].status == "revised"

    correction = build_aggregated_correction_request(
        changes=(_change("c-dark", "Still too bright.", issue_id="issue-dark"),),
        page=page, parent=render2, profile=_profile(), artifacts=artifacts,
    )
    assert correction.issue_ids == ("issue-dark",)
    assert "Still too bright." in correction.instruction


def test_revised_finding_from_a_superseded_render_rejects(tmp_path: Path) -> None:
    from novel_to_comic.page_review import resolve_page_issue

    artifacts, page, _render1 = _setup(tmp_path, issues=(_issue("issue-dark"),))
    _render2 = _advance(artifacts, page, revision=2, image=b"parent-page-png-2")
    resolve_page_issue(artifacts, issue_id="issue-dark", page_number=1, resolution_revision=2, verified=False)
    render3 = _advance(artifacts, page, revision=3, image=b"parent-page-png-3")

    with pytest.raises(StaleCorrectionError, match="revised by render 2"):
        build_aggregated_correction_request(
            changes=(_change("c-dark", "Fix it.", issue_id="issue-dark"),),
            page=page, parent=render3, profile=_profile(), artifacts=artifacts,
        )


def test_adapt_owned_issue_requires_a_story_change(tmp_path: Path) -> None:
    artifacts, page, render = _setup(
        tmp_path,
        issues=(_issue("issue-copy", correction_owner="adapt", correction_kind="copy_change",
                        requested_correction="Reword the caption."),),
    )

    with pytest.raises(InvalidCorrectionError, match="story change"):
        build_aggregated_correction_request(
            changes=(_change("c-copy", "Reword it.", issue_id="issue-copy"),),
            page=page, parent=render, profile=_profile(), artifacts=artifacts,
        )


def test_empty_request_and_bad_marks_reject(tmp_path: Path) -> None:
    artifacts, page, render = _setup(tmp_path)

    with pytest.raises(InvalidCorrectionError, match="requires changes or an author note"):
        build_aggregated_correction_request(
            changes=(), page=page, parent=render, profile=_profile(), artifacts=artifacts,
        )
    with pytest.raises(InvalidCorrectionError, match="change IDs must be unique"):
        build_aggregated_correction_request(
            changes=(_change("c", "One."), _change("c", "Two.")),
            page=page, parent=render, profile=_profile(), artifacts=artifacts,
        )
    with pytest.raises(ValidationError):
        CorrectionAnnotation(kind="pin", points=(), note="Nowhere.")
    with pytest.raises(ValidationError):
        CorrectionAnnotation(
            kind="pin",
            points=({"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}),
            note="A pin is one point.",
        )
    with pytest.raises(ValidationError):
        CorrectionAnnotation(
            kind="text",
            points=({"x": 0.1, "y": 0.1}, {"x": 0.2, "y": 0.2}),
            note="Text marks one point.",
        )
    with pytest.raises(ValidationError):
        CorrectionAnnotation(
            kind="text", points=({"x": 1.5, "y": 0.1}), note="Outside the page."
        )
    with pytest.raises(ValidationError):
        CorrectionAnnotation(kind="text", points=({"x": 0.1, "y": 0.1}), note="  ")
    with pytest.raises(ValidationError):
        CorrectionAnnotation(
            kind="freehand",
            points=({"x": 0.3, "y": 0.3}, {"x": 0.3, "y": 0.3}),
            note="Zero-area stroke.",
        )
    with pytest.raises(ValidationError):
        CorrectionAnnotation(
            kind="freehand",
            points=tuple({"x": i / 100, "y": 0.5} for i in range(65)),
            note="Over the 64-point cap.",
        )
    with pytest.raises(ValidationError):
        CorrectionChange(id="c", instruction="  ")


def test_unknown_detected_region_rejects_but_known_region_targets(tmp_path: Path) -> None:
    artifacts, page, render = _setup(
        tmp_path, issues=(_issue("issue-region", detected_region_ids=("region-9",)),)
    )
    artifacts.write_analysis(
        RenderAnalysis(
            page_number=1,
            render_revision=1,
            render_image_sha256=render.image_sha256,
            observed_regions=(
                ObservedRegion(id="region-2", polygon=((0.5, 0.5), (1.0, 0.5), (1.0, 1.0))),
                ObservedRegion(id="region-1", polygon=((0.0, 0.0), (1.0, 0.0), (0.0, 1.0))),
            ),
        )
    )

    with pytest.raises(InvalidCorrectionError, match="unknown detected region"):
        build_aggregated_correction_request(
            changes=(_change("c-region", "Fix it.", issue_id="issue-region"),),
            page=page, parent=render, profile=_profile(), artifacts=artifacts,
        )

    artifacts.write_issues(1, (_issue("issue-region", detected_region_ids=("region-1",)),))
    targeted = build_aggregated_correction_request(
        changes=(_change("c-region", "Fix it.", issue_id="issue-region"),),
        page=page, parent=render, profile=_profile(), artifacts=artifacts,
    )
    assert targeted.mode == "region_targeted"
    assert targeted.detected_region_ids == ("region-1",)
    assert [region.polygon for region in targeted.resolved_regions] == [
        ((0.0, 0.0), (1.0, 0.0), (0.0, 1.0)),
    ]


def test_bounded_context_omission_never_truncates_author_instructions(tmp_path: Path) -> None:
    # A long novel forces source-passage truncation; the author's own requested
    # changes must still arrive intact, with the omission recorded.
    sentence = "The door opened. "
    unit_count = 400
    text = sentence * unit_count
    units = tuple(
        SourceUnit(
            id=f"big-{index:04d}",
            ordinal=index + 1,
            start_offset=index * len(sentence),
            end_offset=(index + 1) * len(sentence),
            text=sentence,
        )
        for index in range(unit_count)
    )
    source = SourceDocument(
        text=text,
        units=units,
        scenes=[SourceScene(id="scene-big", title="Long night", first_unit_id="big-0000", last_unit_id=f"big-{unit_count - 1:04d}")],
    )
    long_beat_ids = tuple(unit.id for unit in units)
    adaptation = BookAdaptation(
        revision=1,
        source_sha256=source.source_sha256,
        brief_revision=1,
        brief_sha256="b" * 64,
        treatment=NarrativeTreatment(causal_spine=["A very long night."]),
        beats=[
            AdaptedBeat(
                id="beat-1", order=1, summary="The long night.", narrative_function="initial",
                source_unit_ids=long_beat_ids,
            )
        ],
        ledger=[
            AdaptationLedgerEntry(
                source_unit_id="big-0000", disposition="depicted", adapted_beat_ids=["beat-1"],
                preserved_function="Length stands in for a novel.",
            )
        ],
    )
    artifacts = TargetArtifacts(tmp_path / "project")
    artifacts.write_source(source)
    artifacts.write_adaptation(adaptation)
    page = _page()
    artifacts.write_page(page)
    artifacts.write_book_edition(_edition())
    producing = compile_page_generation_request(
        page, _edition(), ApprovedVisualReferenceInventory(references=()), {},
        retry=RetryProvenance(attempt=1),
    ).request
    artifacts.write_request(producing, request_revision=1)
    image = b"parent-page-png"
    artifacts.write_render(page_number=1, render_revision=1, image=image)
    render = PageRenderRevision(
        page_number=1, revision=1, parent_revision=None,
        comic_page_revision=page.revision, comic_page_sha256=page.content_sha256,
        request_sha256=producing.request_sha256, image_sha256=hashlib.sha256(image).hexdigest(),
        width=1696, height=2528, provider=producing.provider, model=producing.model,
        latency_ms=10, cost_usd="0.5",
    )
    artifacts.write_provenance(PageGenerationProvenance(render=render, usage=_usage()))
    note = "Keep the reveal exactly as staged."
    annotation = CorrectionAnnotation(
        id="mark-sweep", kind="freehand",
        points=({"x": 0.2, "y": 0.2}, {"x": 0.4, "y": 0.3}, {"x": 0.6, "y": 0.6}),
        note="Follow this sweep.",
    )
    correction = build_aggregated_correction_request(
        changes=(CorrectionChange(id="c-sweep", instruction=note, annotations=(annotation,)),),
        page=page, parent=render, profile=_profile(), artifacts=artifacts,
    )
    assert correction.context_truncated
    assert correction.context_source_unit_ids != ()
    assert len(correction.context_source_unit_ids) < unit_count
    assert correction.changes[0].instruction == note
    assert correction.changes[0].annotations == (annotation,)
    assert note in correction.instruction
    assert "Follow this sweep." in correction.instruction
    omitted = build_correction_context(page=page, artifacts=artifacts).omitted_source_unit_ids
    assert len(omitted) == unit_count - len(correction.context_source_unit_ids)
    assert omitted != ()


def test_oversized_prompt_rejects_overflow_before_spend(tmp_path: Path, monkeypatch) -> None:
    artifacts, page, render = _setup(tmp_path, issues=(_issue("issue-dark"),))
    profile = _profile().model_copy(update={"max_prompt_characters": 100})
    monkeypatch.setattr(
        "novel_to_comic.page_drawing.current_page_capability_profile",
        lambda: profile,
    )

    with pytest.raises(ValueError, match="exceed"):
        _prepare(
            artifacts, page, render, profile,
            changes=(_change("c-dark", "Fix it.", issue_id="issue-dark"),),
        )


class _Transport:
    async def generate(self, request):
        assert request.edit_source_bytes == b"parent-page-png"
        return CompletePageProviderResult(
            artifact_kind="complete_page",
            image_bytes=b"corrected-page-png",
            media_type="image/png",
            width=1024,
            height=1536,
            latency_ms=10,
            provider_request_id="provider-1",
            actual_provider_model="openai/gpt-image-2.5/sunburst",
            usage=UsageRecord(
                provider="fixture", model="openai/gpt-image-2.5/sunburst", operation="image",
                image_count=1, cost_usd=0.5, cost_source="provider",
            ),
        )


def test_visual_findings_stay_revised_until_human_confirmation(tmp_path: Path) -> None:
    artifacts, page, render = _setup(tmp_path, issues=(_issue("issue-dark"),))
    prepared = _prepare(
        artifacts, page, render,
        changes=(_change("c-dark", "Darken the chamber.", issue_id="issue-dark"),),
    )
    artifacts.write_request(prepared.compiled.request, request_revision=2)

    provenance = asyncio.run(
        correct_complete_page(
            prepared.compiled,
            issue=artifacts.read_issues(1)[0],
            adapter=VertexCompletePageAdapter(_Transport()),
            artifacts=artifacts,
            page=page,
            request_revision=2,
            render_revision=2,
        )
    )

    assert provenance.render.revision == 2
    assert provenance.render.parent_revision == 1
    revised = artifacts.read_issues(1)[0]
    assert revised.status == "revised"
    assert revised.resolution_revision == 2


def test_proven_lettering_fix_resolves_while_visuals_stay_revised(tmp_path: Path) -> None:
    lettering_issue = _issue(
        "page-issue-draw-page-1-lettering",
        issue_type="misspelled_lettering",
        classification="invariant_failure",
        requested_correction="Restore the exact caption.",
    )
    artifacts, page, render = _setup(tmp_path, issues=(lettering_issue, _issue("issue-dark")))
    prepared = _prepare(
        artifacts, page, render,
        changes=(
            _change("c-text", "Restore the exact caption.", issue_id="page-issue-draw-page-1-lettering"),
            _change("c-dark", "Darken the chamber.", issue_id="issue-dark"),
        ),
    )
    artifacts.write_request(prepared.compiled.request, request_revision=2)

    from novel_to_comic.models.draw import OCRExtraction, OCRTextObservation
    from novel_to_comic.usage import ApiResult

    class _ExactOCR:
        async def extract(self, image: bytes):
            assert image == b"corrected-page-png"
            return ApiResult(
                value=OCRExtraction(
                    lettering=(OCRTextObservation(id="ocr-1", text="The door opened."),),
                ),
                usage=UsageRecord(
                    provider="fixture",
                    model="fixture-ocr",
                    operation="text",
                    input_tokens=10,
                    output_tokens=5,
                    cost_usd=0.001,
                    cost_source="provider",
                ),
            )

    asyncio.run(
        correct_complete_page(
            prepared.compiled,
            issue=artifacts.read_issues(1)[0],
            adapter=VertexCompletePageAdapter(_Transport()),
            artifacts=artifacts,
            page=page,
            ocr=_ExactOCR(),
            request_revision=2,
            render_revision=2,
        )
    )

    by_id = {issue.id: issue for issue in artifacts.read_issues(1)}
    assert by_id["page-issue-draw-page-1-lettering"].status == "resolved"
    assert by_id["issue-dark"].status == "revised"


def test_created_manual_issues_enter_history_and_stay_revised(tmp_path: Path) -> None:
    artifacts, page, render = _setup(tmp_path)
    prepared = _prepare(
        artifacts, page, render,
        changes=(_change("c-shadow", "Push the idol deeper into shadow."),),
    )
    artifacts.write_request(prepared.compiled.request, request_revision=2)

    asyncio.run(
        correct_complete_page(
            prepared.compiled,
            issue=None,
            adapter=VertexCompletePageAdapter(_Transport()),
            artifacts=artifacts,
            page=page,
            request_revision=2,
            render_revision=2,
        )
    )

    history = artifacts.read_issues(1)
    assert [issue.id for issue in history] == ["page-issue-manual-1-1-c-shadow"]
    assert history[0].status == "revised"
    assert history[0].resolution_revision == 2


def test_validated_saved_review_matches_current_inputs_only(tmp_path: Path) -> None:
    artifacts, page, render = _setup(tmp_path)
    config = Config()
    compiled = compile_page_generation_request(
        page,
        _edition(),
        ApprovedVisualReferenceInventory(references=()),
        {},
        retry=RetryProvenance(attempt=1),
    )
    image = b"parent-page-png"
    producing = artifacts.read_request(page.page_number, 1)
    digest = visual_review_input_digest(
        config=config, page=page, render=render, image=image, compiled=compiled,
        producing_request=producing,
    )
    report = PageVisualReview(
        input_sha256=digest,
        page_number=1,
        render_revision=1,
        render_image_sha256=render.image_sha256,
        findings=(
            VisualFinding(
                category="composition",
                panel_number=1,
                observation="The chamber reads too bright.",
                expected="A dark reveal keyed to the door.",
                correction="Darken the chamber while keeping the door readable.",
            ),
        ),
        uncertain=("Whether the idol is occluded by shadow.",),
    )
    artifacts.write_visual_review(report)

    assert validated_saved_visual_review(
        page=page, render=render, image=image, compiled=compiled,
        config=config, artifacts=artifacts,
        producing_request=producing,
    ) == report

    # A stale file under another digest is never served as current.
    stale = report.model_copy(update={"input_sha256": "ff" * 32})
    artifacts.write_visual_review(stale)
    assert validated_saved_visual_review(
        page=page, render=render, image=image, compiled=compiled,
        config=config, artifacts=artifacts,
        producing_request=producing,
    ) == report

    # A superseded page no longer validates: raises instead of serving stale.
    with pytest.raises(ValueError, match="canonical page"):
        validated_saved_visual_review(
            page=page.model_copy(update={"revision": 2}),
            render=render, image=image, compiled=compiled,
            config=config, artifacts=artifacts,
            producing_request=producing,
        )


def test_render_correction_summary_projects_exact_submitted_text(tmp_path: Path) -> None:
    from novel_to_comic.server.routers.pages import _render_correction_summary

    artifacts, page, render = _setup(tmp_path, issues=(_issue("issue-dark"),))
    prepared = _prepare(
        artifacts, page, render,
        changes=(
            CorrectionChange(
                id="c-door", issue_id="issue-dark", instruction="Edited: darken deeper.",
                annotations=(
                    CorrectionAnnotation(
                        id="mark-2", kind="arrow",
                        points=({"x": 0.5, "y": 0.5}, {"x": 0.6, "y": 0.6}),
                        note="Keep this edge readable.",
                    ),
                ),
            ),
        ),
        note="Hold the reveal.",
    )
    artifacts.write_request(prepared.compiled.request, request_revision=2)
    image2 = b"corrected-page-png"
    artifacts.write_render(page_number=1, render_revision=2, image=image2)
    render2 = PageRenderRevision(
        page_number=1, revision=2, parent_revision=1,
        comic_page_revision=page.revision, comic_page_sha256=page.content_sha256,
        request_sha256=prepared.compiled.request.request_sha256,
        image_sha256=hashlib.sha256(image2).hexdigest(),
        width=120, height=180, provider="vertex-multimodal", model="gemini-3-pro-image",
        latency_ms=10, cost_usd="0.5",
    )
    artifacts.write_provenance(PageGenerationProvenance(render=render2, usage=_usage()))

    summary = _render_correction_summary(artifacts, 1, 2)

    assert summary["render_revision"] == 2
    assert summary["parent_render_revision"] == 1
    assert summary["request_sha256"] == prepared.compiled.request.request_sha256
    assert summary["correction"]["note"] == "Hold the reveal."
    [change] = summary["correction"]["changes"]
    assert change["id"] == "c-door"
    assert change["issue_id"] == "issue-dark"
    assert change["instruction"] == "Edited: darken deeper."
    [mark] = change["annotations"]
    assert mark["kind"] == "arrow"
    assert mark["note"] == "Keep this edge readable."
    assert list(mark["points"]) == [{"x": 0.5, "y": 0.5}, {"x": 0.6, "y": 0.6}]

def test_finding_links_mark_missing_issues_unavailable(tmp_path: Path) -> None:
    artifacts, page, render = _setup(tmp_path)
    digest = "ab" * 32
    report = PageVisualReview(
        input_sha256=digest,
        page_number=1,
        render_revision=1,
        render_image_sha256=render.image_sha256,
        findings=(
            VisualFinding(
                category="composition",
                panel_number=1,
                observation="The chamber reads too bright.",
                expected="A dark reveal keyed to the door.",
                correction="Darken the chamber while keeping the door readable.",
            ),
        ),
        uncertain=(),
    )
    artifacts.write_visual_review(report)
    artifacts.write_issues(1, (_issue(f"visual-review-{digest}-1", issue_type="visual_composition"),))

    links = finding_issue_links(report, artifacts.read_issues(1))
    assert len(links) == 1
    assert links[0]["issue_id"] == f"visual-review-{digest}-1"
    assert links[0]["issue_status"] == "open"
    assert links[0]["issue_type"] == "visual_composition"
    assert links[0]["correction_owner"] == "draw"
    assert links[0]["available"] is True

    missing = finding_issue_links(report, ())
    assert missing[0]["issue_status"] is None
    assert missing[0]["available"] is False

    prepared = _prepare(artifacts, page, render, note="A look.")
    artifacts.write_request(prepared.compiled.request, request_revision=2)
    assert reference_display_for_render(artifacts, 1, render) == ()


def test_reference_entries_fall_back_without_approved_bytes(tmp_path: Path) -> None:
    from novel_to_comic.server.routers.pages import _reference_entries

    entries = _reference_entries(
        tmp_path / "project",
        [{"order": 1, "id": "ward:base", "entity_id": "ward", "appearance_state_id": None,
          "label": "", "visual_anchor": "anchor", "media_type": "image/png"}],
    )
    assert entries[0]["image_path"] is None
    assert entries[0]["display_label"] == "ward"


def test_identical_request_shares_job_but_changed_instructions_are_busy(tmp_path: Path) -> None:
    from novel_to_comic.server.routers.pages import _select_active_correction_job

    def _job(sha: str, page: int = 1, status: str = "queued"):
        return SimpleNamespace(
            project_name="user/proj", kind="complete_page_draw", status=status,
            payload={"page_number": page, "request_sha256": sha, "issue_ids": ["a"]},
        )

    decision, job = _select_active_correction_job(
        [_job("sha-1")], pkey="user/proj", page_number=1, request_sha256="sha-1",
    )
    assert decision == "share"
    assert job.payload["request_sha256"] == "sha-1"

    decision, _ = _select_active_correction_job(
        [_job("sha-1")], pkey="user/proj", page_number=1, request_sha256="sha-2",
    )
    assert decision == "busy"

    decision, _ = _select_active_correction_job(
        [_job("sha-1", status="complete")], pkey="user/proj", page_number=1, request_sha256="sha-2",
    )
    assert decision == "free"

    decision, _ = _select_active_correction_job(
        [_job("sha-1", page=2)], pkey="user/proj", page_number=1, request_sha256="sha-2",
    )
    assert decision == "free"

def _api_client(tmp_path: Path, project_dir: Path):
    from starlette.testclient import TestClient
    from uuid import uuid4
    from novel_to_comic.server.auth import get_current_user

    from novel_to_comic.config import Config as _Config
    from tests.queue_fixtures import create_app
    from novel_to_comic.server.deps import get_project
    from novel_to_comic.state import PipelineState, save_state

    save_state(
        PipelineState(
            project_name="Test Project",
            novel_path="input/test.txt",
            created_at="2026-01-01T00:00:00Z",
        ),
        project_dir,
    )
    app = create_app(tmp_path)
    app.dependency_overrides[get_project] = lambda: (project_dir, _Config(), None)
    app.dependency_overrides[get_current_user] = lambda: "test-user"
    client = TestClient(app, raise_server_exceptions=False)
    client.event_hooks["request"].append(
        lambda request: request.headers.setdefault("Idempotency-Key", str(uuid4()))
    )
    return client


def _write_empty_story_bible(project_dir: Path) -> None:
    from novel_to_comic.artifacts import write_story_bible
    from novel_to_comic.models.story_bible import StoryBible

    write_story_bible(
        project_dir,
        StoryBible(
            title="Fixture", author="Fixture", total_scenes=1,
            characters=[], locations=[], scenes=[], narrative_arcs=[],
        ),
    )


def test_preview_route_accepts_real_frontend_wire_body(tmp_path: Path) -> None:
    artifacts, page, render = _setup(tmp_path, issues=(_issue("issue-dark"),))
    project_dir = tmp_path / "project"
    _write_empty_story_bible(project_dir)
    client = _api_client(tmp_path, project_dir)

    res = client.post(
        "/api/projects/test_project/pages/1/corrections/preview",
        json={
            "comic_page_revision": 1,
            "parent_render_revision": 1,
            "changes": [
                {
                    "id": "c-dark",
                    "issue_id": "issue-dark",
                    "instruction": "Edited: darken deeper.",
                    "annotations": [
                        {
                            "id": "mark-1",
                            "kind": "rectangle",
                            "points": [{"x": 0.1, "y": 0.2}, {"x": 0.4, "y": 0.45}],
                            "note": "Deepen shadow here.",
                        }
                    ],
                }
            ],
            "note": "Hold the reveal.",
            "context_source_unit_ids": ["source-2"],
        },
    )

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["selected_issue_ids"] == ["issue-dark"]
    assert payload["changes"][0]["issue_id"] == "issue-dark"
    assert payload["changes"][0]["instruction"] == "Edited: darken deeper."
    assert payload["note"] == "Hold the reveal."
    assert payload["context"]["selected_source_unit_ids"] == ["source-2"]
    assert payload["estimate"]["estimate_credits"] > 0
    assert payload["estimate"]["reserved_credits"] is not None
    assert isinstance(payload["warnings"], list) and payload["warnings"]


def test_preview_with_two_linked_issues_and_manual_change_keeps_full_identity(tmp_path: Path) -> None:
    """Live preview over 2 linked issues + 1 manual change keeps whole-ID identity.

    Guards the fixed ``dict.fromkeys`` retry-identity path: the old spread of
    three positional args raised ``TypeError`` (500) for exactly this shape,
    and single-ID shapes silently degenerated into character keys. The real
    preview endpoint (no mocks) must return 200, preserve every selection in
    body order, keep the manual pending ID stable across repeats, and leave
    the stored issue history untouched.
    """
    from novel_to_comic.server.routers.pages import _aggregated_correction_retry

    artifacts, page, render = _setup(
        tmp_path,
        issues=(
            _issue("issue-dark"),
            _issue("issue-hand", requested_correction="Fix the extra finger."),
        ),
    )
    project_dir = tmp_path / "project"
    _write_empty_story_bible(project_dir)
    client = _api_client(tmp_path, project_dir)
    body = {
        "comic_page_revision": 1,
        "parent_render_revision": 1,
        "changes": [
            {"id": "c-dark", "issue_id": "issue-dark", "instruction": "Edited: darken deeper."},
            {"id": "c-hand", "issue_id": "issue-hand", "instruction": "Edited: fix the extra finger."},
            {"id": "c-shadow", "instruction": "Push the idol deeper into shadow."},
        ],
    }
    history_before = [(issue.id, issue.status) for issue in artifacts.read_issues(1)]

    res = client.post("/api/projects/test_project/pages/1/corrections/preview", json=body)
    assert res.status_code == 200, res.text
    payload = res.json()
    manual_id = deterministic_manual_issue_id(page_number=1, parent_revision=1, change_id="c-shadow")
    assert payload["selected_issue_ids"] == ["issue-dark", "issue-hand", manual_id]
    assert [(change["id"], change["issue_id"]) for change in payload["changes"]] == [
        ("c-dark", "issue-dark"),
        ("c-hand", "issue-hand"),
        ("c-shadow", manual_id),
    ]
    assert payload["pending_manual_change_ids"] == ["c-shadow"]

    again = client.post("/api/projects/test_project/pages/1/corrections/preview", json=body)
    assert again.status_code == 200, again.text
    assert again.json()["request_sha256"] == payload["request_sha256"]
    assert again.json()["selected_issue_ids"] == payload["selected_issue_ids"]
    assert again.json()["pending_manual_change_ids"] == ["c-shadow"]
    assert [(issue.id, issue.status) for issue in artifacts.read_issues(1)] == history_before

    # The aggregated retry lookup keys on the whole selected ID set: a prior
    # request for these exact full IDs advances the attempt, while the old
    # character-key corruption shape (chars of one ID) matches nothing.
    prepared = _prepare(
        artifacts,
        page,
        render,
        changes=(
            _change("c-dark", "Edited: darken deeper.", issue_id="issue-dark"),
            _change("c-hand", "Edited: fix the extra finger.", issue_id="issue-hand"),
            _change("c-shadow", "Push the idol deeper into shadow."),
        ),
    )
    artifacts.write_request(prepared.compiled.request, request_revision=2)
    retry = _aggregated_correction_retry(
        artifacts, page_number=1, issue_ids=tuple(payload["selected_issue_ids"]),
    )
    assert retry.attempt == 2
    assert retry.retries_request_sha256 == prepared.compiled.request.request_sha256
    splintered = tuple(payload["selected_issue_ids"][0])
    assert len(splintered) > 1
    assert _aggregated_correction_retry(artifacts, page_number=1, issue_ids=splintered).attempt == 1


def test_saved_review_cold_read_returns_null_without_spending(tmp_path: Path) -> None:
    artifacts, page, render = _setup(tmp_path)
    project_dir = tmp_path / "project"
    _write_empty_story_bible(project_dir)
    client = _api_client(tmp_path, project_dir)

    res = client.get("/api/projects/test_project/pages/1/visual-review")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["cached"] is True
    assert payload["report"] is None
    assert payload["finding_issues"] == []
    assert isinstance(payload["references"], list)


def test_visual_review_estimate_is_no_spend_and_needs_render(tmp_path: Path, monkeypatch) -> None:
    artifacts, page, render = _setup(tmp_path)
    project_dir = tmp_path / "project"
    _write_empty_story_bible(project_dir)
    client = _api_client(tmp_path, project_dir)

    import novel_to_comic.page_visual_review as visual_review_module

    def _fail_review(*args: object, **kwargs: object):
        raise AssertionError("estimate must not call the review provider")

    monkeypatch.setattr(visual_review_module, "review_page_visuals", _fail_review)
    before = {p for p in project_dir.rglob("*") if p.is_file()}

    res = client.get("/api/projects/test_project/pages/1/visual-review/estimate")

    assert res.status_code == 200, res.text
    payload = res.json()
    assert payload["estimate_credits"] > 0
    assert {p for p in project_dir.rglob("*") if p.is_file()} == before

    bare_dir = tmp_path / "bare-project"
    bare = TargetArtifacts(bare_dir)
    source = _source()
    bare.write_source(source)
    bare.write_adaptation(_adaptation(source))
    bare.write_page(_page())
    _write_empty_story_bible(bare_dir)
    bare_client = _api_client(tmp_path, bare_dir)

    missing = bare_client.get("/api/projects/test_project/pages/1/visual-review/estimate")

    assert missing.status_code == 409, missing.text


def test_interrupted_correction_route_resumes_original_parent_without_redraw(tmp_path, monkeypatch):
    from novel_to_comic.server.routers import pages

    artifacts, page, _render = _setup(tmp_path, issues=(_issue("issue-dark"),))
    monkeypatch.setattr(pages, "ensure_current_page_edition", lambda *args: _edition())
    monkeypatch.setattr(pages, "approved_visual_inventory", lambda *args: ApprovedVisualReferenceInventory(references=()))
    monkeypatch.setattr(pages, "approved_reference_files", lambda *args: {})
    body = pages.PageCorrectionCreate(
        changes=(_change("dark", "Darken the chamber.", issue_id="issue-dark"),),
        parent_render_revision=1, comic_page_revision=page.revision,
    )
    config = Config(style_template="")
    from .style_reference_support import write_style_proof
    write_style_proof(artifacts.project_dir, config.style_template)
    prepared = pages._prepare_explicit_correction(
        target=artifacts, page_number=1, body=body, config=config,
    )

    class CountingTransport(_Transport):
        calls = 0

        async def generate(self, request):
            self.calls += 1
            return await super().generate(request)

    class UnavailableOCR:
        async def extract(self, image):
            # Cancellation (worker shutdown) still interrupts; ordinary read failures do not.
            raise asyncio.CancelledError("read-back interrupted")

    transport = CountingTransport()
    adapter = VertexCompletePageAdapter(transport)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(correct_complete_page(
            prepared.compiled, issue=None, adapter=adapter,
            artifacts=artifacts, page=page, ocr=UnavailableOCR(),
        ))
    assert artifacts.provenance_revisions(1) == (1, 2)
    resumed = pages._prepare_explicit_correction(
        target=artifacts, page_number=1, body=body, config=config,
    )
    result = asyncio.run(correct_complete_page(
        resumed.compiled, issue=None, adapter=adapter,
        artifacts=artifacts, page=page,
    ))
    assert result.render.parent_revision == 1
    assert result.render.revision == 2
    assert transport.calls == 1


@pytest.fixture(autouse=True)
def reviewed_story_precondition(monkeypatch):
    # This suite tests rendering/credit contracts with deliberately partial
    # upstream fixtures. Real missing/stale review admission is tested in
    # test_narrative_review.py.
    monkeypatch.setattr("novel_to_comic.server.routers.pages.require_draw_narrative_reviews", lambda target: None)
    monkeypatch.setattr("novel_to_comic.narrative_review.require_draw_narrative_reviews", lambda target: None)


def test_reviewing_existing_art_never_requires_todays_draw_profile(tmp_path: Path, monkeypatch) -> None:
    # A retained edition whose model left the catalog can no longer draw, but
    # its finished pages must stay reviewable under their own frozen profile.
    from novel_to_comic.server.routers import pages

    _setup(tmp_path)
    project_dir = tmp_path / "project"
    _write_empty_story_bible(project_dir)
    client = _api_client(tmp_path, project_dir)

    class RetiredDrawProfile:
        def prepare(self, _compiled):
            raise ValueError("Frozen complete-page request does not match the selected profile")

    monkeypatch.setattr(pages, "complete_page_adapter", lambda _config: RetiredDrawProfile())

    assert client.get("/api/projects/test_project/pages/1/visual-review/estimate").status_code == 200
    saved = client.get("/api/projects/test_project/pages/1/visual-review")
    assert saved.status_code == 200, saved.text
    assert saved.json()["report"] is None
