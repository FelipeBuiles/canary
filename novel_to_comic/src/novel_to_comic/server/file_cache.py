"""Private, revalidated image responses for authenticated project files.

Asset URLs can be reused for new content (a redraw writes the same path; a
restarted Adapt reuses a page/revision), so browsers keep these files but
must revalidate each one. Starlette's ``FileResponse`` sets an ETag but never
answers ``If-None-Match``, which turned every revalidation into a full image
download. A matching validator here returns 304 without reading the file, and
every check still passes through project authorization first.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import Request, Response
from fastapi.responses import FileResponse

PRIVATE_REVALIDATE = "private, no-cache"
# For URLs that carry their content's version: the browser shows its copy
# without asking. Only the private browser cache may keep it.
PRIVATE_IMMUTABLE = "private, max-age=31536000, immutable"
_sha256_by_stat: dict[tuple[str, int, int], str] = {}


def asset_version(path: Path) -> str:
    """The token a versioned asset URL carries (``?v=``) for this file's bytes."""
    stat = path.stat()
    return f"{stat.st_mtime_ns:x}-{stat.st_size:x}"


def file_etag(path: Path) -> str:
    return f'"{asset_version(path)}"'


def versioned_cache_control(request: Request | None, version: str) -> str:
    """Immutable only when the URL names the bytes served; any other URL revalidates."""
    requested = request.query_params.get("v") if request is not None else None
    return PRIVATE_IMMUTABLE if requested == version else PRIVATE_REVALIDATE


def file_sha256(path: Path) -> str:
    """Content hash, recomputed only when the file's size or mtime changes."""
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    digest = _sha256_by_stat.get(key)
    if digest is None:
        if len(_sha256_by_stat) > 4096:
            _sha256_by_stat.clear()
        digest = _sha256_by_stat[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest


def not_modified(
    request: Request | None, etag: str, cache_control: str = PRIVATE_REVALIDATE,
) -> Response | None:
    """A 304 when the browser already holds ``etag``; otherwise ``None``."""
    header = request.headers.get("if-none-match", "") if request is not None else ""
    candidates = {tag.strip().removeprefix("W/") for tag in header.split(",")}
    if "*" in candidates or etag in candidates:
        return Response(status_code=304, headers={"Cache-Control": cache_control, "ETag": etag})
    return None


def private_file_response(
    request: Request, path: Path, media_type: str, version: str | None = None,
) -> Response:
    """Serve ``path`` privately, answering a current validator with 304.

    ``version`` is the token a current URL for this response carries; a match
    lets the browser keep the file without asking again.
    """
    etag = file_etag(path)
    cache = versioned_cache_control(request, version) if version else PRIVATE_REVALIDATE
    return not_modified(request, etag, cache) or FileResponse(
        path, media_type=media_type, headers={"Cache-Control": cache, "ETag": etag},
    )
