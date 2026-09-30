"""Release-blocking security and readiness contracts."""

import os

import asyncio
import json
from pathlib import Path
from types import MappingProxyType
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from novel_to_comic import codex_dev
from novel_to_comic.config import load_config
from novel_to_comic.server import app as app_module
from novel_to_comic.server import deployment_status as deployment_status_module
from novel_to_comic.server.routers import billing


class _StreamingRequest:
    def __init__(self, chunks: list[bytes], content_length: int | None = None):
        self._chunks = chunks
        self.headers = {}
        if content_length is not None:
            self.headers["content-length"] = str(content_length)

    async def stream(self):
        for chunk in self._chunks:
            yield chunk


def test_stripe_webhook_payload_rejects_oversized_content_length(monkeypatch):
    monkeypatch.setenv("CANARY_STRIPE_WEBHOOK_MAX_KB", "1")
    request = _StreamingRequest([b"small"], content_length=1025)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(billing._read_stripe_webhook_payload(request))

    assert exc_info.value.status_code == 413


def test_stripe_webhook_payload_rejects_oversized_chunked_body(monkeypatch):
    monkeypatch.setenv("CANARY_STRIPE_WEBHOOK_MAX_KB", "1")
    request = _StreamingRequest([b"a" * 700, b"b" * 400])

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(billing._read_stripe_webhook_payload(request))

    assert exc_info.value.status_code == 413


def test_stripe_webhook_payload_preserves_exact_raw_bytes(monkeypatch):
    monkeypatch.setenv("CANARY_STRIPE_WEBHOOK_MAX_KB", "1")
    request = _StreamingRequest([b'{"type":', b'"event"}'])

    payload = asyncio.run(billing._read_stripe_webhook_payload(request))

    assert payload == b'{"type":"event"}'


def _paid_checkout(**changes):
    return {
        "id": "cs_test_paid",
        "mode": "payment",
        "status": "complete",
        "payment_status": "paid",
        "payment_intent": "pi_paid",
        "amount_total": 1200,
        "currency": "usd",
        "metadata": {"user_id": "user-1", "package": "starter"},
        **changes,
    }


@pytest.mark.parametrize("payment_status", [None, "unpaid", "no_payment_required"])
def test_checkout_webhook_does_not_credit_unpaid_sessions(payment_status):
    session = _paid_checkout(payment_status=payment_status)

    with patch.object(billing, "get_db") as get_db:
        billing._handle_checkout_completed(session)

    get_db.assert_not_called()


def test_checkout_webhook_does_not_credit_without_payment_intent():
    session = _paid_checkout(payment_intent=None)

    with patch.object(billing, "get_db") as get_db:
        with pytest.raises(HTTPException) as exc_info:
            billing._handle_checkout_completed(session)

    assert exc_info.value.status_code == 400
    assert "reconciliation" in exc_info.value.detail
    get_db.assert_not_called()


def test_checkout_webhook_credits_paid_session_once():
    session = _paid_checkout()
    table = MagicMock()
    table.upsert.return_value.execute.return_value.data = [{"id": "ledger-1"}]
    db = MagicMock()
    db.table.return_value = table

    with patch.object(billing, "get_db", return_value=db):
        billing._handle_checkout_completed(session)

    table.upsert.assert_called_once_with(
        {
            "user_id": "user-1",
            "amount_credits": 1200,
            "status": "settled",
            "description": "Credit purchase — 1,200 credits",
            "stripe_payment_intent_id": "pi_paid",
            "stripe_checkout_session_id": "cs_test_paid",
            "credit_package_id": "starter",
            "gross_amount_cents": 1200,
            "currency": "usd",
            "offer_version": "legacy",
            "purchase_event_environment": os.environ.get("CANARY_ENV", "development"),
            "purchase_event_release": os.environ.get("CANARY_VERSION", "unknown"),
            "stripe_mode": "unknown",
        },
        on_conflict="stripe_payment_intent_id",
        ignore_duplicates=True,
    )
    table.upsert.return_value.execute.assert_called_once_with()


def test_checkout_webhook_duplicate_conflict_is_a_clean_noop():
    session = _paid_checkout(id="cs_test_duplicate")
    table = MagicMock()
    table.upsert.return_value.execute.return_value.data = []
    db = MagicMock()
    db.table.return_value = table

    with patch.object(billing, "get_db", return_value=db):
        billing._handle_checkout_completed(session)

    table.upsert.return_value.execute.assert_called_once_with()


