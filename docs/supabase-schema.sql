-- Pulp — Supabase schema
-- Run this once in the Supabase SQL editor (Dashboard → SQL editor → New query).
-- Safe to re-run: uses IF NOT EXISTS / CREATE OR REPLACE.

-- ── Tables ───────────────────────────────────────────────────────────────────

create table if not exists public.projects (
  id           uuid        primary key default gen_random_uuid(),
  user_id      uuid        not null references auth.users(id) on delete cascade,
  name         text        not null,
  share_token  uuid        not null unique default gen_random_uuid(),
  is_public    boolean     not null default false,
  created_at   timestamptz not null default now(),
  constraint projects_user_name_unique unique (user_id, name)
);

create table if not exists public.credit_ledger (
  id                        uuid        primary key default gen_random_uuid(),
  user_id                   uuid        not null references auth.users(id) on delete cascade,
  amount_credits            integer     not null,
  status                    text        not null default 'settled'
                              check (status in ('reserved', 'settled', 'released')),
  stage                     text,
  description               text,
  stripe_payment_intent_id  text        unique,
  stripe_refund_id          text        unique,
  usage_call_id             text        unique,
  provider                  text,
  model                     text,
  provider_model            text,
  operation                 text,
  input_tokens              integer     not null default 0,
  output_tokens             integer     not null default 0,
  image_count               integer     not null default 0,
  cost_usd                  numeric(12, 6),
  cost_source               text,
  pricing_snapshot          text,
  project_id                uuid        references public.projects(id) on delete set null,
  created_at                timestamptz not null default now()
);

create table if not exists public.ai_usage_events (
  id                    uuid        primary key default gen_random_uuid(),
  created_at            timestamptz not null default now(),
  started_at            timestamptz not null default now(),
  finished_at           timestamptz,
  user_id               uuid        references auth.users(id) on delete cascade,
  project_id            uuid        references public.projects(id) on delete set null,
  workspace_id          text,
  project_name          text,
  stage                 text,
  feature               text        not null,
  operation             text        not null,
  status                text        not null
                                      check (status in ('started', 'succeeded', 'failed', 'refused', 'cancelled')),
  billable              boolean     not null default false,
  funding               text        not null default 'api'
                                      check (funding in ('api', 'codex_subscription', 'claude_subscription')),
  billing_policy        text,
  model_alias           text        not null,
  provider              text,
  provider_model        text,
  litellm_model         text,
  provider_response_id  text,
  request_id            text,
  idempotency_key       text,
  input_tokens          integer     not null default 0,
  output_tokens         integer     not null default 0,
  total_tokens          integer     not null default 0,
  image_count           integer     not null default 0,
  latency_ms            integer,
  cost_usd              numeric(12, 6),
  cost_source           text,
  provider_cost_usd     numeric(12, 6),
  estimated_cost_usd    numeric(12, 6),
  pricing_snapshot      text,
  params_json           jsonb       not null default '{}'::jsonb,
  request_summary_json  jsonb       not null default '{}'::jsonb,
  usage_json            jsonb       not null default '{}'::jsonb,
  metadata_json         jsonb       not null default '{}'::jsonb,
  error_type            text,
  error_message         text,
  error_json            jsonb       not null default '{}'::jsonb
);

-- Durable guarantees for concurrent provider submissions within one job.
create table if not exists public.credit_call_authorizations (
  usage_call_id text primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  job_id uuid not null,
  reservation_id uuid not null references public.credit_ledger(id) on delete cascade,
  amount_credits integer not null check (amount_credits > 0),
  status text not null default 'pending'
    check (status in ('pending', 'settled', 'released')),
  created_at timestamptz not null default now()
);

-- Durable, privacy-bounded customer journey milestones. The service role is
-- the only writer; browser events go through the authenticated API so event
-- names, properties, and payload size remain allowlisted by application code.
create table if not exists public.product_events (
  id                    uuid        primary key default gen_random_uuid(),
  occurred_at           timestamptz not null default now(),
  event_name            text        not null,
  user_id               uuid        references auth.users(id) on delete set null,
  project_id            uuid        references public.projects(id) on delete set null,
  job_id                uuid,
  request_id            text,
  source                text        not null default 'server'
                                      check (source in ('server', 'web')),
  posthog_exported_at    timestamptz,
  properties_json       jsonb       not null default '{}'::jsonb
                                      check (jsonb_typeof(properties_json) = 'object')
);

