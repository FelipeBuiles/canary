import pytest

from novel_to_comic.server.security_headers import CONTENT_SECURITY_POLICY


def _connect_sources() -> set[str]:
    directive = next(d for d in CONTENT_SECURITY_POLICY.split("; ") if d.startswith("connect-src "))
    return set(directive.split()[1:])


@pytest.mark.parametrize("region", ["us", "eu"])
def test_csp_allows_posthog_ingestion_and_the_remote_config_that_enables_replay(region):
    # Blocking the assets host leaves events flowing but silently disables replay.
    assert {f"https://{region}.i.posthog.com", f"https://{region}-assets.i.posthog.com"} <= _connect_sources()


def test_csp_allows_google_tag_and_ga4_collection_without_inline_scripts():
    script = next(d for d in CONTENT_SECURITY_POLICY.split("; ") if d.startswith("script-src "))
    assert "https://www.googletagmanager.com" in script.split()
    assert "'unsafe-inline'" not in script.split()
    # Google's documented GA4 wildcards cover regional collection endpoints.
    assert {"https://*.google-analytics.com", "https://*.analytics.google.com",
            "https://*.googletagmanager.com"} <= _connect_sources()


def test_csp_allows_the_signup_bot_check():
    for name in ("script-src", "frame-src"):
        directive = next(d for d in CONTENT_SECURITY_POLICY.split("; ") if d.startswith(name + " "))
        assert "https://challenges.cloudflare.com" in directive.split()
