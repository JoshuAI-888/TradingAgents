-- Service-only storage admission, bounded raw cache and protected retention.
-- No research/product records are deleted by this migration.
begin;

create or replace function public.screener_refresh_capacity(p_market text)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare used bigint; reserved bigint; required bigint; sizes jsonb;
begin
  if p_market is null or p_market not in ('US','HK') then
    raise exception 'Invalid screener capacity market' using errcode='22023';
  end if;
  used := pg_catalog.pg_database_size(pg_catalog.current_database());
  required := case when p_market='US' then 150000000 else 50000000 end;
  select coalesce(sum(case when market='US' then 150000000 else 50000000 end),0)
    into reserved from public.screener_refresh_leases
    where market<>p_market and expires_at>pg_catalog.clock_timestamp();
  sizes := jsonb_build_object(
    'generation_rows',pg_catalog.pg_total_relation_size('public.screener_generation_rows'),
    'staged_rows',pg_catalog.pg_total_relation_size('public.screener_refresh_staged_rows'),
    'generations',pg_catalog.pg_total_relation_size('public.screener_generations'));
  return jsonb_build_object('version','screener_capacity_v2','market',p_market,
    'used_bytes',used,'limit_bytes',450000000,'reserved_bytes',reserved,
    'required_bytes',required,'relation_bytes',sizes,
    'allowed',used<400000000 and used+reserved+required<=450000000);
end; $$;

create function public.screener_exhausted_receipt_valid(receipt jsonb,n integer)
returns boolean language plpgsql immutable security invoker set search_path='' as $$
declare skipped integer; total integer; pages integer;
begin
  if n not between 1 and 20000 or jsonb_typeof(receipt)<>'object'
    or coalesce(receipt->>'provider_total','') !~ '^[0-9]{1,5}$'
    or coalesce(receipt->>'pages','') !~ '^[1-9][0-9]?$'
    or coalesce(receipt->>'skipped_nonconforming','0') !~ '^[0-9]{1,2}$' then return false; end if;
  skipped := coalesce(receipt->>'skipped_nonconforming','0')::integer;
  total := (receipt->>'provider_total')::integer;
  pages := (receipt->>'pages')::integer;
  return skipped<=50 and total=n+skipped and total<=20000
    and pages between (total+299)/300 and 68;
end; $$;

-- Shared transaction lock makes begin/reservation and bulk writes atomic across
-- both markets. Lease expiry releases reservations without a separate ledger.
create function public.screener_storage_check_growth(extra_bytes bigint)
returns void language plpgsql security invoker set search_path='' as $$
begin
  perform pg_catalog.pg_advisory_xact_lock(743510);
  if extra_bytes is null or extra_bytes<0
    or pg_catalog.pg_database_size(pg_catalog.current_database())+extra_bytes>450000000 then
    raise exception 'Projected database storage exceeds 450 MB' using errcode='53000';
  end if;
end; $$;

