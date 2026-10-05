# Capture cadence engine and private monitoring integration

2 October 2026. Core cadence implementation; scheduled captures are not yet wired or deployed.

## Implemented

capture_schedule.py defines validated IANA timezone, wall-clock hour/minute and unique weekdays. It requires aware instants, computes the next occurrence strictly after an instant, and returns only the latest due occurrence after a creation/revision floor. The bounded three-week scan covers a weekly cadence whose DST-gap slot is skipped.

Nonexistent wall-clock times are skipped. Repeated wall-clock times use the later UTC occurrence exactly once. occurrence_id binds a UUID schedule identity, positive revision and canonical UTC slot; alternate timezone representations resolve to the same ID. Captures must retain actual capture/source timestamps separately from the scheduled occurrence. Missed slots are not backdated and no catch-up backlog is invented.

14 new tests verify New York spring/fall offsets, weekend skipping, Hong Kong offsets, DST gap/fold behavior, bounded latest-slot catch-up, creation floors, stable IDs and invalid inputs. Full API/worker suite: 475 tests pass. JavaScript unchanged from the 138-test checkpoint. No database or provider write and no website action occurred.

## Evidence-driven integration decisions

The current /api/jobs/active endpoint returns ordinary job payloads publicly; it is not an acceptable transport for private screen definitions. Current legacy screen_captures also use shared deployment history. Monitoring therefore needs owner-private schedule, occurrence and result storage rather than inserting private definitions into these public paths.

The existing capture builder enforces complete membership/evidence. Its build and append phases must be separated so scheduled results can use a private publisher without temporarily writing into shared history. Scheduled-result readers and pair reviews must apply the owner scope consistently. The civil-time engine does not itself establish exchange sessions or holidays.

## Remaining build checklist

- [x] Validated civil-time cadence; gap/fold policy; bounded next/latest-slot calculation; stable revision/slot IDs.
- [ ] Add owner-private schedules and occurrence records with RLS/grants and authenticated revision-safe APIs. Preserve legacy shared history explicitly.
- [ ] Atomic bounded dispatch: one durable occurrence per schedule revision/slot; no dispatch before activation floor or after disabling.
- [ ] Fenced claim/renew/finish and bounded retries. Two workers cannot publish twice; disabling/revising prevents obsolete publication; expired worker cannot overwrite successor.
- [ ] Extract complete-capture builder from public append; validate and atomically publish private immutable result. Failure preserves prior success and does not infer exits.
- [ ] Integrate worker dispatch/restart and owner eligibility; no private payloads in the public job feed or shared history.
- [ ] Opt-in per-screen UI: local time/timezone/weekday explanation, next run, running/last success/failure and stop/retry controls. Keep universe refresh cadence separate.
- [ ] Exchange-session/holiday qualification, data-age policy and explicit capture/source-time distinctions.
- [ ] Actual native SQL two-connection/duplicate/restart/failure/stop tests; Auth/PostgREST isolation; desktop/phone, exact history/export and production smoke.

R05/R10/R15 remain open. No schedule has been enabled, no capture automation runs, and no merge/deploy occurred. The pending Supabase advisor approval remains separate; it was not retried or bypassed.

## References checked

Python [ZoneInfo documentation](https://docs.python.org/3/library/zoneinfo.html) confirms IANA and fold behavior; the tests establish this engine's specific policy. Supabase [RLS guide](https://supabase.com/docs/guides/database/postgres/row-level-security) establishes separate grants and row policies for forthcoming private storage. Current changelog and [PostgreSQL minor-release advisory](https://supabase.com/changelog/postgres-15-19-17-11-breaking-changes) were read; no extension/schema change is made here.
