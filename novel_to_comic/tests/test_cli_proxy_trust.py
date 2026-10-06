"""Proxy-header trust: an explicit proxy address must replace the trust-all default."""
import pytest
from click.testing import CliRunner

from novel_to_comic import cli as cli_module


@pytest.mark.parametrize("configured,flag,expected", [
    (None, True, "*"),
    ("172.29.88.1", True, "172.29.88.1"),
    ("172.29.88.1", False, None),
])
def test_forwarded_allow_ips(tmp_path, monkeypatch, configured, flag, expected):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.append(kwargs))
    monkeypatch.setattr("novel_to_comic.server.app.create_app", lambda **kwargs: object())
    monkeypatch.setattr("novel_to_comic.server.logging.configure_logging", lambda: None)
    monkeypatch.delenv("CANARY_FORWARDED_ALLOW_IPS", raising=False)
    if configured:
        monkeypatch.setenv("CANARY_FORWARDED_ALLOW_IPS", configured)
    args = ["serve", "--projects-dir", str(tmp_path)] + (["--proxy-headers"] if flag else [])
    result = CliRunner().invoke(cli_module.cli, args)
    assert result.exit_code == 0, result.output
    assert calls[0]["forwarded_allow_ips"] == expected
