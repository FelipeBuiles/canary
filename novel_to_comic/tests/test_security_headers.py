import pytest

from novel_to_comic.server.security_headers import CONTENT_SECURITY_POLICY


def _connect_sources() -> set[str]:
    directive = next(d for d in CONTENT_SECURITY_POLICY.split("; ") if d.startswith("connect-src "))
    return set(directive.split()[1:])


@pytest.mark.parametrize("region", ["us", "eu"])
def test_csp_allows_posthog_ingestion_and_the_remote_config_that_enables_replay(region):
    # Blocking the assets host leaves events flowing but silently disables replay.
    assert {f"https://{region}.i.posthog.com", f"https://{region}-assets.i.posthog.com"} <= _connect_sources()
