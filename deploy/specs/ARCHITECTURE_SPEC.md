# ARCHITECTURE_SPEC — TradingAgents Portal (v1, 2026-09-26)

Status: DRAFT for owner approval. Companion docs: PRODUCT_SPEC.md, BUILD_SPEC.md,
deploy/supabase/0001_init.sql. Decision log: MEMORY.md.

## 1. System topology

```
                        ┌─────────────────────────────── Render ───────────────────────────┐
                        │                                                                  │
 User ──HTTPS──►  Web Service (portal + API)      Background Worker (inference)   Cron Jobs │
                  Next.js 14 + API routes         Python 3.12:                    02:00 US/East:
                  - auth via Supabase Auth        - FastAPI job runner            - watchlist runs
                  - submit/watch analyses         - consumes jobs queue           - settlement (+5d/+30d)
                  - ledger, history, settings     - TradingAgentsGraph.propagate  - vendor budget sweep
                  - Supabase Realtime subscribe   - moomoo WS quote ingestion     - pg_dump → Storage (Sun)
                                                  │                                         │
                        └──────────────┬──────────┴───────────────┬─────────────────────────┘
                                       │ service-role key          │ mounted disk (10GB)
                                       ▼                           ▼
                        ┌──────────────────────────┐   ┌──────────────────────────┐
                        │ Supabase (us-east)       │   │ /data (scratch, rebuild.)│
                        │ - Postgres (31 tables)   │   │ - vendor cache           │
                        │ - Auth (Google/GitHub)   │   │ - LangGraph checkpoints  │
                        │ - Realtime (job_events)  │   └──────────────────────────┘
                        │ - Storage (run blobs)    │
                        │ - Vault (secrets)        │
                        └──────────────────────────┘
```

Single owner ("just me") for v1: auth is still built (Supabase Auth, one user) so multi-user is a
config change, not a rewrite. RLS on from day one.

## 2. Service responsibilities

| Service | Runtime | Owns | Never does |
|---|---|---|---|
| Portal (web) | Next.js on Render | UI, auth session, submit job, Realtime subscribe, ledger views | LLM calls, vendor keys, signing |
| Worker | Python on Render | job queue consume, propagate(), settlement, moomoo WS+REST ingestion, budget ledger, event emission | serve HTTP (except /health) |
| Cron | Render cron | nightly watchlist, settlement sweep, backup | LLM analysis beyond watchlist |

## 3. Data flow (one analysis)

1. Portal: POST /api/analyses {ticker, date, depth, instructions?} → enqueue `jobs` (idempotency
   key `analysis:{ticker}:{date}:{config_hash}`) → Realtime channel.
2. Worker: `claim_job()` (FOR UPDATE SKIP LOCKED) → create `runs` row → stream LangGraph nodes.
3. Per node: insert `job_events` (stage/status/payload) → Supabase Realtime → portal live view.
4. Analysts fetch via dataflow router (vendor chain §4); every vendor call → `data_fetch_log`.
5. On PM decision: Quality Gate + Report QC run → `agent_reports` + `decisions` (with
   `qc_verdict`, `evidence`) → `memory_entries` pending → settlement rows for each horizon.
6. Raw agent-state JSON → Supabase Storage (`runs.storage_path`, sha256). Reports → markdown tree.
7. Cron settles at +5d/+30d: close prices from `price_bars` (never re-fetch) → alpha vs
   benchmark → `settlements` → Reflector lesson → `memory_entries.resolved`.

## 4. Vendor chain (decided 2026-09-26)

| Category | Primary | Fallback | Notes |
|---|---|---|---|
| Live quotes US/HK | **moomoo WS push** (OAuth, worker-owned) | moomoo REST snapshot → yfinance | 30/min/path budget ledger; HTTP-200 rate_limited handling |
| OHLCV daily US/HK | **moomoo history-kline** (autype recorded) | yfinance | date-windowed paging; PIT-correct |
| OHLCV + quotes ASX | **yfinance** (.AX) | moomoo history (daily, secondary) | AU real-time denied on exploration login; re-probe at Phase 0 |
| Fundamentals | SEC EDGAR (PIT as-filed, keyless) → yfinance | FMP (PIT depth, historical news) | EODHD optional (splits/dividends deep history) |
| News | yfinance + RSS/EDGAR | FMP historical news (backtests) | moomoo find-news = announcements cross-check only |
| Social | StockTwits + Reddit RSS | — | Jev screening optional (TYPESAFE_API_KEY) |
| Macro | FRED (vintage-pinned) | — | stays |
| Prediction | Polymarket | — | stays |
| Dropped | A-share/SG/JP stacks | — | per owner decision |

Rules: moomoo keys (Ed25519 private key) only in worker secrets; TS client `poc/ts/moomoo.ts` is
the protocol reference; Python worker owns all moomoo traffic. No OpenD, ever.

## 5. Worker pipeline additions (from ecosystem survey, Tier-1 adoption)

- **Parallel analysts** (fan-out subgraph, per-branch message channels).
- **Quality Gate node** after analysts: per-report grade A–F (length/sources/numeric claims/
  checklists) → down-weight instruction downstream. Port from SpaceRexxx (Apache-2.0), ~1–2d.
- **Report QC** post-PM: decision-consistency, risk-coverage, unsourced-numbers, scope-violations
  → `qc_verdict` ∈ passed|needs_review|blocked; blocked never enters the ledger as tradeable.
- **AnalystEvidence**: claim→source extraction stored in `decisions.evidence`.
- **Depth presets** fast/standard/deep → rounds/analysts/news windows/reasoning effort.
- **Checkpoint/cancel/heartbeat**: cooperative cancel between chunks; watchdog "thinking…
  (waited Xs)" every 30s, hard-kill at 600s; crash rehydration running→error on boot.
- **Cost metering**: cached/uncached token split, per-tool counts, pre-run estimate, live ticker.
- **TTL vendor cache** (quotes 5m / news 1h / OHLCV 1d / fundamentals 7d) as one choke point.
- **Skill-degradation events**: vendor failure → `job_events` warning + `data_fetch_log`; never silent.

Deferred (Tier-2, on approval): rule-first safety override + evidence chain (zhouxinhao19
re-domain), paper-trading engine (decision→order lineage), chat-with-decisions, A/B diff,
public research feed.

## 6. Supabase schema

`deploy/supabase/0001_init.sql` (31 tables) + additions from this spec:
`decisions.qc_verdict`, `decisions.user_rating/note`, `agent_reports.quality_grade/quality_score`,
`runs.depth_preset/effective_provider/tokens_cached`, `quotes_realtime` + `quote_ticks`
(moomoo WS, de-dup by `sequence`), per-endpoint `vendor_budget_ledger`. Migration 0002 will carry
the deltas; 0001 remains the base.

## 7. Security

- Portal anon key + RLS; worker service-role key only in Render env.
- Provider/vendor keys in `user_secrets` (Vault ref or app-encrypted; masked hints to UI).
- Bearer-token gate + security headers on any non-authed endpoint (DoThatKarma pattern).
- Secret redaction pass before persisting any payload (secret-looking keys scrubbed).
- Disclaimer rendered on every decision artifact ("research/education, not investment advice").

## 8. Environments

| Env | Render | Supabase | Data |
|---|---|---|---|
| dev | local uvicorn/vite | free project | yfinance only, tiny watchlist |
| prod | web + worker + 2 crons | Pro project | full vendor chain |

Deploy via `render.yaml` blueprint (in repo, Phase 0) + Render MCP for management.
