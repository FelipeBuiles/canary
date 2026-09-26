"""Rate-limit keys must not come from client-supplied forwarding headers."""
import pytest
from starlette.requests import Request

from novel_to_comic.server.ratelimit import client_ip


def request(headers: dict[str, str], peer: str = "172.16.0.2") -> Request:
    return Request({
        "type": "http", "method": "GET", "path": "/", "query_string": b"",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": (peer, 1234),
    })


def test_off_fly_uses_the_direct_peer(monkeypatch):
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    assert client_ip(request({"Fly-Client-IP": "9.9.9.9", "CF-Connecting-IP": "8.8.8.8"}, "127.0.0.1")) == "127.0.0.1"


def test_fly_ignores_spoofed_forwarded_for_and_edge_header(monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "canary-web")
    # A direct visitor to the Fly hostname cannot pose as Cloudflare.
    headers = {"Fly-Client-IP": "203.0.113.7", "CF-Connecting-IP": "8.8.8.8",
               "X-Forwarded-For": "1.2.3.4, 203.0.113.7"}
    assert client_ip(request(headers)) == "203.0.113.7"


@pytest.mark.parametrize("edge", ["172.64.80.1", "2606:4700::1"])
def test_fly_trusts_the_visitor_named_by_cloudflare(monkeypatch, edge):
    monkeypatch.setenv("FLY_APP_NAME", "canary-web")
    headers = {"Fly-Client-IP": edge, "CF-Connecting-IP": "198.51.100.4",
               "X-Forwarded-For": "1.2.3.4, 198.51.100.4, " + edge}
    assert client_ip(request(headers)) == "198.51.100.4"


def test_edge_ranges_are_configurable(monkeypatch):
    monkeypatch.setenv("FLY_APP_NAME", "canary-web")
    monkeypatch.setenv("CANARY_TRUSTED_EDGE_CIDRS", "")
    assert client_ip(request({"Fly-Client-IP": "172.64.80.1", "CF-Connecting-IP": "198.51.100.4"})) == "172.64.80.1"
