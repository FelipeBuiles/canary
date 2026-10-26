"""Provider-free regressions for authentication and filesystem authority."""
import asyncio
import time
from types import SimpleNamespace
from uuid import uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException, Request, Response

from novel_to_comic.server import auth
from novel_to_comic.server.project_paths import project_directory


@pytest.fixture
def signing(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://auth.example.test")
    monkeypatch.setenv("CANARY_ENV", "production")
    monkeypatch.delenv("SUPABASE_JWT_AUDIENCE", raising=False)
    key = ec.generate_private_key(ec.SECP256R1())
    client = SimpleNamespace(get_signing_key_from_jwt=lambda token: SimpleNamespace(key=key.public_key()))
    monkeypatch.setattr(auth, "_get_jwks_client", lambda: client)
    claims = {
        "sub": str(uuid4()), "exp": int(time.time()) + 300,
        "iss": "https://auth.example.test/auth/v1", "aud": "authenticated",
    }
    return key, claims


def _request(method="GET"):
    return Request({"type": "http", "method": method, "scheme": "https", "headers": [], "path": "/"})


def _authenticate(token, method="GET", *, cookie=False):
    response = Response()
    result = asyncio.run(auth.get_current_user(
        _request(method), response,
        authorization=None if cookie else f"Bearer {token}",
        session_cookie=token if cookie else None,
    ))
    return result, response


def test_valid_signed_bearer_and_native_cookie_reads(signing):
    key, claims = signing
    token = jwt.encode(claims, key, algorithm="ES256")
    assert _authenticate(token, "POST")[0] == claims["sub"]
    for method in ("GET", "HEAD", "OPTIONS"):
        user, response = _authenticate(token, method, cookie=True)
        assert user == claims["sub"]
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "Secure" in response.headers["set-cookie"]


def test_native_cookie_expires_with_the_access_token(signing):
    key, claims = signing
    claims["exp"] = int(time.time()) + 60
    _, response = _authenticate(jwt.encode(claims, key, algorithm="ES256"))
    from http.cookies import SimpleCookie
    cookies = SimpleCookie(response.headers["set-cookie"])
    assert 0 < int(cookies[auth.SESSION_COOKIE_NAME]["max-age"]) <= 60


def test_logout_clears_cookie_without_requiring_a_live_token(signing):
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient
    key, claims = signing
    app = FastAPI()
    app.include_router(auth.router, prefix="/api/auth")

    @app.get("/private")
    def private(user=Depends(auth.get_current_user)):
        return {"user": user}

    with TestClient(app, base_url="https://testserver") as client:
        assert client.get("/private", headers={"Authorization": f"Bearer {jwt.encode(claims, key, algorithm='ES256')}"}).status_code == 200
        assert client.get("/private").status_code == 200
        logout = client.post("/api/auth/logout", headers={"Authorization": "Bearer expired"})
        assert logout.status_code == 204
        # Private images cached for reloads must not outlive the session.
        assert logout.headers["clear-site-data"] == '"cache"'
        assert client.get("/private").status_code == 401
        assert client.post("/api/auth/logout").status_code == 204


@pytest.mark.parametrize("claim", ["exp", "iss", "sub"])
def test_signed_token_missing_required_claim_rejected(signing, claim):
    key, claims = signing
    claims.pop(claim)
    with pytest.raises(HTTPException) as caught:
        _authenticate(jwt.encode(claims, key, algorithm="ES256"))
    assert caught.value.status_code == 401


@pytest.mark.parametrize("changes", [
    {"iss": "https://another.example.test/auth/v1"}, {"aud": "other-service"},
    {"sub": "../other-account"}, {"sub": ""}, {"exp": 1},
])
def test_signed_token_with_wrong_authority_rejected(signing, changes):
    key, claims = signing
    claims.update(changes)
    with pytest.raises(HTTPException) as caught:
        _authenticate(jwt.encode(claims, key, algorithm="ES256"))
    assert caught.value.status_code == 401


def test_invalid_signature_rejected(signing):
    _, claims = signing
    other_key = ec.generate_private_key(ec.SECP256R1())
    with pytest.raises(HTTPException) as caught:
        _authenticate(jwt.encode(claims, other_key, algorithm="ES256"))
    assert caught.value.status_code == 401


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_cookie_cannot_authorize_mutation(signing, method):
    key, claims = signing
    with pytest.raises(HTTPException) as caught:
        _authenticate(jwt.encode(claims, key, algorithm="ES256"), method, cookie=True)
    assert caught.value.status_code == 401


def test_bad_explicit_header_cannot_fall_back_to_cookie(signing):
    key, claims = signing
    token = jwt.encode(claims, key, algorithm="ES256")
    with pytest.raises(HTTPException) as caught:
        asyncio.run(auth.get_current_user(_request(), Response(), "Basic invalid", token))
    assert caught.value.status_code == 401


def test_production_cannot_disable_audience_or_secure_cookie(monkeypatch):
    monkeypatch.delenv("CANARY_ENV", raising=False)
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("SUPABASE_JWT_AUDIENCE", "")
    monkeypatch.setenv("CANARY_COOKIE_SECURE", "false")
    assert auth._expected_audience() == "authenticated"
    assert auth._cookie_secure(SimpleNamespace(url=SimpleNamespace(scheme="http")))


@pytest.mark.parametrize("slug", ["../victim/story", "/tmp/story", "..", ".", ".secrets", "x/y", r"x\y", "", None])
def test_database_slug_cannot_choose_another_directory(tmp_path, slug):
    with pytest.raises(ValueError):
        project_directory(tmp_path, "account", slug)


def test_valid_new_and_existing_project_paths(tmp_path):
    expected = tmp_path / "account" / "the-gift-of-the-magi"
    assert project_directory(tmp_path, "account", expected.name) == expected
    expected.mkdir(parents=True)
    assert project_directory(tmp_path, "account", expected.name) == expected


@pytest.mark.parametrize("alias", ["account", "project"])
def test_account_and_project_symlinks_cannot_alias_another_tenant(tmp_path, alias):
    victim = tmp_path / "victim" / "story"
    victim.mkdir(parents=True)
    account = tmp_path / "account"
    if alias == "account":
        account.symlink_to(victim.parent, target_is_directory=True)
    else:
        account.mkdir()
        (account / "story").symlink_to(victim, target_is_directory=True)
    with pytest.raises(ValueError):
        project_directory(tmp_path, "account", "story")


def test_same_account_project_symlink_is_not_a_second_identity(tmp_path):
    real = tmp_path / "account" / "real"
    real.mkdir(parents=True)
    (real.parent / "alias").symlink_to(real, target_is_directory=True)
    with pytest.raises(ValueError):
        project_directory(tmp_path, "account", "alias")
