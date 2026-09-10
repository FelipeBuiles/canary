"""Read-only operational evidence; never dispatches, settles, or releases work.

Only allowlisted metadata leaves this boundary. Raw journal bodies, model errors,
project names, source text and provider responses are deliberately not returned.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .release import release_identity

RUNBOOK = "/docs/ops/crash-recovery.md"
SAFE_ACTION = "Preserve saved output and holds. Inspect this work's journal, Draw recovery evidence and ledger; reconcile the original call before any customer-authorized retry."


def _seconds(name: str, default: int) -> int:
    return max(1, int(os.environ.get(name, str(default))))


def _age(value, now: datetime) -> float:
    if not value:
        return 0
    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return max(0, (now - stamp.replace(tzinfo=stamp.tzinfo or timezone.utc)).total_seconds())


def _opaque(*parts) -> str:
    return hashlib.sha256("\0".join(str(p) for p in parts).encode()).hexdigest()[:24]


def exception_snapshot(app, *, db=None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    root = Path(app.state.projects_dir)
    observations = []
    complete = True
    stale = _seconds("CANARY_OPS_STALL_SECONDS", 1800)
    repeated = _seconds("CANARY_OPS_FAILURE_COUNT", 3)
    failure_window = _seconds("CANARY_OPS_FAILURE_WINDOW_SECONDS", 3600)

    def add(kind, identity, *, severity="warning", action=SAFE_ACTION, **fields):
        if fields.get("job_id") or fields.get("action_id"):
            fields.setdefault("credit_state", "inspect_ledger")
        # Production project IDs are UUIDs. A malformed URL or legacy job can
        # instead contain a user-chosen title; use an opaque locator for those.
        if fields.get("project_id"):
            try:
                uuid.UUID(fields["project_id"])
            except (ValueError, TypeError, AttributeError):
                fields["project_id"] = _opaque(fields["project_id"])
        observations.append(dict(key=f"{kind}:{identity}", kind=kind, severity=severity,
                                 safe_action=action, diagnostic_url="/api/ops/exceptions", **fields))

    def unavailable(source):
        nonlocal complete
        complete = False
        add("evidence_unavailable", source, severity="critical",
            evidence={"reason_code": source},
            action="Restore access to this evidence source. Keep existing incidents and holds open; do not infer success from missing evidence.")

    try:
        disk = shutil.disk_usage(root)
        percent = 100 * disk.used / disk.total
        if percent >= _seconds("CANARY_OPS_STORAGE_PERCENT", 85) or disk.free < _seconds("CANARY_OPS_STORAGE_FREE_BYTES", 2 * 1024**3):
            add("storage_pressure", "projects", severity="critical" if percent >= 95 else "warning",
                evidence={"free_bytes": disk.free, "total_bytes": disk.total, "used_percent": round(percent)},
                action="Drain admission; expand or safely archive backed-up storage. Never delete journals, unresolved renders or billing evidence.")
    except OSError:
        unavailable("storage")

    try:
        with app.state.admission.journal() as journal:
            requests = journal.execute("SELECT account,route,key FROM requests WHERE status IS NULL").fetchall()
            has_jobs = journal.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'").fetchone()
            rows = journal.execute("SELECT id,project,payload FROM jobs").fetchall() if has_jobs else []
        # Only requests whose project has no live mutation can be indeterminate.
        from .admission import project_busy
        for account, route, key in requests:
            project = route.split("/api/projects/", 1)[-1].split("/", 1)[0]
            pkey = f"{account}:{project}"
            lock = app.state.admission.locks.get(pkey)
            if not (lock and lock.locked()) and not project_busy(app, pkey):
                add("indeterminate_action", _opaque(account, route, key), action_id=_opaque(account, route, key),
                    project_id=project, evidence={"state": "response_not_recorded"})
        failures = {}
        for job_id, project, raw in rows:
            payload = json.loads(raw)
            status = payload.get("status")
            live = app.state.generation_jobs.get(job_id)
            project_id = project.split(":", 1)[-1]
            if status in {"queued", "running"}:
                if live is None:
                    add("interrupted_job", job_id, job_id=job_id, project_id=project_id,
                        evidence={"state": status, "reason_code": "process_owner_lost"})
                elif _age(payload.get("started_at") or payload.get("queued_at"), now) >= stale:
                    add("stalled_job", job_id, job_id=job_id, project_id=project_id,
                        evidence={"state": status, "threshold": stale},
                        action="Inspect worker progress and provider timeout before cancelling. A long call is not proof of failure; preserve any ambiguous hold and output.")
            if payload.get("phase") == "ambiguous_submission":
                add("ambiguous_submission", job_id, severity="critical", job_id=job_id, project_id=project_id,
                    evidence={"state": "submission_unknown"})
            if status == "failed" and _age(payload.get("finished_at"), now) <= failure_window and payload.get("finished_at"):
                failures.setdefault(project_id, []).append(job_id)
        for project, jobs in failures.items():
            if len(jobs) >= repeated:
                add("repeated_failure", _opaque(project), project_id=project, job_id=jobs[-1],
                    evidence={"count": len(jobs), "threshold": repeated, "window_seconds": failure_window})
    except (OSError, ValueError, RuntimeError, sqlite3.Error):
        unavailable("journal")

    try:
        if db is None:
            from .db import get_db
            db = get_db()

        def records(table, columns, **filters):
            # Supabase's default page cap must not silently hide older evidence.
            offset = 0
            while True:
                query = db.table(table).select(columns).order("id")
                for name, value in filters.items():
                    query = query.eq(name, value)
                page = query.range(offset, offset + 499).execute().data or []
                yield from page
                if len(page) < 500:
                    break
                offset += 500

        from .credits import _unsettled_jobs
        for hold in records("credit_ledger", "id,project_id,job_id,reservation_started_at,reservation_expires_at", status="reserved"):
            expired = hold.get("reservation_expires_at") and _age(hold["reservation_expires_at"], now) > 0
            unsettled = hold.get("job_id") in _unsettled_jobs
            if unsettled or (hold.get("reservation_started_at") and expired):
                add("credit_reconciliation", hold["id"], severity="critical", job_id=hold.get("job_id"),
                    action_id=hold["id"], project_id=hold.get("project_id"), credit_state="reserved",
                    evidence={"hold_state": "started_expired" if expired else "held", "settlement_state": "unknown"})
        for call in records("ai_usage_events", "id,project_id,started_at", status="started"):
            if _age(call.get("started_at"), now) >= stale:
                add("ambiguous_provider_call", call["id"], severity="critical", action_id=call["id"],
                    project_id=call.get("project_id"), credit_state="inspect_ledger",
                    evidence={"state": "started_without_terminal_evidence", "threshold": stale})
        for call in records("ai_usage_events", "id,project_id", **{"error_json->>phase": "ambiguous_submission"}):
            add("ambiguous_provider_call", call["id"], severity="critical", action_id=call["id"],
                project_id=call.get("project_id"), credit_state="inspect_ledger",
                evidence={"state": "submission_unknown"})
        for project in records("projects", "id,user_id,name"):
            directory = root / project["user_id"] / project["name"]
            if not directory.resolve().is_relative_to(root.resolve()):
                unavailable("project_path")
                continue
            state_path = directory / "state.json"
            if not state_path.exists():
                continue
            state = json.loads(state_path.read_text())
            for stage, value in state.get("stages", {}).items():
                if stage not in {"extract", "brief", "style", "cast", "adapt", "plan", "draw", "finish"}:
                    continue
                if value.get("status") == "running" and _age(value.get("last_progress_at") or value.get("started_at"), now) >= stale:
                    add("stalled_stage", f"{project['id']}:{stage}", project_id=project["id"],
                        action_id=stage, evidence={"phase": stage, "threshold": stale, "last_progress_at": value.get("last_progress_at")})
            markers = (*directory.glob("draw/pages/page_*/provenance_*.pending"),
                       *directory.glob("draw/pages/page_*/provenance_*.unfinished"))
            for pending in markers:
                if project_busy(app, f"{project['user_id']}:{project['id']}"):
                    continue
                add("saved_output_recovery", _opaque(project["id"], pending.stem, pending.parent.name),
                    project_id=project["id"], action_id=f"{pending.parent.name}:{pending.stem}",
                    evidence={"saved_output": True, "settlement_state": "inspect_ledger"})
    except Exception:
        # Dependency failures are monitored, never used to release holds or restart.
        unavailable("database_or_artifacts")

    recovery = root / ".ops" / "recovery.json"
    if recovery.exists():
        try:
            value = json.loads(recovery.read_text())
            if value.get("budget_exhausted"):
                add("restart_budget_exhausted", "machine", severity="critical",
                    evidence={"reason_code": "restart_budget_exhausted"},
                    action="Keep admission closed. Follow crash-loop runbook; inspect release and sanitized exit evidence before explicitly resetting the restart budget.")
            if value.get("gateway_status") == "exhausted":
                add("gateway_recovery_exhausted", "litellm", severity="critical",
                    evidence={"reason_code": "gateway_recovery_exhausted"},
                    action="Inspect LiteLLM startup configuration and local readiness. Repair the dependency before a controlled restart; do not retry paid work.")
        except (ValueError, OSError):
            unavailable("restart_state")
    return {"release": release_identity()["git_sha"], "observations": observations,
            "complete": complete, "draining": app.state.admission.draining}
