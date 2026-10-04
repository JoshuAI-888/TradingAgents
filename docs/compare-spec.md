# Compare Page — Multi-Chart Layout Spec

TradingView-style comparative chart workspace for the portal: one hero panel plus
stacked comparison panels, tickers chosen from the portal watchlist, Volume
Profile, full overlay/indicator menus, E/D event markers with an earnings
popover, a Study Settings drawer, and Ticker/Timeframe/Crosshair sync.

Reference: TradingView multi-chart layout screenshots (MSFT hero + AAPL/NVDA
stacked, VP 20 overlay, BB 20,2, RSI 14 pane, "E" earnings markers with the
Earnings & Revenue popover, layout picker, sync toggles).

## Data sources (verified against the moomoo handbook, not guessed)

| Need | Source | Status |
|---|---|---|
| Watchlist tickers | Portal Supabase `watchlists`/`watchlist_items` via `/api/screener?watchlist_only=1` (returns `watchlist` + named rows) | in production |
| Earnings dates | `financials/earnings-price-history` (`pub_trading_day_str`, `period_text`, `pub_type`) | live-verified; already wrapped at `/api/stock/{symbol}/earnings` |
| EPS reported/estimate/surprise | `/api/stock/{symbol}/estimates` (`earnings_history`: eps_estimate/eps_actual/surprise_pct) | in production |
| Dividend ex-dates | `corporate-actions/dividends` (`ex_date`, `dividend_per_share`, `currency`) | live-verified; **new** client method + route |
| Intraday history | `history-kline` `ktype` 1 (1m) / 6 (5m, existing "5D") / 7 (15m) / 9 (60m, existing "3M"); `extended_time` for US pre/post minute bars | live-verified; **new** ranges + param |
| Volume by price | no moomoo endpoint (all 94 indexed) | computed client-side from OHLCV |
| Multi-panel header quotes | `snapshot` (batch, ≤400 codes) | **new** batched route |
| moomoo-native watchlist import | `user-security-group`/`user-security` (read-only) | live-verified; deferred — portal watchlist is the source for v1 |

## API changes

1. `MoomooClient.dividends(symbol)` — `GET /quote/{symbol}/corporate-actions/dividends`
   (read-only; container normalized in the API layer).
2. `MoomooClient.history_kline(..., extended_time=None)` — passes the US
   pre/after flag for 1-min bars.
3. `GET /api/stock/{symbol}/candles` — `ext` query param (0 default, 1 = include
   pre/post) forwarded when ktype=1; `_KLINE_WINDOWS` gains
   `"1d"` (ktype 1, 2-day window) and `"15m"` (ktype 7, 30-day window).
4. `GET /api/stock/{symbol}/dividends` → `{"available": true, "list": [...]}` —
   accepts dict-container or bare-list live shapes; unavailable → `available:false`.
5. `GET /api/stock/quotes?symbols=MSFT,AAPL` (≤12 symbols) →
   `{"available": true, "quotes": {SYM: snapshot_item}}` — one batched snapshot
   call; fixtures-mode synthesizes per-symbol quotes.

Fixtures (`stock_fixtures.py`): `dividends`, `candles:1d`, `candles:15m`, and a
`quotes_batch(symbols)` helper. Tests in `test_stock_page.py` cover all four.

## Frontend architecture (web/api/static/index.html)

Reuses the shared klinecharts engine (`klineHost` factory + `klineApply` /
`klineSetData` / `klineTool` / `klineFullscreen` / controls). The engine is
instance-based (stock page + report dossier already run concurrently), so each
compare cell is one more `klineHost` with its own `state()/data()/overlays()`
callbacks — no engine changes.

### State