def test_checkout_webhook_persists_integration_amount_with_local_presentment():
    # Stripe Adaptive Pricing keeps Session/PaymentIntent amount and currency in
    # the integration currency. Local customer currency is a separate field:
    # https://docs.stripe.com/payments/currencies/localize-prices/adaptive-pricing
    session = _paid_checkout(presentment_details={
        "presentment_amount": 1675,
        "presentment_currency": "cad",
    })
    table = MagicMock()
    table.upsert.return_value.execute.return_value.data = []
    db = MagicMock()
    db.table.return_value = table

    with patch.object(billing, "get_db", return_value=db):
        billing._handle_checkout_completed(session)

    payload = table.upsert.call_args.args[0]
    assert payload["gross_amount_cents"] == 1200
    assert payload["currency"] == "usd"


def test_checkout_webhook_rejects_currency_without_matching_offer_evidence():
    session = _paid_checkout(amount_total=1675, currency="cad")
    with patch.object(billing, "get_db") as get_db:
        with pytest.raises(HTTPException) as exc_info:
            billing._handle_checkout_completed(session)
    assert exc_info.value.status_code == 400
    get_db.assert_not_called()


def test_checkout_origin_uses_configured_url_in_production(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "production")
    monkeypatch.setenv("SCENEWRIGHT_APP_URL", "https://app.scenewright.ink/")
    request = MagicMock()
    request.headers = {"origin": "https://attacker.example"}

    assert billing._checkout_origin(request) == "https://app.scenewright.ink"


def test_checkout_origin_fails_closed_without_production_url(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "production")
    monkeypatch.delenv("SCENEWRIGHT_APP_URL", raising=False)
    request = MagicMock()
    request.headers = {"origin": "https://attacker.example"}

    with pytest.raises(HTTPException) as exc_info:
        billing._checkout_origin(request)

    assert exc_info.value.status_code == 500


def test_checkout_origin_requires_https_in_production(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "production")
    monkeypatch.setenv("SCENEWRIGHT_APP_URL", "http://app.scenewright.ink")
    request = MagicMock()
    request.headers = {}

    with pytest.raises(HTTPException) as exc_info:
        billing._checkout_origin(request)

    assert exc_info.value.status_code == 500


