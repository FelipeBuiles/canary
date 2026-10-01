"""Content-free lifecycle intents on the existing durable operation journal.

The same event UUID survives dependency outages and an acknowledgement crash.
Delivery retries analytics only; it never retries a customer operation.
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import UTC, datetime

from .product_events import _clean_properties, capture_server_event, record_product_event

_NAMESPACE = uuid.UUID("1dfd7b2d-eaed-4a9c-b3bb-1b633c91ee0a")


def event_uuid(event_name: str, identity: str) -> str:
    kind = "stage_terminal" if event_name in {"stage_succeeded", "stage_failed"} else event_name
    return str(uuid.uuid5(_NAMESPACE, f"{kind}:{identity}"))


def enqueue(db, event_name: str, identity: str, **kwargs) -> None:
    properties = _clean_properties(event_name, kwargs.get("properties", {}), source="server")
    payload = {**kwargs, "properties": properties, "event_name": event_name,
               "event_environment": os.environ.get("CANARY_ENV", "development"),
               "event_release": os.environ.get("CANARY_VERSION", "unknown"),
               "event_id": event_uuid(event_name, identity),
               "occurred_at": kwargs.get("occurred_at") or datetime.now(UTC).isoformat()}
    db.execute("CREATE TABLE IF NOT EXISTS lifecycle_events (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    db.execute("INSERT OR IGNORE INTO lifecycle_events VALUES (?,?)", (payload["event_id"], json.dumps(payload)))


def capture(app, event_name: str, identity: str, **kwargs) -> bool:
    admission = getattr(getattr(app, "state", None), "admission", None)
    if admission is None:
        capture_server_event(event_name, event_id=event_uuid(event_name, identity), **kwargs)
        return False
    try:
        with admission.journal() as db:
            enqueue(db, event_name, identity, **kwargs)
        return True
    except Exception as exc:
        logging.getLogger(__name__).warning("Lifecycle journal failed event=%s type=%s", event_name, type(exc).__name__)
        return False


def flush(app) -> int:
    admission = getattr(getattr(app, "state", None), "admission", None)
    if admission is None:
        return 0
    with admission.journal() as db:
        db.execute("CREATE TABLE IF NOT EXISTS lifecycle_events (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
        rows = db.execute("SELECT id,payload FROM lifecycle_events LIMIT 100").fetchall()
    for event_id, raw in rows:
        record_product_event(**json.loads(raw))
        with admission.journal() as db:
            db.execute("DELETE FROM lifecycle_events WHERE id=?", (event_id,))
    return len(rows)


def stage_properties(current, stage: str, outcome: str) -> dict:
    # No usage records means unknown actual spend, never a measured zero.
    from novel_to_comic.usage import UsageRecord, calculate_cost_breakdown
    costs = []
    for record in current.usage_log:
        try:
            costs.append(calculate_cost_breakdown(UsageRecord.model_validate(record)))
        except (ValueError, TypeError):
            costs.append(None)
    known = [cost.cost_usd for cost in costs if cost is not None and cost.cost_usd is not None]
    status = "unknown" if len(known) != len(costs) or not costs else (
        "reported" if all(record.get("cost_usd") is not None for record in current.usage_log) else "estimated")
    return {"stage": stage, "outcome": outcome, "run_id": current.run_id,
            "attempt_id": current.attempt_id, "cost_status": status,
            "cost_usd": sum(known) if known else None,
            "estimated_cost_usd": current.estimated_cost_usd,
            "unknown_usage_count": len(costs) - len(known),
            "cost_source": "unknown" if status == "unknown" else "provider_reported" if status == "reported" else "pricing_estimate",
            "latency_ms": max(0, ((current.finished_at or datetime.now(UTC)) - current.started_at).total_seconds() * 1000) if current.started_at else None}
