"""FastAPI application factory for the web dashboard."""

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from novel_to_comic.assembly.html_renderer import FONTS_DIR

from .routers import config, export, pages, pipeline, projects


def create_app(projects_dir: Path, dev: bool = False) -> FastAPI:
    app = FastAPI(title="Canary — Novel to Comic")

    # Shared state for SSE streaming and concurrency control
    app.state.projects_dir = projects_dir
    app.state.event_queues: dict[str, asyncio.Queue] = {}
    app.state.running_tasks: dict[str, asyncio.Task] = {}

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

    # Serve bundled fonts
    app.mount("/static/fonts", StaticFiles(directory=str(FONTS_DIR)), name="fonts")

    # In production, serve the built React app
    if not dev:
        dist = Path(__file__).parent.parent.parent.parent.parent / "web" / "dist"
        if dist.is_dir():
            app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")

    return app
