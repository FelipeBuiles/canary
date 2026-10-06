"""Supabase client singleton (service/secret key — never exposed to clients)."""

import os

import httpx
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

_client: Client | None = None
_httpx_client: httpx.Client | None = None


def reset_db() -> None:
    """Close the shared client only after every borrower has stopped using it.

    Request-level connection recovery must retry on the live pool instead;
    credit jobs and the lease manager retain this client across requests.
    """
    global _client, _httpx_client
    if _httpx_client is not None:
        _httpx_client.close()
    _client = None
    _httpx_client = None


def get_db() -> Client:
    global _client, _httpx_client
    if _client is None:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SECRET_KEY", "")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set")
        timeout = max(1, min(120, float(os.environ.get("CANARY_DATABASE_TIMEOUT_SECONDS", "30"))))
        _httpx_client = httpx.Client(http2=False, timeout=httpx.Timeout(timeout, connect=5, pool=5))
        _client = create_client(
            url,
            key,
            options=SyncClientOptions(httpx_client=_httpx_client),
        )
    return _client
