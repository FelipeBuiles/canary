"""Auth transport defaults and production audience/cookie policy."""

from types import SimpleNamespace

import pytest

from novel_to_comic.server import auth


@pytest.fixture(autouse=True)
def clean_auth_environment(monkeypatch):
    for name in ("CANARY_ENV", "ENV", "SUPABASE_JWT_AUDIENCE", "CANARY_COOKIE_SECURE"):
        monkeypatch.delenv(name, raising=False)


def _request_with_scheme(scheme: str) -> SimpleNamespace:
    return SimpleNamespace(url=SimpleNamespace(scheme=scheme))


def test_cookie_secure_env_flag_true(monkeypatch):
    monkeypatch.setenv("CANARY_COOKIE_SECURE", "true")
    assert auth._cookie_secure(_request_with_scheme("http")) is True


def test_cookie_secure_env_flag_off_is_explicit_dev_opt_out(monkeypatch):
    monkeypatch.setenv("CANARY_COOKIE_SECURE", "false")
    assert auth._cookie_secure(_request_with_scheme("https")) is False
    assert auth._cookie_secure(_request_with_scheme("http")) is False


def test_cookie_secure_unset_uses_scheme():
    assert auth._cookie_secure(_request_with_scheme("https")) is True
    assert auth._cookie_secure(_request_with_scheme("http")) is False


def test_expected_audience_unset_by_default():
    assert auth._expected_audience() is None


def test_expected_audience_defaults_to_authenticated_in_production(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "production")
    assert auth._expected_audience() == "authenticated"


def test_expected_audience_env_override_wins_in_production(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_AUDIENCE", "custom-aud")
    monkeypatch.setenv("CANARY_ENV", "production")
    assert auth._expected_audience() == "custom-aud"


def test_expected_audience_empty_string_cannot_opt_out_in_production(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_AUDIENCE", "")
    monkeypatch.setenv("CANARY_ENV", "production")
    assert auth._expected_audience() == "authenticated"


def test_expected_audience_empty_string_can_opt_out_in_development(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_AUDIENCE", "")
    assert auth._expected_audience() is None


def test_expected_audience_reads_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_JWT_AUDIENCE", "authenticated")
    assert auth._expected_audience() == "authenticated"


def test_get_current_user_rejects_missing_token():
    import asyncio
    from fastapi import HTTPException

    async def call_without_token() -> str:
        return await auth.get_current_user(
            request=SimpleNamespace(url=SimpleNamespace(scheme="https")),
            response=SimpleNamespace(set_cookie=lambda **kw: None),
            authorization=None,
            session_cookie=None,
        )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(call_without_token())
    assert exc_info.value.status_code == 401
