"""Private working projects publish immutable, explicitly selected reader copies."""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PIL import Image
from pydantic import BaseModel, Field, ConfigDict
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.artifact_lock import production_lock
from novel_to_comic.page_finishing import finish_book
from novel_to_comic.target_artifacts import TargetArtifacts


class PublicationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    author: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=600)
    allow_feature: bool = False


def root(projects_dir: Path) -> Path:
    return projects_dir / ".publications"


def owner_path(projects_dir: Path, user: str, project: str) -> Path:
    key = hashlib.sha256(f"{user}:{project}".encode()).hexdigest()
    return root(projects_dir) / "owners" / f"{key}.json"


def read_json(path: Path):
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        return None


def write_json(path: Path, data: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(data))
    temporary.replace(path)


def publish(
    projects_dir: Path,
    project_dir: Path,
    user: str,
    project: str,
    metadata: PublicationInput,
    ctx: StageRuntime,
):
    with production_lock(root(projects_dir)), production_lock(project_dir):
        target = TargetArtifacts(project_dir)
        with ctx.execute(total=1, estimated_cost_usd=0):
            result = finish_book(target, formats=(), clear_derived_outputs=False)
            if not result.preflight.ready_to_export or not result.preflight.pages:
                raise ValueError(
                    "Finish the edition checks before publishing your book."
                )
            owner = owner_path(projects_dir, user, project)
            prior = read_json(owner)
            publication_id = prior["id"] if prior else uuid4().hex
            version = uuid4().hex
            destination = root(projects_dir) / publication_id / version
            destination.mkdir(parents=True)
            try:
                pages = []
                for page in result.preflight.pages:
                    source = target.normalized_page_path(page.page_number)
                    data = source.read_bytes()
                    if hashlib.sha256(data).hexdigest() != page.normalized_image_sha256:
                        raise ValueError(
                            "A page changed during publication. Try publishing again."
                        )
                    filename = f"{page.page_number}.jpg"
                    (destination / filename).write_bytes(data)
                    with Image.open(source) as image:
                        width, height = image.size
                    pages.append(
                        {
                            "number": page.page_number,
                            "spread_role": target.read_page(page.page_number).spread_role,
                            "width": width,
                            "height": height,
                            "url": f"/api/public/books/{publication_id}/{version}/pages/{page.page_number}",
                        }
                    )
                current = read_json(
                    root(projects_dir) / publication_id / "current.json"
                )
                record = {
                    **metadata.model_dump(),
                    "id": publication_id,
                    "version": version,
                    "published_at": datetime.now(timezone.utc).isoformat(),
                    "pages": pages,
                    "featured": bool(
                        current and current.get("featured") and metadata.allow_feature
                    ),
                }
                # Record the stable identity first; a failed initial publication is still private.
                write_json(owner, {"id": publication_id})
                write_json(root(projects_dir) / publication_id / "current.json", record)
            except Exception:
                shutil.rmtree(destination, ignore_errors=True)
                raise
            ctx.record_item_done()
            ctx.progress(1, 1)
            return record
