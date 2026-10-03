alter table public.research_private_captures add constraint research_private_captures_owner_schedule unique(id,schedule_id,owner_id);
create table public.research_scheduled_pair_reviews (
 owner_id uuid not null references auth.users(id) on delete cascade,
 schedule_id uuid not null,
 previous_id uuid not null,
 current_id uuid not null,
 code text not null check(code ~ '^(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}$'),
 note text not null default '' check(length(note)<=4000),
 review_status text not null default 'unreviewed' check(review_status in ('unreviewed','in_review','reviewed')),
 revision integer not null default 1 check(revision>=1),
 updated_at timestamptz not null default clock_timestamp(),
 primary key(owner_id,schedule_id,previous_id,current_id,code),
 foreign key(previous_id,schedule_id,owner_id) references public.research_private_captures(id,schedule_id,owner_id),
 foreign key(current_id,schedule_id,owner_id) references public.research_private_captures(id,schedule_id,owner_id),
 check(previous_id<>current_id)
);
alter table public.research_scheduled_pair_reviews enable row level security;
revoke all on public.research_scheduled_pair_reviews from public,anon,authenticated,service_role;
grant select on public.research_scheduled_pair_reviews to authenticated;
grant select,insert,update on public.research_scheduled_pair_reviews to service_role;
create policy scheduled_pair_reviews_owner_read on public.research_scheduled_pair_reviews for select to authenticated using((select auth.uid())=owner_id);

create function public.research_scheduled_pair_review_save(p_owner uuid,p_schedule uuid,p_previous uuid,p_current uuid,p_code text,p_revision integer,p_note text,p_status text)
returns setof public.research_scheduled_pair_reviews language plpgsql security invoker set search_path='' as $$
begin
 if p_owner is null or p_schedule is null or p_previous is null or p_current is null or p_revision is null or p_revision<0
  or p_code is null or p_code !~ '^(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}$' or p_note is null or length(p_note)>4000 or p_status is null or p_status not in ('unreviewed','in_review','reviewed') then
  raise exception using errcode='22023',message='Invalid scheduled pair review';
 end if;
 if not exists(select 1 from public.research_private_captures a join public.research_private_captures b on b.schedule_id=a.schedule_id and b.owner_id=a.owner_id
  where a.owner_id=p_owner and a.schedule_id=p_schedule and a.id=p_previous and b.id=p_current
   and a.definition_hash=b.definition_hash and a.snapshot->'definition'=b.snapshot->'definition'
   and a.snapshot->'complete'='true'::jsonb and b.snapshot->'complete'='true'::jsonb and a.snapshot->'version'=b.snapshot->'version'
   and (a.snapshot->>'at')::timestamptz<(b.snapshot->>'at')::timestamptz
   and (exists(select 1 from jsonb_array_elements(a.snapshot->'members') m where m->>'code'=p_code)
    or exists(select 1 from jsonb_array_elements(b.snapshot->'members') m where m->>'code'=p_code))) then return;end if;
 if p_revision=0 then
  return query insert into public.research_scheduled_pair_reviews(owner_id,schedule_id,previous_id,current_id,code,note,review_status)
   values(p_owner,p_schedule,p_previous,p_current,p_code,p_note,p_status) on conflict do nothing returning *;
 else
  return query update public.research_scheduled_pair_reviews set note=p_note,review_status=p_status,revision=revision+1,updated_at=clock_timestamp()
   where owner_id=p_owner and schedule_id=p_schedule and previous_id=p_previous and current_id=p_current and code=p_code and revision=p_revision returning *;
 end if;
end;
$$;

-- Read full lightweight state once; fetch only visible notes with the same hash.
-- Changed state returns confirmed=false, never mixed revisions or huge note blobs.
create function public.research_scheduled_pair_review_read(p_owner uuid,p_schedule uuid,p_previous uuid,p_current uuid,p_codes text[] default '{}',p_expected_hash text default null)
returns jsonb language sql stable security invoker set search_path='' as $$
 with records as materialized (
  select * from public.research_scheduled_pair_reviews where owner_id=p_owner and schedule_id=p_schedule and previous_id=p_previous and current_id=p_current order by code limit 40001
 ), state as (
  select coalesce(jsonb_agg(jsonb_build_object('code',code,'revision',revision,'review_status',review_status) order by code),'[]'::jsonb) value from records
 ), fingerprint as (
  select value,encode(sha256(convert_to(value::text,'UTF8')),'hex') hash from state
 )
 select jsonb_build_object('confirmed',p_expected_hash is null or p_expected_hash=hash,'revision_hash',hash,
  'reviews',case when p_expected_hash is null then value else '[]'::jsonb end,
  'notes',case when (p_expected_hash is null or p_expected_hash=hash) and cardinality(p_codes)<=500 then
   (select coalesce(jsonb_agg(jsonb_build_object('code',code,'revision',revision,'review_status',review_status,'note',note) order by code),'[]'::jsonb) from records where code=any(p_codes)) else '[]'::jsonb end) from fingerprint;
$$;
revoke all on function public.research_scheduled_pair_review_save(uuid,uuid,uuid,uuid,text,integer,text,text) from public,anon,authenticated;
revoke all on function public.research_scheduled_pair_review_read(uuid,uuid,uuid,uuid,text[],text) from public,anon,authenticated;
grant execute on function public.research_scheduled_pair_review_save(uuid,uuid,uuid,uuid,text,integer,text,text) to service_role;
grant execute on function public.research_scheduled_pair_review_read(uuid,uuid,uuid,uuid,text[],text) to service_role;