-- Operator-authorized exception refunds. The row is written before calling
-- Stripe so retries can recover a Stripe-success/local-write-failure split.
create table if not exists public.credit_refunds (
  id                        uuid        primary key default gen_random_uuid(),
  stripe_payment_intent_id  text        not null unique,
  stripe_refund_id          text        unique,
  ledger_grant_id           uuid        not null references public.credit_ledger(id),
  user_id                   uuid        not null references auth.users(id) on delete restrict,
  operator                  text        not null,
  reason                    text        not null,
  amount_cents              integer     not null check (amount_cents > 0),
  credits_reversed          integer     not null check (credits_reversed > 0),
  status                    text        not null
                                        check (status in (
                                          'pending',
                                          'stripe_succeeded',
                                          'completed'
                                        )),
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now(),
  completed_at              timestamptz
);

-- One-time migration for databases created by earlier drafts of this schema.
do $$ begin
  if exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='credit_ledger' and column_name='amount_cents'
  ) and not exists (
    select 1 from information_schema.columns
    where table_schema='public' and table_name='credit_ledger' and column_name='amount_credits'
  ) then
    alter table public.credit_ledger rename column amount_cents to amount_credits;
  end if;
end $$;

alter table public.credit_ledger
  add column if not exists usage_call_id text,
  add column if not exists provider text,
  add column if not exists model text,
  add column if not exists provider_model text,
  add column if not exists operation text,
  add column if not exists input_tokens integer not null default 0,
  add column if not exists output_tokens integer not null default 0,
  add column if not exists image_count integer not null default 0,
  add column if not exists cost_usd numeric(12, 6),
  add column if not exists cost_source text,
  add column if not exists pricing_snapshot text,
  add column if not exists funding text not null default 'api'
    check (funding in ('api', 'codex_subscription')),
  add column if not exists usage_status text,
  add column if not exists job_id uuid,
  add column if not exists reservation_owner uuid,
  add column if not exists reservation_expires_at timestamptz,
  add column if not exists reservation_started_at timestamptz,
  add column if not exists billing_credits_per_usd numeric,
  add column if not exists billing_markup numeric,
  add column if not exists unfunded_credits integer not null default 0,
  add column if not exists stripe_checkout_session_id text,
  add column if not exists credit_package_id text,
  add column if not exists gross_amount_cents integer,
  add column if not exists currency text,
  add column if not exists offer_version text,
  add column if not exists stripe_refund_id text,
  add column if not exists refund_record_id uuid;

do $$ begin
  if not exists (
    select 1 from pg_constraint where conname = 'credit_ledger_refund_record_id_fkey'
  ) then
    alter table public.credit_ledger
      add constraint credit_ledger_refund_record_id_fkey
      foreign key (refund_record_id) references public.credit_refunds(id);
  end if;
end $$;

create unique index if not exists credit_ledger_stripe_refund_id_idx
  on public.credit_ledger (stripe_refund_id)
  where stripe_refund_id is not null;

create unique index if not exists credit_ledger_refund_record_id_idx
  on public.credit_ledger (refund_record_id)
  where refund_record_id is not null;

-- Atomically lock the user's ledger, re-check that the grant is unused, and
-- place a negative reservation before Stripe is called. This closes the race
-- where generation could consume credits between an application-side check
-- and the refund.
create or replace function public.prepare_credit_refund(
  p_payment_intent_id text,
  p_operator text,
  p_reason text
)
returns setof public.credit_refunds
language plpgsql
security definer
set search_path = public
as $$
declare
  v_grant public.credit_ledger%rowtype;
  v_refund public.credit_refunds%rowtype;
  v_balance integer;
