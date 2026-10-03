"""The series' parts: listing, appending, splitting, replacing and deleting.

Adding or changing parts is free; extraction is the paid step and starts only
when the author starts a part. Text edits follow the freeze rules in
``novel_to_comic.series``.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import re
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from novel_to_comic.book_map import part_entry, read_book_map
from novel_to_comic.chapter_detection import detect_chapters, group_chapters
from novel_to_comic.continuity import earlier_part_changed
from novel_to_comic.input_limits import InputLimitError, InputLimits, read_source
from novel_to_comic.series import (
    PartEditRejected,
    append_parts,
    delete_part,
    edit_blocker,
    rename_part,
    replace_part_text,
    split_part,
)
from novel_to_comic.state import PART_STAGES, load_state
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts
from novel_to_comic.workspace import part_workspace

from ..deps import get_project_dir
from ..body_limit import SourceUploadRoute

router = APIRouter(route_class=SourceUploadRoute)


def _page_count(workspace: Path) -> int:
    try:
        return len(TargetArtifacts(workspace).read_plan().pages)
    except (ArtifactMissing, ValueError):
        return 0


def part_summaries(root: Path) -> list[dict]:
    """Manifest order, each part's own stage statuses and its page count."""
    try:
        manifest = TargetArtifacts(root).read_part_manifest()
    except ArtifactMissing:
        return []
    # Unchanged parts keep their map entry even when the map is being rebuilt.
    book_map = read_book_map(root)
    summaries = []
    for record in manifest.parts:
        workspace = part_workspace(root, record.id)
        try:
            state = load_state(workspace)
            stages = {name: state.stages[name].status.value for name in PART_STAGES}
            blocker = edit_blocker(root, record.id)
        except FileNotFoundError:
            stages = {name: "pending" for name in PART_STAGES}
            blocker = None
        mapped = part_entry(book_map, record)
        summaries.append({
            "id": record.id,
            "ordinal": record.ordinal,
            "title": record.title,
            "characters": record.characters,
            "synopsis": mapped.synopsis if mapped else None,
            "book_role": mapped.role if mapped else None,
            "created_at": record.created_at,
            "origin": record.origin,
            "stages": stages,
            "page_count": _page_count(workspace),
            "has_cover": (workspace / "cover" / "cover.png").is_file(),
            "text_editable": blocker is None,
            "text_locked_reason": blocker,
            # Advisory: an earlier part was re-adapted after this one.
            "earlier_part_changed": earlier_part_changed(workspace),
        })
    return summaries


def _chapters(text: str) -> list[dict]:
    return [
        {**chapter.model_dump(), "characters": chapter.characters}
        for chapter in detect_chapters(text)
    ]


async def _submitted_text(root: Path, file: UploadFile | None, text: str | None) -> tuple[str, str]:
    """Read an uploaded file or pasted text within the upload budgets."""
    from .projects import _ALLOWED_EXTENSIONS, _save_upload_capped

    if file is not None and file.filename:
        suffix = Path(file.filename).suffix.lower()
        if suffix not in _ALLOWED_EXTENSIONS:
            raise HTTPException(400, f"Unsupported file type: {suffix}. Accepted: {', '.join(sorted(_ALLOWED_EXTENSIONS))}")
        uploads = root / "input" / "parts"
        uploads.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix=".incoming-", dir=uploads))
        name = Path(file.filename).name
        try:
            staged = staging / name
            _save_upload_capped(file, staged)
            content = read_source(staged)
            # Keep the original beside the project's other uploads.
            kept = uploads / name
            counter = 1
            while kept.exists():
                kept = uploads / f"{Path(name).stem}-{counter}{suffix}"
                counter += 1
            shutil.move(str(staged), kept)
        except InputLimitError as exc:
            raise HTTPException(exc.status_code, str(exc)) from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        return content, kept.name
    if text is not None and text.strip():
        limits = InputLimits.from_env()
        if len(text) > limits.extracted_characters:
            raise HTTPException(413, f"Pasted text exceeds the {limits.extracted_characters:,}-character limit.")
        return text, "paste"
    raise HTTPException(422, "Upload a file or paste some text.")


def _rejected(exc: Exception) -> HTTPException:
    return HTTPException(409, {"code": "part_locked", "message": str(exc)})


@router.get("/parts")
def list_parts(project_dir: Path = Depends(get_project_dir)):
    return {"parts": part_summaries(project_dir)}


@router.post("/parts")
async def add_part(
    title: str | None = Form(None),
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
    auto_split: bool = Form(True),
    project_dir: Path = Depends(get_project_dir),
):
    """Append a manuscript, grouping long inputs at detected chapter headings."""
    content, origin = await _submitted_text(project_dir, file, text)
    pieces = group_chapters(content) if auto_split else [(None, content)]
    if title:
        pieces[0] = (title, pieces[0][1])
    try:
        records = append_parts(project_dir, pieces, origin=origin)
    except PartEditRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    return {"part": records[0].model_dump(), "chapters": _chapters(pieces[0][1]),
            "created": [record.id for record in records],
            "parts": part_summaries(project_dir)}