def test_readiness_fails_closed_when_production_config_is_missing(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "production")
    for name in (
        "SUPABASE_URL",
        "SUPABASE_SECRET_KEY",
        "LITELLM_BASE_URL",
        "LITELLM_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    ok, checks = app_module._readiness_result()

    assert ok is False
    assert checks == {
        "supabase": "error: missing configuration",
        "litellm": "error: missing configuration",
    }


def test_readiness_allows_missing_dependencies_in_development(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "dev")
    for name in (
        "SUPABASE_URL",
        "SUPABASE_SECRET_KEY",
        "LITELLM_BASE_URL",
        "LITELLM_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    ok, checks = app_module._readiness_result()

    assert ok is True
    assert checks == {"supabase": "skipped", "litellm": "skipped"}


def test_readiness_checks_mock_models_instead_of_litellm(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "dev")
    monkeypatch.setenv("CANARY_MOCK_GENERATIONS_ENABLED", "true")
    monkeypatch.setenv("CANARY_MOCK_MODEL_BASE_URL", "http://mock.test:4010")
    monkeypatch.setenv("LITELLM_BASE_URL", "http://paid-gateway.test:4000")
    monkeypatch.setenv("LITELLM_API_KEY", "secret")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)

    response = MagicMock()
    response.raise_for_status.return_value = None
    with patch("httpx.Client.get", return_value=response) as get:
        ok, checks = app_module._readiness_result()

    assert ok is True
    assert checks == {"supabase": "skipped", "mock_models": "ok"}
    get.assert_called_once_with("http://mock.test:4010/health/liveliness")


def test_readiness_endpoint_uses_http_503_on_failure(tmp_path: Path):
    from tests.queue_fixtures import create_app
    app = create_app(tmp_path, dev=True)
    endpoint = next(
        route.endpoint for route in app.routes if route.path == "/api/health/ready"
    )

    with patch.object(
        app_module,
        "_readiness_result",
        return_value=(False, {"supabase": "error: TimeoutError", "litellm": "ok"}),
    ):
        response = endpoint()

    assert response.status_code == 503


def test_readiness_endpoint_uses_http_200_on_success(tmp_path: Path):
    from tests.queue_fixtures import create_app
    app = create_app(tmp_path, dev=True)
    endpoint = next(
        route.endpoint for route in app.routes if route.path == "/api/health/ready"
    )

    with patch.object(
        app_module,
        "_readiness_result",
        return_value=(True, {"supabase": "ok", "litellm": "ok"}),
    ):
        response = endpoint()

    assert response.status_code == 200
    assert b'"pipeline_contract":"eight-stage-v2"' in response.body


@pytest.mark.parametrize(
    ("codex_enabled", "mock_enabled", "expected_mode", "expected_dependency", "claude_enabled"),
    [
        ("0", "false", "api", "litellm", "0"),
        ("0", "true", "mock", "mock_models", "0"),
        ("1", "false", "codex", "litellm", "0"),
        # Claude Code choices are additive to the mode, never a mode of their own.
        ("0", "false", "api", "litellm", "1"),
    ],
)
def test_readiness_reports_process_model_mode(
    tmp_path: Path, monkeypatch, codex_enabled, mock_enabled,
    expected_mode, expected_dependency, claude_enabled,
):
    process = dict.fromkeys(codex_dev._PROCESS)
    process.update(CANARY_CODEX_DEV_ENABLED=codex_enabled, CANARY_ENV="development",
                   CANARY_CLAUDE_DEV_ENABLED=claude_enabled)
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType(process))
    monkeypatch.setattr(codex_dev, "_SETTINGS_ERROR", None)
    monkeypatch.setenv("CANARY_ENV", "development")
    monkeypatch.setenv("CANARY_MOCK_GENERATIONS_ENABLED", mock_enabled)
    monkeypatch.setenv("CANARY_MOCK_MODEL_BASE_URL", "http://mock.test:4010")
    monkeypatch.setenv("LITELLM_BASE_URL", "http://gateway.test:4000")
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    from tests.queue_fixtures import create_app
    app = create_app(tmp_path, dev=True)
    endpoint = next(
        route.endpoint for route in app.routes if route.path == "/api/health/ready"
    )

    with patch("httpx.Client.get", return_value=MagicMock()):
        response = endpoint()

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "status": "ok",
        "pipeline_contract": "eight-stage-v2",
        "model_mode": expected_mode,
        "claude_code": claude_enabled == "1",
        "checks": {"supabase": "skipped", expected_dependency: "ok", "generation_queue": "ok"},
    }


def test_readiness_ignores_dotenv_and_project_codex_opt_in(tmp_path: Path, monkeypatch):
    process = dict.fromkeys(codex_dev._PROCESS)
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType(process))
    # Register restoration before load_config mutates the live environment.
    monkeypatch.delenv("CANARY_CODEX_DEV_ENABLED", raising=False)
    monkeypatch.setenv("CANARY_ENV", "development")
    monkeypatch.setenv("CANARY_MOCK_GENERATIONS_ENABLED", "false")
    (tmp_path / ".env").write_text("CANARY_CODEX_DEV_ENABLED=1\n")
    (tmp_path / "config.yaml").write_text(
        "dev_mode: true\nplan_model: codex-dev/gpt-5.6-terra\n"
    )
    load_config(tmp_path)
    from tests.queue_fixtures import create_app
    app = create_app(tmp_path, dev=True)
    endpoint = next(
        route.endpoint for route in app.routes if route.path == "/api/health/ready"
    )

    with patch.object(
        app_module, "_readiness_result",
        return_value=(True, {"supabase": "skipped", "litellm": "skipped"}),
    ):
        response = endpoint()

    assert json.loads(response.body)["model_mode"] == "api"


