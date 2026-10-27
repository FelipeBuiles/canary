"""Durable Style operations with independent proof outcomes and owned children."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from novel_to_comic import artifacts, cold_open
from novel_to_comic.artifact_lock import production_lock
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.state import StageStatus, load_state
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.stages import s2_style as style
from .event_channel import EventChannel
from .generation_jobs import persist_generation_job


def _runtime(directory, channel=None):
    # The Look room subscribes to style_suggest events; state belongs to Style.
    emit = (lambda event: channel.put_nowait({**event, "stage": "style_suggest"})) if channel else None
    return StageRuntime("style", load_state(directory), directory, on_event=emit)


def _account_proofs(ctx, proofs):
    done = sum(proof["status"] == "complete" for proof in proofs.values())
    for _ in range(max(0, done - ctx.stage_state.items_done)):
        ctx.record_item_done()
    for identity, proof in proofs.items():
        if proof["status"] == "failed" and identity not in ctx.stage_state.items_failed:
            ctx.record_item_failed(identity)
    return done


def _checkpoint(directory, owned, proofs, error=None, channel=None):
    if not owned:
        return
    # Selection and lettering are independent mutations; never save the state
    # snapshot that was captured before those edits.
    with production_lock(directory):
        state = load_state(directory)
        if state.stages["style"].status != StageStatus.RUNNING:
            return
        ctx = _runtime(directory, channel)
        _account_proofs(ctx, proofs)
        if error:
            ctx.fail(error)
        else:
            ctx.complete()


def _record_progress(directory, owned, proofs, channel=None) -> None:
    """Keep the Style stage's done count current while proofs finish.

    The status API's item counts feed every progress view outside the Look
    room (the floating indicator); without this they stayed at zero until the
    whole batch ended.
    """
    with production_lock(directory):
        ctx = _runtime(directory, channel)
        done = sum(proof["status"] == "complete" for proof in proofs.values())
        if owned and ctx.stage_state.status == StageStatus.RUNNING:
            _account_proofs(ctx, proofs)
        ctx.progress(done, len(proofs))


STYLE_OPERATIONS = frozenset({"style_sample", "style_validation", "style_suggest", "style_direction"})


def settle_interrupted_style(job, directory) -> None:
    """A hard stop skips execute_style's own failure checkpoint; apply it on restore.

    Without this the Style stage stays "running" forever: the room shows
    generating and blocks every retry, although no work exists. Idempotent:
    ``_checkpoint`` only acts on a stage that is still running.
    """
    if (directory / "state.json").exists():
        _checkpoint(directory, job.command.arguments.get("lifecycle_owned", False),
                    job.payload.get("proofs", {}), job.error or "Style generation interrupted")


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

    recorded_calls: set[str] = set()

    def record_usage(usage):
        if usage.call_id in recorded_calls:
            return
        # Reload under the same lock as selection so asynchronous children never
        # save a stale Story/Style state snapshot over an author mutation.
        with production_lock(directory):
            StageRuntime("style", load_state(directory), directory).record_api_usage(usage)
            recorded_calls.add(usage.call_id)

    async def shared_brief():
        nonlocal brief_resolved, sample_brief
        async with brief_lock:
            if not brief_resolved:
                with style.style_text_usage(record_usage):
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
            result = await style.generate_sample_image(cfg, bible, output, brief=brief, **kwargs)
            if result is not None:
                for usage in ((result.usage,) if result.usage else ()) + result.additional_usage:
                    record_usage(usage)
            proof["status"] = "complete"
        except BaseException as exc:
            proof.update(status="failed", error=str(exc) or type(exc).__name__)
            raise
        finally:
            persist_generation_job(app, job)
            _record_progress(directory, owned, job.payload["proofs"], channel)

    def set_phase(phase, **fields):
        # Durable, so a reloaded room can still explain which step is running.
        job.payload.update(style_phase=phase, style_phase_at=datetime.now(timezone.utc).isoformat(), **fields)
        persist_generation_job(app, job)

    async def batch(candidates, start):
        for offset, candidate in enumerate(candidates):
            job.payload["proofs"][str(start + offset)] = {
                "index": start + offset, "id": candidate["id"], "status": "queued"}
        set_phase("proofs")
        semaphore = asyncio.Semaphore(config.effective_image_concurrency())
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
            direction = args.get("direction")
            if operation == "style_direction":
                await one(args["candidate"], args["index"])
                with style.style_text_usage(record_usage):
                    await style.describe_custom_direction(
                        config, directory, args["candidate"],
                        artifacts.style_sample_path(directory, args["index"]), bible.title,
                    )
                if not args.get("with_neighbors"):
                    _checkpoint(directory, owned, job.payload["proofs"], channel=channel)
                    return
            existing = style.load_suggestions(directory)
            set_phase("directions")
            # The proof brief needs only the Story Bible: author it meanwhile.
            brief_task = asyncio.create_task(shared_brief())

            async def shortlisted(sketches):
                set_phase("production", style_shortlist=[
                    {"label": sketch["label"], "medium": sketch["medium"], "role": sketch["role"],
                     "palette": sketch["palette"], "story_fit": sketch["story_fit"]}
                    for sketch in sketches
                ])

            try:
                with style.style_text_usage(record_usage):
                    suggestions, _usages = await style.generate_suggestions(config, bible,
                        existing_suggestions=existing + cold_open.adoptable_looks(config, directory, bible, existing),
                        custom_direction=direction, on_shortlist=shortlisted)
            except BaseException:
                await style.settle_style_sample_brief(brief_task, cancel=True)
                raise
            await style.settle_style_sample_brief(brief_task)
            with production_lock(directory):
                # No competing suggestion batch is admitted; selecting a proof
                # changes config/lettering, not this candidate portfolio. Re-read
                # so renames and hides made during generation are preserved.
                existing = style.load_suggestions(directory)
                # Cold Open proofs Style would draw identically join without spend.
                adopted = cold_open.adoptable_looks(config, directory, bible, existing)
                cold_open.adopt_into_style(directory, adopted, len(existing) + 1)
                existing += adopted
                style.save_suggestions(directory, existing + suggestions, bible.title)
            await batch(suggestions, len(existing) + 1)
        _checkpoint(directory, owned, job.payload["proofs"], channel=channel)
    except BaseException as exc:
        # A malformed paid JSON response never returns through the successful
        # result observer. Account for its evidence before closing the job.
        for usage in getattr(exc, "usage_records", ()):
            record_usage(usage)
        _checkpoint(directory, owned, job.payload["proofs"], str(exc) or type(exc).__name__, channel=channel)
        raise
