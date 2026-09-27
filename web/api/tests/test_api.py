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
