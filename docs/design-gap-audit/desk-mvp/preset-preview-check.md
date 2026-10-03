# Preset preview rule integrity

3 October 2026. Found an existing `/api/screener/presets` preview defect: `_apply_filters(..., strict=False)` silently skipped absent fields, while Penny Stocks substituted a daily turnover floor for its saved 30-day average-volume rule. Tests previously asserted that approximation and included an unsupported claim of Moomoo parity.

Removed both approximations. A preview requires every stored criterion value and refuses flat fields for contextual day/period/term/plate rules. Missing/contextual criteria return no top candidates plus explicit `preview_status`, `preview_missing_fields` and reason. Numeric local previews remain labeled `local_snapshot`, without claiming provider membership. Empty cohorts are unavailable rather than confirmed zero matches. Eligible stock labels and each preset's declared sort/direction are preserved.

All 22 original definitions, bounds and provider execution rules remain unchanged. Provider execution continues to be the route for supported presets; the two RSI definitions remain preserved and unavailable. The enabled Desk requests definitions only, so this correction does not introduce extra rail requests or add latency to its main journey.

The [offline full-cohort reconciliation](preset-preview-reconciliation.json) uses all 12,045 captured public US rows and records their response SHA-256. Twenty presets lack sufficient snapshot evidence for previews; P/B < 1 and Junk Stocks can have descriptive local numeric candidates. This is not a conclusion that 20 provider executions are unavailable. It is also not independent classification, financial-period or Moomoo parity qualification.

Regression evidence: **775 API/worker tests pass**. Tests cover missing financial rules, daily volume not proving a 30-day average, sector scope, preserved filter definitions, declared ascending sorting, missing row values and ETF exclusion. No provider/database calls were made by the offline reconciliation. Earlier 186 UI tests remain the latest static checkpoint; this correction changes only backend preview handling.

Release gates remain open for live US/HK classified cohorts, all 20 supported provider preset results and sorts, source reconciliation, minimal migration/cutover and exact-candidate merge/deploy/smoke checks.
