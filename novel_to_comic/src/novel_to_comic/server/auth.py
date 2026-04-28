"""JWT authentication dependency using Supabase JWKS (RS256/ES256)."""

import os

import jwt
from jwt import PyJWKClient
from fastapi import Cookie, Header, HTTPException, Request, Response

SESSION_COOKIE_NAME = "pulp_session"

# Lazily initialised — requires SUPABASE_URL at first request.
_jwks_client: PyJWKClient | None = None


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
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256", "ES256"],
            options={"verify_aud": False},
        )
        user_id = payload["sub"]
        if authorization:
            response.set_cookie(
                SESSION_COOKIE_NAME,
                token,
                httponly=True,
                secure=request.url.scheme == "https",
                samesite="lax",
                max_age=60 * 60,
                path="/",
            )
        return user_id
    except (KeyError, jwt.PyJWTError):
        raise HTTPException(status_code=401, detail="Invalid or expired token")
