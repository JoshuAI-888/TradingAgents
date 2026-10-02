-- Additive cross-history contract. Existing same-key notes/RPCs are unchanged.
create table public.research_cross_history_pair_reviews (
 owner_id uuid not null references auth.users(id) on delete cascade,
 previous_history_key text not null,
 current_history_key text not null,
 previous_id text not null,
 current_id text not null,
 code text not null check(code ~ '^(US|HK|AU|SH|SZ|SG)\.[A-Z0-9][A-Z0-9._-]{0,30}$'),
 note text not null default '' check(length(note)<=4000),
 review_status text not null default 'unreviewed' check(review_status in ('unreviewed','in_review','reviewed')),
 revision integer not null default 1 check(revision>=1),
 updated_at timestamptz not null default clock_timestamp(),
 primary key(owner_id,previous_history_key,current_history_key,previous_id,current_id,code),
 foreign key(previous_history_key,previous_id) references public.screen_captures(history_key,id),
 foreign key(current_history_key,current_id) references public.screen_captures(history_key,id),
 check(previous_history_key<>current_history_key and previous_id<>current_id),
 check(previous_history_key ~ '^screen_history:[a-f0-9]{16,64}:[a-f0-9]{64}$'
   and current_history_key ~ '^screen_history:[a-f0-9]{16,64}:[a-f0-9]{64}$'
   and split_part(previous_history_key,':',2)=split_part(current_history_key,':',2))
);
alter table public.research_cross_history_pair_reviews enable row level security;
revoke all on public.research_cross_history_pair_reviews from public,anon,authenticated,service_role;
grant select on public.research_cross_history_pair_reviews to authenticated;
create policy cross_history_pair_owner_read on public.research_cross_history_pair_reviews for select to authenticated
 using((select auth.uid())=owner_id);
grant select,insert,update on public.research_cross_history_pair_reviews to service_role;

create function public.research_cross_history_pair_review_save(p_owner uuid,p_previous_key text,p_current_key text,p_previous text,p_current text,p_code text,p_revision integer,p_note text,p_status text)
returns setof public.research_cross_history_pair_reviews language plpgsql security invoker set search_path='' as $$
begin
 if p_revision is null or p_revision<0 or p_note is null or length(p_note)>4000
   or p_status is null or p_status not in ('unreviewed','in_review','reviewed') then
  raise exception using errcode='22023',message='Invalid cross-history pair review';
 end if;
 -- Prove the mapped canonical scope against both exact immutable captures,
 -- not merely the original mapping anchors. Server also validates replay and attribution.
 if not exists(
  select 1 from public.screen_captures a
   join public.screen_captures b on b.history_key=p_current_key and b.id=p_current
   join public.screen_capture_definition_aliases aa on aa.history_key=a.history_key
   join public.screen_capture_definition_aliases ba on ba.history_key=b.history_key
  where a.history_key=p_previous_key and a.id=p_previous and a.history_key<>b.history_key and a.id<>b.id
   and aa.owner_namespace=ba.owner_namespace and aa.identity_version=ba.identity_version
   and aa.semantic_digest=ba.semantic_digest and aa.canonical_screen=ba.canonical_screen
   and public.screen_definition_semantic(a.snapshot->'definition')=aa.canonical_screen
   and public.screen_definition_semantic(b.snapshot->'definition')=ba.canonical_screen
   and a.complete and b.complete and a.at<b.at and a.version=b.version
   and (exists(select 1 from jsonb_array_elements(a.snapshot->'members') m where m->>'code'=p_code)
     or exists(select 1 from jsonb_array_elements(b.snapshot->'members') m where m->>'code'=p_code))
 ) then return;end if;
 if p_revision=0 then
  return query insert into public.research_cross_history_pair_reviews(owner_id,previous_history_key,current_history_key,previous_id,current_id,code,note,review_status)
   values(p_owner,p_previous_key,p_current_key,p_previous,p_current,p_code,p_note,p_status)
   on conflict do nothing returning *;
 else
  return query update public.research_cross_history_pair_reviews set note=p_note,review_status=p_status,revision=revision+1,updated_at=clock_timestamp()
   where owner_id=p_owner and previous_history_key=p_previous_key and current_history_key=p_current_key
     and previous_id=p_previous and current_id=p_current and code=p_code and revision=p_revision returning *;
 end if;
end;$$;
create function public.research_cross_history_pair_review_read(p_owner uuid,p_previous_key text,p_current_key text,p_previous text,p_current text)
returns jsonb language sql stable security invoker set search_path='' as $$
 select jsonb_build_object('reviews',coalesce(jsonb_agg(to_jsonb(r) order by r.code),'[]'::jsonb))
 from(select * from public.research_cross_history_pair_reviews where owner_id=p_owner and previous_history_key=p_previous_key
   and current_history_key=p_current_key and previous_id=p_previous and current_id=p_current order by code limit 40001) r;
$$;
revoke all on function public.research_cross_history_pair_review_save(uuid,text,text,text,text,text,integer,text,text) from public,anon,authenticated;
revoke all on function public.research_cross_history_pair_review_read(uuid,text,text,text,text) from public,anon,authenticated;
grant execute on function public.research_cross_history_pair_review_save(uuid,text,text,text,text,text,integer,text,text) to service_role;
grant execute on function public.research_cross_history_pair_review_read(uuid,text,text,text,text) to service_role;
