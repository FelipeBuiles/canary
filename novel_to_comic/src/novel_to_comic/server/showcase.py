"""Operator-selected, portable public editions shipped in the showcase folder."""

from pathlib import Path
from typing import Literal
import logging
import os

from pydantic import BaseModel, Field

from .publications import PublicationInput
from .telemetry import capture_exception, log_event

_reported: set[tuple[str, int]] = set()


class ShowcasePage(BaseModel):
    number: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    spread_role: Literal["single", "left", "right", "spread"] = "single"


class ShowcaseTranslation(BaseModel):
    locale: str = Field(pattern=r"^[a-z]{2}$")
    pages: list[ShowcasePage] = Field(min_length=1)


class ShowcaseBook(PublicationInput):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    version: str = Field(pattern=r"^[0-9a-f]{32}$")
    published_at: str
    pages: list[ShowcasePage] = Field(min_length=1)
    source_credit: dict[str, str] | None = None
    # Editable-lettering editions: the primary language and complete published translations.
    locale: str | None = None
    translations: list[ShowcaseTranslation] | None = None


def root() -> Path:
    return Path(os.environ.get(
        "CANARY_SHOWCASE_DIR", str(Path(__file__).resolve().parents[4] / "showcase" / "books")
    ))


def books(*, strict: bool = False) -> list[tuple[dict, Path]]:
    """Folder names determine display order; only explicit book manifests are public.

    An invalid manifest hides only its own book unless `strict` is set.
    """
    result = []
    seen = set()
    for manifest in sorted(root().glob("*/book.json")):
        try:
            record, directory = _load(manifest)
            if record["id"] in seen:
                raise ValueError(f"Duplicate showcase book ID in {manifest}")
        except ValueError as error:
            if strict:
                raise
            _report(manifest, error)
            continue
        seen.add(record["id"])
        result.append((record, directory))
    return result


def _report(manifest: Path, error: ValueError) -> None:
    key = (str(manifest), manifest.stat().st_mtime_ns)
    if key in _reported:
        return
    _reported.add(key)
    log_event("showcase.book_skipped", level=logging.ERROR, feature="showcase",
              source=manifest.parent.name, error_type=type(error).__name__)
    capture_exception(error, feature="showcase", source=manifest.parent.name)


def _load(manifest: Path) -> tuple[dict, Path]:
    book = ShowcaseBook.model_validate_json(manifest.read_text())
    numbers = [page.number for page in book.pages]
    if numbers != list(range(1, len(numbers) + 1)):
        raise ValueError(f"Showcase pages must be consecutive in {manifest}")
    directory = manifest.parent / book.version
    languages = [("", book.pages)] + [(f"{t.locale}/", t.pages) for t in book.translations or ()]
    for prefix, pages in languages:
        if [page.number for page in pages] != numbers:
            raise ValueError(f"Showcase translation pages must match the book in {manifest}")
        for number in numbers:
            page = directory / f"{prefix}{number}.jpg"
            if not page.is_file() or not page.resolve().is_relative_to(manifest.parent.resolve()):
                raise ValueError(f"Missing or external showcase page: {page}")
    record = book.model_dump(exclude_none=True)
    record.update(allow_feature=True, featured=True)
    for page in record["pages"]:
        page["url"] = f"/api/public/books/{book.id}/{book.version}/pages/{page['number']}"
    for translation in record.get("translations", ()):
        for page in translation["pages"]:
            page["url"] = (
                f"/api/public/books/{book.id}/{book.version}/locales/"
                f"{translation['locale']}/pages/{page['number']}"
            )
    return record, directory


def find(book_id: str) -> tuple[dict, Path] | None:
    return next((entry for entry in books() if entry[0]["id"] == book_id), None)
