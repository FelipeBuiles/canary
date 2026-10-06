-- Historical security delta, now included in docs/supabase-schema.sql.
-- Legacy replay remains safe; the canonical schema alone converges security.
-- Apply as the database owner, not a browser role.
-- This migration changes authorization, not customer files or ledger balances.
begin;

-- Existing Supabase projects may inherit table and column write grants. RLS
-- ownership must not allow bypassing API admission, quotas or path validation.
revoke all on public.projects from public, anon, authenticated;
do $$
declare
  v_column text;
begin
  for v_column in
    select attname from pg_attribute
    where attrelid = 'public.projects'::regclass and attnum > 0 and not attisdropped
  loop
    execute format(
      'revoke insert (%I), update (%I), references (%I) on public.projects from public, anon, authenticated',
      v_column, v_column, v_column
    );
  end loop;
end $$;
grant select on public.projects to anon, authenticated;
grant all on public.projects to service_role;

drop policy if exists "own projects" on public.projects;
create policy "own projects" on public.projects for select to authenticated
  using (auth.uid() = user_id);

-- NOT VALID enforces new/updated rows immediately without making privilege
-- revocation fail because of a previously poisoned/legacy row. The API rejects
-- unsafe paths even for existing rows. Audit those rows, do not blindly rename
-- or delete their filesystem targets; validate the constraint after remediation.
do $$ begin
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.projects'::regclass
      and conname = 'projects_safe_storage_name'
  ) then
    alter table public.projects add constraint projects_safe_storage_name
      check (name ~ '^[A-Za-z0-9][A-Za-z0-9_-]*$' and name !~ E'[\\r\\n]') not valid;
  end if;
end $$;
commit;

-- Required post-migration audit (read-only):
-- select id, user_id, name from public.projects
-- where not (name ~ '^[A-Za-z0-9][A-Za-z0-9_-]*$' and name !~ E'[\\r\\n]');
-- After auditing/remediating rows:
-- alter table public.projects validate constraint projects_safe_storage_name;
