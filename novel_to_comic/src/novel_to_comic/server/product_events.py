"""Privacy-bounded product-event capture.

Server milestones are best-effort: observability must never make a customer
action fail. Browser-originated events use the authenticated endpoint below and
are constrained to a small event/property allowlist.
"""

from __future__ import annotations

import json
import os
import re
import uuid
import logging
from datetime import datetime
from typing import Any, Literal

from .db import get_db

logger = logging.getLogger("canary.product_events")

MAX_PROPERTIES_BYTES = 8 * 1024

ACQUISITION_FIELDS = frozenset({
    "acquisition_source", "acquisition_medium", "acquisition_campaign",
    "referring_domain", "referred_by_book",
})

SERVER_EVENT_PROPERTIES: dict[str, frozenset[str]] = {
    "page_ready": frozenset({"page_number", "render_revision", "run_id", "attempt_id", "stage_attempt_id"}),
    "operation_completed": frozenset({"operation", "operation_id", "run_id", "attempt_id", "stage_attempt_id", "stage", "status", "outcome", "phase", "queue_ms", "latency_ms"}),
    "output_accepted": frozenset({"stage", "scope", "run_id", "attempt_id"}),
    "feedback_submitted": frozenset({"category", "rating", "feedback_id"}),
    "credit_blocked": frozenset({"stage"}),
    "stage_dispatched": frozenset({"stage", "outcome", "latency_ms", "run_id", "attempt_id", "cost_usd", "estimated_cost_usd", "cost_status", "cost_source", "unknown_usage_count"}),
    "export_package_ready": frozenset({"format", "cached"}),
    "export_download_requested": frozenset({"format"}),
    "project_created": frozenset({"source", "file_type"}),
    "stage_started": frozenset({"stage", "rerun", "retry_failed", "run_id", "attempt_id"}),
    "stage_succeeded": frozenset({"stage", "outcome", "latency_ms", "run_id", "attempt_id", "cost_usd", "estimated_cost_usd", "cost_status", "cost_source", "unknown_usage_count"}),
    "stage_failed": frozenset({"stage", "outcome", "error_type", "latency_ms", "run_id", "attempt_id", "cost_usd", "estimated_cost_usd", "cost_status", "cost_source", "unknown_usage_count"}),
    "stage_approved": frozenset({"stage"}),
    "style_selected": frozenset({"style_id"}),
    # The North Star for the Cold Open: upload to first page of the author's story.
    "cold_open_printed": frozenset({"pages", "ranking", "story_copy", "latency_ms"}),
    "cold_open_favorite": frozenset({"look_id"}),
    "page_outcome": frozenset({"outcome", "page_number", "render_revision", "generation_id", "category", "mode"}),
    "checkout_started": frozenset({"package_id", "gross_amount_cents", "currency", "stripe_mode"}),
    "credits_purchased": frozenset({"package_id", "credits", "gross_amount_cents", "currency", "stripe_mode"}),
    "refund_completed": frozenset({"credits", "gross_amount_cents", "currency"}),
    "operator_credit_granted": frozenset({"amount_credits", "app_environment", "stripe_mode"}),
    "export_succeeded": frozenset({"format", "cached"}),
    "account_created": ACQUISITION_FIELDS | frozenset({"signup_capture_method"}),
    "account_observed": ACQUISITION_FIELDS,
}

PERSON_PROPERTIES = frozenset({"signed_up_at", *ACQUISITION_FIELDS})
_ACQUISITION_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_ACCOUNT_NAMESPACE = uuid.UUID("5b0f3c52-8d5e-4f4a-9a57-0b6f1c0e2a71")
_accounts_recorded: set[str] = set()

