\set ON_ERROR_STOP on
begin;
\ir ../../../supabase/migrations/20261002121721_screen_capture_definition_aliases.sql
\ir ../../../supabase/migrations/20261002122855_screen_capture_alias_discovery.sql
set local role service_role;
do $$
declare ns text:=repeat('5',16);k1 text:='screen_history:'||repeat('5',16)||':'||repeat('a',64);
 k2 text:='screen_history:'||repeat('5',16)||':'||repeat('b',64);raw_key text:='screen_history:'||repeat('5',16)||':'||repeat('c',64);
 other text:='screen_history:'||repeat('6',16)||':'||repeat('a',64);fingerprint text:=repeat('f',64);
 canonical jsonb:='{"filters":[{"field":"price","max":10}]}'::jsonb;s jsonb;n integer;i integer;r record;
begin
 s:=jsonb_build_object('id','same','version',2,'at','2026-10-01T00:00:00Z','complete',true,'members','[]'::jsonb,'definition',canonical);
 perform public.screen_capture_append_with_alias(k1,jsonb_build_array(jsonb_build_object('id','same','snapshot',s)),'same',fingerprint,canonical);
 perform public.screen_capture_append_with_alias(k2,jsonb_build_array(jsonb_build_object('id','same','snapshot',s)),'same',fingerprint,canonical);
 perform public.screen_capture_append_with_alias(other,jsonb_build_array(jsonb_build_object('id','same','snapshot',s)),'same',fingerprint,canonical);
 select * into r from public.screen_capture_alias_get(ns,fingerprint,canonical,raw_key,'same');
 if r.copies<>2 or r.conflicting or r.history_key<>k1 then raise exception 'identical copies or namespace resolution failed';end if;
 select * into r from public.screen_capture_alias_get(ns,fingerprint,canonical,k2,'same');
 if r.history_key<>k2 then raise exception 'original requested review key not preferred';end if;
 s:=jsonb_set(s,'{id}','"conflict"');
 perform public.screen_capture_append(k1,jsonb_build_array(jsonb_build_object('id','conflict','snapshot',s)));
 s:=jsonb_set(s,'{at}','"2026-10-02T00:00:00Z"');
 perform public.screen_capture_append(k2,jsonb_build_array(jsonb_build_object('id','conflict','snapshot',s)));
 select * into r from public.screen_capture_alias_get(ns,fingerprint,canonical,raw_key,'conflict');
 if not r.conflicting or r.copies<>2 then raise exception 'divergent evidence silently discarded';end if;
 for i in 1..105 loop
  s:=jsonb_build_object('id','page-'||lpad(i::text,3,'0'),'version',2,'at','2026-10-03T00:00:00Z','complete',true,'members','[]'::jsonb,'definition',canonical);
  perform public.screen_capture_append(case when i%2=0 then k1 else k2 end,jsonb_build_array(jsonb_build_object('id',s->>'id','snapshot',s)));
 end loop;
 select count(*) into n from public.screen_capture_alias_history(ns,fingerprint,canonical,raw_key,100,0);
 if n<>101 then raise exception 'first page not bounded';end if;
 select count(*) into n from public.screen_capture_alias_history(ns,fingerprint,canonical,raw_key,100,100);
 if n<>7 then raise exception 'merged pagination or duplicate metadata count failed';end if;
 select * into r from public.screen_capture_alias_history(ns,fingerprint,canonical,raw_key,1,0) limit 1;
 if r.id<>'page-105' then raise exception 'stable descending order failed';end if;
 select count(*) into n from public.screen_capture_alias_history(ns,fingerprint,'{"filters":[{"field":"price","max":0}]}',raw_key,100,0);
 if n<>0 then raise exception 'non-equivalent definition discovered';end if;
 begin
  perform public.screen_capture_alias_history(ns,fingerprint,canonical,other,100,0);
  raise exception 'cross-namespace raw key accepted';
 exception when invalid_parameter_value then null;end;
 begin
  perform public.screen_capture_alias_get(ns,fingerprint,canonical,other,'same');
  raise exception 'cross-namespace detail accepted';
 exception when invalid_parameter_value then null;end;
end;
$$;
reset role;
do $$
begin
 if has_function_privilege('anon','public.screen_capture_alias_history(text,text,jsonb,text,integer,integer)','EXECUTE')
  or has_function_privilege('authenticated','public.screen_capture_alias_get(text,text,jsonb,text,text)','EXECUTE') then raise exception 'browser discovery RPC grant';end if;
end;
$$;
rollback;
