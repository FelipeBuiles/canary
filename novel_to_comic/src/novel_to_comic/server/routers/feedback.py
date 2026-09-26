"""Private, authenticated launch feedback. Free text never enters telemetry."""
from __future__ import annotations
from typing import Literal
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from ..auth import get_current_user
from ..db import get_db
from ..product_events import capture_server_event
from ..ratelimit import limiter

router = APIRouter()


class Feedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID
    category: Literal["frustration", "feature", "praise", "other"]
    message: str = Field(min_length=1, max_length=3000)
    project_id: UUID | None = None
    station: Literal["story", "look", "pages", "book"] | None = None
    rating: Literal["yes", "after_changes", "no", "unsure"] | None = None

    @field_validator("message")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Write a message before sending")
        return value.strip()


@router.post("", status_code=201)
@limiter.limit("6/minute")
def submit_feedback(body: Feedback, request: Request, user_id: str = Depends(get_current_user)):
    db = get_db()
    if body.project_id:
        owned = db.table("projects").select("id").eq("id", str(body.project_id)).eq("user_id", user_id).limit(1).execute()
        if not owned.data:
            raise HTTPException(404, "Project not found")
    # Account-scoped key prevents one account's ID from replacing another's text.
    existing = db.table("customer_feedback").select("id").eq("user_id", user_id).eq("id", str(body.id)).limit(1).execute()
    if existing.data:
        return {"id": str(body.id), "status": "received"}
    db.table("customer_feedback").upsert({**body.model_dump(mode="json"), "user_id": user_id,
        "request_id": getattr(request.state, "request_id", None)}, on_conflict="user_id,id", ignore_duplicates=True).execute()
    capture_server_event("feedback_submitted", user_id=user_id,
        project_id=str(body.project_id) if body.project_id else None,
        properties={"feedback_id": str(body.id), "category": body.category, "rating": body.rating})
    return {"id": str(body.id), "status": "received"}
