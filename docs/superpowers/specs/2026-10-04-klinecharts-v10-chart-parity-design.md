# KLineChart v10 chart-surface parity — design spec

Date: 2026-10-04
Status: approved in conversation (user chose Option B: upgrade vendored KLineChart 9.8.10 → 10.0.3; chart-surface scope only; no alerts)

## Goal

The kline chart, in fullscreen mode, reaches chart-surface parity with TradingView to the extent KLineChart 10.0.3 + moomoo-api data allow: every KLineChart feature usable, fed by moomoo OHLCV(+turnover) data, fast on desktop and mobile.

## Decisions (from conversation)

- Engine: KLineChart **10.0.3** (latest; npm dist-tags confirmed 2026-10-04). No external license dependency (TradingView Advanced Charts declined by user conditional).
- Scope: **chart surface only** (chart types, intervals, indicators, drawings, scales, snapshot, go-to-date, autoscroll, timezone, compare, fullscreen, themes). No watchlist/screener/panels. **No alerts.**
- Data: moomoo cloud REST via the existing worker client; realtime = polling of the frontier bar through the existing TTL cache (WS push is a follow-up, not in this scope).
- The shared engine block powers 4 chart instances (report `#rep-kc`, stock `#stk-kc`, analysis `#ana-kc`, compare `#cmp-kc-{i}`); all upgrade together via the one engine block.

## KLineChart 10.0.3 feature surface (from package + repo source)

- 6 candle styles: `candle_solid`, `candle_stroke`, `candle_up_stroke`, `candle_down_stroke`, `ohlc`, `area`.
- 26 built-in indicators: MA, EMA, SMA, BOLL, SAR, MACD, RSI, KDJ(STOCH), CCI, WR, ROC, BIAS, DMI, TRIX, OBV, VR, EMV, MOM, PSY, DDI, BRAR, BBI(bullAndBearIndex), AO, PVT, CR(currentRatio), VOL, AVGPRICE(averagePrice).
- 16 built-in overlays: segment, rayLine, straightLine, horizontalSegment/RayLine/StraightLine, verticalSegment/RayLine/StraightLine, parallelStraightLine, priceChannelLine, fibonacciLine, priceLine, simpleAnnotation, simpleTag, brush.
- Continuous drawing mode, custom hotkeys, multi y-axis, `AxisValueToValueCallback` (log scale hook), % axis (native), `DataLoader` (getBars backward paging + subscribeBar realtime), `scrollToRealTime/scrollToDataIndex/scrollToTimestamp`, thousands separator, future-time axis, overlay `points` are serializable (persistence).
- Breaking changes vs 9.8.10 (verified from release notes + 10.0.3 d.ts): `applyNewData/updateData/setLoadMoreData/clearData/setPrecision/setPriceVolumePrecision` removed → `setDataLoader/resetData`; `createIndicator(ind, isStack?, paneOpts?)` → `createIndicator(ind, {isStack, pane, yAxis})`; `calc()` returns object keyed by timestamp; `customApi` → `formatter`; `options.layout` array → object (`basicParams`+`panes`); `setPaneOptions` no longer takes axis config → `overrideXAxis/overrideYAxis`; tooltip style keys renamed.

## Architecture

1. **Vendor swap** — replace `web/api/static/vendor/klinecharts.min.js` with the 10.0.3 UMD build. Single script tag, no build step (repo convention).
2. **Engine block rewrite in place** (`web/api/static/index.html` `klineHost`…`klineSyncControls`, ~2613–2909). Public helper names stay identical so the 4 call sites and UI tests keep working. Internals migrate to the v10 API:
   - `klineEnsure`: `init(el, { locale, formatter, thousandsSeparator })`; precision via formatter; theme via setStyles (renamed tooltip keys).
   - `klineSetData`: `setDataLoader({ getBars })` — initial + backward paging through a new paged API; `subscribeBar` timer feeding the frontier bar (cur-kline poll via existing API, 15 s, market-hours aware).
   - `klineApply` / `klineCreate`: v10 indicator signatures; MA/EMA one-instance-with-calcParams pattern kept.
   - Custom indicators + E/D event markers: ported to v10 `calc()` object return; drawings persistence keeps the localStorage scope + `points` serialization.
3. **New chart-surface features** (all client-side): style menu (6 styles + Heikin Ashi synthetic series), scale toggles (auto / log via axis valueToValue transform / % native), full indicator menu (26), full drawing toolbar (16 overlays + continuous mode + clear), snapshot export (canvas composite → PNG download), go-to-date (date input → scrollToTimestamp), autoscroll (scrollToRealTime), hotkeys, timezone select, light/dark theme toggle, mobile toolbar collapse.
4. **Backend** (`web/api/tradingagents_api/main.py` + worker `moomoo.py`):
   - Expose every moomoo ktype as a range: add native 3m, 10m, 2h, 3h, 4h (ktypes 10, 26, 14, 29, 15) to `_KLINE_WINDOWS` and the range validation set.
   - New paged endpoint `GET /api/stock/{symbol}/candles/back?ktype=&before=&count=` for DataLoader backward loading (date-windowed via worker client).
   - Per-ktype cache TTLs (intraday ≤ 60 s, daily 1 h, weekly+ 24 h) — upstream budget 30 req/min/path stays protected; history served from cache/Supabase, moomoo only for misses + frontier.
5. **Tests**: API tests (ranges, paged endpoint, fixtures for every ktype), UI node tests (engine smoke via vendored UMD + drawings persistence), then **browser verification on desktop (1280×720) and mobile (390×844)**: every tool exercised, responsiveness, snappiness.

## Non-goals

Alerts, watchlist/screener panels, WS push streaming, Renko/Kagi/PnF synthetic types (not KLineChart features; follow-up from moomoo analytics layer), symbol-compare overlay pane (kept: existing compare-page sync), log-axis perfect tick rounding (best-effort ticks via the transform).
