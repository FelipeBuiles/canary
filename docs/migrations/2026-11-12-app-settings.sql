-- Operator settings that change without a restart (runtime_settings.py).
-- Apply once. Until it is applied, every setting comes from the environment.
-- Readable and writable by the server's service role only; never holds secrets.
begin;

create table if not exists public.app_settings (
  key text primary key check (key ~ '^[A-Z][A-Z0-9_]{2,80}$'),
  value text not null check (char_length(value) between 1 and 2000),
  updated_at timestamptz not null default now(),
  updated_by text not null default 'ops_token'
);
alter table public.app_settings enable row level security;
revoke all on public.app_settings from public, anon, authenticated;
grant all on public.app_settings to service_role;

create or replace function public.touch_app_setting() returns trigger
language plpgsql set search_path = public as $$
begin
  new.updated_at := now();
  return new;
end;
$$;
revoke all on function public.touch_app_setting() from public, anon, authenticated;
drop trigger if exists app_settings_touch on public.app_settings;
create trigger app_settings_touch before update on public.app_settings
for each row execute function public.touch_app_setting();

commit;
