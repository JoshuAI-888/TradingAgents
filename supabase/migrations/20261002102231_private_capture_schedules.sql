-- Private monitor definitions. Never place these in public jobs/shared history.
create table public.research_capture_schedules (
 id uuid primary key default gen_random_uuid(),
 owner_id uuid not null references auth.users(id) on delete cascade,
 definition_hash text not null check (definition_hash ~ '^[a-f0-9]{64}$'),
 definition jsonb not null check (jsonb_typeof(definition)='object' and octet_length(definition::text)<=32768),
 name text not null check (length(btrim(name)) between 1 and 80 and name !~ '[[:cntrl:]]'),
 cadence jsonb not null check (jsonb_typeof(cadence)='object'),
 enabled boolean not null default false,
 revision integer not null default 1 check (revision>=1),
 activated_at timestamptz not null default clock_timestamp(),
 next_due_at timestamptz,
 created_at timestamptz not null default clock_timestamp(),
 updated_at timestamptz not null default clock_timestamp(),
 unique(owner_id,definition_hash),
 check ((enabled and next_due_at is not null) or (not enabled and next_due_at is null))
);
create index research_capture_schedules_owner_order on public.research_capture_schedules(owner_id,created_at,id);
create index research_capture_schedules_due on public.research_capture_schedules(next_due_at,id) where enabled;
alter table public.research_capture_schedules enable row level security;
revoke all on public.research_capture_schedules from public,anon,authenticated,service_role;
grant select on public.research_capture_schedules to authenticated;
grant select,insert,update on public.research_capture_schedules to service_role;
create policy research_capture_schedules_owner_read on public.research_capture_schedules for select to authenticated using ((select auth.uid())=owner_id);

create function public.research_capture_schedule_save(p_owner uuid,p_hash text,p_revision integer,p_definition jsonb,p_name text,p_cadence jsonb,p_enabled boolean,p_next timestamptz)
returns setof public.research_capture_schedules
language plpgsql security invoker set search_path='' as $$
declare day jsonb; seen integer[]:='{}'; instant timestamptz:=clock_timestamp();
begin
 if p_owner is null or p_hash is null or p_hash !~ '^[a-f0-9]{64}$' or p_revision is null or p_revision<0
    or jsonb_typeof(p_definition) is distinct from 'object' or octet_length(p_definition::text)>32768
    or p_name is null or length(btrim(p_name)) not between 1 and 80 or p_name ~ '[[:cntrl:]]'
    or jsonb_typeof(p_cadence) is distinct from 'object' or p_enabled is null
    or jsonb_typeof(p_cadence->'timezone') is distinct from 'string'
    or not exists(select 1 from pg_catalog.pg_timezone_names where name=p_cadence->>'timezone')
    or coalesce(p_cadence->>'hour','') !~ '^(0|[1-9]|1[0-9]|2[0-3])$'
    or coalesce(p_cadence->>'minute','') !~ '^(0|[1-9]|[1-5][0-9])$'
    or jsonb_typeof(p_cadence->'hour') is distinct from 'number' or jsonb_typeof(p_cadence->'minute') is distinct from 'number'
    or jsonb_typeof(p_cadence->'weekdays') is distinct from 'array'
    or (p_enabled and (p_next is null or p_next<=instant)) or (not p_enabled and p_next is not null) then
  raise exception using errcode='22023',message='Invalid private capture schedule';
 end if;
 if jsonb_array_length(p_cadence->'weekdays') not between 1 and 7 then
  raise exception using errcode='22023',message='Invalid capture weekdays';
 end if;
 for day in select value from jsonb_array_elements(p_cadence->'weekdays') loop
  if jsonb_typeof(day) is distinct from 'number' or day::text !~ '^[0-6]$' or (day::text)::integer=any(seen) then
   raise exception using errcode='22023',message='Invalid capture weekdays';
  end if;
  seen:=array_append(seen,(day::text)::integer);
 end loop;
 -- Serialize per-owner creation to enforce a bounded collection under concurrency.
 perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended('private_capture_schedule:'||p_owner::text,0));
 if p_revision=0 then
  if not exists(select 1 from public.research_capture_schedules where owner_id=p_owner and definition_hash=p_hash)
     and (select count(*) from public.research_capture_schedules where owner_id=p_owner)>=100 then
   raise exception using errcode='54000',message='Private capture schedule limit reached';
  end if;
  return query insert into public.research_capture_schedules(owner_id,definition_hash,definition,name,cadence,enabled,next_due_at,activated_at,updated_at)
   values(p_owner,p_hash,p_definition,btrim(p_name),p_cadence,p_enabled,p_next,instant,instant)
   on conflict(owner_id,definition_hash) do nothing returning *;
 else
  return query update public.research_capture_schedules set name=btrim(p_name),cadence=p_cadence,enabled=p_enabled,next_due_at=p_next,
   revision=revision+1,activated_at=instant,updated_at=instant
   where owner_id=p_owner and definition_hash=p_hash and revision=p_revision and definition=p_definition returning *;
 end if;
end;
$$;
revoke all on function public.research_capture_schedule_save(uuid,text,integer,jsonb,text,jsonb,boolean,timestamptz) from public,anon,authenticated;
grant execute on function public.research_capture_schedule_save(uuid,text,integer,jsonb,text,jsonb,boolean,timestamptz) to service_role;
