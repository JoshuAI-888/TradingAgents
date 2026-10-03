\set ON_ERROR_STOP on
begin;
\ir ../../../supabase/migrations/20261002121721_screen_capture_definition_aliases.sql
\ir ../../../supabase/migrations/20261002122251_screen_capture_alias_backfill.sql
set local role service_role;
do $$
declare k text:='screen_history:'||repeat('3',16)||':'||repeat('a',64);other text:='screen_history:'||repeat('4',16)||':'||repeat('a',64);
 s jsonb;n integer;i integer;cursor_id text;
begin
 for i in 1..205 loop
  s:=jsonb_build_object('id','backfill-'||lpad(i::text,3,'0'),'version',2,'at','2026-10-01T00:00:00Z','complete',true,'members','[]'::jsonb,'definition','{"filters":[{"field":"price","max":10,"min":null,"_label":"Price"}]}'::jsonb,'observations',jsonb_build_array(jsonb_build_object('private_fixture','never returned by backfill')));
  perform public.screen_capture_append(k,jsonb_build_array(jsonb_build_object('id',s->>'id','snapshot',s)));
 end loop;
 perform public.screen_capture_append(other,jsonb_build_array(jsonb_build_object('id',s->>'id','snapshot',s)));
 select count(*) into n from public.screen_capture_alias_backfill_page(repeat('3',16),null,null,20);
 if n<>21 then raise exception 'first metadata page not bounded';end if;
 select capture_id into cursor_id from public.screen_capture_alias_backfill_page(repeat('3',16),null,null,20) offset 19 limit 1;
 if cursor_id<>'backfill-020' then raise exception 'cursor order incorrect';end if;
 select count(*) into n from public.screen_capture_alias_backfill_page(repeat('3',16),k,cursor_id,20);
 if n<>21 then raise exception 'next metadata page missing';end if;
 select capture_id into cursor_id from public.screen_capture_alias_backfill_page(repeat('3',16),k,cursor_id,20) limit 1;
 if cursor_id<>'backfill-021' then raise exception 'cursor repeated or skipped';end if;
 select count(*) into n from public.screen_capture_alias_backfill_page(repeat('3',16),k,'backfill-200',20);
 if n<>5 then raise exception 'final page incorrect';end if;
 if exists(select 1 from public.screen_capture_alias_backfill_page(repeat('3',16),null,null,100) where history_key<>k or definition?'observations') then raise exception 'scope or metadata projection failed';end if;
 begin
  perform public.screen_capture_alias_backfill_page(repeat('3',16),other,'backfill-001',20);
  raise exception 'cross-namespace cursor accepted';
 exception when invalid_parameter_value then null;end;
 begin
  perform public.screen_capture_alias_backfill_page(repeat('3',16),k,null,20);
  raise exception 'partial cursor accepted';
 exception when invalid_parameter_value then null;end;
 begin
  perform public.screen_capture_alias_backfill_page(repeat('3',16),null,null,101);
  raise exception 'unbounded page accepted';
 exception when invalid_parameter_value then null;end;
end;
$$;
reset role;
do $$
begin
 if has_function_privilege('anon','public.screen_capture_alias_backfill_page(text,text,text,integer)','EXECUTE') or has_function_privilege('authenticated','public.screen_capture_alias_backfill_page(text,text,text,integer)','EXECUTE') then raise exception 'client backfill access';end if;
 if not exists(select 1 from pg_indexes where schemaname='public' and indexname='screen_capture_namespace_backfill') then raise exception 'namespace paging index missing';end if;
end;
$$;
rollback;
