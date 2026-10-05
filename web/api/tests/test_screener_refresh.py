"""Refresh HTTP contract: market isolation and rejected requests do not queue work."""

import copy

import pytest
from fastapi.testclient import TestClient
from tradingagents_api import main as api
from tradingagents_worker.db import Db


class RefreshTransport(Db):
    """Exercise the actual Db adapter's PostgREST JSON-path filter contract."""

    def __init__(self, jobs):
        self.jobs = copy.deepcopy(jobs)
        self.calls = []

    def _call(self, method, path, body=None, query=None, prefer=None):
        self.calls.append((method, path, copy.deepcopy(body), copy.deepcopy(query)))
        assert path == "jobs"
        if method == "GET":
            assert query["job_type"] == "eq.universe_refresh"
            assert query["payload->>market"] in ("eq.US", "eq.HK")
            return [
                copy.deepcopy(job)
                for job in self.jobs
                if job.get("job_type") == "universe_refresh"
                and "eq." + job.get("status", "") == query["status"]
                and "eq." + job.get("payload", {}).get("market", "") == query["payload->>market"]
            ]
        assert method == "POST"
        job = {**body, "id": "new-refresh", "status": "pending"}
        self.jobs.append(job)
        return [copy.deepcopy(job)]


def job(market, status, kind="universe_refresh"):
    return {
        "id": market + "-" + status,
        "job_type": kind,
        "status": status,
        "payload": {"market": market},
    }


@pytest.fixture
def refresh_client(monkeypatch):
    store = RefreshTransport([])
    monkeypatch.setattr(api, "db", store)
    monkeypatch.setenv("DEFAULT_USER_ID", "refresh-owner")
    return TestClient(api.app), store


@pytest.mark.parametrize("market,other", [("US", "HK"), ("HK", "US")])
def test_other_market_jobs_do_not_suppress_refresh(refresh_client, market, other):
    client, store = refresh_client
    store.jobs = [
        job(other, "pending"),
        job(other, "running"),
        job(market, "succeeded"),
        job(market, "failed"),
        job(market, "pending", "analysis"),
    ]
    response = client.post("/api/screener/refresh", params={"market": market, "force": 1})
    assert response.status_code == 200
    assert response.json() == {"queued": True, "job_id": "new-refresh"}
    inserted = store.jobs[-1]
    assert inserted["payload"] == {"market": market, "force": True}
    assert inserted["user_id"] == "refresh-owner"
    assert inserted["idempotency_key"].startswith("universe-refresh:" + market + ":")
    assert sum(call[0] == "POST" for call in store.calls) == 1


@pytest.mark.parametrize("market", ["US", "HK"])
@pytest.mark.parametrize("status", ["pending", "running"])
def test_matching_market_active_job_is_reused(refresh_client, market, status):
    client, store = refresh_client
    store.jobs = [job("HK" if market == "US" else "US", "pending"), job(market, status)]
    response = client.post("/api/screener/refresh", params={"market": market})
    assert response.status_code == 200
    assert response.json() == {
        "queued": True,
        "job_id": market + "-" + status,
        "already_running": True,
    }
    assert all(call[0] == "GET" for call in store.calls)


@pytest.mark.parametrize("market", ["ASX", "us", "", "US,HК", "US&status=eq.running"])
def test_invalid_market_rejected_without_database_access(refresh_client, market):
    client, store = refresh_client
    response = client.post("/api/screener/refresh", params={"market": market})
    assert response.status_code == 400
    assert response.json()["detail"] == "market must be US or HK"
    assert store.calls == []


def test_default_refresh_market_remains_us(refresh_client):
    client, store = refresh_client
    assert client.post("/api/screener/refresh").status_code == 200
    assert store.jobs[-1]["payload"] == {"market": "US"}
