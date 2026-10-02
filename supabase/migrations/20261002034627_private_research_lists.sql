-- Private research is reachable only through the API's verified-session/owner path.
-- No account, existing saved-screen, watchlist or snapshot data is rewritten.
create table public.research_lists (
  id uuid primary key default gen_random_uuid(),
  owner_id uuid not null references auth.users(id),
  name text not null check (char_length(btrim(name)) between 1 and 80),
  description text not null default '' check (char_length(description) <= 500),
  active boolean not null default true,
  revision bigint not null default 1 check (revision >= 1),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (id, owner_id)
);
create unique index research_lists_owner_name on public.research_lists(owner_id, lower(btrim(name))) where active;
create index research_lists_owner_updated on public.research_lists(owner_id, updated_at desc, id);

create table public.research_list_items (
  list_id uuid not null,
  owner_id uuid not null,
  code text not null check (code ~ '^(US|HK|AU|SH|SZ|SG)\.[A-Z0-9][A-Z0-9._-]{0,30}$'),
  note text not null default '' check (char_length(note) <= 4000),
  review_status text not null default 'unreviewed' check (review_status in ('unreviewed','in_review','reviewed')),
  active boolean not null default true,
  revision bigint not null default 1 check (revision >= 1),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (list_id, code),
  foreign key (list_id, owner_id) references public.research_lists(id, owner_id)
);
create index research_list_items_owner on public.research_list_items(owner_id, list_id, code);
alter table public.research_lists enable row level security;
alter table public.research_list_items enable row level security;
-- Intentionally no browser grants/policies. Service-only API performs owner checks.
revoke all on public.research_lists, public.research_list_items from public, anon, authenticated;
grant select, insert, update on public.research_lists, public.research_list_items to service_role;

create function public.research_list_add(p_list uuid, p_owner uuid, p_code text)
returns setof public.research_list_items language plpgsql security invoker set search_path = '' as $$
begin
  -- Lock the parent so archive/add are serialized; check ownership in the same transaction.
  perform 1 from public.research_lists where id=p_list and owner_id=p_owner and active for update;
  if not found then return; end if;
  return query insert into public.research_list_items as existing (list_id,owner_id,code)
    values (p_list,p_owner,p_code)
    on conflict (list_id,code) do update set
      active=true,
      revision=existing.revision + case when existing.active then 0 else 1 end,
      updated_at=case when existing.active then existing.updated_at else now() end
    returning *;
end;
$$;
revoke all on function public.research_list_add(uuid,uuid,text) from public, anon, authenticated;
grant execute on function public.research_list_add(uuid,uuid,text) to service_role;

-- Revision compare-and-set plus parent lock prevents note edits racing archive.
create function public.research_list_review(p_list uuid, p_owner uuid, p_code text,
  p_revision bigint, p_note text, p_status text, p_active boolean)
returns setof public.research_list_items language plpgsql security invoker set search_path = '' as $$
begin
  perform 1 from public.research_lists where id=p_list and owner_id=p_owner and active for update;
  if not found then return; end if;
  return query update public.research_list_items set note=coalesce(p_note,note), review_status=coalesce(p_status,review_status),
    active=coalesce(p_active,active), revision=revision+1, updated_at=now()
    where list_id=p_list and owner_id=p_owner and code=p_code and revision=p_revision
    returning *;
end;
$$;
revoke all on function public.research_list_review(uuid,uuid,text,bigint,text,text,boolean) from public, anon, authenticated;
grant execute on function public.research_list_review(uuid,uuid,text,bigint,text,text,boolean) to service_role;

-- Strict revocation check in addition to Auth's token/user validation. Only the
-- backend service can ask this boolean question; no session rows leave Postgres.
create schema if not exists research_private;
revoke all on schema research_private from public, anon, authenticated;
grant usage on schema research_private to service_role;
-- A narrowly scoped internal lookup needs auth-schema access. It returns only
-- one boolean and is not in an exposed schema. It never grants table access.
create function research_private.session_active(p_owner uuid, p_session uuid)
returns boolean language plpgsql stable security definer set search_path = '' as $$
begin
  if (select auth.uid()) is distinct from p_owner
     and current_setting('role', true) is distinct from 'service_role' then
    return false;
  end if;
  return exists(select 1 from auth.sessions where id=p_session and user_id=p_owner
    and (not_after is null or not_after > now()));
end;
$$;
revoke all on function research_private.session_active(uuid,uuid) from public, anon, authenticated;
grant execute on function research_private.session_active(uuid,uuid) to service_role;
create function public.research_session_active(p_owner uuid, p_session uuid)
returns boolean language sql stable security invoker set search_path = '' as $$
  select research_private.session_active(p_owner,p_session);
$$;
revoke all on function public.research_session_active(uuid,uuid) from public, anon, authenticated;
grant execute on function public.research_session_active(uuid,uuid) to service_role;
