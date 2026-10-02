-- Provider caches, operational records and server-built analytics are accessed
-- through the portal/worker service client, not directly with browser JWTs.
-- No data, existing policies or ownership is changed by this migration.
do $$
declare name text;
begin
  foreach name in array array[
    'corporate_actions','company_profiles','fundamentals','insider_transactions',
    'macro_series','macro_observations','social_posts','prediction_market_quotes',
    'data_fetch_log','backtest_runs','embeddings','vendor_budget_ledger'
  ] loop
    execute format('alter table public.%I enable row level security',name);
    execute format('revoke all on table public.%I from public, anon, authenticated',name);
    execute format('grant select, insert, update, delete on table public.%I to service_role',name);
  end loop;
end $$;

-- Definer views otherwise bypass the underlying owner policies. The portal
-- continues reading them with its existing server-side service role.
alter view public.v_decision_ledger set (security_invoker=true);
alter view public.v_equity_curve set (security_invoker=true);
revoke all on table public.v_decision_ledger, public.v_equity_curve,
  public.vendor_health from public, anon, authenticated;
grant select on table public.v_decision_ledger, public.v_equity_curve,
  public.vendor_health to service_role;
