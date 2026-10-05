\set ON_ERROR_STOP on
begin;
\ir ../../../supabase/migrations/20261002121721_screen_capture_definition_aliases.sql
\ir ../../../supabase/migrations/20261002124757_cross_history_pair_reviews.sql
\ir ../../../supabase/migrations/20261002134257_duplicate_capture_review_scopes.sql
set local role service_role;
do $$
declare k1 text:='screen_history:'||repeat('7',16)||':'||repeat('a',64);k2 text:='screen_history:'||repeat('7',16)||':'||repeat('b',64);
 divergent text:='screen_history:'||repeat('7',16)||':'||repeat('c',64);outside text:='screen_history:'||repeat('8',16)||':'||repeat('a',64);
 owner uuid:='00000000-0000-4000-8000-000000000001';second uuid:='00000000-0000-4000-8000-000000000002';
 canonical jsonb:='{"filters":[{"field":"price","max":10}]}'::jsonb;s jsonb;a jsonb;k text;outcome jsonb;
begin
 s:=jsonb_build_object('id','dup-before','version',2,'at','2026-10-01T00:00:00Z','complete',true,
  'members','[{"code":"US.A","price":1},{"code":"US.B","price":2}]'::jsonb,'definition',canonical);
 a:=jsonb_set(jsonb_set(s,'{id}','"dup-after"'),'{at}','"2026-10-02T00:00:00Z"');
 foreach k in array array[k1,k2,outside] loop
  perform public.screen_capture_append_with_alias(k,jsonb_build_array(jsonb_build_object('id','dup-before','snapshot',s),jsonb_build_object('id','dup-after','snapshot',a)),'dup-before',repeat('f',64),canonical);
 end loop;
 perform public.research_pair_review_save(owner,k1,'dup-before','dup-after','US.A',0,'Original note','reviewed');
 perform public.research_pair_review_save(owner,k1,'dup-before','dup-after','US.A',1,'Exact existing revision','reviewed');
 perform public.research_cross_history_pair_review_save(owner,k1,k2,'dup-before','dup-after','US.A',0,'Separate cross anchor','in_review');
 perform public.research_pair_review_save(owner,k2,'dup-before','dup-after','US.B',0,'Other code same pair','reviewed');
 perform public.research_pair_review_save(second,k2,'dup-before','dup-after','US.A',0,'Other owner secret','reviewed');
 perform public.research_pair_review_save(owner,outside,'dup-before','dup-after','US.A',0,'Other namespace note','reviewed');
 s:=jsonb_set(s,'{members,0,price}','9');a:=jsonb_set(a,'{members,0,price}','9');
 perform public.screen_capture_append_with_alias(divergent,jsonb_build_array(jsonb_build_object('id','dup-before','snapshot',s),jsonb_build_object('id','dup-after','snapshot',a)),'dup-before',repeat('f',64),canonical);
 perform public.research_pair_review_save(owner,divergent,'dup-before','dup-after','US.A',0,'Divergent evidence note','reviewed');
 outcome:=public.research_duplicate_pair_review_scopes(owner,k2,k2,'dup-before','dup-after');
 assert outcome->>'alias_qualified'='true' and jsonb_array_length(outcome->'reviews')=3;
 assert outcome->'reviews'->0->>'note'='Exact existing revision' and outcome->'reviews'->0->>'revision'='2';
 assert outcome->'reviews'->1->>'note'='Separate cross anchor' and outcome->'reviews'->1->>'revision'='1';
 assert outcome->'reviews'->2->>'code'='US.B';
 assert public.research_duplicate_pair_review_scopes(second,k1,k1,'dup-before','dup-after')->'reviews'->0->>'note'='Other owner secret';
 assert (select note from public.research_pair_reviews where owner_id=owner and history_key=k1 and code='US.A')='Exact existing revision';
 assert public.research_duplicate_pair_review_scopes(owner,k2,k2,'dup-after','dup-before')->>'alias_qualified'='false';
 begin
  perform public.research_duplicate_pair_review_scopes(owner,k1,outside,'dup-before','dup-after');
  raise exception 'namespace escape accepted';
 exception when invalid_parameter_value then null;end;
 assert not has_function_privilege('authenticated','public.research_duplicate_pair_review_scopes(uuid,text,text,text,text)','EXECUTE');
 assert not has_function_privilege('anon','public.research_duplicate_pair_review_scopes(uuid,text,text,text,text)','EXECUTE');
end;$$;
reset role;
rollback;
