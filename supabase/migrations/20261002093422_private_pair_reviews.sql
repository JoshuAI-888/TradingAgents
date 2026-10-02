-- Notes are private to an analyst and one immutable comparison pair.
create table public.research_pair_reviews (
  owner_id uuid not null references auth.users(id) on delete cascade,
  history_key text not null,
  previous_id text not null,
  current_id text not null,
  code text not null check (code ~ '^(US|HK|AU|SH|SZ|SG)\.[A-Z0-9][A-Z0-9._-]{0,30}$'),
  note text not null default '' check (length(note)<=4000),
  review_status text not null default 'unreviewed' check (review_status in ('unreviewed','in_review','reviewed')),
  revision integer not null default 1 check (revision>=1),
  updated_at timestamptz not null default now(),
  primary key (owner_id,history_key,previous_id,current_id,code),
  foreign key (history_key,previous_id) references public.screen_captures(history_key,id),
  foreign key (history_key,current_id) references public.screen_captures(history_key,id),
  check (previous_id<>current_id)
);
alter table public.research_pair_reviews enable row level security;
revoke all on public.research_pair_reviews from public,anon,authenticated,service_role;
grant select on public.research_pair_reviews to authenticated;
create policy pair_reviews_owner_read on public.research_pair_reviews for select to authenticated
using ((select auth.uid())=owner_id);
grant select,insert,update on public.research_pair_reviews to service_role;

-- Server-only CAS: revision 0 means no stored review; stale creates/edits return no row.
create function public.research_pair_review_save(p_owner uuid,p_key text,p_previous text,p_current text,p_code text,p_revision integer,p_note text,p_status text)
returns setof public.research_pair_reviews language plpgsql security invoker set search_path='' as $$
begin
  if p_revision is null or p_revision<0 or p_note is null or length(p_note)>4000
     or p_status is null or p_status not in ('unreviewed','in_review','reviewed') then
    raise exception using errcode='22023',message='Invalid pair review';
  end if;
  if not exists (
    select 1 from public.screen_captures a join public.screen_captures b on b.history_key=a.history_key
    where a.history_key=p_key and a.id=p_previous and b.id=p_current
      and a.complete and b.complete and a.at<b.at and a.version=b.version
      and (exists(select 1 from jsonb_array_elements(a.snapshot->'members') m where m->>'code'=p_code)
        or exists(select 1 from jsonb_array_elements(b.snapshot->'members') m where m->>'code'=p_code))
  ) then return; end if;
  if p_revision=0 then
    return query insert into public.research_pair_reviews(owner_id,history_key,previous_id,current_id,code,note,review_status)
      values(p_owner,p_key,p_previous,p_current,p_code,p_note,p_status)
      on conflict do nothing returning *;
  else
    return query update public.research_pair_reviews set note=p_note,review_status=p_status,
      revision=revision+1,updated_at=now()
      where owner_id=p_owner and history_key=p_key and previous_id=p_previous and current_id=p_current
        and code=p_code and revision=p_revision returning *;
  end if;
end;$$;
revoke all on function public.research_pair_review_save(uuid,text,text,text,text,integer,text,text) from public,anon,authenticated;
grant execute on function public.research_pair_review_save(uuid,text,text,text,text,integer,text,text) to service_role;

-- One statement snapshot prevents mixed review revisions across PostgREST pages.
create function public.research_pair_review_read(p_owner uuid,p_key text,p_previous text,p_current text)
returns jsonb language sql stable security invoker set search_path='' as $$
 select jsonb_build_object('reviews',coalesce(jsonb_agg(to_jsonb(r) order by r.code),'[]'::jsonb))
 from (select * from public.research_pair_reviews where owner_id=p_owner and history_key=p_key
   and previous_id=p_previous and current_id=p_current order by code limit 40001) r;
$$;
revoke all on function public.research_pair_review_read(uuid,text,text,text) from public,anon,authenticated;
grant execute on function public.research_pair_review_read(uuid,text,text,text) to service_role;
