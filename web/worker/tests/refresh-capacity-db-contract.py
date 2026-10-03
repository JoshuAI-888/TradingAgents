"""Apply actual migration rollback-only in the isolated qualification database.

Needs its existing generation/staging tables and roles. No production connection,
no row content reads, no relation expansion to manufacture a 500 MiB fixture.
"""

import subprocess
from pathlib import Path

migration = Path(
    "supabase/migrations/20261003124611_screener_refresh_capacity_guard.sql"
).read_text()
assert migration.count("begin;\n") == 1 and migration.endswith("commit;\n")
migration = migration.replace("begin;\n", "", 1).removesuffix("commit;\n")
sql = (
    "begin;\n"
    + migration
    + """
do $$
declare definition pg_catalog.pg_proc; before_bytes bigint; result jsonb;
begin
 select * into definition from pg_catalog.pg_proc
  where oid='public.screener_refresh_capacity(text)'::pg_catalog.regprocedure;
 if definition.prosecdef or definition.proconfig <> array['search_path=""'] then
  raise exception 'Capacity function privilege/search-path contract failed';
 end if;
 if pg_catalog.has_function_privilege('anon',definition.oid,'execute')
  or pg_catalog.has_function_privilege('authenticated',definition.oid,'execute')
  or not pg_catalog.has_function_privilege('service_role',definition.oid,'execute') then
  raise exception 'Capacity RPC role contract failed';
 end if;
 before_bytes := pg_catalog.pg_total_relation_size('public.screener_generation_rows')
  + pg_catalog.pg_total_relation_size('public.screener_refresh_staged_rows')
  + pg_catalog.pg_total_relation_size('public.screener_generations');
 result := public.screener_refresh_capacity('US');
 if result->>'version' <> 'screener_capacity_v1' or result->>'market' <> 'US'
  or (result->>'used_bytes')::bigint <> before_bytes
  or (result->>'limit_bytes')::bigint <> 524288000
  or (result->>'allowed')::boolean <> (before_bytes < 524288000)
  or (result->'relation_bytes'->>'generation_rows')::bigint
    <> pg_catalog.pg_total_relation_size('public.screener_generation_rows')
  or (result->'relation_bytes'->>'staged_rows')::bigint
    <> pg_catalog.pg_total_relation_size('public.screener_refresh_staged_rows')
  or (result->'relation_bytes'->>'generations')::bigint
    <> pg_catalog.pg_total_relation_size('public.screener_generations') then
  raise exception 'Native physical capacity measurement mismatch';
 end if;
 begin
  perform public.screener_refresh_capacity('ASX');
  raise exception 'Invalid market accepted';
 exception when invalid_parameter_value then null; end;
 begin
  perform public.screener_refresh_capacity(null);
  raise exception 'Null market accepted';
 exception when invalid_parameter_value then null; end;
end; $$;
set local role service_role;
select public.screener_refresh_capacity('HK');
reset role;
set local role anon;
do $$ begin
 begin
  perform public.screener_refresh_capacity('US');
  raise exception 'Anonymous capacity access allowed';
 exception when insufficient_privilege then null; end;
end; $$;
reset role;
set local role authenticated;
do $$ begin
 begin
  perform public.screener_refresh_capacity('US');
  raise exception 'Authenticated capacity access allowed';
 exception when insufficient_privilege then null; end;
end; $$;
reset role;
rollback;
select to_regprocedure('public.screener_refresh_capacity(text)') is null as migration_rolled_back;
"""
)
subprocess.run(
    [
        "/opt/homebrew/opt/postgresql@16/bin/psql",
        "postgresql://joshmini@localhost/screener_generation_migration_verification?host=/private/tmp/tradingagent-research-pg&port=55439",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
    ],
    check=True,
)
print(
    "PASS actual capacity migration, physical relation totals, service/browser roles and rollback"
)
