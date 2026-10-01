"""Retry persisted product events independently of customer requests.

PostHog deduplicates stable insert IDs after a response/acknowledgement split.
One process owns delivery on Canary's single Machine. A vendor outage never
replays a customer operation or changes the ledger.
"""
from __future__ import annotations
import asyncio
import datetime
import os
import httpx
from .db import get_db
from .telemetry import _before_send, _with_person_fields, log_event, safe_fields


def _pending():
    return get_db().table("product_events").select("*").is_("posthog_exported_at", "null").order("occurred_at").limit(100).execute().data or []


def _ack(ids):
    get_db().table("product_events").update({"posthog_exported_at": datetime.datetime.now(datetime.UTC).isoformat()}).in_("id", ids).execute()


def wire_event(row):
    stored = row.get("properties_json", {})
    properties = _with_person_fields(safe_fields({**stored,
        "project_id": row.get("project_id"), "job_id": row.get("job_id"),
        "request_id": row.get("request_id"), "event_origin": row.get("source")}), stored)
    properties["$insert_id"] = row["id"]
    event = _before_send({"event": row["event_name"], "properties": properties})
    if event is None:
        raise ValueError("Product event failed privacy validation")
    event.update(distinct_id=row.get("user_id") or "canary-server", timestamp=row["occurred_at"])
    return event


async def deliver_once(client):
    rows = await asyncio.to_thread(_pending)
    if not rows:
        return 0
    response = await client.post(os.environ["POSTHOG_HOST"].rstrip("/") + "/batch/",
        json={"api_key": os.environ["POSTHOG_PROJECT_TOKEN"], "batch": [wire_event(row) for row in rows]})
    response.raise_for_status()
    await asyncio.to_thread(_ack, [row["id"] for row in rows])
    return len(rows)


async def reconcile_signups():
    # RPC returns counts only; no broad auth listing or private rows cross this
    # boundary. Missing migration/outage is observable and never blocks delivery
    # of unrelated existing product events or any customer request.
    try:
        response = await asyncio.to_thread(lambda: get_db().rpc("reconcile_account_created_events", {}).execute())
        result = response.data or {}
        if result.get("recovered") or result.get("remaining") or result.get("legacy_observed"):
            log_event("analytics.signup_reconciled", **{key: int(result.get(key, 0)) for key in ("recovered", "remaining", "legacy_observed")})
    except Exception as exc:
        log_event("analytics.signup_reconciliation_failed", error_type=type(exc).__name__)


async def deliver_product_events(app=None):
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            await reconcile_signups()
            try:
                from .lifecycle_events import flush
                await asyncio.to_thread(flush, app)
                await deliver_once(client)
            except Exception as exc:
                log_event("analytics.delivery_failed", error_type=type(exc).__name__)
            await asyncio.sleep(10)