@router.get("/parts/{part_id}/chapters")
def part_chapters(part_id: str, project_dir: Path = Depends(get_project_dir)):
    try:
        text = TargetArtifacts(project_dir).read_part_text(part_id)
    except (KeyError, ArtifactMissing):
        raise HTTPException(404, f"Part '{part_id}' not found") from None
    return {"part_id": part_id, "chapters": _chapters(text)}


class SplitRequest(BaseModel):
    # Offsets into the part's text where each following part begins.
    boundaries: list[int] = Field(min_length=1, max_length=500)
    titles: list[str | None] = Field(default_factory=list, max_length=501)


@router.post("/parts/{part_id}/split")
def split(part_id: str, body: SplitRequest, project_dir: Path = Depends(get_project_dir)):
    try:
        pieces = split_part(project_dir, part_id, body.boundaries, body.titles)
    except KeyError:
        raise HTTPException(404, f"Part '{part_id}' not found") from None
    except PartEditRejected as exc:
        raise _rejected(exc) from exc
    return {"parts": part_summaries(project_dir), "created": [piece.id for piece in pieces]}


@router.put("/parts/{part_id}/text")
async def replace_text(
    part_id: str,
    text: str | None = Form(None),
    file: UploadFile | None = File(None),
    project_dir: Path = Depends(get_project_dir),
):
    try:
        reason = edit_blocker(project_dir, part_id)
    except KeyError:
        raise HTTPException(404, f"Part '{part_id}' not found") from None
    if reason:
        raise _rejected(PartEditRejected(reason))
    content, origin = await _submitted_text(project_dir, file, text)
    try:
        record = replace_part_text(project_dir, part_id, content, origin=origin)
    except PartEditRejected as exc:
        raise _rejected(exc) from exc
    return {"part": record.model_dump(), "chapters": _chapters(content),
            "parts": part_summaries(project_dir)}


class RenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)


@router.patch("/parts/{part_id}")
def rename(part_id: str, body: RenameRequest, project_dir: Path = Depends(get_project_dir)):
    try:
        record = rename_part(project_dir, part_id, body.title)
    except KeyError:
        raise HTTPException(404, f"Part '{part_id}' not found") from None
    return {"part": record.model_dump()}


@router.get("/parts/{part_id}/page-flags")
def part_page_flags(part_id: str, root: Path = Depends(get_project_dir)):
    """Drawn pages whose artwork predates a later Story Bible or Cast edit."""
    from novel_to_comic.story_bible_edits import pages_drawn_before_edits
    from ..deps import get_part_dir

    return {"pages": pages_drawn_before_edits(get_part_dir(root, part_id))}


@router.delete("/parts/{part_id}")
def remove(part_id: str, project_dir: Path = Depends(get_project_dir)):
    try:
        delete_part(project_dir, part_id)
    except KeyError:
        raise HTTPException(404, f"Part '{part_id}' not found") from None
    except PartEditRejected as exc:
        raise _rejected(exc) from exc
    return {"parts": part_summaries(project_dir)}


class CombinedExportRequest(BaseModel):
    part_ids: list[str] = Field(min_length=1, max_length=500)
    format: Literal["pdf", "cbz"] = "pdf"


_COMBINED_NAME = re.compile(r"part_\d{4}-part_\d{4}-[0-9a-f]{16}\.(pdf|cbz)")


@router.post("/parts/export")
def export_parts(body: CombinedExportRequest, project_dir: Path = Depends(get_project_dir)):
    """Combine consecutive finished parts into one book file."""
    from novel_to_comic.combined_export import CombinedExportRejected, combined_export

    try:
        output = combined_export(project_dir, body.part_ids, body.format)
    except CombinedExportRejected as exc:
        raise HTTPException(409, {"code": "combined_export_rejected", "message": str(exc)}) from exc
    return {"file": output.name, "byte_size": output.stat().st_size}


@router.get("/parts/export/{name}")
def download_combined_export(name: str, project_dir: Path = Depends(get_project_dir)):
    if not _COMBINED_NAME.fullmatch(name):
        raise HTTPException(404, "Export not found")
    path = project_dir / "exports" / "combined" / name
    if not path.is_file():
        raise HTTPException(404, "Export not found")
    media = "application/pdf" if name.endswith(".pdf") else "application/vnd.comicbook+zip"
    return FileResponse(path, media_type=media, filename=name,
                        headers={"Cache-Control": "private, no-cache"})
