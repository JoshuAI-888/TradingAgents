-- Server-only, keyset-paged metadata. Never load complete observation payloads
-- merely to discover an original capture definition.
create index screen_capture_namespace_backfill on public.screen_captures((split_part(history_key,':',2)),history_key,id);
create function public.screen_capture_alias_backfill_page(p_namespace text,p_after_key text,p_after_id text,p_limit integer)
returns table(history_key text,capture_id text,definition jsonb,identity_present boolean,definition_identity jsonb)
language plpgsql stable security invoker set search_path='' as $$
begin
 if p_namespace is null or p_namespace !~ '^[a-f0-9]{16,64}$' or p_limit is null or p_limit not between 1 and 100
  or (p_after_key is null)<>(p_after_id is null)
  or (p_after_key is not null and (p_after_key !~ '^screen_history:[a-f0-9]{16,64}:[a-f0-9]{64}$'
   or split_part(p_after_key,':',2)<>p_namespace or length(p_after_id) not between 1 and 100)) then
  raise exception using errcode='22023',message='Invalid capture backfill scope or cursor';
 end if;
 return query select c.history_key,c.id,c.snapshot->'definition',c.snapshot?'definition_identity',c.snapshot->'definition_identity'
  from public.screen_captures c where split_part(c.history_key,':',2)=p_namespace
  and (p_after_key is null or (c.history_key,c.id)>(p_after_key,p_after_id))
  order by c.history_key,c.id limit p_limit+1;
end;
$$;
revoke all on function public.screen_capture_alias_backfill_page(text,text,text,integer) from public,anon,authenticated;
grant execute on function public.screen_capture_alias_backfill_page(text,text,text,integer) to service_role;
