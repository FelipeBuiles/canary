"""Real PostgreSQL regressions; apply docs/supabase-schema.sql to an isolated DB first.

CREDIT_TEST_DATABASE_URL explicitly opts into database writes. Fixtures roll back
by deleting only their randomly generated auth account; never use production.
"""
import asyncio
import json
import os
import shutil
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from novel_to_comic.server import credits
from novel_to_comic.usage import ApiResult, UsageRecord


def _literal(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    return "'" + str(value).replace("'", "''") + "'"


class Ledger:
    lose_response = False

    def __init__(self, url):
        self.url = url

    def query(self, sql):
        result = subprocess.run(
            ["psql", "--dbname", self.url, "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-c", sql],
            capture_output=True, text=True,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout.strip()

    def rpc(self, name, params):
        def execute():
            args = ", ".join(f"{key} => {_literal(value)}" for key, value in params.items())
            raw = self.query(f"select to_json(public.{name}({args}));")
            if self.lose_response and name == "settle_model_usage_credits":
                self.lose_response = False
                raise TimeoutError("transaction committed; response lost")
            return SimpleNamespace(data=json.loads(raw) if raw else None)
        return SimpleNamespace(execute=execute)


@pytest.fixture
def ledger():
    url = os.environ.get("CREDIT_TEST_DATABASE_URL")
    if not url or not shutil.which("psql"):
        pytest.skip("requires psql and isolated CREDIT_TEST_DATABASE_URL with Canary schema")
    db = Ledger(url)
    user = str(uuid.uuid4())
    db.query(f"insert into auth.users(id) values ('{user}');")
    db.query(f"insert into public.credit_ledger(user_id, amount_credits) values ('{user}', 5);")
    try:
        yield db, user
    finally:
        db.query(f"delete from auth.users where id = '{user}';")


def test_atomic_reservations_across_process_connections(ledger):
    db, user = ledger
    barrier = Barrier(2)

    def reserve(_):
        barrier.wait()
        return db.rpc("reserve_stage_credits", {
            "p_user_id": user, "p_project_id": None, "p_stage": "cast",
            "p_amount_credits": 5, "p_job_id": str(uuid.uuid4()),
            "p_owner": str(uuid.uuid4()), "p_lease_seconds": 3600,
        }).execute().data

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(reserve, range(2)))
    assert results.count(None) == 1


def test_different_cast_jobs_compete_for_one_balance(ledger, tmp_path):
    from fastapi import HTTPException
    from novel_to_comic.server.credited_job import enqueue_credited_job

    db, user = ledger
    barrier = Barrier(2)
    app = MagicMock()
    app.state.generation_jobs = {}
    app.state.generation_queue = asyncio.Queue()
    app.state.generation_job_sequence = 0

    async def work():
        return ApiResult(value=None)

    def submit(asset):
        barrier.wait()
        try:
            return enqueue_credited_job(
                app, project_name="project", user_id=user, project_id=None,
                project_dir=tmp_path, stage="cast", kind="character_ref_regen",
                label=asset, payload={"char_id": asset}, work=work,
                debit_description="cast", estimate_credits=5,
                operations=(("image", "image-gpt-2"),),
            )[0]
        except HTTPException as exc:
            return exc.status_code

    with patch("novel_to_comic.server.credited_job.get_db", return_value=db), \
         patch.object(credits, "get_balance_credits", return_value=0):
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(submit, ["alice", "bob"]))
    assert results.count(402) == 1
    assert db.query(f"select count(*) from public.credit_ledger where user_id='{user}' and status='reserved';") == "1"


