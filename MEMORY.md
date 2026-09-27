# Project Memory & Decision Log

Working decisions for the TradingAgents deployment product (portal + worker on Render).
Newest decisions first. Each entry: context → decision → implications.

---

## 2026-09-27 — Portal aligned to approved v2 mockup (report dossier shipped)

**Gap closure** (owner: "compare to mockup, fix gaps"): the live portal showed only
stage chips + tables; the approved v2 institutional workstation is now implemented:
- **Report dossier** (`Report` from any ledger/candidate row, keyed by job or decision
  id): verdict masthead (rating/conviction/QC/cached-tokens pills, live close + chg,
  fundamentals KV, PT/stop/size/horizon, settlements), S/R rail (floor pivots from the
  latest bar + entry zone/stop from the decision), **interactive canvas chart ported
  from the mockup** (candles, EMA20/50, WMA20, BOLL(20,2), S/R + entry overlay; lower
  panels Volume/RSI(14)/MACD DIF·DEA·HIST/KDJ/ATR/CCI; TF 1M/3M/6M/1Y/2Y; crosshair
  OHLCV+indicator readout), thesis panel, **news with citable links**, agent outputs
  accordion (all reports + both debate transcripts, unedited), live reasoning trace,
  ops rail (elapsed/models/tokens cached bar/cost/config sha/provenance), 👍/👎 review
  (POST /api/decisions/{id}/review → decisions.user_rating).
- **Worker post-run enrichment** (`enrich.py`, best-effort, logged to data_fetch_log):
  1y daily bars → price_bars, headlines with URLs → news_items (handles old+new
  yfinance shapes), profile KV → company_profiles. Verified: 251 bars + 10 news +
  profile per ticker. Local runs need SSL_CERT_FILE=$(python -m certifi) on this Mac.
- **APIs**: /api/analyses/{ref}/report (job or decision ref), /api/bars/{symbol},
  /api/news/{symbol}, /api/fundamentals/{symbol}, review endpoint, /api/meta now
  carries spend {runs, cost_usd, tokens}.
- **Deferred (needs Phase-1 structured outputs)**: evidence register, scenario table,
  catalyst/risk/assumption classification of news, quality-gate grades per agent.
- **Signal-domain fix**: engine emits 5-tier ratings as signal ('overweight') →
  decisions.signal check violation. Fixed in worker (`_signal_slug`) AND at the DB
  boundary (migration 0005 normalize_decision_signal trigger) so any in-flight worker
  version persists cleanly. Both real runs (NVDA fast, RKLB deep) hit this at persist.
- Deploy discipline learned: ANY push redeploys worker+portal and kills in-flight runs
  (rehydrate requeues, but attempts are finite) — batch pushes; verify no job running.

## 2026-09-27 — Runtime toggle + discovery refresh + real-run fixes (owner feedback round)

**Owner feedback** (jobs failing, Sunday staleness, stub mode questions) → shipped:
- **Stub-mode toggle** (Settings → Runtime): `app_settings` key `runtime` =
  `{"stub": bool}` is the authoritative flag; `get_runtime_flags(db)` resolves
  DB → WORKER_STUB_MODE env → default true. Worker picks StubRunner vs EngineRunner
  **per run** (`RuntimeRunner`) — no redeploy needed to flip. Portal env
  WORKER_STUB_MODE=0 on both services now. Health endpoint reports the live flag.
  Stub mode = deterministic offline pipeline (zero LLM cost) for smoke-testing.
- **Market Pulse refresh button** ("↻ Refresh now") → POST /api/candidates/refresh
  runs `discovery.sweep()` inline (moomoo when keys present, watchlist always).
  Discovery cron stays weekday market-hours ("*/15 13-21 * * 1-5") — manual refresh
  covers weekends/after-hours.
- **Real-run crash fixed**: upstream 0.5.1 debate history entries are plain strings
  (not dicts) → `'str' object has no attribute 'get'` in EngineRunner report joins →
  `_join_history` accepts str|dict.
- **Deploy-kill resilience**: `rehydrate_crashed` now requeues deploy-killed runs
  (requeue_job RPC decides pending vs failed by attempts) instead of failing them.
  ⚠ Every worker deploy restarts in-flight runs — expect re-runs after pushes.

