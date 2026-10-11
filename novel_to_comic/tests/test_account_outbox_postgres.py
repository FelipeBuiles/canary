"""True signup capture on a disposable loopback database; never production."""
import json
import os
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from tests.test_credit_ledger_postgres import Ledger


@pytest.fixture
def signup_db():
    url = os.environ.get("CREDIT_TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("requires disposable PostgreSQL")
    target = urlsplit(url)
    assert target.hostname in {"127.0.0.1", "localhost"} and target.path == "/canary_test"
    db = Ledger(url)
    db.query("alter table auth.users add column if not exists created_at timestamptz not null default now(); alter table auth.users add column if not exists raw_user_meta_data jsonb default '{}';")
    migration = Path(__file__).resolve().parents[2] / "docs/migrations/2026-09-30-account-created-outbox.sql"
    db.query(migration.read_text())
    user = str(uuid.uuid4())
    try:
        yield db, user
    finally:
        db.query(f"delete from public.product_events where user_id='{user}'; delete from auth.users where id='{user}'; drop trigger account_created_event on auth.users; drop function public.enqueue_account_created_event(); drop function public.reconcile_account_created_events(); drop function public.signup_event_properties(jsonb,text); drop table public.signup_capture_boundary; drop index public.product_events_one_account_creation_per_user;")


def test_signup_atomic_idempotent_private_and_restricted(signup_db):
    db, user = signup_db
    db.query(f"insert into auth.users(id,created_at,raw_user_meta_data) values ('{user}',now() + interval '1 second', '{{\"acquisition\":{{\"source\":\"Reddit\",\"campaign\":\"SYNTHETIC SECRET\"}},\"private_title\":\"SYNTHETIC SECRET\"}}');")
    row = json.loads(db.query(f"select row_to_json(e) from public.product_events e where user_id='{user}';"))
    assert row["event_name"] == "account_created"
    assert row["properties_json"]["acquisition_source"] == "reddit"
    assert "SYNTHETIC SECRET" not in json.dumps(row)
    with pytest.raises(RuntimeError):
        db.query(f"insert into public.product_events(id,event_name,user_id,source,properties_json) values ('{uuid.uuid4()}','account_created','{user}','server','{{}}') on conflict(id) do nothing;")
    db.query(f"update auth.users set raw_user_meta_data='{{}}' where id='{user}';")
    assert db.query(f"select count(*) from public.product_events where user_id='{user}';") == "1"
    assert db.query("select has_function_privilege('anon','public.enqueue_account_created_event()','execute') or has_function_privilege('authenticated','public.enqueue_account_created_event()','execute');") == "f"
    assert db.query("select prosecdef from pg_proc where oid='public.enqueue_account_created_event()'::regprocedure;") == "t"


def test_signup_outbox_failure_is_recoverable_and_idempotent(signup_db):
    db, user = signup_db
    db.query("alter table public.product_events add constraint fixture_no_signup check (event_name <> 'account_created') not valid;")
    try:
        db.query(f"insert into auth.users(id) values ('{user}');")
        assert db.query(f"select count(*) from auth.users where id='{user}';") == "1"
        assert db.query(f"select count(*) from public.product_events where user_id='{user}';") == "0"
        with pytest.raises(RuntimeError):
            db.query("select public.reconcile_account_created_events();")
    finally:
        db.query("alter table public.product_events drop constraint fixture_no_signup;")
    result = json.loads(db.query("select public.reconcile_account_created_events();"))
    assert result["recovered"] == 1 and result["remaining"] == 0
    assert json.loads(db.query("select public.reconcile_account_created_events();"))["recovered"] == 0
    assert db.query(f"select properties_json->>'signup_capture_method' from public.product_events where user_id='{user}';") == "reconciled"
    assert db.query(f"select e.occurred_at=u.created_at from public.product_events e join auth.users u on u.id=e.user_id where u.id='{user}';") == "t"


def test_missing_outbox_preserves_signup_and_recovers(signup_db):
    db, user = signup_db
    db.query("alter table public.product_events rename to fixture_unavailable_events;")
    try:
        db.query(f"insert into auth.users(id) values ('{user}');")
        assert db.query(f"select count(*) from auth.users where id='{user}';") == "1"
    finally:
        db.query("alter table public.fixture_unavailable_events rename to product_events;")
    assert json.loads(db.query("select public.reconcile_account_created_events();"))["recovered"] == 1
    assert db.query("select has_function_privilege('service_role','public.reconcile_account_created_events()','execute');") == "t"
    assert db.query("select has_function_privilege('anon','public.reconcile_account_created_events()','execute') or has_function_privilege('authenticated','public.reconcile_account_created_events()','execute');") == "f"


def test_boundary_and_legacy_duplicate_are_preserved(signup_db):
    db, user = signup_db
    db.query(f"insert into auth.users(id,created_at) values ('{user}', now()-interval '1 day');")
    assert json.loads(db.query("select public.reconcile_account_created_events();"))["recovered"] == 0
    db.query(f"update auth.users set created_at=now()+interval '1 second' where id='{user}';")
    db.query(f"insert into public.product_events(id,event_name,user_id,source,properties_json) values ('{uuid.uuid4()}','account_created','{user}','server','{{}}');")
    result = json.loads(db.query("select public.reconcile_account_created_events();"))
    assert result == {"recovered": 0, "remaining": 0, "legacy_observed": 1}
    assert db.query(f"select count(*) from public.product_events where user_id='{user}';") == "1"


def test_ga4_migration_excludes_existing_signups_and_claims_new_signup_once(signup_db):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    db, user = signup_db
    new_user = str(uuid.uuid4())
    db.query(f"insert into auth.users(id) values ('{user}');")
    migration = Path(__file__).resolve().parents[2] / "docs/migrations/2026-10-11-ga4-signup-claim.sql"
    try:
        db.query(migration.read_text())
        assert db.query(f"select ga4_signup_claimed_at is not null from public.product_events where user_id='{user}';") == "t"
        db.query(f"insert into auth.users(id) values ('{new_user}');")
        barrier = Barrier(2)

        def claim(_):
            barrier.wait()
            return db.query(f"""update public.product_events set ga4_signup_claimed_at=now()
                where event_name='account_created' and user_id='{new_user}'
                and occurred_at >= now()-interval '24 hours' and occurred_at <= now()
                and ga4_signup_claimed_at is null returning id;""")

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(claim, range(2)))
        assert sum(bool(result) for result in results) == 1
        assert db.query(f"select count(*) from public.product_events where user_id='{new_user}' and event_name='account_created';") == "1"
    finally:
        db.query(f"delete from public.product_events where user_id='{new_user}'; delete from auth.users where id='{new_user}';")