def test_committed_zero_settlement_is_immutable_after_response_loss(ledger):
    db, user = ledger
    job = str(uuid.uuid4())
    first = UsageRecord(provider="openai", model="gpt-5.6-terra", operation="text", input_tokens=1)
    second = UsageRecord(provider="openai", model="gpt-5.6-terra", operation="text", input_tokens=1)
    with patch.object(credits, "usage_to_credit_debit", return_value=(1, 0.001)):
        credits.debit_model_usage(db, user, None, first, description="first", job_id=job)
        db.lose_response = True
        credits.debit_model_usage(db, user, None, second, description="second", job_id=job)
        credits.debit_model_usage(
            db, user, None, second, description="recovered", job_id=str(uuid.uuid4()),
        )
        with pytest.raises(RuntimeError, match="different settlement"):
            credits.debit_model_usage(
                db, str(uuid.uuid4()), None, second,
                description="foreign replay", job_id=str(uuid.uuid4()),
            )
    assert db.query(f"select amount_credits from public.credit_ledger where usage_call_id='{second.call_id}';") == "0"
    assert db.query(f"select sum(amount_credits) from public.credit_ledger where job_id='{job}';") == "-1"
    assert db.query(f"select job_id from public.credit_ledger where usage_call_id='{second.call_id}';") == job
    with pytest.raises(RuntimeError, match="immutable"):
        db.query(f"update public.credit_ledger set amount_credits=-1 where usage_call_id='{second.call_id}';")


def test_foreign_live_and_expired_reservations(ledger):
    db, user = ledger
    live_owner, expired_owner = str(uuid.uuid4()), str(uuid.uuid4())
    def reserve(owner):
        return db.rpc("reserve_stage_credits", {
            "p_user_id": user, "p_project_id": None, "p_stage": "cast",
            "p_amount_credits": 1, "p_job_id": str(uuid.uuid4()),
            "p_owner": owner, "p_lease_seconds": 3600,
        }).execute().data
    live, expired, started = reserve(live_owner), reserve(expired_owner), reserve(expired_owner)
    assert db.rpc("check_credit_reservation_lease", {"p_reservation_id": live, "p_owner": expired_owner}).execute().data is False
    assert db.rpc("check_credit_reservation_lease", {"p_reservation_id": started, "p_owner": expired_owner}).execute().data is True
    db.query(f"update public.credit_ledger set reservation_expires_at=now()-interval '1 second' where id in ('{expired}', '{started}');")
    db.rpc("renew_credit_reservation_leases", {"p_owner": live_owner, "p_lease_seconds": 3600}).execute()
    statuses = json.loads(db.query(f"select json_object_agg(id,status) from public.credit_ledger where id in ('{live}','{expired}','{started}');"))
    assert statuses == {live: "reserved", expired: "released", started: "reserved"}
    with pytest.raises(RuntimeError, match="lease owner"):
        db.query(f"update public.credit_ledger set status='released' where id='{live}';")
    db.rpc("release_credit_reservation", {"p_reservation_id": live, "p_owner": expired_owner}).execute()
    assert db.query(f"select status from public.credit_ledger where id='{live}';") == "reserved"
    assert db.rpc("check_credit_reservation_lease", {"p_reservation_id": started, "p_owner": expired_owner}).execute().data is False
    # An unresolved started hold stays deducted, but cannot freeze the account.
    assert reserve(live_owner) is not None
    assert db.query(f"select status from public.credit_ledger where id='{started}';") == "reserved"
    assert reserve(live_owner) is not None
    assert reserve(live_owner) is not None
    assert reserve(live_owner) is None


def test_subscription_failure_keeps_evidence_outside_credit_ledger(ledger):
    db, user = ledger
    job = str(uuid.uuid4())
    call = str(uuid.uuid4())
    db.query(
        "insert into public.ai_usage_events "
        "(id, user_id, feature, operation, status, model_alias, funding) values "
        f"('{call}', '{user}', 'test.subscription', 'text', 'failed', "
        "'gpt-5.6-terra', 'codex_subscription');"
    )
    usage = UsageRecord(
        call_id=call, provider="openai", model="gpt-5.6-terra", operation="text",
        input_tokens=100, funding="codex_subscription",
    )
    credits.debit_model_usage(db, user, None, usage, description="failed", job_id=job)
    credits.debit_model_usage(db, user, None, usage, description="replayed", job_id=job)
    assert db.query(f"select count(*) from public.credit_ledger where usage_call_id='{call}';") == "0"
    assert db.query(f"select count(*) from public.ai_usage_events where id='{call}';") == "1"
    assert db.query(f"select balance_credits from public.user_credits where user_id='{user}';") == "5"
    assert db.query(
        f"select count(*) from public.ops_usage_reconciliation where usage_call_id='{call}';"
    ) == "0"


