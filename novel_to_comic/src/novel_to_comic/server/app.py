"""FastAPI application factory for the web dashboard."""

import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from novel_to_comic.assembly.html_renderer import FONTS_DIR

from .generation_jobs import generation_worker
from .logging import request_log_middleware
from .routers import config, export, pages, pipeline, projects, stages, styles


@asynccontextmanager
async def _lifespan(app: FastAPI):
    import logging
    from novel_to_comic.usage import audit_pricing
    missing = audit_pricing()
    if missing:
        logging.getLogger(__name__).warning(
            "Models missing from pricing.yaml (cost tracking will be $0 for these): %s",
            ", ".join(missing),
        )

    worker_count = max(1, int(os.environ.get("CANARY_GENERATION_WORKERS", "5")))
    app.state.generation_worker_tasks = [
        asyncio.create_task(generation_worker(app))
        for _ in range(worker_count)
    ]
    yield
    for task in app.state.generation_worker_tasks:
        task.cancel()
    await asyncio.gather(*app.state.generation_worker_tasks, return_exceptions=True)


def create_app(projects_dir: Path, dev: bool = False) -> FastAPI:
    app = FastAPI(title="Canary — Novel to Comic", lifespan=_lifespan)
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

    # Routers
    app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
    app.include_router(
        pipeline.router,
        prefix="/api/projects/{project_name}",
        tags=["pipeline"],
    )
    app.include_router(
        pages.router,
        prefix="/api/projects/{project_name}",
        tags=["pages"],
    )
    app.include_router(
        export.router,
        prefix="/api/projects/{project_name}/export",
        tags=["export"],
    )
    app.include_router(
        config.router,
        prefix="/api/projects/{project_name}/config",
        tags=["config"],
    )
    app.include_router(
        stages.router,
        prefix="/api/projects/{project_name}",
        tags=["stages"],
    )
    app.include_router(
        styles.router,
        prefix="/api/projects/{project_name}",
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
