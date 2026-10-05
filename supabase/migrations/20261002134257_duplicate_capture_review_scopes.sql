-- Discover original owner-private anchors; no note move, merge or revision change.
create index research_pair_review_capture_lookup on public.research_pair_reviews(owner_id,previous_id,current_id,code);
create index research_cross_review_capture_lookup on public.research_cross_history_pair_reviews(owner_id,previous_id,current_id,code);

create function public.research_duplicate_pair_review_scopes(p_owner uuid,p_previous_key text,p_current_key text,p_previous text,p_current text)
returns jsonb language plpgsql stable security invoker set search_path='' as $$
declare before_capture public.screen_captures; after_capture public.screen_captures; before_alias public.screen_capture_definition_aliases;
 after_alias public.screen_capture_definition_aliases; result jsonb;
begin
 if p_owner is null or p_previous is null or p_current is null or p_previous=p_current
  or p_previous !~ '^[A-Za-z0-9_-]{1,100}$' or p_current !~ '^[A-Za-z0-9_-]{1,100}$'
  or p_previous_key is null or p_current_key is null
  or p_previous_key !~ '^screen_history:[a-f0-9]{16,64}:[a-f0-9]{64}$'
  or p_current_key !~ '^screen_history:[a-f0-9]{16,64}:[a-f0-9]{64}$'
  or split_part(p_previous_key,':',2)<>split_part(p_current_key,':',2) then
  raise exception using errcode='22023',message='Invalid duplicate review scope';
 end if;
 select * into before_capture from public.screen_captures where history_key=p_previous_key and id=p_previous;
 select * into after_capture from public.screen_captures where history_key=p_current_key and id=p_current;
 select * into before_alias from public.screen_capture_definition_aliases where history_key=p_previous_key;
 select * into after_alias from public.screen_capture_definition_aliases where history_key=p_current_key;
 if before_capture.id is null or after_capture.id is null or not before_capture.complete or not after_capture.complete
  or before_capture.at>=after_capture.at or before_capture.version<>after_capture.version
  or before_alias.history_key is null or after_alias.history_key is null
  or before_alias.owner_namespace<>after_alias.owner_namespace or before_alias.identity_version<>1 or after_alias.identity_version<>1
  or before_alias.semantic_digest<>after_alias.semantic_digest or before_alias.canonical_screen<>after_alias.canonical_screen
  or public.screen_definition_semantic(before_capture.snapshot->'definition') is distinct from before_alias.canonical_screen
  or public.screen_definition_semantic(after_capture.snapshot->'definition') is distinct from after_alias.canonical_screen then
  return jsonb_build_object('alias_qualified',false,'reviews','[]'::jsonb);
 end if;
 with original_notes as (
  select r.owner_id,r.history_key as previous_history_key,r.history_key as current_history_key,
   r.previous_id,r.current_id,r.code,r.note,r.review_status,r.revision,r.updated_at,'same_history'::text as review_contract
  from public.research_pair_reviews r where r.owner_id=p_owner and r.previous_id=p_previous and r.current_id=p_current
  union all
  select r.owner_id,r.previous_history_key,r.current_history_key,r.previous_id,r.current_id,r.code,r.note,r.review_status,
   r.revision,r.updated_at,'cross_history'::text as review_contract
  from public.research_cross_history_pair_reviews r where r.owner_id=p_owner and r.previous_id=p_previous and r.current_id=p_current
 ), qualified as (
  select r.* from original_notes r
  join public.screen_captures b on b.history_key=r.previous_history_key and b.id=p_previous
  join public.screen_captures a on a.history_key=r.current_history_key and a.id=p_current
  join public.screen_capture_definition_aliases ba on ba.history_key=b.history_key
  join public.screen_capture_definition_aliases aa on aa.history_key=a.history_key
  where b.snapshot=before_capture.snapshot and a.snapshot=after_capture.snapshot
   and ba.owner_namespace=before_alias.owner_namespace and aa.owner_namespace=before_alias.owner_namespace
   and ba.identity_version=1 and aa.identity_version=1
   and ba.semantic_digest=before_alias.semantic_digest and aa.semantic_digest=before_alias.semantic_digest
   and ba.canonical_screen=before_alias.canonical_screen and aa.canonical_screen=before_alias.canonical_screen
   and (exists(select 1 from jsonb_array_elements(b.snapshot->'members') m where m->>'code'=r.code)
      or exists(select 1 from jsonb_array_elements(a.snapshot->'members') m where m->>'code'=r.code))
  order by r.code,r.previous_history_key,r.current_history_key limit 40001
 ) select jsonb_build_object('alias_qualified',true,'reviews',coalesce(jsonb_agg(to_jsonb(q) order by q.code,q.previous_history_key,q.current_history_key),'[]'::jsonb)) into result from qualified q;
 return result;
end;$$;
revoke all on function public.research_duplicate_pair_review_scopes(uuid,text,text,text,text) from public,anon,authenticated;
grant execute on function public.research_duplicate_pair_review_scopes(uuid,text,text,text,text) to service_role;
