-- Atomically authorize each paid call, transfer settled debits out of job holds,
-- and preserve any provider overrun for operator reconciliation.
-- Apply as an administrator before deploying the matching application binary.
BEGIN;
ALTER TABLE public.credit_ledger
  ADD COLUMN IF NOT EXISTS billing_credits_per_usd numeric,
  ADD COLUMN IF NOT EXISTS billing_markup numeric,
  ADD COLUMN IF NOT EXISTS unfunded_credits integer not null default 0;
CREATE TABLE IF NOT EXISTS public.credit_call_authorizations (
  usage_call_id text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid not null,
  reservation_id uuid not null references public.credit_ledger(id) on delete cascade,
  amount_credits integer not null check (amount_credits > 0),
  status text not null default 'pending'
    check (status in ('pending', 'settled', 'released')),
  created_at timestamptz not null default now()
);
ALTER TABLE public.credit_call_authorizations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.credit_call_authorizations FROM public, anon, authenticated;
GRANT ALL ON public.credit_call_authorizations TO service_role;

-- Remove the unsafe old overload on upgrades; old binaries must fail closed.
drop function if exists public.reserve_stage_credits(uuid, uuid, text, integer, uuid);
drop function if exists public.reserve_stage_credits(uuid, uuid, text, integer, uuid, uuid, integer);
create or replace function public.reserve_stage_credits(
  p_user_id       uuid,
  p_project_id    uuid,
  p_stage         text,
  p_amount_credits integer,
  p_job_id        uuid,
  p_owner         uuid,
  p_lease_seconds integer,
  p_credits_per_usd numeric,
  p_markup numeric
)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_balance_credits integer;
  v_reservation_id uuid;
begin
  if p_amount_credits <= 0 then
    raise exception 'Reservation amount must be positive';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  if p_owner is null or p_lease_seconds < 60 or p_lease_seconds > 86400
     or p_credits_per_usd <= 0 or p_markup <= 0 then
    raise exception 'Invalid reservation lease';
  end if;
  -- Only a never-started expired request can be safely reclaimed automatically.
  update public.credit_ledger set status = 'released'
  where user_id = p_user_id and status = 'reserved'
    and reservation_started_at is null
    and reservation_expires_at <= clock_timestamp();
  -- Started/legacy expired holds remain reserved and reduce available credit.
  -- Their reconciliation must not freeze unrelated work with enough balance.
  -- Lease validation still prevents the expired job itself from starting.

  select coalesce(
    sum(case when status != 'released' then amount_credits else 0 end),
    0
  )::integer
  into v_balance_credits
  from public.credit_ledger
  where user_id = p_user_id;

  if v_balance_credits < p_amount_credits then
    return null;
  end if;

  insert into public.credit_ledger (
    user_id,
    project_id,
    amount_credits,
    status,
    stage,
    description,
    job_id, reservation_owner, reservation_expires_at,
    billing_credits_per_usd, billing_markup
  )
  values (
    p_user_id,
    p_project_id,
    -p_amount_credits,
    'reserved',
    p_stage,
    'Reserved: ' || p_stage,
    p_job_id, p_owner, clock_timestamp() + make_interval(secs => p_lease_seconds),
    p_credits_per_usd, p_markup
  )
  returning id into v_reservation_id;

  return v_reservation_id;
end;
$$;

create or replace function public.renew_credit_reservation_leases(
  p_owner uuid, p_lease_seconds integer
) returns void language plpgsql security definer set search_path = public as $$
begin
  if p_owner is null or p_lease_seconds < 60 or p_lease_seconds > 86400 then
    raise exception 'Invalid reservation lease';
  end if;
  update public.credit_ledger
  set reservation_expires_at = clock_timestamp() + make_interval(secs => p_lease_seconds)
  where status = 'reserved' and reservation_owner = p_owner
    and reservation_expires_at > clock_timestamp();
  update public.credit_ledger set status = 'released'
  where status = 'reserved' and reservation_started_at is null
    and reservation_expires_at <= clock_timestamp();
end;
$$;

create or replace function public.check_credit_reservation_lease(
  p_reservation_id uuid, p_owner uuid
) returns boolean language plpgsql security definer set search_path = public as $$
begin
  update public.credit_ledger
  set reservation_started_at = coalesce(reservation_started_at, clock_timestamp())
  where id = p_reservation_id and reservation_owner = p_owner
    and status = 'reserved' and reservation_expires_at > clock_timestamp();
  return found;
end;
$$;