def test_public_version_endpoint_reports_build_identity(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CANARY_VERSION", "abc123")
    monkeypatch.setenv("CANARY_BUILD_TIMESTAMP", "2026-07-24T12:00:00Z")
    client = TestClient(app_module.create_app(tmp_path, dev=True))

    response = client.get("/api/version")

    assert response.status_code == 200
    assert response.json() == {
        "application_version": "0.1.0",
        "git_sha": "abc123",
        "build_timestamp": "2026-07-24T12:00:00Z",
    }


@pytest.mark.parametrize(
    ("path", "expected_status"),
    [
        ("/api/health", 200),
        ("/api/missing", 404),
    ],
)
def test_production_security_headers_cover_success_and_errors(
    tmp_path: Path,
    monkeypatch,
    path: str,
    expected_status: int,
):
    monkeypatch.setenv("CANARY_ENV", "production")
    client = TestClient(app_module.create_app(tmp_path, dev=False))

    response = client.get(path)

    assert response.status_code == expected_status
    assert response.headers["strict-transport-security"].startswith("max-age=")
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    frame_src = next(part for part in response.headers["content-security-policy"].split("; ") if part.startswith("frame-src"))
    assert "https://www.youtube-nocookie.com" in frame_src
    assert "https://www.youtube.com" not in frame_src
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    assert "camera=()" in response.headers["permissions-policy"]


def test_security_headers_are_not_forced_in_local_development(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "dev")
    client = TestClient(app_module.create_app(tmp_path, dev=True))

    response = client.get("/api/health")

    assert "strict-transport-security" not in response.headers


def test_deployment_activity_reports_idle_app(tmp_path: Path):
    app = app_module.create_app(tmp_path, dev=True)
    app.state.generation_jobs = {}
    app.state.generation_queue = asyncio.Queue()

    result = deployment_status_module.deployment_activity(app)

    assert result["safe_to_deploy"] is True
    assert result["status"] == "idle"
    assert not any(result["counts"].values())


def test_deployment_activity_counts_all_generation_work(tmp_path: Path):
    app = app_module.create_app(tmp_path, dev=True)
    app.state.generation_jobs = {}
    app.state.generation_queue = asyncio.Queue()
    pipeline_task = MagicMock()
    pipeline_task.done.return_value = False
    style_task = MagicMock()
    style_task.done.return_value = False
    queued_job = MagicMock(status="queued")
    running_job = MagicMock(status="running")
    app.state.running_tasks["pipeline"] = pipeline_task
    app.state.style_tasks["style"] = style_task
    app.state.generation_jobs.update(
        {"queued": queued_job, "running": running_job}
    )
    app.state.generation_queue.put_nowait(queued_job)
    app.state.draw_in_flight["project"] = [{"panel_number": 1}]

    result = deployment_status_module.deployment_activity(app)

    assert result == {
        "status": "busy",
        "safe_to_deploy": False,
        "draining": False,
        "counts": {
            "admitting_requests": 0,
            "pipeline_tasks": 1,
            "style_tasks": 1,
            "queued_generation_jobs": 1,
            "running_generation_jobs": 1,
            "queue_items": 1,
            "draw_panels_in_flight": 1,
        },
        "preserved_queued_operations": 0,
    }


def test_drained_deploy_preserves_durable_queue_but_waits_for_running_work(tmp_path: Path):
    app = app_module.create_app(tmp_path, dev=True)
    app.state.generation_jobs = {}
    app.state.generation_queue = asyncio.Queue()
    durable = MagicMock(status="queued", command=object())
    app.state.generation_jobs["queued"] = durable
    app.state.admission.set_draining(True)

    result = deployment_status_module.deployment_activity(app)
    assert result["safe_to_deploy"] is True
    assert result["preserved_queued_operations"] == 1
    assert result["counts"]["queued_generation_jobs"] == 1

    app.state.generation_jobs["running"] = MagicMock(status="running", command=object())
    assert deployment_status_module.deployment_activity(app)["safe_to_deploy"] is False


def test_undrained_or_non_durable_queue_blocks_deploy(tmp_path: Path):
    app = app_module.create_app(tmp_path, dev=True)
    app.state.generation_jobs = {"queued": MagicMock(status="queued", command=object())}
    app.state.generation_queue = asyncio.Queue()
    assert deployment_status_module.deployment_activity(app)["safe_to_deploy"] is False

    app.state.admission.set_draining(True)
    app.state.generation_jobs = {"fixture": MagicMock(status="queued", command=None)}
    result = deployment_status_module.deployment_activity(app)
    assert result["safe_to_deploy"] is False
    assert result["preserved_queued_operations"] == 0


def test_ops_token_is_required_and_constant_time_compared(monkeypatch):
    monkeypatch.setenv("CANARY_OPS_TOKEN", "operator-secret")

    with pytest.raises(HTTPException) as exc_info:
        deployment_status_module.require_ops_token("wrong")
    assert exc_info.value.status_code == 401

    assert deployment_status_module.require_ops_token("operator-secret") is None


def test_ops_token_fails_closed_when_unconfigured(monkeypatch):
    monkeypatch.delenv("CANARY_OPS_TOKEN", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        deployment_status_module.require_ops_token(None)

    assert exc_info.value.status_code == 503


def test_fly_routes_on_local_liveness_and_uses_conservative_limits():
    import tomllib

    root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((root / "fly.toml").read_text(encoding="utf-8"))
    service = config["http_service"]

    assert service["checks"][0]["path"] == "/api/health"
    assert service["checks"][0]["headers"] == {"Host": "canary-web.fly.dev"}
    assert service["concurrency"] == {
        "type": "requests",
        "hard_limit": 50,
        "soft_limit": 30,
    }
    assert config["vm"][0]["memory"] == "4gb"
    assert config["vm"][0]["memory_mb"] == 4096




def test_production_docker_build_fails_without_supabase_build_args():
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    assert '[ -z "$VITE_SUPABASE_URL" ]' in dockerfile
    assert '[ -z "$VITE_SUPABASE_PUBLISHABLE_KEY" ]' in dockerfile


def test_production_docker_plumbs_one_release_into_backend_and_frontend():
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.count("ARG CANARY_VERSION=unknown") == 2
    assert 'ENV CANARY_VERSION="$CANARY_VERSION"' in dockerfile
    assert 'VITE_CANARY_VERSION="$CANARY_VERSION"' in dockerfile


def test_production_docker_installs_playwright_system_dependencies():
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    assert "playwright install --with-deps chromium" in dockerfile


def test_bundled_fonts_have_real_sfnt_headers():
    root = Path(__file__).resolve().parents[2]
    fonts = root / "novel_to_comic" / "src" / "novel_to_comic" / "fonts"

    for font in fonts.glob("*.ttf"):
        assert font.read_bytes()[:4] in {b"\x00\x01\x00\x00", b"OTTO"}, (
            f"{font.name} is not a valid TrueType/OpenType asset"
        )


def test_credit_view_uses_callers_rls_context():
    schema = (
        Path(__file__).resolve().parents[2] / "docs" / "supabase-schema.sql"
    ).read_text(encoding="utf-8")

    assert "create or replace view public.user_credits" in schema
    assert "with (security_invoker = true)" in schema


def test_litellm_images_install_the_locked_gateway_environment():
    root = Path(__file__).resolve().parents[2]
    production = (root / "Dockerfile").read_text(encoding="utf-8")
    local_gateway = (root / "litellm" / "Dockerfile").read_text(encoding="utf-8")
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    import tomllib

    gateway = tomllib.loads((root / "litellm/pyproject.toml").read_text())
    lock = tomllib.loads((root / "litellm/uv.lock").read_text())
    versions = {package["name"]: package["version"] for package in lock["package"]}
    assert "litellm[proxy]==1.101.0" in gateway["project"]["dependencies"]
    assert versions["litellm"] == "1.101.0"
    # The gateway ships only the FAL queue handler; Vertex SDKs were retired.
    assert "google-genai" not in versions
    for dockerfile in (production, local_gateway):
        assert "COPY litellm/pyproject.toml litellm/uv.lock" in dockerfile
        assert "uv sync --project /app/gateway --locked" in dockerfile
    assert "dockerfile: litellm/Dockerfile" in compose


def test_operational_drain_requires_authentication_and_explicit_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("CANARY_OPS_TOKEN", "operator-secret")
    from tests.queue_fixtures import create_app
    app = create_app(tmp_path, dev=True)
    app.state.generation_jobs = {}
    app.state.generation_queue = asyncio.Queue()
    client = TestClient(app)
    rejected = client.post("/api/ops/drain")
    assert rejected.status_code == 401
    assert app.state.admission.draining is False
    admitted = client.post("/api/ops/drain", headers={"X-Canary-Ops-Token": "operator-secret"})
    assert admitted.json()["draining"] is True
    assert app.state.admission.draining is True
    assert client.post("/api/ops/resume").status_code == 401
    assert app.state.admission.draining is True
    resumed = client.post("/api/ops/resume", headers={"X-Canary-Ops-Token": "operator-secret"})
    assert resumed.json()["draining"] is False