# PRODUCT_SPEC — TradingAgents Portal (v1, 2026-09-26)

Status: DRAFT for owner approval. Owner: single user (joshuaifang). Positioning: **personal
research cockpit that proposes trades with auditable reasons, keeps an honest track record, and
backtests decision quality.** Not investment advice; not an execution system.

## 1. Jobs to be done

1. "Should I look at X today, and why?" — propose an action with reasoning I can audit.
2. "Was the system right?" — every proposal settled against realized returns, visible as a ledger.
3. "What's moving right now?" — live watchlist prices (moomoo push) + daily digest.
4. "Does it decide well?" — backtest decision quality over history (upstream run_backtest + our QC).

## 2. Users & non-goals

- **User**: single owner (v1). Auth exists from day one so v2 = invite users.
- **Non-goals v1**: order placement/broker execution, A-share/SG/JP markets, multi-tenant
  billing, mobile apps, real-time alerts beyond daily digest/email.

## 3. Feature list (priority-ordered)

### P0 — MVP (Phase 0–1)
| # | Feature | Detail |
|---|---|---|
| 0 | **Home: Market Pulse** | Landing screen (mockup: `deploy/mockups/portal_home_mockup.html`). (a) Market state: index/sector strip via ONE moomoo batch snapshot (SPY/QQQ/IWM + 11 SPDR sector ETFs + VIX proxy; US10Y/FRED; HSI moomoo; ASX200 yfinance) + WS push. (b) Biggest movers via moomoo `stock-screen` server-side sort (gainers/losers/volume-surge; 3 calls/sweep; US+HK; ASX via yfinance). (c) **Analysis candidates** trigger feed — SCREEN hits, NEWS (find-news + EDGAR + RSS), EARNINGS (yfinance/FMP; moomoo earnings calendar is OpenD-only), MACRO (moomoo econ-calendar + FRED + Polymarket deltas), WATCHLIST nightly sweep — each with a stated reason, score, one-click Run at preset depth, deduped against today's runs/ledger. Discovery sweep ~7 moomoo calls/15min (within 30/min budget); nothing auto-runs except the watchlist. (d) Next-5-sessions calendar strip. |
| 1 | Submit analysis | ticker (US/ASX/HK), date, depth preset, optional custom instructions |
| 2 | Live trading floor | per-agent streaming progress (Supabase Realtime), debate bubbles, cost ticker |
| 3 | Decision card | 5-tier rating, thesis (3 bullets), strongest bull vs bear argument, price target, entry/stop, conviction, QC verdict chip, provenance footer |
| 4 | Decision ledger | all decisions + settled raw return / alpha (5d, 30d) vs benchmark; auto-rating vs my rating + notes |
| 5 | Watchlist + nightly runs | cron executes watchlist, email digest of decisions + reasoning summaries |
| 6 | Settings | provider + quick/deep models, depth default, horizons, BYO vendor keys (masked) |

### P1 — Trust & depth (Phase 2)
7. Full reasoning-chain drill-down (every report, debate transcript, evidence claims→sources).
8. Backtest lab v1 (upstream `run_backtest` grid + our QC + equity curve of decisions).
9. Cost dashboard (per run/day/model; cached vs uncached tokens).
10. Data-health page (vendor success %, p95 latency, budget ledger, degradation events).

### P2 — Differentiators (Phase 3+, on approval)
11. Rule-first safety override + evidence chain (zhouxinhao19 port).
12. Paper-trading engine (decision→simulated order→settlement lineage).
13. Chat with decisions (interrogate stored runs, grounded answers).
14. A/B run diff; public research feed.

## 4. Key UX flows

### Analyze (the "trading floor")
Submit → pipeline visualization lights up per stage (4 analysts parallel → quality gate →
bull/bear rounds → research manager → trader → risk debate → PM) with live tokens/cost; each
finished section renders as markdown in a side pane; heartbeat message if a stage stalls >30s;
Stop cancels cooperatively. Final: decision card slides in.

### Decision card (the product's atom)
Rating badge (BUY/OVERWEIGHT/HOLD/UNDERWEIGHT/SELL or REVIEW) · thesis bullets · bull-vs-bear
strongest arguments side-by-side · price target + entry/stop + horizon · conviction ·
**QC verdict chip** (passed / needs-review / blocked) · provenance footer (models, depth,
tokens, cost, elapsed, data freshness) · buttons: full reasoning chain, export PDF, rate
thumbs-up/down + note.

### Ledger (the trust surface)
Rows: date · ticker · rating · my rating · 5d return/alpha · 30d return/alpha · QC · status
(settled/pending). Header stats: hit-rate by direction, cumulative alpha, avg cost/decision.
Blocked/REVIEW decisions visibly excluded from stats.

### Digest
Morning email: overnight decisions (rating + 3-bullet why), watchlist quotes, open-position
settlements that matured, data-health note.

## 5. Decision rules the product must honor

1. `REVIEW`/blocked decisions never count toward performance stats (honest ledger).
2. Every number in the UI traceable to a stored artifact (report, evidence, settlement).
3. Backtest results labeled as backtests; forward ledger visually dominant over backtests.
4. Cost shown before and during every run; pre-run estimate when depth/model known.
5. Disclaimers on decision cards, PDFs, digest.

## 6. Acceptance for v1 (walk-through test)

Submit NVDA → watch floor stream to completion <10 min on cheap mode → decision card shows QC
verdict + provenance → next morning digest arrives → +5d later ledger shows settled alpha →
Backtest lab runs a 20-cell grid on cheap mode without manual intervention.

## 7. Screens (mockup)

Single HTML mockup with the four v1 screens: `deploy/mockups/portal_mockup.html`
(trading floor · decision card · ledger · settings). Approved mockup becomes the shadcn/ui
component contract.
