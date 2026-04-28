"""Logging helpers for the web server."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable

from fastapi import Request, Response
from rich.console import Console
from rich.logging import RichHandler

from novel_to_comic.server.telemetry import configure_telemetry


api_logger = logging.getLogger("canary.api")


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def configure_logging() -> None:
    """Configure concise terminal logs for `pipeline serve`."""
    level_name = os.environ.get("CANARY_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    show_time = _bool_env("CANARY_LOG_SHOW_TIME", default=False)
    logging.basicConfig(
        level=level,
        format="%(message)s",
        handlers=[
            RichHandler(
                console=Console(stderr=True),
                markup=True,
                rich_tracebacks=True,
                show_path=False,
                show_level=True,
                show_time=show_time,
            )
        ],
        force=True,
    )
    logging.getLogger("uvicorn.access").disabled = True
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("google_genai").setLevel(logging.WARNING)
    logging.getLogger("google_genai._api_client").setLevel(logging.WARNING)
    configure_telemetry()


def _should_log_request(request: Request, status_code: int, elapsed_ms: float) -> bool:
    path = request.url.path
    # Suppress expected 404s when the frontend polls for not-yet-generated asset files
    if status_code == 404 and ("/files/refs/" in path or "/files/plates/" in path):
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
