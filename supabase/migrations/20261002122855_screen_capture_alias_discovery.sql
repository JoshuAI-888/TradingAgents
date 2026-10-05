-- Metadata discovery only. Preserve a representative ORIGINAL history key so
-- callers can retain same-key pair review scope. Cross-key reviews need their
-- own qualified contract; discovery does not authorize remapping old notes.
create function public.screen_capture_alias_history(p_namespace text,p_digest text,p_screen jsonb,p_raw_key text,p_limit integer,p_offset integer)
returns table(history_key text,id text,at timestamptz,source_at text,source_clock text,complete boolean,members integer,version integer,copies bigint)
language plpgsql stable security invoker set search_path='' as $$
begin
 if p_namespace is null or p_namespace !~ '^[a-f0-9]{16,64}$' or p_digest is null or p_digest !~ '^[a-f0-9]{64}$'
  or jsonb_typeof(p_screen) is distinct from 'object' or octet_length(p_screen::text)>32768
  or p_raw_key is null or p_raw_key !~ '^screen_history:[a-f0-9]{16,64}:[a-f0-9]{64}$' or split_part(p_raw_key,':',2)<>p_namespace
  or p_limit is null or p_limit not between 1 and 100 or p_offset is null or p_offset not between 0 and 40000 then
  raise exception using errcode='22023',message='Invalid capture history discovery scope';
 end if;
 return query with keys as (
  select p_raw_key as history_key union
  select a.history_key from public.screen_capture_definition_aliases a where a.owner_namespace=p_namespace
   and a.identity_version=1 and a.semantic_digest=p_digest and a.canonical_screen=p_screen
 ), candidates as (
  select c.history_key,c.id,c.at,c.source_at,c.source_clock,c.complete,c.members,c.version,
   row_number() over(partition by c.id order by (c.history_key=p_raw_key) desc,c.history_key) as choice,
   count(*) over(partition by c.id) as copies
  from keys k join public.screen_captures c on c.history_key=k.history_key
 ) select c.history_key,c.id,c.at,c.source_at,c.source_clock,c.complete,c.members,c.version,c.copies
  from candidates c where c.choice=1 order by c.at desc,c.id desc limit p_limit+1 offset p_offset;
end;
$$;
revoke all on function public.screen_capture_alias_history(text,text,jsonb,text,integer,integer) from public,anon,authenticated;
grant execute on function public.screen_capture_alias_history(text,text,jsonb,text,integer,integer) to service_role;

-- Resolve one ID and compare all duplicate payloads in the same SQL statement.
-- Only one payload crosses REST. Exact divergent evidence is never discarded.
create function public.screen_capture_alias_get(p_namespace text,p_digest text,p_screen jsonb,p_raw_key text,p_id text)
returns table(history_key text,id text,snapshot jsonb,conflicting boolean,copies bigint)
language plpgsql stable security invoker set search_path='' as $$
begin
 if p_namespace is null or p_namespace !~ '^[a-f0-9]{16,64}$' or p_digest is null or p_digest !~ '^[a-f0-9]{64}$'
  or jsonb_typeof(p_screen) is distinct from 'object' or octet_length(p_screen::text)>32768
  or p_raw_key is null or p_raw_key !~ '^screen_history:[a-f0-9]{16,64}:[a-f0-9]{64}$' or split_part(p_raw_key,':',2)<>p_namespace
  or p_id is null or p_id !~ '^[A-Za-z0-9_-]{1,100}$' then
  raise exception using errcode='22023',message='Invalid capture discovery identity';
 end if;
 return query with keys as (
  select p_raw_key as history_key union
  select a.history_key from public.screen_capture_definition_aliases a where a.owner_namespace=p_namespace
   and a.identity_version=1 and a.semantic_digest=p_digest and a.canonical_screen=p_screen
 ), candidates as materialized (
  select c.history_key,c.id,c.snapshot from keys k join public.screen_captures c on c.history_key=k.history_key where c.id=p_id
 ), chosen as (
  select c.* from candidates c order by (c.history_key=p_raw_key) desc,c.history_key limit 1
 ) select c.history_key,c.id,c.snapshot,
  exists(select 1 from candidates other where other.snapshot is distinct from c.snapshot),
  (select count(*) from candidates) from chosen c;
end;
$$;
revoke all on function public.screen_capture_alias_get(text,text,jsonb,text,text) from public,anon,authenticated;
grant execute on function public.screen_capture_alias_get(text,text,jsonb,text,text) to service_role;
