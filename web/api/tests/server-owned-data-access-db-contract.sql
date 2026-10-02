\set ON_ERROR_STOP on
begin;
-- Synthetic shape; privileges/RLS are exercised by real PostgreSQL roles.
do $$ declare name text; begin
 foreach name in array array['corporate_actions','company_profiles','fundamentals',
 'insider_transactions','macro_series','macro_observations','social_posts',
 'prediction_market_quotes','data_fetch_log','backtest_runs','embeddings','vendor_budget_ledger'] loop
  assert to_regclass('public.'||name) is null, 'Use a qualification database without these production tables';
  execute format('create table public.%I(id integer primary key, payload text)',name);
  execute format('insert into public.%I values (1,''retained'')',name);
  execute format('grant all on table public.%I to anon, authenticated, service_role',name);
 end loop;
end $$;
create view public.v_decision_ledger as select * from public.backtest_runs;
create view public.v_equity_curve as select * from public.v_decision_ledger;
create materialized view public.vendor_health as select * from public.data_fetch_log;
grant all on public.v_decision_ledger,public.v_equity_curve,public.vendor_health to anon,authenticated,service_role;
\ir ../../../supabase/migrations/20261002142613_server_owned_data_access.sql
-- Idempotent migration application must preserve content and grants.
\ir ../../../supabase/migrations/20261002142613_server_owned_data_access.sql
set local role service_role;
do $$ declare name text; n integer; begin
 foreach name in array array['corporate_actions','company_profiles','fundamentals',
 'insider_transactions','macro_series','macro_observations','social_posts',
 'prediction_market_quotes','data_fetch_log','backtest_runs','embeddings','vendor_budget_ledger'] loop
  execute format('select count(*) from public.%I where payload=''retained''',name) into n; assert n=1;
  execute format('insert into public.%I values (2,''new'')',name);
  execute format('update public.%I set payload=''updated'' where id=2',name);
  execute format('select count(*) from public.%I where id=2 and payload=''updated''',name) into n; assert n=1;
  execute format('delete from public.%I where id=2',name);
 end loop;
 foreach name in array array['v_decision_ledger','v_equity_curve','vendor_health'] loop
  execute format('select count(*) from public.%I',name) into n;assert n=1;
 end loop;
end $$;
reset role;
-- Run every denied statement as each browser role, not merely inspect grants.
create function pg_temp.assert_browser_denied() returns void language plpgsql as $$
declare name text; statement text;
begin
 foreach name in array array['corporate_actions','company_profiles','fundamentals',
 'insider_transactions','macro_series','macro_observations','social_posts',
 'prediction_market_quotes','data_fetch_log','backtest_runs','embeddings','vendor_budget_ledger'] loop
  foreach statement in array array[
   format('select * from public.%I',name),format('insert into public.%I values (3,''forged'')',name),
   format('update public.%I set payload=''forged''',name),format('delete from public.%I',name)] loop
   begin execute statement;raise exception 'Browser statement unexpectedly allowed: %',statement;
   exception when insufficient_privilege then null;end;
  end loop;
 end loop;
 foreach name in array array['v_decision_ledger','v_equity_curve','vendor_health'] loop
  begin execute format('select * from public.%I',name);raise exception 'Browser view unexpectedly readable';
  exception when insufficient_privilege then null;end;
 end loop;
end $$;
do $$ begin execute format('grant usage on schema %I to anon,authenticated',
 (select nspname from pg_namespace where oid=pg_my_temp_schema()));end $$;
set local role anon;
select pg_temp.assert_browser_denied();
reset role;
set local role authenticated;
select pg_temp.assert_browser_denied();
reset role;
-- Defense in depth: a mistaken future grant cannot bypass RLS or invoker views.
grant select on public.backtest_runs,public.v_decision_ledger,public.v_equity_curve to anon;
set local role anon;
do $$ declare n integer;begin
 select count(*) into n from public.backtest_runs;assert n=0;
 select count(*) into n from public.v_decision_ledger;assert n=0;
 select count(*) into n from public.v_equity_curve;assert n=0;
end $$;
reset role;
do $$ declare n integer;begin
 select count(*) into n from public.backtest_runs where payload='retained';assert n=1;
 assert (select relrowsecurity from pg_class where oid='public.backtest_runs'::regclass);
end $$;
rollback;
