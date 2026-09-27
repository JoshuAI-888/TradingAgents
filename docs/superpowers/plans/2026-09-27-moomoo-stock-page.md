# Moomoo Stock Page — Build Plan & Work Loop

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, autonomous — user is not available for checkpoints). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reproduce moomoo's stock-specific page (`/stock/{TICKER}-US`: header+21 stats, chart w/ sessions+ranges, analyst ratings, orderflow, Options chain, 6 Financials sub-tabs, Analysis, Company, 3 News sub-tabs, Comments) in the TradingAgents portal, opened by clicking a screener ticker, with S&P street estimates via yfinance.

**Architecture:** worker `moomoo.py` gains read-only wrappers (one per endpoint template); `main.py` gains TTL-cached `/api/stock/{symbol}/*` routes + a yfinance estimates route + a `/stock/{rest:path}` catch-all serving the SPA; `index.html` gains `stockPage()` + hash routing (`#/stock/{SYM}-US`) and a moomoo-style chart/orderflow/options/financials UI. A fixtures mode (`TA_STOCK_FIXTURES=1`) serves recorded payloads so the page renders (and is verifiable) without moomoo keys locally.

**Tech Stack:** FastAPI + vanilla JS/canvas SPA (existing), MoomooClient (Ed25519, Budget 30/min/path-template), yfinance (S&P Global MI estimates), pytest (offline-first).

**Spec:** `web/STOCK_PAGE_FEASIBILITY.md` (element→endpoint map, §2–§5) + conversation findings: yfinance == S&P Global Market Intelligence data (Yahoo help SLN2310; live-verified vs moomoo CHE figures).

## Global Constraints
- Read-only moomoo endpoints only; never trade/account/sim-trade/crypto/watchlist-write; never log key material (HB §1).
- Tests never touch the network (conftest discipline). Moomoo keys are unset locally — code must degrade to `{"available": false}` and fixtures mode must cover visual checks.
- Rate limit 30/min per path template shared across symbols — page load ≈ 12 distinct templates, no client-side fan-out loops per row.
- Match existing style: one-file API section, worker wrapper one-liners returning `out` dict / list, dark portal CSS vars, `esc()` everywhere.
- No `yfinance` import at API module import time (lazy, inside function).
- moomoo gotchas encoded: find-news needs sort_type; history-kline pages by date window (370/call); snapshot denies → `skipped`; option-chain ≤20 expiries/call; US consensus = 3 tiers only.

## Work Loop
`implement → pytest (offline) → fixture-render check → next task`, then one full-suite pass + browser visual pass + docs. Commit per task on `product/portal-phase0`.

---

### Task 1: Worker read-only wrappers (moomoo.py)
**Files:** Modify `web/worker/tradingagents_worker/moomoo.py`; Test `web/worker/tests/test_moomoo_stock.py`
**Produces:** methods on `MoomooClient`: `cur_kline(symbol,ktype=2,autype=1,count=100)`, `rt_data(symbol,kind="FULL")`, `capital_flow(symbol)`, `capital_flow_history(symbol,period="day")`, `capital_distribution(symbol)`, `option_expirations(symbol)`, `option_chain(symbol,start=None,end=None)`, `statements(symbol,statement_type,financial_type)`, `revenue_breakdown(symbol,period=None)`, `earnings_price_history(symbol)`, `earnings_price_move(symbol)`, `analyst_consensus(symbol)`, `rating_summary(symbol,page=None)`, `company_profile(symbol)`, `company_executives(symbol)`, `find_community(keyword,community_type=1,sort_type=2,size=20)`. `find_news` gains `news_type: int|None`.
- [ ] Step 1: Failing tests — monkeypatch `client.call` recording `(method, path, query, body)`; assert path templates (`/quote/US.CHE/rt-data`, query `{"type":"PREMARKET"}`), that `find_news(..., news_type=2)` passes it, `find_community` maps params, option_chain omits None start/end.
- [ ] Step 2: Run → FAIL (AttributeError).
- [ ] Step 3: Implement wrappers (thin `self.call` calls; GET query dicts only with non-None values).
- [ ] Step 4: `python -m pytest web/worker/tests/test_moomoo_stock.py -q` → PASS; full worker suite still green.
- [ ] Step 5: Commit `feat(worker): moomoo read-only wrappers for the stock detail page`.

### Task 2: API routes + fixtures + estimates + catch-all
**Files:** Modify `web/api/tradingagents_api/main.py`; Create `web/api/tradingagents_api/stock_fixtures.py`; Test `web/api/tests/test_stock_page.py`
**Produces:**
- `_stock_client()` → moomoo client or None; when env `TA_STOCK_FIXTURES=1`, routes return `stock_fixtures.get(template, symbol)` payloads instead (same shapes as live).
- Routes (each TTL-cached via `_cache()`, category quotes/other; degrade → `{"available": false, "reason"}`):
  `GET /api/stock/{symbol}/quote` (snapshot full row: header + 21 stats + session blocks), `/candles?range=5D|D|W|M|Q|Y` (maps to ktype+window via history_kline), `/intraday?kind=FULL|PREMARKET|AFTERHOURS|NORMAL` (rt_data), `/capital?period=intraday|day|week|month` (flow/history + distribution), `/options?expiry=auto` (expirations + chain + contract snapshot ≤80), `/financials/{statements|revenue}` (params statement_type/financial_type/period), `/earnings` (earnings_price_history + move), `/research` (consensus + rating_summary), `/news?type=news|notice|report` (find-news news_type), `/company` (profile + executives), `/community` (find-community).
  `GET /api/stock/{symbol}/estimates` → lazy yfinance (`revenue_estimate, earnings_estimate, eps_trend, earnings_history, calendar`); import failure → available false. `_estimates_fetch(symbol)` module attr so tests monkeypatch.
  `GET /stock/{rest:path}` → serve `PORTAL_STATIC_DIR/index.html` (registered before the static mount).
