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
  usage_call_id             text        unique,
  provider                  text,
  model                     text,
  operation                 text,
  input_tokens              integer     not null default 0,
  output_tokens             integer     not null default 0,
  image_count               integer     not null default 0,
  cost_usd                  numeric(12, 6),
  project_id                uuid        references public.projects(id) on delete set null,
  created_at                timestamptz not null default now()
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
  add column if not exists operation text,
  add column if not exists input_tokens integer not null default 0,
  add column if not exists output_tokens integer not null default 0,
  add column if not exists image_count integer not null default 0,
  add column if not exists cost_usd numeric(12, 6);

-- ── Balance view ─────────────────────────────────────────────────────────────
-- balance_credits = sum of all non-released rows.
-- Purchases are positive; reservations/model usage debits are negative.

drop view if exists public.user_credits;

create or replace view public.user_credits as
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

create or replace function public.reserve_stage_credits(
  p_user_id       uuid,
  p_project_id    uuid,
  p_stage         text,
  p_amount_credits integer
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
    description
  )
  values (
    p_user_id,
    p_project_id,
    -p_amount_credits,
    'reserved',
    p_stage,
    'Reserved: ' || p_stage
  )
  returning id into v_reservation_id;

  return v_reservation_id;
end;
$$;

-- ── Indexes ──────────────────────────────────────────────────────────────────

create index if not exists credit_ledger_user_created_idx
  on public.credit_ledger (user_id, created_at desc);

create index if not exists credit_ledger_payment_intent_idx
  on public.credit_ledger (stripe_payment_intent_id)
  where stripe_payment_intent_id is not null;

create unique index if not exists credit_ledger_usage_call_idx
  on public.credit_ledger (usage_call_id);

create index if not exists projects_user_created_idx
  on public.projects (user_id, created_at desc);

-- ── Row-level security ───────────────────────────────────────────────────────
-- The backend uses the service_role key (SUPABASE_SECRET_KEY) which bypasses
-- RLS entirely. These policies protect against accidental direct client access.

alter table public.projects enable row level security;
alter table public.credit_ledger enable row level security;

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

-- ── Grants ───────────────────────────────────────────────────────────────────
-- Authenticated role needs SELECT on the view; service_role has full access.

grant select on public.user_credits to authenticated;
grant select on public.projects to authenticated;
grant select on public.credit_ledger to authenticated;

revoke all on function public.reserve_stage_credits(uuid, uuid, text, integer)
  from public, anon, authenticated;
grant execute on function public.reserve_stage_credits(uuid, uuid, text, integer)
  to service_role;
