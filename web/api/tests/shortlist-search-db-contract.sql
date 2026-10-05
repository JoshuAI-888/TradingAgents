-- ISOLATED TEST DATABASE ONLY. Disposable quote fixture and research schema required.
begin;
insert into public.research_lists(id,owner_id,name) values
 ('00000000-0000-4000-8000-000000000003','00000000-0000-4000-8000-000000000001','Search fixture');
insert into public.research_list_items(list_id,owner_id,code,review_status,note)
select '00000000-0000-4000-8000-000000000003'::uuid,'00000000-0000-4000-8000-000000000001'::uuid,
 'US.T'||lpad(i::text,4,'0'),case when i%2=0 then 'reviewed' else 'unreviewed' end,'not a company name'
from generate_series(0,1199) i;
insert into public.screener_quotes(code,row)
select 'US.T'||lpad(i::text,4,'0'),jsonb_build_object('code','US.T'||lpad(i::text,4,'0'),
 'name',case when i%2=0 then 'Other company' else $name$O'Reilly & Sons$name$ end)
from generate_series(0,1199) i;
insert into public.research_list_items(list_id,owner_id,code) values
 ('00000000-0000-4000-8000-000000000003','00000000-0000-4000-8000-000000000001','US.WRONG'),
 ('00000000-0000-4000-8000-000000000003','00000000-0000-4000-8000-000000000001','US.MISSING');
insert into public.screener_quotes(code,row) values ('US.WRONG','{"code":"US.OTHER","name":"O''Reilly & Sons"}');
set local role service_role;
do $$
declare sid uuid:='00000000-0000-4000-8000-000000000003';
 owner uuid:='00000000-0000-4000-8000-000000000001'; n integer;
begin
 select count(*) into n from public.research_list_search(sid,owner,$name$o'reilly & sons$name$,'unreviewed',false,'',0,501);
 if n<>501 then raise exception 'Company matching not before pagination'; end if;
 select count(*) into n from public.research_list_search(sid,owner,$name$o'reilly & sons$name$,'unreviewed',false,'',500,501);
 if n<>100 then raise exception 'Second page lost company matches'; end if;
 if (select min(code) from public.research_list_search(sid,owner,'sons','unreviewed',false,'US.T1001',0,1))<>'US.T1003' then raise exception 'Company cursor incorrect'; end if;
 if exists(select 1 from public.research_list_search(sid,'00000000-0000-4000-8000-000000000002','sons','all',false,'',0,501)) then raise exception 'Foreign owner can search'; end if;
 if exists(select 1 from public.research_list_search(sid,owner,'not a company name','all',false,'',0,501)) then raise exception 'Search exposed note content'; end if;
 if exists(select 1 from public.research_list_search(sid,owner,'%', 'all',false,'',0,501)) then raise exception 'Literal wildcard expanded'; end if;
 if (select count(*) from public.research_list_search(sid,owner,'US.WRONG','all',false,'',0,501))<>1 then raise exception 'Canonical ticker lost'; end if;
 if (select count(*) from public.research_list_search(sid,owner,'US.MISSING','all',false,'',0,501))<>1 then raise exception 'Missing quote hid ticker'; end if;
 begin
  perform public.research_list_search(sid,owner,'query','all',false,'US.BAD,owner_id.eq.other',0,501);
  raise exception 'Invalid cursor accepted';
 exception when invalid_parameter_value then null; end;
end;
$$;
reset role;
do $$ begin
 if has_function_privilege('anon','public.research_list_search(uuid,uuid,text,text,boolean,text,integer,integer)','EXECUTE')
 or has_function_privilege('authenticated','public.research_list_search(uuid,uuid,text,text,boolean,text,integer,integer)','EXECUTE') then raise exception 'Browser can invoke private search'; end if;
 if (select prosecdef from pg_proc where oid='public.research_list_search(uuid,uuid,text,text,boolean,text,integer,integer)'::regprocedure) then raise exception 'Search bypasses invoker security'; end if;
end; $$;
rollback;
select 'shortlist company search contracts passed' as result;