begin
  select * into v_grant
  from public.credit_ledger
  where stripe_payment_intent_id = p_payment_intent_id
  for update;

  if not found
     or v_grant.amount_credits <= 0
     or v_grant.status != 'settled'
     or v_grant.gross_amount_cents is null
     or v_grant.gross_amount_cents <= 0 then
    raise exception 'Original credit grant is missing or ambiguous';
  end if;

  perform pg_advisory_xact_lock(hashtextextended(v_grant.user_id::text, 0));

  select * into v_refund
  from public.credit_refunds
  where stripe_payment_intent_id = p_payment_intent_id;
  if found then
    return next v_refund;
    return;
  end if;

  if exists (
    select 1
    from public.credit_ledger
    where user_id = v_grant.user_id
      and created_at > v_grant.created_at
      and amount_credits < 0
      and status != 'released'
  ) then
    raise exception 'Credits may have been consumed after this purchase';
  end if;

  select coalesce(sum(
    case when status != 'released' then amount_credits else 0 end
  ), 0)::integer
  into v_balance
  from public.credit_ledger
  where user_id = v_grant.user_id;

  if v_balance < v_grant.amount_credits then
    raise exception 'Insufficient unused balance for automatic refund';
  end if;

  insert into public.credit_refunds (
    stripe_payment_intent_id, ledger_grant_id, user_id, operator, reason,
    amount_cents, credits_reversed, status
  ) values (
    p_payment_intent_id, v_grant.id, v_grant.user_id, p_operator, p_reason,
    v_grant.gross_amount_cents, v_grant.amount_credits, 'pending'
  )
  returning * into v_refund;

  insert into public.credit_ledger (
    user_id, amount_credits, status, description, operation,
    gross_amount_cents, currency, refund_record_id
  ) values (
    v_grant.user_id, -v_grant.amount_credits, 'reserved',
    'Refund hold — ' || p_payment_intent_id, 'refund_hold',
    -v_grant.gross_amount_cents, coalesce(v_grant.currency, 'usd'), v_refund.id
  );

  return next v_refund;
end;
$$;

create or replace function public.complete_credit_refund(
  p_refund_record_id uuid,
  p_stripe_refund_id text,
  p_completed_at timestamptz
)
returns setof public.credit_refunds
language plpgsql
security definer
set search_path = public
as $$
declare
  v_refund public.credit_refunds%rowtype;
begin
  select * into v_refund
  from public.credit_refunds
  where id = p_refund_record_id
  for update;
  if not found then
    raise exception 'Refund recovery record not found';
  end if;

  update public.credit_ledger
  set status = 'settled',
      stripe_refund_id = p_stripe_refund_id,
      operation = 'refund',
      description = 'Credit reversal — refund ' || p_stripe_refund_id
  where refund_record_id = p_refund_record_id;
  if not found then
    raise exception 'Refund credit hold not found';
  end if;

  update public.credit_refunds
  set status = 'completed',
      stripe_refund_id = p_stripe_refund_id,
      completed_at = p_completed_at,
      updated_at = now()
  where id = p_refund_record_id
  returning * into v_refund;

  return next v_refund;
end;
$$;

alter table public.ai_usage_events
  add column if not exists funding text not null default 'api'
    check (funding in ('api', 'codex_subscription', 'claude_subscription')),
  add column if not exists provider_cost_usd numeric(12, 6),
  add column if not exists estimated_cost_usd numeric(12, 6),
  add column if not exists pricing_snapshot text;

-- ── Balance view ─────────────────────────────────────────────────────────────
-- balance_credits = sum of all non-released rows.
-- Purchases are positive; reservations/model usage debits are negative.

drop view if exists public.user_credits;

create or replace view public.user_credits
  with (security_invoker = true) as
  select
    user_id,
    coalesce(
      sum(case when status != 'released' then amount_credits else 0 end),
      0
    )::integer as balance_credits
  from public.credit_ledger
  group by user_id;

-- ── Atomic reservations ─────────────────────────────────────────────────────
-- Uses a per-user advisory transaction lock so parallel project runs cannot
-- both observe the same balance and over-reserve credits.

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

-- ── Indexes ──────────────────────────────────────────────────────────────────

create index if not exists credit_ledger_user_created_idx
  on public.credit_ledger (user_id, created_at desc);

create index if not exists credit_ledger_job_id_idx
  on public.credit_ledger (user_id, job_id)
  where job_id is not null;

create index if not exists credit_ledger_payment_intent_idx
  on public.credit_ledger (stripe_payment_intent_id)
  where stripe_payment_intent_id is not null;

create unique index if not exists credit_ledger_usage_call_idx
  on public.credit_ledger (usage_call_id);

create index if not exists ai_usage_events_user_created_idx
  on public.ai_usage_events (user_id, created_at desc);

create index if not exists ai_usage_events_project_created_idx
  on public.ai_usage_events (project_id, created_at desc);

create index if not exists ai_usage_events_status_created_idx
  on public.ai_usage_events (status, created_at desc);

create index if not exists ai_usage_events_feature_created_idx
  on public.ai_usage_events (feature, created_at desc);

create unique index if not exists ai_usage_events_idempotency_key_idx
  on public.ai_usage_events (idempotency_key)
  where idempotency_key is not null;

create unique index if not exists ai_usage_events_provider_response_id_idx
  on public.ai_usage_events (provider_response_id)
  where provider_response_id is not null;

