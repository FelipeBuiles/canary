"""Durable Style operations with independent proof outcomes and owned children."""
from __future__ import annotations

import asyncio

from novel_to_comic import artifacts
from novel_to_comic.artifact_lock import production_lock
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.state import StageStatus, complete_stage, fail_stage, load_state, save_state
from novel_to_comic.stages import s2_style as style
from .event_channel import EventChannel
from .generation_jobs import persist_generation_job


def _checkpoint(directory, owned, proofs, error=None):
    if not owned:
        return
    # Selection and lettering are independent mutations; never save the state
    # snapshot that was captured before those edits.
    with production_lock(directory):
        state = load_state(directory)
        if state.stages["style"].status != StageStatus.RUNNING:
            return
        state.stages["style"].items_done = sum(proof["status"] == "complete" for proof in proofs.values())
        if error:
            fail_stage(state, "style", error)
        else:
            complete_stage(state, "style")
        save_state(state, directory)


async def execute_style(app, job, directory, config):
    args = job.command.arguments
    operation = job.command.operation
    bible = StoryBible.model_validate(args["bible"])
    channel = app.state.event_queues.setdefault(job.project_name, EventChannel())
    owned = args.get("lifecycle_owned", False)
    job.payload.setdefault("proofs", {})
    brief_lock = asyncio.Lock()
    brief_resolved = False
    sample_brief = None

    async def shared_brief():
        nonlocal brief_resolved, sample_brief
        async with brief_lock:
            if not brief_resolved:
                sample_brief = await style.ensure_style_sample_brief(config, bible, directory)
                # None is a deliberate deterministic fallback, shared by the
                # entire batch rather than retried for each candidate.
                brief_resolved = True
            return sample_brief

    async def one(candidate, index, validation=False):
        identity = candidate["id"]
        proof = {"index": index, "id": identity, "status": "running"}
        job.payload["proofs"][str(index)] = proof
        persist_generation_job(app, job)
        try:
            cfg = config.model_copy(update={"style_template": style.style_template_for_suggestion(candidate)})
            direction = style.load_style_direction(directory, candidate.get("direction_id")) if candidate.get("direction_id") else None
            reference = style.style_direction_image(directory, direction) if direction else None
            brief = style.style_validation_brief(bible) if validation else await shared_brief()
            output = artifacts.style_validation_path(directory, identity) if validation else artifacts.style_sample_path(directory, index)
            kwargs = dict(candidate_id=f"{identity}:validation" if validation else identity,
                          style_reference=reference, style_reference_mode=candidate["style_reference_mode"])
            if validation:
                kwargs.update(project_dir=directory, subject_action=style.STYLE_VALIDATION_ACTION,
                              composition=style.STYLE_VALIDATION_COMPOSITION)
            await style.generate_sample_image(cfg, bible, output, brief=brief, **kwargs)
            proof["status"] = "complete"
        except BaseException as exc:
            proof.update(status="failed", error=str(exc) or type(exc).__name__)
            raise
        finally:
            persist_generation_job(app, job)
            channel.put_nowait({"type": "stage_progress", "stage": "style_suggest",
                "done": sum(p["status"] == "complete" for p in job.payload["proofs"].values()),
                "total": len(job.payload["proofs"])})

    async def batch(candidates, start):
        for offset, candidate in enumerate(candidates):
            job.payload["proofs"][str(start + offset)] = {
                "index": start + offset, "id": candidate["id"], "status": "queued"}
        persist_generation_job(app, job)
        semaphore = asyncio.Semaphore(style.SAMPLE_CONCURRENCY)
        async def bounded(candidate, index):
            async with semaphore:
                await one(candidate, index)
        # All siblings remain owned until each finishes or cancellation is
        # acknowledged. One failed proof does not discard successful siblings.
        outcomes = await asyncio.gather(*(bounded(candidate, start + i) for i, candidate in enumerate(candidates)), return_exceptions=True)
        errors = [outcome for outcome in outcomes if isinstance(outcome, BaseException)]
        if errors:
            raise RuntimeError(f"{len(errors)} style proof(s) failed: {errors[0]}")

    try:
        if operation in {"style_sample", "style_validation"}:
            await one(args["candidate"], args["index"], operation == "style_validation")
        else:
            channel.put_nowait({"type": "stage_begin", "stage": "style_suggest", "total": 6})
            direction = args.get("direction")
            if operation == "style_direction":
                await one(args["candidate"], args["index"])
                if not args.get("with_neighbors"):
                    _checkpoint(directory, owned, job.payload["proofs"])
                    return
            existing = style.load_suggestions(directory)
            suggestions, _usage = await style.generate_suggestions(config, bible,
                existing_suggestions=existing, custom_direction=direction)
            with production_lock(directory):
                # No competing suggestion batch is admitted; selecting a proof
                # changes config/lettering, not this candidate portfolio.
                style.save_suggestions(directory, existing + suggestions, bible.title)
            await batch(suggestions, len(existing) + 1)
        _checkpoint(directory, owned, job.payload["proofs"])
        channel.put_nowait({"type": "stage_complete", "stage": "style_suggest"})
    except BaseException as exc:
        _checkpoint(directory, owned, job.payload["proofs"], str(exc) or type(exc).__name__)
        channel.put_nowait({"type": "stage_fail", "stage": "style_suggest", "message": str(exc) or "Style generation interrupted"})
        raise
