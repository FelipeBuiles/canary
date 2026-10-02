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
