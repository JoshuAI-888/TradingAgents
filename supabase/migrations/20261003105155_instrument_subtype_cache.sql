-- Isolated service-only mutable cache; published generation evidence stays immutable.
create table public.instrument_subtype_cache (
 market text not null check(market in ('US','HK')),
 code text not null check(code ~ '^(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}$' and split_part(code,'.',1)=market),
 revision integer not null check(revision>0),
 record jsonb not null,
 primary key(market,code)
);
alter table public.instrument_subtype_cache enable row level security;
revoke all on public.instrument_subtype_cache from public,anon,authenticated,service_role;
grant select,insert,update on public.instrument_subtype_cache to service_role;

create function public.instrument_subtype_cache_guard() returns trigger
language plpgsql security invoker set search_path='' as $$
declare r jsonb:=new.record; c jsonb; attempt_at timestamptz; receipt_at timestamptz; symbol text;
begin
 if jsonb_typeof(r) is distinct from 'object' or not r ?& array['version','code','context','retrieved_at','attempted_at','status']
  or r-array['version','code','context','retrieved_at','attempted_at','status'] <> '{}'::jsonb
  or r->>'version' is distinct from 'instrument_subtype_cache_v1' or r->>'code' is distinct from new.code
  or r->>'status' is null or r->>'status' not in ('success','unavailable','identity_mismatch','invalid_subtype')
  or jsonb_typeof(r->'attempted_at') is distinct from 'string'
  or r->>'attempted_at' !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$' then
  raise exception using errcode='22023',message='Invalid subtype evidence';
 end if;
 attempt_at:=(r->>'attempted_at')::timestamptz;
 if not isfinite(attempt_at) or attempt_at>clock_timestamp() then
  raise exception using errcode='22023',message='Invalid subtype attempt clock';
 end if;
 c:=r->'context';
 if c='null'::jsonb then
  if r->'retrieved_at'<>'null'::jsonb or r->>'status'='success' then
   raise exception using errcode='22023',message='Invalid absent subtype';
  end if;
 else
  if jsonb_typeof(r->'retrieved_at') is distinct from 'string'
   or r->>'retrieved_at' !~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$' then
   raise exception using errcode='22023',message='Invalid subtype receipt';
  end if;
  receipt_at:=(r->>'retrieved_at')::timestamptz;
  symbol:=substring(new.code from 4);
  if new.market='HK' then
   if symbol !~ '^\d+$' or symbol::integer not between 1 and 99999 then
    raise exception using errcode='22023',message='Invalid HK subtype identity';
   end if;
   symbol:=lpad(symbol::integer::text,greatest(4,length(symbol::integer::text)),'0')||'.HK';
  else symbol:=replace(symbol,'.','-');end if;
  if not isfinite(receipt_at) or receipt_at>attempt_at
   or (r->>'status'='success' and r->>'retrieved_at'<>r->>'attempted_at')
   or jsonb_typeof(c->'fields'->'quoteType') is distinct from 'string'
   or c->'fields'->>'quoteType' !~ '^[A-Z][A-Z0-9_]{0,31}$'
   or c is distinct from jsonb_build_object('version','yfinance_info_context_v1','code',new.code,
    'provider_symbol',symbol,'source','yfinance','fields',jsonb_build_object('quoteType',c->'fields'->>'quoteType'),
    'scope','Same-response provider info calendar and currencies; not per-metric periods or cross-provider currency attribution',
    'classification_scope','Same-response Yahoo quoteType; does not reinterpret another provider trust/fund category') then
   raise exception using errcode='22023',message='Invalid subtype identity or receipt';
  end if;
 end if;
 if tg_op='INSERT' then
  if new.revision<>1 or (r->>'status'<>'success' and c<>'null'::jsonb) then
   raise exception using errcode='22023',message='Invalid initial subtype evidence';
  end if;
 else
  if new.market<>old.market or new.code<>old.code or new.revision<>old.revision+1
   or attempt_at<=(old.record->>'attempted_at')::timestamptz
   or (r->>'status'<>'success' and (r->'context' is distinct from old.record->'context'
      or r->'retrieved_at' is distinct from old.record->'retrieved_at')) then
   raise exception using errcode='22023',message='Stale or conflicting subtype update';
  end if;
 end if;
 return new;
end;$$;
create trigger instrument_subtype_cache_guard before insert or update on public.instrument_subtype_cache
 for each row execute function public.instrument_subtype_cache_guard();
revoke all on function public.instrument_subtype_cache_guard() from public,anon,authenticated;
grant execute on function public.instrument_subtype_cache_guard() to service_role;

create function public.instrument_subtype_cache_save(p_market text,p_code text,p_revision integer,p_record jsonb)
returns setof public.instrument_subtype_cache language plpgsql security invoker set search_path='' as $$
declare existing public.instrument_subtype_cache;
begin
 if p_revision is null or p_revision<0 then
  raise exception using errcode='22023',message='Invalid subtype revision';
 end if;
 if p_revision=0 then
  insert into public.instrument_subtype_cache(market,code,revision,record)
   values(p_market,p_code,1,p_record) on conflict do nothing;
 else
  update public.instrument_subtype_cache set revision=revision+1,record=p_record
   where market=p_market and code=p_code and revision=p_revision;
 end if;
 select * into existing from public.instrument_subtype_cache where market=p_market and code=p_code;
 -- Same receipt replay after an uncertain transport outcome is idempotent.
 if existing.revision=p_revision+1 and existing.record=p_record then return next existing;end if;
 return;
end;$$;
revoke all on function public.instrument_subtype_cache_save(text,text,integer,jsonb) from public,anon,authenticated;
grant execute on function public.instrument_subtype_cache_save(text,text,integer,jsonb) to service_role;
