"""Operator-only customer, pipeline, and credit observability endpoints."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from ..db import get_db
from ..deployment_status import require_ops_token
from ..generation_jobs import GenerationJob
from ..product_events import capture_server_event
from ..release import release_identity
from ..runtime_environment import stripe_environment_snapshot
from novel_to_comic.state import STAGE_NAMES, StageStatus, is_stale, load_state
from novel_to_comic.model_catalog import STAGE_FIELDS as MODEL_STAGE_FIELDS, STAGE_LABELS as MODEL_STAGE_LABELS, STAGE_DESCRIPTIONS as MODEL_STAGE_DESCRIPTIONS, allowed_models, models
from ..account_models import read_global_reasoning, read_global_effort, read_global_selections, update_global_selections

from novel_to_comic.text_models import reasoning_options

router = APIRouter(dependencies=[Depends(require_ops_token)])
logger = logging.getLogger("canary.backoffice")

MAX_USER_PAGES = 10
USERS_PER_PAGE = 100
MAX_ERRORS_PER_USER = 20

STAGE_LABELS = {
    "extract": "Story review",
    "brief": "Story review",
    "style": "Choosing a look",
    "cast": "Casting references",
    "adapt": "Adapting scenes",
    "plan": "Planning pages",
    "draw": "Drawing pages",
    "finish": "Preparing export",
}


class GrantCreditsRequest(BaseModel):
    amount_credits: int = Field(gt=0, le=1_000_000)
    reason: str = Field(min_length=3, max_length=500)
    operator: str = Field(min_length=2, max_length=120)
    idempotency_key: str = Field(
        min_length=8,
        max_length=120,
        pattern=r"^[A-Za-z0-9:_-]+$",
    )


class OperatorModelSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selections: dict[str, str] = Field(default_factory=dict)
    text_reasoning_effort: str | None = None
    reasoning_efforts: dict[str, str] = Field(default_factory=dict)


def _rows(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None) or []
    return [row for row in data if isinstance(row, dict)]


def _value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    text = str(value).strip()
    return text or None


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _relative_time(value: Any) -> str:
    parsed = _datetime(value)
    if parsed is None:
        return "Never"
    seconds = max(0, (datetime.now(timezone.utc) - parsed).total_seconds())
    if seconds < 60:
        return "Just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hr ago"
    if seconds < 172800:
        return "Yesterday"
    if seconds < 604800:
        return f"{int(seconds // 86400)} days ago"
    return f"{parsed:%b} {parsed.day}"


def _date_label(value: Any) -> str:
    parsed = _datetime(value)
    return f"{parsed:%b} {parsed.day}, {parsed.year}" if parsed else "Unknown"


def _truncate(value: Any, limit: int = 420) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _display_name(user: Any) -> str:
    metadata = _value(user, "user_metadata", {}) or {}
    for key in ("full_name", "display_name", "name"):
        candidate = metadata.get(key) if isinstance(metadata, dict) else None
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()[:120]
    email = _value(user, "email")
    if isinstance(email, str) and email.strip():
        return email.split("@", 1)[0].replace(".", " ").replace("_", " ").title()
    return "Anonymous user"


def _initials(name: str) -> str:
    parts = [part for part in name.split() if part]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    return (name[:2] or "??").upper()


def _avatar_tone(user_id: str) -> str:
    tones = ("red", "gold", "blue", "sage", "ink")
    return tones[sum(ord(char) for char in user_id) % len(tones)]


def _is_banned(user: Any) -> bool:
    banned_until = _value(user, "banned_until")
    if not banned_until or str(banned_until).lower() in {"none", "null", "false"}:
        return False
    until = _datetime(banned_until)
    return until is None or until > datetime.now(timezone.utc)


def _load_admin_users(db: Any) -> list[Any]:
    users: list[Any] = []
    for page in range(1, MAX_USER_PAGES + 1):
        page_users = db.auth.admin.list_users(page=page, per_page=USERS_PER_PAGE)
        if not page_users:
            break
        users.extend(page_users)
        if len(page_users) < USERS_PER_PAGE:
            break
    return users


def _query_user_rows(
    db: Any,
    table: str,
    columns: str,
    user_ids: list[str],
    *,
    limit: int = 5000,
    order_column: str | None = None,
) -> list[dict[str, Any]]:
    if not user_ids:
        return []
    query = db.table(table).select(columns).in_("user_id", user_ids)
    if order_column:
        query = query.order(order_column, desc=True)
    return _rows(query.limit(limit).execute())


def _query_events(db: Any, user_ids: list[str]) -> list[dict[str, Any]]:
    if not user_ids:
        return []
    query = (
        db.table("product_events")
        .select("event_name,user_id,project_id,occurred_at,properties_json")
        .in_("user_id", user_ids)
        .order("occurred_at", desc=True)
    )
    try:
        return _rows(query.limit(5000).execute())
    except Exception:  # noqa: BLE001 - product events are optional observability
        logger.warning(
            "Could not load product events for the operator snapshot",
            exc_info=True,
        )
        return []


def _project_state(project_dir: Path) -> Any | None:
    try:
        return load_state(project_dir)
    except Exception:  # noqa: BLE001 - incompatible projects stay visible
        return None


def _job_project_id(job: GenerationJob, user_id: str) -> str | None:
    prefix = f"{user_id}:"
    if job.project_name.startswith(prefix):
        return job.project_name[len(prefix) :]
    return None


def _project_snapshot(
    app: Any,
    row: dict[str, Any],
    *,
    jobs: list[GenerationJob],
) -> dict[str, Any]:
    user_id = str(row.get("user_id") or "")
    project_id = str(row.get("id") or "")
    slug = str(row.get("name") or project_id)
    project_dir = Path(app.state.projects_dir) / user_id / slug
    state = _project_state(project_dir)
    pkey = f"{user_id}:{project_id}"
    related_jobs = [job for job in jobs if job.project_name == pkey]
    active_jobs = [job for job in related_jobs if job.status in {"queued", "running"}]
    pipeline_task = getattr(app.state, "running_tasks", {}).get(pkey)
    style_task = getattr(app.state, "style_tasks", {}).get(pkey)
    live_task = any(
        task is not None and not task.done() for task in (pipeline_task, style_task)
    )

    errors: list[dict[str, Any]] = []
    stages: list[dict[str, Any]] = []
    current_stage = "No active project"
    project_status = "idle"
    project_name = slug
    if state is not None:
        project_name = state.project_name
        for name in STAGE_NAMES:
            stage = state.stages[name]
            status = stage.status.value
            stages.append(
                {
                    "stage": name,
                    "label": STAGE_LABELS.get(name, name.title()),
                    "status": status,
                    "items_done": stage.items_done,
                    "items_total": stage.items_total,
                    "started_at": _iso(stage.started_at),
                    "finished_at": _iso(stage.finished_at),
                }
            )
            occurred_at = stage.finished_at or stage.last_progress_at or stage.started_at
            if stage.error:
                errors.append(
                    {
                        "source": "pipeline",
                        "stage": name,
                        "project_id": project_id,
                        "project_name": project_name,
                        "status": "failed",
                        "message": _truncate(stage.error),
                        "occurred_at": _iso(occurred_at),
                    }
                )
            elif stage.items_failed:
                errors.append(
                    {
                        "source": "pipeline",
                        "stage": name,
                        "project_id": project_id,
                        "project_name": project_name,
                        "status": "failed",
                        "message": f"{len(stage.items_failed)} item(s) need attention.",
                        "occurred_at": _iso(occurred_at),
                    }
                )

        running = next(
            (
                name
                for name in STAGE_NAMES
                if state.stages[name].status == StageStatus.RUNNING
            ),
            None,
        )
        failed = next(
            (
                name
                for name in STAGE_NAMES
                if state.stages[name].status == StageStatus.FAILED
            ),
            None,
        )
        review = next(
            (
                name
                for name in STAGE_NAMES
                if state.stages[name].status == StageStatus.AWAITING_REVIEW
            ),
            None,
        )
        furthest = next(
            (
                name
                for name in reversed(STAGE_NAMES)
                if state.stages[name].status
                in {StageStatus.COMPLETE, StageStatus.AWAITING_REVIEW}
            ),
            None,
        )
        if running:
            current_stage = STAGE_LABELS.get(running, running.title())
            project_status = "running"
        elif active_jobs:
            current_stage = active_jobs[-1].label
            project_status = "running"
        elif failed:
            current_stage = f"Error in {STAGE_LABELS.get(failed, failed.title())}"
            project_status = "error"
        elif review:
            current_stage = f"Reviewing {STAGE_LABELS.get(review, review.title())}"
            project_status = "review"
        elif furthest and furthest != STAGE_NAMES[-1]:
            next_index = STAGE_NAMES.index(furthest) + 1
            current_stage = STAGE_LABELS.get(STAGE_NAMES[next_index], "Next stage")
            project_status = "ready"
        elif furthest == STAGE_NAMES[-1]:
            current_stage = "Ready to export"
            project_status = "complete"
        elif live_task:
            current_stage = "Pipeline is starting"
            project_status = "running"

        if (
            any(
                state.stages[name].status == StageStatus.RUNNING
                and is_stale(state.stages[name])
                for name in STAGE_NAMES
            )
            and not live_task
            and not active_jobs
        ):
            project_status = "stalled"
            errors.append(
                {
                    "source": "pipeline",
                    "stage": current_stage,
                    "project_id": project_id,
                    "project_name": project_name,
                    "status": "stalled",
                    "message": "The saved pipeline heartbeat is stale and no live job is attached.",
                    "occurred_at": _iso(datetime.now(timezone.utc)),
                }
            )

    job_payloads = [
        {
            "id": job.id,
            "kind": job.kind,
            "label": job.label,
            "status": job.status,
            "queued_at": _iso(job.queued_at),
            "started_at": _iso(job.started_at),
            "finished_at": _iso(job.finished_at),
            "error": _truncate(job.error) if job.error else None,
        }
        for job in sorted(
            related_jobs, key=lambda candidate: candidate.sequence, reverse=True
        )[:10]
    ]
    for job in related_jobs:
        if job.status == "failed" and job.error:
            errors.append(
                {
                    "source": "generation_job",
                    "stage": job.kind,
                    "project_id": project_id,
                    "project_name": project_name,
                    "status": "failed",
                    "message": _truncate(job.error),
                    "occurred_at": _iso(job.finished_at or job.started_at or job.queued_at),
                }
            )

    return {
        "id": project_id,
        "name": project_name,
        "slug": slug,
        "created_at": _iso(row.get("created_at")),
        "status": project_status,
        "is_active": project_status in {"running", "stalled"},
        "current_stage": current_stage,
        "stages": stages,
        "jobs": job_payloads,
        "errors": errors,
    }


def _usage_error(row: dict[str, Any]) -> dict[str, Any]:
    stage = str(row.get("stage") or row.get("feature") or "AI call")
    error_type = str(row.get("error_type") or "provider_error")
    message = row.get("error_message") or error_type
    return {
        "source": "ai_usage",
        "stage": stage,
        "project_id": row.get("project_id"),
        "project_name": row.get("project_name"),
        "status": row.get("status") or "failed",
        "message": _truncate(message),
        "error_type": error_type,
        "occurred_at": _iso(row.get("finished_at") or row.get("created_at")),
    }


def _event_label(row: dict[str, Any]) -> str:
    event_name = str(row.get("event_name") or "Activity").replace("_", " ").title()
    properties = row.get("properties_json") or {}
    if isinstance(properties, dict) and properties.get("stage"):
        return f"{event_name} · {properties['stage']}"
    return event_name


def _balance(ledger_rows: list[dict[str, Any]]) -> int:
    return sum(
        int(row.get("amount_credits") or 0)
        for row in ledger_rows
        if row.get("status") != "released"
    )


def _flatten(groups: Any) -> list[Any]:
    return [item for group in groups for item in group]


def _make_user(
    user: Any,
    *,
    project_rows: list[dict[str, Any]],
    ledger_rows: list[dict[str, Any]],
    usage_rows: list[dict[str, Any]],
    events: list[dict[str, Any]],
    jobs: list[GenerationJob],
    app: Any,
) -> dict[str, Any]:
    user_id = str(_value(user, "id"))
    name = _display_name(user)
    user_projects = [row for row in project_rows if str(row.get("user_id")) == user_id]
    project_snapshots = [
        _project_snapshot(app, row, jobs=jobs) for row in user_projects
    ]
    project_snapshots.sort(
        key=lambda project: _datetime(project.get("created_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    user_ledger = [row for row in ledger_rows if str(row.get("user_id")) == user_id]
    user_usage = [row for row in usage_rows if str(row.get("user_id")) == user_id]
    user_events = [row for row in events if str(row.get("user_id")) == user_id]
    errors = [
        *_flatten(project.get("errors", []) for project in project_snapshots),
        *[
            _usage_error(row)
            for row in user_usage
            if row.get("status") in {"failed", "refused", "cancelled"}
        ],
    ]
    for job in jobs:
        if job.user_id == user_id and job.status == "failed" and job.error:
            errors.append(
                {
                    "source": "generation_job",
                    "stage": job.kind,
                    "project_id": _job_project_id(job, user_id),
                    "project_name": job.label,
                    "status": "failed",
                    "message": _truncate(job.error),
                    "occurred_at": _iso(job.finished_at or job.started_at or job.queued_at),
                }
            )
    errors.sort(
        key=lambda item: _datetime(item.get("occurred_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    errors = errors[:MAX_ERRORS_PER_USER]

    active_projects = [project for project in project_snapshots if project["is_active"]]
    active_jobs = [
        job
        for job in jobs
        if job.user_id == user_id and job.status in {"queued", "running"}
    ]
    current_project = (
        active_projects[0]
        if active_projects
        else (project_snapshots[0] if project_snapshots else None)
    )
    latest_usage = user_usage[0] if user_usage else None
    latest_event = user_events[0] if user_events else None
    last_activity = (
        (latest_event or {}).get("occurred_at")
        if latest_event
        else (latest_usage or {}).get("finished_at")
        or (latest_usage or {}).get("created_at")
    )
    if latest_event:
        last_event = _event_label(latest_event)
    elif latest_usage:
        stage = latest_usage.get("stage") or latest_usage.get("feature") or "AI call"
        last_event = f"{str(latest_usage.get('status') or 'updated').title()} · {stage}"
    elif current_project:
        last_event = f"{current_project['current_stage']} · {current_project['name']}"
    else:
        last_event = "No activity recorded"

    metadata = _value(user, "user_metadata", {}) or {}
    location = metadata.get("location") if isinstance(metadata, dict) else None
    timezone_name = metadata.get("timezone") if isinstance(metadata, dict) else None
    status = "suspended" if _is_banned(user) else "active"
    if not _value(user, "email_confirmed_at") and not _value(user, "phone_confirmed_at"):
        status = "unconfirmed"
    tags: list[str] = []
    if active_projects or active_jobs:
        tags.append("active work")
    if errors:
        tags.append("errors")
    if not tags:
        tags.append("no current work")

    return {
        "id": user_id,
        "name": name,
        "email": _value(user, "email") or "No email address",
        "initials": _initials(name),
        "avatar_tone": _avatar_tone(user_id),
        "plan": "Customer",
        "status": status,
        "projects": len(user_projects),
        "credits": _balance(user_ledger),
        "last_seen": _relative_time(_value(user, "last_sign_in_at")),
        "last_seen_at": _iso(_value(user, "last_sign_in_at")),
        "joined": _date_label(_value(user, "created_at")),
        "joined_at": _iso(_value(user, "created_at")),
        "current_stage": (
            current_project["current_stage"] if current_project else "No active project"
        ),
        "active_project": current_project,
        "active_jobs": [
            {
                "id": job.id,
                "label": job.label,
                "kind": job.kind,
                "status": job.status,
                "project_id": _job_project_id(job, user_id),
                "queued_at": _iso(job.queued_at),
                "started_at": _iso(job.started_at),
            }
            for job in active_jobs
        ],
        "errors": errors,
        "error_count": len(errors),
        "last_error": errors[0] if errors else None,
        "last_event": last_event,
        "last_event_at": _iso(last_activity),
        "spend": round(
            sum(
                float(row.get("gross_amount_cents") or 0) / 100
                for row in user_ledger
                if int(row.get("amount_credits") or 0) > 0
                and row.get("status") == "settled"
            ),
            2,
        ),
        "location": location or "—",
        "timezone": timezone_name or "—",
        "tags": tags,
        "projects_detail": project_snapshots,
        "auth": {
            "confirmed": bool(
                _value(user, "email_confirmed_at")
                or _value(user, "phone_confirmed_at")
            ),
            "anonymous": bool(_value(user, "is_anonymous")),
            "sso": bool(_value(user, "is_sso_user")),
        },
        "source": "live",
    }


def _load_snapshot(request: Request) -> dict[str, Any]:
    db = get_db()
    try:
        auth_users = _load_admin_users(db)
        user_ids = [str(_value(user, "id")) for user in auth_users]
        project_rows = _query_user_rows(
            db,
            "projects",
            "id,user_id,name,created_at",
            user_ids,
            order_column="created_at",
        )
        ledger_rows = _query_user_rows(
            db,
            "credit_ledger",
            "user_id,amount_credits,status,created_at,gross_amount_cents,cost_usd,operation,description",
            user_ids,
            order_column="created_at",
        )
        usage_rows = _query_user_rows(
            db,
            "ai_usage_events",
            "id,user_id,project_id,project_name,stage,feature,status,created_at,finished_at,error_type,error_message,model_alias,provider,provider_model,cost_usd",
            user_ids,
            order_column="created_at",
        )
        events = _query_events(db, user_ids)
    except Exception as exc:  # noqa: BLE001 - operator gets a safe dependency error
        logger.exception("Could not load operator snapshot")
        raise HTTPException(
            503,
            "Operator data is unavailable. Check Supabase service credentials and schema.",
        ) from exc

    jobs = list(getattr(request.app.state, "generation_jobs", {}).values())
    users = [
        _make_user(
            user,
            project_rows=project_rows,
            ledger_rows=ledger_rows,
            usage_rows=usage_rows,
            events=events,
            jobs=jobs,
            app=request.app,
        )
        for user in auth_users
    ]
    users.sort(
        key=lambda user: _datetime(user.get("last_seen_at"))
        or _datetime(user.get("joined_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )

    recent_errors = _flatten(user.get("errors", []) for user in users)
    recent_errors.sort(
        key=lambda item: _datetime(item.get("occurred_at"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    now = datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)
    day_7_ago = now - timedelta(days=7)
    active_users = sum(
        1
        for user in auth_users
        if (
            _datetime(_value(user, "last_sign_in_at"))
            or datetime.min.replace(tzinfo=timezone.utc)
        )
        >= month_ago
    )
    active_users_7d = sum(
        1
        for user in auth_users
        if (
            _datetime(_value(user, "last_sign_in_at"))
            or datetime.min.replace(tzinfo=timezone.utc)
        )
        >= day_7_ago
    )
    recent_projects = [
        row
        for row in project_rows
        if (_datetime(row.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
        >= day_7_ago
    ]
    recent_usage = [
        row
        for row in usage_rows
        if (_datetime(row.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc))
        >= day_7_ago
    ]
    recent_events = [
        row
        for row in events
        if (_datetime(row.get("occurred_at")) or datetime.min.replace(tzinfo=timezone.utc))
        >= day_7_ago
    ]
    model_stats: dict[str, dict[str, Any]] = {}
    for row in recent_usage:
        model = str(row.get("provider_model") or row.get("model_alias") or "unknown")
        stat = model_stats.setdefault(
            model,
            {"model": model, "alias": row.get("model_alias") or model, "calls": 0, "spend": 0.0},
        )
        stat["calls"] += 1
        stat["spend"] += float(row.get("cost_usd") or 0)
    model_spend = sorted(model_stats.values(), key=lambda row: row["spend"], reverse=True)
    total_model_spend = sum(row["spend"] for row in model_spend)
    for row in model_spend:
        row["spend"] = round(row["spend"], 2)
        row["share"] = round((row["spend"] / total_model_spend) * 100) if total_model_spend else 0
    recent_ledger = [
        row
        for row in ledger_rows
        if (
            _datetime(row.get("created_at"))
            or datetime.min.replace(tzinfo=timezone.utc)
        )
        >= week_ago
    ]
    active_projects = _flatten(
        [project for project in user.get("projects_detail", []) if project["is_active"]]
        for user in users
    )
    active_jobs = [
        job for job in jobs if job.status in {"queued", "running"}
    ]
    event_activity = [
        {
            "id": f"event-{index}",
            "tone": (
                "red"
                if str(row.get("event_name", "")).endswith("failed")
                else "blue"
            ),
            "title": _event_label(row),
            "detail": next(
                (
                    user["name"]
                    for user in users
                    if user["id"] == str(row.get("user_id"))
                ),
                "Unknown user",
            ),
            "occurred_at": _iso(row.get("occurred_at")),
        }
        for index, row in enumerate(events[:20])
    ]

    return {
        "environment": {**stripe_environment_snapshot(), **release_identity()},
        "users": users,
        "overview": {
            "user_count": len(users),
            "active_users_30d": active_users,
            "active_users_7d": active_users_7d,
            "project_count": len(project_rows),
            "projects_created_7d": len(recent_projects),
            "projects_in_motion": len(active_projects),
            "running_jobs": sum(1 for job in active_jobs if job.status == "running"),
            "queued_jobs": sum(1 for job in active_jobs if job.status == "queued"),
            "users_with_errors": sum(1 for user in users if user["error_count"]),
            "errors_24h": sum(
                1
                for error in recent_errors
                if (
                    _datetime(error.get("occurred_at"))
                    or datetime.min.replace(tzinfo=timezone.utc)
                )
                >= now - timedelta(days=1)
            ),
            "ai_calls_7d": len(recent_usage),
            "failed_ai_calls_7d": sum(
                1 for row in recent_usage if row.get("status") in {"failed", "refused", "cancelled"}
            ),
            "exports_7d": sum(1 for row in recent_events if row.get("event_name") == "export_succeeded"),
            "credits_granted_7d": sum(
                int(row.get("amount_credits") or 0)
                for row in recent_ledger
                if int(row.get("amount_credits") or 0) > 0
                and row.get("status") == "settled"
            ),
            "credits_used_7d": sum(
                abs(int(row.get("amount_credits") or 0))
                for row in recent_ledger
                if int(row.get("amount_credits") or 0) < 0
                and row.get("status") == "settled"
            ),
            "provider_cost_usd_7d": round(
                sum(float(row.get("cost_usd") or 0) for row in recent_ledger), 2
            ),
        },
        "recent_errors": recent_errors[:30],
        "projects_in_motion": active_projects[:30],
        "activity": event_activity,
        "model_spend": model_spend[:12],
        "data_as_of": now.isoformat(),
    }


@router.get("/")
def backoffice_snapshot(request: Request):
    """Return the live operator snapshot; never return seeded customer data."""
    return _load_snapshot(request)


def _operator_model_payload(selections: dict[str, str], effort: str, reasoning: dict[str, str]) -> dict[str, Any]:
    return {
        "selections": selections,
        "text_reasoning_effort": effort,
        "reasoning_efforts": reasoning,
        "reasoning_options": {model["id"]: list(reasoning_options(model["id"]))
                              for model in models(include_codex=False) if model["kind"] == "text"},
        "text_reasoning_effort_options": ["low", "medium", "high"],
        "models": models(include_codex=False),
        "stages": [
            {"id": stage, "label": MODEL_STAGE_LABELS[stage],
             "description": MODEL_STAGE_DESCRIPTIONS[stage],
             "model_ids": list(allowed_models(stage, include_codex=False))}
            for stage in MODEL_STAGE_FIELDS
        ],
        "note": "Applies to new jobs in every account and project. Running jobs and existing Draw editions retain their recorded models.",
    }


@router.get("/models")
def operator_model_settings(request: Request):
    try:
        return _operator_model_payload(read_global_selections(request.app.state.projects_dir),
                                       read_global_effort(request.app.state.projects_dir),
                                       read_global_reasoning(request.app.state.projects_dir, read_global_selections(request.app.state.projects_dir)))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.patch("/models")
def patch_operator_model_settings(body: OperatorModelSettingsPatch, request: Request):
    try:
        selections = update_global_selections(request.app.state.projects_dir, body.selections, body.text_reasoning_effort, body.reasoning_efforts)
        return _operator_model_payload(selections, read_global_effort(request.app.state.projects_dir),
                                       read_global_reasoning(request.app.state.projects_dir, selections))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


def _grant_row(
    *,
    user_id: str,
    body: GrantCreditsRequest,
    marker: str,
) -> dict[str, Any]:
    return {
        "user_id": user_id,
        "amount_credits": body.amount_credits,
        "status": "settled",
        "description": f"Manual operator grant by {body.operator}: {body.reason}",
        "provider": "operator",
        "operation": "operator_grant",
        "usage_call_id": marker,
        "cost_usd": 0,
        "cost_source": "operator",
    }


def _matching_grant(
    existing: dict[str, Any],
    user_id: str,
    body: GrantCreditsRequest,
) -> bool:
    return (
        str(existing.get("user_id")) == user_id
        and int(existing.get("amount_credits") or 0) == body.amount_credits
        and existing.get("operation") == "operator_grant"
    )


@router.post("/users/{user_id}/credits")
def grant_credits(user_id: str, body: GrantCreditsRequest):
    """Add an audited, idempotent manual credit grant to one customer's ledger."""
    db = get_db()
    marker = f"operator-grant:{body.idempotency_key}"
    ledger = db.table("credit_ledger")
    existing_rows = _rows(
        ledger.select(
            "id,user_id,amount_credits,status,operation,created_at"
        ).eq("usage_call_id", marker).limit(1).execute()
    )
    if existing_rows:
        existing = existing_rows[0]
        if not _matching_grant(existing, user_id, body):
            raise HTTPException(409, "This idempotency key belongs to another credit grant.")
        return {
            "status": "granted",
            "id": existing.get("id"),
            "user_id": user_id,
            "amount_credits": existing.get("amount_credits"),
            "idempotent": True,
            "environment": stripe_environment_snapshot(),
            "stripe_charge": False,
        }

    try:
        inserted = _rows(
            ledger.insert(
                _grant_row(user_id=user_id, body=body, marker=marker)
            ).execute()
        )
    except Exception as exc:  # noqa: BLE001 - recover a concurrent idempotent retry
        concurrent = _rows(
            ledger.select(
                "id,user_id,amount_credits,status,operation,created_at"
            ).eq("usage_call_id", marker).limit(1).execute()
        )
        if concurrent and _matching_grant(concurrent[0], user_id, body):
            return {
                "status": "granted",
                "id": concurrent[0].get("id"),
                "user_id": user_id,
                "amount_credits": concurrent[0].get("amount_credits"),
                "idempotent": True,
                "environment": stripe_environment_snapshot(),
                "stripe_charge": False,
            }
        logger.exception("Operator credit grant failed for user %s", user_id)
        raise HTTPException(503, "Could not persist the credit grant.") from exc

    if not inserted:
        raise HTTPException(503, "Credit grant was not persisted.")
    row = inserted[0]
    environment = stripe_environment_snapshot()
    capture_server_event(
        "operator_credit_granted",
        user_id=user_id,
        properties={
            "amount_credits": body.amount_credits,
            "app_environment": environment.get("app_environment", "unknown"),
            "stripe_mode": environment.get("stripe_mode", "unknown"),
        },
    )
    return {
        "status": "granted",
        "id": row.get("id"),
        "user_id": user_id,
        "amount_credits": body.amount_credits,
        "idempotent": False,
        "environment": environment,
        "stripe_charge": False,
    }


class FeedbackStatusPatch(BaseModel):
    status: str = Field(pattern=r"^(new|reviewed|planned|resolved)$")


@router.get("/feedback")
def list_feedback():
    return {"items": _rows(get_db().table("customer_feedback").select("*").order("created_at", desc=True).limit(200).execute())}


@router.patch("/feedback/{user_id}/{feedback_id}")
def update_feedback(user_id: str, feedback_id: str, body: FeedbackStatusPatch):
    rows = _rows(get_db().table("customer_feedback").update({"status": body.status}).eq("user_id", user_id).eq("id", feedback_id).execute())
    if not rows:
        raise HTTPException(404, "Feedback not found")
    return rows[0]
