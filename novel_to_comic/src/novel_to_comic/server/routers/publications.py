"""Owner publishing controls and allowlisted anonymous book reads."""


from pathlib import Path
import os
import html
import json
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


# The curated showcase book linked from /examples/kaitlin-out-of-space
# (KAITLIN_EXAMPLE_BOOK_ID in web/src/lib/publicPages.ts).
KAITLIN_EXAMPLE_BOOK_ID = "df3a1b400a444815bddeca430360f0d9"


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
        "SCENEWRIGHT_APP_URL", "https://scenewright.ink"
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
                                   description="This book is not available.", path=f"/read/{book_id}",
                                   intro='<h1>Book unavailable</h1><p><a href="/">Return to Scenewright</a></p>', noindex=True)
        response.status_code = 404
        response.headers["X-Robots-Tag"] = "noindex"
        return response
    origin = public_origin()
    intro = f"<h1>{html.escape(record['title'])}</h1><p>By {html.escape(record['author'])} · {len(record['pages'])} comic pages</p><p>{html.escape(record['description'])}</p>"
    intro += '<p>Read this complete comic adaptation, inspect the preview pages, or open the interactive reader. Made with Scenewright, an AI-assisted comic studio for authors.</p>'
    intro += '<div class="grid gap-4 sm:grid-cols-3">' + ''.join(
        f'<figure><a href="{html.escape(page["url"], quote=True)}"><img src="{html.escape(page["url"], quote=True)}" width="{page["width"]}" height="{page["height"]}" alt="{html.escape(record["title"], quote=True)}, page {page["number"]}" loading="{"eager" if page["number"] == 1 else "lazy"}" style="max-width:100%;height:auto"></a><figcaption>Page {page["number"]}</figcaption></figure>'
        for page in record["pages"][:3]) + '</div>'
    credit = record.get("source_credit")
    if credit:
        intro += f'<p>Source: <a href="{html.escape(credit["source_url"], quote=True)}">{html.escape(credit["title"])}</a> by {html.escape(credit["author"])}. License: <a href="{html.escape(credit["license_url"], quote=True)}">{html.escape(credit["license"])}</a>.</p>'
    if book_id == KAITLIN_EXAMPLE_BOOK_ID:
        intro += '<p><a href="/samples?story=kaitlin-out-of-space">Read the original Kaitlin Out of Space story and its CC0 source license</a> · <a href="/examples/kaitlin-out-of-space">Compare the annotated adaptation example</a></p>'
    intro += '<p>Generated art and lettering can need correction. Review the sequence at full size before adapting your own scene. <a href="/how-it-works">How it works</a> · <a href="/samples">Source stories</a> · <a href="/signup">Create your own comic</a></p>'
    schema = {"@context": "https://schema.org", "@type": "Book", "name": record["title"],
              "author": {"@type": "Person", "name": record["author"]}, "description": record["description"],
              "url": origin + f"/read/{book_id}", "numberOfPages": len(record["pages"]), "image": origin + record["pages"][0]["url"]}
    if credit:
        schema.update(isBasedOn=credit["source_url"], license=credit["license_url"])
    return public_document(
        index, title=f"{record['title']} — Scenewright",
        description=record["description"] or f"By {record['author']} · Read on Scenewright",
        path=f"/read/{book_id}", image=origin + record["pages"][0]["url"], kind="book",
        intro=intro, schema=schema, bootstrap={"book": record},
    )


def public_origin() -> str:
    return os.environ.get("SCENEWRIGHT_PUBLIC_URL", "https://scenewright.ink").rstrip("/")


def public_document(index: Path, *, title: str, description: str, path: str,
                    image: str | None = None, kind: str = "website", intro: str = "",
                    noindex: bool = False, schema: dict | None = None, bootstrap: dict | None = None):
    document = index.read_text()
    document = re.sub(r"<title\b[^>]*>.*?</title>", "", document, flags=re.S | re.I)
    document = re.sub(
        r'<meta\b[^>]*(?:property|name)=["\'](?:description|robots|og:[^"\']+|twitter:[^"\']+)["\'][^>]*>',
        "", document, flags=re.I,
    )
    document = re.sub(r'<link\b[^>]*rel=["\']canonical["\'][^>]*>', "", document, flags=re.I)
    url = public_origin() + path
    default_image = image is None
    image = image or public_origin() + "/marketing/scenewright-social.png"
    metadata = {"description": description, "robots": "noindex, follow" if noindex else "index, follow",
                "og:site_name": "Scenewright", "og:title": title, "og:description": description,
                "og:type": kind, "og:url": url, "twitter:title": title,
                "twitter:description": description, "twitter:card": "summary_large_image" if image else "summary"}
    metadata.update({"og:image": image, "twitter:image": image,
                     "og:image:alt": title, "twitter:image:alt": title})
    if default_image:
        metadata.update({"og:image:width": "1200", "og:image:height": "630"})
    tags = f"<title>{html.escape(title)}</title><link rel=\"canonical\" href=\"{html.escape(url, quote=True)}\">"
    tags += "".join(f'<meta {"property" if key.startswith("og:") else "name"}="{key}" content="{html.escape(value, quote=True)}">'
                    for key, value in metadata.items())
    if schema:
        tags += f'<script id="public-schema" type="application/ld+json">{_public_json(schema)}</script>'
    document = document.replace("</head>", tags + "</head>")
    if intro:
        document = re.sub(r'<div id=["\']root["\']></div>', lambda _: '<div id="root"><main class="server-intro mx-auto max-w-[1100px] space-y-6 px-5 py-12 font-body leading-7">' + intro + '</main></div>', document)
    if bootstrap:
        document = document.replace('</body>', f'<script id="public-bootstrap" type="application/json">{_public_json(bootstrap)}</script></body>')
    return HTMLResponse(document, headers={"Cache-Control": "no-store", **({"X-Robots-Tag": "noindex, follow"} if noindex else {})})


