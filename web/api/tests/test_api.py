"""API contract tests (offline): health, meta, submit dedup against fake Db."""
import os
os.environ.setdefault("SUPABASE_URL", "https://example.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "test")
os.environ.setdefault("CRON_SECRET", "cron-test")

from fastapi.testclient import TestClient
from tradingagents_api import main as api

# SETTINGS is a module-level singleton (created before this file set env) — patch it.
api.SETTINGS.supabase_url = "https://example.supabase.co"
api.SETTINGS.supabase_service_key = "test"
api.SETTINGS.cron_secret = "cron-test"


class FakeDb:
    def __init__(self):
        self.tables = {}
    def _t(self, n): return self.tables.setdefault(n, [])
    def select(self, table, query=None, columns="*"):
        rows = [dict(r) for r in self._t(table)]
        for k, v in (query or {}).items():
            if v.startswith("eq."):
                col, val = k, v[3:]
                rows = [r for r in rows if str(r.get(col)) == val]
            elif v.startswith("in.("):
                col, vals = k, set(v[4:-1].split(","))
                rows = [r for r in rows if str(r.get(col)) in vals]
        return rows
    def insert(self, table, row, prefer="return=representation"):
        row = {**row, "id": f"{table}-{len(self._t(table))+1}"}
        self._t(table).append(row)
        return [row]
    def update(self, table, f, row):
        if f.startswith("id=eq."):
            tid = f[len("id=eq."):]
            rows = self._t(table)
            for i, r in enumerate(rows):
                if r.get("id") == tid:
                    rows[i] = {**r, **row}
                    return rows[i]
        return None
    def upsert(self, table, on_conflict, row):
        rows = self._t(table)
        key = row.get(on_conflict)
        for i, r in enumerate(rows):
            if r.get(on_conflict) == key:
                rows[i] = {**r, **row}
                return [rows[i]]
        rows.append({**row})
        return [row]
    def select_all(self, table, query=None, columns="*"):
        # single-user fakes are small; PostgREST pagination is a non-issue here
        return self.select(table, query, columns)

api.db = FakeDb()
client = TestClient(api.app)


def test_health_and_meta():
    assert client.get("/api/health").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert meta["framework"].startswith("tradingagents 0.5.1")
    assert set(meta["markets"]) == {"US", "HK", "ASX"}


def test_settings_stub_roundtrip():
    r = client.put("/api/settings", json={"provider": "openrouter", "quick": "z-ai/glm-5.3-flash",
                                          "deep": "z-ai/glm-5.3-flash", "stub": True})
    assert r.json()["saved"] is True and r.json()["runtime"]["stub"] is True
    s = client.get("/api/settings").json()
    assert s["runtime"]["stub"] is True
    assert client.get("/api/health").json()["stub_mode"] is True
    # flip back off
    client.put("/api/settings", json={"provider": "openrouter", "quick": "qq", "deep": "dd", "stub": False})
    assert client.get("/api/settings").json()["runtime"]["stub"] is False


def test_candidates_refresh_runs_watchlist_sweep():
    r = client.post("/api/candidates/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["refreshed"] is True and body["moomoo"] is False
    assert body["candidates_stored"] >= 1  # watchlist sweep always yields candidates


def test_report_by_job_and_by_decision():
    j = client.post("/api/analyses", json={"ticker": "AAPL", "trade_date": "2026-09-25", "depth": "fast"}).json()
    api.db._t("runs").append({"id": "run-1", "job_id": j["job_id"], "user_id": None, "ticker_id": "tick-1",
                              "trade_date": "2026-09-25", "config_hash": "abc", "status": "succeeded",
                              "prompt_tokens": 10, "completion_tokens": 5, "cost_usd": 0.01,
                              "framework_version": "0.5.1"})
    api.db._t("tickers").append({"id": "tick-1", "symbol": "AAPL", "name": "Apple", "exchange": "NASDAQ", "currency": "USD"})
    api.db._t("agent_reports").append({"run_id": "run-1", "stage": "trader", "content_markdown": "buy", "quality_grade": "A"})
    api.db._t("decisions").append({"id": "dec-1", "run_id": "run-1", "ticker_id": "tick-1",
                                   "trade_date": "2026-09-25", "rating": "buy", "rating_rank": 5,
                                   "signal": "buy", "is_review": False, "full_decision": {},
                                   "qc_verdict": "passed"})
    api.db._t("run_digest").append({"run_id": "run-1", "model": "z-ai/glm-5.3-flash",
                                    "digest": {"evidence": [{"claim": "capex up", "stage": "fundamentals",
                                                             "support": "+48%"}],
                                               "scenarios": {}, "news": [], "qc": []}})
    # by job id
    r = client.get(f"/api/analyses/{j['job_id']}/report").json()
    assert r["ticker"]["symbol"] == "AAPL" and r["run"]["id"] == "run-1"
    assert r["reports"][0]["stage"] == "trader" and r["decision"]["id"] == "dec-1"
    assert r["digest"]["digest"]["evidence"][0]["claim"] == "capex up"
    # by decision id (ledger rows link this way)
    r2 = client.get("/api/analyses/dec-1/report").json()
    assert r2["run"]["id"] == "run-1"
    # review endpoint
    rr = client.post("/api/decisions/dec-1/review", json={"user_rating": "agree"})
    assert rr.json()["saved"] is True
    assert api.db._t("decisions")[-1]["user_rating"] == "agree"
    # bars endpoint (unknown symbol → 404)
    assert client.get("/api/bars/NOPE").status_code == 404
    # spend block reflects the seeded run
    m = client.get("/api/meta").json()
    assert m["spend"]["runs"] >= 1 and m["spend"]["cost_usd"] >= 0.01


def test_screener_pagination_and_exports(monkeypatch):
    monkeypatch.setattr(api, "_screener_cache", None)
    monkeypatch.setattr(api, "_market_client", lambda: _FakeMoomoo())
    monkeypatch.setattr(api, "_watchlist_symbols", lambda: ["SPY", "XLK"])
    # offset paging
    p1 = client.get("/api/screener?watchlist_only=1&limit=1&offset=0").json()
    p2 = client.get("/api/screener?watchlist_only=1&limit=1&offset=1").json()
    assert p1["rows"][0]["symbol"] != p2["rows"][0]["symbol"]
    assert p1["matched"] == p2["matched"] == 2 and p1["offset"] == 0 and p2["offset"] == 1
    # CSV export: all matched rows, header + BOM, attachment disposition
    r = client.get("/api/screener?watchlist_only=1&export=csv")
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers.get("content-disposition", "")
    body = r.content.decode("utf-8-sig")
    lines = [l for l in body.strip().split("\n") if l]
    assert len(lines) == 3 and lines[0].startswith("symbol") and "SPY" in body
    # Excel export: SpreadsheetML with typed cells
    x = client.get("/api/screener?watchlist_only=1&export=xls")
    assert "vnd.ms-excel" in x.headers.get("content-type", "")
    assert b"Workbook" in x.content and b"ss:Type=" in x.content


def test_submit_creates_job_and_dedups():
    r1 = client.post("/api/analyses", json={"ticker": "nvda", "trade_date": "2026-09-26", "depth": "standard"}).json()
    r2 = client.post("/api/analyses", json={"ticker": "NVDA", "trade_date": "2026-09-26", "depth": "standard"}).json()
    assert r1["deduplicated"] is False and r2["deduplicated"] is True
    assert r1["job_id"] == r2["job_id"]
    jobs = api.db._t("jobs")
    assert any(j["payload"]["ticker"] == "NVDA" for j in jobs)


def test_queue_candidate_requires_cron_secret():
    r = client.post("/api/candidates/some-id/queue")
    assert r.status_code == 401


def test_active_jobs_lists_pending_and_running_only():
    api.db._t("jobs").append({"id": "j-pend", "status": "pending",
                              "payload": {"ticker": "META", "depth": "standard"},
                              "created_at": "2026-09-27T04:44:32Z"})
    api.db._t("jobs").append({"id": "j-run", "status": "running",
                              "payload": {"ticker": "NVDA", "depth": "fast"},
                              "created_at": "2026-09-27T03:00:00Z"})
    api.db._t("jobs").append({"id": "j-done", "status": "succeeded",
                              "payload": {"ticker": "AAPL", "depth": "fast"},
                              "created_at": "2026-09-26T20:00:00Z"})
    ids = {j["id"] for j in client.get("/api/jobs/active").json()["jobs"]}
    assert {"j-pend", "j-run"} <= ids and "j-done" not in ids


class _FakeMoomoo:
    def snapshot(self, codes):
        return {"snapshot_list": [
            {"code": "US.SPY", "last_price": 682.14, "prev_close_price": 679.3,
             "update_time": 1790380957281},
            {"code": "US.XLK", "last_price": 240.0, "pct_change": 1.6,
             "update_time": 1790380957281},
        ]}

    def econ_calendar_hot(self):
        return [{"event_text": "US CPI YoY", "country": "US", "star": 3,
                 "event_time": 1789000000, "predictive": "2.9", "announce": ""}]


def test_market_state_builds_or_reports_unavailable(monkeypatch):
    monkeypatch.setattr(api, "_market_cache", None)
    monkeypatch.setattr(api, "_market_client", lambda: _FakeMoomoo())
    r = client.get("/api/market/state").json()
    assert r["available"] is True
    spy = next(i for i in r["indices"] if i["symbol"] == "SPY")
    assert spy["name"] == "S&P 500" and spy["last"] == 682.14
    assert spy["pct"] == 0.42  # computed from prev close when pct_change is null
    assert "T00:00" in spy["as_of"] or "T" in spy["as_of"]  # ISO stamp
    assert any(s["symbol"] == "XLK" and s["pct"] == 1.6 for s in r["sectors"])
    assert r["calendar"][0]["event"] == "US CPI YoY"

    monkeypatch.setattr(api, "_market_cache", None)
    monkeypatch.setattr(api, "_market_client", lambda: None)
    r2 = client.get("/api/market/state").json()
    assert r2["available"] is False and "not configured" in r2["reason"]


def test_screener_filters_and_sort():
    rows = [
        {"symbol": "AAA", "name": "Alpha", "price": 150, "pct": 2.5, "chg": 3.7, "market_cap": 2e11,
         "volume": 1e6, "pe_ttm": 30, "pb": 5, "volume_ratio": 1.4, "turnover_rate": 2.1, "div_yield": 0.5},
        {"symbol": "BBB", "name": "Beta", "price": 4, "pct": -1.2, "chg": -0.05, "market_cap": 8e8,
         "volume": 5e5, "pe_ttm": 8, "pb": 0.7, "volume_ratio": 2.2, "turnover_rate": 5.0, "div_yield": 6.0},
        {"symbol": "CCC", "name": "Gamma", "price": 60, "pct": 0.0, "chg": 0.0, "market_cap": 5e9,
         "volume": 2e6, "pe_ttm": 12, "pb": 1.2, "volume_ratio": 0.9, "turnover_rate": 1.0, "div_yield": None},
    ]
    got, skipped = api._apply_filters(rows, [{"field": "price", "max": 5}])
    assert [r["symbol"] for r in got] == ["BBB"] and skipped == []
    got, skipped = api._apply_filters(rows, [{"field": "pb", "min": 0.01, "max": 1}])
    assert [r["symbol"] for r in got] == ["BBB"]
    # a field absent from the universe SKIPS its filter instead of failing all rows
    got, skipped = api._apply_filters(rows, [{"field": "rsi14", "max": 30}])
    assert len(got) == 3 and skipped == ["rsi14"]
    # Buffett-style triple filter: none of the sample rows pass all three
    buffett, skipped = api._apply_filters(rows, [{"field": "market_cap", "min": 1e10},
                                                 {"field": "pe_ttm", "min": 0.01, "max": 15},
                                                 {"field": "div_yield", "min": 1}])
    assert buffett == [] and skipped == []
    assert [r["symbol"] for r in api._sort_rows(rows, "pct", 2)] == ["AAA", "CCC", "BBB"]
    # None-valued fields sort last regardless of direction
    desc = api._sort_rows([{"symbol": "X", "pe_ttm": None}] + rows, "pe_ttm", 2)
    assert desc[-1]["symbol"] == "X"


def test_values_multiselect_and_facets(monkeypatch):
    rows = [{"symbol": "A", "stock_type": "STOCK", "plate": "Software"},
            {"symbol": "B", "stock_type": "ETF", "plate": "ETFs"},
            {"symbol": "C", "stock_type": None, "plate": None}]
    got, skipped = api._apply_filters(rows, [{"field": "stock_type", "values": ["stock", "etf"]}])
    assert [r["symbol"] for r in got] == ["A", "B"] and skipped == []  # case-insensitive
    got2, _ = api._apply_filters(rows, [{"field": "stock_type", "values": ["WARRANT"]}])
    assert got2 == []
    got3, sk3 = api._apply_filters(rows, [{"field": "absent_field", "values": ["X"]}])
    assert len(got3) == 3 and sk3 == ["absent_field"]  # absent field skips, not fails


def test_snapshot_to_row_normalizes():
    row = api._snapshot_to_row({"code": "US.SPY", "name": "SPDR S&P 500 ETF", "last_price": 682.14,
                                "prev_close_price": 679.3, "pct_change": None,
                                "total_market_val": 8.17e11, "volume_ratio": 0.7})
    assert row["symbol"] == "SPY" and row["price"] == 682.14
    assert row["pct"] == 0.42  # prev-close fallback
    assert row["chg"] == 2.84
    assert row["market_cap"] == 8.17e11 and row["volume_ratio"] == 0.7


def test_screener_endpoint_watchlist_universe(monkeypatch):
    monkeypatch.setattr(api, "_screener_cache", None)
    monkeypatch.setattr(api, "_market_client", lambda: _FakeMoomoo())
    monkeypatch.setattr(api, "_watchlist_symbols", lambda: ["SPY", "XLK"])
    r = client.get("/api/screener?watchlist_only=1").json()
    assert r["available"] is True and r["universe"] == "watchlist"
    assert r["count"] == 2 and r["watchlist"] == ["SPY", "XLK"]
    assert {row["symbol"] for row in r["rows"]} == {"SPY", "XLK"}
    # presets endpoint returns all 15 recommended screeners with top-3 structure
    p = client.get("/api/screener/presets?market=US&page=1").json()
    names = [x["name"] for x in p["presets"]]
    assert "Penny Stocks" in names and "Warren Buffett Strategy" in names
    assert all(len(x["top"]) <= 3 for x in p["presets"])


class _SlicedMoomoo:
    """stock-screen returning 300 unique codes per call (no pagination cursor,
    like the live API) + batched snapshot."""

    def __init__(self):
        self.screen_calls = 0

    def call(self, method, path, body=None, query=None, retries=2):
        self.screen_calls += 1
        start = (self.screen_calls - 1) * 300
        page = [{"code": f"US.S{i:04d}"} for i in range(start, start + 300)]
        return {"items": page}

    def snapshot(self, codes):
        return {"snapshot_list": [{"code": c, "name": c.split(".")[1], "last_price": 10.0,
                                   "prev_close_price": 9.5} for c in codes]}


def test_market_rows_unions_sort_slices(monkeypatch):
    mm = _SlicedMoomoo()
    monkeypatch.setattr(api, "_screener_cache", None)
    rows = api._market_rows("US", "price", 1, mm)
    assert len(rows) == 1200            # 4 sorts x 300 unique
    assert mm.screen_calls == 4
    assert rows[0]["symbol"] == "S0000" and rows[-1]["symbol"] == "S1199"
    # primary slice (caller's sort) leads the ordering
    assert [r["symbol"] for r in rows[:3]] == ["S0000", "S0001", "S0002"]


class _NoCache:
    """_merge_universe_meta's TtlCache is disk-backed (persists across pytest
    runs) — tests inject this so classification reads come from the fake db."""
    def key(self, *a): return "k"
    def get(self, *a): return None
    def put(self, *a): pass


def test_presets_rail_scores_stored_rows_without_inline_stock_type(monkeypatch):
    """Regression 2026-09-29: stored quote rows carry no stock_type (classification
    lives in screener_universe), so filtering before merging dropped every row and
    the rail showed 'no matches in universe' with '0 rows scored'."""
    monkeypatch.setattr(api, "_screener_cache", None)
    monkeypatch.setattr(api, "_universe_meta_cache", _NoCache())
    api.db._t("screener_quotes").append({"market": "US", "code": "US.ZPST",
                                         "row": {"code": "US.ZPST", "symbol": "ZPST",
                                                 "name": "Zerostate", "pct": 4.2}})
    api.db._t("screener_universe").append({"market": "US", "code": "US.ZPST",
                                           "stock_type": "STOCK"})
    p = client.get("/api/screener/presets?market=US").json()
    assert p["universe_rows"] >= 1
    tops = [t for x in p["presets"] for t in x["top"]]
    assert any(t["symbol"] == "ZPST" and t["pct"] == 4.2 for t in tops)


def test_execute_hydrates_rows_from_stored_snapshot(monkeypatch):
    """Regression 2026-09-29: stock-screen retrieves returned null for every item,
    leaving preset tables all dashes — display values fill from the snapshot."""

    class _NullScreen:
        def call(self, method, path, body=None, query=None, retries=2):
            return {"items": [{"code": "US.ZEXE", "name": "Zexecute",
                               "results": [{"simple_property_result": {
                                   "property": {"name": 2201}, "ival": None}}]},
                              {"code": "US.ZOTC", "name": "Zotc Otc", "results": []}]}

        def snapshot(self, codes):
            return {"snapshot_list": [{"code": c, "last_price": 1.5, "pct_change": -1200}
                                      for c in codes]}

    monkeypatch.setattr(api, "_market_client", lambda: _NullScreen())
    monkeypatch.setattr(api, "_universe_meta_cache", _NoCache())
    api.db._t("screener_quotes").append({"market": "US", "code": "US.ZEXE",
                                         "row": {"code": "US.ZEXE", "symbol": "ZEXE", "price": 3.21,
                                                 "pct": -1.4, "market_cap": 2.5e8}})
    api.db._t("screener_universe").append({"market": "US", "code": "US.ZEXE",
                                           "stock_type": "STOCK", "plate": "Biotech",
                                           "exchange": "US"})
    r = client.get("/api/screener/execute?key=penny&market=US").json()
    assert r["available"] is True and len(r["rows"]) == 2
    row = r["rows"][0]
    assert row["price"] == 3.21 and row["pct"] == -1.4 and row["market_cap"] == 2.5e8
    assert row["stock_type"] == "STOCK" and row["plate"] == "Biotech"
    # ZOTC isn't stored (enumeration-missed OTC tail) — live snapshot fallback
    otc = r["rows"][1]
    assert otc["symbol"] == "ZOTC" and otc["price"] == 1.5 and otc["pct"] == -1200.0


def test_prompt_store_roundtrip():
    api.db._t("prompt_versions").append({"agent_key": "trader", "version": 1,
                                         "note": "engine stock prompt", "created_at": "t",
                                         "content": "stock trader prompt"})
    trader = next(a for a in client.get("/api/prompts").json()["agents"] if a["key"] == "trader")
    assert trader["active_version"] is None
    assert trader["default_content"] == "stock trader prompt"
    assert trader["active_content"] == "stock trader prompt"  # falls back to stock
    r = client.post("/api/prompts/trader/versions",
                    json={"content": "custom prompt {grounding}", "note": "tighter risk language"}).json()
    assert r["saved"] is True and r["version"] == 2
    trader = next(a for a in client.get("/api/prompts").json()["agents"] if a["key"] == "trader")
    assert trader["active_version"] == 2 and trader["active_content"] == "custom prompt {grounding}"
    assert client.put("/api/prompts/trader/active", json={"version": 1}).json()["active_version"] == 1
    assert client.put("/api/prompts/trader/active", json={"version": None}).json()["active_version"] is None
    assert client.post("/api/prompts/nope/versions", json={"content": "x"}).status_code == 404
    assert client.put("/api/prompts/trader/active", json={"version": 99}).status_code == 404


def test_status_includes_queue_context():
    r = client.post("/api/analyses", json={"ticker": "MSFT", "trade_date": "2026-09-29", "depth": "fast"})
    # FakeDb has no column defaults: mirror the jobs table's `status default 'pending'`.
    next(j for j in api.db._t("jobs") if j["id"] == r.json()["job_id"])["status"] = "pending"
    body = client.get(f"/api/analyses/{r.json()['job_id']}").json()
    assert body["job"]["status"] == "pending"
    q = body["queue"]
    assert q["position"] == 1 and q["ahead"] == 0
    assert q["eta_seconds"] is None and q["worker_alive"] in (None, True, False)


def test_report_repairs_mangled_debate_rows():
    j = client.post("/api/analyses", json={"ticker": "TSLA", "trade_date": "2026-09-25", "depth": "fast"}).json()
    api.db._t("runs").append({"id": "run-d", "job_id": j["job_id"], "user_id": None, "ticker_id": "tick-d",
                              "trade_date": "2026-09-25", "config_hash": "abc", "status": "succeeded",
                              "prompt_tokens": 10, "completion_tokens": 5, "cost_usd": 0.01,
                              "framework_version": "0.5.1"})
    api.db._t("tickers").append({"id": "tick-d", "symbol": "TSLA", "name": "Tesla"})
    # a real transcript is thousands of chars; the repair detector ignores short runs
    letters = "Bull Analyst: the bull case rests on margin expansion and backlog growth through 2027."
    api.db._t("debate_messages").append({"run_id": "run-d", "debate_type": "research",
                                         "speaker": "neutral", "round": 1,
                                         "content": "\n\n".join(c for c in letters if c.strip())})
    api.db._t("debate_messages").append({"run_id": "run-d", "debate_type": "risk",
                                         "speaker": "neutral", "round": 1,
                                         "content": "Aggressive Analyst: keep it\n\nall on one line"})
    r = client.get(f"/api/analyses/{j['job_id']}/report").json()
    research = [d for d in r["debates"] if d["debate_type"] == "research"][0]
    risk = [d for d in r["debates"] if d["debate_type"] == "risk"][0]
    assert research["content"] == "BullAnalyst:thebullcaserestsonmarginexpansionandbackloggrowththrough2027."  # spaces were lost at write time
    assert risk["content"] == "Aggressive Analyst: keep it\n\nall on one line"  # normal row untouched


def test_submit_validates_symbol_with_suggestion(monkeypatch):
    api._universe_symbols_cache = (0.0, {})  # reset the 5-min cache
    api.db._t("screener_universe").append({"market": "US", "code": "US.NVDA", "stock_type": "STOCK"})
    r = client.post("/api/analyses", json={"ticker": "ndva", "trade_date": "2026-09-29", "depth": "fast"}).json()
    assert r["validation"]["known"] is False
    assert r["validation"]["suggestion"] == "NVDA"
    assert "did you mean NVDA" in r["validation"]["note"]
    assert r["job_id"]  # soft check: the run is still enqueued
    r2 = client.post("/api/analyses", json={"ticker": "NVDA", "trade_date": "2026-09-29", "depth": "fast"}).json()
    assert r2["validation"]["known"] is True
    # dedup path carries the check too
    r3 = client.post("/api/analyses", json={"ticker": "NVDA", "trade_date": "2026-09-29", "depth": "fast"}).json()
    assert r3["deduplicated"] is True and r3["validation"]["known"] is True


def test_schedule_reports_stock_breakdown():
    api.db._t("screener_universe").append({"market": "US", "code": "US.SPY", "stock_type": "ETF"})
    s = client.get("/api/screener/schedule").json()
    assert s["stock_rows"] >= 1 and s["other_rows"] >= 1 and s["universe_rows"] >= s["stock_rows"] + s["other_rows"]


def test_report_degrades_without_content_original_column():
    class _NoColDb(api.FakeDb if hasattr(api, "FakeDb") else object):
        pass
    # a db whose debate_messages select rejects content_original (migration 0010 not applied)
    class _PreMigrationDb:
        def __init__(self, base):
            self.base = base
        def __getattr__(self, name):
            return getattr(self.base, name)
        def select(self, table, query=None, columns="*"):
            if table == "debate_messages" and "content_original" in columns:
                raise RuntimeError('supabase GET debate_messages -> 400: column "content_original" does not exist')
            return self.base.select(table, query, columns)
    j = client.post("/api/analyses", json={"ticker": "ZZZPLS", "trade_date": "2026-09-25", "depth": "fast"}).json()
    api.db._t("runs").append({"id": "run-nocol", "job_id": j["job_id"], "user_id": None, "ticker_id": "tick-1",
                              "trade_date": "2026-09-25", "config_hash": "abc", "status": "succeeded",
                              "prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 0.0,
                              "framework_version": "0.5.1"})
    api.db._t("debate_messages").append({"run_id": "run-nocol", "debate_type": "risk",
                                         "speaker": "neutral", "round": 1, "content": "Aggressive Analyst: go."})
    outer = api.db
    api.db = _PreMigrationDb(outer)
    try:
        r = client.get(f"/api/analyses/{j['job_id']}/report")
        assert r.status_code == 200, r.text
        assert r.json()["debates"][0]["content"] == "Aggressive Analyst: go."
        assert r.json()["debates"][0]["content_original"] is None
    finally:
        api.db = outer


def test_report_surfaces_real_error_not_bare_500():
    class _BrokenDb:
        def __getattr__(self, name):
            raise RuntimeError("db down")
    outer = api.db
    api.db = _BrokenDb()
    try:
        r = client.get("/api/analyses/some-ref/report")
        assert r.status_code == 502
        assert "report data unavailable" in r.json()["detail"]
    finally:
        api.db = outer

def _fresh_caches(monkeypatch):
    """Per-test TTL caches: the default root is disk-backed and shared, so a
    plain cache reset leaks rows across tests within the 5-minute TTL."""
    import os as _os
    import tempfile as _tempfile
    from tradingagents_worker.ttl_cache import TtlCache as _Ttl
    root = _tempfile.mkdtemp(prefix="ta-test-ttl-")
    monkeypatch.setattr(api, "_screener_cache", _Ttl(root=_os.path.join(root, "scr")))
    monkeypatch.setattr(api, "_universe_meta_cache", _Ttl(root=_os.path.join(root, "meta")))
    monkeypatch.setattr(api, "_groups_cache", _Ttl(root=_os.path.join(root, "grp")),
                         raising=False)


# ── src=moo|yf enrichment mode (Phase A task 7) ──────────────────────────────
def _seed_enrichment_rows(fdb):
    for code, sym in (("US.AAPL", "AAPL"), ("US.MSFT", "MSFT")):
        fdb._t("screener_universe").append(
            {"code": code, "market": "US", "plate": "Tech",
             "stock_type": "STOCK", "exchange": "NASDAQ"})
    fdb._t("screener_quotes").append(
        {"code": "US.AAPL", "market": "US", "updated_at": "2025-01-01T00:00:00+00:00",
         "row": {"symbol": "AAPL", "name": "Apple", "price": 200.0, "pe_ttm": 30.0}})
    fdb._t("screener_quotes").append(
        {"code": "US.MSFT", "market": "US", "updated_at": "2025-01-01T00:00:00+00:00",
         "row": {"symbol": "MSFT", "name": "Microsoft", "price": 400.0, "pe_ttm": 33.0}})
    fdb._t("screener_enrichment").append(
        {"code": "US.AAPL", "market": "US", "as_of": "2025-01-02T00:00:00+00:00",
         "data": {"forward_pe": 28.0, "beta": 1.2}})
    fdb._t("screener_enrichment").append(
        {"code": "US.MSFT", "market": "US", "as_of": "2025-01-02T00:00:00+00:00",
         "data": {"forward_pe": 31.0}})


def test_screener_default_moo_excludes_enrichment(monkeypatch):
    _fresh_caches(monkeypatch)
    monkeypatch.setattr(api, "_market_client", lambda: object())
    fdb = FakeDb()
    _seed_enrichment_rows(fdb)
    api.db = fdb
    r = client.get("/api/screener?watchlist_only=0&src=moo").json()
    assert r["available"] and r["enrich_as_of"] is None
    assert all("forward_pe" not in row for row in r["rows"])


def test_screener_yf_mode_merges_and_stamps(monkeypatch):
    _fresh_caches(monkeypatch)
    monkeypatch.setattr(api, "_market_client", lambda: object())
    fdb = FakeDb()
    _seed_enrichment_rows(fdb)
    api.db = fdb
    r = client.get("/api/screener?watchlist_only=0&src=yf").json()
    assert r["enrich_as_of"] == "2025-01-02T00:00:00+00:00"
    by = {row["symbol"]: row for row in r["rows"]}
    assert by["AAPL"]["forward_pe"] == 28.0 and by["AAPL"]["beta"] == 1.2
    assert by["MSFT"]["forward_pe"] == 31.0 and "beta" not in by["MSFT"]  # absent, not zero


def test_yf_only_filter_skipped_in_moo_mode(monkeypatch):
    _fresh_caches(monkeypatch)
    monkeypatch.setattr(api, "_market_client", lambda: object())
    fdb = FakeDb()
    _seed_enrichment_rows(fdb)
    api.db = fdb
    import json as _json
    flt = _json.dumps([{"field": "forward_pe", "min": 25.0}])
    r = client.get(f"/api/screener?watchlist_only=0&src=moo&filters={flt}").json()
    assert any("forward_pe" in s and "src=yf" in s for s in r["skipped_filters"])
    r2 = client.get(f"/api/screener?watchlist_only=0&src=yf&filters={flt}").json()
    assert r2["skipped_filters"] == [] and r2["matched"] == 2


# ── /api/groups — Finviz-style group aggregates (Phase A task 8) ─────────────
def test_groups_aggregates(monkeypatch):
    _fresh_caches(monkeypatch)
    monkeypatch.setattr(api, "_market_client", lambda: object())
    fdb = FakeDb()
    _seed_enrichment_rows(fdb)
    api.db = fdb
    r = client.get("/api/groups?group_by=plate").json()
    assert r["available"] and r["group_by"] == "plate"
    row = r["rows"][0]
    assert row["key"] == "Tech" and row["stocks"] == 2
    assert row["avgs"]["pe_ttm"] == 31.5                      # mean over non-null
    assert row["avgs"]["forward_pe"] == 29.5
    assert "peg" not in row["avgs"]                            # absent for whole group
    assert r["as_of"] == "2025-01-01T00:00:00+00:00"


def test_groups_cap_bucket_grouping(monkeypatch):
    _fresh_caches(monkeypatch)
    monkeypatch.setattr(api, "_market_client", lambda: object())
    fdb = FakeDb()
    _seed_enrichment_rows(fdb)
    for code, cap in (("US.AAPL", 3.0e12), ("US.MSFT", 3.0e12)):
        qrow = next(q for q in fdb._t("screener_quotes") if q["code"] == code)
        qrow["row"]["market_cap"] = cap
        qrow["row"]["pct"] = 1.0 if code == "US.AAPL" else -1.0
    api.db = fdb
    r = client.get("/api/groups?group_by=cap_bucket").json()
    assert r["rows"][0]["key"] == "mega (≥200B)" and r["rows"][0]["stocks"] == 2
    assert r["rows"][0]["adv"] == 1 and r["rows"][0]["decl"] == 1


def test_groups_empty_universe(monkeypatch):
    _fresh_caches(monkeypatch)
    monkeypatch.setattr(api, "_market_client", lambda: object())
    api.db = FakeDb()
    r = client.get("/api/groups").json()
    assert r["available"] is False and "loader" in r["reason"]


def test_concepts_filter_matches_list_membership(monkeypatch):
    """Phase B: concepts is a list field; values[] filters match ANY overlap."""
    _fresh_caches(monkeypatch)
    monkeypatch.setattr(api, "_market_client", lambda: object())
    fdb = FakeDb()
    _seed_enrichment_rows(fdb)
    for u in fdb._t("screener_universe"):
        u["plates"] = ["Tech", "AI Computing"] if u["code"] == "US.AAPL" else ["Tech"]
    api.db = fdb
    import json as _json
    flt = _json.dumps([{"field": "concepts", "values": ["ai computing"]}])
    r = client.get(f"/api/screener?watchlist_only=0&src=moo&filters={flt}").json()
    assert [row["symbol"] for row in r["rows"]] == ["AAPL"]   # case-insensitive overlap
    assert r["matched"] == 1


def test_moo_mode_still_serves_concepts(monkeypatch):
    _fresh_caches(monkeypatch)
    monkeypatch.setattr(api, "_market_client", lambda: object())
    fdb = FakeDb()
    _seed_enrichment_rows(fdb)
    for u in fdb._t("screener_universe"):
        u["plates"] = ["Tech", "AI Computing"]
    api.db = fdb
    r = client.get("/api/screener?watchlist_only=0&src=moo").json()
    assert all("concepts" in row for row in r["rows"])        # taxonomy is moo-carried
