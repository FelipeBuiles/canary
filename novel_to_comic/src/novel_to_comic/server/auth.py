"""JWT authentication dependency using Supabase JWKS (RS256/ES256)."""

import os

import jwt
from jwt import PyJWKClient
from fastapi import Cookie, Header, HTTPException, Request, Response

SESSION_COOKIE_NAME = "pulp_session"

# Lazily initialised — requires SUPABASE_URL at first request.
_jwks_client: PyJWKClient | None = None


def _cookie_secure(request: Request) -> bool:
    """Decide whether to mark the session cookie Secure (HTTPS-only).

    Explicit opt-in via CANARY_COOKIE_SECURE=true wins and is the correct
    setting in production behind a TLS-terminating proxy. Without it we fall
    back to scheme detection — but note that behind a proxy ``request.url``
    reports the *internal* scheme (http) unless Uvicorn runs with
    ``--proxy-headers``, so prod must set the env flag explicitly.
    """
    raw = os.environ.get("CANARY_COOKIE_SECURE")
    if raw is not None:
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return request.url.scheme == "https"


def _expected_audience() -> str | None:
    """The JWT audience to enforce (e.g. Supabase's "authenticated").

    Resolution order:

    1. ``SUPABASE_JWT_AUDIENCE`` — explicit override (any value, incl. empty
       string to opt out entirely).
    2. In production (``CANARY_ENV=production``) — defaults to Supabase's
       standard ``"authenticated"`` audience. Supabase JWTs always carry this
       claim, so enforcing it costs nothing and blocks tokens minted for a
       different audience.
    3. Elsewhere (dev/test) — ``None`` (no audience check), preserving
       backwards compatibility for hand-built test tokens.
    """
    if "SUPABASE_JWT_AUDIENCE" in os.environ:
        raw = os.environ["SUPABASE_JWT_AUDIENCE"].strip()
        return raw or None
    if (os.environ.get("CANARY_ENV") or "").lower() == "production":
        return "authenticated"
    return None


def _get_jwks_client() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        supabase_url = os.environ.get("SUPABASE_URL", "").rstrip("/")
        if not supabase_url:
            raise RuntimeError("SUPABASE_URL is not set")
        _jwks_client = PyJWKClient(
            f"{supabase_url}/auth/v1/.well-known/jwks.json",
            lifespan=300,  # cache keys for 5 minutes; re-fetches on unknown kid
        )
    return _jwks_client


async def get_current_user(
    request: Request,
    response: Response,
    authorization: str | None = Header(None),
    session_cookie: str | None = Cookie(None, alias=SESSION_COOKIE_NAME),
) -> str:
    """Verify a Supabase-issued JWT and return the user_id (sub claim).

    Normal API fetches send the bearer token. Browser-native consumers such as
    EventSource, img, iframe, and window.open cannot set Authorization headers,
    so successful bearer-authenticated requests also refresh an HttpOnly cookie
    that those same-origin requests can use.
    """
    token = None
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
    elif session_cookie:
        token = session_cookie

    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")

    try:
        client = _get_jwks_client()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))
    try:
        signing_key = client.get_signing_key_from_jwt(token)
        expected_audience = _expected_audience()
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            audience=expected_audience,
            # verify_aud only has an effect when `audience` is provided, so this
            # is a no-op unless SUPABASE_JWT_AUDIENCE is set in production.
            options={"verify_aud": expected_audience is not None},
        )
        user_id = payload["sub"]
        # Refresh the HttpOnly session cookie so browser-native consumers
        # (img, EventSource, etc.) that can only use cookies stay authenticated.
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
    except (KeyError, jwt.PyJWTError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
