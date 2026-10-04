# KLineChart v10 chart-surface parity — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the shared kline chart engine from vendored KLineChart 9.8.10 to 10.0.3 and expose its full feature surface (6 styles, 26 indicators, 16 overlays, log/% scales, paging, snapshot, go-to-date, hotkeys, themes) on all 4 chart instances, fed by moomoo data, verified on desktop + mobile.

**Architecture:** One engine block in the single-file SPA (`web/api/static/index.html` ~L2613–2909) serves report/stock/analysis/compare charts. Vendor UMD swap + in-place engine rewrite keep public helper names stable. Backend adds native moomoo intervals + a paged-klines endpoint for DataLoader backward loading, behind the existing TTL cache.

**Tech Stack:** Vanilla JS SPA (no build), KLineChart 10.0.3 UMD, FastAPI + worker moomoo cloud REST client, pytest + node:test.

**Spec:** `docs/superpowers/specs/2026-10-04-klinecharts-v10-chart-parity-design.md`

## Global Constraints

- No build step, no npm — vendor UMD only (`web/api/static/vendor/`), single-file SPA convention preserved.
- Public engine helper names unchanged: `klineHost, klineEnsure, klineApply, klineSetData, klineTool, klineFullscreen, klineControlsHTML, klineBindControls, klineSyncControls, klineTeardown, klineTeardownAll, klineRebuild, klineDrawOverlays, klineCreate`.
- Moomoo upstream budget 30 req/min/path-template — all new backend calls go through `TtlCache` + the existing worker client; no per-viewer upstream polling.
- No alerts, no panels, no WS push (follow-ups).
- Dark-first theme; light theme is an additional option, not a replacement.
- Tests: `cd web/api && python -m pytest tests -x -q` and `cd web/api/tests/ui && node --test` stay green.

---

### Task 1: Vendor swap to KLineChart 10.0.3

**Files:**
- Modify: `web/api/static/vendor/klinecharts.min.js` (replace)
- Modify: `web/api/static/index.html:456` (banner comment only)

- [ ] Copy `/tmp/klc-check/package/dist/umd/klinecharts.min.js` → `web/api/static/vendor/klinecharts.min.js`
- [ ] Verify `KLineChart.version` string in the bundle is `10.0.3` (grep)
- [ ] Commit: `feat(chart): vendor KLineChart 10.0.3 (replaces 9.8.10)`

### Task 2: Backend — native moomoo intervals + per-ktype TTLs

**Files:**
- Modify: `web/api/tradingagents_api/main.py:1734-1741` (`_KLINE_WINDOWS`), range validation in the candles endpoint (~1825)
- Modify: `web/worker/tradingagents_worker/moomoo.py` (only if ktype constants missing)
- Test: `web/api/tests/test_stock_page.py`

**Interfaces:**
- Produces: ranges `1m,3m,5m,10m,15m,30m,1h,2h,3h,4h,5D...` map to ktypes `K_1M,K_3M,K_5M,K_10M,K_15M,K_30M,K_60M,K_120M,K_180M,K_240M`; response shape unchanged (`{available, range, bars[]}`).

- [ ] Write failing test: `GET /api/stock/TEST/candles?range=3m` returns bars (fixture), `range=bogus` → 400
- [ ] Extend `_KLINE_WINDOWS` with the new ktype mappings (moomoo ktype enum: 3m=10, 10m=26, 120m=14, 180m=29, 240m=15)
- [ ] Per-ktype TTL: intraday ktypes cache ≤60 s, daily 1 h, weekly+ 24 h (extend `TtlCache.DEFAULTS` categories, e.g. `ohlcv_live`)
- [ ] Run tests, commit: `feat(api): expose native moomoo intraday intervals (3m/10m/2h/3h/4h)`

### Task 3: Backend — paged klines endpoint for backward loading

**Files:**
- Modify: `web/api/tradingagents_api/main.py` (new endpoint near existing candles)
- Modify: `web/worker/tradingagents_worker/moomoo.py` (history paging helper if not callable with an end-date window)
- Test: `web/api/tests/test_stock_page.py` (+ fixture synth for arbitrary ktype/before)

**Interfaces:**
- Produces: `GET /api/stock/{symbol}/candles/back?ktype=K_5M&before=<epoch_ms>&count=300` → `{available, ktype, bars:[{time_key, open, high, low, close, volume, turnover}]}` ascending, strictly older than `before` (omit `before` = newest).

- [ ] Failing test: paged endpoint returns count ≤ requested, all bars older than `before`, ascending
- [ ] Implement endpoint calling the worker client windowed (end = before, start = before − window)
- [ ] Fixture synth: generate deterministic bars for any `ktype`/`before` in `stock_fixtures.py`
- [ ] Run tests, commit: `feat(api): paged kline history endpoint for chart backward loading`

### Task 4: Engine block rewrite to v10 (core)

**Files:**
- Modify: `web/api/static/index.html:2613-2909` (engine block only; helper names preserved)

**Interfaces:**
- Consumes: Task 3 paged endpoint, existing `GET /api/stock/{sym}/candles`, `GET /api/stock/{sym}/intraday`
- Produces: same helper signatures; new host fields: `h.dataLoader`, `h.pollTimer`, `h.ktype`, `h.scale` (`auto|log|percent`), `h.style`, `h.tz`

