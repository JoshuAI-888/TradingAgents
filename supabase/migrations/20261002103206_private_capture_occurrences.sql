-- Durable private queue. No definitions or outcomes enter the public jobs feed.
alter table public.research_capture_schedules add constraint research_capture_schedules_id_owner unique(id,owner_id);
create table public.research_capture_occurrences (
 id uuid primary key,
 schedule_id uuid not null,
 owner_id uuid not null references auth.users(id) on delete cascade,
 schedule_revision integer not null check(schedule_revision>=1),
 due_at timestamptz not null,
 status text not null default 'pending' check(status in ('pending','running','succeeded','failed','cancelled')),
 attempts integer not null default 0 check(attempts between 0 and 3),
 lease_token uuid,
 lease_until timestamptz,
 worker_id uuid,
 retry_at timestamptz not null default clock_timestamp(),
 created_at timestamptz not null default clock_timestamp(),
 updated_at timestamptz not null default clock_timestamp(),
 foreign key(schedule_id,owner_id) references public.research_capture_schedules(id,owner_id) on delete cascade,
 unique(schedule_id,schedule_revision,due_at),
 check((status='running' and lease_token is not null and lease_until is not null and worker_id is not null and attempts>0)
    or (status<>'running' and lease_token is null and lease_until is null and worker_id is null))
);
create index research_capture_occurrences_owner_order on public.research_capture_occurrences(owner_id,created_at,id);
create index research_capture_occurrences_claim on public.research_capture_occurrences(retry_at,due_at,id) where status in ('pending','running');
alter table public.research_capture_occurrences enable row level security;
revoke all on public.research_capture_occurrences from public,anon,authenticated,service_role;
grant select on public.research_capture_occurrences to authenticated;
grant select,insert,update on public.research_capture_occurrences to service_role;
create policy research_capture_occurrences_owner_read on public.research_capture_occurrences for select to authenticated using((select auth.uid())=owner_id);

create function public.research_capture_dispatch(p_schedule uuid,p_owner uuid,p_revision integer,p_expected_due timestamptz,p_due timestamptz,p_next timestamptz,p_occurrence uuid)
returns setof public.research_capture_occurrences
language plpgsql security invoker set search_path='' as $$
declare s public.research_capture_schedules%rowtype; o public.research_capture_occurrences%rowtype; instant timestamptz;
begin
 if p_schedule is null or p_owner is null or p_revision is null or p_revision<1 or p_expected_due is null or p_due is null or p_next is null or p_occurrence is null then
  raise exception using errcode='22023',message='Invalid private capture dispatch';
 end if;
 select * into s from public.research_capture_schedules where id=p_schedule and owner_id=p_owner for update;
 instant:=clock_timestamp();
 if not found or not s.enabled or s.revision<>p_revision then return;end if;
 -- Lost-response retry returns the original occurrence without advancing twice.
 select * into o from public.research_capture_occurrences where schedule_id=s.id and schedule_revision=s.revision and due_at=p_due;
 if found then
  if o.id<>p_occurrence then raise exception using errcode='22023',message='Occurrence identity conflict';end if;
  return next o;return;
 end if;
 if s.next_due_at is distinct from p_expected_due or p_due<s.next_due_at or p_due<s.activated_at or p_due>instant or p_next<=instant or p_next<=p_due then return;end if;
 insert into public.research_capture_occurrences(id,schedule_id,owner_id,schedule_revision,due_at)
 values(p_occurrence,s.id,s.owner_id,s.revision,p_due) returning * into o;
 update public.research_capture_schedules set next_due_at=p_next,updated_at=instant where id=s.id;
 return next o;
end;
$$;
revoke all on function public.research_capture_dispatch(uuid,uuid,integer,timestamptz,timestamptz,timestamptz,uuid) from public,anon,authenticated;
grant execute on function public.research_capture_dispatch(uuid,uuid,integer,timestamptz,timestamptz,timestamptz,uuid) to service_role;
