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
from unittest.mock import patch

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
            "p_credits_per_usd": 100, "p_markup": 1,
        }).execute().data

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(reserve, range(2)))
    assert results.count(None) == 1


def test_different_cast_jobs_compete_for_one_balance(ledger, tmp_path):
    from fastapi import HTTPException
    from novel_to_comic.config import Config
    from novel_to_comic.server.generation_jobs import GenerationJob
    from novel_to_comic.server.job_commands import command
    from novel_to_comic.server.job_execution import execute_command
    from novel_to_comic.state import create_initial_state, save_state

    db, user = ledger
    directory = tmp_path / user / "book"
    directory.mkdir(parents=True)
    save_state(create_initial_state("Book", "source.txt"), directory)
    app = SimpleNamespace(state=SimpleNamespace(projects_dir=tmp_path))
    jobs = []
    for asset in ("alice", "bob"):
        spec = command("cast_asset", directory, Config(), asset_id=asset, kind="character_ref_regen")
        spec = spec.model_copy(update={"user_id": user, "stage": "cast", "reservation_credits": 5,
                                       "ledger_job_id": str(uuid.uuid4())})
        jobs.append(GenerationJob(id=str(uuid.uuid4()), project_name=f"{user}:book",
                                  kind="character_ref_regen", label=asset, sequence=len(jobs),
                                  runner=None, payload={"char_id": asset}, command=spec))

    async def exercise():
        entered, release = asyncio.Event(), asyncio.Event()
        calls = []
        async def operation(_app, job, *_args):
            calls.append(job.label)
            entered.set()
            await release.wait()
            return ApiResult(value=None), None
        # Simulate competing execution connections; the database enforces the
        # hold even if the process-local scheduler cannot coordinate them.
        with patch("novel_to_comic.server.db.get_db", return_value=db), \
             patch.object(credits, "get_balance_credits", return_value=0), \
             patch("novel_to_comic.server.job_execution._operate", new=operation):
            tasks = [asyncio.create_task(execute_command(app, job)) for job in jobs]
            try:
                await asyncio.wait_for(entered.wait(), 5)
                finished, _ = await asyncio.wait(tasks, timeout=5, return_when=asyncio.FIRST_COMPLETED)
                assert len(finished) == 1
                error = next(iter(finished)).exception()
                assert isinstance(error, HTTPException) and error.status_code == 402
                assert db.query(f"select count(*) from public.credit_ledger where user_id='{user}' and status='reserved';") == "1"
                assert len(calls) == 1
            finally:
                release.set()
                results = await asyncio.gather(*tasks, return_exceptions=True)
            assert sum(isinstance(result, HTTPException) for result in results) == 1
            assert db.query(f"select count(*) from public.credit_ledger where user_id='{user}' and status='reserved';") == "0"
    asyncio.run(exercise())


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
            "p_credits_per_usd": 100, "p_markup": 1,
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


def _model_settlement(user, job, call, cost):
    return {
        "p_user_id": user, "p_project_id": None, "p_job_id": job,
        "p_stage": "cast", "p_description": "model call",
        "p_usage_call_id": call, "p_provider": "openai",
        "p_model": "gpt-5.6-terra", "p_provider_model": None,
        "p_operation": "text", "p_input_tokens": 10,
        "p_output_tokens": 10, "p_image_count": 0,
        "p_cost_usd": cost, "p_cost_source": "provider_reported_cost",
        "p_pricing_snapshot": None, "p_credits_per_usd": 100,
        "p_markup": 1, "p_billable": True, "p_funding": "api",
    }


def test_concurrent_call_guarantees_top_up_only_from_free_balance(ledger):
    db, user = ledger
    job, owner = str(uuid.uuid4()), str(uuid.uuid4())
    hold = db.rpc("reserve_stage_credits", {
        "p_user_id": user, "p_project_id": None, "p_stage": "cast",
        "p_amount_credits": 3, "p_job_id": job,
        "p_owner": owner, "p_lease_seconds": 3600,
        "p_credits_per_usd": 100, "p_markup": 1,
    }).execute().data
    assert hold

    def authorize(call):
        return db.rpc("authorize_model_call_credits", {
            "p_user_id": user, "p_job_id": job, "p_usage_call_id": call,
            "p_amount_credits": 2, "p_owner": owner,
            "p_credits_per_usd": 100, "p_markup": 1,
        }).execute().data

    first, second, third = (str(uuid.uuid4()) for _ in range(3))
    assert authorize(first) is True
    assert authorize(second) is True  # Extends the hold by one credit.
    assert authorize(third) is False
    assert db.query(f"select balance_credits from public.user_credits where user_id='{user}';") == "1"
    assert db.rpc("settle_model_usage_credits", _model_settlement(user, job, first, 0.01)).execute().data == 1
    assert authorize(third) is True  # Settled credit left the hold atomically.
    assert db.query(f"select balance_credits from public.user_credits where user_id='{user}';") == "0"


