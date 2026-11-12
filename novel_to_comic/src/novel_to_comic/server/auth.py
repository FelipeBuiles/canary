"""JWT authentication dependency using Supabase JWKS (RS256/ES256)."""

import os
import time
from uuid import UUID

import jwt
from jwt import PyJWKClient
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from starlette.concurrency import run_in_threadpool

SESSION_COOKIE_NAME = "pulp_session"
router = APIRouter()

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


def token_identity(request: Request) -> tuple[str | None, bool]:
    """The email and its verification, from this request's bearer token.

    Only for a request ``get_current_user`` has already authenticated: the
    token is decoded here without verifying it again. Supabase issues no
    session for an unconfirmed address while confirmation is required, so a
    token is unverified only when it says so or carries no email.
    """
    scheme, _, credentials = (request.headers.get("authorization") or "").partition(" ")
    if scheme.lower() != "bearer" or not credentials.strip():
        return None, False
    try:
        payload = jwt.decode(credentials.strip(), options={"verify_signature": False})
    except jwt.PyJWTError:
        return None, False
    email = payload.get("email")
    if not isinstance(email, str) or not email.strip():
        return None, False
    metadata = payload.get("user_metadata")
    verified = not (isinstance(metadata, dict) and metadata.get("email_verified") is False)
    return email, verified


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
    response.set_cookie(
        SESSION_COOKIE_NAME,
        token,
        httponly=True,
        secure=_cookie_secure(request),
        samesite="lax",
        # The cookie must not outlive the already verified access token.
        max_age=max(0, min(60 * 60, int(jwt.decode(token, options={"verify_signature": False})["exp"]) - int(time.time()))),
        path="/",
    )
    return user_id


@router.post("/session")
def synchronize_session(user: str = Depends(get_current_user)):
    """Bearer-authenticated account/refresh transitions update native reads."""
    return {"status": "ready"}


@router.post("/logout", status_code=204)
def logout(request: Request):
    """Expire native-read authorization even when the JWT is already expired."""
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/", httponly=True,
                           secure=_cookie_secure(request), samesite="lax")
    response.headers["Cache-Control"] = "no-store"
    # Private project images stay in the browser cache across reloads; drop
    # them so the next person on this browser cannot read them from disk.
    response.headers["Clear-Site-Data"] = '"cache"'
    return response