-- Preserve every existing fencing, replay, identity and classification check.
-- Replace only the receipt predicate and add admission at the write boundaries.
do $patch$
declare fn regprocedure; definition text; old_predicate text;
begin
  fn := 'public.screener_refresh_begin(text,uuid,integer)'::regprocedure;
  definition := pg_get_functiondef(fn);
  if position(E'begin\n' in definition)=0 then raise exception 'Unknown begin function layout'; end if;
  definition := replace(definition,E'begin\n',E'begin\n  perform pg_catalog.pg_advisory_xact_lock(743510);\n  if not exists(select 1 from public.screener_refresh_leases where market=p_market and run_id=p_run and expires_at>pg_catalog.clock_timestamp()) and not (public.screener_refresh_capacity(p_market)->>''allowed'')::boolean then\n    raise exception ''Insufficient database headroom for refresh reservation'' using errcode=''53000'';\n  end if;\n');
  execute definition;

  fn := 'public.screener_refresh_stage(text,uuid,jsonb)'::regprocedure;
  definition := pg_get_functiondef(fn);
  definition := replace(definition,E'begin\n',E'begin\n  perform pg_catalog.pg_advisory_xact_lock(743510);\n');
  definition := replace(definition,'  insert into public.screener_refresh_staged_rows',E'  perform public.screener_storage_check_growth(pg_catalog.octet_length(p_rows::text)::bigint*2+1048576);\n  insert into public.screener_refresh_staged_rows');
  execute definition;

  foreach fn in array array[
    'public.screener_refresh_publish_staged(text,uuid,jsonb,jsonb,boolean)'::regprocedure,
    'public.screener_refresh_publish(text,uuid,jsonb,jsonb,jsonb,boolean)'::regprocedure
  ] loop
    definition := pg_get_functiondef(fn);
    definition := replace(definition,E'begin\n',E'begin\n  perform pg_catalog.pg_advisory_xact_lock(743510);\n');
    old_predicate := substring(definition from '(and \(p_result->''enum''->>''provider_total''[\s\S]*?(?:\(n\+299\)/300|68)\))');
    if old_predicate is null then raise exception 'Unknown exhausted receipt predicate in %',fn; end if;
    definition := replace(definition,old_predicate,'and not public.screener_exhausted_receipt_valid(p_result->''enum'',n)');
    if position('publish_staged' in fn::text)>0 then
      definition := replace(definition,'  insert into public.screener_generations',E'  perform public.screener_storage_check_growth(coalesce((select sum(pg_catalog.octet_length(payload::text))::bigint*3 from public.screener_refresh_staged_rows where run_id=p_run),0)+16777216);\n  insert into public.screener_generations');
    else
      definition := replace(definition,'  insert into public.screener_generations',E'  perform public.screener_storage_check_growth(pg_catalog.octet_length(p_rows::text)::bigint*3+16777216);\n  insert into public.screener_generations');
    end if;
    execute definition;
  end loop;
end; $patch$;

create function public.screener_kline_cache_members()
returns table(market text,code text) language sql stable security invoker set search_path='' as $$
  with current_rows as (
    select g.market,r.code from public.app_settings s
    join public.screener_generations g on g.id=(s.value->>'generation_id')::uuid
    join public.screener_generation_rows r on r.generation_id=g.id
    where s.key in ('universe_state_US','universe_state_HK') and r.metadata->>'stock_type'='STOCK'
  ), watched as (
    select distinct case
      when t.currency='HKD' and t.symbol ~ '^[0-9]{1,5}$' then 'HK.'||lpad(t.symbol,5,'0')
      when t.currency='USD' and t.native_symbol ~ '^[A-Z0-9][A-Z0-9._-]{0,30}$' then 'US.'||t.native_symbol
    end code from public.watchlist_items w join public.tickers t on t.id=w.ticker_id
    where w.active
  ), ranked as (
    select c.*,row_number() over(partition by c.market order by (w.code is not null) desc,c.code collate "C") n
    from current_rows c left join watched w on w.code=c.code
  ) select r.market,r.code from ranked r where r.n<=1000;
$$;

