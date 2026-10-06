"""Serializable operation inputs. No request objects, pickles, or executable closures.

Large immutable inputs are content-addressed on the project volume. PostgreSQL
carries only an outbox identity; the volume remains the artifact authority.
"""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from novel_to_comic.config import Config
from novel_to_comic.models.draw import FrozenPageGenerationRequest, PageIssue
from novel_to_comic.models.page import ComicPage
from novel_to_comic.models.story_bible import StoryBible


class Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PipelineArguments(Arguments):
    rerun: bool = False
    queue_pages: bool = False
    approve_part: str | None = None


class PageArguments(Arguments):
    request: FrozenPageGenerationRequest
    page: ComicPage
    references: list[str] = Field(max_length=32)
    edit_source: str | None = None
    ocr: bool = False
    request_revision: int | None = Field(default=None, ge=1)
    render_revision: int | None = Field(default=None, ge=1)
    parent_render_revision: int | None = Field(default=None, ge=1)
    issue: PageIssue | None = None


class CastArguments(Arguments):
    asset_id: str = Field(min_length=1, max_length=200)
    kind: Literal["character_ref_regen", "location_plate_regen", "prop_ref_regen"]


class InstructionArguments(Arguments):
    asset_type: Literal["character", "location", "prop"]
    asset_id: str = Field(min_length=1, max_length=200)
    state_id: str | None = None
    instruction: str = Field(min_length=1, max_length=4000)
    attachments: list[dict[str, Any]] = Field(max_length=3)


class TranslationArguments(Arguments):
    prepared: dict[str, Any]


class StyleArguments(Arguments):
    bible: StoryBible
    candidate: dict[str, Any]
    index: int = Field(ge=1)
    lifecycle_owned: bool = False


class DirectionArguments(StyleArguments):
    direction: dict[str, Any]
    with_neighbors: bool = False


class SuggestArguments(Arguments):
    bible: StoryBible
    direction: dict[str, Any] | None = None
    lifecycle_owned: bool = False


ARGUMENT_MODELS = {
    "pipeline": PipelineArguments, "page_draw": PageArguments,
    "cover": Arguments, "cast_asset": CastArguments,
    "cast_instruction": InstructionArguments, "lettering_translation": TranslationArguments,
    "style_sample": StyleArguments, "style_validation": StyleArguments,
    "style_direction": DirectionArguments, "style_suggest": SuggestArguments,
}


class JobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=1, ge=1, le=1)
    operation: Literal["pipeline", "page_draw", "cover", "cast_asset", "cast_instruction",
                       "lettering_translation", "style_sample", "style_validation",
                       "style_direction", "style_suggest"]
    project_dir: str
    config: dict[str, Any]
    one_shot_image_model_alias: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    stage: str = ""
    user_id: str = ""
    project_id: str | None = None
    reservation_credits: int = Field(default=0, ge=0)
    ledger_job_id: str = ""
    debit_description: str = "Generation"
    traceparent: str = Field(default="", pattern=r"^(?:[0-9a-f]{2}-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2})?$")
    request_id: str = Field(default="", max_length=64)
    browser_session_id: str = Field(default="", pattern=r"^(?:[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})?$")

    @model_validator(mode="after")
    def validate_arguments(self):
        self.arguments = ARGUMENT_MODELS[self.operation].model_validate(self.arguments).model_dump(mode="json")
        if self.operation == "cast_instruction":
            from novel_to_comic.cast_reference_inputs import parse_reference_input
            for reference in self.arguments["attachments"]:
                parse_reference_input(reference)
        elif self.operation == "lettering_translation":
            from novel_to_comic.lettering.translation import PreparedTranslation
            TypeAdapter(PreparedTranslation).validate_python(self.arguments["prepared"])
        elif self.operation == "page_draw":
            for digest in [*self.arguments["references"], self.arguments["edit_source"]]:
                if digest is not None and not re.fullmatch(r"[0-9a-f]{64}", digest):
                    raise ValueError("Invalid job input digest")
        return self


def command(operation: str, project_dir: Path, config: Config, **arguments) -> JobCommand:
    from .telemetry import trace_carrier, context_fields
    return JobCommand(traceparent=trace_carrier().get("traceparent", ""),
                      browser_session_id=context_fields().get("browser_session_id", ""),
                      request_id=context_fields().get("request_id", ""), operation=operation, project_dir=str(project_dir.resolve()),
                      config=config.model_dump(mode="json"), arguments=arguments,
                      one_shot_image_model_alias=config._one_shot_image_model_alias)


def snapshot(value) -> Any:
    """JSON conversion for typed dataclass/model inputs (never arbitrary code)."""
    return TypeAdapter(type(value)).dump_python(value, mode="json")


def save_blob(project_dir: Path, data: bytes | None) -> str | None:
    if data is None:
        return None
    digest = hashlib.sha256(data).hexdigest()
    root = project_dir / ".jobs" / "inputs"
    root.mkdir(parents=True, exist_ok=True)
    path = root / digest
    if not path.exists():
        fd, name = tempfile.mkstemp(dir=root)
        try:
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
    return digest


def read_blob(project_dir: Path, digest: str | None) -> bytes | None:
    if digest is None:
        return None
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid job input digest")
    data = (project_dir / ".jobs" / "inputs" / digest).read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError("Saved job input changed; explicitly prepare a new operation")
    return data