-- Usage settlement is append-only, including zero-credit incremental rows.
-- Project deletion may clear project_id, but cannot change the financial fact.
create or replace function public.protect_settled_model_usage()
returns trigger language plpgsql set search_path = public as $$
begin
  if old.status = 'reserved' and new.status = 'released'
    and not coalesce(
      (old.reservation_owner is not null and old.reservation_owner::text =
        coalesce(current_setting('canary.reservation_owner', true), ''))
      or (old.reservation_started_at is null
        and old.reservation_expires_at <= clock_timestamp()),
      false
    ) then
    raise exception 'Reservation release requires its lease owner';
  end if;
  if old.status = 'settled' and old.usage_call_id is not null
    and (to_jsonb(new) - 'project_id') is distinct from (to_jsonb(old) - 'project_id') then
    raise exception 'Settled model usage is immutable';
  end if;
  return new;
end;
$$;
drop trigger if exists immutable_settled_model_usage on public.credit_ledger;
create trigger immutable_settled_model_usage before update on public.credit_ledger
for each row execute function public.protect_settled_model_usage();

create or replace function public.release_credit_reservation(
  p_reservation_id uuid, p_owner uuid
) returns void language plpgsql security definer set search_path = public as $$
begin
  perform set_config('canary.reservation_owner', p_owner::text, true);
  update public.credit_ledger set status = 'released'
  where id = p_reservation_id and reservation_owner = p_owner and status = 'reserved';
end;
$$;

create unique index if not exists credit_ledger_active_job_hold_idx
  on public.credit_ledger (user_id, job_id)
  where status = 'reserved' and reservation_owner is not null;

create or replace function public.authorize_model_call_credits(
  p_user_id uuid,
  p_job_id uuid,
  p_usage_call_id text,
  p_amount_credits integer,
  p_owner uuid,
  p_credits_per_usd numeric,
  p_markup numeric
) returns boolean language plpgsql security definer set search_path = public as $$
declare
  v_hold public.credit_ledger%rowtype;
  v_existing public.credit_call_authorizations%rowtype;
  v_pending integer;
  v_balance integer;
  v_extra integer;
begin
  if p_user_id is null or p_job_id is null or p_owner is null
     or p_usage_call_id is null or p_amount_credits <= 0
     or p_credits_per_usd <= 0 or p_markup <= 0 then
    raise exception 'Invalid model call authorization';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  select * into v_existing from public.credit_call_authorizations
  where usage_call_id = p_usage_call_id;
  if exists (select 1 from public.credit_ledger where usage_call_id = p_usage_call_id)
     or exists (select 1 from public.credit_ledger
       where user_id = p_user_id and job_id = p_job_id and unfunded_credits > 0) then
    return false;
  end if;
  select * into v_hold from public.credit_ledger
  where user_id = p_user_id and job_id = p_job_id and status = 'reserved'
    and reservation_owner = p_owner
    and reservation_expires_at > clock_timestamp()
  for update;
  if not found then
    return false;
  end if;
  if v_hold.billing_credits_per_usd is not null
     and (v_hold.billing_credits_per_usd != p_credits_per_usd
       or v_hold.billing_markup != p_markup) then
    raise exception 'Job billing terms changed; restart with a new reservation';
  end if;
  if v_existing.usage_call_id is not null then
    return v_existing.user_id = p_user_id and v_existing.job_id = p_job_id
      and v_existing.reservation_id = v_hold.id
      and v_existing.amount_credits = p_amount_credits
      and v_existing.status = 'pending';
  end if;
  select coalesce(sum(amount_credits), 0)::integer into v_pending
  from public.credit_call_authorizations
  where reservation_id = v_hold.id and status = 'pending';
  v_extra := greatest(0, v_pending + p_amount_credits + v_hold.amount_credits);
  select coalesce(sum(case when status != 'released' then amount_credits else 0 end), 0)::integer
  into v_balance from public.credit_ledger where user_id = p_user_id;
  if v_balance < v_extra then
    return false;
  end if;
  update public.credit_ledger
  set amount_credits = amount_credits - v_extra,
      reservation_started_at = coalesce(reservation_started_at, clock_timestamp()),
      billing_credits_per_usd = coalesce(billing_credits_per_usd, p_credits_per_usd),
      billing_markup = coalesce(billing_markup, p_markup)
  where id = v_hold.id;
  insert into public.credit_call_authorizations (
    usage_call_id, user_id, job_id, reservation_id, amount_credits
  ) values (
    p_usage_call_id, p_user_id, p_job_id, v_hold.id, p_amount_credits
  );
  return true;
