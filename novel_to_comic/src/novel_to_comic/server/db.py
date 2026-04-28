"""Supabase client singleton (service/secret key — never exposed to clients)."""

import os

from supabase import Client, create_client

_client: Client | None = None


def get_db() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL", "")
        key = os.environ.get("SUPABASE_SECRET_KEY", "")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SECRET_KEY must be set")
        _client = create_client(url, key)
    return _client
