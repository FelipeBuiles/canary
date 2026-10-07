"""Application operations independent of HTTP routing."""

from __future__ import annotations
from novel_to_comic.page_drawing import (
    CompiledPageGeneration,
    CompletePageAdapter,
    estimate_draw_api_cost,
)
from fastapi import FastAPI
from .generation_jobs import GenerationJob
from novel_to_comic.page_review import OCRAdapter
import asyncio
from pathlib import Path
from novel_to_comic.config import Config
from novel_to_comic.models.draw import PageIssue
from novel_to_comic.models.page import ComicPage
from novel_to_comic.target_artifacts import TargetArtifacts


async def enqueue_complete_page_draw(
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
) -> tuple[GenerationJob, bool]:
    """Estimate, reserve, execute, settle, and release one complete-page job."""

    # This is deliberately before the credited-job call: capability, geometry,
    # reference capacity, identity, and selected bytes must fail before cost.
    adapter.prepare(compiled)
    from novel_to_comic.server.credited_job import enqueue_reserved_generation_job
    from novel_to_comic.server.credits import credit_estimate_for_provider_cost
    from novel_to_comic.codex_dev import classify_operations
    from novel_to_comic.server.codex_admission import draw_operations

    operations = draw_operations(config, checks=ocr is not None)
    funding = classify_operations(operations)

    estimate = credit_estimate_for_provider_cost(
        estimate_draw_api_cost(config, compiled, checks=ocr is not None),
        "draw",
        reserve=True,
        zero_cost_estimate=0,
        funding=funding,
    )

    from novel_to_comic.server.job_commands import command, save_blob

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

    return await enqueue_reserved_generation_job(
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
