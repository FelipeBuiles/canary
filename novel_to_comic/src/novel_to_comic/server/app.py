"""FastAPI application factory for the web dashboard."""

import asyncio
import logging
import json
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import HTTPConnection
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.staticfiles import StaticFiles
from novel_to_comic.model_costs import DEFAULT_COST_MAP_PATH, refresh_litellm_cost_cache
from novel_to_comic.clients.structured_call import validation_error_summary
from novel_to_comic.config import DEFAULT_IMAGE_CONCURRENCY
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing
from novel_to_comic.usage import audit_pricing

from .durable_queue import initialize_queue
from .deployment_status import deployment_activity, require_ops_token
from .logging import request_log_middleware
from .ratelimit import configure_rate_limiting
from .telemetry import configure_telemetry, shutdown_telemetry
from .routers import (
    billing,
    publications,
    account_models,
    backoffice,
    cast_assets,
    config,
    credits,
    editorial,
    export,
    events,
    files,
    operator_billing,
    pages,
    pipeline,
    projects,
    stages,
    styles,
)
from .metrics import metrics_response
from .release import release_identity

FONTS_DIR = Path(__file__).resolve().parents[1] / "fonts"


# Mirrors web/src/lib/sessionHint.ts. A presentation hint only: it selects the
# document for `/` and never authorizes anything.
SESSION_HINT_COOKIE = "sw_signed_in"


