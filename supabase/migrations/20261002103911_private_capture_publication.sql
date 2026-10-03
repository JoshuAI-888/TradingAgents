alter table public.research_capture_occurrences add constraint research_capture_occurrences_identity unique(id,schedule_id,owner_id,schedule_revision);
create table public.research_private_captures (
 id uuid primary key,
 schedule_id uuid not null,
 owner_id uuid not null references auth.users(id) on delete cascade,
 schedule_revision integer not null,
 definition_hash text not null check(definition_hash ~ '^[a-f0-9]{64}$'),
 snapshot jsonb not null check(jsonb_typeof(snapshot)='object' and octet_length(snapshot::text)<=33554432),
 publish_token uuid not null,
 publish_worker uuid not null,
 published_at timestamptz not null default clock_timestamp(),
 foreign key(id,schedule_id,owner_id,schedule_revision) references public.research_capture_occurrences(id,schedule_id,owner_id,schedule_revision) on delete cascade
);
create index research_private_captures_history on public.research_private_captures(owner_id,definition_hash,published_at desc,id);
alter table public.research_private_captures enable row level security;
revoke all on public.research_private_captures from public,anon,authenticated,service_role;
grant select on public.research_private_captures to authenticated;
grant select,insert on public.research_private_captures to service_role;
create policy research_private_captures_owner_read on public.research_private_captures for select to authenticated using((select auth.uid())=owner_id);

create function public.research_capture_publish(p_occurrence uuid,p_worker uuid,p_token uuid,p_snapshot jsonb)
returns setof public.research_private_captures
language plpgsql security invoker set search_path='' as $$
declare sid uuid; s public.research_capture_schedules%rowtype; o public.research_capture_occurrences%rowtype; saved public.research_private_captures%rowtype;
 instant timestamptz; captured timestamptz; sourced timestamptz; members jsonb; observations jsonb; market text;
