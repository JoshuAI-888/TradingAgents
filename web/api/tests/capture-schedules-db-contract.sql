-- Isolated local database only; schema and fixture records roll back.
\set ON_ERROR_STOP on
begin;
\ir ../../../supabase/migrations/20261002102231_private_capture_schedules.sql
do $$ begin
 assert (select relrowsecurity from pg_class where oid='public.research_capture_schedules'::regclass);
 assert not has_table_privilege('anon','public.research_capture_schedules','SELECT');
 assert not has_table_privilege('authenticated','public.research_capture_schedules','INSERT');
 assert not has_table_privilege('authenticated','public.research_capture_schedules','UPDATE');
 assert not has_function_privilege('authenticated','public.research_capture_schedule_save(uuid,text,integer,jsonb,text,jsonb,boolean,timestamptz)','EXECUTE');
 assert has_function_privilege('service_role','public.research_capture_schedule_save(uuid,text,integer,jsonb,text,jsonb,boolean,timestamptz)','EXECUTE');
end $$;
set local role service_role;
do $$ declare a uuid:='00000000-0000-4000-8000-000000000001'; b uuid:='00000000-0000-4000-8000-000000000002'; h text:=repeat('a',64); d jsonb:='{"schema_version":1,"screen":{"market":"US"}}'; c jsonb:='{"timezone":"America/New_York","hour":16,"minute":15,"weekdays":[0,1,2,3,4]}'; n integer; r integer; i integer;
begin
 select count(*) into n from public.research_capture_schedule_save(a,h,0,d,'First',c,false,null);assert n=1;
 select count(*) into n from public.research_capture_schedule_save(a,h,0,d,'Duplicate',c,false,null);assert n=0;
 select revision into r from public.research_capture_schedule_save(a,h,1,d,'Enabled',c,true,clock_timestamp()+interval '1 day');assert r=2;
 select count(*) into n from public.research_capture_schedule_save(a,h,1,d,'Stale',c,false,null);assert n=0;
 select count(*) into n from public.research_capture_schedule_save(a,h,2,'{}','Changed definition',c,false,null);assert n=0;
 select revision into r from public.research_capture_schedule_save(a,h,2,d,'Paused',c,false,null);assert r=3;
 assert (select next_due_at is null and not enabled from public.research_capture_schedules where owner_id=a and definition_hash=h);
 select count(*) into n from public.research_capture_schedule_save(b,h,0,d,'Other',c,false,null);assert n=1;
 begin
  perform public.research_capture_schedule_save(a,repeat('b',64),0,d,'Bad days',jsonb_set(c,'{weekdays}','[0,0]'),false,null);
  raise exception 'Duplicate weekdays accepted';
 exception when invalid_parameter_value then null;end;
 begin
  perform public.research_capture_schedule_save(a,repeat('b',64),0,d,'Bad zone',jsonb_set(c,'{timezone}','"Invalid/Zone"'),false,null);
  raise exception 'Invalid zone accepted';
 exception when invalid_parameter_value then null;end;
 begin
  perform public.research_capture_schedule_save(a,repeat('b',64),0,d,'Invalid due',c,true,null);
  raise exception 'Missing due accepted';
 exception when invalid_parameter_value then null;end;
 for i in 1..99 loop
  perform public.research_capture_schedule_save(a,lpad(to_hex(i),64,'0'),0,d,'Bounded',c,false,null);
 end loop;
 assert (select count(*) from public.research_capture_schedules where owner_id=a)=100;
 begin
  perform public.research_capture_schedule_save(a,repeat('f',64),0,d,'Over quota',c,false,null);
  raise exception 'Quota exceeded';
 exception when program_limit_exceeded then null;end;
 select revision into r from public.research_capture_schedule_save(a,h,3,d,'Edit at quota',c,false,null);assert r=4;
end $$;
reset role;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000001',true);
set local role authenticated;
do $$ begin
 assert (select count(*) from public.research_capture_schedules)=100;
 assert not exists(select 1 from public.research_capture_schedules where owner_id='00000000-0000-4000-8000-000000000002');
 assert (select name from public.research_capture_schedules where definition_hash=repeat('a',64))='Edit at quota';
end $$;
reset role;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000002',true);
set local role authenticated;
do $$ begin assert (select count(*) from public.research_capture_schedules)=1;end $$;
reset role;
rollback;
