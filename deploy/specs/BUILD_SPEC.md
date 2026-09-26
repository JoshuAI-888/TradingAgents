# BUILD_SPEC — Phases, Test Loop, Deployment, Checklist (v1, 2026-09-26)

Status: DRAFT for owner approval. Execution: ZCode runs the loop directly (no orchestration
skill needed): write → pytest → fix → deploy (Render MCP) → verify (web-gui-tester).

## 0. Working agreements

- Engine stays stock upstream 0.5.1; all product code in `web/` (worker+api) and `webui/`
  (portal). No edits inside `tradingagents/` except additive vendors under
  `tradingagents/dataflows/vendors/` (upstream-style) — keeps upstream merges cheap.
- Every phase ends green: pytest passing, deploy healthy, checklist items ticked in this file.
- All code Apache-2.0-compatible; attribute SpaceRexxx/BSTester/TheLocalLab ports in NOTICE.

## 1. Phases & work breakdown

### Phase 0 — Skeleton on Render (~1 wk)
| # | Task | Done when |
|---|---|---|
| 0.1 | Apply Supabase migration 0001 (+0002 deltas: qc_verdict, quality_grade, depth_preset, quotes_realtime, vendor_budget_ledger) | tables + RLS live |
| 0.2 | `web/worker`: FastAPI entry, job consumer (claim_job loop), stub runner, event emitter | unit tests pass offline (stub graph) |
| 0.3 | `web/api`: submit/status/history endpoints on Supabase | curl round-trip green |
| 0.4 | render.yaml (web + worker + 2 crons + disk) deployed via Render MCP | both services healthy |
| 0.5 | Secrets: LLM key + Supabase service key in Render env; masked keys in user_secrets | probe script passes |
| 0.6 | moomoo read-only probe with owner keys (tier, per-endpoint limits, ASX entitlement) | results → REVIEW.md |

### Phase 1 — Product slice (~2–3 wks)
| # | Task | Done when |
|---|---|---|
| 1.1 | Wire real runner: propagate() + parallel analysts + depth presets + cost metering | 1 real run end-to-end |
| 1.2 | Realtime floor: job_events → portal live pipeline UI (mockup-faithful) | stream visible <2s lag |
| 1.3 | Decision card + QC (quality gate port + report_qc port) + provenance footer | card matches mockup |
| 1.4 | Ledger + settlement cron (+5d/+30d) + memory_entries reflection | settled alpha appears |
| 1.5 | Watchlist + nightly cron + email digest | digest received |
| 1.6 | Settings screen (models, depth, keys) | settings persist + take effect |
| 1.7 | PDF export + disclaimers | PDF carries provenance footer |

### Phase 2 — Trust & depth (~2–3 wks)
moomoo WS ingestion worker → quotes_realtime/ticks; FMP vendor (PIT fundamentals + historical
news); data-health page; cost dashboard; backtest lab v1 (run_backtest grid UI); TTL vendor
cache; skill-degradation events.

### Phase 3 — Differentiators (on approval)
Safety-override + evidence chain port; paper-trading engine; chat-with-decisions; A/B diff;
public feed.

## 2. API surface (v1)

```
POST /api/analyses            {ticker, trade_date, depth, instructions?} → {job_id}
GET  /api/analyses/{job}      status + progress snapshot (REST hydration channel)
GET  /api/analyses/{job}/events  (Realtime preferred; SSE fallback w/ snapshot-on-join)
GET  /api/decisions           ledger (filter: ticker, status, horizon)
GET  /api/decisions/{id}      full card payload (reports, debates, evidence, settlement)
GET  /api/decisions/{id}/report.md | /report.pdf
PATCH /api/decisions/{id}     {user_rating, note}
GET  /api/settings | PUT      models, depth, horizons, vendors
POST /api/secrets             vendor keys (masked read-back)
GET  /api/health
```

## 3. Test & build loop (the loop itself)

1. **Unit** (pytest, offline): stub-graph discipline from DoThatKarma ADR 0003 — fake
   TradingAgentsGraph, no network, no keys. Suites per module (queue, runner, events, QC,
   settlement math, budget ledger). Target: worker+api ≥85% on business logic.
2. **Contract**: SQL schema tests (migrations apply twice idempotently; RLS denies cross-user);
   API contract tests against a disposable Supabase branch.
3. **E2E local**: docker-compose (worker+api+stub) → submit NVDA → assert decision row + events.
4. **GUI black-box**: browser-use:web-gui-tester against the deployed portal after each UI
   phase — scripted flows from PRODUCT_SPEC §6 acceptance.
5. **Deploy gate**: Render MCP deploy → /health green → run 3. and 4. against prod → only then
   tick checklist.
6. **Fix loop**: any red = fix → rerun from step 1 → no checklist ticks on red.

## 4. Definition of Done — master checklist

**Phase 0**
- [ ] Supabase 0001+0002 applied, RLS verified
- [ ] Worker consumes jobs; stub E2E green offline
- [ ] API round-trip green; secrets configured
- [ ] render.yaml deployed; both services healthy; crons scheduled
- [ ] moomoo probe results recorded

**Phase 1**
- [ ] Real NVDA run end-to-end <10 min (cheap mode)
- [ ] Live floor streams all stages; cancel works; heartbeat shows on stall
- [ ] Decision card = approved mockup incl. QC chip + provenance
- [ ] Ledger settles at +5d/+30d with correct alpha math (unit-proven)
- [ ] Nightly watchlist cron + email digest received
- [ ] Settings persist and change run behavior
- [ ] PDF export with disclaimers

**Phase 2**
- [ ] moomoo WS quotes land in quotes_realtime (<2s end-to-end)
- [ ] FMP historical news PIT-verified on a known date
- [ ] Backtest grid (20 cells) completes unattended; equity curve renders
- [ ] Data-health page reflects induced vendor failure (degradation event visible)

**Ongoing**
- [ ] pytest green on every push (CI: ruff + pytest, py3.12)
- [ ] Upstream merge still clean (no engine edits outside vendors/)
- [ ] NOTICE attribution present

## 5. Risks & rollbacks

- Vendor flake → degradation events + fallback chain; ledger marks insufficient_data, never
  fabricates.
- Cost overrun → depth presets + pre-run estimate + monthly budget alert in digest.
- Upstream drift → vendor-only edit rule + weekly upstream-sync check (zhouxinhao19's CI idea).
- Rollback = Render previous deploy (one click via MCP); migrations are additive-only in 0.x.
