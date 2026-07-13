"""FastAPI application factory for the web dashboard."""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles

from novel_to_comic.assembly.html_renderer import FONTS_DIR
from novel_to_comic.model_costs import DEFAULT_COST_MAP_PATH, refresh_litellm_cost_cache
from novel_to_comic.usage import audit_pricing

from .generation_jobs import generation_worker
from .logging import request_log_middleware
from .ratelimit import configure_rate_limiting
from .sentry import configure_sentry
from .routers import (
    billing,
    config,
    credits,
    export,
    labs,
    pages,
    pipeline,
    projects,
    stages,
    styles,
)


class SPAStaticFiles(StaticFiles):
    """Static files that fall back to ``index.html`` for unknown routes.

    The React app uses client-side routing (e.g. ``/login``, ``/project/123``);
    those paths exist only in the browser, not as files on disk. A plain
    ``StaticFiles(html=True)`` mount returns ``{"detail":"Not Found"}`` for any
    such path, breaking deep links and refreshes. Here we catch the 404 for
    non-asset requests and serve ``index.html`` so the client router can take
    over. Real missing assets (``*.js``, ``*.css``, …) still 404 so broken
    links surface instead of silently returning the HTML shell.
    """

    # Extensions that should always be served as real files (or 404). Anything
    # without one of these is treated as a client-side route.
    _ASSET_SUFFIXES = frozenset(
        {".js", ".mjs", ".css", ".map", ".html", ".htm", ".json", ".txt",
         ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".avif",
         ".woff", ".woff2", ".ttf", ".eot", ".otf", ".wasm"}
    )

    async def get_response(self, path: str, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404:
                raise
            # Real assets (.js/.css/…) must 404 so broken links surface, and
            # API paths must never get the HTML shell — clients expect JSON.
            path_lc = path.lower()
            if (
                any(path_lc.endswith(suf) for suf in self._ASSET_SUFFIXES)
                or path_lc.startswith("api/")
            ):
                raise
            # Looks like a client-side route — serve the SPA shell so the
            # browser's history/router can render it.
            return await super().get_response("index.html", scope)
log = logging.getLogger(__name__)


def _labs_enabled() -> bool:
    """Feature flag for the Labs experimentation router.

    Defaults OFF: Labs is an image-model experimentation surface that bypasses
    the credit system (it bills provider quota directly to operator keys), so
    it must not ship enabled by default. Set ``CANARY_LABS_ENABLED=true`` to
    mount the router for local development or an internal deployment."""
    raw = os.environ.get("CANARY_LABS_ENABLED", "false").strip().lower()
    return raw not in {"0", "false", "no", "off"}


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


def _readiness_result() -> tuple[bool, dict[str, str]]:
    """Check production dependencies and return an HTTP-readiness result.

    Local development may intentionally run without Supabase or LiteLLM. A
    production process must never report ready when either dependency is
    missing or unreachable.
    """
    checks: dict[str, str] = {}
    ok = True
    env = (os.environ.get("CANARY_ENV") or os.environ.get("ENV") or "dev").lower()
    production = env == "production"

    supabase_values = (
        os.environ.get("SUPABASE_URL", "").strip(),
        os.environ.get("SUPABASE_SECRET_KEY", "").strip(),
    )
    if all(supabase_values):
        try:
            from .db import get_db

            get_db().table("projects").select("id").limit(1).execute()
            checks["supabase"] = "ok"
        except Exception as exc:  # noqa: BLE001 - surfaced to the probe payload
            ok = False
            checks["supabase"] = f"error: {type(exc).__name__}"
    elif production or any(supabase_values):
        ok = False
        checks["supabase"] = "error: missing configuration"
    else:
        checks["supabase"] = "skipped"

    litellm_values = (
        os.environ.get("LITELLM_BASE_URL", "").strip(),
        os.environ.get("LITELLM_API_KEY", "").strip(),
    )
    if all(litellm_values):
        import httpx

        try:
            with httpx.Client(timeout=2.0) as client:
                response = client.get(
                    f"{litellm_values[0].rstrip('/')}/health/liveliness",
                    headers={"Authorization": f"Bearer {litellm_values[1]}"},
                )
                response.raise_for_status()
            checks["litellm"] = "ok"
        except Exception as exc:  # noqa: BLE001 - surfaced to the probe payload
            ok = False
            checks["litellm"] = f"error: {type(exc).__name__}"
    elif production or any(litellm_values):
        ok = False
        checks["litellm"] = "error: missing configuration"
    else:
        checks["litellm"] = "skipped"

    return ok, checks


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Initialise Sentry first so it can capture startup errors (e.g. pricing
    # audit failures). No-op without SENTRY_DSN.
    configure_sentry()
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
                log.info(
                    "Released %d stale credit reservation(s) from previous server run",
                    released,
                )
        except Exception as exc:
            log.warning(
                "Could not clean up stale credit reservations on startup: %s", exc
            )

    asyncio.create_task(_release_stale_reservations())

    worker_count = max(1, int(os.environ.get("CANARY_GENERATION_WORKERS", "5")))
    app.state.generation_worker_tasks = [
        asyncio.create_task(generation_worker(app)) for _ in range(worker_count)
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
    app = FastAPI(title="Scenewright", lifespan=_lifespan)
    app.middleware("http")(request_log_middleware)
    # Defense-in-depth body-size cap on every non-exempt route. Runs before
    # route handlers so an oversized JSON POST is rejected before any work.
    from .body_limit import body_size_limit_middleware

    app.middleware("http")(body_size_limit_middleware)
    # Trusted host validation — only added when explicitly configured. Set
    # CANARY_ALLOWED_HOSTS to a comma-separated list (e.g. "scenewright.ink,
    # www.scenewright.ink"). Stripe redirects have a separate trusted-origin
    # contract in billing.py; this middleware protects Host-based URL handling.
    allowed_hosts_raw = os.environ.get("CANARY_ALLOWED_HOSTS", "").strip()
    if allowed_hosts_raw:
        allowed_hosts = [h.strip() for h in allowed_hosts_raw.split(",") if h.strip()]
        if allowed_hosts:
            app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)
    configure_rate_limiting(app)

    # Shared state for SSE streaming and concurrency control
    from .generation_jobs import (
        get_global_queue,
        get_global_semaphore,
        _global_jobs,
        _global_light_semaphores,
    )

    app.state.projects_dir = projects_dir
    app.state.event_queues: dict[str, asyncio.Queue] = {}
    app.state.running_tasks: dict[str, asyncio.Task] = {}
    # Per-project in-flight panel map for the draw stage. Maintained from
    # panel_start / panel_done events (see _wrap_on_event in pipeline.py).
    # Not persisted — if the server restarts, nothing is in flight.
    app.state.draw_in_flight: dict[str, list[dict]] = {}
    app.state.style_tasks: dict[str, asyncio.Task] = {}
    app.state.generation_semaphore = get_global_semaphore()
    app.state.light_generation_semaphore = asyncio.Semaphore(5)
    app.state.light_generation_semaphores = _global_light_semaphores
    app.state.light_generation_semaphores[5] = app.state.light_generation_semaphore
    app.state.generation_queue = get_global_queue()
    app.state.generation_jobs = _global_jobs
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
        # Liveness: always ok and cheap. Never depend on external services here —
        # a slow dependency must not make the load balancer kill a healthy instance.
        return {"status": "ok"}

    @app.get("/api/branding", tags=["meta"])
    def branding():
        # Public brand + contact identifiers consumed by legal pages, the footer,
        # and the report-abuse channel. No secrets — safe to expose unauthenticated.
        from .branding import get_branding

        b = get_branding()
        return {
            "product_name": b.product_name,
            "support_email": b.support_email,
            "legal_email": b.legal_email,
        }

    @app.get("/api/health/ready", tags=["meta"])
    def health_ready():
        # Fly treats every 2xx response as healthy, so dependency failure must
        # change the HTTP status rather than only the JSON payload.
        ok, checks = _readiness_result()
        return JSONResponse(
            status_code=200 if ok else 503,
            content={"status": "ok" if ok else "error", "checks": checks},
        )

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
    # Labs is an image-model experimentation surface that bills provider quota
    # directly and is not credit-gated. It defaults OFF; set
    # CANARY_LABS_ENABLED=true for local dev or an internal deployment.
    if _labs_enabled():
        app.include_router(labs.router, prefix="/api/labs", tags=["labs"])
    else:
        log.info("Labs router disabled (CANARY_LABS_ENABLED not set to truthy)")

    # Serve bundled fonts
    app.mount("/static/fonts", StaticFiles(directory=str(FONTS_DIR)), name="fonts")

    # In production, serve the built React app. SPAStaticFiles falls back to
    # index.html for unknown non-asset paths so client-side routes (e.g.
    # /login) survive direct hits and refreshes.
    if not dev:
        dist = Path(__file__).parent.parent.parent.parent.parent / "web" / "dist"
        if dist.is_dir():
            app.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="frontend")

    return app
