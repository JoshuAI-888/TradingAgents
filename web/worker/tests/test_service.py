"""Pipeline tests with the stub runner: run → persist → settle, end to end offline."""
from __future__ import annotations

from datetime import date, timedelta

from tradingagents_worker.events import Emitter
from tradingagents_worker.runner import StubRunner, Cancelled
from tradingagents_worker.service import persist_run
from tradingagents_worker.settlement import settle_due


def test_stub_run_persists_run_reports_decision_memory_settlements(fake_db, analysis_job):
    emitted = []
    result = StubRunner().run("NVDA", "2026-09-26", "standard", None,
                              Emitter(_RecorderDb(emitted), "job-1"))
    assert result["signal"] == "buy" and not result["is_review"]
    assert set(result["reports"]) >= {"analysts", "trader", "portfolio_manager"}

    run_id = persist_run(fake_db, analysis_job, result)
    runs = fake_db.select("runs")
    assert len(runs) == 1 and runs[0]["ticker_id"] == "tick-1"
    assert runs[0]["depth_preset"] == "standard"

    reports = fake_db.select("agent_reports")
    assert {r["stage"] for r in reports} == {"analysts", "research_debate", "trader", "risk_debate", "portfolio_manager"}

    decisions = fake_db.select("decisions")
    assert len(decisions) == 1 and decisions[0]["rating"] == "buy" and decisions[0]["rating_rank"] == 5
    assert decisions[0]["qc_verdict"] == "passed"

    assert len(fake_db.select("memory_entries")) == 1
    settlements = fake_db.select("settlements")
    assert {s["horizon_days"] for s in settlements} == {5, 30}
    assert settlements[0]["as_of_date"] == str(date(2026, 9, 26) + timedelta(days=5))
    assert run_id


def test_review_signal_does_not_create_decision(fake_db, analysis_job):
    result = StubRunner().run("NVDA", "2026-09-26", "fast", None,
                              Emitter(_RecorderDb([]), "job-1"))
    result["is_review"] = True
    persist_run(fake_db, analysis_job, result)
    assert fake_db.select("decisions") == []
    assert len(fake_db.select("runs")) == 1  # run still recorded


class _RecorderDb:
    """Minimal Emitter sink that doesn't touch Supabase."""
    def __init__(self, sink):
        self.sink = sink

    def insert(self, table, row, prefer="return=minimal"):
        if table == "job_events":
            self.sink.append(row)
        return None


def test_settlement_math_and_memory_resolution(fake_db, analysis_job):
    result = StubRunner().run("NVDA", "2026-09-26", "standard", None, Emitter(_RecorderDb([]), "j"))
    run_id = persist_run(fake_db, analysis_job, result)
    dec = fake_db.select("decisions")[0]
    tid = dec["ticker_id"]
    # entry 180 → exit 183.6 (+2.0%); benchmark 580 → 585.8 (+1.0%) ⇒ alpha +1.0%
    bars = fake_db._t("price_bars")
    for tid_, d, close in [(tid, "2026-09-26", 180.0), (tid, "2026-10-01", 183.6),
                           ("bench-1", "2026-09-26", 580.0), ("bench-1", "2026-10-01", 585.8)]:
        bars.append({"ticker_id": tid_, "bar_date": d, "close": close})
    fake_db._t("tickers").append({"id": "bench-1", "symbol": "SPY"})
    fake_db.update("settlements", "decision_id=eq.x", {}) if False else None
    settled = settle_due(fake_db, today="2026-10-01")
    assert len(settled) == 1  # only the 5d horizon is due (30d lands 10-26)
    s5 = settled[0]
    assert s5["horizon_days"] == 5
    assert abs(s5["raw_return_pct"] - 2.0) < 1e-6
    assert abs(s5["alpha_pct"] - 1.0) < 1e-6
    mem = fake_db.select("memory_entries")[0]
    assert mem["status"] == "resolved" and abs(mem["alpha_pct"] - 1.0) < 1e-6


def test_settlement_missing_bars_marks_insufficient(fake_db, analysis_job):
    result = StubRunner().run("NVDA", "2026-09-26", "standard", None, Emitter(_RecorderDb([]), "j"))
    persist_run(fake_db, analysis_job, result)
    settled = settle_due(fake_db, today="2026-10-01")
    assert all(s["status"] == "insufficient_data" for s in settled)


def test_cancel_raises_mid_run():
    import threading
    r = StubRunner()
    ev = threading.Event(); ev.set()
    try:
        r.run("NVDA", "2026-09-26", "fast", None, Emitter(_RecorderDb([]), "j"), cancel=ev)
        assert False, "should have raised"
    except Cancelled:
        pass
