"""Real role/constraint checks; opt in ONLY with an isolated test database."""
import os
import shutil
import subprocess
from uuid import uuid4

import pytest


@pytest.fixture
def query():
    url = os.environ.get("CREDIT_TEST_DATABASE_URL")
    if not url or not shutil.which("psql"):
        pytest.skip("requires isolated PostgreSQL with base schema + security migration")

    def execute(sql):
        result = subprocess.run(
            ["psql", "--dbname", url, "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-c", sql],
            text=True, capture_output=True, check=False,
        )
        if result.returncode:
            raise RuntimeError(result.stderr)
        return result.stdout.strip()
    return execute


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_browser_roles_have_no_project_write_grants(query, role):
    for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER"):
        assert query(f"select has_table_privilege('{role}', 'public.projects', '{privilege}');") == "f"
    for privilege in ("INSERT", "UPDATE", "REFERENCES"):
        assert query(f"select has_any_column_privilege('{role}', 'public.projects', '{privilege}');") == "f"
    assert query(f"select has_table_privilege('{role}', 'public.projects', 'SELECT');") == "t"


def test_service_role_retains_project_authority(query):
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert query(f"select has_table_privilege('service_role', 'public.projects', '{privilege}');") == "t"


def test_browser_cannot_call_money_mutation_rpc(query):
    signatures = (
        "public.reserve_stage_credits(uuid,uuid,text,integer,uuid,uuid,integer,numeric,numeric)",
        "public.authorize_model_call_credits(uuid,uuid,text,integer,uuid,numeric,numeric)",
        "public.release_model_call_authorization(uuid,text)",
    )
    for signature in signatures:
        for role in ("anon", "authenticated"):
            assert query(f"select has_function_privilege('{role}', '{signature}', 'EXECUTE');") == "f"
        assert query(f"select has_function_privilege('service_role', '{signature}', 'EXECUTE');") == "t"
    for role in ("anon", "authenticated"):
        assert query(f"select has_table_privilege('{role}', 'public.credit_call_authorizations', 'SELECT');") == "f"


def test_row_visibility_is_owned_or_explicitly_public(query):
    owner, victim = str(uuid4()), str(uuid4())
    result = query(f"""
      begin;
      insert into auth.users(id) values ('{owner}'), ('{victim}');
      insert into public.projects(user_id,name,is_public) values
        ('{owner}', 'own-private', false),
        ('{victim}', 'victim-private', false),
        ('{victim}', 'public-story', true);
      set local role authenticated;
      set local request.jwt.claim.sub = '{owner}';
      select string_agg(name, ',' order by name) from public.projects;
      rollback;
    """)
    assert result == "own-private,public-story"


def test_constraint_rejects_storage_traversal_for_service_writes(query):
    user = str(uuid4())
    # Each psql process exits on failure; its uncommitted transaction rolls back.
    with pytest.raises(RuntimeError, match="projects_safe_storage_name"):
        query(f"""
          begin;
          insert into auth.users(id) values ('{user}');
          set local role service_role;
          insert into public.projects(user_id,name) values ('{user}', '../victim/story');
          rollback;
        """)


def test_browser_update_is_rejected_not_silently_allowed_by_owner_policy(query):
    user = str(uuid4())
    with pytest.raises(RuntimeError, match="permission denied"):
        query(f"""
          begin;
          insert into auth.users(id) values ('{user}');
          insert into public.projects(user_id,name) values ('{user}', 'own-story');
          set local role authenticated;
          set local request.jwt.claim.sub = '{user}';
          update public.projects set name = 'renamed' where user_id = '{user}';
          rollback;
        """)