**Job forensics for owner**: 75717894 (RKLB deep) failed = claimed by the old worker
seconds before the stage-map fix went live (deploy-swap race; reset after 'live' from
now on). 18abaadb (RKLB standard) actually succeeded — UI had shown its earlier failed
state. NVDA first real run burned ~$0.04 across two attempts before the join fix.

**Model pair note**: owner switched deep model to openai/gpt-6-luna via Settings —
deep runs get pricier (research manager + PM on the premium model). Toggle back in
Settings → Models if cost matters.

---

## 2026-09-27 — DEPLOYED & VERIFIED end-to-end (Supabase + Render, Virginia)

**Live URLs**: portal https://tradingagents-portal.onrender.com · worker https://tradingagents-worker.onrender.com

**Credentials**: owner supplied the Supabase `sb_secret_…` service key from the dashboard
(hosted MCP exposes only publishable keys; no legacy jwt_secret GUC reachable via SQL on
new projects). Set as SUPABASE_SERVICE_KEY on all 4 services. Never printed/committed.

**Supabase**: project `tradingagents`, ref `hiqasyjalspuchtacatk`, us-east-1, $10/mo
(owner cost-confirmed). Migrations 0001→0002→0003 applied, then **0004 seed_owner_identity**:
profiles.id FKs auth.users, so Phase 0's single owner is a deterministic auth row
(uuid5(URL, 'tradingagents-owner:joshuaifang@gmail.com') = `414d1831-84ed-520c-a2a7-a093f19a2cde`,
joshuaifang@gmail.com, timezone Pacific/Auckland). Portal defaults unauthenticated
submissions to it via DEFAULT_USER_ID env; when real auth lands, retire the default.

**Render services** (region virginia, branch product/portal-phase0, autoDeploy):
- portal `srv-das1tjbncjis73fi131g` (web/starter) — env: SUPABASE_URL, SUPABASE_SERVICE_KEY,
  DEFAULT_USER_ID, CRON_SECRET, WORKER_STUB_MODE=1(portal flag only), OPENROUTER_API_KEY
- worker `srv-das1tngu01pc73ebb7sg` (web/starter; MCP can't create bg-workers/disks →
  PORT-gated /healthz thread + /tmp cache dirs) — WORKER_STUB_MODE **0** since 2026-09-27
- settlement cron `crn-das1to7avr4c738m2bog` "30 * * * *" · discovery cron
  `crn-das1tojbc2fs7390e32g` "*/15 13-21 * * 1-5" (both: SUPABASE_URL/KEY; moomoo keys
  still absent → discovery runs watchlist-only until probe)

**First-run bugs fixed** (all pushed; 18 tests green):
1. Migration create-order for real Postgres: SQL-language fns validate table refs at
   create time (enqueue_job after jobs); FK targets must exist (tickers first).
2. Portal couldn't import tradingagents_worker (not pip-installed) → path bootstrap in
   tradingagents_api/__init__.
3. claim_job returns a null composite when the queue is empty; PostgREST serialized it
   as {} (no id) → worker crashed → guard: id-less claims treated as no job.
4. Runner stages (analysts/research_debate/risk_debate) violate agent_reports_stage_check
   → mapping in persist_run: analysts→analyst_market; debates → debate_messages
   (speaker neutral, round 1).
5. Render MCP gotchas: no rootDir (commands `cd` from repo root), no bg-worker/disk
   types, web-service health = TCP-only (worker binds $PORT), env updates auto-redeploy.
   ⚠ Deploy-swap race: reset queued jobs only AFTER the fixed deploy reports `live`.

**Verification**: stub end-to-end green via live API (AAPL fast + owner-submitted RKLB
standard): job succeeded, QC events, decision in v_decision_ledger, settlements pending
(5d/30d). WORKER_STUB_MODE flipped to 0 — first real GLM-5.3-flash run pending at write
time (≈$0.14/decision).

---

## 2026-09-27 — Phase 0 BUILT and pushed (`product/portal-phase0`)

**Built** (branch `product/portal-phase0`, commit 277b30b):
- `web/worker` — Supabase queue consumer (`claim_job` RPC / SKIP LOCKED), StubRunner
  (offline deterministic) + EngineRunner (0.5.1 `propagate()`), job_events emitter,
  settlement ledger (+5d/+30d alpha from `price_bars` — never live fetches),
  discovery engine (screens/news/calendar/watchlist → `discovery_candidates`),
  moomoo cloud-REST client (Ed25519 signing, path-template budget 30/min, HTTP-200
  rate_limited handling), TTL vendor cache, crash rehydration.
- `web/api` — FastAPI: idempotent enqueue, live job status, decision ledger,
  candidates queueing (cron-gated), health/meta; serves the portal SPA.
- `web/api/static` — portal v0 (Market Pulse candidates, live floor, ledger, system page).
- `deploy/supabase/0002_product_deltas.sql` — qc_verdict/user_rating/evidence,
  quality grades, runs preset/token split, quotes_realtime+quote_ticks,
  vendor_budget_ledger, discovery_candidates, requeue RPC.
- `render.yaml` — web + worker(10GB disk) + settlement/discovery crons.
- **Tests: 13/13 green** (offline: fake Supabase + stub graph, no network/keys).

**Deliberately NOT done yet** (blocked on owner): Supabase project + creds, LLM key,
Render service creation (services would crash-loop without SUPABASE_URL — created only
when creds land), moomoo probe run (needs keys), real-run smoke, price-bars backfill.

**Open design items for Phase 1**: node-level streaming (floor currently coarse-grained),
moomoo WS ingestion worker, FMP vendor, "diff-first" ledger view, degraded-state UI.

---

## 2026-09-26 — Data source: moomoo OpenAPI added as live-quote + US/HK OHLCV vendor

**Context.** Private repo `JoshuAI-888/moomoo-api` (branch `claude/moomoo-api-exploration-dvyz2n`)
contains a verified exploration: 62/62 read-only quote endpoints live-verified, OAuth WebSocket
push measured at 65–77 ms p50, REST rate limit 30 req/min per path-template, cloud REST requires
no OpenD gateway. Full review: `ecosystem-survey/moomoo-api/REVIEW.md`.

**Decision.** Add moomoo to the vendor chain as: (1) primary live-quote/push vendor (WS, OAuth)
for US/HK watchlists — replaces yfinance polling for the portal; (2) primary US/HK intraday +
daily OHLCV and valuation/consensus source (REST, AppKey Ed25519, nightly batch with a
per-path-template budget ledger). Keep yfinance as fallback + for denied markets (AU/CA/SG/JP
real-time, NZX). FMP/EODHD still required for PIT fundamentals depth, full-text news; FRED and
Polymarket unchanged. Do NOT deploy OpenD on Render (native binary, SMS login, quote-right
kicking) — skip OpenD-only datasets.

**Implications.** One ingestion worker owns moomoo (WS long-lived + REST batch); TS client
`poc/ts/moomoo.ts` is a viable canonical client; Ed25519 private key only in worker secrets;
HTTP-200 `rate_limited` + `Retry-After` handled everywhere; Supabase gains `quotes_realtime`,
ticks (de-dup by `sequence`), `bars_1d/1m` with `autype`, valuation/short-interest tables.
Risks: redistribution licensing for multi-user display (Morningstar content third-party),
promotional tier withdrawable, single-account rate limits shared prod/dev/backtests.

**Owner resolutions (2026-09-26).** Markets = **US + ASX + HK** (no A-shares/SG/JP; skip A-share
vendor stacks). Single user → redistribution risk moot; retail tier, no professional
classification. **No OpenD** — cloud REST/WS proven sufficient. Python worker owns moomoo;
`poc/ts/moomoo.ts` = protocol reference. ASX real-time was denied on the exploration login →
yfinance primary for ASX, moomoo ASX daily history secondary; probe owner's account entitlement
at Phase 0. Proof status split (measured vs docs-assumed) in REVIEW.md.

---

## 2026-09-26 — zhouxinhao19 frontend permission granted (was PROPRIETARY)

Owner reports direct permission from zhouxinhao19 to use any part of TradingAgent-Future's
`frontend/` previously labelled proprietary. Treat as reusable (EvidenceChain UI, dashboards,
settings dialogs — Vue 3 + Element Plus, Chinese-language; selective reuse into our Next.js
portal). TODO before commercial shipment: obtain the grant in writing (LICENSE change or note
in their repo). Recorded in `ecosystem-survey/SYNTHESIS.md` header.

---

## 2026-09-26 — Upstream sync to v0.5.1; plan impact assessment

**Context.** Fork synced with TauricResearch upstream: 103 commits, releases v0.5.0 (2026-09-18)
and v0.5.1 (2026-09-24). Framework restructured (breaking import-path changes).

**What's new and adopted.**
- **SEC EDGAR fundamentals vendor (keyless, as-filed).** US statements served point-in-time:
  unfiled periods withheld, restatements read as first reported. Fundamentals PIT gap closed
  for US filers at zero cost — strengthen than our planned FMP fundamentals path; FMP/EODHD
  remain for prices + historical news.
- **Native backtesting.** `tradingagents/backtest.py`: `run_backtest` over a ticker×date grid,
  `summarize` scores settled cells (direction-aware: a Sell that fell is a hit), CLI
  `tradingagents backtest --run-id` resume. Phase 3 "Backtest Lab" engine is now upstream —
  we productize (batch jobs on the worker, equity-curve UI) instead of building the engine.
  Explicitly a decision-quality evaluator, NOT a portfolio simulator — keep that framing in UI.
- **Portfolio context.** `propagate(..., portfolio=...)` / `PortfolioContext` — trader, risk
  and PM size against real holdings. New product feature: user portfolio input. Schema:
  `runs.portfolio_snapshot` added.
- **PIT integrity hardened everywhere** (dated tools read the run date from graph state,
  vendor failures raise honestly, a feed that never observed a window says so). Strengthens
  the audit story; our `data_fetch_log`/`vendor_health` telemetry remains complementary.
- **Configurable `holding_period_days`** (was fixed 5). Schema: `settlements.horizon_days`
  CHECK relaxed to >0; `user_settings.holding_period_days` added.
- **Jev/TypeSafe social screening** (optional `TYPESAFE_API_KEY`): drops off-topic StockTwits/
  Reddit posts. Added to `user_secrets.key_name`.
- **Defaults now GPT-6 Sol (deep) / GPT-6 Luna (quick)** — `user_settings` defaults updated.
- Run isolation fixed for graph reuse in one process — directly relevant to our long-lived
  worker running sequential runs.

**Implications of the restructure.** `dataflows/interface.py`→`router.py`, vendors under
`dataflows/vendors/`, `agents/utils/memory`→`decision_log.py`, `graph/settlement.py` new,
`SignalProcessor` removed (`process_signal`). Zero migration cost for us — no wrapper code
was written yet; all OUR artifacts written against 0.5.1 from here (schema, worker, portal).

**Decision.** Stay synced to upstream main as baseline; no forks of framework internals.
Vendor additions (FMP/EODHD) go under `dataflows/vendors/` following the 0.5.x layout.

## 2026-09-16 — Data platform: Supabase Postgres (over Render Postgres)

**Context.** The product needs: (1) a system of record for users, decisions, settlements and
reflections; (2) multi-user auth; (3) live progress streaming from the Render worker to the
portal; (4) blob storage for per-run raw agent-state JSON (audit trail); (5) a job queue.

**Decision.** Supabase Postgres (Pro, $25/mo) is the single data platform. Chosen over
Render Postgres because the decision hinged on what ships *with* the database, not the engine:
Supabase Auth (OAuth + RLS) replaces hand-rolled tenancy, Supabase Realtime replaces SSE
plumbing for the "trading floor" live view, Storage replaces blob handling for run audit
payloads, and pgvector is available for future similarity retrieval. The engine is commodity
Postgres and stays portable (`pg_dump`).

**Architecture placement.**
- Job queue lives in Postgres (`FOR UPDATE SKIP LOCKED`); no broker at this scale.
- Raw per-run agent-state JSON → Supabase Storage; metadata + reports → Postgres.
- OHLCV/indicator disk cache and LangGraph SQLite checkpoints stay on the Render worker's
  mounted disk — rebuildable scratch, not system of record.
- Cross-cloud latency (Render Oregon → Supabase AWS) accepted: workload is LLM-bound,
  dozens of DB writes per run, not thousands. Pick nearest Supabase region.

**Implications / caveats.**
- Supabase free tier pauses after ~1 week inactivity → production requires Pro ($25/mo).
- Daily backups start at Pro; add a weekly `pg_dump` → Storage cron as cheap insurance for
  the decision ledger (the crown jewel).
- Tenancy enforced with RLS (user-scoped rows); worker uses service role.

**Rejected alternatives.** Render Postgres (same-region simplicity but auth/SSE/storage all
hand-rolled); Neon (great branching, fewer batteries); Timescale/ClickHouse (volume is tens of
MB/month — not justified); message broker (jobs/day too low).

**Related.** Stack: Render Web Service (portal) + Background Worker (inference) + Cron
(settlement) + Supabase. Next: detailed schema design (`docs/schema/`), Phase 0 scaffold.

---

## 2026-09-16 — Deployment target: Render (portal + worker + cron), no Vercel

**Context.** Framework runs are minutes-long with disk state (cache, checkpoints, memory);
serverless/Vercel functions break on runtime limits, ephemeral disk, and dependency size.
Render MCP is connected to ZCode for direct service management.

**Decision.** Render for all compute: Web Service (portal/API), Background Worker
(`tradingagents` runner), Cron Job (nightly watchlist runs + decision settlement).
`render.yaml` blueprint in-repo.

**Implications.** Persistent disk mount required on the worker for cache/checkpoints
(paths are env-configurable: `TRADINGAGENTS_CACHE_DIR`, `TRADINGAGENTS_RESULTS_DIR`,
`TRADINGAGENTS_MEMORY_LOG_PATH` — the memory log is superseded by Postgres `memory_entries`).
Free tier spins down → paid tiers (~$7/mo each).

---

## 2026-09-16 — Reliability thesis & datasource strategy

**Context.** Upstream framework is point-in-time correct for prices/fundamentals/macro/memory
but NOT for live news/social on historical dates; no P&L engine; yfinance is unofficial/fragile.

**Decision.**
1. Ship a settlement engine we own (cron settles each decision at +5d/+30d vs benchmark into
   Postgres) before any backtest claims.
2. Add FMP and EODHD as first-class dataflow vendors (historical prices, fundamentals,
   historical news with timestamps) to enable trustworthy backtests; yfinance demoted to
   live-quote convenience.
3. Label backtests as backtests; weight forward-tracked ledger results over backtests in the UI.
4. Every decision must be auditable: store raw agent-state JSON + all reports per run.

**Implications.** Vendor abstraction seam is `tradingagents/dataflows/interface.py` +
`data_vendors` config — adding vendors is contained, not a rewrite. FMP/EODHD keys required
(user-supplied, encrypted at rest in `user_secrets`).

---

## 2026-09-27 — Region decision: Render Virginia + Supabase North Virginia

**Context.** Owner asked where each datasource lives and where Supabase should sit. The moomoo
exploration states it directly (poc/README.md:323): *"Location: put it in US East (Virginia)
for US names. moomoo's quote servers are there and in Singapore."*

**Decision.** All four Render services move **oregon → virginia** (render.yaml updated).
Supabase project region = **North Virginia (us-east-1)** — co-located with the worker, and
Supabase's best-provisioned region.

**Region map (evidence).**
- moomoo REST/WS: quote servers **US East (Virginia) + Singapore** → Virginia keeps WS push
  at ~70 ms behind the exchange event (measured from a US-east-ish cloud container).
- SEC EDGAR: AWS US East (Virginia). FRED: St. Louis Fed, US. yfinance: global CDN edge.
  FMP: US. Polymarket: Cloudflare global edge. LLM APIs: anycast, region-irrelevant.
- Supabase: N. Virginia (chosen). Portal user in NZ: NZ→Virginia page latency is CDN-mitigated;
  data-plane latency is worker↔Supabase, both in Virginia.

