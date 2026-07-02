"""Brand + legal identifiers surfaced to docs, emails, and Stripe.

All values default to the public Scenewright brand so the app is usable in
local dev without any configuration. In production these are overridden via
environment variables (see `.env.example`).

These are *display* values only — they don't change runtime behaviour. The
fields exist so the billing flow, legal pages, and report channels all read
from one place instead of hardcoding the brand name and contact email in a
dozen spots.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


def _env(name: str, default: str) -> str:
    """Trimmed env read, falling back to default when unset or empty."""
    val = os.environ.get(name, "").strip()
    return val or default


@dataclass(frozen=True)
class Branding:
    """Display-only brand + legal identity used across the app surface."""

    #: Product name shown in Stripe line items, legal docs, footer.
    product_name: str
    #: Public support / abuse-report contact. Must be monitored.
    support_email: str
    #: DMCA / legal notices contact (often the same address as support).
    legal_email: str
    #: Optional URL the Stripe checkout flow points users at for ToS.
    terms_url: str

    def __post_init__(self) -> None:
        # URLs should be absolute before reaching Stripe / external links.
        if self.terms_url and not self.terms_url.startswith(("http://", "https://")):
            object.__setattr__(self, "terms_url", f"https://{self.terms_url}")


def get_branding() -> Branding:
    """Read brand/legal identity from the environment.

    Overridable env vars (all optional — sensible Scenewright defaults):
      SCENEWRIGHT_PRODUCT_NAME  — product/brand name (default: Scenewright)
      SCENEWRIGHT_SUPPORT_EMAIL — support + abuse contact (default: hello@...)
      SCENEWRIGHT_LEGAL_EMAIL   — DMCA / legal notices (default: legal@...)
      SCENEWRIGHT_TERMS_URL     — absolute ToS URL for Stripe (default: /legal/terms)
    """
    product = _env("SCENEWRIGHT_PRODUCT_NAME", "Scenewright")
    domain = "scenewright.ink"
    support = _env("SCENEWRIGHT_SUPPORT_EMAIL", f"hello@{domain}")
    legal = _env("SCENEWRIGHT_LEGAL_EMAIL", f"legal@{domain}")
    terms = _env("SCENEWRIGHT_TERMS_URL", "https://scenewright.ink/legal/terms")
    return Branding(
        product_name=product,
        support_email=support,
        legal_email=legal,
        terms_url=terms,
    )
