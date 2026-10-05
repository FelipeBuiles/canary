"""Operation registry and settlement for durable jobs.

Handlers reconstruct only explicit, typed inputs. Provider execution never
replays an HTTP mutation or reserves a second copy of an admitted command.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

from pydantic import TypeAdapter

from novel_to_comic.ai import ai_request_context
from novel_to_comic.config import Config
from novel_to_comic.state import load_state
from novel_to_comic.target_artifacts import TargetArtifacts
from .job_commands import read_blob


class PipelineStageFailed(RuntimeError):
    """A settled failure whose cause is reported at its handling boundary.

    Expected insufficient-credit denials intentionally do not report exceptions.
    """


async def execute_command(app, job):
    from .credits import (reserve_credits, assert_reservation_active, debit_model_usage,
                          release_reservation, retain_ambiguous_job)
    from .db import get_db

    spec = job.command
    directory = Path(spec.project_dir)
    from .project_paths import project_directory
    from novel_to_comic.workspace import is_part_workspace, part_id_for_path, part_workspace
    # A part operation addresses its workspace inside the project root.
    part = part_id_for_path(directory)
    root = directory.parent.parent if part else directory
    if root != project_directory(app.state.projects_dir, spec.user_id, root.name):
        raise ValueError("Operation project is outside its account volume")
    if part and (directory != part_workspace(root, part) or not is_part_workspace(directory)):
        raise ValueError("Operation part is outside its project")
    if not (directory / "state.json").exists():
        raise ValueError("Operation project no longer exists")
    config = Config.model_validate(spec.config)
    config._one_shot_image_model_alias = spec.one_shot_image_model_alias
    if spec.operation == "pipeline":
        return await _pipeline(app, job, directory, config)
    db = get_db()
    reservation, ledger_id = reserve_credits(db, spec.user_id, spec.project_id, spec.stage,
                                            spec.reservation_credits, job_id=spec.ledger_job_id)
    try:
        assert_reservation_active(db, reservation)
        with ai_request_context(user_id=spec.user_id, project_id=spec.project_id,
                                project_name=directory.name, workspace_id=str(directory.parent),
                                stage=spec.stage, job_id=ledger_id,
                                page_number=job.payload.get("page_number"),
                                is_correction=bool(job.payload.get("issue_ids") or job.payload.get("issue_id"))):
            result, settled = await _operate(app, job, directory, config)
        if result is not None:
            for usage in (result.usage, *result.additional_usage):
                if usage is not None:
                    debit_model_usage(db, spec.user_id, spec.project_id, usage,
                                      stage=spec.stage, description=spec.debit_description, job_id=ledger_id)
            if settled is not None:
                settled(result)
    except asyncio.CancelledError:
        retain_ambiguous_job(ledger_id)
        raise
    finally:
        if reservation:
            release_reservation(db, reservation)


async def _operate(app, job, directory, config):
    spec = job.command
    args = spec.arguments
    target = TargetArtifacts(directory)
    if spec.operation == "page_draw":
        from novel_to_comic.page_drawing import (
            CompiledPageGeneration, complete_page_adapter, page_draw_execution, page_visual_check,
        )
        from novel_to_comic.models.draw import FrozenPageGenerationRequest
        from novel_to_comic.models.page import ComicPage
        from novel_to_comic.models.draw import PageIssue
        from .routers.pages import _draw_success_callback

        frozen = FrozenPageGenerationRequest.model_validate(args["request"])
        page = ComicPage.model_validate(args["page"])
        current = next((p for p in target.read_plan().pages if p.page_number == page.page_number), None)
        if current is None or frozen.is_stale_for(current):
            raise ValueError("Queued page input changed; explicitly prepare a new draw")
        compiled = CompiledPageGeneration(frozen,
            tuple(read_blob(directory, digest) for digest in args["references"]),
            read_blob(directory, args.get("edit_source")))
        from novel_to_comic.lettering.page_read import page_read_adapter
        ocr = page_read_adapter(config, target, page) if args.get("ocr") else None
        work, settled = page_draw_execution(
            project_dir=directory, compiled=compiled, adapter=complete_page_adapter(config, request=frozen),
            artifacts=target, page=page, ocr=ocr,
            visual_review=page_visual_check(config, directory, target, page) if ocr is not None else None,
            request_revision=args.get("request_revision"), render_revision=args.get("render_revision"),
            parent_render_revision=args.get("parent_render_revision"),
            issue=PageIssue.model_validate(args["issue"]) if args.get("issue") else None,
            on_success=_draw_success_callback(SimpleNamespace(app=app), pkey=job.project_name, project_dir=directory),
        )
        return await work(), settled
    if spec.operation == "cover":
        from .routers.projects import _generate_project_cover
        return await _generate_project_cover(config, directory, spec.user_id, spec.project_id), None
    if spec.operation == "cast_asset":
        from novel_to_comic.stages import s3_cast
        asset_id, _, state_id = args["asset_id"].partition(":")
        if args["kind"] == "character_ref_regen":
            result = (await s3_cast.regenerate_character_state_ref(config, directory, asset_id, state_id)
                      if state_id else await s3_cast.regenerate_character_ref(config, directory, asset_id))
        elif args["kind"] == "location_plate_regen":
            result = await s3_cast.regenerate_location_plate(config, directory, asset_id, state_id=state_id or None)
        else:
            result = await s3_cast.regenerate_prop_ref(config, directory, asset_id)
        from novel_to_comic.cast_instructions import _clear_repaired_cast_failure
        _clear_repaired_cast_failure(directory, args["asset_id"])
        return result, None
    if spec.operation == "cast_instruction":
        from novel_to_comic.cast_instructions import instructed_asset_execution
        from novel_to_comic.cast_reference_inputs import parse_reference_input
        from .db import get_db
        work = instructed_asset_execution(config, directory, get_db(), spec.user_id, spec.project_id,
            args["asset_type"], args["asset_id"], args["instruction"], args.get("state_id"),
            [parse_reference_input(item) for item in args["attachments"]])
        return await work(), None
    if spec.operation == "lettering_translation":
        from novel_to_comic.lettering.translation import PreparedTranslation, translate_project
        prepared = TypeAdapter(PreparedTranslation).validate_python(args["prepared"])
        await translate_project(target, config, prepared)
        return None, None
    if spec.operation == "frozen_asset":
        from novel_to_comic.asset_generation import NonPanelRequest, persist_non_panel_provenance
        from novel_to_comic.frozen_requests import execute_frozen_request
        request = TypeAdapter(NonPanelRequest).validate_python(args["request"])
        output = directory / args["output_path"]
        output.resolve().relative_to(directory.resolve())
        try:
            result = await execute_frozen_request(project_dir=directory,
                request_id=args["frozen_request_id"], config=config, output_path=output, feature=args["feature"])
        except BaseException as exc:
            persist_non_panel_provenance(request=request, output_path=output, project_dir=directory,
                                        request_id=args["frozen_request_id"], error=exc)
            raise
        persist_non_panel_provenance(request=request, output_path=output, project_dir=directory,
                                    request_id=args["frozen_request_id"], result=result)
        return result, None
    if spec.operation in {"style_sample", "style_validation", "style_suggest", "style_direction"}:
        from .style_jobs import execute_style
        await execute_style(app, job, directory, config)
        return None, None
    raise ValueError(f"Unsupported operation: {spec.operation}")


async def _pipeline(app, job, directory, config):
    from .routers.pipeline import _run_stage_with_credits
    from .event_channel import EventChannel
    from novel_to_comic.state import StageStatus
    spec = job.command
    from .deps import event_key
    channel = app.state.event_queues.setdefault(event_key(job.project_name, directory), EventChannel())
    state = load_state(directory)
    try:
        await _run_stage_with_credits(spec.stage, config, directory, state, channel,
            spec.user_id, spec.project_id, rerun=spec.arguments.get("rerun", False),
            request=SimpleNamespace(app=app), queue_draw_pages=spec.arguments.get("queue_pages", False),
            approve_part=spec.arguments.get("approve_part"))
        active_stage = job.payload.get("stage", spec.stage)
        outcome = state.stages[active_stage]
        if outcome.status == StageStatus.FAILED:
            raise PipelineStageFailed(outcome.error or "Pipeline stage failed")
    except Exception as exc:
        # Orchestration can fail after StageRuntime has initialized Draw but
        # before any child page job exists. Persist that failure too.
        from novel_to_comic.artifact_lock import production_lock
        from novel_to_comic.state import fail_stage, save_state
        with production_lock(directory):
            latest = load_state(directory)
            active_stage = job.payload.get("stage", spec.stage)
            if latest.stages[active_stage].status == StageStatus.RUNNING:
                message = str(exc) or type(exc).__name__
                fail_stage(latest, active_stage, message)
                save_state(latest, directory)
                channel.put_nowait({"type": "stage_fail", "stage": active_stage, "message": message})
        raise
    finally:
        channel.put_nowait({"type": "pipeline_done"})
