-- Isolated local DB only: migration and fixture records roll back.
\set ON_ERROR_STOP on
begin;
\ir ../../../supabase/migrations/20261002093422_private_pair_reviews.sql

do $$ begin
 assert (select relrowsecurity from pg_class where oid='public.research_pair_reviews'::regclass);
 assert not has_table_privilege('anon','public.research_pair_reviews','SELECT');
 assert not has_table_privilege('authenticated','public.research_pair_reviews','INSERT');
 assert not has_table_privilege('authenticated','public.research_pair_reviews','UPDATE');
 assert not has_function_privilege('authenticated','public.research_pair_review_save(uuid,text,text,text,text,integer,text,text)','EXECUTE');
 assert has_function_privilege('service_role','public.research_pair_review_save(uuid,text,text,text,text,integer,text,text)','EXECUTE');
end $$;
set local role service_role;
do $$ declare k text:='screen_history:'||repeat('c',16)||':'||repeat('d',64); n integer; r integer;
begin
 perform public.screen_capture_append(k,'[
 {"id":"pair-one","snapshot":{"id":"pair-one","at":"2026-10-01T00:00:00Z","complete":true,"version":1,"members":[{"code":"US.BRK.B"}]}},
 {"id":"pair-two","snapshot":{"id":"pair-two","at":"2026-10-02T00:00:00Z","complete":true,"version":1,"members":[{"code":"US.BRK.B"}]}},
 {"id":"pair-three","snapshot":{"id":"pair-three","at":"2026-10-03T00:00:00Z","complete":true,"version":1,"members":[{"code":"US.BRK.B"}]}},
 {"id":"pair-incomplete","snapshot":{"id":"pair-incomplete","at":"2026-10-04T00:00:00Z","complete":false,"version":1,"members":[{"code":"US.BRK.B"}]}}
 ]');
 select count(*) into n from public.research_pair_review_save('00000000-0000-4000-8000-000000000001',k,'pair-one','pair-two','US.BRK.B',0,'first pair','reviewed');assert n=1;
 select count(*) into n from public.research_pair_review_save('00000000-0000-4000-8000-000000000001',k,'pair-one','pair-two','US.BRK.B',0,'stale create','unreviewed');assert n=0;
 select revision into r from public.research_pair_review_save('00000000-0000-4000-8000-000000000001',k,'pair-one','pair-two','US.BRK.B',1,'updated','in_review');assert r=2;
 select count(*) into n from public.research_pair_review_save('00000000-0000-4000-8000-000000000001',k,'pair-one','pair-two','US.BRK.B',1,'stale edit','reviewed');assert n=0;
 select count(*) into n from public.research_pair_review_save('00000000-0000-4000-8000-000000000001',k,'pair-two','pair-three','US.BRK.B',0,'second pair','unreviewed');assert n=1;
 select count(*) into n from public.research_pair_review_save('00000000-0000-4000-8000-000000000002',k,'pair-one','pair-two','US.BRK.B',0,'other owner','reviewed');assert n=1;
 select count(*) into n from public.research_pair_review_save('00000000-0000-4000-8000-000000000001',k,'pair-one','pair-two','US.MISSING',0,'absent','reviewed');assert n=0;
 select count(*) into n from public.research_pair_review_save('00000000-0000-4000-8000-000000000001',k,'pair-two','pair-incomplete','US.BRK.B',0,'partial','reviewed');assert n=0;
 select count(*) into n from public.research_pair_review_save('00000000-0000-4000-8000-000000000001',k,'pair-two','pair-one','US.BRK.B',0,'reversed','reviewed');assert n=0;
 assert jsonb_array_length(public.research_pair_review_read('00000000-0000-4000-8000-000000000001',k,'pair-one','pair-two')->'reviews')=1;
end $$;
reset role;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000001',true);
set local role authenticated;
do $$ begin
 assert (select count(*) from public.research_pair_reviews)=2;
 assert not exists(select 1 from public.research_pair_reviews where owner_id='00000000-0000-4000-8000-000000000002');
 assert (select note from public.research_pair_reviews where previous_id='pair-one')='updated';
end $$;
reset role;
select set_config('request.jwt.claim.sub','00000000-0000-4000-8000-000000000002',true);
set local role authenticated;
do $$ begin assert (select count(*) from public.research_pair_reviews)=1;end $$;
reset role;
rollback;
