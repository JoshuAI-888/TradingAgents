-- Append-only capture storage. Legacy deployment history is not private account data.
create table public.screen_captures (
  history_key text not null check (history_key ~ '^screen_history:[a-f0-9]{16,64}:[a-f0-9]{64}$'),
  id text not null check (length(id) between 1 and 100),
  at timestamptz not null,
  source_at text,
  source_clock text not null,
  complete boolean not null,
  members integer not null check (members >= 0),
  version integer not null check (version >= 1),
  snapshot jsonb not null check (jsonb_typeof(snapshot) = 'object' and jsonb_typeof(snapshot->'members') = 'array'),
  primary key (history_key, id)
);
create index screen_captures_timeline on public.screen_captures (history_key, at desc, id desc);
alter table public.screen_captures enable row level security;
revoke all on public.screen_captures from public, anon, authenticated, service_role;
grant select, insert on public.screen_captures to service_role;

create function public.screen_capture_immutable() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  raise exception using errcode = '55000', message = 'Screen captures are immutable';
end;
$$;
revoke all on function public.screen_capture_immutable() from public, anon, authenticated, service_role;
create trigger screen_capture_immutable before update or delete on public.screen_captures
for each row execute function public.screen_capture_immutable();
create trigger screen_capture_no_truncate before truncate on public.screen_captures
for each statement execute function public.screen_capture_immutable();

-- Import the two legacy records and append the new capture in one transaction.
-- Concurrent callers insert independent records; conflicts never overwrite history.
create function public.screen_capture_append(p_key text, p_records jsonb) returns integer
language plpgsql security invoker set search_path = '' as $$
declare item jsonb; s jsonb; inserted integer; total integer := 0;
begin
  if jsonb_typeof(p_records) is distinct from 'array' or jsonb_array_length(p_records) not between 1 and 101 then
    raise exception using errcode = '22023', message = 'Invalid capture batch';
  end if;
  for item in select value from jsonb_array_elements(p_records) loop
    s := item->'snapshot';
    if jsonb_typeof(s) is distinct from 'object' or jsonb_typeof(s->'members') is distinct from 'array'
       or s->>'at' is null or s->>'at' !~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
       or item->>'id' is null or (s ? 'id' and s->>'id' is distinct from item->>'id') then
      raise exception using errcode = '22023', message = 'Invalid capture record';
    end if;
    insert into public.screen_captures(history_key,id,at,source_at,source_clock,complete,members,version,snapshot)
    values (p_key,item->>'id',(s->>'at')::timestamptz,s->>'source_at',
      coalesce(s->>'source_clock','unverified'),coalesce((s->>'complete')::boolean,false),
      jsonb_array_length(s->'members'),coalesce((s->>'version')::integer,1),s)
    on conflict (history_key,id) do nothing;
    get diagnostics inserted = row_count;
    if inserted = 0 and not exists (
      select 1 from public.screen_captures c where c.history_key=p_key and c.id=item->>'id' and c.snapshot=s
    ) then
      raise exception using errcode = '23505', message = 'Capture identity already has different evidence';
    end if;
    total := total + inserted;
  end loop;
  return total;
end;
$$;
revoke all on function public.screen_capture_append(text,jsonb) from public, anon, authenticated;
grant execute on function public.screen_capture_append(text,jsonb) to service_role;

alter table public.screen_captures add constraint screen_capture_payload_contract check (
  jsonb_typeof(snapshot) is not distinct from 'object'
  and jsonb_typeof(snapshot->'members') is not distinct from 'array'
  and snapshot->>'at' is not null
  and at = (snapshot->>'at')::timestamptz
  and members = jsonb_array_length(snapshot->'members')
  and complete = coalesce((snapshot->>'complete')::boolean,false)
  and version = coalesce((snapshot->>'version')::integer,1)
  and (not (snapshot ? 'id') or snapshot->>'id' = id)
);