WEB_EVENT_PROPERTIES: dict[str, frozenset[str]] = {
    "station_viewed": frozenset({"station"}),
    "inspect_drawer_opened": frozenset({"drawer"}),
    "checkout_cancelled": frozenset({"package_id"}),
    "page_viewed": frozenset({"page_number", "render_revision"}),
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
    for key in ("page_number", "render_revision"):
        if key in properties and (type(properties[key]) is not int or properties[key] < 1):
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
    event_id: str | None = None,
    occurred_at: str | None = None,
    person_set_once: dict[str, Any] | None = None,
    event_environment: str | None = None,
    event_release: str | None = None,
) -> None:
    """Validate and persist one product event; raises on invalid input/write.

    A caller-supplied ``event_id`` makes the event idempotent: a repeated
    write with the same ID is ignored rather than duplicated.
    """
    clean = _clean_properties(event_name, properties or {}, source=source)
    clean.update(schema_version=1, environment=event_environment or os.environ.get("CANARY_ENV", "development"), release=event_release or os.environ.get("CANARY_VERSION", "unknown"))
    if person_set_once:
        unknown = set(person_set_once) - PERSON_PROPERTIES
        if unknown:
            raise ValueError(f"Unsupported person properties: {sorted(unknown)}")
        clean["$set_once"] = {k: v for k, v in person_set_once.items() if isinstance(v, (bool, int, float, str))}
    payload = {
        "id": event_id or str(uuid.uuid4()),
        "event_name": event_name,
        "user_id": user_id,
        "project_id": project_id,
        "job_id": job_id,
        "request_id": request_id,
        "source": source,
        "properties_json": clean,
    }
    if occurred_at:
        payload["occurred_at"] = occurred_at
    table = get_db().table("product_events")
    if event_id:
        table.upsert(payload, on_conflict="id", ignore_duplicates=True).execute()
    else:
        table.insert(payload).execute()


def capture_server_event(event_name: str, **kwargs: Any) -> None:
    """Best-effort server capture that cannot fail the owning customer action."""
    try:
        record_product_event(event_name, source="server", **kwargs)
    except Exception as exc:  # noqa: BLE001 - telemetry is intentionally non-blocking
        logger.warning("Product event capture failed event=%s: %s", event_name, exc)


def _acquisition(metadata: dict[str, Any]) -> dict[str, Any]:
    """First-touch attribution saved at signup; advisory, never authorization."""
    raw = metadata.get("acquisition") if isinstance(metadata.get("acquisition"), dict) else {}
    result: dict[str, Any] = {}
    for key in ("source", "medium", "campaign", "referring_domain"):
        value = raw.get(key)
        if isinstance(value, str) and _ACQUISITION_TOKEN.fullmatch(value.lower()):
            result["referring_domain" if key == "referring_domain" else f"acquisition_{key}"] = value.lower()
    if metadata.get("referred_by_book"):
        result["referred_by_book"] = True
        result.setdefault("acquisition_source", "book_referral")
    # Signups predating attribution capture stay "unknown", never "direct".
    result.setdefault("acquisition_source", "direct" if isinstance(metadata.get("acquisition"), dict) else "unknown")
    return result


def _internal_accounts() -> set[str]:
    return {item.strip().lower() for item in os.environ.get("CANARY_INTERNAL_ACCOUNT_IDS", "").split(",") if item.strip()}


def _attribute(record: Any, name: str) -> Any:
    return record.get(name) if isinstance(record, dict) else getattr(record, name, None)


def record_account_observed(user_id: str) -> None:
    """Observe an authenticated account, without inventing a signup occurrence.

    Called on each authenticated app load; the deterministic event ID makes the
    write idempotent and the process-local set avoids repeated auth lookups.
    The internal-account flag is re-sent once per process so a changed
    ``CANARY_INTERNAL_ACCOUNT_IDS`` takes effect after the next deploy; it
    feeds PostHog's "Internal / Test users" cohort, which launch views exclude.
    """
    if user_id in _accounts_recorded:
        return
    from .telemetry import capture
    capture("$set", user_id=user_id,
            properties={"$set": {"$internal_or_test_user": user_id.lower() in _internal_accounts()}})
    response = get_db().auth.admin.get_user_by_id(user_id)
    user = _attribute(response, "user") or response
    created = _attribute(user, "created_at")
    if isinstance(created, datetime):
        created = created.isoformat()
    metadata = _attribute(user, "user_metadata") or {}
    acquisition = _acquisition(metadata if isinstance(metadata, dict) else {})
    record_product_event(
        "account_observed",
        user_id=user_id,
        properties=acquisition,
        event_id=str(uuid.uuid5(_ACCOUNT_NAMESPACE, f"account_observed:{user_id}")),
        person_set_once={**acquisition, **({"signed_up_at": created} if isinstance(created, str) else {})},
    )
    _accounts_recorded.add(user_id)