create index if not exists projects_user_created_idx
  on public.projects (user_id, created_at desc);

create index if not exists product_events_user_occurred_idx
  on public.product_events (user_id, occurred_at desc);

create index if not exists product_events_project_occurred_idx
  on public.product_events (project_id, occurred_at desc)
  where project_id is not null;

create index if not exists product_events_name_occurred_idx
  on public.product_events (event_name, occurred_at desc);

create unique index if not exists credit_ledger_checkout_session_idx
  on public.credit_ledger (stripe_checkout_session_id)
  where stripe_checkout_session_id is not null;

-- ── Operator observability views ────────────────────────────────────────────
-- These views are intentionally not granted to anon/authenticated. Query them
-- through the service role or a future dedicated read-only operator role.

create or replace view public.ops_ai_cost_daily
with (security_invoker = true) as
select
  date_trunc('day', created_at) as day,
  stage,
  feature,
  provider,
  coalesce(provider_model, model_alias) as model,
  operation,
  status,
  billable,
  count(*)::bigint as call_count,
  coalesce(sum(input_tokens), 0)::bigint as input_tokens,
  coalesce(sum(output_tokens), 0)::bigint as output_tokens,
  coalesce(sum(image_count), 0)::bigint as image_count,
  (case when funding in ('codex_subscription', 'claude_subscription') then sum(cost_usd)
    else coalesce(sum(cost_usd), 0) end)::numeric(14, 6) as actual_cost_usd,
  coalesce(sum(estimated_cost_usd), 0)::numeric(14, 6) as estimated_cost_usd,
  percentile_cont(0.5) within group (order by latency_ms)
    filter (where latency_ms is not null) as latency_p50_ms,
  percentile_cont(0.95) within group (order by latency_ms)
    filter (where latency_ms is not null) as latency_p95_ms,
  funding,
  count(*) filter (where cost_usd is null)::bigint as unknown_cost_count
from public.ai_usage_events
group by 1, 2, 3, 4, 5, 6, 7, 8, funding;

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

create or replace view public.ops_unit_economics_daily
with (security_invoker = true) as
with days as (
  select date_trunc('day', created_at) as day from public.ai_usage_events
  union
  select date_trunc('day', created_at) as day from public.credit_ledger
), spend as (
  select
    date_trunc('day', created_at) as day,
    coalesce(sum(cost_usd) filter (where billable and funding = 'api'), 0) as provider_cost_usd
  from public.ai_usage_events
  group by 1
), ledger as (
  select
    date_trunc('day', created_at) as day,
    coalesce(sum(gross_amount_cents) filter (
      where amount_credits > 0 and status = 'settled' and currency = 'usd'
    ), 0) as gross_revenue_cents,
    coalesce(sum(amount_credits) filter (
      where amount_credits > 0 and status = 'settled'
    ), 0) as credits_granted,
    coalesce(sum(abs(amount_credits)) filter (
      where amount_credits < 0 and status = 'settled' and usage_call_id is not null
    ), 0) as credits_used
  from public.credit_ledger
  group by 1
)
select
  days.day,
  coalesce(ledger.gross_revenue_cents, 0)::bigint as gross_revenue_cents,
  coalesce(spend.provider_cost_usd, 0)::numeric(14, 6) as provider_cost_usd,
  (
    coalesce(ledger.gross_revenue_cents, 0)::numeric / 100
    - coalesce(spend.provider_cost_usd, 0)
  )::numeric(14, 6) as pre_fee_margin_usd,
  coalesce(ledger.credits_granted, 0)::bigint as credits_granted,
  coalesce(ledger.credits_used, 0)::bigint as credits_used
from days
left join spend using (day)
left join ledger using (day);

create or replace view public.ops_product_funnel_daily
with (security_invoker = true) as
select
  date_trunc('day', occurred_at) as day,
  event_name,
  count(*)::bigint as event_count,
  count(distinct user_id)::bigint as unique_users,
  count(distinct project_id)::bigint as unique_projects
from public.product_events
group by 1, 2;

-- ── Row-level security ───────────────────────────────────────────────────────
-- The backend uses the service_role key (SUPABASE_SECRET_KEY) which bypasses
-- RLS entirely. These policies protect against accidental direct client access.

alter table public.projects enable row level security;
alter table public.credit_ledger enable row level security;
alter table public.ai_usage_events enable row level security;
alter table public.credit_call_authorizations enable row level security;
alter table public.product_events enable row level security;
alter table public.credit_refunds enable row level security;

