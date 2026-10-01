-- Local change set: NOT applied to production. No historical signup backfill.
-- Inspect named objects and duplicate signup rows before an approved rollout.
-- Analytics failure never rolls back signup. The existing delivery worker calls
-- the bounded, service-role-only reconciler to recover post-boundary gaps.
begin;
create table public.signup_capture_boundary (
  singleton boolean primary key check (singleton),
  started_at timestamptz not null
);
insert into public.signup_capture_boundary values (true, transaction_timestamp());
revoke all on public.signup_capture_boundary from public, anon, authenticated, service_role;

-- Refuse existing duplicate signup rows instead of rewriting history. This
-- prevents the old app-load writer duplicating trigger rows during rollout.
create unique index product_events_one_account_creation_per_user
on public.product_events(user_id) where event_name = 'account_created' and user_id is not null;

create function public.signup_event_properties(metadata jsonb, method text)
returns jsonb language plpgsql set search_path = '' as $$
declare
  props jsonb;
  token text;
  field text;
begin
  props := jsonb_build_object('schema_version', 1, 'environment', 'production',
    'release', 'auth-signup-outbox-v1', 'acquisition_source', 'unknown',
    'signup_capture_method', method);
  foreach field in array array['source','medium','campaign','referring_domain'] loop
    token := lower(metadata->'acquisition'->>field);
    if token ~ '^[a-z0-9][a-z0-9._-]{0,63}$' then
      props := props || jsonb_build_object(case when field = 'referring_domain' then field else 'acquisition_' || field end, token);
    end if;
  end loop;
  return props;
end;
$$;
revoke all on function public.signup_event_properties(jsonb, text) from public, anon, authenticated, service_role;

create function public.enqueue_account_created_event()
returns trigger language plpgsql security definer
set search_path = '' set lock_timeout = '250ms' as $$
begin
  if new.created_at >= (select started_at from public.signup_capture_boundary where singleton) then
    insert into public.product_events (id, occurred_at, event_name, user_id, source, properties_json)
    values (md5('account_created:' || new.id::text)::uuid, new.created_at,
      'account_created', new.id, 'server',
      public.signup_event_properties(new.raw_user_meta_data, 'trigger'))
    on conflict do nothing;
  end if;
  return new;
exception when others then
  -- No SQLERRM, account ID, email, or metadata in the warning. Reconciliation
  -- uses the committed auth row as its recovery source, not an unreliable
  -- second write inside this exception handler.
  raise warning 'Canary signup analytics gap SQLSTATE=%', SQLSTATE;
  return new;
end;
$$;
revoke all on function public.enqueue_account_created_event() from public, anon, authenticated, service_role;
create trigger account_created_event after insert on auth.users
for each row execute function public.enqueue_account_created_event();

create function public.reconcile_account_created_events()
returns jsonb language plpgsql security definer
set search_path = '' set lock_timeout = '250ms' as $$
declare
  recovered integer;
  remaining bigint;
  legacy_observed bigint;
begin
  insert into public.product_events (id, occurred_at, event_name, user_id, source, properties_json)
  select md5('account_created:' || u.id::text)::uuid, u.created_at,
    'account_created', u.id, 'server',
    public.signup_event_properties(u.raw_user_meta_data, 'reconciled')
  from auth.users u
  where u.created_at >= (select started_at from public.signup_capture_boundary where singleton)
    and not exists (select 1 from public.product_events e where e.user_id = u.id and e.event_name = 'account_created')
  order by u.created_at, u.id limit 100
  on conflict do nothing;
  get diagnostics recovered = row_count;
  select count(*) into remaining from auth.users u
  where u.created_at >= (select started_at from public.signup_capture_boundary where singleton)
    and not exists (select 1 from public.product_events e where e.user_id = u.id and e.event_name = 'account_created');
  select count(*) into legacy_observed from auth.users u
  join public.product_events e on e.user_id = u.id and e.event_name = 'account_created'
  where u.created_at >= (select started_at from public.signup_capture_boundary where singleton)
    and coalesce(e.properties_json->>'release', '') <> 'auth-signup-outbox-v1';
  return jsonb_build_object('recovered', recovered, 'remaining', remaining, 'legacy_observed', legacy_observed);
end;
$$;
revoke all on function public.reconcile_account_created_events() from public, anon, authenticated, service_role;
grant execute on function public.reconcile_account_created_events() to service_role;
commit;
