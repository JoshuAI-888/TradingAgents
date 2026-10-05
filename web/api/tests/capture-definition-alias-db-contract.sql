\set ON_ERROR_STOP on
begin;
\ir ../../../supabase/migrations/20261002121721_screen_capture_definition_aliases.sql
set local role service_role;
do $$
declare k1 text:='screen_history:'||repeat('1',16)||':'||repeat('a',64);
 k2 text:='screen_history:'||repeat('1',16)||':'||repeat('b',64);
 k3 text:='screen_history:'||repeat('2',16)||':'||repeat('a',64);
 k4 text:='screen_history:'||repeat('1',16)||':'||repeat('c',64);
 minimal jsonb:='{"filters":[{"field":"price","max":10}]}'::jsonb;
 decorated jsonb:='{"filters":[{"field":"price","min":null,"max":10,"_label":"Price"}]}'::jsonb;
 s jsonb;batch jsonb;fingerprint text:=repeat('f',64);n integer;
begin
 if public.screen_definition_semantic(decorated)<>minimal then raise exception 'normalization mismatch';end if;
 if public.screen_definition_semantic('{"filters":[{"field":"volume","min":0,"days":30},{"field":"volume","min":0,"days":60}]}')<>'{"filters":[{"field":"volume","min":0,"days":30},{"field":"volume","min":0,"days":60}]}'::jsonb then raise exception 'slots or zero bounds changed';end if;
 s:=jsonb_build_object('id','a','version',2,'at','2026-10-01T00:00:00Z','complete',true,'members','[]'::jsonb,'definition',decorated);
 batch:=jsonb_build_array(jsonb_build_object('id','a','snapshot',s));
 if public.screen_capture_append_with_alias(k1,batch,'a',fingerprint,minimal)<>1 then raise exception 'append missing';end if;
 if public.screen_capture_append_with_alias(k1,batch,'a',fingerprint,minimal)<>0 then raise exception 'retry duplicated';end if;
 if public.screen_capture_definition_alias_register(k1,'a',fingerprint,minimal) then raise exception 'register duplicated';end if;
 perform public.screen_capture_append_with_alias(k2,batch,'a',fingerprint,minimal);
 perform public.screen_capture_append_with_alias(k3,batch,'a',fingerprint,minimal);
 select count(*) into n from public.screen_capture_definition_aliases where owner_namespace=repeat('1',16) and semantic_digest=fingerprint;
 if n<>2 then raise exception 'namespace grouping failed';end if;
 select count(*) into n from public.screen_capture_definition_aliases where owner_namespace=repeat('2',16) and semantic_digest=fingerprint;
 if n<>1 then raise exception 'other namespace grouping failed';end if;
 if (select snapshot->'definition' from public.screen_captures where history_key=k1 and id='a')<>decorated then raise exception 'original evidence changed';end if;
 begin
  perform public.screen_capture_definition_alias_register(k1,'a',repeat('e',64),minimal);
  raise exception 'conflicting mapping accepted';
 exception when unique_violation then null;end;
 begin
  perform public.screen_capture_append_with_alias(k4,batch,'a',fingerprint,'{"filters":[{"field":"price","max":0}]}');
  raise exception 'false canonical mapping accepted';
 exception when invalid_parameter_value then null;end;
 if exists(select 1 from public.screen_captures where history_key=k4) then raise exception 'failed mapping left a partial capture';end if;
 begin
  perform public.screen_capture_definition_alias_register(k4,'a',fingerprint,minimal);
  raise exception 'cross-key anchor accepted';
 exception when invalid_parameter_value then null;end;
end;
$$;
reset role;
do $$
begin
 if not (select relrowsecurity from pg_class where oid='public.screen_capture_definition_aliases'::regclass) then raise exception 'RLS absent';end if;
 if has_table_privilege('anon','public.screen_capture_definition_aliases','SELECT') or has_table_privilege('authenticated','public.screen_capture_definition_aliases','SELECT') then raise exception 'shared aliases publicly readable';end if;
 if has_function_privilege('anon','public.screen_capture_definition_alias_register(text,text,text,jsonb)','EXECUTE') or has_function_privilege('authenticated','public.screen_capture_append_with_alias(text,jsonb,text,text,jsonb)','EXECUTE') then raise exception 'client RPC access';end if;
 if has_table_privilege('service_role','public.screen_capture_definition_aliases','UPDATE') or has_table_privilege('service_role','public.screen_capture_definition_aliases','DELETE') then raise exception 'mutable mapping grants';end if;
 begin
  update public.screen_capture_definition_aliases set semantic_digest=repeat('0',64);
  raise exception 'mapping mutation accepted';
 exception when sqlstate '55000' then null;end;
 begin
  truncate public.screen_capture_definition_aliases;
  raise exception 'mapping truncate accepted';
 exception when sqlstate '55000' then null;end;
end;
$$;
rollback;