- [ ] Step 1: Failing tests (TestClient, `TA_STOCK_FIXTURES=1` monkeypatched env + `_cache` rooted at tmp_path): each route 200 + key fields (quote has last_price & stats; candles non-empty; options has expirations+chain; statements has periods; estimates monkeypatched stub; catch-all `/stock/CHE-US` 200 text/html; unknown route under /stock still serves SPA).
- [ ] Step 2: Run → FAIL 404.
- [ ] Step 3: Implement `stock_fixtures.py` (CHE-shaped payloads for all 11 templates incl. estimates stub) + routes.
- [ ] Step 4: New tests PASS; existing `test_api.py` PASS.
- [ ] Step 5: Commit `feat(api): moomoo-backed stock detail routes + S&P estimates (yfinance) + SPA catch-all`.

### Task 3: Portal shell — routing, header, 21-stat grid, moomoo-style chart
**Files:** Modify `web/api/static/index.html`
**Produces:** `openStock(sym)` (hash `#/stock/{SYM}-US`), hashchange + path routing on load; `pages.stock`-equivalent `stockPage(sym, tab)`; `window.__stk` state; header (name/last/chg/session lines/cap/PE + expandable 21-stat grid + ☆ toggleWatch); chart panel with session dropdown (rt-data kinds), range tabs 5D/D/W/M/Q/Y (kline mapping; Q = last ~63 D bars), Time↔Candle toggle, volume + turnover-rate panes, crosshair readout (Time O H L C Chg %Chg Vol Turnover Turnover%), MA5/20/60 + BOLL chips; new engine `stk*` functions (independent `chart` state from report page).
- [ ] Step 1: Implement JS + CSS (moomoo-like stat-grid/tabs styling on existing vars).
- [ ] Step 2: Local check — serve API with fixtures env; open `http://127.0.0.1:8000/stock/CHE-US`; no JS-error banner; header+stats+chart render; range/session toggles re-fetch.
- [ ] Step 3: Commit `feat(portal): stock page shell — moomoo header, 21-stat grid, session/range chart`.

### Task 4: Overview tab modules — ratings, orderflow, news & forum previews
**Files:** Modify `index.html`
**Produces:** Analyst ratings panel (Buy/Hold/Sell 3-tier bar, avg/high/low PT, N analysts, last-updated, rating-summary table ref); Orderflow panel (Net/In/Out totals, trend period filters Intraday/Day/Week/Month, XL/L/M/S bucket bar chart from distribution, canvas); news preview (top 5), community preview (top 3); click-through to respective tabs.
- [ ] Step 1: Implement. Step 2: fixture render check (bars align, filters refetch). Step 3: Commit `feat(portal): stock overview — analyst ratings + orderflow + previews`.

### Task 5: Financials tab — 6 sub-tabs incl. S&P estimates
**Files:** Modify `index.html`
**Produces:** sub-nav Earnings/Revenue Breakdown/Financial Indicators/Income Statement/Balance Sheet/Cash Flow. Earnings = forward estimates table (yfinance: EPS+revenue avg/low/high/analysts/growth, next earnings date) + actuals per quarter (statements revenue/net income/EPS + YoY) + EPS surprise history (earnings_history); Revenue = business/region tables w/ period select; Indicators = key-metric cards (quarterly bar + YoY) w/ Quarterly/Annual selector; three statement tabs = period-columns table (All/12/8/4 selector, YoY toggle, hide-blank toggle, currency note, Deadline+standard footer).
- [ ] Step 1: Implement (statements item_list → pivoted table; financial_type 7 annual / 102 cumulative quarters). Step 2: fixture render check. Step 3: Commit `feat(portal): stock financials — six sub-tabs with S&P estimates`.

### Task 6: Options, Analysis, Company, News, Comments tabs
**Files:** Modify `index.html`
**Produces:** Options: expiry dropdown, ITM/OTM + strike-range (All/±5/±10%) chips, sortable chain table calls|strike|puts (last/chg/%/bid/ask/vol/turnover/OI/IV), delay note. Analysis: consensus + PT + rating-summary rows. Company: profile kv + about + executives (name/position/salary). News: 3 sub-tabs (News/Announcement/Institutional Ratings) + announcement chips All/Earnings/Transactions/Shareholding/Events/Other classified by title keywords. Comments: find-community cards.
- [ ] Step 1: Implement. Step 2: fixture render check each tab. Step 3: Commit `feat(portal): stock options/analysis/company/news/comments tabs`.

### Task 7: Click-through + polish
**Files:** Modify `index.html` (screener symbol cell → `openStock`; candidates/ledger symbol links); `web/api/static/index.html` disclosures line update.
- [ ] Step 1: screener row symbol click opens stock page (Analyze stays on a separate button); ledger/report ticker links too. Step 2: check. Step 3: Commit `feat(portal): screener → stock page click-through`.

### Task 8: Full verification loop
- [ ] `python -m pytest web/worker/tests web/api/tests -q` all green.
- [ ] Run API locally with `TA_STOCK_FIXTURES=1 PORTAL_STATIC_DIR=web/api/static`; browser pass over `http://127.0.0.1:8000/stock/CHE-US` — every tab, filter, toggle exercised; zero script errors; visual check vs moomoo layout (side-by-side with the live page inventory).
- [ ] Budget sanity: fixture-off smoke against live moomoo skipped locally (no keys) — documented for Render.
- [ ] Docs: MEMORY.md entry; web/README.md note; feasibility doc status header.
- [ ] Final commit `docs: stock page build log` + delivery report to user.
