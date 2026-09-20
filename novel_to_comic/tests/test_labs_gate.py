"""Tests for the Labs feature gate (CANARY_LABS_ENABLED).

Labs is an experimentation surface that shrinks the public attack surface when
disabled. The router is conditionally included by ``create_app`` based on the
env flag — these tests lock that behaviour in so a refactor can't silently
re-expose it.
"""

from pathlib import Path

import pytest

from tests.queue_fixtures import create_app


def _has_labs_routes(app) -> bool:
    # Included routers are lazy in newer FastAPI; inspect the public schema.
    return any(path.startswith("/api/labs") for path in app.openapi()["paths"])


def test_labs_disabled_by_default(monkeypatch, tmp_path):
    monkeypatch.delenv("CANARY_LABS_ENABLED", raising=False)
    app = create_app(Path(str(tmp_path)), dev=True)
    assert not _has_labs_routes(app), (
        "Labs must default OFF — it bills provider quota directly and is not "
        "credit-gated, so it should not ship enabled without an explicit opt-in."
    )


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "FALSE"])
def test_labs_disabled_when_flag_false(monkeypatch, tmp_path, value):
    monkeypatch.setenv("CANARY_LABS_ENABLED", value)
    app = create_app(Path(str(tmp_path)), dev=True)
    assert not _has_labs_routes(app), (
        f"Labs should be hidden when CANARY_LABS_ENABLED={value!r}"
    )


@pytest.mark.parametrize("value", ["true", "1", "yes", "on"])
def test_labs_enabled_when_flag_true(monkeypatch, tmp_path, value):
    monkeypatch.setenv("CANARY_LABS_ENABLED", value)
    app = create_app(Path(str(tmp_path)), dev=True)
    assert _has_labs_routes(app)
