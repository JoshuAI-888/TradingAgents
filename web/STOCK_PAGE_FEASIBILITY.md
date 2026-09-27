# Feasibility: reproducing the moomoo stock-specific page with the moomoo OpenAPI

**Question:** when a ticker is clicked in the screener, can we render a moomoo-style per-stock page
(`/stock/{TICKER}-US`, e.g. https://www.moomoo.com/stock/CHE-US) from the moomoo OpenAPI? Can every
sub-page / tab / filter / graph view be faithfully reproduced?

**Verdict: yes for ~90% of the page.** Every quote, chart, options, financials, analyst-rating,
capital-flow and company module on the page has a matching read-only OpenAPI endpoint (all verified
live in the POC, 2026-09-26). Two real gaps exist — **street earnings estimates** (estimate vs actual
columns on the Financials/Earnings tab) and the **community forum** (only a 50-row search endpoint,
no threads/pagination). A few small features are approximations (SEC-filing category chips, app-only
order-book depth level) and two things are deliberately excluded (watchlist writes, moomoo's
marketing rail).

Sources for this document:
- Live page inventory: moomoo.com/stock/CHE-US clicked through tab-by-tab in a browser (logged-out
  web, NZ locale, 2026-09-27); sub-page slugs taken from the site's Vue router (authoritative route
  table in `app.*.js`).
- API surface: `JoshuAI-888/Moomoo-api` @ `claude/moomoo-api-exploration-dvyz2n`,
  `MOOMOO_API_HANDBOOK.md` (94 REST endpoints + WebSocket; all 60 read-only quote endpoints called
  live on 2026-09-26; US real-time entitlement confirmed on this login, §4.2 of the handbook).

---

## 1. Page inventory (what moomoo actually renders)

Top-level tabs (from the router; the visible nav):

| Tab | Route | Sub-routes found in the router |
|---|---|---|
| Overview | `/stock/{SYM}-US` | `overview` (default) |
| Options | `/stock/{SYM}-US/options-chain` | `options-chain` |
| Financials | `/stock/{SYM}-US/earnings` | `earnings`, `financials-revenue`, `financials-key-indicators`, `financials-income-statement`, `financials-balance-sheet`, `financials-cash-flow` |
| Analysis | `/stock/{SYM}-US/forecast` (locked → sign-up wall when logged out; route name is `forecast`) | `forecast` |
| Company | `/stock/{SYM}-US/company` | `company` |
| News | `/stock/{SYM}-US/news` | `news`, `announcement`, `institutional-ratings` |
| Comments | `/stock/{SYM}-US/community` | `community/:commentType?/:pageNum?` |

(Router also contains non-stock children that belong to other instrument pages — `ipo`, `heatmap`,
`contract-specs`, `related-futures`, `sector-industry`, `stock-list`, `thematic-etfs`,
`most-active-stocks`, `business-statistics`, `others` — these are not part of the stock page.)

Header (persistent across tabs): symbol + name + flag, last price with change/% change, close time,
post-market quote line, Market Cap, P/E (TTM), expandable stats grid (21 fields), Watchlist button,
market-status context. Below the tabs, each page is a single column + a right rail
("Market Insights" — moomoo marketing widgets: Star Tech Companies, Earnings Season, Warren Buffett
Portfolio; sign-up walls).

---

## 2. Element-by-element mapping

Legend: ✅ faithful (endpoint returns the exact data) · 🟡 partial / computed client-side · ❌ no API.
All endpoints below are read-only quote endpoints verified live in the POC unless noted.

### 2.1 Header / quote block

| UI element | Fidelity | API |
|---|---|---|
| Symbol, name, exchange flag | ✅ | `POST /quote/snapshot` (`code`, `name`), `POST /quote/stock-basicinfo` |
| Last price, chg, %chg, close time | ✅ | snapshot (`last_price`, `prev_close_price`, `update_time`, `data_date`) or WS `QUOTE` push |
| Pre-market / post-market / overnight quote lines | ✅ | snapshot session fields (`pre_market{…}`, `after_market{…}`, `overnight{…}` with own price/high/low/volume/turnover); WS `QUOTE` carries the same blocks |
| Market status ("Close Sep 25 16:00 ET") | ✅ | `POST /quote/market-state` (market open/closed/`trade_date`) + `sec_status` |
| Expandable stats grid — High / Low / Volume / Open / Prev Close / Turnover / Turnover Ratio / P/E (Static) / Shares / 52wk High / P/B / Float Cap / 52wk Low / Dividend TTM / Shs Float / Highest / Div Yield TTM / Range % / Lowest / Avg Price / Lot Size | ✅ all 21 | snapshot: `high_price, low_price, volume, open_price, prev_close_price, turnover, turnover_rate, pe_ratio, issued_shares, highest52weeks_price, pb_ratio, outstanding_shares, lowest52weeks_price, dividend_ttm, lot_size, highest_history_price, dividend_ratio_ttm, amplitude, avg_price` — plus extras we get free: `volume_ratio`, `bid_ask_ratio`, `ey_ratio`, `net_asset`, EPS, all-time low, bid/ask + sizes, suspension |
| Watchlist button | ⛔ excluded by design | add/remove = `POST /quote/modify-user-security` (a write; out of scope for the read-only research app). Read-only membership via `GET /quote/user-security` |

### 2.2 Overview tab

**Chart module** ("CHE Stock Chart")

| UI element | Fidelity | API |
|---|---|---|
| Session dropdown: Full Hours / Real-Time / After-Hours / Pre-Market | ✅ | `GET /quote/{symbol}/rt-data` with `type=NORMAL / FULL / PREMARKET / AFTERHOURS` (US; `OVERNIGHT` also exists). Returns the minute line incl. per-point volume; docs literally describe it as "the intraday mountain chart shown on quote pages" |
| Time-share (line/area) view + intraday volume histogram | ✅ | `rt-data` `point_list[]` (price, volume, avg_price per minute) |
| Range tabs: 5D / Daily / Weekly / Monthly / 1Q / 1Y | 🟡 | `GET /quote/{symbol}/history-kline` ktype: 1=1min, 2=Day, 3=Week, 4=Month, 5=Year, 6/7/8/9=5/15/30/60min; `extended_time=1|2` includes pre/after/overnight for US minute bars; 370 bars/call, date-windowed paging (worker already wraps this). **Quarterly bars: only `cur-kline` documents a quarter period; history-kline has no quarter ktype — build 1Q by aggregating monthly, or roll 3-month OHLCV client-side** |
| Candlestick view (Daily etc.) | ✅ | history-kline OHLCV (+`turnover`, change, turnover_rate per bar); current forming bar from `GET /quote/{symbol}/cur-kline` or WS `KLINE` push |
| Crosshair tooltip: Time/Open/High/Low/Close/Chg/%Chg/Volume/Turnover/Turnover% | ✅ | same bar data (turnover_rate included per bar) |
| Third pane under volume (turnover-ratio line) | ✅ | per-bar `turnover_rate` from history-kline |
| Chart-type toggle (Time ↔ Candle), indicators (MA/BOLL/MACD/KDJ/RSI…), hover readout | 🟡 | no API needed: computed client-side from OHLCV. (Our portal already has a canvas chart with EMA/WMA/BOLL/RSI/MACD/KDJ/ATR/CCI in `web/api/static/index.html` `reportPage`) |
| Live updates while open | ✅ | WS: `KLINE` push (per period/adjust), `QUOTE` push for the header; refresh frame every ≤10 min, de-dup TICKER by `sequence` (client recipe §10.5, implemented in `poc/ts/moomoo.ts`) |

**Analyst Ratings, Stock Forecast and Price Target section**

| UI element | Fidelity | API |
|---|---|---|
| "Based on N analysts in the past 3 months" + Buy/Hold/Sell % bar | ✅ | `GET /quote/{symbol}/research/analyst-consensus`: `total`, `strong_buy/buy/hold/underperform/sell` proportions (US returns 3 tiers only — exactly what the web shows: Buy 50% / Hold 50% / Sell 0%), composite `rating`, `update_time_str` ("Last Updated: Sep 26, 2026") |
| Price target next-12-months: avg / max / min, # analysts | ✅ | analyst-consensus: `average`, `highest`, `lowest`, `num_of_target_analysts` (the locked web widget's summary line matches these fields) |
| Detailed Ratings (per-institution/per-analyst rows, history) | ✅ (app parity) | `GET /quote/{symbol}/research/rating-summary` — per-institution / per-analyst rating, target price, date, report link |
| Earnings estimates link → Financials | — | see §2.3 gap G1 |

**Orderflow section**

| UI element | Fidelity | API |
|---|---|---|
| Net Inflow / Inflow / Outflow (Unit: K) today | ✅ | `GET /quote/{symbol}/capital-flow` (intraday minute-level in/out; sum for the day) or `capital-flow-history` for the daily record |
| Orderflow Trend: filters Intraday / Day / Week / Month / Overall | ✅ | Intraday → `capital-flow`; Day/Week/Month → `GET /quote/{symbol}/capital-flow/history` (day/week/month granularity); "Overall" → aggregate history client-side |
| Trade-size buckets XL / L / M / S (super-large / large / medium / small) | ✅ | `GET /quote/{symbol}/capital-distribution`: `capital_in/out_super/big/mid/small` (intraday cumulative snapshot; exact match to the four buckets) |
| Intraday net-inflow curve | ✅ | capital-flow (minute series, in vs out) |

**News preview / Stock Forum preview** — see §2.6/2.7 (same data sources as their dedicated tabs).

**Right rail ("Market Insights": Star Tech Companies, Earnings Season, Buffett Portfolio, sign-up walls)** | ❌ by design | moomoo marketing widgets, no OpenAPI. Replace with our own rail (e.g. screener peers from `stock-screen`, sector heat from existing Market Pulse). Not a fidelity loss for a research tool.

### 2.3 Financials tab (6 sub-tabs)

| UI element | Fidelity | API |
|---|---|---|
| **Earnings**: dates & summary table (Revenue / Net Income × Estimate / Actual / YoY / Beat / Vs Estimate), "Revenue, EPS and EBIT Estimates" chart with Actual↔Estimate toggle, per-quarter list w/ earnings-call dates, Earnings FAQ, historical 10-Q links | 🟡 | Actuals + per-period records: `GET /quote/{symbol}/financials/statements` (income items incl. revenue/net profit/EPS by period, YoY/QoQ, currency, accounting standard). Price reaction around earnings: `financials/earnings-price-history` & `financials/earnings-price-move` (±15 days around each disclosure date, OHLC, IV, avg earnings-day move). **The street estimates themselves (S&P consensus revenue/EPS/EBIT per quarter, "Estimate" and "Vs Estimate" columns) have NO OpenAPI endpoint — gap G1.** The 10-Q/8-K document links are moomoo-internal notice pages; we can link the item but the notice content is only in `find-news` `url` (points at moomoo.com) — gap G4 |
| **Revenue Breakdown**: By Business/Source + By Country/Region tables w/ period selector + currency | ✅ | `GET /quote/{symbol}/financials/revenue-breakdown` — "product / industry / region / business" dimensions + "available period dropdown list" (the selector is server-provided); pie/bar rendered client-side |
| **Financial Indicators**: cards (EPS, FCF, Current Ratio, Quick Ratio, ROE, ROA, Gross Margin, Net Margin, …) each with Quarterly chart + YoY, currency + Quarterly/Annual selector | ✅ | `financials/statements` with `financial_type` = annual(7) / cumulative-quarterly(102) and statement_type key-metrics set (handbook §9.9: "income / balance / cash flow / key metrics … each with field_id, display_name, value, YoY, QoQ") |
| **Income Statement / Balance Sheet / Cash Flow**: filters `Quarterly·All` (period count), YOY toggle, Hide-blank-lines toggle, currency; 20 quarterly columns; per-row YoY; Deadline + Accounting Standard footer rows | ✅ | `financials/statements` per statement_type; YoY is in each item; period list, `report_date` (Deadline) and `accounting_standard` (US_GAAP) are fields of the response. Column count / hide-blank-lines are client-side table options |
| Period selector "Quarterly · All / N", Annual | ✅ | statements `financial_type` + period array |

### 2.4 Options tab

| UI element | Fidelity | API |
|---|---|---|
| Expiry tabs (Oct 16 2026, Nov 20 2026, …) | ✅ | `GET /quote/{symbol}/option-expiration` (dates); `option-chain` returns ≤20 expiries/call via `start`/`end` ranges |
| Chain table: Calls (OI, Chg, %Chg, Price, Bid×size, Ask×size, Volume, Turnover) ↔ Strike ↔ mirrored Puts; "15min Delay" notice | ✅ | `GET /quote/{symbol}/option-chain` gives contract codes/strikes per expiry; then batch `POST /quote/snapshot` on the contract codes for last/chg/%chg/bid/ask/volume/turnover + `option_open_interest`, `option_implied_volatility`, delta/gamma/vega/theta/rho (snapshot option fields). Bid/ask *sizes* come from the contract's order book (`POST /quote/order-book`) — fine for a few strikes, too expensive for every row (note below) |
| Filters: ITM/OTM (All/ITM/OTM), Strike-Price range (All / ±N) | 🟡 | client-side: compare `strike_price` vs underlying `last_price` from snapshot. No server param needed |
| Sort row (Open Interest / Turnover / Volume / Chg / %Chg / Price / Ask / Bid) | 🟡 | client-side sort of the snapshot columns |
| Greeks / IV columns (web shows delay; app shows full) | ✅ | snapshot greeks (above); plus `option-volatility`, `option-exercise-probability`, combo strategy/spread/quote endpoints if we want the app's extras |
| Contract detail pages (`/options/CHE261016C450000-US`) | ✅ | same snapshot/quote on the contract code; K-line of the contract where entitled |