def _public_json(value: dict) -> str:
    # Public text must not terminate a script element or become executable HTML.
    return json.dumps(value, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def samples_html(index: Path, story: str | None = None):
    from novel_to_comic import sample_library
    from urllib.parse import quote
    entries = sample_library.catalog() + sample_library.archive_catalog()
    entry = next((entry for entry in entries if entry["code"] == story), None)
    title = f"{entry['title']} by {entry['author']} — Scenewright" if entry else "Sample stories — Scenewright"
    description = (entry.get("description") or f"Read {entry['title']} by {entry['author']} in the Scenewright sample library.") if entry else "Explore selected stories, authors and themes in the Scenewright sample library."
    path = f"/samples?story={quote(entry['code'])}" if entry else "/samples"
    intro = f"<h1>{html.escape(title)}</h1><p>{html.escape(description)}</p>"
    bootstrap = {"stories": sample_library.catalog()}
    schema = None
    if entry:
        if sample := sample_library.find(entry["code"]):
            text = sample[1]
            body = re.sub(r'^.*\nBy [^\n]+\n+', '', text).strip()
            intro += '<article>' + ''.join(f'<p style="white-space:pre-line">{html.escape(paragraph)}</p>' for paragraph in re.split(r'\n\s*\n', body)) + '</article>'
            bootstrap["story"] = {"code": entry["code"], "text": text}
        else:
            bootstrap["stories"].append(entry)
        for key in ("source_note", "rights_note", "content_note"):
            if entry.get(key):
                intro += f'<p>{html.escape(entry[key])}</p>'
        for key, label in (("source_url", "Original source"), ("license_url", entry.get("license", "License"))):
            if entry.get(key):
                intro += f'<p><a href="{html.escape(entry[key], quote=True)}">{html.escape(label)}</a></p>'
        intro += '<p><a href="/samples">Browse the sample library</a> · <a href="/how-it-works">How to adapt a story</a></p>'
        schema = {"@context": "https://schema.org", "@type": "CreativeWork", "name": entry["title"], "description": description,
                  "author": {"@type": "Person", "name": entry["author"]}, "url": public_origin() + path}
        if entry.get("source_url"):
            schema["isBasedOn"] = entry["source_url"]
        if entry.get("license_url"):
            schema["license"] = entry["license_url"]
    if not entry:
        intro += '<p>Read a complete licensed source story before starting an adaptation. Each curated entry identifies its author, source, and license. Classic archive rights vary by work and jurisdiction.</p><ul>' + "".join(f'<li><a href="/samples?story={quote(item["code"])}">{html.escape(item["title"])}</a> by {html.escape(item["author"])} — {html.escape(item.get("description", ""))}</li>' for item in sample_library.catalog()) + "</ul>"
    return public_document(index, title=title, description=description, path=path, intro=intro, schema=schema, bootstrap=bootstrap)


def sitemap_document():
    from novel_to_comic import sample_library
    from urllib.parse import quote
    # Discovery is deliberately curated; owner publications remain direct-link public.
    paths = ["/", "/es", "/fr", "/how-it-works", "/pricing", "/guides/turn-a-novel-into-a-comic",
             "/examples/kaitlin-out-of-space", "/about", "/legal/terms", "/legal/privacy", "/legal/acceptable-use", "/samples"]
    paths += [f"/read/{record['id']}" for record, _ in showcase.books()]
    paths += [f"/samples?story={quote(entry['code'])}" for entry in sample_library.catalog()]
    body = '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    body += "".join(f"<url><loc>{html.escape(public_origin() + path)}</loc></url>" for path in paths)
    return Response(body + "</urlset>", media_type="application/xml")


def robots_document():
    return Response("User-agent: *\nDisallow: /api/\nAllow: /api/public/books$\nAllow: /api/public/books/\nDisallow: /project/\nDisallow: /backoffice\n"
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
        "SCENEWRIGHT_APP_URL", "https://scenewright.ink"
    ).rstrip("/")
    return Response(
        bookend_image(first.read_bytes(), f"{origin}/signup?ref=book-{book_id}"),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )
