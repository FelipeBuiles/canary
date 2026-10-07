"""Durable hosted OCR inputs and attempts; raw evidence survives interpretation."""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TextractCrop(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    observation_id: str
    status: Literal["ready", "no_region", "over_budget", "unavailable"]
    bounds: tuple[int, int, int, int] | None = None
    sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    width: int = Field(default=0, ge=0)
    height: int = Field(default=0, ge=0)


class TextractPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    page_number: int = Field(ge=1)
    render_revision: int = Field(ge=1)
    render_image_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    input_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    crops: tuple[TextractCrop, ...]


class TextractAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[1] = 1
    attempt_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    page_number: int = Field(ge=1)
    render_revision: int = Field(ge=1)
    render_image_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    recognition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    crop_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    model: str
    region: str
    started_at: float
    expires_at: float
    finished_at: float | None = None
    status: Literal["submitting", "succeeded", "failed", "outcome_unknown"]
    estimated_units: Literal[1] = 1
    unit_price_usd: str
    pricing_snapshot: str
    charged_credits: Literal[0] = 0  # Canary funds this optional quality check.
    response: dict[str, Any] | None = None
    error_code: str | None = None
