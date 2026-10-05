-- Additive discovery metadata for deployment-shared manual captures only.
-- This is not authenticated-owner schedule history or an ownership migration.
create function public.screen_definition_semantic(p_definition jsonb) returns jsonb
language plpgsql immutable security invoker set search_path='' as $$
declare criterion jsonb; normalized jsonb:='[]'::jsonb;
begin
 if jsonb_typeof(p_definition) is distinct from 'object' or jsonb_typeof(p_definition->'filters') is distinct from 'array' then
  raise exception using errcode='22023',message='Invalid screen definition';
 end if;
 for criterion in select value from jsonb_array_elements(p_definition->'filters') loop
  if jsonb_typeof(criterion) is distinct from 'object' then
   raise exception using errcode='22023',message='Invalid criterion definition';
  end if;
  criterion:=criterion-'_label';
  if coalesce(criterion->'min','null'::jsonb)='null'::jsonb then criterion:=criterion-'min';end if;
  if coalesce(criterion->'max','null'::jsonb)='null'::jsonb then criterion:=criterion-'max';end if;
  normalized:=normalized||jsonb_build_array(criterion);
 end loop;
 return jsonb_set(p_definition,'{filters}',normalized);
end;
$$;
revoke all on function public.screen_definition_semantic(jsonb) from public,anon,authenticated;
grant execute on function public.screen_definition_semantic(jsonb) to service_role;

create table public.screen_capture_definition_aliases (
 history_key text primary key,
 owner_namespace text not null check(owner_namespace ~ '^[a-f0-9]{16,64}$'),
 identity_version integer not null check(identity_version=1),
 semantic_digest text not null check(semantic_digest ~ '^[a-f0-9]{64}$'),
 canonical_screen jsonb not null check(jsonb_typeof(canonical_screen)='object' and octet_length(canonical_screen::text)<=32768),
 anchor_capture_id text not null,
 created_at timestamptz not null default clock_timestamp(),
 foreign key(history_key,anchor_capture_id) references public.screen_captures(history_key,id),
 check(history_key ~ '^screen_history:[a-f0-9]{16,64}:[a-f0-9]{64}$' and split_part(history_key,':',2)=owner_namespace)
);
create index screen_capture_definition_alias_lookup on public.screen_capture_definition_aliases(owner_namespace,identity_version,semantic_digest,history_key);
alter table public.screen_capture_definition_aliases enable row level security;
revoke all on public.screen_capture_definition_aliases from public,anon,authenticated,service_role;
grant select,insert on public.screen_capture_definition_aliases to service_role;
create trigger screen_capture_definition_alias_immutable before update or delete on public.screen_capture_definition_aliases
 for each row execute function public.screen_capture_immutable();
create trigger screen_capture_definition_alias_no_truncate before truncate on public.screen_capture_definition_aliases
 for each statement execute function public.screen_capture_immutable();

-- The trusted server computes the versioned Python digest; SQL independently
-- proves normalization against the immutable anchor. No client write grant.
create function public.screen_capture_definition_alias_register(p_key text,p_capture_id text,p_digest text,p_screen jsonb) returns boolean
language plpgsql security invoker set search_path='' as $$
declare original jsonb; inserted integer;
begin
 if p_key is null or p_key !~ '^screen_history:[a-f0-9]{16,64}:[a-f0-9]{64}$'
  or p_digest is null or p_digest !~ '^[a-f0-9]{64}$' or p_capture_id is null
  or jsonb_typeof(p_screen) is distinct from 'object' or octet_length(p_screen::text)>32768 then
  raise exception using errcode='22023',message='Invalid capture alias';
 end if;
 select c.snapshot->'definition' into original from public.screen_captures c where c.history_key=p_key and c.id=p_capture_id;
 if original is null or public.screen_definition_semantic(original) is distinct from p_screen then
  raise exception using errcode='22023',message='Alias does not match an immutable capture definition';
 end if;
 insert into public.screen_capture_definition_aliases(history_key,owner_namespace,identity_version,semantic_digest,canonical_screen,anchor_capture_id)
 values(p_key,split_part(p_key,':',2),1,p_digest,p_screen,p_capture_id) on conflict(history_key) do nothing;
 get diagnostics inserted=row_count;
 if inserted=0 and not exists(select 1 from public.screen_capture_definition_aliases a where a.history_key=p_key
  and a.semantic_digest=p_digest and a.canonical_screen=p_screen and a.identity_version=1) then
  raise exception using errcode='23505',message='Capture alias conflicts with existing immutable mapping';
 end if;
 return inserted=1;
end;
$$;
revoke all on function public.screen_capture_definition_alias_register(text,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.screen_capture_definition_alias_register(text,text,text,jsonb) to service_role;

-- New captures and their discovery mapping commit together. Existing append RPC
-- remains available for rollback; original keys/records are never rewritten.
create function public.screen_capture_append_with_alias(p_key text,p_records jsonb,p_capture_id text,p_digest text,p_screen jsonb) returns integer
language plpgsql security invoker set search_path='' as $$
declare inserted integer;
begin
 inserted:=public.screen_capture_append(p_key,p_records);
 perform public.screen_capture_definition_alias_register(p_key,p_capture_id,p_digest,p_screen);
 return inserted;
end;
$$;
revoke all on function public.screen_capture_append_with_alias(text,jsonb,text,text,jsonb) from public,anon,authenticated;
grant execute on function public.screen_capture_append_with_alias(text,jsonb,text,text,jsonb) to service_role;
