-- Keep unresolved holds deducted without blocking unrelated new work.
-- Apply to the application Supabase database as an administrator.
BEGIN;
create or replace function public.reserve_stage_credits(
  p_user_id       uuid,
  p_project_id    uuid,
  p_stage         text,
  p_amount_credits integer,
  p_job_id        uuid,
  p_owner         uuid,
  p_lease_seconds integer
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
  if p_owner is null or p_lease_seconds < 60 or p_lease_seconds > 86400 then
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
    job_id, reservation_owner, reservation_expires_at
  )
  values (
    p_user_id,
    p_project_id,
    -p_amount_credits,
    'reserved',
    p_stage,
    'Reserved: ' || p_stage,
    p_job_id, p_owner, clock_timestamp() + make_interval(secs => p_lease_seconds)
  )
  returning id into v_reservation_id;

  return v_reservation_id;
end;
$$;
COMMIT;
