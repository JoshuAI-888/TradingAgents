# Bounded market storage

Supabase Free allows 500 MB of database storage. The operational ceiling is
450,000,000 bytes across the **whole database**, with warnings at 350 MB.
Publication, staging, retention and raw-cache writes share a transaction lock.
US enumeration reserves 150 MB and HK reserves 50 MB, including other active
leases. Refresh admission stops above 400 MB or when those reservations would
exceed the ceiling. A rejected refresh preserves the published generation.

## Market data

- Enrichment uses only stocks in the currently published generation. History is
  fetched and technical indicators are calculated in memory, then each symbol's
  metrics are saved before its freshness state advances. Interrupted runs resume
  from completed symbols; old fundamentals keep their own clock.
- Technical rotation processes up to 4,000 eligible symbols per market per run,
  oldest first, with a 24-hour freshness rule. This does not promise that every
  symbol remains fresh every day; the API continues to suppress stale fields.
- The optional raw cache contains at most 1,000 current stocks per market,
  prioritizing watchlist symbols, and 260 recent daily bars per symbol. Its writer
  enforces a 150 MB relation budget and retains headroom for the next US refresh.
  Direct service-role insertion and updates are denied. Daily retention can evict
  this expendable cache above 280 MB without losing computed enrichment.
- Generation retention preserves the published pointer, the two newest cohorts
  per market and a 24-hour reader grace period. Staging expires after one hour
  when no lease is active. An empty staging table is truncated to release space.
- Supabase cron runs `screener_storage_retention()` at 04:30 UTC daily. The
  `storage_state` setting records measured bytes and deletion counts.

## Backups

The existing weekly backup exports the 27 recovery tables, excluding raw market
bars and secrets. New backups use unique UTC prefixes and are accepted only
after remote SHA-256, gzip, JSON and row-count verification. Keep four verified
new-format backups. Legacy backups are preserved. Incomplete exports older than
seven days can be removed only after a newer complete backup is verified.
The bucket has a 750 MB operating ceiling and a warning at 250 MB, separate
from the database quota. These checks verify exported objects; they do not make
the sequential table export a transactionally consistent database snapshot.

## Deployment and recovery

Apply `20261010094127_bounded_market_storage.sql` before deploying this worker.
It also restores immutable-row and deletion fences and aligns exhausted US
screening receipts with the worker's bounded skipped-identity contract. HK
classification reads now use stable code ordering during pagination.

On 2026-10-10, all 27 pre-maintenance recovery exports were downloaded and
verified before clearing the oversized raw cache, its freshness state and expired
staging. The database fell from 804,998,291 to 187,509,907 bytes. Published cohorts
and enrichment were preserved. Refreshes and enrichment repopulate current data.

Do not roll back to the unrestricted raw writer or the old v1 capacity client:
the database deliberately denies those writes and returns a v2 capacity receipt.
Prefer a compatible forward fix. Any SQL rollback must retain capacity, receipt
validation and published-generation protection. No hosting plans were changed.

Monitor the Supabase usage page for its independently measured 5 GB uncached
egress quota. Compact quote projections remove duplicate full-cohort transfers,
but database bounds alone do not guarantee an egress allowance. Inspect actual
monthly usage before increasing refresh frequency or history coverage.
