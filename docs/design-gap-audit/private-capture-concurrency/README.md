# Native worker concurrency qualification

[native-concurrency.py](native-concurrency.py) ran against actual PostgreSQL 16.14 processes in a fresh capture_concurrency_qualification database cloned from the isolated local foundation. It applied the four current schedule/dispatch/lease/publication migrations, and removed the disposable database in finally. No production database, remote Auth or provider was accessed.

[native-concurrency-result.json](native-concurrency-result.json) records completed assertions:
- Confirmed the first claim transaction was live in PgSleep while holding its locks before starting the second worker. The contender skipped the locked schedule; the persisted live lease was not reclaimed after commit.
- Forced durable lease expiry to model a crashed worker. Recovery reclaimed the same occurrence at attempt 2 with a fresh token. Original worker/token renewal, failure and publication returned no rows.
- Built complete synthetic two-stock evidence through the actual capture builder. Confirmed a second publication process was waiting for a PostgreSQL lock while the first publication remained uncommitted. Both calls confirmed the same capture after commit; exactly one capture and succeeded occurrence persisted.
- Confirmed schedule-off/edit revision 2 held its transaction before a waiting publication. The waiting revision-1 publication returned no rows after the edit committed. Renewal failed, claim cancelled the obsolete occurrence, and the prior successful capture remained.

This closes the native overlapping claim/publication/edit cases only. Forced lease expiry is not an executed worker-process crash/restart. Real PostgREST transport, long-running renewal/shutdown, actual worker restart, larger history/cohort stress, market sessions, real provider and production qualification remain open. User automation remains disabled.
