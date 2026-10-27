"""The Canary-paid Cold Open: admission when Extract reads the opening, and its job.

Admission is orchestration: Extract only publishes its opening snapshot, and
this module decides whether the account still has its Cold Open. Every model
call in the job runs with ``sponsor="cold_open"``, so usage is recorded at its
provider cost but never authorized against or debited from the author.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path

from novel_to_comic import cold_open
from novel_to_comic.artifact_lock import production_lock
from novel_to_comic.config import Config
from novel_to_comic.lettering.proof import LABEL_COPY
from novel_to_comic.models.cold_open import ColdOpenRecord
from novel_to_comic.style_contract import style_template_for_suggestion
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts
from novel_to_comic.workspace import FIRST_PART_ID, is_part_workspace, part_id_for_path, series_root
from .deps import project_key
from .generation_jobs import (
    enqueue_generation_job, find_active_generation_job, generation_semaphore_for_config, persist_generation_job,
)
from .job_commands import JobCommand, command
from .runtime_environment import app_environment

logger = logging.getLogger("canary.cold_open")

GRANTS_FILE = ".cold_open_grants.json"


def per_account_limit() -> int | None:
    """Operator control; 0 turns the Cold Open off, None means no account limit.

    Unset, production grants one per account and every other environment is
    unlimited, so local and staging projects always get their first pages.
    """
    raw = os.getenv("CANARY_COLD_OPEN_PER_ACCOUNT", "").strip()
    if not raw:
        return 1 if app_environment() == "production" else None
    try:
        return max(0, int(raw))
    except ValueError:
        return 1


def claim_grant(account_dir: Path, project_id: str) -> bool:
    """Spend one of the account's Cold Opens on this project, once.

    Deleting the project does not return the grant: the marker is account-level.
    """
    limit = per_account_limit()
    if limit is None:
        return True
    if limit == 0:
        return False
    path = account_dir / GRANTS_FILE
    with production_lock(account_dir):
        try:
            projects = list(json.loads(path.read_text()).get("projects", []))
        except (OSError, ValueError, AttributeError):
            projects = []
        if project_id in projects:
            return True
        if len(projects) >= limit:
            return False
        path.write_text(json.dumps({"projects": [*projects, project_id]}))
        return True


def start_cold_open(app, *, user_id: str, project_id: str | None, part_dir: Path, config: Config):
    """Admit the Cold Open once the first part's opening snapshot exists.

    Returns the job, or None when this project does not get one. Never raises:
    the Cold Open must not disturb the Extract run that announced it.
    """
    try:
        root = series_root(part_dir)
        if (
            project_id is None or part_id_for_path(part_dir) != FIRST_PART_ID
            or not TargetArtifacts(part_dir).opening_snapshot_path.exists()
            # One per project, ever: a re-extraction keeps the first pages.
            or cold_open.record_path(root).exists()
            # Style already has proofs of its own; the opening adds nothing.
            or cold_open.style_has_suggestions(root)
        ):
            return None
        pkey = project_key(user_id, project_id)
        if find_active_generation_job(app, pkey, "cold_open") is not None:
            return None
        if not claim_grant(root.parent, project_id):
            return None
        snapshot = TargetArtifacts(part_dir).read_opening_snapshot()
        cold_open.begin_record(root, FIRST_PART_ID, snapshot.bible)
        spec = command("cold_open", root, config, part_dir=str(part_dir.resolve()))
        spec = JobCommand.model_validate({
            **spec.model_dump(), "stage": "style", "user_id": user_id, "project_id": project_id,
            "sponsor": cold_open.SPONSOR, "reservation_credits": 0, "ledger_job_id": str(uuid.uuid4()),
            "debit_description": "Cold Open (paid by Canary)",
        })
        return enqueue_generation_job(
            app, project_name=pkey, kind="cold_open", label="Cold Open", payload={}, runner=None,
            user_id=user_id, command=spec, semaphore=generation_semaphore_for_config(app, config),
        )
    except Exception:
        logger.exception("Cold Open admission failed project=%s", project_id)
        return None


def _mutate(root: Path, change) -> ColdOpenRecord:
    # The favorite route writes the same record; never save a stale copy.
    with production_lock(root):
        record = cold_open.read_record(root)
        if record is None:
            raise ArtifactMissing("cold_open", cold_open.record_path(root))
        change(record)
        cold_open.write_record(root, record)
        return record


async def execute_cold_open(app, job, root: Path, config: Config) -> None:
    from novel_to_comic.stages import s2_style as style
    from novel_to_comic.style_briefing import style_sample_selection
    from novel_to_comic.usage import calculate_cost_breakdown

    spec = job.command
    part_dir = Path(spec.arguments["part_dir"])
    if spec.sponsor != cold_open.SPONSOR:
        raise ValueError("The Cold Open runs only as Canary-paid work")
    if part_dir.parent.parent != root or not is_part_workspace(part_dir):
        raise ValueError("Cold Open part is outside its project")
    snapshot = TargetArtifacts(part_dir).read_opening_snapshot()
    bible = snapshot.bible
    seen: set[str] = set()

    def record_usage(usage) -> None:
        if usage.call_id in seen:
            return
        seen.add(usage.call_id)
        cost = calculate_cost_breakdown(usage)
        known = cost.cost_usd is not None and cost.source != "unknown_provider_usage"

        def add(record):
            if known:
                record.provider_cost_usd = round(record.provider_cost_usd + cost.cost_usd, 6)
            else:
                record.unknown_cost_calls += 1
        _mutate(root, add)

    def set_phase(phase: str) -> None:
        job.payload["phase"] = phase
        persist_generation_job(app, job)

    try:
        set_phase("reading")
        passage = cold_open.opening_passage(snapshot, style_sample_selection(bible).scene)
        # The ranking and the shared proof brief are independent: author both at once.
        with style.style_text_usage(record_usage):
            order, brief = await asyncio.gather(
                cold_open.rank_looks(config, bible, record_usage),
                style.ensure_style_sample_brief(config, bible, root, passage=passage),
            )
        looks = cold_open.choose_looks(bible, order=order)
        copy = style.style_proof_copy(config, bible, root)

        def planned(record):
            cold_open.set_looks(record, looks, order is not None)
            record.proof_copy = None if copy == LABEL_COPY else copy.model_dump()
        _mutate(root, planned)
        set_phase("printing")
        semaphore = asyncio.Semaphore(config.effective_image_concurrency())

        def set_look(look_id: str, **fields) -> None:
            def change(record):
                entry = next(item for item in record.looks if item.id == look_id)
                for key, value in fields.items():
                    setattr(entry, key, value)
            _mutate(root, change)

        async def print_look(look: cold_open.HouseLook) -> None:
            async with semaphore:
                set_look(look.id, status="printing")
                try:
                    result = await style.generate_sample_image(
                        config.model_copy(update={"style_template": style_template_for_suggestion(look.suggestion)}),
                        bible, cold_open.proof_path(root, look.id), brief=brief, candidate_id=look.id,
                        project_dir=root, style_reference_mode=look.suggestion["style_reference_mode"],
                    )
                except Exception as error:
                    for usage in getattr(error, "usage_records", ()):
                        record_usage(usage)
                    # One proof failing never discards its siblings, and nothing
                    # retries a paid submission here.
                    logger.warning("Cold Open proof failed look=%s", look.id, exc_info=True)
                    set_look(look.id, status="failed", error="This one didn't make it off the press.")
                    return
                for usage in ((result.usage,) if result.usage else ()) + tuple(result.additional_usage):
                    record_usage(usage)
                set_look(look.id, status="ready")

        await asyncio.gather(*(print_look(look) for look in looks))
    except BaseException:
        _mutate(root, _finish)
        raise
    record = _mutate(root, _finish)
    from .product_events import capture_server_event

    capture_server_event("cold_open_printed", user_id=spec.user_id, project_id=spec.project_id, properties={
        "pages": sum(entry.status == "ready" for entry in record.looks), "ranking": record.ranking,
        "story_copy": record.proof_copy is not None,
        "latency_ms": int((datetime.fromisoformat(record.finished_at) - datetime.fromisoformat(record.started_at))
                          .total_seconds() * 1000) if record.finished_at else None,
    })
    if record.status == "failed":
        raise RuntimeError("No Cold Open page was printed")


def _finish(record: ColdOpenRecord) -> None:
    for entry in record.looks:
        if entry.status in {"queued", "printing"}:
            entry.status, entry.error = "failed", "This one didn't make it off the press."
    record.status = "ready" if any(entry.status == "ready" for entry in record.looks) else "failed"
    record.finished_at = cold_open.now()
