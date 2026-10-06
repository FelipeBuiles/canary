"""Cheap in-process deployment-safety monitoring.

This deliberately avoids Supabase and model-provider calls. It answers the
operational question "is this process currently responsible for generation
work?" using the task and queue state already owned by the FastAPI app.
"""

from __future__ import annotations

import hmac
import os
from typing import Any

from fastapi import Header, HTTPException
from .generation_jobs import generation_jobs_snapshot


def require_ops_token(
    x_canary_ops_token: str | None = Header(None, alias="X-Canary-Ops-Token"),
) -> None:
    """Protect global activity information with an operator-only token."""
    expected = os.environ.get("CANARY_OPS_TOKEN", "").strip()
    if not expected:
        raise HTTPException(503, "CANARY_OPS_TOKEN is not configured")
    supplied = (x_canary_ops_token or "").strip()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(401, "Invalid operations token")


def _unfinished(values) -> int:
    return sum(1 for value in values if not value.done())


def deployment_activity(app) -> dict[str, Any]:
    """Return aggregate activity without exposing users, projects, or prompts."""
    active_jobs = [
        job
        for job in generation_jobs_snapshot(app)
        if job.status in {"queued", "running"}
    ]
    queued_jobs = sum(1 for job in active_jobs if job.status == "queued")
    running_jobs = sum(1 for job in active_jobs if job.status == "running")
    # Durable operations are persisted and cannot start while drained, so they
    # survive process replacement. Fixture closures (no command) cannot.
    durable_queued = sum(
        1 for job in active_jobs
        if job.status == "queued" and getattr(job, "command", None) is not None
    )
    draining = getattr(getattr(app.state, "admission", None), "draining", False)
    queued_items = app.state.generation_queue.qsize()
    draw_panels = sum(
        len(panels) for panels in app.state.draw_in_flight.values()
    )

    counts = {
        "admitting_requests": getattr(getattr(app.state, "admission", None), "active_requests", 0),
        "queued_generation_jobs": queued_jobs,
        "running_generation_jobs": running_jobs,
        "queue_items": queued_items,
        "draw_panels_in_flight": draw_panels,
    }
    blocking = dict(counts)
    if draining:
        blocking["queued_generation_jobs"] -= durable_queued
    safe_to_deploy = not any(blocking.values())
    return {
        "status": "idle" if safe_to_deploy else "busy",
        "safe_to_deploy": safe_to_deploy,
        "draining": draining,
        "counts": counts,
        # Queued durable work a deploy preserves and resumes after restart.
        "preserved_queued_operations": durable_queued if draining else 0,
    }
