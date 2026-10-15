"""Application operations independent of HTTP routing."""

from __future__ import annotations
import asyncio
from fastapi import Request
from novel_to_comic.models.draw import RetryProvenance
from novel_to_comic.page_drawing import (
    complete_page_adapter,
    initial_page_profile,
    select_book_edition,
    compile_page_generation_request,
    ensure_current_page_edition,
)
from novel_to_comic.narrative_review import require_draw_narrative_reviews
from novel_to_comic.lettering.page_read import page_read_adapter
from novel_to_comic.stages.s5_plan import (
    approved_reference_files,
    approved_visual_inventory,
)
from novel_to_comic.state import StageStatus, complete_stage, load_state, save_state
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts
from novel_to_comic.codex_dev import classify_operations
from .codex_admission import draw_operations
from .deps import event_key, project_key
from .page_admission import enqueue_complete_page_draw


def _generation_retry(target: TargetArtifacts, page_number: int) -> RetryProvenance:
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


def _sync_draw_progress(project_dir, app=None) -> None:
    from novel_to_comic.artifact_lock import production_lock

    with production_lock(project_dir):
        _sync_locked_draw_progress(project_dir, app)


def _sync_locked_draw_progress(project_dir, app=None) -> None:
    """Reconcile Draw's stage state with the renders actually on disk.

    Progress is recomputed from artifacts rather than incremented, so a state
    write that loses a race with a concurrent job is corrected by the next call
    instead of leaving Draw stuck in RUNNING with every page already drawn.
    """

    target = TargetArtifacts(project_dir)
    try:
        plan = target.read_plan()
    except ArtifactMissing:
        return
    state = load_state(project_dir)
    draw_state = state.stages["draw"]
    if not plan.pages:
        return
    rendered = sum(
        bool(target.provenance_revisions(page.page_number)) for page in plan.pages
    )

    def terminal(outcome):
        if draw_state.attempt_id and draw_state.telemetry_terminal_outcome is None:
            from .lifecycle_events import capture, stage_properties

            if capture(
                app,
                "stage_succeeded" if outcome == "awaiting_review" else "stage_failed",
                draw_state.attempt_id,
                user_id=draw_state.telemetry_user_id,
                project_id=draw_state.telemetry_project_id,
                properties=stage_properties(draw_state, "draw", outcome),
            ):
                draw_state.telemetry_terminal_outcome = outcome
                save_state(state, project_dir)

    jobs = getattr(getattr(app, "state", None), "generation_jobs", {})
    expected = [jobs.get(job_id) for job_id in draw_state.telemetry_draw_jobs]
    missing = [
        identity
        for identity, job in zip(draw_state.telemetry_draw_jobs, expected)
        if job is None
    ]
    if missing and getattr(getattr(app, "state", None), "admission", None):
        from .job_journal import history
        from types import SimpleNamespace

        # A large book may have more than the bounded in-memory terminal history.
        from .deps import project_key

        key = project_key(draw_state.telemetry_user_id, draw_state.telemetry_project_id)
        records = {}
        for offset in range(0, len(missing), 200):
            saved, _ = history(app, key, ids=missing[offset : offset + 200], limit=200)
            records.update({item["id"]: SimpleNamespace(**item) for item in saved})
        expected = [
            job or records.get(identity)
            for identity, job in zip(draw_state.telemetry_draw_jobs, expected)
        ]
    cohort_failed = any(
        job is not None and job.status in {"failed", "cancelled"} for job in expected
    )
    if expected and all(
        job is not None and job.status in {"complete", "failed", "cancelled"}
        for job in expected
    ):
        terminal(
            "outcome_unknown"
            if any(job.phase == "outcome_unknown" for job in expected)
            else "cancelled"
            if any(job.status == "cancelled" for job in expected)
            else "failed"
            if cohort_failed
            else "awaiting_review"
        )
    elif (
        not expected
        and not draw_state.telemetry_draw_rerun
        and rendered == len(plan.pages)
        and draw_state.status in {StageStatus.AWAITING_REVIEW, StageStatus.COMPLETE}
    ):
        terminal("awaiting_review")
    if draw_state.items_done == rendered and (
        rendered < len(plan.pages) or draw_state.status != StageStatus.RUNNING
    ):
        return
    draw_state.items_done = rendered
    if rendered == len(plan.pages) and draw_state.status == StageStatus.RUNNING:
        complete_stage(state, "draw")
        if not expected and not draw_state.telemetry_draw_rerun:
            terminal("awaiting_review")
    save_state(state, project_dir)