### 2.5 Analysis tab (`/forecast`)

Covered in §2.2 — analyst-consensus + rating-summary reproduce everything the page shows
(Buy/Hold/Sell distribution, analyst count, avg/max/min target, last-updated). The web's "Detailed
Ratings" upsell (rating-change notifications, per-analyst history page) maps to `rating-summary`
records (institution/analyst, rating, TP, date, report link). Morningstar star rating / fair value /
moat is available as a bonus via `GET /quote/{symbol}/research/morningstar` (not on the web page).

### 2.6 News tab (3 sub-tabs)

| UI element | Fidelity | API |
|---|---|---|
| **News** feed (source badges: Moomoo News, TipRanks, MT Newswires, Dow Jones, GlobeNewswire, Benzinga, Quiver; title, snippet, timestamp; Load More) | ✅ | `GET /quote/find-news` `symbol=<keyword>`, `sort_type` required (returns empty without it — gotcha #13), `news_type=1` (POST). Returns `news_id, news_type, title, publish_time, url, img_url`. Feed-aspect: one call per symbol per refresh; 30 calls/min shared across the whole endpoint — per-symbol detail page opened on click is 1 call, fine |
| **Announcement** feed w/ category chips All / Earnings / Transactions / Shareholding / Events / Other (SEC filings: 144, Form 4, SCHEDULE 13G, 10-Q, 8-K, 11-K) | 🟡 | `find-news` `news_type=2` (NOTICE) returns the same items incl. form-type in the title. The six category chips are **not** an API parameter — classify client-side by title keywords (Form 4/144 → Transactions, 10-Q/8-K earnings → Earnings, 13G/13D → Shareholding, …). Approximate, same as many third-party UIs |
| **Institutional Ratings** feed (rating-action items only) | ✅ | `find-news` `news_type=3` (REPORT) and/or rating-change records from `research/rating-summary` (has rating + TP + date + report link — richer than the feed) |
| Load More / pagination | 🟡 | find-news has no cursor documented (size-bounded result set) — "latest N" is what's available |

### 2.7 Comments tab

| UI element | Fidelity | API |
|---|---|---|
| Forum posts for the symbol (author, avatar, timestamp, snippet, like/comment counts, linked tickers) | 🟡 | `GET /quote/find-community` `symbol=<keyword>`, `community_type=1` (FEED), `sort_type` 1=popularity / 2=time. Max `size` 50, **no pagination cursor documented** → "latest 50 posts" only |
| Post detail thread, replies, posting, likes | ❌ | no API (posting is interactive anyway) |
| Router shows `community/:commentType?/:pageNum?` (Hot/Latest tabs, page numbers) | ❌ | pagination not exposed by the API |

### 2.8 App-only modules worth building (the moomoo app shows them; the logged-out web page hides them — OpenAPI supports all)

| Module | API |
|---|---|
| Order book (bid/ask ladder) | `POST /quote/order-book` + WS `ORDER_BOOK` push (US LV3: 60 levels measured; level count depends on our data permission) |
| Trades tape (time & sales, buy/sell direction) | `GET /quote/{symbol}/rt-ticker` + WS `TICKER` push (de-dup by `sequence`) |
| Dividends history | `GET /quote/{symbol}/corporate-actions/dividends` (per-share, currency, payout ratio, key dates, ≤100 records). US splits: ✅ via endpoint? — **`corporate-actions/splits` is HK-only per docs; US split history would come from kline `autype` forward-adjusted series or static data — gap G5**. Buybacks endpoint returns HK/A-share data only |
| Shareholding: institutions, holders, changes, insiders | `GET /quote/{symbol}/shareholders/{overview, institutional, holder-detail, holding-changes, insider-holders, insider-trades}` (insider-trades is Form 3/4/144-based — pairs with the Announcement tab) |
| Short interest / daily short volume (US) | `GET /quote/{symbol}/short/{interest, daily-volume}` |
| Valuation bands (PE/PB/PS vs own history + sector distribution + percentile) | `GET /quote/{symbol}/valuation/detail` |
| Operational efficiency (rev/profit per employee) | `GET /quote/{symbol}/company/operational-efficiency` |
| Executive list + per-executive background | `GET /quote/{symbol}/company/{executives, executive-background}` (name → long-text profile) |
| Company profile card | `GET /quote/{symbol}/company/profile` (label/value pairs; matches the Company tab fields: listing date, ISIN, founded, CEO, employees, fiscal-year-end, address, website…) |

---

## 3. Filters & graph views — can each one be "faithfully reproduced"?

**Filters**

| Filter on moomoo | Source of its options | Reproducible |
|---|---|---|
| Session selector (Full Hours / Real-Time / After-Hours / Pre-Market) | fixed enum → rt-data `type` | ✅ |
| Chart range tabs | fixed enum → history-kline `ktype` (+ client aggregation for 1Q) | ✅ (1Q 🟡) |
| Options: expiry, ITM/OTM, strike range, sort row | `option-expiration` + client-side on snapshot columns | ✅ / 🟡 |
| Financials: Quarterly·All, Annual, YOY, Hide-blank-lines, currency | `financials/statements` `financial_type`, `accounting_standard`, currency fields; toggles client-side | ✅ |
| Revenue-breakdown period + currency | response includes available-period list | ✅ |
| Announcement category chips | not an API param → title-keyword classification | 🟡 |
| Community sort (popularity/time) + type | `find-community` params | ✅ (no pagination 🟡) |
| Orderflow trend: Intraday/Day/Week/Month/Overall + XL/L/M/S | capital-flow + capital-flow-history + capital-distribution | ✅ |
| News "Load More" | no cursor → size cap | 🟡 |

**Graph views**

| Graph | Data | Reproducible |
|---|---|---|
| Intraday mountain line + volume histogram (per session) | rt-data | ✅ |
| Candles (1m…yearly, adjusted/unadjusted, extended-hours minute bars) + volume + turnover-ratio pane | history-kline / cur-kline / WS KLINE | ✅ (1Q bars 🟡) |
| Technical indicators / chart-type toggles | client-side from OHLCV | ✅ (already built in our report chart) |
| Crosshair OHLCV+turnover tooltip | bar data | ✅ |
| Buy/Hold/Sell donut + distribution | analyst-consensus | ✅ |
| Price-target range chart | analyst-consensus average/highest/lowest | ✅ |
| Orderflow trend bars (per size bucket, per period) | capital-distribution + capital-flow(-history) | ✅ |
| Revenue-breakdown pies (business / region) | revenue-breakdown | ✅ |
| Indicator cards (EPS/FCF/ratios/margins) w/ quarterly bars + YoY | statements key metrics | ✅ |
| Valuation percentile bands | valuation/detail | ✅ (bonus) |
| Institutional-ownership trend | shareholders/institutional | ✅ (bonus) |

---

## 4. What is missed (ranked)

| # | Gap | Severity | Workaround |
|---|---|---|---|
| G1 | **Street earnings estimates** — the "Estimate vs Actual / Beat Est. / Vs Estimate" table and the Revenue/Net-Profit/EPS/EBIT estimates chart (moomoo sources them from S&P). No OpenAPI endpoint returns forward consensus estimates. `analyst-consensus` covers ratings + target price only. | Major for an earnings-preview workflow; cosmetic for the rest of the page | Show actuals (statements) + earnings-day price reaction (earnings-price-history/move) + IV; or merge a second vendor (yfinance fallback already in the stack) for consensus estimates |
| G2 | **Community forum depth** — no thread/detail/replies, no pagination, 50-row search cap. | Minor (research tool doesn't need moomoo's forum) | Embed a "social buzz" counter from find-community; skip threads |
| G3 | Announcement **category chips** are derivable only by title parsing; the underlying notice *document* lives on moomoo's own pages. | Minor | Client-side classification; link out to the `url` each item carries (or to SEC EDGAR by form type + date) |
| G4 | Historical quarterly bars ("1Q" tab) — history-kline has no quarter ktype (cur-kline documents quarter). | Nit | Aggregate from month bars client-side |
| G5 | US **splits** (endpoint is HK-only) and buybacks (HK/A-share only) in corporate actions. | Nit (US splits rare) | Use adjusted-price ratio to detect splits; skip buybacks for US |
| G6 | Order-book depth level is gated by our market-data permission (LV1 vs LV3) — moomoo's own site shows its licensed level. | Depends on entitlement | Handbook measured 60-level US book on this login; re-check at integration time |
| G7 | News/Load-More pagination, forum pagination — no cursors. | Nit | Latest-N with auto-refresh (polling cadence in handbook §4.5) |
| ⛔ | Watchlist add/remove = `modify-user-security` write — excluded by the read-only policy in the POC. | Policy, not capability | Could be enabled later with the same AppKey (it's the user's own watchlist), but out of scope here |
| ⛔ | moomoo marketing rail (Star Tech, Buffett list, sign-up walls), moomoo AI summaries. | N/A | Replace with our own rail; not part of the data surface |

Nothing else on the page is missing: every number rendered in the header, chart, orderflow,
options chain, financial statements, analyst-ratings and company modules has a verified endpoint.

---

## 5. Wiring it into TradingAgents (the screener click-through)

Current state (from the repo survey): worker `web/worker/tradingagents_worker/moomoo.py` already
wraps `snapshot`, `stock-screen`, `history_kline`, `find_news`, `econ_calendar_hot` with Ed25519
signing, the 30/min per-path-template `Budget` and HTTP-200 `rate_limited` retry. Portal is a
single-file vanilla-JS SPA (`web/api/static/index.html`) + FastAPI (`web/api/tradingagents_api/main.py`)
with per-symbol `/api/bars | /api/news | /api/fundamentals` (yfinance-backed today) and a reusable
canvas chart engine; **no URL routing** and no per-symbol moomoo quote route yet.

1. **Click-through:** screener row (moomoo `stock-screen` / our `discovery_candidates`) → route
   `#/stock/{SYM}-US` (hash routing avoids the StaticFiles 404) or a FastAPI catch-all before the
   static mount. Symbol format conversion: screener property → `US.{TICKER}` code.
2. **New API routes** (all served from the worker's `MoomooClient`, TTL-cached per handbook §4.5):
   - `GET /api/quote/{symbol}` → snapshot (header + stats grid + session quotes) + market-state
   - `GET /api/quote/{symbol}/candles?ktype=&autype=` → history-kline + cur-kline
   - `GET /api/quote/{symbol}/intraday?type=` → rt-data
   - `GET /api/quote/{symbol}/capital?period=` → capital-flow / -history / distribution
   - `GET /api/quote/{symbol}/options?expiry=` → option-expiration + option-chain + contract snapshots
   - `GET /api/quote/{symbol}/financials/{statements,revenue}` → statements (`financial_type`),
     revenue-breakdown; earnings-price-history/move for the earnings panel
   - `GET /api/quote/{symbol}/research` → analyst-consensus + rating-summary (+ morningstar)
   - `GET /api/quote/{symbol}/news?type=news|notice|report` → find-news (`sort_type` always set!)
   - `GET /api/quote/{symbol}/company` → profile + executives (+ operational-efficiency)
   - optional: `/shareholders/*`, `/short/*`, `/valuation` for app-parity modules
3. **Rate limits:** 30 calls per endpoint *path template* per server minute shared across symbols —
   a per-symbol detail view costs ~6–10 template-buckets on first load; cache snapshots 5 min,
   statements/consensus/profile daily-weekly (cadences in handbook §8). Budget class already enforces
   this.
4. **Real-time:** optional WS (`QuotePush` recipe in `poc/ts/moomoo.ts`) for QUOTE/ORDER_BOOK/TICKER/
   KLINE while a detail page is open; OAuth creds are already stored (WS requires OAuth, not AppKey).
   Subscription quota = symbol×type units (free 100); one connection for everything.
5. **Hard rules carried over:** no trade/account/sim-trade/crypto endpoints, no watchlist writes,
   no secrets in logs (handbook §1; same allowlist philosophy as `rest_verify.is_callable`).

## 6. Bottom line

A moomoo-style stock detail page is buildable end-to-end from the OpenAPI for a clicked screener
ticker: header + 21-stat grid, multi-session intraday and multi-period candle charts, orderflow with
size buckets, options chain with greeks, all six Financials sub-tabs, analyst ratings/price targets,
three news feeds, company profile — with the single substantive gap being street earnings estimates
(G1) and the forum being search-only (G2). Everything else that moomoo's own web page renders from
its internal APIs can be rendered from the public OpenAPI with equal or better fidelity
(detailed ratings, valuation bands, short data, shareholders are actually *richer* via API than the
logged-out web page).
