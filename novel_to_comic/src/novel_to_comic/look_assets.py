"""Produce one Look asset with shared reuse, hold, version and dependency rules."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from novel_to_comic.asset_generation import (
    NonPanelRequest, NonPanelSubmission, asset_matches_request, held_asset_failure,
    submit_non_panel_request,
)
from novel_to_comic.config import Config
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state_assets import mark_dependent_states_stale
from novel_to_comic.usage import ApiResult, UsageRecord


@dataclass(frozen=True)
class LookAssetOutcome:
    status: Literal["reused", "held", "generated"]
    submission: NonPanelSubmission | None = None
    failure: dict | None = None

    @property
    def result(self) -> ApiResult | None:
        return self.submission.result if self.submission else None


async def produce_look_asset(
    *, config: Config, project_dir: Path, request: NonPanelRequest,
    output_path: Path, feature: str, force: bool = False,
    semaphore: asyncio.Semaphore | None = None,
    on_generated: Callable[[ApiResult], Awaitable[ApiResult]] | None = None,
    refresh_review: bool = False,
    usage_sink: Callable[[UsageRecord], None] | None = None,
) -> LookAssetOutcome:
    """Resume without spend, or explicitly regenerate once; archive before overwrite."""
    async with semaphore or asyncio.Semaphore(1):
        if not force:
            if asset_matches_request(output_path, request):
                return LookAssetOutcome("reused")
            if failure := held_asset_failure(output_path, request):
                return LookAssetOutcome("held", failure=failure)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        submission = await submit_non_panel_request(
            config=config, project_dir=project_dir, request=request,
            output_path=output_path, feature=feature,
        )
        observed: set[int] = set()

        def observe(result):
            if usage_sink is not None and result is not None:
                for usage in (result.usage, *result.additional_usage):
                    if usage is not None and id(usage) not in observed:
                        usage_sink(usage)
                        observed.add(id(usage))

        # Record the paid image before cropping or refreshing its review can fail.
        observe(submission.result)
        # Only canonical assets own descendants. State lineage is explicit and
        # never inferred from the filename of a newly generated image.
        kind = request.input.asset_kind
        identity = request.input.asset_identity
        if not request.input.lineage:
            entity_kind = {"character_ref": "character", "location_plate": "location", "prop_ref": "prop"}.get(kind)
            if entity_kind and ":" in identity:
                mark_dependent_states_stale(project_dir, entity_kind, identity.split(":", 1)[1])
        if on_generated is not None and submission.result is not None:
            submission = replace(submission, result=await on_generated(submission.result))
            observe(submission.result)
        if refresh_review and submission.result is not None:
            submission = replace(submission, result=await _refresh_cast_review(config, project_dir, submission.result))
            observe(submission.result)
        return LookAssetOutcome("generated", submission=submission)


async def produce_stage_look_asset(
    *, ctx: StageRuntime, item_id: str, label: str, **kwargs,
) -> LookAssetOutcome | None:
    """Account for one batch item while keeping its siblings independently owned."""
    observed: set[int] = set()

    def record(usage):
        if usage is not None and id(usage) not in observed:
            ctx.record_api_usage(usage)
            observed.add(id(usage))

    try:
        outcome = await produce_look_asset(**kwargs, usage_sink=record)
        if outcome.status == "held":
            ctx.record_item_failed(item_id)
            ctx.log(f"Skipped {label}: {(outcome.failure or {}).get('user_message') or 'the last attempt failed.'} "
                    "Resume Cast will not resubmit the unchanged request. Change this reference's "
                    "direction, or regenerate it from its card.", level="error")
        else:
            ctx.record_item_done()
            if outcome.status == "reused":
                ctx.log(f"Using existing {label}", level="dim")
        return outcome
    except Exception as exc:
        for usage in (*getattr(exc, "usage_records", ()), getattr(exc, "usage", None),
                      *getattr(exc, "additional_usage", ())):
            record(usage)
        ctx.record_item_failed(item_id)
        ctx.log(f"Failed {label}: {exc}", level="error")
        return None
    finally:
        ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)


async def _refresh_cast_review(config: Config, project_dir: Path, result: ApiResult[Path]) -> ApiResult[Path]:
    """Re-run the Character Check after a sheet changes, in the same job.

    Its usage settles with the redraw. A failed or skipped review never fails
    the redraw; the check stays out of date and Resume Cast runs it.
    """
    from novel_to_comic.cast_roster import read_cast_story_bible
    from novel_to_comic.cast_design import review_ready, run_cast_review

    usage: list = []
    try:
        bible = read_cast_story_bible(project_dir)
        if review_ready(config, project_dir, bible):
            await run_cast_review(config, project_dir, bible, log=lambda _message: None, usage_sink=usage.append)
    except Exception as exc:  # noqa: BLE001 — advisory follow-up only
        logging.getLogger(__name__).warning("Character check after redraw skipped: %s", exc)
    # Settle any review call that ran, even when its answer was rejected.
    return replace(result, additional_usage=(*result.additional_usage, *usage)) if usage else result