-- Projects: users see only their own; public projects visible to all.
do $$ begin
  if not exists (
    select 1 from pg_policies where tablename='projects' and policyname='own projects'
  ) then
    create policy "own projects"
      on public.projects for all
      using (auth.uid() = user_id)
      with check (auth.uid() = user_id);
  end if;
end $$;

do $$ begin
  if not exists (
    select 1 from pg_policies where tablename='projects' and policyname='public projects readable'
  ) then
    create policy "public projects readable"
      on public.projects for select
      using (is_public = true);
  end if;
end $$;

-- Credit ledger: users see only their own rows.
do $$ begin
  if not exists (
    select 1 from pg_policies where tablename='credit_ledger' and policyname='own ledger'
  ) then
    create policy "own ledger"
      on public.credit_ledger for select
      using (auth.uid() = user_id);
  end if;
end $$;

-- AI usage events: users see only their own request rows.
do $$ begin
  if not exists (
    select 1 from pg_policies where tablename='ai_usage_events' and policyname='own ai usage events'
  ) then
    create policy "own ai usage events"
      on public.ai_usage_events for select
      using (auth.uid() = user_id);
  end if;
end $$;

-- ── Grants ───────────────────────────────────────────────────────────────────
-- Authenticated role needs SELECT on the view; service_role has full access.

grant select on public.user_credits to authenticated;
grant select on public.projects to authenticated;
grant select on public.credit_ledger to authenticated;
grant select on public.ai_usage_events to authenticated;

revoke all on public.product_events from public, anon, authenticated;
revoke all on public.credit_refunds from public, anon, authenticated;
revoke all on public.credit_call_authorizations from public, anon, authenticated;
revoke all on public.ops_ai_cost_daily from public, anon, authenticated;
revoke all on public.ops_usage_reconciliation from public, anon, authenticated;
revoke all on public.ops_unit_economics_daily from public, anon, authenticated;
revoke all on public.ops_product_funnel_daily from public, anon, authenticated;

grant all on public.product_events to service_role;
grant all on public.credit_refunds to service_role;
grant all on public.credit_call_authorizations to service_role;
grant select on public.ops_ai_cost_daily to service_role;
grant select on public.ops_usage_reconciliation to service_role;
grant select on public.ops_unit_economics_daily to service_role;
grant select on public.ops_product_funnel_daily to service_role;

revoke all on function public.reserve_stage_credits(uuid, uuid, text, integer, uuid, uuid, integer, numeric, numeric)
  from public, anon, authenticated;
grant execute on function public.reserve_stage_credits(uuid, uuid, text, integer, uuid, uuid, integer, numeric, numeric)
  to service_role;
revoke all on function public.authorize_model_call_credits(
  uuid, uuid, text, integer, uuid, numeric, numeric
), public.release_model_call_authorization(uuid, text)
  from public, anon, authenticated;
grant execute on function public.authorize_model_call_credits(
  uuid, uuid, text, integer, uuid, numeric, numeric
), public.release_model_call_authorization(uuid, text)
  to service_role;
revoke all on function public.renew_credit_reservation_leases(uuid, integer),
  public.check_credit_reservation_lease(uuid, uuid),
  public.release_credit_reservation(uuid, uuid) from public, anon, authenticated;
grant execute on function public.renew_credit_reservation_leases(uuid, integer),
  public.check_credit_reservation_lease(uuid, uuid),
  public.release_credit_reservation(uuid, uuid) to service_role;

revoke all on function public.settle_model_usage_credits(
  uuid, uuid, uuid, text, text, text, text, text, text, text, integer, integer,
  integer, numeric, text, text, numeric, numeric, boolean, text
) from public, anon, authenticated;
grant execute on function public.settle_model_usage_credits(
  uuid, uuid, uuid, text, text, text, text, text, text, text, integer, integer,
  integer, numeric, text, text, numeric, numeric, boolean, text
) to service_role;

revoke all on function public.prepare_credit_refund(text, text, text)
  from public, anon, authenticated;
grant execute on function public.prepare_credit_refund(text, text, text)
  to service_role;

revoke all on function public.complete_credit_refund(uuid, text, timestamptz)
  from public, anon, authenticated;
grant execute on function public.complete_credit_refund(uuid, text, timestamptz)
  to service_role;

-- Private feedback and pending analytics delivery.
create index if not exists product_events_pending_posthog_idx
  on public.product_events(occurred_at) where posthog_exported_at is null;

