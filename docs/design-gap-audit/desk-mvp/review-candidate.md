# US/HK desktop screener MVP acceptance

3 October 2026 UTC / 4 October New Zealand. Scope: Research Desk → full analysis/KLine → Back → existing CSV/Excel exports. All 22 original preset definitions remain: 20 supported and two RSI definitions visible as unavailable. Explorer, Changes, scheduled captures and new team features remain deferred.

## Verified production data

| Market | Raw Moomoo screen cohort | Qualified stocks | Excluded ETFs | Unresolved | Published generation |
|---|---:|---:|---:|---:|---|
| US | 9,421 | 9,420 | 1 | 0 | `4165c77d-f6f6-4213-bff9-4095557ebe51` |
| HK | 2,825 | 2,825 | 0 | 0 | `67d0e784-6c0f-41e3-a282-095185e7370e` |

The source scope is an exhausted provider market screen, not a complete exchange/ETF catalog. Fresh Moomoo website aggregate counts agree; the top 12 cap-descending rows in each market match symbol, name, price, change and rounded cap. No complete website membership equality is claimed. All 171 ambiguous trust/fund subtypes have same-response Yahoo evidence: US 159 equities / one ETF (SCOP), HK 11 equities. Prologis is retained; US Blue Chip shows 39 qualified members, matching 39 provider members.

Actual production CSV and SpreadsheetML `.xls` downloads passed for page 500, all available (US 9,420 / HK 2,825) and selected 2. Every CSV/Excel field agrees; identities, order and numeric price/change/cap/PE/volume agree with the pinned API cohort. Existing formula escaping and scope controls remain covered by regression tests. Native XLSX remains optional.

Currency attribution is unavailable in these quote rows, including HK RMB counters. UI `cur?` and export `Unavailable` are intentional. Cache publication is separate from provider snapshot updates; a fresh weekend cache is not fresh trading. Financial periods, delay/session/adjustment and missing advanced factors remain unverified instead of inferred.

## Verified analyst journey

All 20 preset buttons in each market apply their declared sorting, keep Clear reachable and toggle back to stock-only market-cap descending. Two RSI presets remain disabled. The all-stocks reset works. HK page 2 → ticker 01783 → full research / 3M KLine → Back restores page 2, selected tickers and the Type column. US NVDA / HK Tencent full research retains seven research tabs, six financial subtabs and existing KLine periods, studies, drawing tools and fullscreen. The column chooser retains every column and saved layout, and discloses supplied counts in loaded results; field presence does not qualify currency or period.

Cold market switching exposed a ready-table wait on unrelated side panels. A regression reproduces HK→US→HK with a held panel request; the correction lets quote results render independently and ignores late other-market responses. Immutable generation contents now retain a bounded process cache; every request still resolves its current pointer and new generations revalidate. Final served-candidate browser/timing checks must confirm these corrections after deployment.

## Operations and release

Seven focused migrations are applied; service access and browser denials are verified. Uploads are bounded 400-row batches, final publication is atomic, and stale owners are fenced. A fixed 500 MiB admission budget stops new refreshes before provider acquisition when generation/staging storage reaches its threshold. It preserves all evidence and the last good cohort; it is not a hard quota or retention policy.

MVP cadence is daily HK/US after close on existing services; subtype collection shares the post-close enrichment router. A bounded streaming backup includes generation, staging, lease and subtype dependencies. REST backups are explicitly nontransactional; consistent recovery requires coordinating writers. Archive and retention is a follow-up before indefinite growth or hourly cadence. Do not delete immutable evidence as an unreviewed cleanup.

Local integrated checks: 862 backend tests, 197 UI tests, strict Ruff and native PostgreSQL publication, role, replay and capacity contracts passed before the final cache correction. Exact-candidate CI, merge and built cron/runtime acceptance remain to be recorded after final integration. Historical evidence under this folder stays dated; older empty-HK and legacy counts do not describe current production.

Private receipts live outside Git in the workspace release-cutover directory. [Ordered migration/recovery runbook](mvp-cutover.md), [MVP checklist](../../../screener-mvp-delivery-plan.md), [Capacity limitations](../../../screener-refresh-capacity-guard.md).
