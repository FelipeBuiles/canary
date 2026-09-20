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
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from novel_to_comic.config import Config


class JobCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=1, ge=1, le=1)
    operation: str
    project_dir: str
    config: dict[str, Any]
    one_shot_image_model_alias: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    stage: str = ""
    user_id: str = ""
    project_id: str | None = None
    reservation_credits: int = 0
    ledger_job_id: str = ""
    debit_description: str = "Generation"


def command(operation: str, project_dir: Path, config: Config, **arguments) -> JobCommand:
    return JobCommand(operation=operation, project_dir=str(project_dir.resolve()),
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
