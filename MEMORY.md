# Project Memory & Decision Log

Working decisions for the TradingAgents deployment product (portal + worker on Render).
Newest decisions first. Each entry: context → decision → implications.

---

## 2026-09-29 — Unified chart engine (KLineChart), Analyze page restored, financials formatting (owner feedback round)

**Owner feedback** (candles not rendering, no drawing/zoom/indicators, key indicators null,
% vs currency, Chinese segments, Analyze button error, sync the two kline charts,
fullscreen, MA/EMA 5/20/50/100/200) → shipped:
- **Embedded KLineChart 9.8.10** (`web/api/static/vendor/klinecharts.min.js`, UMD, no build
  step) replaces both hand-rolled canvas engines. ONE shared engine now drives the stock-page
  chart and the report-dossier chart (identical toolbar: Time/Candle, MA/EMA/BOLL, sub-pane
  dropdown VOL/MACD(DIF·DEA)/RSI/KDJ/CCI/WR/ROC/BIAS, draw tools trend/h-line/ray/v-line/
  parallel/fib, wheel zoom + pan, crosshair readout, ⛶ fullscreen + Esc). Report keeps its
  1M/3M/6M/1Y/2Y switch and draws the S/R ladder + entry zone + stop as static overlays.
- **MA/EMA period pickers**: ▾ menus select 5/20/50/100/200 per overlay; implemented as ONE
  indicator instance whose calcParams = selected periods (labels stay MA5/MA20/…).
- **Candle-on-intraday root cause**: old engine forced line mode for `!isK`; plus a
  klinecharts quirk — switching area↔candle on a live instance leaves the stale area canvas
  painted above the candles → mode switches now rebuild the chart (`klineApply` rebuild path).
- **klinecharts gotchas (learned the hard way, all verified live)**: `createIndicator(x, false,
  {id})` REPLACES the pane's indicator set — must pass `isStack=true` to stack MA+EMA+BOLL;
  partial indicator `styles` objects REPLACE built-ins (custom VOL bars styles crashed the
  draw pass at `styles.lines[0]`); indicator line styles REQUIRE `dashedValue` (draw reads
  `[0]`/`[1]` per segment); main-pane indicators need explicit `{id:"candle_pane"}`.
- **Key financial indicators null**: cards read `item.value`; live/fixture items carry
  `item.data` (fixed for the statements table in 10b2adc, missed here) → `stkStmtNum`.
- **`Profit from Continuing Operations 133749000000.00%`**: `stkStmtVal` word-unbounded
  substring `/ratio/` matched inside "Continuing OpeRATIOns" → currency row rendered as %.
  Now word-bounded classification + guards (`debt to equity` is a multiple — its name
  contains "Equity Ratio" which would misfire as %); EPS/per-share plain numbers;
  coverage → ×.
- **Chinese segment names**: revenue-breakdown has NO lang param (unlike find-news) →
  server-side zh→en dictionary `_ZH_SEGMENT_EN` (~70 known names: 美国→United States,
  智能云→Intelligent Cloud, …) applied in `/financials/revenue`; unmapped pass through.
- **Analyze page**: `pages.analyze` was dropped in an early refactor while nav + callers
  survived → "pages[p] is not a function" on click. Restored (submit form + in-flight rail +
  live trace + recent decisions).
- Verified: 31 API + 46 worker tests green; fixture-mode browser walkthrough (candles on all
  ranges, MA 20/50/100/200 + EMA, MACD DIF/DEA, trend-line drawing, fullscreen, report-chart
  harness) — screenshots in session.