end;
$$;

create or replace function public.release_model_call_authorization(
  p_user_id uuid, p_usage_call_id text
) returns void language plpgsql security definer set search_path = public as $$
begin
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  update public.credit_call_authorizations set status = 'released'
  where user_id = p_user_id and usage_call_id = p_usage_call_id and status = 'pending';
end;
$$;

-- ── Atomic model-usage settlement ───────────────────────────────────────────
-- Model calls are retained as individual audit rows, but whole public credits
-- are rounded once across the job's cumulative provider cost. The advisory
-- lock prevents concurrent panel calls from each observing the same subtotal.

-- Clean cutover: remove the API-only overload rather than leaving an unsafe RPC.
drop function if exists public.settle_model_usage_credits(
  uuid, uuid, uuid, text, text, text, text, text, text, text, integer, integer,
  integer, numeric, text, text, numeric, numeric, boolean
);

create or replace function public.settle_model_usage_credits(
  p_user_id             uuid,
  p_project_id          uuid,
  p_job_id              uuid,
  p_stage               text,
  p_description         text,
  p_usage_call_id       text,
  p_provider            text,
  p_model               text,
  p_provider_model      text,
  p_operation           text,
  p_input_tokens        integer,
  p_output_tokens       integer,
  p_image_count         integer,
  p_cost_usd            numeric,
  p_cost_source         text,
  p_pricing_snapshot    text,
  p_credits_per_usd     numeric,
  p_markup              numeric,
  p_billable            boolean,
  p_funding             text
)
returns integer
language plpgsql
security definer
set search_path = public
as $$
declare
  v_existing_amount integer;
  v_hold public.credit_ledger%rowtype;
  v_auth public.credit_call_authorizations%rowtype;
  v_prior_cost numeric := 0;
  v_prior_accounted integer := 0;
  v_target_debit integer := 0;
  v_increment integer := 0;
  v_other_pending integer := 0;
  v_reserved_capacity integer := 0;
  v_balance integer := 0;
  v_charge integer := 0;
  v_rate numeric;
  v_markup numeric;
begin
  if p_funding is null or p_funding not in ('api', 'codex_subscription') then
    raise exception 'Unknown usage funding';
  end if;
  perform pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));
  perform pg_advisory_xact_lock(hashtextextended(p_usage_call_id, 1));

  select amount_credits into v_existing_amount
  from public.credit_ledger
  where usage_call_id = p_usage_call_id;
  if found then
    if not exists (
      select 1 from public.credit_ledger where usage_call_id = p_usage_call_id
        and user_id = p_user_id and status = 'settled'
    ) then
      raise exception 'Usage call belongs to a different settlement';
    end if;
    -- Recovered durable artifacts may replay this call under a new job.
    -- The original usage identity and financial row remain authoritative.
    return abs(v_existing_amount);
  end if;

  select * into v_auth from public.credit_call_authorizations
  where usage_call_id = p_usage_call_id for update;
  if found and (v_auth.user_id != p_user_id or v_auth.job_id != p_job_id) then
    raise exception 'Model call authorization belongs to a different job';
  end if;
  select * into v_hold from public.credit_ledger
  where user_id = p_user_id and job_id = p_job_id and status = 'reserved'
    and reservation_owner is not null
    and (v_auth.reservation_id is null or id = v_auth.reservation_id)
  for update;
  v_rate := coalesce(v_hold.billing_credits_per_usd, p_credits_per_usd);
  v_markup := coalesce(v_hold.billing_markup, p_markup);

  -- Subscription evidence is balance-neutral even with contradictory USD or
  -- billable input. It must not enter the cumulative API rounding calculation.
  if p_funding = 'api' then
  select
    coalesce(sum(cost_usd), 0),
    coalesce(sum(abs(amount_credits) + unfunded_credits), 0)::integer
  into v_prior_cost, v_prior_accounted
  from public.credit_ledger
  where user_id = p_user_id
    and job_id = p_job_id
    and status = 'settled'
    and usage_call_id is not null
    and funding = 'api';

  v_target_debit := ceil(
    (v_prior_cost + greatest(coalesce(p_cost_usd, 0), 0))
    * greatest(coalesce(v_rate, 0), 0)
    * greatest(coalesce(v_markup, 0), 0)
  )::integer;
  if p_billable and v_target_debit <= 0 then
    v_target_debit := 1;
  end if;
  v_increment := greatest(0, v_target_debit - v_prior_accounted);
  if v_hold.id is not null then
    select coalesce(sum(amount_credits), 0)::integer into v_other_pending
    from public.credit_call_authorizations
    where reservation_id = v_hold.id and status = 'pending'
      and usage_call_id != p_usage_call_id;
    v_reserved_capacity := greatest(0, -v_hold.amount_credits - v_other_pending);
    v_charge := least(v_increment, v_reserved_capacity);
    -- Only the pre-submission hold can pay this call. Any provider surprise is
    -- recorded as unfunded rather than spending other available credits.
    update public.credit_ledger
    set amount_credits = amount_credits + v_charge
    where id = v_hold.id;
  else
    -- Legacy/manual settlements without a hold remain bounded by free balance.
    select coalesce(sum(case when status != 'released' then amount_credits else 0 end), 0)::integer
    into v_balance from public.credit_ledger where user_id = p_user_id;
    v_charge := least(v_increment, greatest(v_balance, 0));
  end if;
  end if;

  insert into public.credit_ledger (
    user_id, project_id, amount_credits, status, stage, description,
    usage_call_id, provider, model, provider_model, operation, input_tokens,
    output_tokens, image_count, cost_usd, cost_source, pricing_snapshot, job_id,
    funding, usage_status, unfunded_credits
  ) values (
    p_user_id, p_project_id, -v_charge, 'settled', p_stage, p_description,
    p_usage_call_id, p_provider, p_model, p_provider_model, p_operation,
    coalesce(p_input_tokens, 0), coalesce(p_output_tokens, 0),
    coalesce(p_image_count, 0), p_cost_usd, p_cost_source,
    p_pricing_snapshot, p_job_id, p_funding,
    (select status from public.ai_usage_events where id::text = p_usage_call_id),
    v_increment - v_charge
  );

  update public.credit_call_authorizations set status = 'settled'
  where usage_call_id = p_usage_call_id and user_id = p_user_id and status = 'pending';

  return v_charge;
