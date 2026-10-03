"""Settlement engine (we own it): settle pending decisions at +5d/+30d vs the
ticker's benchmark using price_bars already stored — never a live fetch. Cron-invoked.
"""

from __future__ import annotations

from datetime import date

from .db import Db


def settle_due(db: Db, today: str | None = None) -> list[dict]:
    today = today or date.today().isoformat()
    due = db.select(
        "settlements",
        {
            "status": "eq.pending",
            "as_of_date": f"lte.{today}",
        },
        "id,decision_id,horizon_days,as_of_date,benchmark_symbol",
    )
    settled = []
    for s in due:
        try:
            row = _settle_one(db, s)
            settled.append(row)
        except Exception as e:
            db.update(
                "settlements", f"id=eq.{s['id']}", {"status": "failed", "error": str(e)[:300]}
            )
    return settled


def _settle_one(db: Db, s: dict) -> dict:
    dec = db.select("decisions", {"id": f"eq.{s['decision_id']}"}, "ticker_id,trade_date")[0]
    tid, tdate = dec["ticker_id"], dec["trade_date"]
    as_of = s["as_of_date"]
    bench = s.get("benchmark_symbol") or "SPY"
    bench_tid = _ticker_id(db, bench)

    entry = _close_on_or_before(db, tid, tdate)
    exit_ = _close_on_or_before(db, tid, as_of)
    b_entry = _close_on_or_before(db, bench_tid, tdate)
    b_exit = _close_on_or_before(db, bench_tid, as_of)
    if not (entry and exit_ and b_entry and b_exit):
        db.update(
            "settlements",
            f"id=eq.{s['id']}",
            {"status": "insufficient_data", "error": "missing price bars"},
        )
        return {"id": s["id"], "status": "insufficient_data"}

    raw = (exit_ - entry) / entry * 100
    bench_ret = (b_exit - b_entry) / b_entry * 100
    row = {
        "status": "settled",
        "as_of_date": as_of,
        "entry_price": entry,
        "exit_price": exit_,
        "benchmark_symbol": bench,
        "benchmark_entry": b_entry,
        "benchmark_exit": b_exit,
        "raw_return_pct": round(raw, 4),
        "benchmark_return_pct": round(bench_ret, 4),
        "alpha_pct": round(raw - bench_ret, 4),
        "source": "price_bars",
        "settled_at": "now()",
    }
    db.update("settlements", f"id=eq.{s['id']}", row)
    # resolve the memory entry for this decision (same-window settlement)
    mem = db.select("memory_entries", {"decision_id": f"eq.{s['decision_id']}"}, "id")
    if mem and s["horizon_days"] == 5:
        db.update(
            "memory_entries",
            f"id=eq.{mem[0]['id']}",
            {
                "status": "resolved",
                "raw_return_pct": round(raw, 4),
                "alpha_pct": round(raw - bench_ret, 4),
                "resolved_at": "now()",
            },
        )
    return {**row, "id": s["id"], "horizon_days": s["horizon_days"]}


def _ticker_id(db: Db, symbol: str) -> str | None:
    rows = db.select("tickers", {"symbol": f"eq.{symbol}"}, "id")
    return rows[0]["id"] if rows else None


def _close_on_or_before(db: Db, ticker_id: str, day: str) -> float | None:
    rows = db.select(
        "price_bars",
        {
            "ticker_id": f"eq.{ticker_id}",
            "bar_date": f"lte.{day}",
            "order": "bar_date.desc",
            "limit": "1",
        },
        "close",
    )
    return float(rows[0]["close"]) if rows else None
