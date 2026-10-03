"""Offline-first test fixtures: a fake Supabase (in-memory) + stub runner.

No network, no keys — the DoThatKarma ADR-0003 discipline.
"""

from __future__ import annotations

import pytest
from tradingagents_worker.db import Db


class FakeSupa(Db):
    """Records calls; implements just enough for service.settle/queue flows."""

    def __init__(self):
        self.tables: dict[str, list] = {}
        self.calls: list[tuple] = []

    def _t(self, name):
        return self.tables.setdefault(name, [])

    def insert(self, table, row, prefer="return=representation"):
        self.calls.append(("insert", table, row))
        row = {**row, "id": row.get("id") or f"{table}-id-{len(self._t(table)) + 1}"}
        self._t(table).append(row)
        return [row] if "representation" in prefer else None

    def update(self, table, filter, row):
        self.calls.append(("update", table, filter, row))
        col, _, val = filter.partition("=eq.")
        for r in self._t(table):
            if str(r.get(col)) == val:
                r.update({k: v for k, v in row.items() if v != "now()"})
        return None

    def upsert(self, table, on_conflict, row):
        self.calls.append(("upsert", table, on_conflict, row))
        rows = self._t(table)
        keys = [k.strip() for k in on_conflict.split(",")]  # compound keys: "market,code"
        for r in rows:
            if all(str(r.get(k)) == str(row.get(k)) for k in keys):
                r.update(row)
                return
        rows.append(dict(row))

    def upsert_many(self, table, on_conflict, rows, chunk=400):
        self.calls.append(("upsert_many", table, on_conflict, len(rows)))
        for row in rows:
            self.upsert(table, on_conflict, row)
        return len(rows)

    def select(self, table, query=None, columns="*"):
        self.calls.append(("select", table, query))
        if table == "screener_generation_display_rows":
            rows = []
            for record in self._t("screener_generation_rows"):
                row = dict(record["row"])
                observations = row.get("field_observations", {})
                row["field_observations"] = {
                    key: value
                    for key, value in observations.items()
                    if isinstance(value, dict) and isinstance(value.get("currency"), str)
                }
                rows.append({**record, "row": row})
        else:
            rows = [dict(r) for r in self._t(table)]
        for k, v in (query or {}).items():
            if k == "order":
                col, _, direction = v.partition(".")
                rows.sort(key=lambda r: str(r.get(col, "")), reverse=direction == "desc")
            elif k == "limit" or k == "offset":
                continue
            elif v.startswith("eq."):
                rows = [r for r in rows if str(r.get(k)) == v[3:]]
            elif v.startswith("in.("):
                vals = set(v[4:-1].split(","))
                rows = [r for r in rows if str(r.get(k)) in vals]
            elif v.startswith("lte."):
                rows = [r for r in rows if str(r.get(k)) <= v[4:]]
            elif v.startswith("neq."):
                rows = [r for r in rows if str(r.get(k)) != v[4:]]
        offset = int((query or {}).get("offset", 0))
        limit = int((query or {}).get("limit", len(rows)))
        return rows[offset : offset + limit]

    def claim_job(self, worker_id, types=None):
        for j in self._t("jobs"):
            if j.get("status") == "pending":
                j["status"] = "running"
                j["locked_by"] = worker_id
                j["attempts"] = j.get("attempts", 0) + 1
                return j
        return None

    def finish_job(self, job_id, status, error=None, run_id=None):
        self.update("jobs", f"id=eq.{job_id}", {"status": status, "last_error": error})

    def requeue_job(self, job_id, error):
        self.update("jobs", f"id=eq.{job_id}", {"status": "pending", "last_error": error})


@pytest.fixture()
def fake_db():
    return FakeSupa()


@pytest.fixture()
def analysis_job(fake_db):
    job = {
        "id": "job-1",
        "job_type": "analysis",
        "user_id": "user-1",
        "status": "running",
        "payload": {"ticker": "NVDA", "trade_date": "2026-09-26", "depth": "standard"},
    }
    fake_db._t("jobs").append(job)
    fake_db._t("tickers").append({"id": "tick-1", "symbol": "NVDA"})
    return job
