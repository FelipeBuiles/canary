"""Logging helpers for the web server."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

from fastapi import Request, Response
from rich.console import Console
from rich.logging import RichHandler

from novel_to_comic.server.env import bool_env
from novel_to_comic.server.sentry import configure_sentry
from novel_to_comic.server.telemetry import configure_telemetry


api_logger = logging.getLogger("canary.api")


def configure_logging() -> None:
    """Configure concise terminal logs for `pipeline serve`."""
    import sys

    level_name = os.environ.get("CANARY_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    show_time = bool_env("CANARY_LOG_SHOW_TIME", default=False)

    # Suppress verbose traceback frames from third-party libraries and venv
    suppress_list = [
        "httpx",
        "asyncio",
        "fastapi",
        "uvicorn",
        "starlette",
        "anyio",
        "click",
        "jinja2",
        "sqlalchemy",
        "pydantic",
        "http",
        "litellm",
    ]
    try:
        for path in sys.path:
            if "site-packages" in path or ".venv" in path:
                suppress_list.append(path)
    except Exception:
        pass

    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[
            RichHandler(
                console=Console(stderr=True),
                markup=True,
                rich_tracebacks=True,
                tracebacks_extra_lines=1,
                tracebacks_suppress=suppress_list,
                show_path=False,
                show_level=True,
                show_time=show_time,
            )
        ],
        force=True,
    )
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
    configure_telemetry()
    configure_sentry()


_STATIC_FILE_PATH_FRAGMENTS = (
    "/files/refs/",
    "/files/plates/",
    "/files/pages/",
    "/files/draw/",
)


def _should_log_request(request: Request, status_code: int, elapsed_ms: float) -> bool:
    path = request.url.path
    # Suppress noisy polling for asset files (auth failures, not-yet-generated, etc.)
    if any(fragment in path for fragment in _STATIC_FILE_PATH_FRAGMENTS):
        return False
    if status_code >= 400:
        return True
    if path.endswith("/events"):
        return False
    if path.endswith("/generation-jobs"):
        return False
    if path.endswith("/status"):
        return False
    if request.method != "GET" or elapsed_ms >= 1000:
        return True
    return False


async def request_log_middleware(
    request: Request,
    call_next: Callable[[Request], Response],
) -> Response:
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        api_logger.exception(
            "[bold red]API failed[/] %s [white]%s[/] elapsed=[bold]%.0fms[/]",
            request.method,
            request.url.path,
            elapsed_ms,
        )
        raise

    elapsed_ms = (time.perf_counter() - started) * 1000
    if _should_log_request(request, response.status_code, elapsed_ms):
        api_logger.info(
            "[bold magenta]API[/] %s [white]%s[/] -> [bold]%s[/] elapsed=%.0fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
    return response
