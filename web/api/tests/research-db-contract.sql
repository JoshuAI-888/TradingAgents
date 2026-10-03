-- ISOLATED TEST DATABASE ONLY; all fixture writes are rolled back.
begin;
set local role service_role;
insert into public.research_lists(id,owner_id,name) values
 ('00000000-0000-4000-8000-000000000003','00000000-0000-4000-8000-000000000001','Quality');
do $$
declare item public.research_list_items;
begin
  if not public.research_session_active('00000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000004') then raise exception 'Live session rejected'; end if;
  if public.research_session_active('00000000-0000-4000-8000-000000000002','00000000-0000-4000-8000-000000000004') then raise exception 'Foreign session accepted'; end if;
  if public.research_session_active('00000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000005') then raise exception 'Missing session accepted'; end if;
  if exists(select 1 from public.research_list_add('00000000-0000-4000-8000-000000000003','00000000-0000-4000-8000-000000000002','US.BRK.B')) then raise exception 'Foreign add accepted'; end if;
  select * into item from public.research_list_add('00000000-0000-4000-8000-000000000003','00000000-0000-4000-8000-000000000001','US.BRK.B');
  if item.revision<>1 or item.code<>'US.BRK.B' then raise exception 'Identity lost'; end if;
  if (select revision from public.research_lists where id=item.list_id)<>2 then raise exception 'Membership did not invalidate list revision'; end if;
  select * into item from public.research_list_review(item.list_id,item.owner_id,item.code,1,'Private note','reviewed',false);
  if item.revision<>2 then raise exception 'Revision not advanced'; end if;
  if (select revision from public.research_lists where id=item.list_id)<>3 then raise exception 'Review did not invalidate list revision'; end if;
  if exists(select 1 from public.research_list_review(item.list_id,item.owner_id,item.code,1,'Overwrite','unreviewed',true)) then raise exception 'Stale review accepted'; end if;
  if (select revision from public.research_lists where id=item.list_id)<>3 then raise exception 'Failed review changed list revision'; end if;
  select * into item from public.research_list_add(item.list_id,item.owner_id,item.code);
  if item.revision<>3 or item.note<>'Private note' or item.review_status<>'reviewed' or not item.active then raise exception 'Restore lost review'; end if;
  select * into item from public.research_list_add(item.list_id,item.owner_id,item.code);
  if item.revision<>3 then raise exception 'Idempotent add changed revision'; end if;
  if (select revision from public.research_lists where id=item.list_id)<>4 then raise exception 'Restore or idempotent add changed parent incorrectly'; end if;
  select * into item from public.research_list_review(item.list_id,item.owner_id,item.code,3,null,'in_review',null);
  if item.revision<>4 or item.note<>'Private note' or item.review_status<>'in_review' or not item.active then raise exception 'Partial edit lost fields'; end if;
  if (select revision from public.research_lists where id=item.list_id)<>5 then raise exception 'Partial edit did not invalidate parent'; end if;
  update public.research_lists set active=false where id=item.list_id;
  if exists(select 1 from public.research_list_review(item.list_id,item.owner_id,item.code,item.revision,'Archived edit','reviewed',true)) then raise exception 'Archived list edit accepted'; end if;
  if exists(select 1 from public.research_list_add(item.list_id,item.owner_id,item.code)) then raise exception 'Archived list add accepted'; end if;
end;
$$;
reset role;
update auth.sessions set not_after=now()-interval '1 minute' where id='00000000-0000-4000-8000-000000000004';
set local role service_role;
do $$ begin
 if public.research_session_active('00000000-0000-4000-8000-000000000001','00000000-0000-4000-8000-000000000004') then raise exception 'Expired session accepted'; end if;
end; $$;
reset role;
do $$
begin
 if has_table_privilege('anon','public.research_lists','SELECT') or has_table_privilege('authenticated','public.research_list_items','UPDATE') then raise exception 'Browser grants expose private data'; end if;
 if has_function_privilege('anon','public.research_list_add(uuid,uuid,text)','EXECUTE') or has_function_privilege('authenticated','public.research_session_active(uuid,uuid)','EXECUTE') then raise exception 'RPC public exposure'; end if;
 if has_schema_privilege('authenticated','research_private','USAGE') then raise exception 'Internal schema exposed'; end if;
 if not (select relrowsecurity from pg_class where oid='public.research_lists'::regclass) or not (select relrowsecurity from pg_class where oid='public.research_list_items'::regclass) then raise exception 'RLS absent'; end if;
end;
$$;
rollback;
select 'research database contracts passed' as result;
