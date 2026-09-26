-- Apply once before deploying the PostHog/feedback release.
-- No historical events are backfilled: earlier milestone meanings differ.
begin;
do $$ begin
  if not exists (select 1 from information_schema.columns where table_schema = 'public'
                 and table_name = 'product_events' and column_name = 'posthog_exported_at') then
    alter table public.product_events add column posthog_exported_at timestamptz;
    update public.product_events set posthog_exported_at = now();
  end if;
end $$;
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
commit;
