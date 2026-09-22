"""Operator-selected, portable public editions shipped in the showcase folder."""

from pathlib import Path
from typing import Literal
import os

from pydantic import BaseModel, Field

from .publications import PublicationInput


class ShowcasePage(BaseModel):
    number: int = Field(gt=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    spread_role: Literal["single", "left", "right", "spread"] = "single"


class ShowcaseBook(PublicationInput):
    id: str = Field(pattern=r"^[0-9a-f]{32}$")
    version: str = Field(pattern=r"^[0-9a-f]{32}$")
    published_at: str
    pages: list[ShowcasePage] = Field(min_length=1)


def root() -> Path:
    return Path(os.environ.get(
        "CANARY_SHOWCASE_DIR", str(Path(__file__).resolve().parents[4] / "showcase" / "books")
    ))


def books() -> list[tuple[dict, Path]]:
    """Folder names determine display order; only explicit book manifests are public."""
    result = []
    seen = set()
    for manifest in sorted(root().glob("*/book.json")):
        book = ShowcaseBook.model_validate_json(manifest.read_text())
        if book.id in seen:
            raise ValueError(f"Duplicate showcase book ID in {manifest}")
        seen.add(book.id)
        numbers = [page.number for page in book.pages]
        if numbers != list(range(1, len(numbers) + 1)):
            raise ValueError(f"Showcase pages must be consecutive in {manifest}")
        directory = manifest.parent / book.version
        for number in numbers:
            page = directory / f"{number}.jpg"
            if not page.is_file() or not page.resolve().is_relative_to(manifest.parent.resolve()):
                raise ValueError(f"Missing or external showcase page: {page}")
        record = book.model_dump()
        record.update(allow_feature=True, featured=True)
        for page in record["pages"]:
            page["url"] = f"/api/public/books/{book.id}/{book.version}/pages/{page['number']}"
        result.append((record, directory))
    return result


def find(book_id: str) -> tuple[dict, Path] | None:
    return next((entry for entry in books() if entry[0]["id"] == book_id), None)
