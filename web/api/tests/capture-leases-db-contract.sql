-- Isolated local PostgreSQL only. Schema/fixtures roll back.
\set ON_ERROR_STOP on
begin;
\ir ../../../supabase/migrations/20261002102231_private_capture_schedules.sql
\ir ../../../supabase/migrations/20261002103206_private_capture_occurrences.sql
\ir ../../../supabase/migrations/20261002103538_private_capture_leases.sql
do $$ begin
 assert not has_function_privilege('authenticated','public.research_capture_claim(uuid)','EXECUTE');
 assert not has_function_privilege('anon','public.research_capture_renew(uuid,uuid,uuid)','EXECUTE');
 assert not has_function_privilege('authenticated','public.research_capture_fail(uuid,uuid,uuid,text,boolean)','EXECUTE');
end $$;
set local role service_role;
do $$ declare sid uuid:='00000000-0000-4000-8000-000000000030'; oid uuid:='00000000-0000-4000-8000-000000000031'; a uuid:='00000000-0000-4000-8000-000000000001'; worker uuid:='00000000-0000-4000-8000-000000000040'; other uuid:='00000000-0000-4000-8000-000000000041'; old_token uuid; current_token uuid; n integer; o public.research_capture_occurrences%rowtype;
begin
 insert into public.research_capture_schedules(id,owner_id,definition_hash,definition,name,cadence,enabled,activated_at,next_due_at)
 values(sid,a,repeat('a',64),'{}','Lease fixture','{}',true,clock_timestamp()-interval '2 days',clock_timestamp()+interval '1 day');
 insert into public.research_capture_occurrences(id,schedule_id,owner_id,schedule_revision,due_at) values(oid,sid,a,1,clock_timestamp()-interval '1 day');
 select * into o from public.research_capture_claim(worker);
 assert o.id=oid and o.status='running' and o.attempts=1 and o.worker_id=worker and o.lease_token is not null and o.lease_until>clock_timestamp();
 old_token:=o.lease_token;
 insert into public.research_capture_occurrences(id,schedule_id,owner_id,schedule_revision,due_at)
 values('00000000-0000-4000-8000-000000000034',sid,a,1,clock_timestamp());
 select count(*) into n from public.research_capture_claim(other);assert n=0;
 update public.research_capture_occurrences set retry_at=clock_timestamp()+interval '1 day' where id='00000000-0000-4000-8000-000000000034';
 select count(*) into n from public.research_capture_claim(other);assert n=0;
 select count(*) into n from public.research_capture_renew(oid,other,old_token);assert n=0;
 select count(*) into n from public.research_capture_renew(oid,worker,old_token);assert n=1;
 select count(*) into n from public.research_capture_fail(oid,other,old_token,'worker_interrupted',true);assert n=0;
 select * into o from public.research_capture_fail(oid,worker,old_token,'provider_unavailable',true);
 assert o.status='pending' and o.attempts=1 and o.lease_token is null and o.retry_at>clock_timestamp()+interval '29 seconds';
 select count(*) into n from public.research_capture_claim(worker);assert n=0;
 update public.research_capture_occurrences set retry_at=clock_timestamp()-interval '1 second' where id=oid;
 select * into o from public.research_capture_claim(other);
 assert o.attempts=2 and o.lease_token<>old_token;current_token:=o.lease_token;
 select count(*) into n from public.research_capture_renew(oid,worker,old_token);assert n=0;
 select count(*) into n from public.research_capture_fail(oid,worker,old_token,'worker_interrupted',true);assert n=0;
 -- A crash leaves the row running until lease expiry, then another token claims it.
 update public.research_capture_occurrences set lease_until=clock_timestamp()-interval '1 second' where id=oid;
 select count(*) into n from public.research_capture_renew(oid,other,current_token);assert n=0;
 select * into o from public.research_capture_claim(worker);
 assert o.attempts=3 and o.lease_token<>current_token;current_token:=o.lease_token;
 select * into o from public.research_capture_fail(oid,worker,current_token,'incomplete_data',true);
 assert o.status='failed' and o.attempts=3 and o.lease_token is null;
 select count(*) into n from public.research_capture_claim(worker);assert n=0;
 -- Nonretryable failure terminates immediately, without raw error strings.
 insert into public.research_capture_occurrences(id,schedule_id,owner_id,schedule_revision,due_at)
 values('00000000-0000-4000-8000-000000000032',sid,a,1,clock_timestamp()-interval '2 hours');
 select * into o from public.research_capture_claim(worker);
 select * into o from public.research_capture_fail(o.id,worker,o.lease_token,'definition_changed',false);
 assert o.status='failed' and o.attempts=1;
 -- An expired third crash terminates without a fourth claim.
 insert into public.research_capture_occurrences(id,schedule_id,owner_id,schedule_revision,due_at,status,attempts,lease_token,lease_until,worker_id,attempt_started_at)
 values('00000000-0000-4000-8000-000000000035',sid,a,1,clock_timestamp()-interval '90 minutes','running',3,gen_random_uuid(),clock_timestamp()-interval '1 second',worker,clock_timestamp()-interval '3 minutes');
 select count(*) into n from public.research_capture_claim(worker);assert n=0;
 assert (select status='failed' and error_code='lease_exhausted' and attempts=3 from public.research_capture_occurrences where id='00000000-0000-4000-8000-000000000035');
 -- Renewal cannot keep a single attempt alive indefinitely.
 insert into public.research_capture_occurrences(id,schedule_id,owner_id,schedule_revision,due_at)
 values('00000000-0000-4000-8000-000000000033',sid,a,1,clock_timestamp()-interval '1 hour');
 select * into o from public.research_capture_claim(worker);current_token:=o.lease_token;
 update public.research_capture_occurrences set attempt_started_at=clock_timestamp()-interval '21 minutes' where id=o.id;
 select count(*) into n from public.research_capture_renew(o.id,worker,current_token);assert n=0;
 select count(*) into n from public.research_capture_fail(o.id,worker,current_token,'worker_interrupted',true);assert n=0;
 -- Off/revision change invalidates even an otherwise live token.
 update public.research_capture_schedules set enabled=false,next_due_at=null,revision=2 where id=sid;
 select count(*) into n from public.research_capture_renew(o.id,worker,current_token);assert n=0;
 select count(*) into n from public.research_capture_fail(o.id,worker,current_token,'worker_interrupted',true);assert n=0;
 select count(*) into n from public.research_capture_claim(worker);assert n=0;
 assert (select status='cancelled' and error_code='schedule_changed' and lease_token is null from public.research_capture_occurrences where id=o.id);
end $$;
reset role;
rollback;
