"""Local-first diagnostic records for development debugging.

The journal does not capture request bodies or images. Exception text can still
contain source content or paths; enable it only for trusted local development
and inspect records before sharing them.
"""

from __future__ import annotations
import datetime
import json
import os
import traceback
from pathlib import Path
from typing import Any

_MAX_MESSAGE = 2_000
_MAX_TRACEBACK = 12_000


def local_diagnostics_enabled() -> bool:
    """Return whether developer diagnostics are explicitly enabled outside production."""
    env = (os.environ.get("CANARY_ENV") or os.environ.get("ENV") or "dev").strip().lower()
    raw = os.environ.get("CANARY_LOCAL_DIAGNOSTICS", "")
    return env != "production" and raw.strip().lower() in {"1", "true", "yes", "on"}


def _bounded(value: object, limit: int) -> str:
    return " ".join(str(value).split())[:limit]


def _traceback_text(error: BaseException | None) -> str | None:
    if error is None:
        return None
    return "".join(traceback.format_exception(error))[-_MAX_TRACEBACK:]


def record_diagnostic(
    project_dir: Path,
    event: str,
    *,
    stage: str | None = None,
    request_id: str | None = None,
    event_id: str | None = None,
    feature: str | None = None,
    model: str | None = None,
    status: str | None = None,
    message: str | None = None,
    error: BaseException | None = None,
    error_detail: str | None = None,
    extra: dict[str, Any] | None = None,
) -> Path | None:
    """Append one bounded diagnostic record to the opt-in local journal."""
    if not local_diagnostics_enabled():
        return None
    from novel_to_comic.ai.context import current_ai_request_context

    context = current_ai_request_context()
    record: dict[str, Any] = {
        "timestamp": datetime.datetime.now(datetime.UTC).isoformat(),
        "event": event,
    }
    for key, value in {
        "stage": stage or context.stage,
        "request_id": request_id or context.request_id,
        "project_id": context.project_id,
        "job_id": context.job_id,
        "event_id": event_id,
        "feature": feature,
        "model": model,
        "status": status,
    }.items():
        if value:
            record[key] = _bounded(value, 300)
    if message:
        record["message"] = _bounded(message, _MAX_MESSAGE)
    detail = error_detail or _traceback_text(error)
    if detail:
        record["traceback"] = detail[-_MAX_TRACEBACK:]
    if error is not None:
        record["error_type"] = type(error).__name__
    if extra:
        record["details"] = extra

    path = project_dir / ".canary" / "diagnostics.jsonl"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        fd = os.open(path, flags, 0o600)
        try:
            with os.fdopen(fd, "a", encoding="utf-8") as handle:
                fd = -1
                handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
        finally:
            if fd >= 0:
                os.close(fd)
    except Exception:
        # Diagnostics must never change the workflow outcome.
        return None
    return path
