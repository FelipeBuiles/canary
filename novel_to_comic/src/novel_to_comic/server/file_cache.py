"""Private, revalidated image responses for authenticated project files.

Asset URLs can be reused for new content (a redraw writes the same path; a
restarted Adapt reuses a page/revision), so browsers keep these files but
must revalidate each one. Starlette's ``FileResponse`` sets an ETag but never
answers ``If-None-Match``, which turned every revalidation into a full image
download. A matching validator here returns 304 without reading the file, and
every check still passes through project authorization first.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import FileResponse

PRIVATE_REVALIDATE = "private, no-cache"


def file_etag(path: Path) -> str:
    stat = path.stat()
    return f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'


def not_modified(request: Request | None, etag: str) -> Response | None:
    """A 304 when the browser already holds ``etag``; otherwise ``None``."""
    header = request.headers.get("if-none-match", "") if request is not None else ""
    candidates = {tag.strip().removeprefix("W/") for tag in header.split(",")}
    if "*" in candidates or etag in candidates:
        return Response(status_code=304, headers={"Cache-Control": PRIVATE_REVALIDATE, "ETag": etag})
    return None


def private_file_response(request: Request, path: Path, media_type: str) -> Response:
    """Serve ``path`` privately, answering a current validator with 304."""
    etag = file_etag(path)
    return not_modified(request, etag) or FileResponse(
        path, media_type=media_type, headers={"Cache-Control": PRIVATE_REVALIDATE, "ETag": etag},
    )
