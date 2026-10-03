-- Fixed-duration acquisition leases: whole CLI run <=300s, lease <=330s.
-- Tokens are never reused, including after expiry/release or on another market.
create table public.instrument_subtype_runs (
 id uuid primary key,
 market text not null check(market in ('US','HK')),
 started_at timestamptz not null,
 expires_at timestamptz not null check(expires_at=started_at+interval '330 seconds'),
 unique(market,id)
);
create table public.instrument_subtype_leases (
 market text primary key check(market in ('US','HK')),
 run_id uuid,
 active boolean not null default false,
 foreign key(market,run_id) references public.instrument_subtype_runs(market,id),
 check(not active or run_id is not null)
);
insert into public.instrument_subtype_leases(market) values('US'),('HK');
alter table public.instrument_subtype_runs enable row level security;
alter table public.instrument_subtype_leases enable row level security;
revoke all on public.instrument_subtype_runs,public.instrument_subtype_leases from public,anon,authenticated,service_role;
grant select,insert on public.instrument_subtype_runs to service_role;
grant select,update on public.instrument_subtype_leases to service_role;

create function public.instrument_subtype_claim(p_market text,p_run uuid)
returns jsonb language plpgsql security invoker set search_path='' as $$
declare slot public.instrument_subtype_leases; attempt public.instrument_subtype_runs; instant timestamptz;
begin
 if p_market is null or p_market not in ('US','HK') or p_run is null then
  raise exception using errcode='22023',message='Invalid subtype lease scope';
 end if;
 select * into slot from public.instrument_subtype_leases where market=p_market for update;
 if not found then raise exception using errcode='55000',message='Subtype lease slot unavailable';end if;
 instant:=clock_timestamp();
 if slot.active then
  select * into attempt from public.instrument_subtype_runs where id=slot.run_id;
  if attempt.expires_at>instant then
   if slot.run_id=p_run then return to_jsonb(attempt);end if;
   return null;
  end if;
 end if;
 insert into public.instrument_subtype_runs(id,market,started_at,expires_at)
  values(p_run,p_market,instant,instant+interval '330 seconds') on conflict do nothing returning * into attempt;
 if not found then return null;end if;
 update public.instrument_subtype_leases set run_id=p_run,active=true where market=p_market;
 return to_jsonb(attempt);
end;$$;

create function public.instrument_subtype_release(p_market text,p_run uuid)
returns boolean language plpgsql security invoker set search_path='' as $$
declare slot public.instrument_subtype_leases;
begin
 if p_market is null or p_market not in ('US','HK') or p_run is null then
  raise exception using errcode='22023',message='Invalid subtype lease scope';
 end if;
 select * into slot from public.instrument_subtype_leases where market=p_market for update;
 if slot.run_id is distinct from p_run then return false;end if;
 if not slot.active then return true;end if;
 if not exists(select 1 from public.instrument_subtype_runs where id=p_run and expires_at>clock_timestamp()) then return false;end if;
 update public.instrument_subtype_leases set active=false where market=p_market;
 return true;
end;$$;

create function public.instrument_subtype_save_leased(p_market text,p_run uuid,p_code text,p_revision integer,p_record jsonb)
returns setof public.instrument_subtype_cache language plpgsql security invoker set search_path='' as $$
declare slot public.instrument_subtype_leases; existing public.instrument_subtype_cache;
begin
 if p_market is null or p_market not in ('US','HK') or p_run is null or p_revision is null or p_revision<0 then
  raise exception using errcode='22023',message='Invalid subtype publication lease';
 end if;
 -- Holding the market lock through publication orders save vs replacement/release.
 select * into slot from public.instrument_subtype_leases where market=p_market for update;
 if not slot.active or slot.run_id is distinct from p_run
  or not exists(select 1 from public.instrument_subtype_runs where id=p_run and expires_at>clock_timestamp()) then
  raise exception using errcode='55000',message='Subtype lease expired or superseded';
 end if;
 if p_revision=0 then
  insert into public.instrument_subtype_cache(market,code,revision,record)
   values(p_market,p_code,1,p_record) on conflict do nothing;
 else
  update public.instrument_subtype_cache set revision=revision+1,record=p_record
   where market=p_market and code=p_code and revision=p_revision;
 end if;
 select * into existing from public.instrument_subtype_cache where market=p_market and code=p_code;
 if existing.revision=p_revision+1 and existing.record=p_record then return next existing;end if;
 return;
end;$$;
-- Old publication entry is retained for historical migration evidence, but is
-- no longer executable by a worker: current publication must hold a lease.
revoke all on function public.instrument_subtype_cache_save(text,text,integer,jsonb) from service_role;
revoke all on function public.instrument_subtype_claim(text,uuid),public.instrument_subtype_release(text,uuid),
 public.instrument_subtype_save_leased(text,uuid,text,integer,jsonb) from public,anon,authenticated;
grant execute on function public.instrument_subtype_claim(text,uuid),public.instrument_subtype_release(text,uuid),
 public.instrument_subtype_save_leased(text,uuid,text,integer,jsonb) to service_role;