create table if not exists public.customer_feedback (
  user_id uuid not null references auth.users(id) on delete cascade,
  id uuid not null,
  created_at timestamptz not null default now(),
  project_id uuid references public.projects(id) on delete set null,
  category text not null check (category in ('frustration','feature','praise','other')),
  message text not null check (length(message) between 1 and 3000),
  station text,
  rating text check (rating in ('yes','after_changes','no','unsure')),
  request_id text,
  status text not null default 'new' check (status in ('new','reviewed','planned','resolved')),
  primary key (user_id,id)
);
create index if not exists customer_feedback_created_idx on public.customer_feedback(created_at desc);
alter table public.customer_feedback enable row level security;
revoke all on public.customer_feedback from public, anon, authenticated;
grant all on public.customer_feedback to service_role;

-- Atomic purchase analytics outbox (no historical backfill).
-- Apply before deploying the billing writer. No historical purchase backfill.
-- Settlement and its content-free event commit or roll back together.
alter table public.credit_ledger
  add column if not exists purchase_event_environment text,
  add column if not exists purchase_event_release text,
  add column if not exists stripe_mode text check (stripe_mode in ('test', 'live', 'unknown'));

create or replace function public.enqueue_purchase_event()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  -- Old application releases still capture best-effort events; do not duplicate
  -- those during the migration-before-code rollout. New writers always set this.
  if new.purchase_event_environment is not null
     and new.status = 'settled' and new.amount_credits > 0
     and new.stripe_payment_intent_id is not null
     and new.stripe_checkout_session_id is not null then
    insert into public.product_events (id, occurred_at, event_name, user_id, source, properties_json)
    values (
      md5('credits_purchased:' || new.id::text)::uuid,
      new.created_at, 'credits_purchased', new.user_id, 'server',
      jsonb_build_object(
        'schema_version', 1,
        'environment', coalesce(new.purchase_event_environment, 'unknown'),
        'release', coalesce(new.purchase_event_release, 'unknown'),
        'stripe_mode', coalesce(new.stripe_mode, 'unknown'),
        'package_id', new.credit_package_id,
        'credits', new.amount_credits,
        'gross_amount_cents', new.gross_amount_cents,
        'currency', new.currency
      )
    ) on conflict (id) do nothing;
  end if;
  return new;
end;
$$;
revoke all on function public.enqueue_purchase_event() from public, anon, authenticated;
drop trigger if exists settled_purchase_event on public.credit_ledger;
create trigger settled_purchase_event after insert on public.credit_ledger
for each row execute function public.enqueue_purchase_event();

-- Private operator research records. Apply once before enabling the tracker.
create table if not exists public.operator_tester_records (
  collection text not null check (collection in ('people','sessions','notes','findings')),
  id text not null,
  data jsonb not null default '{}'::jsonb check (jsonb_typeof(data) = 'object' and octet_length(data::text) <= 64000),
  revision integer not null default 1,
  deleted boolean not null default false,
  updated_at timestamptz not null default now(),
  primary key (collection, id)
);
alter table public.operator_tester_records enable row level security;
revoke all on public.operator_tester_records from anon, authenticated;
grant all on public.operator_tester_records to service_role;

create or replace function public.write_operator_tester_record(
  p_collection text, p_id text, p_data jsonb, p_mode text, p_expected_revision integer
) returns setof public.operator_tester_records language plpgsql security invoker set search_path = public as $$
declare current_row public.operator_tester_records;
begin
  perform pg_advisory_xact_lock(hashtextextended(p_collection || '/' || p_id, 0));
  select * into current_row from public.operator_tester_records where collection=p_collection and id=p_id;
  if coalesce(current_row.revision,0) <> p_expected_revision then
    raise exception 'tracker_revision_conflict';
  end if;
  if p_mode not in ('set','update','delete') or (p_mode <> 'set' and (current_row.id is null or current_row.deleted)) then
    raise exception 'tracker_record_missing';
  end if;
  return query insert into public.operator_tester_records as records (collection,id,data,revision,deleted)
    values (p_collection,p_id, case when p_mode='update' then current_row.data || p_data when p_mode='delete' then current_row.data else p_data end,
      p_expected_revision+1,p_mode='delete')
    on conflict (collection,id) do update set data=excluded.data,revision=excluded.revision,deleted=excluded.deleted,updated_at=now()
    returning records.*;
end;
$$;
revoke all on function public.write_operator_tester_record(text,text,jsonb,text,integer) from public,anon,authenticated;
grant execute on function public.write_operator_tester_record(text,text,jsonb,text,integer) to service_role;
