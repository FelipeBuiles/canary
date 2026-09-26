"""Privacy-bounded product-event capture.

Server milestones are best-effort: observability must never make a customer
action fail. Browser-originated events use the authenticated endpoint below and
are constrained to a small event/property allowlist.
"""

from __future__ import annotations

import json
import os
import uuid
import logging
from typing import Any, Literal

from .db import get_db

logger = logging.getLogger("canary.product_events")

MAX_PROPERTIES_BYTES = 8 * 1024

SERVER_EVENT_PROPERTIES: dict[str, frozenset[str]] = {
    "page_ready": frozenset({"page_number"}),
    "feedback_submitted": frozenset({"category", "rating", "feedback_id"}),
    "credit_blocked": frozenset({"stage"}),
    "stage_dispatched": frozenset({"stage", "outcome"}),
    "export_package_ready": frozenset({"format", "cached"}),
    "export_download_requested": frozenset({"format"}),
    "project_created": frozenset({"source", "file_type"}),
    "stage_started": frozenset({"stage", "rerun", "retry_failed"}),
    "stage_succeeded": frozenset({"stage", "outcome"}),
    "stage_failed": frozenset({"stage", "outcome", "error_type"}),
    "stage_approved": frozenset({"stage"}),
    "style_selected": frozenset({"style_id"}),
    "panel_flagged": frozenset(),
    "panel_regenerated": frozenset({"mode"}),
    "checkout_started": frozenset({"package_id", "gross_amount_cents", "currency"}),
    "credits_purchased": frozenset({"package_id", "credits", "gross_amount_cents", "currency"}),
    "refund_completed": frozenset({"credits", "gross_amount_cents", "currency"}),
    "operator_credit_granted": frozenset({"amount_credits", "app_environment", "stripe_mode"}),
    "export_succeeded": frozenset({"format", "cached"}),
}

WEB_EVENT_PROPERTIES: dict[str, frozenset[str]] = {
    "station_viewed": frozenset({"station"}),
    "inspect_drawer_opened": frozenset({"drawer"}),
    "checkout_cancelled": frozenset({"package_id"}),
}


def _clean_properties(event_name: str, properties: dict[str, Any], *, source: str) -> dict[str, Any]:
    allowlist = SERVER_EVENT_PROPERTIES if source == "server" else WEB_EVENT_PROPERTIES
    allowed = allowlist.get(event_name)
    if allowed is None:
        raise ValueError(f"Unknown {source} product event: {event_name}")
    unknown = set(properties) - allowed
    if unknown:
        raise ValueError(f"Unsupported properties for {event_name}: {sorted(unknown)}")

    enums = {"station": {"story", "look", "pages", "book"},
             "drawer": {"inspect", "details", "generation", "history"}}
    for key, choices in enums.items():
        if key in properties and properties[key] not in choices:
            raise ValueError(f"Invalid {key}")
    clean: dict[str, Any] = {}
    for key, value in properties.items():
        if value is None or isinstance(value, (bool, int, float)):
            clean[key] = value
        elif isinstance(value, str):
            clean[key] = value[:200]
        else:
            raise ValueError(f"Product event property {key} must be scalar")
    if len(json.dumps(clean, separators=(",", ":")).encode()) > MAX_PROPERTIES_BYTES:
        raise ValueError("Product event properties exceed 8 KiB")
    return clean


def record_product_event(
    event_name: str,
    *,
    user_id: str | None,
    project_id: str | None = None,
    job_id: str | None = None,
    request_id: str | None = None,
    source: Literal["server", "web"] = "server",
    properties: dict[str, Any] | None = None,
) -> None:
    """Validate and persist one product event; raises on invalid input/write."""
    clean = _clean_properties(event_name, properties or {}, source=source)
    clean.update(schema_version=1, environment=os.environ.get("CANARY_ENV", "dev"), release=os.environ.get("CANARY_VERSION", "unknown"))
    payload = {
        "id": str(uuid.uuid4()),
        "event_name": event_name,
        "user_id": user_id,
        "project_id": project_id,
        "job_id": job_id,
        "request_id": request_id,
        "source": source,
        "properties_json": clean,
    }
    get_db().table("product_events").insert(payload).execute()


def capture_server_event(event_name: str, **kwargs: Any) -> None:
    """Best-effort server capture that cannot fail the owning customer action."""
    try:
        record_product_event(event_name, source="server", **kwargs)
    except Exception as exc:  # noqa: BLE001 - telemetry is intentionally non-blocking
        logger.warning("Product event capture failed event=%s: %s", event_name, exc)
