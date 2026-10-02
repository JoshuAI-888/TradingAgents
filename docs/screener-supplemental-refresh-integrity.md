# Supplemental refresh integrity checkpoint

2 October 2026. Partial R02/D01 progress. No migration, production refresh, live-provider coverage or release acceptance is claimed.

## Problem and resulting behaviour

The nightly worker merged a successful fundamental response into previously stored fields and stamped the merged category with the current run time. If a provider stopped returning forward P/E or sector, an unrelated fresh beta could make the old value look current. A successful empty response was also indistinguishable from no response. This undermines factor eligibility and the proposed company/peer UX.

Successful per-company retrieval now replaces the registered fundamental category, including removal of absent fields, and retains the response's actual retrieval clock. Successful empty dictionaries clear prior fundamentals. Failed ticker/transport responses are absent and retain prior fields with their old fundamental clock. Technical computation keeps its own category/time and continues independently. Wrong-market, unrequested-code, missing/naive/future-clock responses cannot renew the category. Request identity lookup is bounded by a set rather than a quadratic scan.

The yfinance fetcher excludes boolean/nonfinite numeric values and blank/structured classifications, preserves real zero and timestamps each successfully retrieved company separately. It reports an empty successful dictionary explicitly. Existing optional import and per-ticker failure isolation remain.

The API now shares the worker's factor availability registry, with the existing derived LT-debt field included explicitly. Registered fresh supplemental fields fill absent/null values without replacing valid zero or quote values. Unknown keys cannot inject identity/generation/observation metadata. Each filled field records yfinance or computed-technical origin and its retrieval/computation clock; an absent quote observation is removed rather than relabelled as supplemental financial evidence. Reporting periods and currency remain unverified and are not inferred from retrieval time.

## Verification

**388 API/worker tests passed** (`PYTHONPATH=web/api:web/worker /private/tmp/tradingagent-ui-venv/bin/python3 -m pytest web/api/tests web/worker/tests -q`). Added cases cover:

- Successful replacement removes disappeared P/E, sector and derived debt; zero beta remains; technical values/clocks cannot be supplied through a fundamental response.
- Failed fetch plus a fresh technical update retains the old fundamental clock.
- Successful empty response clears fundamentals while technicals remain.
- Market/identity/clock rejection and nonfinite/boolean/structured-value rejection.
- Actual nightly output passed through the actual screener API: absent forward P/E cannot satisfy a filter; remaining zero beta has the original fetch clock.
- Null fill, existing-zero preservation, metadata rejection, independent category TTLs and registry parity.

The UI did not change in this packet. Its previous 87-test checkpoint remains historical. All 22 preset definitions are retained by the full API preservation test. No graphical screenshot is used to prove financial reliability.

## Remaining investment-grade requirements

This fixes refresh integrity, not factor qualification. Fresh live samples, canonical Yahoo/share-class mapping, per-field coverage, actual period/currency/session/adjustment contracts, cross-provider derived-ratio currency consistency, supplemental cohort versioning/capture reproducibility, groups aggregation freshness/currency and qualified peer ranks remain open. Enable the original mockup's advanced axes, bubbles and causal labels only after those contracts are verified. Full API/worker suite success is development evidence; real Auth/PostgREST/migration/rollback, Moomoo reconciliation, device/performance and production release gates remain open.
