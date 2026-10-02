alter table public.research_capture_occurrences
 add column attempt_started_at timestamptz,
 add column error_code text check(error_code in ('provider_unavailable','incomplete_data','storage_unconfirmed','worker_interrupted','definition_changed','lease_exhausted','schedule_changed'));

-- Lock order is schedule then occurrence for dispatch/edit/claim/renew/failure.
-- Candidates and work per call are bounded; unrelated schedule locks are skipped.
create function public.research_capture_claim(p_worker uuid)
returns setof public.research_capture_occurrences
language plpgsql security invoker set search_path='' as $$
declare candidate record; s public.research_capture_schedules%rowtype; o public.research_capture_occurrences%rowtype; instant timestamptz;
begin
 if p_worker is null then raise exception using errcode='22023',message='Invalid capture worker';end if;
 for candidate in
  select q.id,q.schedule_id from public.research_capture_occurrences q join public.research_capture_schedules sc on sc.id=q.schedule_id
  where q.status in ('pending','running') and
   (not sc.enabled or sc.revision<>q.schedule_revision or (q.status='pending' and q.retry_at<=clock_timestamp()) or (q.status='running' and q.lease_until<=clock_timestamp()))
  order by q.due_at,q.id limit 100
 loop
  select * into s from public.research_capture_schedules where id=candidate.schedule_id for update skip locked;
  if not found then continue;end if;
  select * into o from public.research_capture_occurrences where id=candidate.id for update skip locked;
  if not found or o.status not in ('pending','running') then continue;end if;
  instant:=clock_timestamp();
  if not s.enabled or s.revision<>o.schedule_revision then
   update public.research_capture_occurrences set status='cancelled',error_code='schedule_changed',lease_token=null,lease_until=null,worker_id=null,updated_at=instant where id=o.id;
   continue;
  end if;
  if (o.status='running' and o.lease_until>instant) or (o.status='pending' and o.retry_at>instant) then continue;end if;
  if o.attempts>=3 then
   update public.research_capture_occurrences set status='failed',error_code='lease_exhausted',lease_token=null,lease_until=null,worker_id=null,updated_at=instant where id=o.id;
   continue;
  end if;
  if exists(select 1 from public.research_capture_occurrences q where q.schedule_id=s.id and q.id<>o.id
    and q.schedule_revision=s.revision and q.status='running' and q.lease_until>instant
    and q.attempt_started_at+interval '20 minutes'>instant) then continue;end if;
  return query update public.research_capture_occurrences set status='running',attempts=attempts+1,
   lease_token=gen_random_uuid(),lease_until=instant+interval '120 seconds',worker_id=p_worker,attempt_started_at=instant,
   error_code=null,updated_at=instant where id=o.id returning *;
  return;
 end loop;
end;
$$;

create function public.research_capture_renew(p_occurrence uuid,p_worker uuid,p_token uuid)
returns setof public.research_capture_occurrences
language plpgsql security invoker set search_path='' as $$
declare sid uuid; s public.research_capture_schedules%rowtype; instant timestamptz;
begin
 if p_occurrence is null or p_worker is null or p_token is null then raise exception using errcode='22023',message='Invalid capture lease';end if;
 select schedule_id into sid from public.research_capture_occurrences where id=p_occurrence;
 if not found then return;end if;
 select * into s from public.research_capture_schedules where id=sid for update;
 if not found or not s.enabled then return;end if;
 instant:=clock_timestamp();
 return query update public.research_capture_occurrences set lease_until=least(instant+interval '120 seconds',attempt_started_at+interval '20 minutes'),updated_at=instant
 where id=p_occurrence and schedule_revision=s.revision and status='running' and worker_id=p_worker and lease_token=p_token
  and lease_until>instant and attempt_started_at+interval '20 minutes'>instant returning *;
end;
$$;

create function public.research_capture_fail(p_occurrence uuid,p_worker uuid,p_token uuid,p_error text,p_retryable boolean)
returns setof public.research_capture_occurrences
language plpgsql security invoker set search_path='' as $$
declare sid uuid; s public.research_capture_schedules%rowtype; instant timestamptz;
begin
 if p_occurrence is null or p_worker is null or p_token is null or p_retryable is null or p_error is null
  or p_error not in ('provider_unavailable','incomplete_data','storage_unconfirmed','worker_interrupted','definition_changed') then
  raise exception using errcode='22023',message='Invalid capture failure';
 end if;
 select schedule_id into sid from public.research_capture_occurrences where id=p_occurrence;
 if not found then return;end if;
 select * into s from public.research_capture_schedules where id=sid for update;
 if not found or not s.enabled then return;end if;
 instant:=clock_timestamp();
 return query update public.research_capture_occurrences set status=case when p_retryable and attempts<3 then 'pending' else 'failed' end,
  error_code=p_error,retry_at=instant+case when attempts=1 then interval '30 seconds' else interval '120 seconds' end,
  lease_token=null,lease_until=null,worker_id=null,updated_at=instant
 where id=p_occurrence and schedule_revision=s.revision and status='running' and worker_id=p_worker and lease_token=p_token
  and lease_until>instant and attempt_started_at+interval '20 minutes'>instant returning *;
end;
$$;
revoke all on function public.research_capture_claim(uuid) from public,anon,authenticated;
revoke all on function public.research_capture_renew(uuid,uuid,uuid) from public,anon,authenticated;
revoke all on function public.research_capture_fail(uuid,uuid,uuid,text,boolean) from public,anon,authenticated;
grant execute on function public.research_capture_claim(uuid) to service_role;
grant execute on function public.research_capture_renew(uuid,uuid,uuid) to service_role;
grant execute on function public.research_capture_fail(uuid,uuid,uuid,text,boolean) to service_role;
