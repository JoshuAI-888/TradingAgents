# Screener Phase C — UX Parity & Breakdowns Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or superpowers:executing-plans. Checkboxes for tracking.

**Goal:** Ship the Phase C UX bundle: deep-linkable screener state, red/green cells + summary bar, view-tab column presets (+ Custom), preset factor auto-columns, a Groups breakdowns page with drill-through, and the UX polish pack (unit-aware chips, ⓘ tooltips, modal search, filter collapse, My-Presets select).

**Architecture:** All frontend (`web/api/static/index.html`) against the Phase-A/B APIs; no schema or API changes except none. Deep links encode screener state into `location.hash` on every persist and restore at boot. Groups page renders `/api/groups` (exists since Phase A) with CSS bar charts. View presets are column-set constants over the extended `SCR_COLS` catalog.

**Spec:** FEATURE-GAP.md §6 Phase C (items 12–14). **Deferred explicitly:** per-row sparklines (needs a per-symbol kline batch endpoint — recorded as follow-up; everything else in scope ships).

## Global Constraints

- Frontend has no unit test harness — verify each task via the fixture-mode browser walkthrough (server: `SUPABASE_URL=https://example.supabase.co SUPABASE_SERVICE_KEY=dummy TA_STOCK_FIXTURES=1 PORTAL_STATIC_DIR=$PWD/static uvicorn … --port 8901`), plus `node --check` on all script blocks before commit.
- index.html is not WIP-modified → plain staging is safe (no dance needed).
- Commit style `feat(screener): …`.

## Tasks

- [ ] **C1 — Extended catalog + red/green cells + summary bar**: add the ~30 enrichment/technical keys to `SCR_COLS` (kind `num`); color price/%chg/chg cells (cellFmt pct/chg/price → green/red spans); compute ▲/▼ + avg %chg + median cap over the returned page near the result count. Verify in browser; commit.
- [ ] **C2 — View-tab column presets + Custom**: `VIEW_PRESETS` constants (Overview/Valuation/Financial/Ownership/Performance/Technical) + tab strip above the table; click swaps `st.cols` (previous manual set preserved as `custom`); existing picker stays for Custom. Commit.
- [ ] **C3 — Preset factor auto-columns**: `scrApplyPreset` merges the preset's filter fields into `st.cols` (cap 18 cols). Commit.
- [ ] **C4 — Deep links**: `scrPersist()` also writes `location.hash = "#/screener?" + compact-params` (m, src, wo, etfs, f=JSON, s, d, cols, ps); boot parses the hash into `__scr` before first render. Round-trip verified in browser. Commit.
- [ ] **C5 — Groups page**: nav button `Groups`; `pages.groups()` renders group-by select (plate/sector/industry/exchange/cap_bucket), aggregates table (Group · Stocks · Σ Cap · Δ% · ▲/▼ · P/E · Fwd P/E · PEG · Short % · Recom), inline CSS bars for Δ%, drill-through links → screener pre-filtered on that group. Commit.
- [ ] **C6 — Polish pack**: unit-aware chip values (300M/1.2B/%), ⓘ `title` definitions on column headers (FIELD_DEFS dict), Add-Filter modal search box, Filters collapse toggle, My-Presets toolbar select (saved screeners). Commit.

## Self-Review

Maps to spec §6 Phase C items 12–14 minus sparklines (deferred, noted in FEATURE-GAP follow-ups). All data from existing endpoints; no server changes.
