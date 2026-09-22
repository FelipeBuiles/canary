"""Owner publishing controls and allowlisted anonymous book reads."""

from pathlib import Path
import os
import html
import re
from typing import Literal
import io
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response, HTMLResponse

from novel_to_comic.artifact_lock import production_lock
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.target_artifacts import ArtifactMissing, ArtifactInvalid
from ..ratelimit import limiter, export_limit
from ..auth import get_current_user
from ..deps import get_project, get_project_dir, get_projects_dir
from ..deployment_status import require_ops_token
from .. import publications as store
from .. import showcase
from ..publication_bookend import bookend_image

router = APIRouter()
public_router = APIRouter()
ops_router = APIRouter(dependencies=[Depends(require_ops_token)])


def current(base: Path, book_id: str):
    if len(book_id) != 32 or any(c not in "0123456789abcdef" for c in book_id):
        raise HTTPException(404, "Book not available")
    bundled = showcase.find(book_id)
    if bundled:
        return bundled[0]
    result = store.read_json(store.root(base) / book_id / "current.json")
    if not result:
        raise HTTPException(404, "Book not available")
    return result



def page_directory(base: Path, book_id: str, version: str) -> Path:
    bundled = showcase.find(book_id)
    if bundled:
        return bundled[1]
    return store.root(base) / book_id / version


@router.get("/publication")
def owned(
    project_id: str,
    project=Depends(get_project_dir),
    user: str = Depends(get_current_user),
    base: Path = Depends(get_projects_dir),
):
    owner = store.read_json(store.owner_path(base, user, project_id))
    return (
        store.read_json(store.root(base) / owner["id"] / "current.json")
        if owner
        else None
    )


@router.post("/publication")
@limiter.limit(export_limit)
def publish(
    request: Request,
    body: store.PublicationInput,
    project_id: str,
    project=Depends(get_project),
    user: str = Depends(get_current_user),
    base: Path = Depends(get_projects_dir),
):
    directory, _config, state = project
    try:
        return store.publish(
            base,
            directory,
            user,
            project_id,
            body,
            StageRuntime("finish", state, directory),
        )
    except (ValueError, ArtifactMissing, ArtifactInvalid) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/publication")
def unpublish(
    project_id: str,
    project=Depends(get_project_dir),
    user: str = Depends(get_current_user),
    base: Path = Depends(get_projects_dir),
):
    with production_lock(store.root(base)):
        owner = store.read_json(store.owner_path(base, user, project_id))
        if owner:
            (store.root(base) / owner["id"] / "current.json").unlink(missing_ok=True)
    return {"status": "unpublished"}


@public_router.get("")
def featured(response: Response, base: Path = Depends(get_projects_dir)):
    response.headers["Cache-Control"] = "no-store"
    return [record for record, _directory in showcase.books()]


@public_router.get("/{book_id}")
def book(book_id: str, response: Response, base: Path = Depends(get_projects_dir)):
    response.headers["Cache-Control"] = "no-store"
    return current(base, book_id)


@public_router.get("/{book_id}/{version}/pages/{number}")
def page(
    book_id: str, version: str, number: int, base: Path = Depends(get_projects_dir)
):
    record = current(base, book_id)
    if version != record["version"] or number not in [
        page["number"] for page in record["pages"]
    ]:
        raise HTTPException(404, "Page not available")
    return FileResponse(
        page_directory(base, book_id, version) / f"{number}.jpg",
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@public_router.get("/{book_id}/download/{format}")
@limiter.limit(export_limit)
def download(
    book_id: str,
    format: Literal["pdf", "cbz"],
    request: Request,
    base: Path = Depends(get_projects_dir),
):
    import img2pdf
    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import Link

    record = current(base, book_id)
    directory = page_directory(base, book_id, record["version"])
    pages = [
        (directory / f"{page['number']}.jpg").read_bytes() for page in record["pages"]
    ]
    origin = os.environ.get(
        "SCENEWRIGHT_APP_URL", "https://app.scenewright.ink"
    ).rstrip("/")
    url = f"{origin}/signup?ref=book-{book_id}"
    pages.append(bookend_image(pages[0], url))
    if format == "cbz":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for index, data in enumerate(pages, 1):
                archive.writestr(f"page_{index:04d}.jpg", data)
        data = buffer.getvalue()
    else:
        data = img2pdf.convert(pages)
        writer = PdfWriter()
        writer.append(PdfReader(io.BytesIO(data)))
        last = writer.pages[-1]
        writer.add_annotation(
            len(writer.pages) - 1,
            Link(
                rect=(
                    0,
                    0,
                    float(last.mediabox.width),
                    float(last.mediabox.height),
                ),
                url=url,
            ),
        )
        buffer = io.BytesIO()
        writer.write(buffer)
        data = buffer.getvalue()
    return Response(
        data,
        media_type="application/pdf" if format == "pdf" else "application/zip",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="book.{format}"',
        },
    )


@ops_router.get("")
def list_publications(base: Path = Depends(get_projects_dir)):
    return [
        record
        for path in sorted(store.root(base).glob("*/current.json"))
        if (record := store.read_json(path))
    ]


def reader_html(book_id: str, base: Path, index: Path):
    """Crawler-visible metadata on the same URL the React reader uses."""
    try:
        record = current(base, book_id)
    except HTTPException as exc:
        if exc.status_code != 404:
            raise
        return HTMLResponse(
            index.read_text(), status_code=404, headers={"Cache-Control": "no-store"}
        )
    origin = os.environ.get(
        "SCENEWRIGHT_APP_URL", "https://app.scenewright.ink"
    ).rstrip("/")
    metadata = {
        "og:title": record["title"],
        "og:description": record["description"]
        or f"By {record['author']} · Read on Scenewright",
        "og:type": "book",
        "og:url": f"{origin}/read/{book_id}",
        "og:image": origin + record["pages"][0]["url"],
        "twitter:card": "summary_large_image",
    }
    document = index.read_text()
    document = re.sub(r"<title>.*?</title>", "", document, flags=re.S)
    document = re.sub(
        r'<meta\b[^>]*(?:property|name)=["\'](?:og:[^"\']+|twitter:[^"\']+)["\'][^>]*>',
        "",
        document,
        flags=re.I,
    )
    tags = f"<title>{html.escape(record['title'])} — Scenewright</title>"
    tags += "".join(
        f'<meta property="{key}" content="{html.escape(value, quote=True)}">'
        for key, value in metadata.items()
    )
    return HTMLResponse(
        document.replace("</head>", tags + "</head>"),
        headers={"Cache-Control": "no-store"},
    )


@public_router.get("/{book_id}/bookend")
@limiter.limit(export_limit)
def preview_bookend(
    book_id: str, request: Request, base: Path = Depends(get_projects_dir)
):
    record = current(base, book_id)
    first = page_directory(base, book_id, record["version"]) / f"{record['pages'][0]['number']}.jpg"
    origin = os.environ.get(
        "SCENEWRIGHT_APP_URL", "https://app.scenewright.ink"
    ).rstrip("/")
    return Response(
        bookend_image(first.read_bytes(), f"{origin}/signup?ref=book-{book_id}"),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )
