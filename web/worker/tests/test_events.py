"""Event emission: seq continues across re-attempts (no order-by-seq scrambles)."""

from tradingagents_worker.events import Emitter


def test_emitter_continues_seq_after_requeue(fake_db):
    first = Emitter(fake_db, "job-9")
    first.emit("analysts", "started", "a")
    first.emit("trader", "progress", "b")
    second = Emitter(fake_db, "job-9")  # e.g. the worker restarted mid-run
    second.emit("analysts", "progress", "c")
    second.emit("portfolio_manager", "done", "d")
    seqs = [r["seq"] for r in fake_db.select("job_events", {"job_id": "eq.job-9"})]
    assert seqs == [1, 2, 3, 4]


def test_emitter_fresh_job_starts_at_one(fake_db):
    Emitter(fake_db, "job-x").emit("analysts", "started", "a")
    assert fake_db.select("job_events", {"job_id": "eq.job-x"})[0]["seq"] == 1
