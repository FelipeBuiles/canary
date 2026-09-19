"""JWT authentication dependency using Supabase JWKS (RS256/ES256)."""

import os
from uuid import UUID

import jwt
from jwt import PyJWKClient
from fastapi import Cookie, Header, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

SESSION_COOKIE_NAME = "pulp_session"

# Lazily initialised — requires SUPABASE_URL at first request.
_jwks_client: PyJWKClient | None = None


def _production() -> bool:
    return (os.environ.get("CANARY_ENV") or os.environ.get("ENV") or "dev").strip().lower() == "production"


def _cookie_secure(request: Request) -> bool:
    """Production cookies are HTTPS-only, including behind TLS termination."""
    if _production():
        return True
    raw = os.environ.get("CANARY_COOKIE_SECURE")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return request.url.scheme == "https"


def _expected_audience() -> str | None:
    """Production cannot disable audience validation with an empty override."""
    raw = os.environ.get("SUPABASE_JWT_AUDIENCE", "").strip()
    return raw or ("authenticated" if _production() else None)


def _expected_issuer() -> str:
    supabase_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    if not supabase_url:
        raise RuntimeError("SUPABASE_URL is not set")
    return f"{supabase_url}/auth/v1"


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        _jwks_client = PyJWKClient(
            f"{_expected_issuer()}/.well-known/jwks.json",
            lifespan=300,
            timeout=5,
        )
    return _jwks_client


def _verify_token(token: str) -> str:
    """Blocking JWKS work runs in the thread pool, not the API event loop."""
    signing_key = _get_jwks_client().get_signing_key_from_jwt(token)
    audience = _expected_audience()
    payload = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256", "ES256"],
        audience=audience,
        issuer=_expected_issuer(),
        options={
            "verify_aud": audience is not None,
            "require": ["exp", "iss", "sub"],
        },
    )
    subject = payload["sub"]
    if not isinstance(subject, str):
        raise jwt.InvalidTokenError("Invalid subject")
    try:
        return str(UUID(subject))
    except ValueError as exc:
        raise jwt.InvalidTokenError("Invalid subject") from exc


async def get_current_user(
    request: Request,
    response: Response,
    authorization: str | None = Header(None),
    session_cookie: str | None = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> str:
    """Verify a Supabase access token and return its account UUID.

    Browser-native image, iframe, EventSource and download reads can use the
    HttpOnly cookie. Mutations must explicitly send a bearer token: SameSite
    cookies alone are not a CSRF boundary against a compromised sibling site.
    An explicitly invalid Authorization header never falls back to a cookie.
    """
    token = None
    if authorization is not None:
        scheme, _, credentials = authorization.partition(" ")
        if scheme.lower() != "bearer" or not credentials.strip():
            raise HTTPException(401, "Invalid authentication header")
        token = credentials.strip()
    elif session_cookie:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            raise HTTPException(401, "Bearer authentication is required for mutations")
        token = session_cookie
    if not token:
        raise HTTPException(401, "Missing authentication token")

    try:
        user_id = await run_in_threadpool(_verify_token, token)
    except RuntimeError as exc:
        raise HTTPException(500, str(exc)) from exc
    except jwt.PyJWTError as exc:
        raise HTTPException(401, "Invalid or expired token") from exc

    request.state.user_id = user_id
    try:
        import sentry_sdk

        sentry_sdk.set_user({"id": user_id})
        sentry_sdk.set_tag("request_id", getattr(request.state, "request_id", "unknown"))
    except Exception:
        # Error reporting is optional and must never affect authentication.
        pass
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        max_age=60 * 60,
        path="/",
    )
    return user_id