- [ ] `klineEnsure`: `KC.init(el, { locale: "en-US", formatter: {...}, thousandsSeparator })`; drop `setPriceVolumePrecision`; keep theme via `setStyles` with v10 tooltip keys; keep crosshair subscribe + resize listener
- [ ] Replace `applyNewData` with `setDataLoader({ getBars, subscribeBar })`: initial bars passed through loader callback; `type:"backward"` + `timestamp` → fetch `/candles/back`; `subscribeBar` = 15 s timer fetching frontier bar (cur-kline via existing candles endpoint with tiny range) → callback; clear timer in `klineTeardown`
- [ ] `klineCreate` → `createIndicator(indicatorOrName, { isStack: true, pane: paneId, ...opts })`; `getIndicatorByPaneId` → `getIndicators({ pane: paneId, name })`; `removeIndicator` → v10 filter form
- [ ] Port MA/EMA one-instance-with-calcParams + BOLL + additive sub-panes logic unchanged
- [ ] Port drawings persistence (createOverlay/getOverlays `points` serialization — shape unchanged) + static overlays + rebuild paths
- [ ] Run `node --test` UI tests; fix fallout; commit: `refactor(chart): migrate engine block to KLineChart v10 APIs`

### Task 5: Chart styles + scales

**Files:**
- Modify: engine block + `klineControlsHTML`/`klineBindControls`/`klineSyncControls`

**Interfaces:**
- Produces: `h.state().style` ∈ `candle_solid|candle_stroke|candle_up_stroke|candle_down_stroke|ohlc|area|heikin`; `h.state().scale` ∈ `auto|log|percent`; HA series = client-side transform `close'=(o+h+l+c)/4, open'=(prev close'+open)/2`, high/low = max/min(h, open', close') stored as parallel buffer keyed by timestamp; switch to HA rebuilds with transformed bars (same pattern as area↔candle rebuild)

- [ ] Style menu buttons (7 entries incl. Heikin Ashi); setStyles candle.type for the 6 native; HA rebuild path
- [ ] Scale toggles: percent → `setStyles({ yAxis: { type: "percentage" } })` equivalent per v10 d.ts field; log → y-axis `valueToValue` transform (ln/exp pair) via `overrideYAxis`; auto → clear transforms
- [ ] Unit test (node): HA transform function (synthetic 3-bar fixture, exact expected values)
- [ ] Commit: `feat(chart): candle styles incl. Heikin Ashi + auto/log/percent scales`

### Task 6: Full indicator + overlay exposure

**Files:**
- Modify: engine block (`STK_SUBS` superseded by full built-in menu; keep MA/EMA/BOLL quick toggles)
- Modify: compare custom indicators (`index.html:2946-3163`) → v10 `calc()` object returns; E/D event markers port

- [ ] Indicator menu: all 26 built-ins, grouped (Overlays-in-main: MA/EMA/BOLL/SAR/AVGPRICE; Sub-panes: the rest) with default calcParams; picker writes through `h.update({subs|…})`
- [ ] Port compare-page custom indicators to v10 calc-object API (mechanical: return `{ [timestamp]: { knots… } }` per figure spec)
- [ ] Drawing toolbar: 16 built-in overlays + "keep drawing" (continuous mode toggle via `createOverlay` mode/`drawingMode`) + clear; icons text-based (repo convention, no assets)
- [ ] Port drawings-persistence save/restore for the new overlay names
- [ ] `node --test` UI drawings persistence test still passes (scope + restore)
- [ ] Commit: `feat(chart): expose full KLineChart v10 indicator + overlay surface`

### Task 7: Chart UX — snapshot, go-to-date, autoscroll, hotkeys, timezone, theme

**Files:**
- Modify: engine block controls

- [ ] Snapshot: composite the chart canvases (`el.querySelectorAll("canvas")`) into one PNG → download `SYMBOL_RANGE.png`
- [ ] Go-to-date: date input → `chart.scrollToTimestamp(ms)`; Autoscroll button → `chart.scrollToRealTime()`
- [ ] Hotkeys: `registerHotkey` arrows/zxc defaults + document in title tooltips
- [ ] Timezone select (UTC / Exchange / local) via `formatter.formatDate` offset
- [ ] Light/dark toggle: two `setStyles` presets
- [ ] Commit: `feat(chart): snapshot export, go-to-date, autoscroll, hotkeys, timezone, light theme`

### Task 8: Wire ranges + tests green (backend ↔ frontend)

**Files:**
- Modify: range enums in stock/report/compare pages (`STK_RANGES`, `CMP_TFS`, report buttons) to include new intervals
- Modify: fixtures if needed

- [ ] Frontend range chips gain 3m/10m/2h/3h/4h where space allows (compare per-cell menu full set; stock page toolbar grouped)
- [ ] `cd web/api && python -m pytest tests -x -q` green; `node --test` UI green
- [ ] Commit: `feat(chart): full interval set wired across report/stock/compare`

### Task 9: Browser verification — desktop + mobile, every tool

**Files:** test evidence under `docs/superpowers/evidence/` (screenshots)

- [ ] Start local server with `TA_STOCK_FIXTURES=1`; desktop 1280×720: exercise style menu (7), scale toggles, ≥10 indicators, all 16 drawing tools + persistence + clear, snapshot download, go-to-date, autoscroll, hotkeys, fullscreen, intervals incl. 3m/10m/2h/4h, compare sync
- [ ] Mobile 390×844: collapsed toolbar usable, touch draw, pinch/wheel zoom, pan, fullscreen; screenshot evidence
- [ ] Snappiness: interaction → paint ≤ ~100 ms feel (no long tasks blocking scroll), fix findings
- [ ] Fix any defects found; re-run suites; commit fixes

### Task 10: Docs + wrap-up

- [ ] `MEMORY.md` entry (v10 migration gotchas encountered), `docs/compare-spec.md` scope table update
- [ ] Final commit; report with evidence