-- Narrow privileged writer: service_role cannot bypass admission by direct REST
-- inserts. EXECUTE is revoked from PUBLIC/anon/authenticated below.
create function public.screener_kline_cache_write(p_market text,p_code text,p_rows jsonb)
returns integer language plpgsql security definer set search_path='' as $$
declare n integer; reserved bigint;
begin
  perform pg_catalog.pg_advisory_xact_lock(743510);
  if p_market is null or p_market not in ('US','HK') or p_code is null
    or p_code !~ ('^'||p_market||'\.[A-Z0-9][A-Z0-9._-]{0,30}$')
    or jsonb_typeof(p_rows) is distinct from 'array' then
    raise exception 'Invalid kline cache payload' using errcode='22023'; end if;
  n:=jsonb_array_length(p_rows);
  if n not between 1 and 260 or pg_catalog.octet_length(p_rows::text)>131072
    or exists(select 1 from jsonb_array_elements(p_rows) r
      where r->>'market' is distinct from p_market or r->>'code' is distinct from p_code
        or coalesce(r->>'day','') !~ '^\d{4}-\d{2}-\d{2}$'
        or (r->>'day')::date>current_date or (r->>'day')::date<current_date-550)
    or (select count(distinct r->>'day') from jsonb_array_elements(p_rows) r)<>n then
    raise exception 'Invalid or oversized kline cache rows' using errcode='22023'; end if;
  if not exists(select 1 from public.screener_kline_cache_members() m where m.market=p_market and m.code=p_code) then return 0; end if;
  select coalesce(sum(case when market='US' then 150000000 else 50000000 end),0)
    into reserved from public.screener_refresh_leases where expires_at>pg_catalog.clock_timestamp();
  -- Reserve the larger next refresh even while no universe run is active.
  if pg_catalog.pg_database_size(pg_catalog.current_database())+reserved+150000000+n*512>450000000
    or pg_catalog.pg_total_relation_size('public.screener_klines')+n*512>150000000 then return 0; end if;
  delete from public.screener_klines k where k.market=p_market and k.code=p_code
    and not exists(select 1 from jsonb_array_elements(p_rows) r where (r->>'day')::date=k.day);
  insert into public.screener_klines(market,code,day,o,h,l,c,v)
    select p_market,p_code,(r->>'day')::date,(r->>'o')::double precision,
      (r->>'h')::double precision,(r->>'l')::double precision,(r->>'c')::double precision,(r->>'v')::double precision
    from jsonb_array_elements(p_rows) r
    on conflict(market,code,day) do update set o=excluded.o,h=excluded.h,l=excluded.l,c=excluded.c,v=excluded.v
    where (screener_klines.o,screener_klines.h,screener_klines.l,screener_klines.c,screener_klines.v)
      is distinct from (excluded.o,excluded.h,excluded.l,excluded.c,excluded.v);
  return n;
end; $$;

-- Restore immutable updates/truncation while allowing only bounded expiry.
drop trigger if exists screener_generation_rows_immutable on public.screener_generation_rows;
create trigger screener_generation_rows_immutable before update or truncate
  on public.screener_generation_rows for each statement execute function public.screener_generation_immutable();
drop trigger if exists screener_staged_rows_immutable on public.screener_refresh_staged_rows;
create trigger screener_staged_rows_immutable before update
  on public.screener_refresh_staged_rows for each statement execute function public.screener_generation_immutable();
create function public.screener_empty_staging_truncate_fence()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
  if exists(select 1 from public.screener_refresh_staged_rows) then
    raise exception 'Nonempty staging cannot be truncated' using errcode='55000';
  end if;
  return null;
end; $$;
create trigger screener_staged_empty_truncate before truncate on public.screener_refresh_staged_rows
  for each statement execute function public.screener_empty_staging_truncate_fence();

create function public.screener_retention_delete_fence()
returns trigger language plpgsql security invoker set search_path='' as $$
begin
  if tg_table_name='screener_refresh_staged_rows' then
    if exists(select 1 from public.screener_refresh_runs where id=old.run_id and started_at>now()-interval '1 hour')
      or exists(select 1 from public.screener_refresh_leases where run_id=old.run_id and expires_at>now()) then
      raise exception 'Staged retry or lease evidence is protected' using errcode='55000'; end if;
  elsif exists(select 1 from public.app_settings where key in ('universe_state_US','universe_state_HK')
    and value->>'generation_id'=old.generation_id::text)
    or exists(select 1 from (select id,published_at,row_number() over(partition by market order by published_at desc,id) n
      from public.screener_generations) g where g.id=old.generation_id and (g.n<=2 or g.published_at>now()-interval '24 hours')) then
    raise exception 'Current, rollback or reader generation is protected' using errcode='55000';
  end if;
  return old;
end; $$;
create trigger screener_generation_delete_fence before delete on public.screener_generation_rows
  for each row execute function public.screener_retention_delete_fence();
create trigger screener_staged_delete_fence before delete on public.screener_refresh_staged_rows
  for each row execute function public.screener_retention_delete_fence();