- **Owner round 2** (live PBR): Time→Candle showed a BLANK pane — live rt-data points omit or
  blank open/high/low on some points (docs list them; the wire doesn't always carry them), so
  NaN hit the y-scale and killed the whole main pane. Fix: sanitize at fetch (derive
  o/h/l from cur_price, drop points with dead closes) for both pts and klines; fixture now
  carries 8 o/h/l-less session-start points to keep that path tested. Sub panes are now
  ADDITIVE — a "＋ Panes ▾" multi-select (VOL/MACD/RSI/KDJ/CCI/WR/ROC/BIAS) stacks each
  selection as its own pane below the candles (set changes rebuild the chart; removing an
  indicator from a shared pane would leave dead space). Fullscreen exits via Esc and the ⤡
  button. 35 API (fixture grew) + 46 worker tests green.
- **"4 analysts but no ratings"** (live PBR): moomoo analyst-consensus returns only 3 tiers
  for US/CA (strong_buy/hold/sell) — `buy`/`underperform` are HK/CN/SG/MY/AU/JP-only fields
  (handbook gotcha, confirmed live). The frontend read only buy/hold/sell → 0% everywhere,
  and its `!c.buy && !c.hold && !c.sell` fallback mislabeled covered stocks "no coverage".
  Fix: render every tier present (stkTiers/stkRatingBar, 5-tier aware), normalize count-shaped
  responses to %, show the composite consensus badge (rating 1–5 → Buy/Strong Buy/…), and
  reserve "no tier breakdown published" for genuinely empty distributions. Fixture + test now
  pin the US 3-tier shape (no buy/underperform keys).

---

## 2026-09-29 — Render cron failures root-caused (discovery PermissionError every run)

**Owner report: "lots of failed cron job emails from Render."** Render events + logs showed
`tradingagents-discovery` failing on EVERY 15-min run since creation, exit 1:
`PermissionError: [Errno 13] Permission denied: '/data'` at `discovery_cron.py` import —
`TtlCache(root=SETTINGS.cache_dir …)` with the hard-coded `/data/cache` default. Render
**cron jobs have no attached disk**, so `/data` is not writable; the worker WEB SERVICE got
`TRADINGAGENTS_CACHE_DIR=/tmp/ta-cache` in render.yaml, but no cron service defines it
(crons were created via hosted MCP, so render.yaml changes alone don't update them either).
Universe/settlement/backup crons succeeded because they never touch the cache.

Fix (two layers, both in commit 134dc99):
1. **Code**: `config._path()` — explicit env wins; else use the disk path only if
   `makedirs` succeeds; else fall back to a writable temp dir. No entrypoint can crash on
   an unwritable default again (discovery_cron also dropped its `or "/data/cache"`).
2. **Blueprint**: all 4 cron services get `TRADINGAGENTS_CACHE_DIR=/tmp/ta-cache` in
   render.yaml (applies on future blueprint syncs).

Note: cron cache was only a 15-min TTL anyway (cron instances are ephemeral — the disk
wouldn't have helped across runs either), so /tmp loses nothing. Verified: local env-unset
run falls back cleanly; 134dc99 deployed to all services 19:13Z; waiting on the 19:30Z run
for the green confirmation.

---

## 2026-09-29 — Market Pulse 'r3 is not defined' after clicking a preset (production)

 Screener preset round (70b1d18) left a destructure/read mismatch in `pages.home()`'s
 active-preset branch: `const [r0, r1, r2, r4, ex] = await Promise.allSettled(...)` named the
 presets result **r4**, but the rail line read **r3** → ReferenceError killed the entire page
 render ("Failed to load: r3 is not defined") whenever `st.activePreset` was set. Only the
 preset path crashed; the no-preset branch used a different settled/val pattern. One-line
 rename (r4→r3), committed surgically (27ef48e) on top of HEAD without sweeping concurrent
 WIP (temp-copy dance: commit HEAD+fix, restore working tree). Verified live: fixture-mode
 render with activePreset set → full page, no error banner; production serves the fixed line.
 Lesson: this page has no test harness — the error surfaced only through user clicks. The
 visible script-error banner + `window.__lastScriptError` remain the best first probe.
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

## 2026-09-27 — Moomoo keys live: Phase-0 probe passed (US+HK real-time; AU not entitled)

Owner supplied AppKey + Ed25519 private key (base64 PKCS#8 DER) + OAuth client/refresh
token. All four set on the Render worker (never in the repo). Worker client fixed
against the verified PoC (ecosystem-survey/moomoo-api/poc — run it with creds to bisect
auth bugs): **signed path must include /api/v1.0**; **body-less requests sign the empty
string, not sha256("")**; body JSON must be compact separators; find-news takes
`symbol` (required, it IS the keyword) + `size` (not keyword/limit); stock-screen body
is structured `screen_queries` and rows come back in `items`. Phase-0 probe results:
server-time offset −48 ms; US+HK snapshot ✅ real-time; **AU snapshot denied
(ret −9 realtime permission)** → ASX stays on yfinance; screen ✅; history-kline ✅;
find-news ✅ (0 rows on a Sunday); economic-calendar ✅.

Discovered live: stock-screen `simple_field` market enum **1=HK 2=US 3=BJ**;
`simple_property` **2201 = last_price×1000**. A true movers screen needs the
pct_change property id — only verifiable during a live US session, so
`discovery._screen_candidates` is disabled (news + watchlist still feed candidates).
OAuth creds stored for the future WS push ingestion (WS requires OAuth; AppKey fails
there — HB §3.4).

## 2026-09-27 — Market Pulse live, main synced, usage capture made version-proof

`/api/market/state` (portal env carries MOOMOO keys): one batched snapshot — SPY/QQQ/
IWM/VIXY + HK.HSI (auto-dropped when quote-less) + 11 SPDR sector ETFs — plus the hot
economic calendar; 5-min TTL; prev-close pct fallback off-session; ISO as_of stamps.
Home page renders the Market state panel. **main is synced** with product/portal-phase0
(fast-forward pushes both branches).

TSLA standard run (16.5 min live trace): Underweight 2/5, Jev screening ran ("Jev's
classifier read… 8 bullish / 1 bearish / 9 neutral / 4 unclear"), digest 8 evidence /
3 scenarios / qc 5 stages. But engine token capture returned 0 — the openai SDK class
patch goes silent when a deploy re-resolves a different SDK layout. Fixed properly:
`LLMUsageCallback` (LangChain BaseCallbackHandler — must SUBCLASS it, the manager
checks raise_error; AMD crashed with AttributeError until it did) threaded via
`TradingAgentsGraph.llm_callbacks` → `get_graph_args(callbacks=…)`. `reconcile()` takes
tokens from whichever source saw them and estimates cost from the catalog when
OpenRouter's per-call cost is absent. Validated: AMD fast run 62,315 in / 42,743 out /
$0.0085 captured. Digest retry hardened (json_object mode with plain fallback).
Also: failed/cancelled jobs no longer block resubmission (dedup checks status);
`web/STOCK_PAGE_FEASIBILITY.md` (owner-authored) committed.

## 2026-09-28 — Market Pulse screener (moomoo-powered, watchlist universe)

**Live API discoveries (bounded experiments).** stock-screen range filters
(simple_property_query with lower/upper) return -3 invalid parameter in every
documented shape — only the market enum query + server-side sort work. Property
dictionary mapped by value-matching a screened symbol against its snapshot:
2201=price, 2202=open, 2204=high, 2205=prev_close, 2207=bid, 2208=ask,
2210=pct_change, 2215=? ; 2301=total_market_val (all x1000). Server sort
verified: mktcap desc -> NVDA/AAPL/GOOGL/MSFT. All 15 recommended screeners
transcribed from moomoo's SSR page (web reader; includes page 2): Penny,
High Dividend, Blue Chip, Buffett, Undervalued, Growth, P/B<1, LT High Div |
High/Good/Low P/E, RSI<30, Junk, Small-Cap Growth, Blue Chip Dividend.

**Architecture.** /api/screener: watchlist universe = saved TradingAgents
watchlist -> ONE batched snapshot (all filters applied Python-side, any column
sortable); market universe = stock-screen page (server-sorted) -> snapshot
enrichment. /api/screener/presets: all 15 presets scored over the universe,
top-3 each. POST /api/watchlist/{symbol} stars a ticker. Default watchlist
seeded (NVDA AAPL META TSLA RKLB AMD). Portal home: moomoo-style layout —
toolbar (market select, watchlist toggle, Add Filter), filter chips, 12-col
table with stars, preset rail with page tabs, Add-Filter modal (Quotes live;
Technical/Financial disabled pending the undocumented indicator/financial
property dictionary — needs a live US session to map like the quotes ids).

**Gotchas.** Rewriting home() silently dropped the `c`/`d` candidates/decisions
mappings ("c is not defined" via the showPage catch) and the Add Filter button
referenced an undefined openFilterModal — browser-based UI testing caught both.
git add -A keeps sweeping owner-authored files (docs/, web/api stock_page
tests) into commits — they are legit project files.

## 2026-09-27 — Stock detail page shipped (moomoo per-symbol surface, screener click-through)

Built `/stock/{SYM}-US` (spec: web/STOCK_PAGE_FEASIBILITY.md; plan:
docs/superpowers/plans/2026-09-27-moomoo-stock-page.md). Clicking a screener symbol
now opens the moomoo-style stock page: header + expandable 21-stat grid (one
snapshot), pre/post session lines, chart with session dropdown (rt-data
FULL/NORMAL/PREMARKET/AFTERHOURS) + range tabs 5D/D/W/M/Q/1Y (history-kline; 1Q
= 105-day daily window), Time/Candle toggle, MA/BOLL, volume + turnover-rate
panes, crosshair readout (O/H/L/C/Chg/Vol/Turnover/Turnover%); analyst ratings
(3-tier US consensus + avg/high/low PT) and orderflow trend (capital-flow
intraday/day/week/month + XL/L/M/S capital-distribution bars); Options chain
(option-expiration → option-chain ≤80 contracts → snapshot for prices/IV/Δ,
ITM/OTM + ±5/±10% filters, sortable); Financials with SIX sub-tabs — Earnings
(forward street estimates via yfinance == S&P Global MI, verified
dollar-identical to moomoo's numbers for CHE; GAAP actuals from statements;
EPS surprise history; earnings-day price reaction), Revenue Breakdown,
Financial Indicators (statement_type=4 cards), Income/Balance/Cash-Flow pivot
tables with All/4Q/8Q/12Q + YOY + hide-blank toggles; Analysis
(rating-summary per institution); Company (profile labels + executives);
News with News/Announcement/Institutional-Ratings sub-tabs and title-keyword
category chips; Comments via find-community. Routing: `#/stock/{SYM}-US` hash +
FastAPI `/stock/{rest:path}` catch-all serving the SPA (add routes BEFORE the
static mount). New worker wrappers in moomoo.py (one per path template);
API routes /api/stock/{sym}/{quote,candles,intraday,capital,options,
financials/statements,financials/revenue,earnings,research,news,company,
community,estimates}, all TTL-cached, all degrade to available:false without
keys. **TA_STOCK_FIXTURES=1** env serves recorded CHE payloads
(stock_fixtures.py) — how the page renders/tests offline (70 web tests pass;
browser-verified every tab). Gotcha: yfinance EPS actuals are street-basis
(GAAP diluted differs); estimates route is API-side lazy-import — yfinance
already in root pyproject, add to web/api/requirements.txt on next deploy if
missing.

## 2026-09-28 — Screener universe widened: 899 stocks whole-market (was 6/100)

**What limited the list:** (1) the screener defaulted to the watchlist universe
(6 seeded tickers); (2) market mode fetched one 100-row page; (3) the response
`limit` param defaulted to 100 — UI never passed it.

**Live probes that shaped the fix:** moomoo stock-screen returns up to 300
items/call with NO pagination cursor (the docs' pagination.* fields are absent
from responses — handbook §17 pattern again). So coverage comes from a sort-
slice UNION: caller's sort + mktcap-desc + top-gainers + top-losers, deduped →
899 unique US stocks (4 screen calls + 3 batched snapshots per 5-min cache).
Filters run Python-side over the full union; display always Python-sorts the
requested column globally (slice order must not leak). Filter-aware server
sort: max-only bound → ascending slice, else descending. Endpoint now reports
matched vs shown (limit default 500, cap 1200). UI defaults to whole-market;
watchlist mode stays one click away (grows as you star tickers).

## 2026-09-27 — Stock page live-reconciled (production), Data & Coverage page added

Probed every live /api/stock/* endpoint on Render and fixed 11 fixture-vs-live
drifts (the POC handbook documented some shapes the live gateway doesn't match):
- snapshot session fields are FLAT (pre_price/after_price/pre_change_rate…),
  not the nested pre_market{} of the WS push — header reads both
- find-news AND find-community return a BARE LIST (no news_list/community_list
  container) — worker wrappers now accept both; news was silently empty before
- option-expiration container is expiration_list (not expire_date_list)
- earnings-price-history container is `records` (600 rows for CHE), fields
  pub_trading_day_str/close_price/last_close_price
- company/profile is {items:[{name,value,field_type}]}, field_type 2=intro
  block; company/executives container is `executives`
- statements: **financial_type=102 is rejected live (-3, allowed 1..7/9)** —
  the handbook's "7/102" is wrong; 0 (server default) returns the same
  quarterly+FY mix moomoo's web shows; item value field is `data` (FULL
  currency units, value_type amount/ratio); container report_list; limit param
  works; pass financial_type=7 for annual
- revenue-breakdown: breakdown_list[type 1=Product 2=Industry 4=Region
  8=Business].item_list[].{name, main_oper_income, ratio} + screen_date_list
  period picker (date s + financial_type); names come provider-localized
- find-news accepts `lang` (undocumented) — lang=en gives English titles;
  titles carry <em> keyword highlights (stripped client-side)
- estimates (yfinance/S&P): first probe from Render returned empty frames —
  transient; now live (685.04M next-qtr revenue, 5 analysts). Route now
  reports available:false with reason when everything comes back empty
- ALL stock routes degrade upstream errors to {available:false, reason}
  instead of 500
Deployed: portal dep 925724f + 42f5990 + 10b2adc (auto-deploy on push to
product/portal-phase0; worker + crons also redeploy). Verified on production:
all 13 endpoints OK, options chain 58 contracts w/ quotes, news EN, statements
12 periods (673.251M = moomoo web exactly), browser-checked Financials tabs.
NEW: "Data & Coverage" nav page (#/info) — live status cards (portal/moomoo/
estimates), module→source matrix, 17 documented gaps vs moomoo's own page
(forum threads, WS streaming, order-book ladder, dividends/shareholders/short/
valuation/Morningstar UI, US splits-buybacks, pagination limits, AI rails).
74 web tests green. Diagnostics tip: the POC's poc/catalogue/verification.json
holds actual live response samples (data_keys) — fastest way to settle
container-name questions without burning API budget.

## 2026-09-28 — Full-market universe loader (9,381-stock coverage)

User hit the real limits: preset rail scored the 6-stock watchlist universe
(PLTR missing from High P/E despite 162 P/E; blanks everywhere), and the
market list capped ~900/9,381 (screen API: 300/call, no cursor, undocumented
range filters). Fix: universe_refresh job enumerates EVERY listing via
moomoo plate endpoints (plate-list INDUSTRY -> plate-stock x145 plates,
next_key pagination, <=1000/page) into screener_universe, then snapshot-
enriches all codes in 400-batches into screener_quotes (jsonb rows) —
migration 0007. /api/screener market mode reads the stored universe first
(zero live calls at view time); live slices remain the fallback. Presets now
score the ACTIVE universe and render as ONE list. Manual refresh: POST
/api/screener/refresh queues the job; home shows a progress bar off the
universe job_events. Budget/backoff: client MinuteBudget 30/min per path
template + Retry-After sleeps; a full run is ~7 min (145 plate calls + ~24
snapshot batches). db.upsert_many added (bulk merge-duplicates; single-row
upserts would be 9k HTTP calls). Cron follows (hourly quotes, daily enum).
FakeSupa upsert learned compound conflict keys ("market,code").

## 2026-09-28 — Quotes in top nav + ticker switcher; Comments-tab triage

USER REPORT: clicking Comments on the stock page "goes back to the screener".
Triage on the current deploy: Comments itself is clean (programmatic stkSet +
real-click probes never navigate; no overlay; navlog empty). Found and fixed
the one control that DID kick back: the ☆ star — toggleWatch ended with
showPage("home"). Now it re-renders the stock page in place (star state
updated optimistically in window.__scr.watchlistSyms). Hardened screener row
links with event.preventDefault() so a throwing handler can't follow href="#".
If the report was on a pre-deploy build, 7522ab5+ supersede it.

NEW: "Quotes" in the top nav — landing = last-viewed symbol, else the picker
(#/stocks): search by ticker/company over the stock-screen universe (~1,200/mkt,
5-min client cache), Market US/HK switch, Watchlist-only toggle, Sector browse
via plate-list (145 US industry plates) → plate-stock members snapshot-enriched.
Stock page header gained a ticker switcher (suggestion dropdown, Enter/click)
+ "All quotes" button. Routing: stkRoute handles #/stocks (regex tolerant of
hash query suffixes); showPage('quotes') opens last symbol or picker; nav
active-state maps stock→Quotes. openStock refreshes the hash on every switch
(was keeping the previous symbol's URL).

NEW worker wrappers: plate_list(market, class) → plate_list container;
plate_stocks(code) → stock_list; find_community gained lang (route sends en —
NOTE: MSFT's moomoo community feed is genuinely Chinese-language posts; lang=en
doesn't translate, it's faithful data). Live fixes: plate-stock sort_field enum
is MARKET_VAL ('MarketCapital' → -3); universe: /api/sectors +
/api/sectors/stocks (TTL-cached).

INCIDENT: `git add web/` swept the parallel session's in-progress
universe_refresh/screener_rows/db/service files into 7522ab5+11b299a (their
tests were mid-edit and flapped red→green as they committed cab8e11). Rule
refined: stage explicit paths, never `git add web/` while another session is
active in the same tree. Deploy: a7d18d2 live; picker/sectors verified on
production (145 sectors; members w/ prices; switcher NVDA flow; Comments stays).

## 2026-09-28 (later) — Full universe live: 5,794 stocks; parallel-session reconciliation

Universe refresh: 145 US industry plates → **5,794 unique codes** → 15 snapshot
batches → 5,794 quote rows (the first run wrote 1,000 — PostgREST default row
cap; db.select_all limit/offset pagination added for loader + API reads).
/api/screener market mode: matched 5,794, zero live moomoo calls at view time,
globally sorted, PLTR present. Presets: NO more blanks — parallel-session
_apply_filters skips filters whose field the universe lacks + full universe =
every preset has top-3. Honesty guard: when ALL of a preset's filters are
skipped (e.g. Below-30 RSI — no rsi14 field yet), the preset renders "needs
rsi14 data — pending the indicator dictionary" instead of fake gainers.

**Parallel session warning:** the owner runs another agent on this repo
(stock-page feature, saved_screeners migration 0008, Quotes nav). It changed
_apply_filters to return (rows, skipped_fields) between my commits — my tests
broke and I pushed red once. Before editing main.py/index.html, re-read them;
reconcile, don't overwrite. Applied their 0008 to the live DB.

Cron tradingagents-universe crn-dat3eujncjis73cvc55g: hourly 13–21 UTC weekdays
(quotes refresh; enum re-runs after 24h TTL). Universe covers 5,794 common
stocks (moomoo's screener shows 9,381 instruments incl. ETFs/ETPs — widen
later via plate_class=ALL if wanted, ~1,000 plates ≈ 33 min at budget).

## 2026-09-28 — Screener presets made moomoo-exact + Save/Manage Screeners

User supplied screenshots of all 21 moomoo recommended screeners ("Applied
Filters" + Selected chips). PRESET_SCREENERS rewritten 1:1 (penny now price≤5 +
cap≤300M + vol≥100K + revenue_growth≥10% + np_growth≥5% + debt≤40%, buffett =
float_cap≥500M + np_growth≥10% + gross_margin≥50% + OP/EBT≥70% + ROE≥15% +
ROE-YoY≥20%, speculative = new_low_10d, undervalued-semi/tech/banks = sector
filters, high-eps, high-roe, low-pe-high-div…). Filter fields the snapshot
doesn't carry (roe, margins, growth rates, rsi14, sector, new_low_10d) are kept
with needs:1 and SKIPPED by _apply_filters (now returns (rows, skipped)) —
skipping beats zeroing every row; /api/screener returns skipped_filters and the
rail shows "excl. …" / "needs … data — pending" (verified live: P/B<1 and Junk
fully active; Below-30 RSI fully pending). Preset descriptions + tooltips from
the screenshots.

SAVE SCREENER: table saved_screeners (migration 0008, applied to prod Supabase
by the parallel session), CRUD /api/screeners (GET/POST/PUT/DELETE, owner =
DEFAULT_USER_ID), Db.delete added. Filter modal gained a "Screeners" tab:
list w/ Apply/Edit/Update/Delete + save box (captures market, watchlist mode,
filters, sort, direction). Verified on production: create→list→update→delete
round-trip OK, table empty after.

Also: presets route no longer requires moomoo keys when the stored universe
exists; home() uses Promise.allSettled (one dead endpoint no longer blanks the
page); test_stock_page fixture got a _StubDb (was order-dependent on test_api's
env). 85 tests green. Commits 99f40f5, a7d18d2-era… see git log.

## 2026-09-29 — Universe widened to 13,585; NZ-time default; cadence setting; progress fix

User review round: (1) "only 5,794 vs 9,381" — INDUSTRY plates cover common stocks
only; loader v2 now enumerates INDUSTRY+CONCEPT+OTHER plates (469 plates) and unions
6 server-side sort slices → **13,585 codes / 13,560 quote rows** (a superset of
moomoo's screener count, which is their filtered stock view). No public moomoo
endpoint lists all instruments (basicinfo requires code_list; plate-stock curated
lists are tiny) — plate+slice union is the practical ceiling. (2) Progress bar:
refresh used to re-render home each poll (page refetch flash); now scrPollProgress
updates the bar DOM in place every 2s and re-renders exactly once on completion.
(3) Refresh cadence: GET/PUT /api/screener/schedule (interval_h ∈ 1/2/4/8/12/24,
stored in universe_state); the hourly cron skips when quotes are fresher; Settings
→ Data & coverage card (rows, last refresh, cadence select). force=1 on
/api/screener/refresh bypasses the skip (needed after loader-code changes).
(4) All site times render via fmtTs/fmtClock — Pacific/Auckland with DST by
default (localStorage tzmode=nz), UTC option in Settings→Display timezone.
Settings slowness note: /api/screener/schedule does two paginated 13.5k-row reads;
cache if it bothers anyone.

## 2026-09-28 — Screener reconciled to moomoo.com/screener (server-side execution)

AUDIT: cycling all presets showed 12 missing fields (debt_ratio, revenue_growth,
roe, net_profit_growth, roe_yoy, sector, gross_margin, net_margin, rsi14,
op_ebt, eps_growth, new_low_10d) skipped in up to 9 presets each.

DISCOVERY: (1) moomoo's web screener chunks hold the factor-KEY dictionary
(77 keys: assetLiabilityRatio, operatingIncomeGrowthRate, grossProfitRate,
roeYoYGrowthRate…); (2) their SSR strategy pages embed the CANONICAL
stock-screen payloads per screener (window.__INITIAL_STATE__.hot_strategy_info
.queries) — extracted all 22; (3) Futu's get-stock-screen docs give the enum
system (FinancialProperty 4101+, term 100=annual). Live probes vs known
NVDA/AAPL/Tencent figures pinned the dictionary:
simple 2201 price / 2301 cap (x1000) · 2303 PE_TTM / 2304 P/B (x100000)
· financial term=100: 4102 npGrowth 4106 revGrowth 4107 netMargin 4108
grossMargin 4109 debt/asset 4110 ROE 4606 epsYoY 4607 opProfitYoY 4625 roeYoY
4702 OP/EBT 4219 divYieldTTM 4801 basicEPS 4903 floatCap (pct & money x1000)
· cumulative 3104 N-day avg volume (periodAverage), 3108 N-day change
(new-low: days=10 upper<0) · RSI = indicatorPositionalQuery {position 1/2,
period 11, firstIndicator 52, firstIndicatorParams [14], secondValue x1000}
· sectors = plateQuery {plateList:[{plateIdList:[10002016,…]}]} (numeric ids
from moomoo's own semi/tech/bank payloads).

RESULT: ALL 22 presets (incl. the 22nd, Best LT High Dividend) now execute
SERVER-SIDE via /api/screener/execute — moomoo's own screening backend, zero
pending fields, results carry per-stock factor values. Reconciliation: penny
executed with moomoo's exact payload anchors on USEI first-row (price asc)
matching moomoo.com's own display; note moomoo's PUBLIC page count (3079)
applies only the 3 quote filters (premium fundamental filters are not applied
anonymous) — ours applies ALL filters per the definition. Stock-screen caps at
300 rows/page and exposes no next_key on this tier → counts >300 shown as a
full first page. Probe route left in place (POST /api/screener/probe, read-only
pass-through) for future dictionary work. Screeners tab in the filter modal now
lists all 22 with definitions + per-screener skip status + Run/Edit; presets
run server-side (banner "server-side execution — matches moomoo.com/screener").
99 tests green. RSI and OP/EBT: moomoo's own web UI locks RSI behind VIP — our
account executes it server-side anyway.

CLEANUP (same day): presets route + rail + Screeners tab no longer emit the
stale skipped/pending hints — every preset filter has a verified server-side
property, so the honest state is "all filters · server-side". Live: 22 presets,
no stale fields; RSI<30 executes (60 rows, top ITFCY/BAC/MS). Commit 1bae3b6.

## 2026-09-29 (evening) — Configurable columns + per-column sort/filter + security classification

Screener table is now fully data-driven: 26-column catalog (SCR_COLS: key →
label + kind text/num/multi/bool); Columns picker (show/hide, persisted in
localStorage scrState with filters/sort); EVERY column sorts (click header —
Python sorts the full matched set); per-column filter menu via the ⚈ icon —
numeric ranges, multi-select checkboxes backed by GET /api/screener/facets
(distinct values + counts over the universe, meta-merged), boolean toggles;
chips show column filters; Reset all (toolbar) + per-menu Reset + chip ×.
_apply_filters learned values[] (case-insensitive multi-select, same
skip-semantics for absent fields). Loader enriches screener_universe with
stock_type/exchange via /quote/stock-basicinfo (400-code batches, budgeted;
migration 0010 columns) — verified facets: STOCK 8,807 · ETF 4,117 · IDX 551 ·
WARRANT 162 over 15,487 matched rows. NOTE: a full loader run is now ~25 min
(469 plates + 34 basicinfo + 34 snapshot batches) — pushes restart the worker
and requeue the job ("worker restarted mid-run" x3 this round); never push
while a loader job is in flight.

## 2026-09-29 (night) — Stock-chart panes grow downward, candles never squeeze

klinecharts divided a fixed container (#stk-kc 480px / #rep-kc 460px; fullscreen:
stretched to 100vh via flex:1!important), so every added sub-pane compressed the
candles. Fix: klineEnsure captures the host's base height once (h.baseH from the
inline style); klineApply sets container height = baseH + 84×subs and chart.resize()
— candles stay constant, panes stack downward, the page scrolls naturally.
Fullscreen: removed the viewport-stretch rules; .kc-full keeps overflow:auto so a
scrollbar appears only when panes exceed the screen. Verified live: COST chart
564px → 732px after adding RSI+KDJ (+2×84 exact), candles unchanged.

## 2026-09-29 (late) — Screener parity + Columns fix + preset editor pane

1. **Count parity**: 15,487 was our stored universe (stocks + ETFs + indices +
   warrants). Screener now defaults to classified `stock_type == STOCK` →
   **8,807**, zero non-stocks in view (also applied to the presets top-3
   scoring). Honest gap vs moomoo's 9,381: their count includes ~574 OTC/
   pink-sheet listings our 469-plate walk can't reach (no public all-instruments
   endpoint). ETFs remain available via an explicit Type filter and on stock pages.
2. **Columns button**: `<details>/<summary>` swallowed clicks (button-styled
   summary); replaced with the proven body-attached JS toggle (scrToggleColPick).
3. **Preset editor pane**: Add Filter → Screeners tab is now two-column —
   presets + saved screeners left, editor pane right. Clicking a preset/saved
   screener shows its filters as editable min/max rows (name + description
   prefilled), Apply-to-table and Save screener / Update saved (POST/PUT
   /api/screeners). Verified end-to-end: clicked Penny Stocks, edited a filter,
   saved → appears in Your saved screeners.