def _draw_success_callback(
    request: Request,
    *,
    pkey: str,
    project_dir,
):
    def callback(provenance) -> None:
        from .lifecycle_events import capture
        from .telemetry import context_fields

        context = context_fields()
        operation_id = context.get("operation_id")
        job = request.app.state.generation_jobs.get(operation_id)
        payload = job.payload if job else {}
        capture(
            request.app,
            "page_ready",
            f"{operation_id}:{provenance.render.page_number}:{provenance.render.revision}",
            user_id=context.get("posthogDistinctId"),
            project_id=context.get("project_id"),
            job_id=context.get("operation_id"),
            properties={
                "page_number": provenance.render.page_number,
                "render_revision": provenance.render.revision,
                "run_id": payload.get("run_id") or operation_id,
                "attempt_id": operation_id,
                "stage_attempt_id": payload.get("stage_attempt_id"),
            },
        )
        _sync_draw_progress(project_dir, request.app)
        queue = request.app.state.event_queues.get(event_key(pkey, project_dir))
        if queue is not None:
            queue.put_nowait(
                {
                    "type": "page_done",
                    "stage": "draw",
                    "page_number": provenance.render.page_number,
                    "revision": provenance.render.revision,
                    "status": "ok",
                    "duration_ms": provenance.render.latency_ms,
                    "error": None,
                }
            )

    return callback


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
    edition = (
        ensure_current_page_edition(
            target, target.read_book_edition(), config, persist=False
        )
        if target.book_edition_path.exists()
        else select_book_edition(
            edition_id="book-edition-001",
            profile=initial_page_profile(project_dir, config),
        )
    )
    inventory = approved_visual_inventory(project_dir)
    reference_files = approved_reference_files(project_dir)
    adapter = complete_page_adapter(config, edition.capability_profile)
    prepared = []
    for selected in target.read_plan().pages:
        page_number = selected.page_number
        if pages is not None:
            if page_number not in pages:
                continue
        elif target.provenance_revisions(page_number) and not rerun:
            continue
        page = target.read_page(page_number)
        compiled = compile_page_generation_request(
            page,
            edition,
            inventory,
            reference_files,
            retry=_generation_retry(target, page_number),
            style_template=config.style_template,
        )
        adapter.prepare(compiled)
        prepared.append((page_number, page, compiled))
    return target, adapter, prepared


async def enqueue_all_undrawn_pages(
    request: Request,
    *,
    project_id: str,
    user_id: str,
    project_dir,
    config,
    rerun: bool = False,
    pages: frozenset[int] | None = None,
):
    """Queue missing pages, or explicit replacement revisions without deletion."""
    target, adapter, prepared = await asyncio.to_thread(
        prepare_undrawn_pages,
        project_dir=project_dir,
        config=config,
        rerun=rerun,
        pages=pages,
    )
    # Estimation can select an ephemeral first edition; submission requires
    # Draw initialization to have durably pinned it first.
    ensure_current_page_edition(target, target.read_book_edition(), config)
    # No reservation or publication occurs until the entire batch is prepared.
    pkey = project_key(user_id, project_id)
    queue = request.app.state.event_queues.get(event_key(pkey, project_dir))
    jobs = []

    for page_number, page, compiled in prepared:
        # Keep dispatch/heartbeats responsive during large batches. Publication
        # stays on the event loop because it owns the in-memory job registry.
        await asyncio.sleep(0)
        job, _created = await enqueue_complete_page_draw(
            request.app,
            project_name=pkey,
            user_id=user_id,
            project_id=project_id,
            project_dir=project_dir,
            config=config,
            compiled=compiled,
            adapter=adapter,
            artifacts=target,
            page=page,
            ocr=page_read_adapter(config, target, page),
        )
        jobs.append(job)
        if queue is not None:
            queue.put_nowait(
                {"type": "page_start", "stage": "draw", "page_number": page_number}
            )

    return tuple(jobs)
