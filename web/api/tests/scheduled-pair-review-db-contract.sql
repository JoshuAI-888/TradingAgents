-- Isolated local PostgreSQL only. Schema/fixtures roll back.
\set ON_ERROR_STOP on
begin;
\ir ../../../supabase/migrations/20261002102231_private_capture_schedules.sql
\ir ../../../supabase/migrations/20261002103206_private_capture_occurrences.sql
\ir ../../../supabase/migrations/20261002103538_private_capture_leases.sql
\ir ../../../supabase/migrations/20261002103911_private_capture_publication.sql
\ir ../../../supabase/migrations/20261002105321_private_scheduled_pair_reviews.sql
do $$ begin
 assert (select relrowsecurity from pg_class where oid='public.research_scheduled_pair_reviews'::regclass);
 assert not has_table_privilege('anon','public.research_scheduled_pair_reviews','SELECT');
 assert not has_table_privilege('authenticated','public.research_scheduled_pair_reviews','UPDATE');
 assert not has_function_privilege('authenticated','public.research_scheduled_pair_review_save(uuid,uuid,uuid,uuid,text,integer,text,text)','EXECUTE');
end $$;
set local role service_role;
do $$ declare owner uuid:='00000000-0000-4000-8000-000000000001'; other uuid:='00000000-0000-4000-8000-000000000002'; sid uuid:='00000000-0000-4000-8000-000000000070'; before_id uuid:='00000000-0000-4000-8000-000000000071'; after_id uuid:='00000000-0000-4000-8000-000000000072'; third_id uuid:='00000000-0000-4000-8000-000000000073'; cid uuid; i integer:=0; n integer; r integer; state jsonb; h text;
begin
 insert into public.research_capture_schedules(id,owner_id,definition_hash,definition,name,cadence) values(sid,owner,repeat('a',64),'{}','Review fixture','{}');
 foreach cid in array array[before_id,after_id,third_id] loop
  i:=i+1;
  insert into public.research_capture_occurrences(id,schedule_id,owner_id,schedule_revision,due_at) values(cid,sid,owner,1,clock_timestamp()+i*interval '1 minute');
  insert into public.research_private_captures(id,schedule_id,owner_id,schedule_revision,definition_hash,snapshot,publish_token,publish_worker)
   values(cid,sid,owner,1,repeat('a',64),jsonb_build_object('id',cid,'at',clock_timestamp()+i*interval '1 minute','version',2,'complete',true,'definition','{}'::jsonb,'members','[{"code":"US.A"}]'::jsonb),gen_random_uuid(),gen_random_uuid());
 end loop;
 select count(*) into n from public.research_scheduled_pair_review_save(owner,sid,before_id,after_id,'US.A',0,'First','reviewed');assert n=1;
 select count(*) into n from public.research_scheduled_pair_review_save(owner,sid,before_id,after_id,'US.A',0,'Stale create','unreviewed');assert n=0;
 select revision into r from public.research_scheduled_pair_review_save(owner,sid,before_id,after_id,'US.A',1,'Updated','in_review');assert r=2;
 select count(*) into n from public.research_scheduled_pair_review_save(owner,sid,before_id,after_id,'US.A',1,'Stale edit','reviewed');assert n=0;
 select count(*) into n from public.research_scheduled_pair_review_save(owner,sid,after_id,third_id,'US.A',0,'Different pair','unreviewed');assert n=1;
 select count(*) into n from public.research_scheduled_pair_review_save(other,sid,before_id,after_id,'US.A',0,'Stolen','reviewed');assert n=0;
 select count(*) into n from public.research_scheduled_pair_review_save(owner,sid,after_id,before_id,'US.A',0,'Reversed','reviewed');assert n=0;
 select count(*) into n from public.research_scheduled_pair_review_save(owner,sid,before_id,after_id,'US.MISSING',0,'Absent','reviewed');assert n=0;
 state:=public.research_scheduled_pair_review_read(owner,sid,before_id,after_id);h:=state->>'revision_hash';
 assert state->'confirmed'='true'::jsonb and jsonb_array_length(state->'reviews')=1 and state->'notes'='[]'::jsonb;
 assert length(h)=64 and not (state->'reviews'->0 ? 'note');
 state:=public.research_scheduled_pair_review_read(owner,sid,before_id,after_id,array['US.A'],h);
 assert state->'confirmed'='true'::jsonb and state->'reviews'='[]'::jsonb and state->'notes'->0->>'note'='Updated';
 perform public.research_scheduled_pair_review_save(owner,sid,before_id,after_id,'US.A',2,'Concurrent update','reviewed');
 state:=public.research_scheduled_pair_review_read(owner,sid,before_id,after_id,array['US.A'],h);
 assert state->'confirmed'='false'::jsonb and state->'notes'='[]'::jsonb;
 assert public.research_scheduled_pair_review_read(other,sid,before_id,after_id)->'reviews'='[]'::jsonb;
end $$;
reset role;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000001',true);
set local role authenticated;
do $$ begin assert (select count(*) from public.research_scheduled_pair_reviews)=2;end $$;
reset role;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000002',true);
set local role authenticated;
do $$ begin assert (select count(*) from public.research_scheduled_pair_reviews)=0;end $$;
reset role;
rollback;
