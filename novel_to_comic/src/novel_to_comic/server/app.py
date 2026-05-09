"""FastAPI application factory for the web dashboard."""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from novel_to_comic.assembly.html_renderer import FONTS_DIR
from novel_to_comic.model_costs import DEFAULT_COST_MAP_PATH, refresh_litellm_cost_cache
from novel_to_comic.usage import audit_pricing

from .generation_jobs import generation_worker
from .logging import request_log_middleware
from .routers import billing, config, credits, export, pages, pipeline, projects, stages, styles

log = logging.getLogger(__name__)


def _pricing_refresh_ttl_days() -> int:
    raw = os.environ.get("PULP_PRICING_REFRESH_DAYS", "7")
    try:
        return max(0, int(raw))
    except ValueError:
        log.warning("Invalid PULP_PRICING_REFRESH_DAYS=%r; using 7", raw)
        return 7


def _pricing_cache_age_seconds(cost_map_path: Path = DEFAULT_COST_MAP_PATH) -> float:
    try:
        return time.time() - cost_map_path.stat().st_mtime
    except FileNotFoundError:
        return float("inf")


def _refresh_pricing_if_stale(cost_map_path: Path = DEFAULT_COST_MAP_PATH) -> None:
    ttl_days = _pricing_refresh_ttl_days()
    age_seconds = _pricing_cache_age_seconds(cost_map_path)
    if age_seconds < ttl_days * 86400:
        return
    try:
        meta = refresh_litellm_cost_cache(output_path=cost_map_path, timeout_seconds=10)
        log.info("Refreshed LiteLLM cost cache: %s", meta)
    except Exception as exc:
        log.warning("LiteLLM cost cache refresh failed; using on-disk file: %s", exc)


def _audit_pricing_at_startup() -> None:
    missing = audit_pricing()
    if not missing:
        return
    msg = f"Pricing entries missing for: {', '.join(missing)}"
    env = (os.environ.get("CANARY_ENV") or os.environ.get("ENV") or "dev").lower()
    if env == "production":
        raise RuntimeError(msg)
    log.warning(msg)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    _audit_pricing_at_startup()
    app.state.pricing_refresh_task = asyncio.create_task(
        asyncio.to_thread(_refresh_pricing_if_stale)
    )

    async def _release_stale_reservations():
        from .db import get_db
        from .credits import release_all_stale_reservations
        try:
            released = await asyncio.to_thread(release_all_stale_reservations, get_db())
            if released:
                log.info("Released %d stale credit reservation(s) from previous server run", released)
        except Exception as exc:
            log.warning("Could not clean up stale credit reservations on startup: %s", exc)

    asyncio.create_task(_release_stale_reservations())

    worker_count = max(1, int(os.environ.get("CANARY_GENERATION_WORKERS", "5")))
    app.state.generation_worker_tasks = [
        asyncio.create_task(generation_worker(app))
        for _ in range(worker_count)
    ]
    yield
    # Close shared httpx pool used by ai/client.py
    from novel_to_comic.ai.client import _http
    await _http.aclose()
    if not app.state.pricing_refresh_task.done():
        app.state.pricing_refresh_task.cancel()
    for task in app.state.generation_worker_tasks:
        task.cancel()
    await asyncio.gather(
        app.state.pricing_refresh_task,
        *app.state.generation_worker_tasks,
        return_exceptions=True,
    )


def create_app(projects_dir: Path, dev: bool = False) -> FastAPI:
    app = FastAPI(title="Pulp", lifespan=_lifespan)
    app.middleware("http")(request_log_middleware)

    # Shared state for SSE streaming and concurrency control
    app.state.projects_dir = projects_dir
    app.state.event_queues: dict[str, asyncio.Queue] = {}
    app.state.running_tasks: dict[str, asyncio.Task] = {}
    app.state.style_tasks: dict[str, asyncio.Task] = {}
    app.state.generation_semaphore = asyncio.Semaphore(1)
    app.state.light_generation_semaphore = asyncio.Semaphore(5)
    app.state.light_generation_semaphores: dict[int, asyncio.Semaphore] = {
        5: app.state.light_generation_semaphore,
    }
    app.state.generation_queue: asyncio.Queue = asyncio.Queue()
    app.state.generation_jobs = {}
    app.state.generation_job_sequence = 1
    app.state.generation_job_timeout_seconds = max(
        1,
        int(os.environ.get("CANARY_GENERATION_JOB_TIMEOUT_SECONDS", "900")),
    )

    # CORS for Vite dev server
    if dev:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["http://localhost:5173"],
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/api/health", tags=["meta"])
    def health():
        return {"status": "ok"}

    # Routers
    app.include_router(credits.router, prefix="/api/credits", tags=["credits"])
    app.include_router(billing.router, prefix="/api/billing", tags=["billing"])
    app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(
        pipeline.router,
        prefix="/api/projects/{project_id}",
        tags=["pipeline"],
    )
    app.include_router(
        pages.router,
        prefix="/api/projects/{project_id}",
        tags=["pages"],
    )
    app.include_router(
        export.router,
        prefix="/api/projects/{project_id}/export",
        tags=["export"],
    )
    app.include_router(
        config.router,
        prefix="/api/projects/{project_id}/config",
        tags=["config"],
    )
    app.include_router(
        stages.router,
        prefix="/api/projects/{project_id}",
        tags=["stages"],
    )
    app.include_router(
        styles.router,
        prefix="/api/projects/{project_id}",
        tags=["styles"],
    )

    # Serve bundled fonts
    app.mount("/static/fonts", StaticFiles(directory=str(FONTS_DIR)), name="fonts")

    # In production, serve the built React app
    if not dev:
        dist = Path(__file__).parent.parent.parent.parent.parent / "web" / "dist"
        if dist.is_dir():
            app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app
