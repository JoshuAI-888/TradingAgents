-- Service-only search over the verified owner's list, before pagination.
-- Literal substring matching does not interpret wildcards or query operators.
create function public.research_list_search(p_list uuid, p_owner uuid, p_query text,
  p_status text, p_removed boolean, p_after text, p_offset integer, p_limit integer)
returns setof public.research_list_items
language plpgsql stable security invoker set search_path = '' as $$
begin
  if p_query is null or char_length(p_query)>80 or p_query ~ '[[:cntrl:]]'
     or p_status is null or p_status not in ('all','unreviewed','in_review','reviewed')
     or p_removed is null or p_offset is null or p_offset not between 0 and 40000
     or p_limit is null or p_limit not between 1 and 501
     or p_after is null or (p_after<>'' and p_after !~ '^(US|HK|AU|SH|SZ|SG)\.[A-Z0-9][A-Z0-9._-]{0,30}$') then
    raise exception using errcode='22023', message='Invalid shortlist search';
  end if;
  return query
    select i.* from public.research_list_items i
    join public.research_lists l on l.id=i.list_id and l.owner_id=i.owner_id
    where i.list_id=p_list and i.owner_id=p_owner
      and (p_removed or i.active)
      and (p_status='all' or i.review_status=p_status)
      and (p_after='' or i.code>p_after)
      and (strpos(lower(i.code),lower(btrim(p_query)))>0 or exists (
        select 1 from public.screener_quotes q where q.code=i.code
          and jsonb_typeof(q.row)='object' and q.row->>'code'=i.code
          and jsonb_typeof(q.row->'name')='string'
          and strpos(lower(q.row->>'name'),lower(btrim(p_query)))>0
      ))
    order by i.code asc limit p_limit offset p_offset;
end;
$$;
revoke all on function public.research_list_search(uuid,uuid,text,text,boolean,text,integer,integer)
  from public, anon, authenticated;
grant execute on function public.research_list_search(uuid,uuid,text,text,boolean,text,integer,integer)
  to service_role;
