"""Authenticated ingestion for the small browser product-event allowlist."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from ..auth import get_current_user
from ..db import get_db
from ..product_events import record_account_created, record_product_event

logger = logging.getLogger("canary.product_events")
router = APIRouter()


class WebProductEvent(BaseModel):
    event_name: str = Field(min_length=1, max_length=80)
    project_id: str | None = Field(default=None, max_length=80)
    properties: dict[str, Any] = Field(default_factory=dict)


@router.post("", status_code=202)
def ingest_web_event(
    body: WebProductEvent,
    request: Request,
    user_id: str = Depends(get_current_user),
):
    if body.project_id:
        owned = (
            get_db()
            .table("projects")
            .select("id")
            .eq("id", body.project_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        if not owned.data:
            raise HTTPException(404, "Project not found")
    try:
        record_product_event(
            body.event_name,
            user_id=user_id,
            project_id=body.project_id,
            request_id=getattr(request.state, "request_id", None),
            source="web",
            properties=body.properties,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        logger.warning("Web product event persistence failed: %s", exc)
        raise HTTPException(503, "Analytics temporarily unavailable") from exc
    return {"status": "accepted"}


@router.post("/account", status_code=202)
def observe_account(user_id: str = Depends(get_current_user)):
    """Record the account's signup milestone once; safe to call on every app load."""
    try:
        record_account_created(user_id)
    except Exception as exc:
        # Analytics must never block the app shell.
        logger.warning("Account analytics capture failed: %s", type(exc).__name__)
    return {"status": "accepted"}
