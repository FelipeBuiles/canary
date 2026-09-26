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
from novel_to_comic.localization import LANGUAGES
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.artifact_lock import production_lock
from novel_to_comic.models.finish import FinishProductionSpec
from novel_to_comic.lettering.service import is_hybrid, render_stored_locale
from novel_to_comic.models.finish import FinishPreflight
from novel_to_comic.page_finishing import (
    _normalize_page,
    finish_book,
    source_credit_info,
    source_credit_page,
)
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts

# Reader languages; "source" is published only when it is the project's language.
PUBLIC_LOCALES = LANGUAGES


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


def _translated_pages(
    target: TargetArtifacts,
    preflight: FinishPreflight,
    locale: str,
    directory: Path,
    url: str,
    primary: list[dict],
    credit_image: bytes | None,
) -> list[dict]:
    """Every page of one stored language, or an error that leaves the language out."""
    directory.mkdir(parents=True)
    pages = []
    production = preflight.production
    for page, published in zip(preflight.pages, primary):
        image = render_stored_locale(
            target, page.page_number, locale, expected_render_revision=page.render_revision
        )
        spec = FinishProductionSpec(
            canvas_width=page.width,
            canvas_height=page.height,
            bleed_px=page.bleed_px,
            dpi=production.dpi if production else 300,
            jpeg_quality=production.jpeg_quality if production else 88,
        )
        _normalize_page(image, directory / f"{page.page_number}.jpg", spec)
        pages.append(published | {"url": f"{url}/{page.page_number}"})
    if credit_image is not None:
        published = primary[-1]
        (directory / f"{published['number']}.jpg").write_bytes(credit_image)
        pages.append(published | {"url": f"{url}/{published['number']}"})
    return pages


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
                credit = source_credit_info(project_dir)
                credit_image = None
                if credit:
                    last = pages[-1]
                    production = result.preflight.production
                    spec = FinishProductionSpec(
                        canvas_width=last["width"],
                        canvas_height=last["height"],
                        dpi=production.dpi if production else 300,
                        jpeg_quality=production.jpeg_quality if production else 88,
                    )
                    credit_image = source_credit_page(project_dir, spec)
                    if credit_image is None:
                        raise ValueError("Share-alike sample is missing publication attribution")
                    number = last["number"] + 1
                    (destination / f"{number}.jpg").write_bytes(credit_image)
                    pages.append({
                        "number": number,
                        "spread_role": "single",
                        "width": spec.canvas_width,
                        "height": spec.canvas_height,
                        "url": f"/api/public/books/{publication_id}/{version}/pages/{number}",
                    })
                languages = {}
                if is_hybrid(target):
                    primary = target.read_lettering_settings().locale
                    languages = {"locale": primary, "translations": [], "unpublished_locales": {}}
                    for locale in PUBLIC_LOCALES:
                        if locale == primary:
                            continue
                        try:
                            translated = _translated_pages(
                                target, result.preflight, locale, destination / locale,
                                f"/api/public/books/{publication_id}/{version}/locales/{locale}/pages",
                                pages, credit_image,
                            )
                        except (ValueError, ArtifactMissing, ArtifactInvalid) as exc:
                            # Incomplete or unfit languages stay private; the book still publishes.
                            shutil.rmtree(destination / locale, ignore_errors=True)
                            languages["unpublished_locales"][locale] = str(exc)
                            continue
                        languages["translations"].append({"locale": locale, "pages": translated})
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
                if credit:
                    record["source_credit"] = credit
                if languages:
                    record["locale"] = languages["locale"]
                    record["translations"] = languages["translations"]
                # Record the stable identity first; a failed initial publication is still private.
                write_json(owner, {"id": publication_id})
                write_json(root(projects_dir) / publication_id / "current.json", record)
            except Exception:
                shutil.rmtree(destination, ignore_errors=True)
                raise
            ctx.record_item_done()
            ctx.progress(1, 1)
            # Why a language was left out is for the author only, never the public record.
            if languages:
                return record | {"unpublished_locales": languages["unpublished_locales"]}
            return record
