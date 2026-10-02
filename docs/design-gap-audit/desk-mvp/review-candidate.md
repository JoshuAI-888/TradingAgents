# Desktop screener MVP review candidate

3 October 2026. Review scope: US/HK Research Desk → full analysis/KLine → return to the same screen → existing CSV/Excel exports. All 22 preset contracts remain; two RSI presets are visibly unavailable. The candidate is a draft and is not live-data release acceptance.

## Review order

1. Enabled user journey: `web/api/static/index.html`, `research-workspace.js`, `research-workspace.css`, `research-account.js`, plus `desk-mvp.test.cjs` and `screener.test.cjs`. Check permanent Clear, preset second-click reset, market scope, state/scroll retention, loading/recovery, paging and export scope.
2. Source truth: `main.py`, shared quote/context/classification/generation modules, and their tests. Check exact canonical identity, quote sentinel/timezone/color fixes, authoritative provider membership versus display snapshots, normalized outside-cohort classifications, pagination metadata validation and generation fencing.
3. Operations: the new portal/worker CI job, `render.yaml`, required migration files and [ordered cutover](mvp-cutover.md). Blueprint changes and migrations are prepared, not activated. Do not apply the full historical migration directory.
4. Evidence: [lint/runtime regressions](lint-release-check.md), [source chart/header](responsiveness/public-quote-header-check.md), [actual fixture downloads](downloads/README.md), [representative public-cohort responsiveness](responsiveness/real-cohort-check.md), [public market recheck](public-market-release-recheck.json).

The branch also preserves earlier Explorer/Changes/private capture/review/schedule foundations. They remain deferred and hidden by the default MVP flag. Their existence in the source or candidate is not a claim that these flows are enabled, qualified, or required for MVP acceptance. Historical evidence and migration files are retained for recoverability; the migration runbook distinguishes required and conditional dependencies.

Strict lint cleanup is broad because the committed portal/worker baseline also failed the existing gate. Use whitespace-ignoring diffs for formatted Python, then review import, callback/fixture and control-flow changes against the regression evidence. The original preset catalog is independently compared against captured definitions. Static layout and public provider values are not changed by lint cleanup.

## Current acceptance

Local checks pass: strict Ruff, clean Python 3.12 engine/CLI imports, 787 API/worker tests, 1,008 root tests plus 91 subtests (two documented skips), 189 UI contracts, preset definition equality and diff whitespace. Native combined migration rehearsal passes against synthetic PostgreSQL 16 tables.

The required remaining gates are live US/HK raw/normalized classification and source coverage; all 20 supported preset membership/sorts; bounded like-for-like Moomoo sanity checks; target-platform migration/advisor/history reconciliation; exact candidate deployment, actual production downloads, analyst-journey timing and rollback smoke checks. The latest public HK full-market response still has zero rows and no clock. These gaps prevent a ready-for-investment-team or safe-to-merge claim.

Newer [live Moomoo source evidence](moomoo-browser/README.md) verifies complete raw provider membership and order for 17/20 working US presets. All four large provider cursor chains terminate with stable totals and no duplicate identities after one explicit rate-limit retry. Three website traversals change declared totals and duplicate boundary rows, so they remain unqualified as immutable source snapshots despite all captured identities occurring in the API chains. Website US total 12,141 versus stored default 12,045 and HK website 2,825 versus empty stored HK remain unresolved. This narrows the source gate; it does not close classification, HK, quote precision/freshness or candidate-hosted UX acceptance.

No production database mutation, writer/collector flag activation, merge or deployment is authorized by this artifact itself. Existing human authorization to merge/deploy remains subject to completing these release checks.

[Provider page recovery](responsiveness/provider-page-recovery/README.md) now rejects overlapping or inconsistent continuation pages and retains rows/cursors on failure. Synthetic browser retries, both default-reset paths and actual retained-match CSV downloads pass. This is an enabled Desk correction, not an optional feature activation or a live-data gate closure.
