-- Isolated local PostgreSQL only. All schema/fixtures roll back.
\set ON_ERROR_STOP on
begin;
\ir ../../../supabase/migrations/20261002102231_private_capture_schedules.sql
\ir ../../../supabase/migrations/20261002103206_private_capture_occurrences.sql
\ir ../../../supabase/migrations/20261002103538_private_capture_leases.sql
\ir ../../../supabase/migrations/20261002103911_private_capture_publication.sql
do $$ begin
 assert (select relrowsecurity from pg_class where oid='public.research_private_captures'::regclass);
 assert not has_table_privilege('anon','public.research_private_captures','SELECT');
 assert not has_table_privilege('authenticated','public.research_private_captures','INSERT');
 assert not has_table_privilege('service_role','public.research_private_captures','UPDATE');
 assert not has_function_privilege('authenticated','public.research_capture_publish(uuid,uuid,uuid,jsonb)','EXECUTE');
end $$;
set local role service_role;
do $$ declare sid uuid:='00000000-0000-4000-8000-000000000060'; oid uuid:='00000000-0000-4000-8000-000000000061'; owner uuid:='00000000-0000-4000-8000-000000000001'; worker uuid:='00000000-0000-4000-8000-000000000040'; other uuid:='00000000-0000-4000-8000-000000000041'; o public.research_capture_occurrences%rowtype; payload jsonb; n integer; def jsonb:='{"market":"US","src":"moo","etfs":false,"watchlist_only":false,"filters":[],"preset":null}'; old_token uuid;
begin
 insert into public.research_capture_schedules(id,owner_id,definition_hash,definition,name,cadence,enabled,activated_at,next_due_at)
 values(sid,owner,repeat('a',64),jsonb_build_object('screen',def,'schema_version',1),'Private publish','{}',true,clock_timestamp()-interval '2 days',clock_timestamp()+interval '1 day');
 insert into public.research_capture_occurrences(id,schedule_id,owner_id,schedule_revision,due_at) values(oid,sid,owner,1,clock_timestamp()-interval '1 hour');
 select * into o from public.research_capture_claim(worker);old_token:=o.lease_token;
 payload:=jsonb_build_object('id',oid,'version',3,'at',clock_timestamp(),'source_at',clock_timestamp(),'source_clock','stored_universe','definition',def,
  'members','[]'::jsonb,'complete',true,'observations','[]'::jsonb,'observation_scope','eligible_stored_universe','eligible_count',0);
 select count(*) into n from public.research_capture_publish(oid,other,old_token,payload);assert n=0;
 begin
  perform public.research_capture_publish(oid,worker,old_token,jsonb_set(payload,'{complete}','false'));
  raise exception 'Incomplete capture accepted';
 exception when invalid_parameter_value then null;end;
 begin
  perform public.research_capture_publish(oid,worker,old_token,jsonb_set(payload,'{eligible_count}','1'));
  raise exception 'Incomplete observation count accepted';
 exception when invalid_parameter_value then null;end;
 begin
  perform public.research_capture_publish(oid,worker,old_token,jsonb_set(payload,'{members}','[{"code":"HK.00700"}]'));
  raise exception 'Wrong-market membership accepted';
 exception when invalid_parameter_value then null;end;
 begin
  perform public.research_capture_publish(oid,worker,old_token,jsonb_set(payload,'{source_clock}','"generation_publication"'));
  raise exception 'Missing generation identity accepted';
 exception when invalid_parameter_value then null;end;
 begin
  perform public.research_capture_publish(oid,worker,old_token,jsonb_set(payload,'{source_at}',to_jsonb((clock_timestamp()-interval '2 days')::text)));
  raise exception 'Stale source accepted';
 exception when invalid_parameter_value then null;end;
 assert not exists(select 1 from public.research_private_captures);
 assert (select status from public.research_capture_occurrences where id=oid)='running';
 select count(*) into n from public.research_capture_publish(oid,worker,old_token,payload);assert n=1;
 assert (select status='succeeded' and lease_token is null from public.research_capture_occurrences where id=oid);
 select count(*) into n from public.research_capture_publish(oid,worker,old_token,payload);assert n=1;
 select count(*) into n from public.research_capture_publish(oid,other,old_token,payload);assert n=0;
 select count(*) into n from public.research_capture_publish(oid,worker,old_token,jsonb_set(payload,'{eligible_count}','2'));assert n=0;
 assert (select count(*) from public.research_private_captures)=1;
 -- Existing success stays intact while an expired attempt cannot publish.
 oid:='00000000-0000-4000-8000-000000000062';
 insert into public.research_capture_occurrences(id,schedule_id,owner_id,schedule_revision,due_at) values(oid,sid,owner,1,clock_timestamp());
 select * into o from public.research_capture_claim(worker);
 payload:=jsonb_set(payload,'{id}',to_jsonb(oid::text));
 update public.research_capture_occurrences set lease_until=clock_timestamp()-interval '1 second' where id=oid;
 select count(*) into n from public.research_capture_publish(oid,worker,o.lease_token,payload);assert n=0;
 update public.research_capture_occurrences set lease_until=clock_timestamp()+interval '1 minute' where id=oid;
 update public.research_capture_occurrences set lease_token=gen_random_uuid() where id=oid;
 select count(*) into n from public.research_capture_publish(oid,worker,o.lease_token,payload);assert n=0;
 update public.research_capture_occurrences set lease_token=o.lease_token,attempt_started_at=clock_timestamp()-interval '21 minutes' where id=oid;
 select count(*) into n from public.research_capture_publish(oid,worker,o.lease_token,payload);assert n=0;
 update public.research_capture_occurrences set attempt_started_at=clock_timestamp() where id=oid;
 update public.research_capture_schedules set revision=2 where id=sid;
 select count(*) into n from public.research_capture_publish(oid,worker,o.lease_token,payload);assert n=0;
 update public.research_capture_schedules set enabled=false,next_due_at=null where id=sid;
 select count(*) into n from public.research_capture_publish(oid,worker,o.lease_token,payload);assert n=0;
 assert (select count(*) from public.research_private_captures)=1;
 -- Exact lost-response confirmation survives schedule-off, without inserting.
 payload:=jsonb_set(payload,'{id}','"00000000-0000-4000-8000-000000000061"');
 select count(*) into n from public.research_capture_publish('00000000-0000-4000-8000-000000000061',worker,old_token,payload);assert n=1;
end $$;
reset role;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000002',true);
set local role authenticated;
do $$ begin assert (select count(*) from public.research_private_captures)=0;end $$;
reset role;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000001',true);
set local role authenticated;
do $$ begin assert (select count(*) from public.research_private_captures)=1;end $$;
reset role;
rollback;