```
window.__cmp = {
  layout: "1+2",            // "1" | "2h" | "2v" | "1+2" | "2x2"
  sync: { ticker: true, tf: true, cross: true },
  active: 0,                // cell index the Study drawer edits
  cells: [ { sym, range, mode, ma, ema, boll, subs, events, ext, _maLast, _emaLast }, ... ]
}
```
Persisted to localStorage (`cmp_state`); restored on page open. Hosts are
per-render (torn down by `showPage`'s `klineTeardownAll()` like every page).

### Layouts

CSS grid templates on `.cmp-grid[data-layout=…]`: `1` (single), `2h`
(side-by-side), `2v` (stacked), `1+2` (hero left, two stacked right — the
screenshot default), `2x2`. Cells render in order; removing a cell keeps the
rest. Layout picker = icon strip in the page header (screenshot 7).

### Custom indicators (registered once, guarded)

Sub-panes: `ATR` (Wilder), `AROON`+`AROONOSC`, `MFI`, `FORCE` (Force Index),
`RVOL` (volume / SMA(volume,20)), `PERF` (% vs first bar — the comparative
line), `STOCHF` (Stoch FAST), plus built-ins MACD/RSI/KDJ/CCI/WR/ROC/BIAS/OBV/DMI.
Main-pane overlays: built-in MA/EMA/BOLL/SAR; custom `DONCH` (Donchian 20),
`KELT` (Keltner EMA±2·ATR), `SUPERT` (Supertrend 10,3), `PIVOT` (prior-period
P/R1-R2/S1-S2), `VWAP` (intraday ranges only), and `VP` (Volume Profile).

`VP` uses the custom `draw({ctx, kLineDataList, indicator, visibleRange,
bounding, barSpace, yAxis})` hook (verified present in the vendored 9.8.10):
buckets the last N bars (calcParams `[period, rows, valueArea]`, default
`[20, 24, 0.7]`) into price rows, spreading each bar's volume uniformly across
its high–low span, colored by that bar's close vs open, drawn from the pane's
left edge (≤22% width) with a dashed POC line. Returns true to suppress the
default figure pass.

### Per-cell controls

Compact header per cell: symbol button (opens picker), timeframe menu (1d, 5D,
15m, 1M, 3M, 6M, Y, W, M, 10Y), Time/Candle buttons, Events toggle, and the
shared `klineControlsHTML` cluster (MA/EMA/BOLL/Panes/tools/fullscreen) bound
with a per-cell prefix `cmp{i}` — the bind/sync helpers are prefix-parameterized
already. OHLCV crosshair readout per cell (same format as the stock page).

### Watchlist picker

Modal listing the starred watchlist (from `/api/screener?watchlist_only=1`:
names + last price + % change) with a search box over the same universe;
clicking a row assigns the symbol to the requesting cell (and to all cells when
Ticker sync is on). Star toggle inline, reusing `toggleWatch`.

### Sync toggles

Header toggles: Ticker / Timeframe / Crosshair (screenshot 7).
- Ticker: a pick in any cell applies to all.
- Timeframe: a range change applies to all.
- Crosshair: each host subscribes `onCrosshairChange` and replays into the other
  hosts via `chart.executeAction("onCrosshairChange", {x, y, paneId})` (both
  verified in the vendored build) behind a re-entrancy flag.

### Event markers (E/D) + popover

Per-cell "Events" toggle fetches once and caches:
- earnings dates from `/api/stock/{symbol}/earnings` (`records[].pub_trading_day_str`,
  `period_text`, `pub_type` 1=BMC 2=AMC per naming dictionary, tolerant lookup),
- dividend ex-dates from the new `/api/stock/{symbol}/dividends`.

Markers are `simpleAnnotation` overlays ("E" green, "D" teal) above the bar
high; next earnings date (from `/estimates` `calendar`) shows as a header chip.
Clicking a candle whose date carries an event opens an HTML popover
(subscription to the verified `onCandleBarClick` action) with Earnings Date,
Fiscal Period, EPS Reported/Estimate/Surprise (matched from `/estimates`
`earnings_history` by quarter within ±45 days) and Revenue Reported (matched
from the cached quarterly income statement). Revenue estimate/surprise are
shown only when a source has them — neither moomoo nor yfinance exposes
historical revenue consensus; the popover omits those two lines rather than
guessing.

### Study Settings drawer

One right-hand drawer bound to `__cmp.active`: chart type (Candle/Area),
extended-hours checkboxes (Pre-market / After-market → `ext=1`), Show major
events toggle, Overlays list (dropdown + numeric params + delete) and
Indicators list (dropdown + params + reorder + delete). Changing chart type or
the sub-pane set goes through the engine's rebuild path; changing overlay
params removes and re-creates that indicator with new calcParams.

### Header quotes poll

One `/api/stock/quotes?symbols=…` call for every cell symbol, polled every 10 s
while the page is mounted (hooked to the page's `state.poll` lifecycle), feeding
each cell header's last price and colored % change.

## Deliberately out of scope

- **Log chart scale** — shipped 2026-10-05: the engine upgrade to KLineChart
  10.0.3 added log/% scales via `overrideYAxis` value transforms (was
  impossible on 9.8.10 — no log-scale code in that vendored build).
- **"Patterns (daily charts)"** — TradingView-proprietary auto pattern detection.
- **Ichimoku forward cloud** — indicator results align 1:1 with bars, so the
  26-bar forward projection cannot render; omitted rather than approximated.
- **moomoo watchlist writes** — `modify-user-security` stays outside the app's
  read-only scope (existing design note).
- **Drawing persistence** — drawings stay per-session per-cell (localStorage
  persistence is a follow-up).
- **Sub-pane reordering** — the engine's `klineApply` sorts sub-panes by the
  built-in menu order, so per-pane reorder controls were dropped from the Study
  drawer (add/remove remain; v1 deviation from the original plan).

## Build deviations & known cosmetics

- Extended-hours syncs with the Timeframe sync toggle (it only affects 1d bars).
- Volume/RSI sub-pane legend text can be crossed by tall bars or MA lines —
  engine-standard legend placement, identical on the stock page.
- The "Next E" header chip shows on every panel (events data loads for all);
  the E/D canvas markers remain gated by each panel's E toggle.
- Panel chart heights equalize to the tallest panel so no grid cell is left
  with dead space (`cmpEqualize`).

## Test plan

1. `python -m pytest` — API suite incl. new dividends/quotes/intraday tests.
2. `node --check` on extracted `<script>` blocks.
3. Fixtures-mode server (port 8877) + in-app browser walkthrough matrix:
   - all 5 layouts render; cell add/remove; layout persists across reload;
   - watchlist picker assigns symbol (single + ticker-sync);
   - every timeframe loads (1d, 5D, 15m, 1M, 3M, 6M, Y, W, M, 10Y incl. tf-sync);
   - Time/Candle switch per cell + rebuild;
   - MA/EMA/BOLL toggles; each custom indicator pane adds/removes; overlays
     DONCH/KELT/SUPERT/PIVOT/VWAP draw; VP renders with params;
   - drawing tools draw + clear per cell; fullscreen per cell + Esc;
   - Events toggle renders E/D markers; popover shows EPS data; next-earnings chip;
   - sync toggles: ticker, timeframe, crosshair (visually on screenshots);
   - header quotes poll updates (fixture data static → assert call fired + fields render);
   - Study drawer: every control acts on the active cell only.
4. Visual gate: rendered screenshots through the visual-judge agent.
5. Surgical commit + push; verify production serves the new route + page.

## Build checklist

- [x] Spec written (this file)
- [x] `moomoo.py`: `dividends()` + `history_kline(extended_time)`
- [x] `main.py`: `_KLINE_WINDOWS` + `ext` + `/dividends` + `/stock/quotes`
- [x] `stock_fixtures.py`: dividends, candles:1d/15m, quotes_batch
- [x] `test_stock_page.py`: new route tests — full suite green
- [x] index.html: custom indicator registry (incl. VP draw)
- [x] index.html: Compare page shell + layouts + per-cell hosts + controls
- [x] index.html: watchlist picker modal
- [x] index.html: events (E/D) + earnings popover + next-earnings chip
- [x] index.html: Study drawer
- [x] index.html: sync toggles + batched quotes poll
- [x] node --check + pytest re-run
- [x] Browser walkthrough matrix (fixtures) + screenshots
- [x] Visual-judge pass (2 rounds + targeted re-check)
- [ ] Commit + push + production verify
