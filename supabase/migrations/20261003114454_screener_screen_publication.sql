-- Keep generation publication atomic and service-only. The larger screened
-- cohort needs a bounded RPC-specific timeout; interactive queries retain theirs.
begin;

create or replace function public.screener_refresh_publish(p_market text, p_run uuid, p_codes jsonb,
  p_rows jsonb, p_result jsonb, p_enumerated boolean default false)
returns jsonb language plpgsql security invoker set search_path = '' set statement_timeout = '45s' as $$
declare
  lease public.screener_refresh_leases;
  run public.screener_refresh_runs;
  prior public.screener_generations;
  n integer;
  stamp timestamptz;
  cohort_hash text;
  payload_hash text;
  receipt jsonb;
  result jsonb;
  state jsonb;
begin
  if p_market is null or p_market not in ('US','HK') or p_run is null or p_enumerated is null
      or jsonb_typeof(p_codes) is distinct from 'array'
      or jsonb_typeof(p_rows) is distinct from 'array'
      or jsonb_typeof(p_result) is distinct from 'object' then
    raise exception 'Invalid screener generation payload' using errcode = '22023';
  end if;
  n := jsonb_array_length(p_codes);
  if n not between 1 and 20000 or jsonb_array_length(p_rows) <> n
      or pg_catalog.octet_length(p_rows::text) > 67108864
      or pg_catalog.octet_length(p_result::text) > 65536 then
    raise exception 'Incomplete or oversized screener generation' using errcode = '22023';
  end if;
  if exists (select 1 from jsonb_array_elements(p_codes) c
      where jsonb_typeof(c) <> 'string' or (c #>> '{}') !~ ('^' || p_market || '\.[A-Z0-9][A-Z0-9._-]{0,30}$'))
      or (select count(distinct c #>> '{}') from jsonb_array_elements(p_codes) c) <> n then
    raise exception 'Invalid or duplicate requested identities' using errcode = '22023';
  end if;
  if exists (select 1 from jsonb_array_elements(p_rows) r
      where jsonb_typeof(r) <> 'object'
        or jsonb_typeof(r->'code') is distinct from 'string'
        or jsonb_typeof(r->'row') is distinct from 'object'
        or r->'row'->>'code' is distinct from r->>'code'
        or jsonb_typeof(r->'metadata') is distinct from 'object'
        or r->'metadata'->>'code' is distinct from r->>'code'
        or r->'metadata'->>'market' is distinct from p_market
        or (r->'metadata' ? 'name' and jsonb_typeof(r->'metadata'->'name') not in ('string','null'))
        or (r->'metadata' ? 'plate' and jsonb_typeof(r->'metadata'->'plate') not in ('string','null'))
        or (r->'metadata' ? 'exchange' and jsonb_typeof(r->'metadata'->'exchange') not in ('string','null'))
        or jsonb_typeof(r->'metadata'->'stock_type') is distinct from 'string'
        or length(r->'metadata'->>'stock_type') not between 1 and 32
        or jsonb_typeof(r->'metadata'->'plates') is distinct from 'array'
        or jsonb_typeof(r->'quote_cache_at') is distinct from 'string'
        or r->>'quote_cache_at' !~ '^\d{4}-\d{2}-\d{2}T.*(Z|[+-]\d{2}:\d{2})$')
      or (select count(distinct r->>'code') from jsonb_array_elements(p_rows) r) <> n
      or exists (select c #>> '{}' from jsonb_array_elements(p_codes) c
                 except select r->>'code' from jsonb_array_elements(p_rows) r) then
    raise exception 'Generation rows do not match the classified requested cohort' using errcode = '22023';
  end if;
  if exists (select 1 from jsonb_array_elements(p_rows) r,
      lateral jsonb_array_elements(r->'metadata'->'plates') p where jsonb_typeof(p) <> 'string') then
    raise exception 'Invalid provider plate metadata' using errcode = '22023';
  end if;
  select pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(
    string_agg(c #>> '{}', E'\n' order by (c #>> '{}') collate "C"),'UTF8')),'hex')
    into cohort_hash from jsonb_array_elements(p_codes) c;
  -- Object key order is canonicalized by JSONB; array order is part of exact replay.
  payload_hash := pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(
    jsonb_build_array(p_market,p_run,p_codes,p_rows,p_result,p_enumerated)::text,'UTF8')),'hex');
  select * into lease from public.screener_refresh_leases where market = p_market for update;
  select * into prior from public.screener_generations where id = p_run;
  if found then
    if prior.market <> p_market or prior.payload_fingerprint <> payload_hash then
      raise exception 'Conflicting replay of a published generation' using errcode = '22023';
    end if;
    return jsonb_build_object('generation_id',prior.id,'market',prior.market,
      'published_at',prior.published_at,'row_count',prior.row_count,
      'cohort_fingerprint',prior.cohort_fingerprint,'result',prior.result);
  end if;
  if lease.run_id is distinct from p_run or lease.expires_at <= pg_catalog.clock_timestamp() then
    raise exception 'Refresh lease is expired or superseded' using errcode = '55000';
  end if;
  select * into run from public.screener_refresh_runs where id = p_run;
  if not found or run.market <> p_market then
    raise exception 'Refresh run does not own this market' using errcode = '55000';
  end if;
  -- Lock the pointer and preserve unrelated config/state fields during publication.
  select value into state from public.app_settings where key = 'universe_state_' || p_market for update;
  if not found or jsonb_typeof(state) is distinct from 'object'
      or state->'last_attempt'->>'run_id' is distinct from p_run::text
      or state->'last_attempt'->>'status' is distinct from 'running' then
    raise exception 'Refresh attempt state does not belong to this run' using errcode = '55000';
  end if;
  if (state->>'generation_id')::uuid is distinct from run.base_generation_id then
    raise exception 'Published generation changed during refresh' using errcode = '55000';
  end if;
  stamp := pg_catalog.clock_timestamp();
  if exists (select 1 from jsonb_array_elements(p_rows) r
      where (r->>'quote_cache_at')::timestamptz < run.started_at
         or (r->>'quote_cache_at')::timestamptz > stamp) then
    raise exception 'Quote cache receipt is outside the refresh interval' using errcode = '22023';
  end if;
  if (not p_enumerated and p_result ? 'enum') or (p_enumerated and (jsonb_typeof(p_result->'enum') is distinct from 'object'
      or coalesce(p_result->'enum'->>'scope','') not in ('observed_plate_and_screen_slice_union','exhausted_provider_market_screen')
      or p_result->'enum'->>'codes' is distinct from n::text)) then
    raise exception 'Invalid enumeration receipt' using errcode = '22023';
  end if;
  if p_enumerated and p_result->'enum'->>'scope' = 'exhausted_provider_market_screen'
      and (p_result->'enum'->>'provider_total' is distinct from n::text
        or coalesce(p_result->'enum'->>'pages','') !~ '^[1-9][0-9]?$'
        or (p_result->'enum'->>'pages')::integer > 68) then
    raise exception 'Invalid exhausted screening receipt' using errcode = '22023';
  end if;
  result := p_result || jsonb_build_object('market',p_market,'quotes',jsonb_build_object(
    'quotes',n,'requested',n,'batches',(n+399)/400,'cohort_fingerprint',cohort_hash,
    'scope','requested_stored_universe'));
  receipt := jsonb_build_object('generation_id',p_run,'market',p_market,
    'published_at',stamp,'row_count',n,'cohort_fingerprint',cohort_hash,'result',result);
  insert into public.screener_generations(id,market,started_at,published_at,row_count,
    cohort_fingerprint,payload_fingerprint,result)
    values (p_run,p_market,run.started_at,stamp,n,cohort_hash,payload_hash,result);
  insert into public.screener_generation_rows(generation_id,code,row,metadata,quote_cache_at)
    select p_run,r->>'code',r->'row',r->'metadata',(r->>'quote_cache_at')::timestamptz
    from jsonb_array_elements(p_rows) r;
  -- Atomic compatibility mirrors. Old rows are retained for historical lookups;
  -- authoritative complete membership is generation_id + generation_rows only.
  insert into public.screener_universe(market,code,name,plate,plates,stock_type,exchange,updated_at)
    select p_market,r->>'code',r->'metadata'->>'name',r->'metadata'->>'plate',
      r->'metadata'->'plates',r->'metadata'->>'stock_type',r->'metadata'->>'exchange',stamp
    from jsonb_array_elements(p_rows) r
    on conflict (market,code) do update set name=excluded.name,plate=excluded.plate,
      plates=excluded.plates,stock_type=excluded.stock_type,exchange=excluded.exchange,updated_at=excluded.updated_at;
  insert into public.screener_quotes(code,market,row,updated_at)
    select r->>'code',p_market,r->'row',(r->>'quote_cache_at')::timestamptz
    from jsonb_array_elements(p_rows) r
    on conflict (code) do update set market=excluded.market,row=excluded.row,updated_at=excluded.updated_at;
  update public.app_settings set value = coalesce(state,'{}'::jsonb)
    || jsonb_build_object('generation_id',p_run,'last_quotes',stamp,'last_result',result,
      'last_attempt',jsonb_build_object('run_id',p_run,'started_at',run.started_at,
        'finished_at',stamp,'status','succeeded','stage','publication'))
    || case when p_enumerated then jsonb_build_object('last_enum',stamp) else '{}'::jsonb end,
    updated_at=stamp where key='universe_state_' || p_market;
  update public.screener_refresh_leases set expires_at=stamp where market=p_market;
  return receipt;
end;
$$;

notify pgrst, 'reload schema';
commit;
