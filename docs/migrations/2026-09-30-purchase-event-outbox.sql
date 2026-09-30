-- Apply before deploying the billing writer. No historical purchase backfill.
-- Settlement and its content-free event commit or roll back together.
begin;
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
commit;
