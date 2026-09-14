"""A read retry must not invalidate clients held by credited generation jobs."""

import httpx
import pytest
from fastapi import HTTPException
from supabase import create_client
from supabase.lib.client_options import SyncClientOptions

from novel_to_comic.server import credits, db, deps


@pytest.mark.parametrize("found", [True, False])
def test_project_lookup_retry_keeps_the_lease_client_open(monkeypatch, found):
    reads = 0
    renewals = 0

    def handle(request):
        nonlocal reads, renewals
        if request.method == "GET":
            reads += 1
            if reads == 1:
                raise httpx.ConnectError("Temporary connection failure", request=request)
            return httpx.Response(200, json=[{"name": "novel"}] if found else [])
        assert request.url.path.endswith("/rpc/renew_credit_reservation_leases")
        renewals += 1
        return httpx.Response(200, json=1)

    with httpx.Client(transport=httpx.MockTransport(handle)) as transport:
        shared = create_client("https://database.example", "test-key",
                               options=SyncClientOptions(httpx_client=transport))
        monkeypatch.setattr(db, "_client", shared)
        monkeypatch.setattr(db, "_httpx_client", transport)
        monkeypatch.setattr(credits, "_lease_last_success", None)
        # The lease manager and an admitted job retain this same client while
        # unrelated browser requests look up projects.
        credits.renew_reservation_leases(shared)
        if found:
            assert deps._resolve_project_slug("user", "project") == "novel"
        else:
            with pytest.raises(HTTPException) as error:
                deps._resolve_project_slug("user", "project")
            assert error.value.status_code == 404
        assert not transport.is_closed
        assert db.get_db() is shared
        credits.renew_reservation_leases(shared)
        assert credits.reservation_leases_healthy()
    assert (reads, renewals) == (2, 2)
