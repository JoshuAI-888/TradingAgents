# Screener refresh storage admission guard

Prepared locally on 4 October 2026. No production migration, Render change, retention/deletion or paid resource change performed by this workstream.

`20261003124611_screener_refresh_capacity_guard.sql` adds a service-only `screener_refresh_capacity(text)` RPC. It uses SECURITY INVOKER and an empty search path, revokes PUBLIC/anon/authenticated execution, and measures the sum of `pg_total_relation_size` for generation rows, staged rows and generation headers, including indexes and TOAST. Its fixed server-side admission budget is **524,288,000 bytes (500 MiB)** across US and HK. No caller-supplied budget can bypass it.

When a refresh is necessary, the worker checks this receipt before acquiring a run/lease or requesting provider data. At or above the budget, it emits a descriptive operational error and raises: no generation rows, staging, run or state/pointer writes are attempted. Malformed receipts, negative sizes, wrong markets/versions/budgets, inconsistent sums/decisions and failed RPCs also stop work. A fresh-generation no-op remains a no-op. Existing last-good data remains readable.

This stops indefinite growth from repeated hourly generation publication after the threshold is reached. It is an **admission guard, not a hard database quota**: an admitted in-flight refresh or simultaneous US/HK refreshes can exceed the threshold before the next check. It does not bound other tables, queue/event logs, WAL or total project storage, and does not reclaim retained staging or historical generations. Storage monitoring and an explicit retention/archive decision remain operational follow-ups. Do not describe this as automatic retention or a guarantee that total project storage cannot fill.

Apply the migration before deploying the updated worker or restoring refresh schedules. A missing RPC deliberately stops refresh; it does not fall back to unguarded writes. The root release owner reviews and performs production application separately.

Verification:

- 99 focused tests pass across capacity, universe-refresh and transport suites. Boundary/elevated-budget tests repeat three attempts and retain the original tables, staging, leases and pointer exactly; provider calls and acquisition are forbidden. Both US/HK success paths check before acquisition/publication.
- Native PostgreSQL 16 rollback-only `web/worker/tests/refresh-capacity-db-contract.py` applies the actual migration, checks exact physical relation sums, fixed budget, invoker/search-path attributes, real service execution and denied anon/authenticated execution. Invalid/null markets fail. Migration is absent after rollback. Synthetic existing cohort measured 3,145,728 bytes; this is local qualification, not production capacity evidence.

References checked: [Supabase database functions](https://supabase.com/docs/guides/database/functions), [PostgreSQL relation-size functions](https://www.postgresql.org/docs/current/functions-admin.html), and [Supabase changelog](https://supabase.com/changelog). The listed PostgreSQL minor-version changes for ltree/pgcrypto/btree_gist/custom operators do not affect this built-in relation-size/invoker RPC.
