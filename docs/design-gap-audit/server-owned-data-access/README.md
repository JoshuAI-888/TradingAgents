# Confirmed production access-control gap and prepared remediation

Read-only connected Supabase inspection, 3 October 2026. Project `tradingagents` (`hiqasyjalspuchtacatk`), reported ACTIVE_HEALTHY, PostgreSQL 17.6.1.166. The local shell has no Supabase/Moomoo credentials; the connected tool can read platform metadata. No production data or schema was changed.

## Authoritative findings

- Migration history ends at `20261002002748 investment_workspace_state`. The local private-history/generation/classification/review migrations are absent from production. This confirms that local qualification does not prove deployed behavior.
- These 12 public tables have RLS disabled and actual SELECT/INSERT/UPDATE/DELETE grants for both `anon` and `authenticated`: corporate_actions, company_profiles, fundamentals, insider_transactions, macro_series, macro_observations, social_posts, prediction_market_quotes, data_fetch_log, backtest_runs, embeddings, vendor_budget_ledger.
- Target tables have no policies. `anon` and `authenticated` do not bypass RLS; `service_role` does and has CRUD grants on every target table.
- `v_decision_ledger` and `v_equity_curve` have default view options and browser SELECT grants. These definer views bypass underlying owner policies. The vendor_health materialized view also has browser SELECT grants. No private rows were read to establish this metadata finding.
- Portal and worker DB transport uses its server-side service key for both apikey and Bearer headers (`tradingagents_worker/db.py`); browser operations route through the portal. The selected remediation denies direct browser SQL access and preserves that existing service contract.

## Prepared local migration

CLI generated `20261002142613_server_owned_data_access.sql`: enable RLS on all 12 tables, revoke PUBLIC/anon/authenticated table privileges, preserve service CRUD, make both analytics views security-invoker, revoke browser access to the two views and vendor_health, preserve service SELECT. No data/policy/ownership deletion and no credentials included. Applied on 3 October as `20261003103407_server_owned_data_access.sql` with identical bytes; verified target RLS/grants, service reads and advisor remediation. See the MVP cutover runbook for remaining gates.

Rollback-only native PostgreSQL 16 contract (`web/api/tests/server-owned-data-access-db-contract.sql`) applies the migration twice, preserves existing content, exercises service read/insert/update/delete on all 12 targets, reads all analytics objects, and executes 96 denied browser table statements plus six denied analytics reads. A deliberate later anon SELECT grant still yields no table or nested-view rows through RLS/invoker semantics. Contract passes and rolls back. This uses synthetic table shapes and actual roles; PostgreSQL 17/PostgREST production checks remain required.

## Release prerequisites still open

- Supabase advisors: previous automatic approval review rejected the advisor invocation because schema/connection metadata may be transmitted externally without specific permission. Do not bypass that restriction through the connected advisor tool. Existing user approval remains unanswered.
- Confirm actual platform migration, public portal read behavior and service writes after applying the reviewed migration. Check original saved definitions and table counts before/after; preserve existing rows. Do not roll back by restoring insecure anonymous write grants.
- Qualify the rest of private Auth/generation/history/schema migration cutover and rollback separately. This targeted access patch does not close R15 or justify enabling any new feature.

Sources: [official Supabase RLS/grants/view guidance](https://supabase.com/docs/guides/database/postgres/row-level-security), [current PostgreSQL breaking-change notice](https://supabase.com/changelog/postgres-15-19-17-11-breaking-changes). Changelog checked: ltree/pgcrypto/btree_gist/custom-operator changes do not apply to this RLS/grant/view-only migration.
