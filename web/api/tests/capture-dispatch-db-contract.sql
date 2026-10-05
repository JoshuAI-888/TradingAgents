-- Isolated local DB only. New schemas and fixture records roll back.
\set ON_ERROR_STOP on
begin;
\ir ../../../supabase/migrations/20261002102231_private_capture_schedules.sql
\ir ../../../supabase/migrations/20261002103206_private_capture_occurrences.sql
do $$ begin
 assert (select relrowsecurity from pg_class where oid='public.research_capture_occurrences'::regclass);
 assert not has_table_privilege('anon','public.research_capture_occurrences','SELECT');
 assert not has_table_privilege('authenticated','public.research_capture_occurrences','INSERT');
 assert not has_table_privilege('authenticated','public.research_capture_occurrences','UPDATE');
 assert not has_function_privilege('authenticated','public.research_capture_dispatch(uuid,uuid,integer,timestamptz,timestamptz,timestamptz,uuid)','EXECUTE');
end $$;
set local role service_role;
do $$ declare a uuid:='00000000-0000-4000-8000-000000000001'; b uuid:='00000000-0000-4000-8000-000000000002'; sid uuid; oid uuid:='00000000-0000-4000-8000-000000000011'; due timestamptz:=clock_timestamp()-interval '1 minute'; expected timestamptz:=clock_timestamp()-interval '1 day'; next_due timestamptz:=clock_timestamp()+interval '1 day'; n integer; c jsonb:='{"timezone":"UTC","hour":16,"minute":0,"weekdays":[0,1,2,3,4]}'; d jsonb:='{"screen":{"market":"US"},"schema_version":1}';
begin
 select id into sid from public.research_capture_schedule_save(a,repeat('a',64),0,d,'Private',c,false,null);
 update public.research_capture_schedules set enabled=true,activated_at=expected-interval '1 day',next_due_at=expected where id=sid;
 select count(*) into n from public.research_capture_dispatch(sid,b,1,expected,due,next_due,oid);assert n=0;
 select count(*) into n from public.research_capture_dispatch(sid,a,2,expected,due,next_due,oid);assert n=0;
 select count(*) into n from public.research_capture_dispatch(sid,a,1,expected+interval '1 minute',due,next_due,oid);assert n=0;
 select count(*) into n from public.research_capture_dispatch(sid,a,1,expected,due,next_due,oid);assert n=1;
 assert (select next_due_at from public.research_capture_schedules where id=sid)=next_due;
 select count(*) into n from public.research_capture_dispatch(sid,a,1,expected,due,next_due,oid);assert n=1;
 assert (select count(*) from public.research_capture_occurrences)=1;
 begin
  perform public.research_capture_dispatch(sid,a,1,expected,due,next_due,'00000000-0000-4000-8000-000000000012');
  raise exception 'Conflicting occurrence identity accepted';
 exception when invalid_parameter_value then null;end;
 perform public.research_capture_schedule_save(a,repeat('a',64),1,d,'Paused',c,false,null);
 select count(*) into n from public.research_capture_dispatch(sid,a,1,expected,due,next_due,oid);assert n=0;
 assert (select status='pending' and attempts=0 and lease_token is null from public.research_capture_occurrences where id=oid);
 -- A second owner's independent occurrence is isolated by RLS.
 select id into sid from public.research_capture_schedule_save(b,repeat('a',64),0,d,'Other private',c,false,null);
 update public.research_capture_schedules set enabled=true,activated_at=expected-interval '1 day',next_due_at=expected where id=sid;
 perform public.research_capture_dispatch(sid,b,1,expected,due,next_due,'00000000-0000-4000-8000-000000000013');
 assert (select count(*) from public.research_capture_occurrences)=2;
end $$;
reset role;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000001',true);
set local role authenticated;
do $$ begin
 assert (select count(*) from public.research_capture_occurrences)=1;
 assert not exists(select 1 from public.research_capture_occurrences where owner_id='00000000-0000-4000-8000-000000000002');
end $$;
reset role;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000002',true);
set local role authenticated;
do $$ begin assert (select count(*) from public.research_capture_occurrences)=1;end $$;
reset role;
rollback;
