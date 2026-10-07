"""Account ingestion budget and conservative reachability cleanup on the volume."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import shutil

from fastapi import HTTPException

from novel_to_comic.artifact_lock import production_lock
from novel_to_comic.workspace import series_root


def _bytes(directory: Path) -> int:
    total = 0
    for path in directory.rglob("*"):
        try:
            if path.is_file() and not path.is_symlink():
                total += path.stat().st_size
        except FileNotFoundError:
            # A derived file can be atomically replaced while usage is read.
            continue
    return total


def usage(account: Path) -> dict:
    used = _bytes(account)
    publications = account.parent / ".publications"
    for owner in (publications / "owners").glob("*.json"):
        record = json.loads(owner.read_text())
        if record.get("account") == account.name:
            used += _bytes(publications / record["id"])
    limit = int(os.getenv("CANARY_ACCOUNT_STORAGE_BYTES", str(5 * 1024**3)))
    if limit < 1:
        raise ValueError("CANARY_ACCOUNT_STORAGE_BYTES must be positive")
    return {
        "used_bytes": used,
        "limit_bytes": limit,
        "remaining_bytes": max(0, limit - used),
    }


def require_capacity(account: Path, additional: int, *, budget: dict | None = None):
    budget = usage(account) if budget is None else budget
    if additional < 0:
        raise ValueError("Additional storage cannot be negative")
    if budget["used_bytes"] + additional > budget["limit_bytes"]:
        raise HTTPException(
            413,
            {
                "code": "storage_budget_exceeded",
                "message": "Account storage is full. Delete projects you no longer need from their settings, then try again.",
                "admitted": False,
                **budget,
            },
        )


@contextmanager
def ingestion(project: Path, additional: int):
    """Account before series: serialize capacity checks across distinct projects."""
    account = series_root(project).parent
    with production_lock(account):
        budget = usage(account)
        require_capacity(account, additional, budget=budget)
        yield budget


def _strings(value):
    if isinstance(value, str):
        yield value
        if "/" in value and "\n" not in value:
            yield Path(value).name
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def housekeeping(app, *, retention_days=30) -> dict:
    """Keep receipts and unknown paid work; discard only provably unreferenced inputs.

    Call while drained and idle. This is deliberately conservative: failed paid
    operations and author revision archives keep their inputs indefinitely.
    """
    from .deployment_status import deployment_activity

    status = deployment_activity(app)
    if not app.state.admission.draining or not status["safe_to_deploy"]:
        raise RuntimeError("Drain Canary and wait for active work before housekeeping")
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    referenced = set()
    removed = 0
    with app.state.admission.journal() as db:
        rows = db.execute(
            "SELECT j.payload,o.command,o.id FROM jobs j JOIN operation_outbox o ON o.id=j.id"
        ).fetchall()
        for raw, command, identity in rows:
            record = json.loads(raw)
            finished = record.get("finished_at")
            safe = record["status"] == "complete" or (
                record["status"] == "cancelled" and not record.get("started_at")
            )
            if safe and finished and datetime.fromisoformat(finished) < cutoff:
                # The immutable request receipt and outcome remain the dedup tombstone.
                db.execute("DELETE FROM operation_outbox WHERE id=?", (identity,))
            else:
                referenced.update(_strings(json.loads(command)))
    for account in app.state.projects_dir.iterdir():
        if not account.is_dir() or account.name.startswith(".") or account.is_symlink():
            continue
        with production_lock(account):
            for project in account.iterdir():
                if not project.is_dir() or project.is_symlink() or project.name.startswith("."):
                    continue
                with production_lock(project):
                    words = set(referenced)
                    # Active and archived author revision manifests are authorities.
                    for manifest in project.rglob("*.json"):
                        if ".jobs" in manifest.parts:
                            continue
                        try:
                            words.update(_strings(json.loads(manifest.read_text())))
                        except (ValueError, OSError):
                            # A malformed authority prevents cleanup of this project.
                            words = None
                            break
                    if words is None:
                        continue
                    for blob in project.glob("**/.jobs/inputs/*"):
                        if blob.is_file() and blob.name not in words:
                            blob.unlink()
                            removed += 1
                    # Original manuscripts are author-owned. Their provenance
                    # is not always a literal JSON path; only explicit project
                    # deletion may remove them. Cleanup covers job blobs only.
    # Public reads already accept only current versions. Retain one prior version
    # for rollback; the private owner record names the two reachable snapshots.
    for owner in (app.state.projects_dir / ".publications" / "owners").glob("*.json"):
        record = json.loads(owner.read_text())
        book = app.state.projects_dir / ".publications" / record["id"]
        if "version" not in record:
            continue  # Historical owner has no rollback inventory; preserve it.
        keep = {record.get("version"), record.get("previous_version")}
        for candidate in book.iterdir() if book.exists() else []:
            if candidate.is_dir() and candidate.name not in keep:
                shutil.rmtree(candidate)
                removed += 1
    return {"removed_items": removed}
