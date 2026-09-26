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
from .telemetry import _before_send, log_event, safe_fields


def _pending():
    return get_db().table("product_events").select("*").is_("posthog_exported_at", "null").order("occurred_at").limit(100).execute().data or []


def _ack(ids):
    get_db().table("product_events").update({"posthog_exported_at": datetime.datetime.now(datetime.UTC).isoformat()}).in_("id", ids).execute()


def wire_event(row):
    properties = safe_fields({**row.get("properties_json", {}),
        "project_id": row.get("project_id"), "job_id": row.get("job_id"),
        "request_id": row.get("request_id"), "source": row.get("source")})
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


async def deliver_product_events():
    async with httpx.AsyncClient(timeout=5) as client:
        while True:
            try:
                await deliver_once(client)
            except Exception as exc:
                log_event("analytics.delivery_failed", error_type=type(exc).__name__)
            await asyncio.sleep(10)