class SPAStaticFiles(StaticFiles):
    """Complete public documents and SPA fallback for recognized app routes.

    The React app uses client-side routing (e.g. ``/login``, ``/project/123``);
    those paths exist only in the browser, not as files on disk. A plain
    ``StaticFiles(html=True)`` mount returns ``{"detail":"Not Found"}`` for any
    such path, breaking deep links and refreshes. Here we catch the 404 for
    recognized non-asset requests and serve ``index.html`` so the client router can take
    over. Real missing assets (``*.js``, ``*.css``, …) still 404 so broken
    links surface instead of silently returning the HTML shell.
    """

    # Extensions that should always be served as real files (or 404). Anything
    # without one of these is checked against recognized client routes.
    _ASSET_SUFFIXES = frozenset(
        {".js", ".mjs", ".css", ".map", ".html", ".htm", ".json", ".txt",
         ".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".avif",
         ".woff", ".woff2", ".ttf", ".eot", ".otf", ".wasm",
         ".mp4", ".webm", ".mp3", ".ogg", ".wav"}
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        manifest = Path(self.directory) / "public-pages.json"
        self.public_pages = json.loads(manifest.read_text()) if manifest.is_file() else {}

    @staticmethod
    def _client_route(path: str) -> bool:
        return path in {"login", "signup", "reset-password", "auth/callback", "account", "credits", "backoffice", "labs", "dev/primitives"} or bool(re.fullmatch(r"project/[^/]+(?:/.*)?", path))

    async def get_response(self, path: str, scope):
        public_path = "/" + ("" if path == "." else path.strip("/"))
        if path in self.public_pages.values():
            return RedirectResponse(next(route for route, file in self.public_pages.items() if file == path), status_code=308)
        if public_path in self.public_pages:
            if path.endswith("/") and public_path != "/":
                return RedirectResponse(public_path, status_code=308)
            # A signed-in browser's `/` is its Library: send the app shell so
            # the public homepage never flashes before the account loads.
            signed_in = public_path == "/" and HTTPConnection(scope).cookies.get(SESSION_HINT_COOKIE) == "1"
            response = await super().get_response(
                "index.html" if signed_in else self.public_pages[public_path], scope
            )
            response.headers["Cache-Control"] = "no-cache"
            if public_path == "/":
                response.headers["Vary"] = "Cookie"
            return response
        document = path in {"", ".", "index.html"} or path.lower().endswith(".html")
        try:
            response = await super().get_response(path, scope)
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
            if not self._client_route(path):
                response = publications.public_document(Path(self.directory) / "index.html",
                    title="Page not found — Scenewright", description="This page does not exist.",
                    path="/" + path, intro='<h1>Page not found</h1><p><a href="/">Return to Scenewright</a></p>', noindex=True)
                response.status_code = 404
                return response
            response = await super().get_response("index.html", scope)
            document = True
        if response.status_code in {200, 206, 304}:
            if document or response.headers.get("content-type", "").startswith("text/html"):
                # Revalidate the shell so releases never strand readers on old chunks.
                response.headers["Cache-Control"] = "no-cache"
            elif path.startswith("assets/") and re.search(r"-[\w-]{8,}\.[\w]+$", path):
                response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            else:
                # Unfingerprinted marketing files can change at the same URL.
                response.headers["Cache-Control"] = "public, max-age=3600"
        if self._client_route(path):
            response.headers["X-Robots-Tag"] = "noindex, follow"
        if path.lower().endswith(".webp") and response.status_code in {200, 206}:
            response.headers["Content-Type"] = "image/webp"
        return response


class MetricsAwareTrustedHostMiddleware(TrustedHostMiddleware):
    """Keep host validation everywhere except Fly's internal metrics scrape.

    Fly scrapes the Machine directly on the configured port and does not
    document a stable Host header. The metrics payload is aggregate-only, so
    allowing that one path avoids coupling scraping to public-host validation
    without weakening any customer or operator endpoint.
    """

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/metrics":
            await self.app(scope, receive, send)
            return
        await super().__call__(scope, receive, send)
log = logging.getLogger(__name__)


def _labs_enabled() -> bool:
    """Feature flag for the Labs experimentation router.

    Defaults OFF: Labs is a model experimentation surface that bypasses
    the credit system (it bills provider quota directly to operator keys).
    Mount it only in local development with ``CANARY_LABS_ENABLED=true``."""
    from .account_models import model_settings_enabled

    raw = os.environ.get("CANARY_LABS_ENABLED", "false").strip().lower()
    return model_settings_enabled() and raw not in {"0", "false", "no", "off"}


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

    mock_enabled = os.environ.get(
        "CANARY_MOCK_GENERATIONS_ENABLED", "false"
    ).strip().lower() not in {"", "0", "false", "no", "off"}
    if mock_enabled:
        import httpx

        mock_base_url = os.environ.get(
            "CANARY_MOCK_MODEL_BASE_URL", "http://127.0.0.1:4010"
        ).strip()
        try:
            with httpx.Client(timeout=2.0) as client:
                response = client.get(
                    f"{mock_base_url.rstrip('/')}/health/liveliness",
                )
                response.raise_for_status()
            checks["mock_models"] = "ok"
        except Exception as exc:  # noqa: BLE001 - surfaced to the probe payload
            ok = False
            checks["mock_models"] = f"error: {type(exc).__name__}"
    else:
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
    from .analytics_delivery import deliver_product_events
    app.state.analytics_task = asyncio.create_task(deliver_product_events(app)) if configure_telemetry() else None
    _audit_pricing_at_startup()
    app.state.pricing_refresh_task = asyncio.create_task(
        asyncio.to_thread(_refresh_pricing_if_stale)
    )

    from .credits import start_reservation_leases, stop_reservation_leases
    from .db import get_db

    # Dependency readiness must not crash the web process. Keep diagnostics
    # alive and paid admission closed while the existing lease manager starts.
    app.state.credit_leases_ready = False
    app.state.lease_shutdown = False

    def start_leases():
        start_reservation_leases(get_db())
        # asyncio cancellation cannot stop a synchronous dependency call.
        # If it returned after shutdown, do not leave a late lease thread alive.
        if app.state.lease_shutdown:
            stop_reservation_leases()

    async def initialize_leases():
        while True:
            try:
                await asyncio.to_thread(start_leases)
                app.state.credit_leases_ready = True
                return
            except Exception:
                logging.getLogger("canary.operations").warning(
                    "Credit lease initialization unavailable; admission remains closed"
                )
                await asyncio.sleep(30)

    app.state.lease_initialization_task = asyncio.create_task(initialize_leases())

    app.state.generation_worker_tasks = [asyncio.create_task(initialize_queue(app))]
    yield
    if app.state.analytics_task is not None:
        app.state.analytics_task.cancel()
        await asyncio.gather(app.state.analytics_task, return_exceptions=True)
    app.state.lease_shutdown = True
    app.state.admission.draining = True
    # Deployment control drains before shutdown. Forced shutdown cancels work
    # before closing provider clients, allowing credited runners to settle.
    labs_tasks = list(getattr(app.state, "labs_tasks", {}).values())
    for task in labs_tasks:
        task.cancel()
    if not app.state.pricing_refresh_task.done():
        app.state.pricing_refresh_task.cancel()
    app.state.lease_initialization_task.cancel()
    for task in app.state.generation_worker_tasks:
        task.cancel()
    await asyncio.gather(
        app.state.pricing_refresh_task,
        app.state.lease_initialization_task,
        *app.state.generation_worker_tasks,
        *labs_tasks,
        return_exceptions=True,
    )
    # Accepted but unstarted commands remain durable across shutdown. Running
    # commands are interrupted and fenced before provider clients close.
    stop_reservation_leases()
    from novel_to_comic.ai.client import _http

    await _http.aclose()
    await asyncio.to_thread(shutdown_telemetry)


def create_app(projects_dir: Path, dev: bool = False) -> FastAPI:
    from novel_to_comic.codex_dev import (
        CodexRoutingError, any_enabled, claude_enabled, enabled, is_loopback, validate_startup,
    )

    validate_startup()
    app = FastAPI(title="Scenewright", lifespan=_lifespan)

    @app.exception_handler(CodexRoutingError)
    async def codex_routing_error_handler(request, exc: CodexRoutingError):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    if any_enabled():
        @app.middleware("http")
        async def codex_loopback_only(request, call_next):
            if (
                request.client is None
                or not is_loopback(request.client.host)
                or not is_loopback(request.url.hostname or "")
                or any(name in request.headers for name in (
                    "forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"
                ))
            ):
                return JSONResponse(status_code=403, content={"detail": "Codex development requires a direct loopback request"})
            return await call_next(request)

    @app.exception_handler(ArtifactMissing)
    async def artifact_missing_exception_handler(request, exc: ArtifactMissing):
        request.state.artifact_unavailable = request.method in {"GET", "HEAD"}
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ArtifactInvalid)
    async def artifact_invalid_exception_handler(request, exc: ArtifactInvalid):
        request.state.artifact_unavailable = request.method in {"GET", "HEAD"}
        level = logging.DEBUG if request.state.artifact_unavailable and os.environ.get("CANARY_ENV") != "production" else logging.WARNING
        log.log(
            level,
            "Stored artifact rejected name=%s action=rerun_%s reason=%s",
            exc.name,
            (exc.owner_stage or "owner").lower(),
            validation_error_summary(exc.validation_error),
        )
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    app.middleware("http")(request_log_middleware)
    from .admission import Admission, admission_middleware

    app.state.admission = Admission(projects_dir)
    app.middleware("http")(admission_middleware)
    env = (os.environ.get("CANARY_ENV") or os.environ.get("ENV") or "dev").lower()
    if env == "production":
        from .security_headers import security_headers_middleware

        app.middleware("http")(security_headers_middleware)
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
            app.add_middleware(
                MetricsAwareTrustedHostMiddleware,
                allowed_hosts=allowed_hosts,
            )
    configure_rate_limiting(app)

    # Shared state for SSE streaming and concurrency control
    from .generation_jobs import (
        get_global_semaphore,
        _global_light_semaphores,
    )

    app.state.projects_dir = projects_dir
    app.state.event_queues: dict[str, asyncio.Queue] = {}
    # Per-project in-flight panel map for the draw stage. Maintained from
    # panel_start / panel_done events (see _wrap_on_event in pipeline.py).
    # Not persisted — if the server restarts, nothing is in flight.
    app.state.draw_in_flight: dict[str, list[dict]] = {}
    app.state.generation_semaphore = get_global_semaphore()
    app.state.light_generation_semaphore = asyncio.Semaphore(DEFAULT_IMAGE_CONCURRENCY)
    app.state.light_generation_semaphores = _global_light_semaphores
    app.state.light_generation_semaphores[DEFAULT_IMAGE_CONCURRENCY] = app.state.light_generation_semaphore
    app.state.generation_queue = asyncio.Queue()
    app.state.durable_queue_required = True
    app.state.durable_queue = None
    app.state.generation_jobs = {}
    app.state.user_generation_semaphores: dict[str, asyncio.Semaphore] = {}
    app.state.generation_job_timeout_seconds = max(
        1,
        int(os.environ.get("CANARY_GENERATION_JOB_TIMEOUT_SECONDS", "900")),
    )

    # CORS for the local operator desk. Production can explicitly allow a
    # local Vite origin when an operator intentionally connects to prod; the
    # operator token remains mandatory and no credentials are sent by CORS.
    configured_backoffice_origins = [
        origin.strip()
        for origin in os.environ.get("CANARY_BACKOFFICE_ORIGINS", "").split(",")
        if origin.strip()
    ]
    cors_origins = configured_backoffice_origins or (
        ["http://localhost:5173", "http://127.0.0.1:5173"] if dev else []
    )
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
            allow_headers=["Content-Type", "Authorization", "Idempotency-Key", "X-Canary-Ops-Token",
                           "X-Request-ID", "X-Canary-Session-ID", "traceparent"],
            expose_headers=["X-Request-ID", "X-Trace-ID"],
        )

    @app.get("/api/health", tags=["meta"])
    def health():
        # Liveness: always ok and cheap. Never depend on external services here —
        # a slow dependency must not make the load balancer kill a healthy instance.
        return {"status": "ok"}

    @app.get("/api/version", tags=["meta"])
    def api_version():
        return release_identity()

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
        from .credits import reservation_leases_healthy
        if hasattr(app.state, "credit_leases_ready") and (
            not app.state.credit_leases_ready or not reservation_leases_healthy()
        ):
            ok = False
            checks["credit_leases"] = "unavailable"
        queue = app.state.durable_queue
        if queue is None or not queue.healthy:
            ok = False
            checks["generation_queue"] = "unavailable"
        else:
            checks["generation_queue"] = "ok"
        return JSONResponse(
            status_code=200 if ok else 503,
            content={
                "status": "ok" if ok else "error",
                "pipeline_contract": "eight-stage-v2",
                "model_mode": (
                    "codex" if enabled() else "mock" if "mock_models" in checks else "api"
                ),
                # Additive to model_mode: Claude Code choices mix with API or Codex.
                "claude_code": claude_enabled(),
                "checks": checks,
            },
        )

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics():
        # Aggregate-only endpoint scraped by Fly. It intentionally contains no
        # customer, project, request, prompt, or path-parameter labels.
        return metrics_response(app)

    @app.get(
        "/api/ops/deployment-status",
        tags=["operations"],
        dependencies=[Depends(require_ops_token)],
    )
    def deployment_status():
        """Report whether in-process generation activity makes a deploy unsafe."""
        return deployment_activity(app)

    @app.post("/api/ops/drain", tags=["operations"], dependencies=[Depends(require_ops_token)])
    async def drain():
        async with app.state.admission.gate:
            app.state.admission.set_draining(True)
        return deployment_activity(app)

    @app.post("/api/ops/resume", tags=["operations"], dependencies=[Depends(require_ops_token)])
    async def resume():
        async with app.state.admission.gate:
            ok, _ = await asyncio.to_thread(_readiness_result)
            from .credits import reservation_leases_healthy
            leases_ready = not hasattr(app.state, "credit_leases_ready") or (
                app.state.credit_leases_ready and reservation_leases_healthy()
            )
            queue_ready = app.state.durable_queue is not None and app.state.durable_queue.healthy
            if not ok or not leases_ready or not queue_ready:
                raise HTTPException(503, "Dependencies must be ready before reopening admission")
            app.state.admission.set_draining(False)
        return deployment_activity(app)

    @app.get("/api/ops/exceptions", tags=["operations"], dependencies=[Depends(require_ops_token)])
    def operational_exceptions():
        from .operations import exception_snapshot
        return exception_snapshot(app)

    # Routers
    from .auth import router as auth_router
    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
    app.include_router(publications.router, prefix="/api/projects/{project_id}/parts/{part_id}", tags=["publications"])
    app.include_router(publications.public_router, prefix="/api/public/books", tags=["publications"])
    app.include_router(publications.ops_router, prefix="/api/ops/publications", tags=["publications"])
    app.include_router(account_models.router, prefix="/api/account", tags=["account"])
    app.include_router(credits.router, prefix="/api/credits", tags=["credits"])
    app.include_router(billing.router, prefix="/api/billing", tags=["billing"])
    app.include_router(
        operator_billing.router,
        prefix="/api/ops/billing",
        tags=["operations"],
    )
    app.include_router(
        backoffice.router,
        prefix="/api/ops/backoffice",
        tags=["operations"],
    )
    from .routers import feedback
    app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])
    app.include_router(events.router, prefix="/api/events", tags=["analytics"])
    @app.post("/api/ops/housekeeping", dependencies=[Depends(require_ops_token)])
    def cleanup_storage():
        from .storage_budget import housekeeping
        try:
            return housekeeping(app)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc

    app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
    from .routers import parts as parts_router
    from .routers import story_bible as story_bible_router
    app.include_router(parts_router.router, prefix="/api/projects/{project_id}", tags=["parts"])
    app.include_router(story_bible_router.router, prefix="/api/projects/{project_id}", tags=["story-bible"])
    app.include_router(publications.owner_router, prefix="/api/projects/{project_id}", tags=["publication"])
    # Page work belongs to a part workspace; Look work to the series root.
    # Pipeline, stage artifacts and files serve both: series routes act on the
    # root (Style, Cast, Story Bible), part routes on one part's workspace.
    part_prefix = "/api/projects/{project_id}/parts/{part_id}"
    for prefix in ("/api/projects/{project_id}", part_prefix):
        app.include_router(pipeline.router, prefix=prefix, tags=["pipeline"])
        app.include_router(stages.router, prefix=prefix, tags=["stages"])
    app.include_router(pages.router, prefix=part_prefix, tags=["pages"])
    app.include_router(export.router, prefix=f"{part_prefix}/export", tags=["export"])
    app.include_router(editorial.router, prefix=part_prefix, tags=["stages"])
    app.include_router(
        config.router,
        prefix="/api/projects/{project_id}/config",
        tags=["config"],
    )
    app.include_router(
        styles.router,
        prefix="/api/projects/{project_id}",
        tags=["styles"],
    )
    app.include_router(
        cast_assets.router,
        prefix="/api/projects/{project_id}",
        tags=["cast"],
    )
    from .routers import cold_open as cold_open_router
    app.include_router(cold_open_router.router, prefix="/api/projects/{project_id}", tags=["cold-open"])
    # Registered last: the asset reader owns a greedy `{file_path:path}` route,
    # so every named project route must be matched before it is considered.
    app.include_router(files.router, prefix=part_prefix, tags=["files"])
    app.include_router(
        files.router,
        prefix="/api/projects/{project_id}",
        tags=["files"],
    )
    # Labs is a model experimentation surface that bills provider quota
    # directly and is not credit-gated. It defaults OFF; set
    # CANARY_LABS_ENABLED=true for local development.
    if _labs_enabled():
        from .routers import labs

        app.include_router(labs.router, prefix="/api/labs", tags=["labs"])
    else:
        log.info("Labs router disabled (CANARY_LABS_ENABLED not set to truthy)")

    @app.get("/sitemap.xml", include_in_schema=False)
    def public_sitemap():
        return publications.sitemap_document()

    @app.get("/robots.txt", include_in_schema=False)
    def public_robots():
        return publications.robots_document()

    # Serve bundled fonts
    app.mount("/static/fonts", StaticFiles(directory=str(FONTS_DIR)), name="fonts")

    # Complete public React documents are built alongside the SPA shell.
    # Recognized private/auth routes retain deep links; unknown URLs return 404.
    if not dev:
        dist = Path(__file__).parent.parent.parent.parent.parent / "web" / "dist"
        if dist.is_dir():
            @app.get("/read/{book_id}", include_in_schema=False)
            def public_reader_document(book_id: str):
                return publications.reader_html(book_id, projects_dir, dist / "index.html")

            @app.get("/samples", include_in_schema=False)
            def public_samples_document(story: str | None = None):
                return publications.samples_html(dist / "index.html", story)

            app.mount("/", SPAStaticFiles(directory=str(dist), html=True), name="frontend")

    return app
