"""Operator settings: stored value, then environment, then the reader's default."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_to_comic import runtime_settings, sponsored_budget
from novel_to_comic.server import card_grant, cold_open_jobs


class _Table:
    def __init__(self, rows):
        self.rows, self._key = rows, None

    def select(self, _columns):
        return self

    def upsert(self, row, on_conflict):
        assert on_conflict == "key"
        self.rows[row["key"]] = row["value"]
        return self

    def delete(self):
        self._delete = True
        return self

    def eq(self, _column, value):
        self.rows.pop(value, None)
        return self

    def execute(self):
        return type("Result", (), {"data": [{"key": k, "value": v} for k, v in self.rows.items()]})()


class _Database:
    def __init__(self, rows=None):
        self.rows = dict(rows or {})

    def table(self, name):
        assert name == "app_settings"
        return _Table(self.rows)


@pytest.fixture
def database(monkeypatch):
    db = _Database()
    monkeypatch.setattr(runtime_settings, "_database", lambda: db)
    runtime_settings.use_loader(None)
    return db


def test_stored_value_overrides_environment_and_removal_restores_it(database, monkeypatch):
    monkeypatch.setenv("CANARY_CARD_GRANT_CREDITS", "500")
    assert card_grant.grant_credits() == 500

    runtime_settings.set_override("CANARY_CARD_GRANT_CREDITS", " 1200 ")
    assert database.rows == {"CANARY_CARD_GRANT_CREDITS": "1200"}
    assert card_grant.grant_credits() == 1200

    runtime_settings.clear_override("CANARY_CARD_GRANT_CREDITS")
    assert card_grant.grant_credits() == 500


def test_stored_values_reach_every_pilot_reader(database):
    database.rows.update({
        "CANARY_FREE_OPENING_MAX_CHARS": "20000", "CANARY_SPONSORED_DAILY_USD": "4.5",
        "CANARY_IMAGE_CASH_ROUTES_DISABLED": "true", "CANARY_COLD_OPEN_PER_ACCOUNT": "0",
        "CANARY_SECRET_NOT_REGISTERED": "ignored",
    })
    runtime_settings.reset()
    assert cold_open_jobs.free_opening_max_chars() == 20000
    assert sponsored_budget.daily_ceiling_usd() == 4.5
    assert sponsored_budget.cash_routes_disabled() is True
    assert cold_open_jobs.per_account_limit() == 0


@pytest.mark.parametrize(("key", "value", "reason"), [
    ("CANARY_CARD_GRANT_CREDITS", "10001", "highest allowed"),
    ("CANARY_CARD_GRANT_CREDITS", "-1", "lowest allowed"),
    ("CANARY_CARD_GRANT_CREDITS", "many", "whole number"),
    ("CANARY_SPONSORED_DAILY_USD", "nan", "Use a number"),
    ("CANARY_IMAGE_CASH_ROUTES_DISABLED", "maybe", "true or false"),
    ("CANARY_CARD_GRANT_ENDS", "next week", "date"),
    ("CANARY_TURNSTILE_SITE_KEY", "<script>", "characters"),
    ("CANARY_SPONSORED_GRANT_ROUTES_ONLY", "false", "host environment"),
    ("STRIPE_SECRET_KEY", "sk_live_x", "Unknown"),
    ("CANARY_CARD_GRANT_SEATS", " ", "remove the override"),
])
def test_invalid_values_are_refused_before_anything_is_stored(database, key, value, reason):
    with pytest.raises(runtime_settings.InvalidSetting, match=reason):
        runtime_settings.set_override(key, value)
    assert database.rows == {}


def test_environment_only_setting_ignores_a_stored_row(database, monkeypatch):
    database.rows["CANARY_SPONSORED_GRANT_ROUTES_ONLY"] = "false"
    monkeypatch.setenv("CANARY_SPONSORED_GRANT_ROUTES_ONLY", "true")
    runtime_settings.reset()
    assert sponsored_budget.grant_routes_only() is True


def test_unreadable_table_holds_give_aways_off_until_it_has_been_read(monkeypatch):
    monkeypatch.setenv("CANARY_CARD_GRANT_CREDITS", "1200")
    monkeypatch.setenv("CANARY_FREE_OPENING_MAX_CHARS", "20000")
    monkeypatch.setenv("CANARY_CARD_GRANT_SEATS", "40")

    def broken():
        raise ConnectionError("database unreachable")

    runtime_settings.use_loader(broken)
    assert runtime_settings.store_state() == "unavailable"
    assert card_grant.grant_credits() == 0
    assert cold_open_jobs.free_opening_max_chars() == 0
    # Settings that give nothing away keep their environment value.
    assert card_grant.seats() == 40
    assert {row["key"]: row["source"] for row in runtime_settings.effective()}["CANARY_CARD_GRANT_CREDITS"] == "safe"


def test_last_values_read_stay_in_force_when_a_later_read_fails(monkeypatch):
    calls = []

    def loader():
        calls.append(1)
        if len(calls) > 1:
            raise ConnectionError("database unreachable")
        return {"CANARY_CARD_GRANT_CREDITS": "1200"}

    runtime_settings.use_loader(loader)
    assert card_grant.grant_credits() == 1200
    monkeypatch.setattr(runtime_settings, "_next_read", 0.0)
    assert card_grant.grant_credits() == 1200
    assert len(calls) == 2 and runtime_settings.store_state() == "loaded"


def test_table_is_read_once_per_refresh_window():
    calls = []
    runtime_settings.use_loader(lambda: calls.append(1) or {})
    for _ in range(5):
        runtime_settings.raw("CANARY_CARD_GRANT_SEATS")
    assert len(calls) == 1


def test_missing_table_means_environment_only_and_no_writes(monkeypatch):
    class Missing(Exception):
        code = "PGRST205"

    class NoTable:
        def table(self, _name):
            raise Missing("Could not find the table 'public.app_settings' in the schema cache")

    monkeypatch.setattr(runtime_settings, "_database", lambda: NoTable())
    monkeypatch.setenv("CANARY_CARD_GRANT_CREDITS", "700")
    runtime_settings.use_loader(None)
    assert runtime_settings.store_state() == "absent"
    assert card_grant.grant_credits() == 700
    with pytest.raises(runtime_settings.SettingsStoreUnavailable):
        runtime_settings.set_override("CANARY_CARD_GRANT_CREDITS", "900")


def test_invalid_stored_row_is_ignored(database, monkeypatch):
    database.rows["CANARY_CARD_GRANT_CREDITS"] = "999999"
    monkeypatch.setenv("CANARY_CARD_GRANT_CREDITS", "300")
    runtime_settings.reset()
    assert card_grant.grant_credits() == 300


def _operator_client(monkeypatch):
    from novel_to_comic.server.routers.backoffice import router

    monkeypatch.setenv("CANARY_OPS_TOKEN", "operator-secret")
    app = FastAPI()
    app.include_router(router, prefix="/api/ops/backoffice")
    return TestClient(app), {"X-Canary-Ops-Token": "operator-secret"}


def test_operator_endpoints_require_the_token_and_report_sources(database, monkeypatch):
    client, headers = _operator_client(monkeypatch)
    path = "/api/ops/backoffice/settings"
    assert client.get(path).status_code in {401, 403}
    assert client.put(f"{path}/CANARY_CARD_GRANT_CREDITS", json={"value": "1200"}).status_code in {401, 403}

    monkeypatch.setenv("CANARY_CARD_GRANT_SEATS", "40")
    saved = client.put(f"{path}/CANARY_CARD_GRANT_CREDITS", json={"value": "1200"}, headers=headers)
    assert saved.status_code == 200
    rows = {row["key"]: row for row in saved.json()["settings"]}
    assert saved.json()["store"] == "loaded"
    assert (rows["CANARY_CARD_GRANT_CREDITS"]["value"], rows["CANARY_CARD_GRANT_CREDITS"]["source"]) == ("1200", "database")
    assert (rows["CANARY_CARD_GRANT_SEATS"]["value"], rows["CANARY_CARD_GRANT_SEATS"]["source"]) == ("40", "environment")
    assert rows["CANARY_SPONSORED_GRANT_ROUTES_ONLY"]["editable"] is False

    refused = client.put(f"{path}/CANARY_CARD_GRANT_CREDITS", json={"value": "50000"}, headers=headers)
    assert refused.status_code == 422 and "highest allowed" in refused.json()["detail"]
    assert database.rows["CANARY_CARD_GRANT_CREDITS"] == "1200"

    cleared = client.delete(f"{path}/CANARY_CARD_GRANT_CREDITS", headers=headers)
    assert cleared.status_code == 200 and database.rows == {}


def test_operator_write_without_the_table_changes_nothing(monkeypatch):
    client, headers = _operator_client(monkeypatch)
    response = client.put("/api/ops/backoffice/settings/CANARY_CARD_GRANT_CREDITS", json={"value": "1200"}, headers=headers)
    assert response.status_code == 409
    assert response.json()["detail"].startswith("The settings table is not installed")


def test_public_config_returns_only_the_site_key(tmp_path, monkeypatch):
    from novel_to_comic.server.app import create_app

    runtime_settings.use_loader(lambda: {"CANARY_TURNSTILE_SITE_KEY": "0x4AAAAAAA-site", "CANARY_CARD_GRANT_CREDITS": "1200"})
    response = TestClient(create_app(tmp_path, dev=False)).get("/api/public-config")
    assert response.status_code == 200
    assert response.json() == {"turnstile_site_key": "0x4AAAAAAA-site"}


@pytest.mark.parametrize("method", ["PUT", "DELETE"])
def test_local_operator_desk_may_change_production_settings(tmp_path, monkeypatch, method):
    from novel_to_comic.server.app import create_app

    origin = "http://localhost:5173"
    monkeypatch.setenv("CANARY_BACKOFFICE_ORIGINS", origin)
    monkeypatch.setenv("CANARY_OPS_TOKEN", "operator-secret")
    production = TestClient(create_app(tmp_path, dev=False))
    headers = {"Origin": origin, "Access-Control-Request-Method": method,
               "Access-Control-Request-Headers": "content-type,x-canary-ops-token"}
    path = "/api/ops/backoffice/settings/CANARY_FREE_OPENING_MAX_CHARS"
    preflight = production.options(path, headers=headers)
    assert preflight.status_code == 200
    assert method in preflight.headers["access-control-allow-methods"]
    assert production.options(path, headers={**headers, "Origin": "https://untrusted.example"}).status_code == 400