begin
 if p_occurrence is null or p_worker is null or p_token is null or jsonb_typeof(p_snapshot) is distinct from 'object' or octet_length(p_snapshot::text)>33554432 then
  raise exception using errcode='22023',message='Invalid private capture publication';
 end if;
 select schedule_id into sid from public.research_capture_occurrences where id=p_occurrence;
 if not found then return;end if;
 select * into s from public.research_capture_schedules where id=sid for update;
 if not found then return;end if;
 select * into o from public.research_capture_occurrences where id=p_occurrence for update;
 if not found then return;end if;
 select * into saved from public.research_private_captures where id=p_occurrence;
 if found then
  -- Confirmation of an already committed capture is allowed after schedule-off.
  -- It cannot create new evidence and requires the original exact attempt/payload.
  if o.status='succeeded' and saved.publish_worker=p_worker and saved.publish_token=p_token and saved.snapshot=p_snapshot then return next saved;end if;
  return;
 end if;
 instant:=clock_timestamp();
 if not s.enabled or s.revision<>o.schedule_revision or o.status<>'running' or o.worker_id<>p_worker or o.lease_token<>p_token
  or o.lease_until<=instant or o.attempt_started_at+interval '20 minutes'<=instant then return;end if;
 members:=p_snapshot->'members';observations:=p_snapshot->'observations';market:=s.definition->'screen'->>'market';
 if p_snapshot->>'id' is distinct from p_occurrence::text or p_snapshot->'complete' is distinct from 'true'::jsonb
  or p_snapshot->'definition' is distinct from s.definition->'screen'
  or p_snapshot->'version' not in ('2'::jsonb,'3'::jsonb) or p_snapshot->'version' is null
  or jsonb_typeof(members) is distinct from 'array' or market not in ('US','HK') or market is null
  or jsonb_typeof(p_snapshot->'at') is distinct from 'string' or jsonb_typeof(p_snapshot->'source_at') is distinct from 'string'
  or (p_snapshot->>'at') !~ '(Z|[+-][0-9]{2}:[0-9]{2})$' or (p_snapshot->>'source_at') !~ '(Z|[+-][0-9]{2}:[0-9]{2})$'
  or p_snapshot->>'source_clock' not in ('provider_retrieval','generation_publication','stored_universe') or p_snapshot->>'source_clock' is null then
  raise exception using errcode='22023',message='Incomplete or incompatible private capture';
 end if;
 begin
  captured:=(p_snapshot->>'at')::timestamptz;sourced:=(p_snapshot->>'source_at')::timestamptz;
 exception when invalid_datetime_format or datetime_field_overflow then
  raise exception using errcode='22023',message='Invalid private capture timestamps';
 end;
 if not isfinite(captured) or not isfinite(sourced) or captured<o.attempt_started_at-interval '5 seconds' or captured>instant+interval '5 minutes'
  or captured<instant-interval '20 minutes' or sourced>captured+interval '5 minutes' or sourced<captured-interval '24 hours' or jsonb_array_length(members)>20000 then
  raise exception using errcode='22023',message='Stale or invalid private capture';
 end if;
 if exists(select 1 from jsonb_array_elements(members) m where jsonb_typeof(m) is distinct from 'object' or jsonb_typeof(m->'code') is distinct from 'string'
   or m->>'code' !~ ('^'||market||'\.[A-Z0-9][A-Z0-9._-]{0,30}$'))
  or (select count(distinct m->>'code') from jsonb_array_elements(members) m)<>jsonb_array_length(members) then
  raise exception using errcode='22023',message='Invalid private capture identities';
 end if;
 if s.definition->'screen'->>'preset' is null then
  if p_snapshot->'version' is distinct from '3'::jsonb or jsonb_typeof(observations) is distinct from 'array'
   or p_snapshot->>'observation_scope' is distinct from 'eligible_stored_universe'
   or p_snapshot->>'source_clock' not in ('stored_universe','generation_publication') then
   raise exception using errcode='22023',message='Private stored capture requires complete eligible observations';
  end if;
  if (p_snapshot->>'source_clock'='generation_publication' and (jsonb_typeof(p_snapshot->'source_generation_id') is distinct from 'string'
    or p_snapshot->>'source_generation_id' !~ '^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$'))
   or (p_snapshot ? 'source_generation_id' and p_snapshot->>'source_clock'<>'generation_publication')
   or exists(select 1 from jsonb_array_elements(observations) m where m->'generation_id' is distinct from p_snapshot->'source_generation_id') then
   raise exception using errcode='22023',message='Private capture observation generation is inconsistent';
  end if;
  if jsonb_array_length(observations)>20000 or p_snapshot->'eligible_count' is distinct from to_jsonb(jsonb_array_length(observations)) or not observations @> members
   or exists(select 1 from jsonb_array_elements(observations) m where jsonb_typeof(m) is distinct from 'object' or jsonb_typeof(m->'code') is distinct from 'string'
    or m->>'code' !~ ('^'||market||'\.[A-Z0-9][A-Z0-9._-]{0,30}$'))
   or (select count(distinct m->>'code') from jsonb_array_elements(observations) m)<>jsonb_array_length(observations) then
   raise exception using errcode='22023',message='Incomplete eligible private capture observations';
  end if;
 elsif p_snapshot->'version' is distinct from '2'::jsonb or p_snapshot->>'source_clock' is distinct from 'provider_retrieval' then
  raise exception using errcode='22023',message='Invalid private provider capture contract';
 end if;
 insert into public.research_private_captures(id,schedule_id,owner_id,schedule_revision,definition_hash,snapshot,publish_token,publish_worker,published_at)
 values(o.id,s.id,s.owner_id,s.revision,s.definition_hash,p_snapshot,p_token,p_worker,instant) returning * into saved;
 update public.research_capture_occurrences set status='succeeded',lease_token=null,lease_until=null,worker_id=null,error_code=null,updated_at=instant where id=o.id;
 return next saved;
end;
$$;
revoke all on function public.research_capture_publish(uuid,uuid,uuid,jsonb) from public,anon,authenticated;
grant execute on function public.research_capture_publish(uuid,uuid,uuid,jsonb) to service_role;
