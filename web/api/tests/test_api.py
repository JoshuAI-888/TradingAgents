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
            if ".eq." in v:
                col, val = k, v.split(".eq.")[1]
                rows = [r for r in rows if str(r.get(col)) == val]
        return rows
    def insert(self, table, row, prefer="return=representation"):
        row = {**row, "id": f"{table}-{len(self._t(table))+1}"}
        self._t(table).append(row)
        return [row]
    def update(self, table, f, row):
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


def test_submit_creates_job_and_dedups():
    r1 = client.post("/api/analyses", json={"ticker": "nvda", "trade_date": "2026-09-26", "depth": "standard"}).json()
    r2 = client.post("/api/analyses", json={"ticker": "NVDA", "trade_date": "2026-09-26", "depth": "standard"}).json()
    assert r1["deduplicated"] is False and r2["deduplicated"] is True
    assert r1["job_id"] == r2["job_id"]
    jobs = api.db._t("jobs")
    assert jobs[0]["payload"]["ticker"] == "NVDA"


def test_queue_candidate_requires_cron_secret():
    r = client.post("/api/candidates/some-id/queue")
    assert r.status_code == 401
