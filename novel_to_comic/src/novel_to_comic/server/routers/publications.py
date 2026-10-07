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
owner_router = APIRouter()
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
@owner_router.get("/publication")
def owned(
    project_id: str,
    project=Depends(get_project_dir),
    user: str = Depends(get_current_user),
    base: Path = Depends(get_projects_dir),
):
    return store.owned_record(base, user, project_id)


@router.post("/publication", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
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
        result = store.publish(
            base,
            directory,
            user,
            project_id,
            body,
            StageRuntime("finish", state, directory),
        )
        return result | {key: value for key, value in store.owned_record(base, user, project_id).items() if key.startswith("source_part_")}
    except store.PublicationReplacementRequired as exc:
        raise HTTPException(409, {"code": "publication_replacement_required", "message": str(exc), "admitted": False}) from exc
    except (ValueError, ArtifactMissing, ArtifactInvalid) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.delete("/publication", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
@owner_router.delete("/publication", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
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


def language_pages(record: dict, locale: str | None) -> list[dict]:
    """The frozen page list for one published language; the default is the primary."""
    if locale is None or locale == record.get("locale"):
        return record["pages"]
    for translation in record.get("translations", ()):
        if translation["locale"] == locale:
            return translation["pages"]
    raise HTTPException(404, "Language not available")


@public_router.get("/{book_id}/{version}/locales/{locale}/pages/{number}")
def translated_page(
    book_id: str,
    version: str,
    locale: str,
    number: int,
    base: Path = Depends(get_projects_dir),
):
    record = current(base, book_id)
    if (
        version != record["version"]
        or locale == record.get("locale")
        or number not in [page["number"] for page in language_pages(record, locale)]
    ):
        raise HTTPException(404, "Page not available")
    return FileResponse(
        page_directory(base, book_id, version) / locale / f"{number}.jpg",
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@public_router.get("/{book_id}/download/{format}")
@limiter.limit(export_limit)
def download(
    book_id: str,
    format: Literal["pdf", "cbz"],
    request: Request,
    locale: str | None = None,
    base: Path = Depends(get_projects_dir),
):
    import img2pdf
    from pypdf import PdfReader, PdfWriter
    from pypdf.annotations import Link

    record = current(base, book_id)
    directory = page_directory(base, book_id, record["version"])
    if locale is not None and locale != record.get("locale"):
        language_pages(record, locale)  # 404 unless this language was published.
        directory = directory / locale
    pages = [
        (directory / f"{page['number']}.jpg").read_bytes()
        for page in language_pages(record, locale)
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
        response = public_document(index, title="Book unavailable — Scenewright",
                                   description="This book is not available.", path=f"/read/{book_id}")
        response.status_code = 404
        response.headers["X-Robots-Tag"] = "noindex"
        return response
    origin = public_origin()
    return public_document(
        index, title=f"{record['title']} — Scenewright",
        description=record["description"] or f"By {record['author']} · Read on Scenewright",
        path=f"/read/{book_id}", image=origin + record["pages"][0]["url"], kind="book",
        intro=f"<h1>{html.escape(record['title'])}</h1><p>{html.escape(record['author'])}</p>"
              f"<p>{html.escape(record['description'])}</p>",
    )


def public_origin() -> str:
    return os.environ.get("SCENEWRIGHT_PUBLIC_URL", "https://scenewright.ink").rstrip("/")


def public_document(index: Path, *, title: str, description: str, path: str,
                    image: str | None = None, kind: str = "website", intro: str = ""):
    document = index.read_text()
    document = re.sub(r"<title\b[^>]*>.*?</title>", "", document, flags=re.S | re.I)
    document = re.sub(
        r'<meta\b[^>]*(?:property|name)=["\'](?:description|og:[^"\']+|twitter:[^"\']+)["\'][^>]*>',
        "", document, flags=re.I,
    )
    document = re.sub(r'<link\b[^>]*rel=["\']canonical["\'][^>]*>', "", document, flags=re.I)
    url = public_origin() + path
    metadata = {"description": description, "og:title": title, "og:description": description,
                "og:type": kind, "og:url": url, "twitter:title": title,
                "twitter:description": description, "twitter:card": "summary_large_image" if image else "summary"}
    if image:
        metadata.update({"og:image": image, "twitter:image": image})
    tags = f"<title>{html.escape(title)}</title><link rel=\"canonical\" href=\"{html.escape(url, quote=True)}\">"
    tags += "".join(f'<meta {"property" if key.startswith("og:") else "name"}="{key}" content="{html.escape(value, quote=True)}">'
                    for key, value in metadata.items())
    document = document.replace("</head>", tags + "</head>")
    if intro:
        document = document.replace('<div id="root"></div>', f'<div id="root"><main>{intro}</main></div>')
    return HTMLResponse(document, headers={"Cache-Control": "no-store"})


def samples_html(index: Path, story: str | None = None):
    from novel_to_comic import sample_library
    from urllib.parse import quote
    entries = sample_library.catalog() + sample_library.archive_catalog()
    entry = next((entry for entry in entries if entry["code"] == story), None)
    title = f"{entry['title']} by {entry['author']} — Scenewright" if entry else "Sample stories — Scenewright"
    description = (entry.get("description") or f"Read {entry['title']} by {entry['author']} in the Scenewright sample library.") if entry else "Explore selected stories, authors and themes in the Scenewright sample library."
    path = f"/samples?story={quote(entry['code'])}" if entry else "/samples"
    intro = f"<h1>{html.escape(title)}</h1><p>{html.escape(description)}</p>"
    if not entry:
        intro += "<ul>" + "".join(f'<li><a href="/samples?story={quote(item["code"])}">{html.escape(item["title"])}</a></li>' for item in sample_library.catalog()) + "</ul>"
    return public_document(index, title=title, description=description, path=path, intro=intro)


def sitemap_document():
    from novel_to_comic import sample_library
    from urllib.parse import quote
    # Discovery is deliberately curated; owner publications remain direct-link public.
    paths = ["/", "/samples"]
    paths += [f"/read/{record['id']}" for record, _ in showcase.books()]
    paths += [f"/samples?story={quote(entry['code'])}" for entry in sample_library.catalog()]
    body = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    body += "".join(f"<url><loc>{html.escape(public_origin() + path)}</loc></url>" for path in paths)
    return Response(body + "</urlset>", media_type="application/xml")


def robots_document():
    return Response("User-agent: *\nDisallow: /api/\nDisallow: /project/\nDisallow: /backoffice\n"
                    "Disallow: /account\nDisallow: /credits\nDisallow: /auth/\n"
                    f"Sitemap: {public_origin()}/sitemap.xml\n", media_type="text/plain")


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
