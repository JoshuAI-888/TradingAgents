"""Verified price context: snapshot build, runner injection, digest storage.

Offline-first: the engine's snapshot module is faked via sys.modules so no
test reaches yfinance; a sys.modules None-entry proves the graceful fallback
when the engine is not installed.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from tradingagents_worker import digest
from tradingagents_worker.price_context import build_price_context

# The engine normally runs on the deployed worker; the wiring test below needs
# its package importable, so put the repo root on sys.path (the web venv carries
# the engine deps — stockstats/langgraph were installed for engine-side tests).
_ROOT = str(Path(__file__).resolve().parents[3])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

SNAP_TEXT = "## Verified market data snapshot for NVDA\n\n| Close | 178.05 |"
SNAP_ROWS = [{"date": "2026-09-26", "open": 176.0, "high": 179.0, "low": 175.0,
              "close": 178.05, "volume": 123456}]


def _fake_snapshot_module(monkeypatch, fn):
    mod = SimpleNamespace(snapshot_with_rows=fn)
    monkeypatch.setitem(sys.modules, "tradingagents.dataflows.vendors.yahoo.snapshot", mod)


def test_build_price_context_returns_text_rows_and_latest(monkeypatch):
    _fake_snapshot_module(monkeypatch, lambda sym, date: {
        "text": SNAP_TEXT, "rows": SNAP_ROWS, "latest_date": "2026-09-26"})
    out = build_price_context("NVDA", "2026-09-26")
    assert out == {"text": SNAP_TEXT, "rows": SNAP_ROWS, "latest_date": "2026-09-26"}


def test_build_price_context_survives_vendor_errors(monkeypatch):
    def boom(sym, date):
        raise RuntimeError("yfinance down")
    _fake_snapshot_module(monkeypatch, boom)
    assert build_price_context("NVDA", "2026-09-26") is None


def test_build_price_context_without_rows_is_none(monkeypatch):
    _fake_snapshot_module(monkeypatch, lambda sym, date: {"text": SNAP_TEXT, "rows": []})
    assert build_price_context("NVDA", "2026-09-26") is None


def test_build_price_context_without_engine_is_none(monkeypatch):
    # None in sys.modules → "from … import" raises ImportError → graceful None.
    monkeypatch.setitem(sys.modules, "tradingagents.dataflows.vendors.yahoo.snapshot", None)
    assert build_price_context("NVDA", "2026-09-26") is None


class _RecorderDb:
    def insert(self, table, row, prefer="return=minimal"):
        return None


def test_stub_runner_accepts_and_ignores_price_context():
    from tradingagents_worker.events import Emitter
    from tradingagents_worker.runner import StubRunner

    out = StubRunner().run("NVDA", "2026-09-26", "standard", None,
                           Emitter(_RecorderDb(), "j"), price_context=SNAP_TEXT)
    assert out["signal"] == "buy" and "verified_snapshot" not in (out.get("reports") or {})


def test_engine_runner_forwards_price_context_to_propagate(monkeypatch):
    from tradingagents_worker import llm_usage
    from tradingagents_worker.runner import EngineRunner

    captured = {}

    def fake_propagate(ticker, trade_date, on_node=None, price_context=""):
        captured["price_context"] = price_context
        return {"market_report": "m", "sentiment_report": "", "news_report": "",
                "fundamentals_report": "", "trader_investment_plan": "t",
                "investment_debate_state": {"history": ""},
                "risk_debate_state": {"history": ""},
                "final_trade_decision": "d"}, "Buy"

    monkeypatch.setattr(EngineRunner, "_ensure_graph",
                        lambda self, depth: SimpleNamespace(propagate=fake_propagate))
    monkeypatch.setattr(llm_usage, "reconcile",
                        lambda totals, handler_totals, model: {"prompt": 0, "completion": 0, "cost_usd": 0.0})
    monkeypatch.setattr(llm_usage, "install", lambda: None)
    emitted = []

    class _E:
        def emit(self, *a, **k):
            emitted.append(a)

        def stage_done(self, *a, **k):
            emitted.append(a)

    runner = EngineRunner()
    out = runner.run("NVDA", "2026-09-26", "standard", None, _E(), price_context=SNAP_TEXT)
    assert captured["price_context"] == SNAP_TEXT
    assert out["rating"] == "Buy"


def test_digest_stores_the_verified_snapshot(monkeypatch):
    class FakeDb:
        def __init__(self):
            self.upserts = []

        def select(self, table, query=None, columns="*"):
            return [{"id": "run-1", "ticker_id": "t", "quick_model": "m", "deep_model": "x",
                     "prompt_tokens": 0, "completion_tokens": 0, "cost_usd": 0.0}] \
                if table == "runs" else []

        def upsert(self, table, on_conflict, row):
            self.upserts.append((table, row))

        def update(self, *a):
            pass

    db = FakeDb()
    resp = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(
            content='{"debate_summary": "s"}'))],
        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, cost=0.0))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **kw: resp)))
    monkeypatch.setattr(digest, "_client", lambda: client)
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

    digest.build_digest(db, "run-1", "NVDA", verified_snapshot=SNAP_TEXT)
    stored = db.upserts[0][1]["digest"]
    assert stored["verified_snapshot"].startswith("## Verified market data snapshot")

    digest.build_digest(db, "run-1", "NVDA")
    assert "verified_snapshot" not in db.upserts[1][1]["digest"]


def _backfill_db(missing_ids):
    """FakeDb with succeeded runs; run_digest exists only for ids NOT in missing_ids."""
    from tradingagents_worker.db import Db

    class BackfillDb(Db):
        def __init__(self):
            self.tables = {}

        def t_(self, name):
            return self.tables.setdefault(name, [])

        def select(self, table, query=None, columns="*"):
            rows = [dict(r) for r in self.tables.setdefault(table, [])]
            for k, v in (query or {}).items():
                if v.startswith("eq."):
                    rows = [r for r in rows if str(r.get(k)) == v[3:]]
            return rows

        def upsert(self, table, on_conflict, row):
            self.tables.setdefault(table, []).append(row)

        def insert(self, table, row, prefer="return=minimal"):
            self.tables.setdefault(table, []).append(row)
            return [row]

    db = BackfillDb()
    for i, (rid, missing) in enumerate([("run-keep", False), ("run-missing", True)]):
        db.t_("tickers").append({"id": f"tick-{i}", "symbol": "NVDA"})
        db.t_("runs").append({"id": rid, "ticker_id": f"tick-{i}",
                             "trade_date": "2026-09-30", "status": "succeeded"})
        if not missing:
            db.t_("run_digest").append({"run_id": rid, "digest": {"evidence": []}})
    return db


def test_backfill_digests_rebuilds_missing_with_snapshot(monkeypatch):
    from tradingagents_worker import digest as dg

    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    _fake_snapshot_module(monkeypatch, lambda sym, date: {
        "text": SNAP_TEXT, "rows": SNAP_ROWS, "latest_date": "2026-09-26"})
    called = {}

    def fake_build(db_, run_id, ticker, verified_snapshot=None):
        called[run_id] = verified_snapshot
        return {"stored": True}

    monkeypatch.setattr(dg, "build_digest", fake_build)
    db = _backfill_db(missing_ids=["run-missing"])
    written = dg.backfill_digests(db)
    assert written == 1 and called == {"run-missing": SNAP_TEXT}


def test_backfill_digests_skips_existing_and_needs_key(monkeypatch):
    from tradingagents_worker import digest as dg

    db = _backfill_db(missing_ids=[])
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    assert dg.backfill_digests(db) == 0
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert dg.backfill_digests(db, cap=2) == 0
