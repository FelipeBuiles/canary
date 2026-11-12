-- Card-verified first-chapter grant: one per card and per account, with a seat
-- cap and an expiry. Apply before setting CANARY_CARD_GRANT_CREDITS.
--
-- The grant is an ordinary positive ledger row. At expiry, the unspent part is
-- taken back with a negative row. Usage after the grant spends the grant
-- first, so credits the author bought are never taken back.
begin;

create table if not exists public.card_chapter_grants (
  id                     uuid        primary key default gen_random_uuid(),
  -- Kept when the account is deleted, so the card cannot claim again.
  user_id                uuid        unique references auth.users(id) on delete set null,
  card_fingerprint       text        not null unique,
  stripe_setup_intent_id text        not null unique,
  ledger_grant_id        uuid        references public.credit_ledger(id) on delete set null,
  amount_credits         integer     not null check (amount_credits > 0),
  granted_at             timestamptz not null default now(),
  expires_at             timestamptz not null,
  expired_at             timestamptz,
  expiry_ledger_id       uuid        references public.credit_ledger(id) on delete set null
);

create index if not exists card_chapter_grants_due_idx
  on public.card_chapter_grants (expires_at) where expired_at is null;

alter table public.card_chapter_grants enable row level security;
revoke all on public.card_chapter_grants from public, anon, authenticated;
grant all on public.card_chapter_grants to service_role;

create or replace function public.claim_card_chapter_grant(
  p_user_id          uuid,
  p_card_fingerprint text,
  p_setup_intent_id  text,
  p_amount_credits   integer,
  p_expires_at       timestamptz,
  p_seats            integer
)
returns text
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_ledger_id uuid;
begin
  if p_amount_credits <= 0 or p_seats < 0 or p_expires_at <= now()
     or coalesce(p_card_fingerprint, '') = '' or coalesce(p_setup_intent_id, '') = '' then
    raise exception 'Invalid card chapter grant';
  end if;
  -- One claim at a time, so the seat count and both unique checks are exact.
  perform pg_advisory_xact_lock(hashtextextended('card_chapter_grants', 0));
  if exists (select 1 from public.card_chapter_grants where stripe_setup_intent_id = p_setup_intent_id) then
    return 'duplicate';
  end if;
  if exists (select 1 from public.card_chapter_grants where user_id = p_user_id) then
    return 'account_already_claimed';
  end if;
  if exists (select 1 from public.card_chapter_grants where card_fingerprint = p_card_fingerprint) then
    return 'card_already_used';
  end if;
  if (select count(*) from public.card_chapter_grants) >= p_seats then
    return 'seats_taken';
  end if;
  insert into public.credit_ledger (user_id, amount_credits, status, description, operation)
  values (p_user_id, p_amount_credits, 'settled', 'First chapter grant (card verified)', 'card_chapter_grant')
  returning id into v_ledger_id;
  insert into public.card_chapter_grants
    (user_id, card_fingerprint, stripe_setup_intent_id, ledger_grant_id, amount_credits, expires_at)
  values (p_user_id, p_card_fingerprint, p_setup_intent_id, v_ledger_id, p_amount_credits, p_expires_at);
  return 'granted';
end $$;

create or replace function public.expire_card_chapter_grants(p_user_id uuid default null)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_grant public.card_chapter_grants%rowtype;
  v_spent integer;
  v_balance integer;
  v_take integer;
  v_ledger_id uuid;
  v_count integer := 0;
begin
  for v_grant in
    select * from public.card_chapter_grants
    where expired_at is null and expires_at <= now() and user_id is not null
      and (p_user_id is null or user_id = p_user_id)
    for update skip locked
  loop
    -- The same per-user lock reservations take, so a balance is never read mid-reservation.
    perform pg_advisory_xact_lock(hashtextextended(v_grant.user_id::text, 0));
    select coalesce(-sum(amount_credits), 0)::integer into v_spent
    from public.credit_ledger
    where user_id = v_grant.user_id and status = 'settled' and amount_credits < 0
      and usage_call_id is not null and created_at >= v_grant.granted_at;
    -- Active holds count against the balance, so running work keeps its credits.
    select coalesce(sum(case when status != 'released' then amount_credits else 0 end), 0)::integer
    into v_balance from public.credit_ledger where user_id = v_grant.user_id;
    v_take := greatest(0, least(v_grant.amount_credits - v_spent, v_balance));
    v_ledger_id := null;
    if v_take > 0 then
      insert into public.credit_ledger (user_id, amount_credits, status, description, operation)
      values (v_grant.user_id, -v_take, 'settled', 'First chapter grant expired', 'card_chapter_expiry')
      returning id into v_ledger_id;
    end if;
    update public.card_chapter_grants
    set expired_at = now(), expiry_ledger_id = v_ledger_id where id = v_grant.id;
    v_count := v_count + 1;
  end loop;
  return v_count;
end $$;

revoke all on function public.claim_card_chapter_grant(uuid, text, text, integer, timestamptz, integer)
  from public, anon, authenticated;
grant execute on function public.claim_card_chapter_grant(uuid, text, text, integer, timestamptz, integer)
  to service_role;
revoke all on function public.expire_card_chapter_grants(uuid) from public, anon, authenticated;
grant execute on function public.expire_card_chapter_grants(uuid) to service_role;

commit;