def test_provider_overrun_never_spends_unreserved_credits(ledger):
    db, user = ledger
    job, owner, call = (str(uuid.uuid4()) for _ in range(3))
    db.rpc("reserve_stage_credits", {
        "p_user_id": user, "p_project_id": None, "p_stage": "cast",
        "p_amount_credits": 3, "p_job_id": job,
        "p_owner": owner, "p_lease_seconds": 3600,
        "p_credits_per_usd": 100, "p_markup": 1,
    }).execute().data
    params = {
        "p_user_id": user, "p_job_id": job, "p_usage_call_id": call,
        "p_amount_credits": 2, "p_owner": owner,
        "p_credits_per_usd": 100, "p_markup": 1,
    }
    assert db.rpc("authorize_model_call_credits", params).execute().data is True
    settle = _model_settlement(user, job, call, 0.04)
    assert db.rpc("settle_model_usage_credits", settle).execute().data == 3
    assert db.rpc("settle_model_usage_credits", settle).execute().data == 3
    assert db.query(f"select unfunded_credits from public.credit_ledger where usage_call_id='{call}';") == "1"
    assert db.query(f"select balance_credits from public.user_credits where user_id='{user}';") == "2"
    assert db.rpc("authorize_model_call_credits", {
        **params, "p_usage_call_id": str(uuid.uuid4()),
    }).execute().data is False
    assert db.query(f"select issue from public.ops_usage_reconciliation where usage_call_id='{call}';") == "unfunded_provider_usage"


def test_call_rejects_billing_rate_change_within_reserved_job(ledger):
    db, user = ledger
    job, owner = str(uuid.uuid4()), str(uuid.uuid4())
    hold = db.rpc("reserve_stage_credits", {
        "p_user_id": user, "p_project_id": None, "p_stage": "cast",
        "p_amount_credits": 2, "p_job_id": job,
        "p_owner": owner, "p_lease_seconds": 3600,
        "p_credits_per_usd": 100, "p_markup": 1,
    }).execute().data
    assert hold
    with pytest.raises(RuntimeError, match="billing terms changed"):
        db.rpc("authorize_model_call_credits", {
            "p_user_id": user, "p_job_id": job,
            "p_usage_call_id": str(uuid.uuid4()), "p_amount_credits": 1,
            "p_owner": owner, "p_credits_per_usd": 200, "p_markup": 1,
        }).execute()
    assert db.query(f"select balance_credits from public.user_credits where user_id='{user}';") == "3"


def test_unbilled_call_releases_its_pending_guarantee(ledger):
    db, user = ledger
    job, owner, first, second = (str(uuid.uuid4()) for _ in range(4))
    hold = db.rpc("reserve_stage_credits", {
        "p_user_id": user, "p_project_id": None, "p_stage": "cast",
        "p_amount_credits": 1, "p_job_id": job,
        "p_owner": owner, "p_lease_seconds": 3600,
        "p_credits_per_usd": 100, "p_markup": 1,
    }).execute().data
    assert hold
    params = {
        "p_user_id": user, "p_job_id": job, "p_usage_call_id": first,
        "p_amount_credits": 1, "p_owner": owner,
        "p_credits_per_usd": 100, "p_markup": 1,
    }
    assert db.rpc("authorize_model_call_credits", params).execute().data is True
    db.rpc("release_model_call_authorization", {
        "p_user_id": user, "p_usage_call_id": first,
    }).execute()
    assert db.rpc("authorize_model_call_credits", {
        **params, "p_usage_call_id": second,
    }).execute().data is True
    assert db.query(f"select balance_credits from public.user_credits where user_id='{user}';") == "4"


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
            "p_credits_per_usd": 100, "p_markup": 1,
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
