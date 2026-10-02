\set ON_ERROR_STOP on
begin;
\ir ../../../supabase/migrations/20261002121721_screen_capture_definition_aliases.sql
\ir ../../../supabase/migrations/20261002124757_cross_history_pair_reviews.sql
set local role service_role;
do $$
declare k1 text:='screen_history:'||repeat('7',16)||':'||repeat('a',64);k2 text:='screen_history:'||repeat('7',16)||':'||repeat('b',64);
 other text:='screen_history:'||repeat('8',16)||':'||repeat('b',64);canonical jsonb:='{"filters":[{"field":"price","max":10}]}'::jsonb;
 owner uuid:='00000000-0000-4000-8000-000000000001';second uuid:='00000000-0000-4000-8000-000000000002';s jsonb;n integer;r integer;
begin
 s:=jsonb_build_object('id','cross-before','version',2,'at','2026-10-01T00:00:00Z','complete',true,'members','[{"code":"US.A"}]'::jsonb,'definition',canonical);
 perform public.screen_capture_append_with_alias(k1,jsonb_build_array(jsonb_build_object('id','cross-before','snapshot',s)),'cross-before',repeat('f',64),canonical);
 s:=jsonb_set(jsonb_set(s,'{id}','"cross-after"'),'{at}','"2026-10-02T00:00:00Z"');
 s:=jsonb_set(s,'{definition,filters}','[{"field":"price","max":10,"min":null,"_label":"Price"}]');
 perform public.screen_capture_append_with_alias(k2,jsonb_build_array(jsonb_build_object('id','cross-after','snapshot',s)),'cross-after',repeat('f',64),canonical);
 perform public.screen_capture_append_with_alias(other,jsonb_build_array(jsonb_build_object('id','cross-after','snapshot',s)),'cross-after',repeat('f',64),canonical);
 -- Preserve the old same-key note contract and its exact revision/content.
 perform public.screen_capture_append(k1,jsonb_build_array(jsonb_build_object('id','cross-after','snapshot',s)));
 select count(*) into n from public.research_pair_review_save(owner,k1,'cross-before','cross-after','US.A',0,'Existing same-key note','reviewed');assert n=1;

 select count(*) into n from public.research_cross_history_pair_review_save(owner,k1,k2,'cross-before','cross-after','US.A',0,'Original scope','reviewed');assert n=1;
 select count(*) into n from public.research_cross_history_pair_review_save(owner,k1,k2,'cross-before','cross-after','US.A',0,'Stale create','reviewed');assert n=0;
 select revision into r from public.research_cross_history_pair_review_save(owner,k1,k2,'cross-before','cross-after','US.A',1,'Updated','in_review');assert r=2;
 select count(*) into n from public.research_cross_history_pair_review_save(owner,k1,k2,'cross-before','cross-after','US.A',1,'Stale edit','reviewed');assert n=0;
 assert public.research_cross_history_pair_review_read(owner,k1,k2,'cross-before','cross-after')->'reviews'->0->>'note'='Updated';
 assert public.research_cross_history_pair_review_read(second,k1,k2,'cross-before','cross-after')->'reviews'='[]'::jsonb;
 select count(*) into n from public.research_cross_history_pair_review_save(second,k1,k2,'cross-before','cross-after','US.A',0,'Other analyst','reviewed');assert n=1;
 select count(*) into n from public.research_cross_history_pair_review_save(owner,k1,k2,'cross-before','cross-after','US.MISSING',0,'Absent','reviewed');assert n=0;
 select count(*) into n from public.research_cross_history_pair_review_save(owner,k2,k1,'cross-after','cross-before','US.A',0,'Reverse','reviewed');assert n=0;
 select count(*) into n from public.research_cross_history_pair_review_save(owner,k1,other,'cross-before','cross-after','US.A',0,'Namespace escape','reviewed');assert n=0;
 -- A valid history mapping does not prove later captures still have its definition.
 s:=jsonb_set(jsonb_set(s,'{id}','"changed"'),'{definition,filters}','[{"field":"price","max":20}]');
 perform public.screen_capture_append(k2,jsonb_build_array(jsonb_build_object('id','changed','snapshot',s)));
 select count(*) into n from public.research_cross_history_pair_review_save(owner,k1,k2,'cross-before','changed','US.A',0,'Changed scope','reviewed');assert n=0;
 assert (select note from public.research_pair_reviews where owner_id=owner and history_key=k1 and previous_id='cross-before' and current_id='cross-after' and code='US.A')='Existing same-key note';
 assert (select revision from public.research_pair_reviews where owner_id=owner and history_key=k1 and previous_id='cross-before' and current_id='cross-after' and code='US.A')=1;
end $$;
reset role;
do $$ begin
 assert (select relrowsecurity from pg_class where oid='public.research_cross_history_pair_reviews'::regclass);
 assert not has_table_privilege('anon','public.research_cross_history_pair_reviews','SELECT');
 assert not has_table_privilege('authenticated','public.research_cross_history_pair_reviews','INSERT');
 assert not has_table_privilege('authenticated','public.research_cross_history_pair_reviews','UPDATE');
 assert not has_function_privilege('authenticated','public.research_cross_history_pair_review_save(uuid,text,text,text,text,text,integer,text,text)','EXECUTE');
 assert not has_function_privilege('anon','public.research_cross_history_pair_review_read(uuid,text,text,text,text)','EXECUTE');
end $$;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000001',true);
set local role authenticated;
do $$ begin assert (select count(*) from public.research_cross_history_pair_reviews)=1;end $$;
reset role;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000002',true);
set local role authenticated;
do $$ begin assert (select count(*) from public.research_cross_history_pair_reviews)=1;assert (select note from public.research_cross_history_pair_reviews)='Other analyst';end $$;
reset role;
rollback;
