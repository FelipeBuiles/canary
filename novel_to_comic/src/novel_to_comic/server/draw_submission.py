"""Quote, admit and execute frozen page draws without changing provider requests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from novel_to_comic.codex_dev import classify_operations
from novel_to_comic.config import Config
from novel_to_comic.models.draw import CorrectionChange, PageIssue, RetryProvenance
from novel_to_comic.models.page import ComicPage
from novel_to_comic.narrative_review import require_draw_narrative_reviews
from novel_to_comic.page_draw_preparation import DrawPreparation, resolve_draw_edition
from novel_to_comic.page_drawing import (
    CompiledPageGeneration,
    CompletePageAdapter,
    complete_page_adapter,
    estimate_draw_api_cost,
    prepare_page_correction,
)
from novel_to_comic.page_review import OCRAdapter
from novel_to_comic.stages.s5_plan import approved_reference_files
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts

from .codex_admission import draw_operations
from .generation_jobs import GenerationJob
from .render_checks import active_provenance


async def _submit_page_draw(
    app: FastAPI,
    *,
    project_name: str,
    user_id: str,
    project_id: str | None,
    project_dir: Path,
    config: Config,
    compiled: CompiledPageGeneration,
    adapter: CompletePageAdapter,
    artifacts: TargetArtifacts,
    page: ComicPage,
    ocr: "OCRAdapter | None" = None,
    request_revision: int | None = None,
    render_revision: int | None = None,
    parent_render_revision: int | None = None,
    issue: PageIssue | None = None,
    ledger=None,
) -> tuple[GenerationJob, bool]:
    """Quote one complete-page job, persist its inputs and admit it with a hold.

    The durable worker executes, settles and releases it through
    ``execute_page_draw``.
    """

    # This is deliberately before the credited-job call: capability, geometry,
    # reference capacity, identity, and selected bytes must fail before cost.
    adapter.prepare(compiled)
    operations = draw_operations(config, checks=ocr is not None)
    classify_operations(operations)

    estimate = quote_page_draw(config, compiled, checks=ocr is not None)

    from .job_commands import command, save_blob

    def keep_inputs():
        from .storage_budget import ingestion

        with ingestion(
            project_dir,
            sum(len(data) for data in compiled.reference_bytes)
            + len(compiled.edit_source_bytes or b""),
        ):
            return [
                save_blob(project_dir, data) for data in compiled.reference_bytes
            ], save_blob(project_dir, compiled.edit_source_bytes)

    references, edit_source = await asyncio.to_thread(keep_inputs)
    descriptor = command(
        "page_draw",
        project_dir,
        config,
        request=compiled.request.model_dump(mode="json"),
        references=references,
        edit_source=edit_source,
        page=page.model_dump(mode="json"),
        ocr=ocr is not None,
        request_revision=request_revision,
        render_revision=render_revision,
        parent_render_revision=parent_render_revision,
        issue=issue.model_dump(mode="json") if issue else None,
    )

    ledger = ledger or DrawLedger()
    return await ledger.admit(
        app,
        project_name=project_name,
        user_id=user_id,
        project_id=project_id,
        project_dir=project_dir,
        stage="draw",
        kind="complete_page_draw",
        label=f"Page {compiled.request.page_number}",
        payload={
            "page_number": compiled.request.page_number,
            "request_sha256": compiled.request.request_sha256,
            "retry_attempt": compiled.request.retry.attempt,
            "issue_id": issue.id if issue is not None else None,
            "issue_ids": list(compiled.request.correction.issue_ids)
            if compiled.request.correction
            else [],
        },
        debit_description=f"Complete page {compiled.request.page_number}",
        reservation_credits=estimate["reserved_credits"] or 0,
        operations=operations,
        command=descriptor,
    )


def select_active_draw(jobs, *, pkey: str, page_number: int, request_sha256: str):
    """Share one identical in-flight request; reject anything else on the page.

    An identical frozen request already queued or running is shared, so submit
    retries never double-enqueue. Any other active draw job for the same page
    means changed instructions: reject as busy instead of absorbing or
    dropping the edited request into the running one.
    """
    busy = None
    for job in jobs:
        if job.project_name != pkey or job.kind != "complete_page_draw":
            continue
        if job.status not in {"queued", "running"}:
            continue
        if job.payload.get("page_number") != page_number:
            continue
        if job.payload.get("request_sha256") == request_sha256:
            return ("share", job)
        if busy is None:
            busy = job
    if busy is not None:
        return ("busy", busy)
    return ("free", None)


async def execute_page_draw(app, job, directory, config, *, adapter=None):
    """Run a queued page command exactly as frozen, refusing changed page input."""
    from types import SimpleNamespace

    from novel_to_comic.lettering.page_read import page_read_adapter
    from novel_to_comic.page_drawing import page_draw_execution, page_visual_check

    from .job_commands import read_blob
    from .page_draw_job import PageDrawJob
    from .page_operations import _draw_success_callback

    args = PageDrawJob(job.command).arguments
    target = TargetArtifacts(directory)
    frozen = args.request
    page = args.page
    selected = next((p for p in target.read_plan().pages if p.page_number == page.page_number), None)
    current = target.read_page(page.page_number)
    if (
        selected is None
        or selected.revision != current.revision
        or selected.content_sha256 != current.content_sha256
        or frozen.is_stale_for(current)
    ):
        raise ValueError("Queued page input changed; explicitly prepare a new draw")
    compiled = CompiledPageGeneration(
        frozen,
        tuple(read_blob(directory, digest) for digest in args.references),
        read_blob(directory, args.edit_source),
    )
    ocr = page_read_adapter(config, target, page) if args.ocr else None
    work, settled = page_draw_execution(
        project_dir=directory,
        compiled=compiled,
        adapter=adapter or complete_page_adapter(config, request=frozen),
        artifacts=target,
        page=page,
        ocr=ocr,
        visual_review=page_visual_check(config, directory, target, page) if ocr is not None else None,
        request_revision=args.request_revision,
        render_revision=args.render_revision,
        parent_render_revision=args.parent_render_revision,
        issue=args.issue,
        on_success=_draw_success_callback(SimpleNamespace(app=app), pkey=job.project_name, project_dir=directory),
    )
    return await work(), settled


def correction_retry(
    target: TargetArtifacts,
    *,
    page_number: int,
    issue_ids: tuple[str, ...],
) -> RetryProvenance:
    """Advance retry identity for one exact selected-issue set."""
    selected = frozenset(issue_ids)
    resumable = target.resumable_generation_request(page_number)
    if (resumable is not None and resumable.correction is not None
            and frozenset(resumable.correction.issue_ids) == selected):
        return resumable.retry
    prior_attempts = [
        target.read_request(page_number, revision)
        for revision in target.request_revisions(page_number)
    ]
    matching = [
        request
        for request in prior_attempts
        if request.correction is not None
        and frozenset(request.correction.issue_ids) == selected
    ]
    if not matching:
        return RetryProvenance(attempt=1)
    prior = max(matching, key=lambda request: request.retry.attempt)
    return RetryProvenance(
        attempt=prior.retry.attempt + 1,
        retries_request_sha256=prior.request_sha256,
    )


def quote_page_draw(config, compiled, *, checks=True):
    """Price precisely the frozen request that submission will execute."""
    from .credits import credit_estimate_for_provider_cost

    return credit_estimate_for_provider_cost(
        estimate_draw_api_cost(config, compiled, checks=checks),
        "draw", reserve=True, zero_cost_estimate=0,
        funding=classify_operations(draw_operations(config, checks=checks)),
    )


def _part_draw_jobs(app, project_dir):
    from .generation_jobs import generation_jobs_snapshot, job_part_id
    from novel_to_comic.workspace import part_id_for_path

    part_id = part_id_for_path(project_dir)
    return [job for job in generation_jobs_snapshot(app) if job_part_id(job) == part_id]


def _busy_message(page_number: int) -> str:
    return (f"Page {page_number} has an active draw job; wait for it to finish "
            "before submitting changed instructions.")


def require_batch_not_busy(app, *, project_name: str, project_dir, prepared) -> None:
    """Refuse a batch before any page is admitted when one page is busy.

    Per-page admission still serializes and rechecks; this keeps an ordinary
    conflict from reserving the earlier pages of a batch that then fails.
    """
    jobs = _part_draw_jobs(app, project_dir)
    for page_number, _page, compiled in prepared:
        decision, _job = select_active_draw(
            jobs, pkey=project_name, page_number=page_number,
            request_sha256=compiled.request.request_sha256,
        )
        if decision == "busy":
            raise HTTPException(409, _busy_message(page_number))


async def enqueue_complete_page_draw(app, **inputs):
    """Serialize admission per part/page, sharing identical active commands.

    The lock covers blob persistence and admission as well as the busy decision;
    simultaneous different actions cannot both observe an empty page lane.
    """
    locks = getattr(app.state, "page_draw_admission_locks", None)
    if locks is None:
        locks = app.state.page_draw_admission_locks = {}
    key = (str(inputs["project_dir"]), inputs["compiled"].request.page_number)
    lock = locks.setdefault(key, asyncio.Lock())
    async with lock:
        decision, job = select_active_draw(
            _part_draw_jobs(app, inputs["project_dir"]),
            pkey=inputs["project_name"], page_number=key[1],
            request_sha256=inputs["compiled"].request.request_sha256,
        )
        if decision == "share":
            return job, False
        if decision == "busy":
            raise HTTPException(409, _busy_message(key[1]))
        return await _submit_page_draw(app, **inputs)


def redraw_inputs(project_dir):
    from novel_to_comic.stages.s5_plan import approved_visual_inventory

    inventory = {ref.id: ref for ref in approved_visual_inventory(project_dir).references}
    return approved_reference_files(project_dir), inventory


def page_redraw(project_dir, target: TargetArtifacts, page_number: int) -> dict | None:
    from novel_to_comic.page_redraws import redraw_reasons

    try:
        return redraw_reasons(target, page_number, *redraw_inputs(project_dir))
    except (ArtifactMissing, ArtifactInvalid, ValueError, OSError):
        return None


def latest_render_is_stale(target: TargetArtifacts, page_number: int, revision: int) -> bool:
    """A re-planned page: its newest art belongs to an earlier ComicPage.

    A correction edits art of the same page revision, so such a page is drawn
    fresh from its current plan instead; the old art stays in its history.
    """
    try:
        return target.read_provenance(page_number, revision).render.is_stale_for(target.read_page(page_number))
    except (ArtifactMissing, ArtifactInvalid):
        return False


def prepare_initial_generation(
    project, page_number: int, depiction: Literal["canonical", "less_graphic"], *, persist: bool = True,
):
    project_dir, config, _state = project
    classify_operations(draw_operations(config))
    target = TargetArtifacts(project_dir)
    resumable = target.resumable_generation_request(page_number)
    revisions = target.provenance_revisions(page_number)
    if revisions and (resumable is None or resumable.correction is not None) and not latest_render_is_stale(
        target, page_number, revisions[-1],
    ) and page_redraw(project_dir, target, page_number) is None:
        raise HTTPException(
            409,
            "Page already has a render; create an issue and request a correction.",
        )
    try:
        require_draw_narrative_reviews(target)
        page = target.read_page(page_number)
        authority = DrawPreparation.load(target, config, persist=persist)
        compiled = authority.compile(page, retry=generation_retry(target, page_number), depiction=depiction)
    except (ArtifactMissing, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    return target, page, compiled


class PageCorrectionCreate(BaseModel):
    """One explicit author-edited correction set for a single full-page job."""

    changes: tuple[CorrectionChange, ...] = Field(default=(), max_length=24)
    note: str = Field(default="", max_length=1000)
    context_source_unit_ids: tuple[str, ...] = ()
    parent_render_revision: int = Field(ge=1)
    comic_page_revision: int = Field(ge=1)


def prepare_explicit_correction(
    *, target: TargetArtifacts, page_number: int, body: PageCorrectionCreate, config, persist: bool = True,
):
    """Run the shared no-spend validation+compile; maps failures to HTTP."""
    from novel_to_comic.page_review import (
        InvalidCorrectionError,
        StaleCorrectionError,
        deterministic_manual_issue_id,
    )

    try:
        require_draw_narrative_reviews(target)
        page = target.read_page(page_number)
        authority = DrawPreparation.load(target, config, persist=persist)
        provenance = active_provenance(target, page_number)
        resumable = target.resumable_generation_request(page_number)
        if (resumable is not None and resumable.correction is not None
                and resumable.correction.parent_render_revision == body.parent_render_revision):
            # Publication can have succeeded before OCR/settlement failed.
            # Recompile against the original correction parent, not the new
            # unpaid/unconfirmed publication, to preserve the frozen identity.
            provenance = target.read_provenance(page_number, body.parent_render_revision)
        if provenance is None:
            raise StaleCorrectionError("a rendered page is required before correcting findings")
        if body.parent_render_revision != provenance.render.revision:
            raise StaleCorrectionError(
                f"correction targets render {body.parent_render_revision}, "
                f"but current render is {provenance.render.revision}"
            )
        # The requested canonical revision plus the exact active parent
        # revision gate staleness here; the builder additionally verifies the
        # authoritative page SHA and the exact parent render bytes.
        if body.comic_page_revision != page.revision:
            raise StaleCorrectionError("correction targets a superseded ComicPage revision")
        # Retry lineage covers the full deterministic id set (linked issues
        # plus manual changes), so preview, submit, and retries share one
        # identity for one author selection.
        full_issue_ids = tuple(dict.fromkeys(
            change.issue_id
            if change.issue_id is not None
            else deterministic_manual_issue_id(
                page_number=page_number,
                parent_revision=provenance.render.revision,
                change_id=change.id,
            )
            for change in body.changes
        ))
        prepared = prepare_page_correction(
            page=page,
            edition=authority.edition,
            inventory=authority.inventory,
            reference_files=authority.reference_files,
            retry=correction_retry(
                target, page_number=page_number, issue_ids=full_issue_ids,
            ),
            parent=provenance.render,
            changes=tuple(body.changes),
            note=body.note,
            context_source_unit_ids=tuple(body.context_source_unit_ids),
            artifacts=target,
            style_template=config.style_template,
        )
        complete_page_adapter(config, request=prepared.compiled.request).prepare(prepared.compiled)
        return prepared
    except StaleCorrectionError as exc:
        raise HTTPException(409, str(exc)) from exc
    except InvalidCorrectionError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ArtifactInvalid as exc:
        raise HTTPException(
            409,
            f"Saved page artifacts failed validation and the correction cannot proceed: {exc}. "
            "Re-run the owning stage and retry.",
        ) from exc
    except ArtifactMissing as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        message = str(exc)
        # Prompt/reference overflow is fixable client-side (select less);
        # missing bytes or edition conflicts behave like other 409s here.
        status = 422 if "exceed" in message else 409
        raise HTTPException(status, message) from exc


def generation_retry(target: TargetArtifacts, page_number: int) -> RetryProvenance:
    """Resume an incomplete durable paid result before allocating a retry."""
    resumable = target.resumable_generation_request(page_number)
    if resumable is not None and resumable.correction is None:
        return resumable.retry

    prior_requests = [
        target.read_request(page_number, revision)
        for revision in target.request_revisions(page_number)
    ]
    prior_attempts = [
        request for request in prior_requests if request.correction is None
    ]
    if not prior_attempts:
        return RetryProvenance(attempt=1)
    prior = max(prior_attempts, key=lambda request: request.retry.attempt)
    return RetryProvenance(
        attempt=prior.retry.attempt + 1,
        retries_request_sha256=prior.request_sha256,
    )


class DrawLedger:
    """Production admission seam; the durable worker retains reservation/settlement."""

    async def admit(self, app, **submission):
        from .credited_job import enqueue_reserved_generation_job
        return await enqueue_reserved_generation_job(app, **submission)


def prepare_undrawn_pages(
    *, project_dir, config, rerun: bool = False, pages: frozenset[int] | None = None
):
    """Preflight every selected page without writing an edition or placing holds.

    ``pages`` limits the batch to an explicit set (out-of-date drawn pages),
    drawn or not.
    """
    classify_operations(draw_operations(config))
    target = TargetArtifacts(project_dir)
    require_draw_narrative_reviews(target)
    authority = DrawPreparation.load(target, config, allow_new=True)
    adapter = authority.adapter()
    prepared = []
    for selected in target.read_plan().pages:
        page_number = selected.page_number
        if pages is not None:
            if page_number not in pages:
                continue
        elif target.provenance_revisions(page_number) and not rerun:
            continue
        page = target.read_page(page_number)
        compiled = authority.compile(page, retry=generation_retry(target, page_number))
        prepared.append((page_number, page, compiled))
    return target, adapter, prepared


def initialize_draw_stage(target, config):
    """Admit the checkpoint and pin its edition before any page is queued."""
    classify_operations(draw_operations(config))
    require_draw_narrative_reviews(target)
    plan = target.read_plan()
    # Existing editions advance by the same rule as each submitted page.
    resolve_draw_edition(target, config, persist=True, allow_new=True)
    return plan


def estimate_draw_stage_cost(target, config):
    """Price the stage's complete planned book using its historical quote identity."""
    classify_operations(draw_operations(config))
    # Resolve the profile even before Plan exists, retaining the prior gate.
    resolve_draw_edition(target, config, allow_new=True)
    if not target.plan_path.exists():
        return 0.0
    authority = DrawPreparation.load(target, config, allow_new=True, quote_identity=True)
    return sum(estimate_draw_api_cost(config, authority.compile(
        target.read_page(selected.page_number), retry=RetryProvenance(attempt=1),
    )) for selected in target.read_plan().pages)
