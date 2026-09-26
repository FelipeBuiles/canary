"""Production browser-security headers applied to every HTTP response."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response


CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'self'",
        "object-src 'none'",
        "frame-ancestors 'none'",
        "script-src 'self' https://js.stripe.com",
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' data: https://fonts.gstatic.com",
        "img-src 'self' data: blob: https:",
        (
            "connect-src 'self' https://*.supabase.co wss://*.supabase.co "
            "https://*.stripe.com https://us.i.posthog.com https://eu.i.posthog.com"
        ),
        "frame-src https://js.stripe.com https://hooks.stripe.com",
        "worker-src 'self' blob:",
        "form-action 'self' https://checkout.stripe.com",
    )
)

SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": (
        "camera=(), microphone=(), geolocation=(), payment=(self \"https://js.stripe.com\")"
    ),
}


async def security_headers_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    """Attach the production header contract without overwriting route headers."""
    response = await call_next(request)
    for name, value in SECURITY_HEADERS.items():
        response.headers.setdefault(name, value)
    return response
