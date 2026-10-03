-- ISOLATED LOCAL DATABASE ONLY. All fixture writes roll back.
\set ON_ERROR_STOP on
begin;
do $$ begin
  assert (select relrowsecurity from pg_class where oid='public.screen_captures'::regclass);
  assert not has_table_privilege('anon','public.screen_captures','SELECT');
  assert not has_table_privilege('authenticated','public.screen_captures','INSERT');
  assert not has_table_privilege('service_role','public.screen_captures','UPDATE');
  assert not has_table_privilege('service_role','public.screen_captures','DELETE');
  assert not has_function_privilege('anon','public.screen_capture_append(text,jsonb)','EXECUTE');
  assert not has_function_privilege('authenticated','public.screen_capture_append(text,jsonb)','EXECUTE');
  assert has_function_privilege('service_role','public.screen_capture_append(text,jsonb)','EXECUTE');
end $$;
set local role service_role;
do $$ declare k text := 'screen_history:'||repeat('a',16)||':'||repeat('b',64); s jsonb; batch jsonb;
begin
 s := '{"id":"native-one","version":2,"at":"2026-10-02T00:00:00Z","complete":true,"members":[{"code":"US.BRK.B"}]}';
 batch := jsonb_build_array(jsonb_build_object('id','native-one','snapshot',s));
 assert public.screen_capture_append(k,batch)=1;
 assert public.screen_capture_append(k,batch)=0; -- exact retry is idempotent
 assert (select members from public.screen_captures where history_key=k and id='native-one')=1;
 begin
  perform public.screen_capture_append(k,jsonb_build_array(jsonb_build_object('id','native-one','snapshot',jsonb_set(s,'{members}','[]'))));
  raise exception 'Different evidence overwrote immutable identity';
 exception when unique_violation then null; end;
 begin
  perform public.screen_capture_append(k,jsonb_build_array(jsonb_build_object('id','partial-one','snapshot',jsonb_set(s,'{id}','"partial-one"')),jsonb_build_object('id','broken','snapshot','{}'::jsonb)));
  raise exception 'Invalid batch did not fail';
 exception when invalid_parameter_value then null; end;
 assert not exists(select 1 from public.screen_captures where history_key=k and id='partial-one');
 begin
  insert into public.screen_captures(history_key,id,at,source_clock,complete,members,version,snapshot)
  values(k,'invalid-direct',now(),'unverified',true,0,2,'{}');
  raise exception 'Invalid payload accepted through direct insert';
 exception when check_violation then null; end;
end $$;
reset role;
do $$ begin
 begin
  update public.screen_captures set source_clock='altered' where id='native-one';
  raise exception 'Capture update was allowed';
 exception when object_not_in_prerequisite_state then null; end;
 begin
  delete from public.screen_captures where id='native-one';
  raise exception 'Capture delete was allowed';
 exception when object_not_in_prerequisite_state then null; end;
 begin
  truncate public.screen_captures;
  raise exception 'Capture truncate was allowed';
 exception when object_not_in_prerequisite_state then null; end;
end $$;
rollback;