def test_sql_subscription_dollars_and_billable_flag_cannot_charge_or_poison_api_rounding(ledger):
    db, user = ledger
    job = str(uuid.uuid4())
    params = {
        "p_user_id": user, "p_project_id": None, "p_job_id": job,
        "p_stage": "extract", "p_description": "contradictory evidence",
        "p_usage_call_id": str(uuid.uuid4()), "p_provider": "openai",
        "p_model": "gpt-5.6-terra", "p_provider_model": None, "p_operation": "text",
        "p_input_tokens": 100, "p_output_tokens": 100, "p_image_count": 0,
        "p_cost_usd": 100, "p_cost_source": "provider_reported_cost",
        "p_pricing_snapshot": None, "p_credits_per_usd": 100, "p_markup": 1,
        "p_billable": True, "p_funding": "codex_subscription",
    }
    assert db.rpc("settle_model_usage_credits", params).execute().data == 0
    params.update(p_usage_call_id=str(uuid.uuid4()), p_funding="api", p_cost_usd=0.001)
    assert db.rpc("settle_model_usage_credits", params).execute().data == 1
    params.update(p_usage_call_id=str(uuid.uuid4()))
    assert db.rpc("settle_model_usage_credits", params).execute().data == 0
    assert db.query(f"select sum(amount_credits) from public.credit_ledger where job_id='{job}';") == "-1"


@pytest.mark.parametrize("provider_model", [None, "observed-image-model"])
def test_subscription_images_do_not_write_credit_ledger(ledger, provider_model):
    db, user = ledger
    usage = UsageRecord(
        provider="codex", model="image-gpt-2", provider_model=provider_model,
        operation="image", image_count=1, funding="codex_subscription",
    )
    credits.debit_model_usage(db, user, None, usage, description="subscription image")
    assert db.query(f"select count(*) from public.credit_ledger where usage_call_id='{usage.call_id}';") == "0"


@pytest.mark.parametrize("started", [False, True])
def test_deleted_project_hold_does_not_block_recreated_project(ledger, started):
    db, user = ledger
    old_project, new_project, owner = (str(uuid.uuid4()) for _ in range(3))
    db.query(f"insert into public.projects(id, user_id, name) values ('{old_project}', '{user}', 'same-story');")
    def reserve(project, amount):
        return db.rpc("reserve_stage_credits", {
            "p_user_id": user, "p_project_id": project, "p_stage": "extract",
            "p_amount_credits": amount, "p_job_id": str(uuid.uuid4()),
            "p_owner": owner, "p_lease_seconds": 3600,
        }).execute().data
    hold = reserve(old_project, 3)
    if started:
        assert db.rpc("check_credit_reservation_lease", {"p_reservation_id": hold, "p_owner": owner}).execute().data
    db.query(f"update public.credit_ledger set reservation_expires_at=now()-interval '1 second' where id='{hold}';")
    db.query(f"delete from public.projects where id='{old_project}';")
    db.query(f"insert into public.projects(id, user_id, name) values ('{new_project}', '{user}', 'same-story');")
    assert reserve(new_project, 2) is not None
    row = json.loads(db.query(f"select row_to_json(r) from (select project_id, status, amount_credits from public.credit_ledger where id='{hold}') r;"))
    assert row == {"project_id": None, "status": "reserved" if started else "released", "amount_credits": -3}
    assert db.rpc("check_credit_reservation_lease", {"p_reservation_id": hold, "p_owner": owner}).execute().data is False
    if started:
        assert reserve(new_project, 1) is None  # Liability still counts after deletion.
    else:
        assert reserve(new_project, 3) is not None  # Never-started hold is reclaimable.