end;
$$;

create or replace view public.ops_usage_reconciliation
with (security_invoker = true) as
select
  coalesce(a.id::text, l.usage_call_id) as usage_call_id,
  coalesce(a.created_at, l.created_at) as occurred_at,
  coalesce(a.user_id, l.user_id) as user_id,
  coalesce(a.project_id, l.project_id) as project_id,
  coalesce(a.stage, l.stage) as stage,
  a.feature,
  a.status as ai_status,
  a.billable,
  a.cost_usd as provider_cost_usd,
  l.amount_credits,
  case
    when l.unfunded_credits > 0 then 'unfunded_provider_usage'
    when a.id is not null and a.billable and a.funding = 'api' and l.id is null
      then 'billable_ai_event_without_debit'
    when a.id is null and l.id is not null
      then 'debit_without_ai_event'
    when a.status != 'succeeded' and l.amount_credits < 0
      then 'failed_ai_event_debited'
  end as issue
from public.ai_usage_events a
full outer join public.credit_ledger l
  on l.usage_call_id = a.id::text
  and l.status = 'settled'
where
  (a.id is not null and a.billable and a.funding = 'api' and l.id is null)
  or (a.id is null and l.usage_call_id is not null)
  or (a.status != 'succeeded' and l.amount_credits < 0)
  or l.unfunded_credits > 0;


REVOKE ALL ON FUNCTION public.reserve_stage_credits(uuid, uuid, text, integer, uuid, uuid, integer, numeric, numeric)
  FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reserve_stage_credits(uuid, uuid, text, integer, uuid, uuid, integer, numeric, numeric)
  TO service_role;
REVOKE ALL ON FUNCTION public.authorize_model_call_credits(uuid, uuid, text, integer, uuid, numeric, numeric),
  public.release_model_call_authorization(uuid, text) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.authorize_model_call_credits(uuid, uuid, text, integer, uuid, numeric, numeric),
  public.release_model_call_authorization(uuid, text) TO service_role;
REVOKE ALL ON FUNCTION public.settle_model_usage_credits(
  uuid, uuid, uuid, text, text, text, text, text, text, text, integer, integer,
  integer, numeric, text, text, numeric, numeric, boolean, text
) FROM public, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.settle_model_usage_credits(
  uuid, uuid, uuid, text, text, text, text, text, text, text, integer, integer,
  integer, numeric, text, text, numeric, numeric, boolean, text
) TO service_role;
GRANT SELECT ON public.ops_usage_reconciliation TO service_role;
COMMIT;