**Supabase MCP.** Hosted server `https://mcp.supabase.com/mcp` (OAuth, no PAT needed) added to
`~/.zcode/cli/config.json` alongside Render MCP. Supports create_project + apply_migration +
execute_sql → deployment can be driven from ZCode after the owner restarts and completes the
browser OAuth grant. Fallback if ZCode can't OAuth: PAT from supabase.com dashboard →
Authorization: Bearer header on the same URL.

## 2026-09-27 — LLM provider: OpenRouter, cheap-mode defaults (owner key verified live)

Owner supplied an OpenRouter key; verified via /auth/key (valid, $0 usage, no expiry) and a
live completion (z-ai/glm-5.3-flash, 37 tokens). OpenRouter carries the full current lineup
(gpt-6-sol/luna, glm-5.3 family, deepseek-v4.1, opus-5.5, gemini-3.8-flash).

**Decision.** `OPENROUTER_API_KEY` on the worker → provider auto-selects `openrouter` with
**z-ai/glm-5.3-flash for BOTH quick and deep** as the shipping default (≈$0.14/run at
1.8M-in/140k-out vs ≈$4.98 on GPT-6 defaults). Matches the BSTester/DoThatKarma OpenRouter
baseline. Upgrade path is a settings change (gpt-6-sol deep + gpt-6-luna quick), not code.
`render.yaml` worker env gains OPENROUTER_API_KEY (sync: false); config.py missing_critical
now accepts it. Engine 0.5.1 accepts non-catalog model IDs.

## 2026-09-27 — Completion round: usage capture, post-run digest, weekly backups

**Usage capture.** Framework `cost_tracker` never sees OpenRouter traffic (LangChain
ChatOpenAI → openai SDK), so real runs recorded 0 tokens. `worker/llm_usage.py` wraps
`openai.resources.chat.completions.Completions.create` once per process; OpenRouter
responses opt into per-call cost via `extra_body {"usage":{"include":True}}` (injected
only for openrouter.ai base URLs). EngineRunner resets/drains the recorder per run.
Verified live: NVDA fast run recorded **4,552 in / 695 out / $0.0010**.

**Post-run digest (Phase-1 first cut).** `worker/digest.py` — one small OpenRouter call
(quick model) over stored run artifacts (stage reports clipped, debate heads, decision,
news titles) → normalized JSON in `run_digest` (migration 0006; upsert by run_id):
evidence register (≤8 claims w/ stage tags), bull/base/bear scenarios, news
classification (catalyst/risk/assumption + impact), per-stage QC scores 0–100. The
normalizer coerces/clamps everything; the LLM is told to omit rather than invent —
it correctly wrote "not provided" for fair-value bands when the engine gave no targets.
Runs after `enrich_run`, non-fatal. Digest call's own usage is folded back into the run.
Portal dossier renders Evidence register, Scenario & sensitivity table, news
classification chips, Agent QC grade bars (visual-judge: 9/9 segments pass).

**Weekly backups.** `worker/backup.py` — 19 product tables (deliberately NOT
user_secrets) → gzipped JSONL → Storage bucket `backups/<date>/` + `_manifest.json` +
app_settings `backup_state`. Pure REST (PostgREST pagination + Storage upload); crons
only install `web/worker/requirements.txt`, so `requests>=2.32` was added there.
Render cron `tradingagents-backup` crn-das8g0fpn0mc73f9det0, Mondays 03:00 UTC.
Validated live: 1,104 rows / 20 objects uploaded.

**Data hygiene.** Deploy-race churn had left duplicate run rows per job (one RKLB job
had 4). Cleanup rule: keep runs with a decision, delete decision-less siblings
(cascades agent_reports/debate_messages). Report API resolves **job ids and decision
ids — NOT run ids** ("no run for reference" 404 means you passed a run id).

**OpenAI SDK note.** Local dev venv lacks `openai` (framework dep, not worker req) —
install it in web/.venv for the llm_usage tests; install() no-ops returning False
when the SDK is absent, so stub-mode/worker-thin environments stay safe.

**render.yaml** now mirrors deployed MCP topology (worker as web service w/ /healthz,
no disk, `cd`-prefixed commands from repo root, backup cron present).