create function public.screener_storage_retention()
returns jsonb language plpgsql security invoker set search_path='' as $$
declare staged integer; generations integer; bars integer;
begin
  perform pg_catalog.pg_advisory_xact_lock(743510);
  -- Keep abandoned/published staging for one hour for uncertain-response replay.
  delete from public.screener_refresh_staged_rows s using public.screener_refresh_runs r
    where s.run_id=r.id and r.started_at<now()-interval '1 hour'
      and not exists(select 1 from public.screener_refresh_leases l where l.run_id=s.run_id and l.expires_at>now());
  get diagnostics staged=row_count;
  -- Empty transient storage can be truncated safely, reclaiming allocation
  -- without a recurring VACUUM FULL or temporarily duplicating the table.
  if not exists(select 1 from public.screener_refresh_staged_rows) then
    truncate public.screener_refresh_staged_rows;
  end if;
  delete from public.screener_generation_rows r where not exists(
    select 1 from public.app_settings s where s.key in ('universe_state_US','universe_state_HK')
      and s.value->>'generation_id'=r.generation_id::text
  ) and not exists(select 1 from public.screener_generations g where g.id=r.generation_id and g.published_at>now()-interval '24 hours') and r.generation_id not in (
    select id from (select id,row_number() over(partition by market order by published_at desc,id) n
      from public.screener_generations) g where n<=2
  );
  get diagnostics generations=row_count;
  delete from public.screener_klines k where not exists(
    select 1 from public.screener_kline_cache_members() m where m.market=k.market and m.code=k.code
  ) or k.day<current_date-550;
  get diagnostics bars=row_count;
  delete from public.screener_klines k using (
    select market,code,day,row_number() over(partition by market,code order by day desc) n from public.screener_klines
  ) older where older.n>260 and (k.market,k.code,k.day)=(older.market,older.code,older.day);
  -- Raw bars are expendable; preserve next-refresh headroom when allocations
  -- have grown. Derived technicals and computation freshness survive eviction.
  if pg_catalog.pg_database_size(pg_catalog.current_database())>280000000 then
    truncate public.screener_klines;
  end if;
  -- Freshness is computation freshness, so retain it for uncached CURRENT codes.
  delete from public.screener_kline_state k where not exists(
    select 1 from public.app_settings s join public.screener_generation_rows r
      on r.generation_id=(s.value->>'generation_id')::uuid
    where s.key='universe_state_'||k.market and r.code=k.code
  );
  insert into public.app_settings(key,value,updated_at) values('storage_state',jsonb_build_object(
    'measured_at',now(),'database_bytes',pg_catalog.pg_database_size(pg_catalog.current_database()),
    'warning',pg_catalog.pg_database_size(pg_catalog.current_database())>=350000000,
    'staged_deleted',staged,'generation_rows_deleted',generations,'bars_deleted',bars),now())
    on conflict(key) do update set value=excluded.value,updated_at=excluded.updated_at;
  return (select value from public.app_settings where key='storage_state');
end; $$;

revoke all on function public.screener_refresh_capacity(text),public.screener_exhausted_receipt_valid(jsonb,integer),
  public.screener_storage_check_growth(bigint),public.screener_kline_cache_members(),
  public.screener_kline_cache_write(text,text,jsonb),public.screener_storage_retention(),public.screener_retention_delete_fence(),public.screener_empty_staging_truncate_fence() from public,anon,authenticated;
grant execute on function public.screener_refresh_capacity(text),public.screener_exhausted_receipt_valid(jsonb,integer),
  public.screener_storage_check_growth(bigint),public.screener_kline_cache_members(),
  public.screener_kline_cache_write(text,text,jsonb),public.screener_storage_retention(),public.screener_retention_delete_fence(),public.screener_empty_staging_truncate_fence() to service_role;

grant delete on public.screener_generation_rows,public.screener_refresh_staged_rows to service_role;
revoke insert,update on public.screener_klines from service_role;
grant truncate on public.screener_klines,public.screener_refresh_staged_rows to service_role;

-- Retention is scheduled separately after backup and production verification.
commit;
