"""Worker service loop: claim → run → persist (runs, agent_reports, decisions,
memory, settlements) with cooperative cancel and crash rehydration."""
from __future__ import annotations

import os
import threading
import uuid
from datetime import date, datetime, timedelta

from .config import SETTINGS
from .db import Db
from .events import Emitter
from .runner import Cancelled, get_runner
from .settings import get_model_pair, get_runtime_flags

REPORT_STAGES = ["analysts", "research_debate", "trader", "risk_debate", "portfolio_manager"]

# Runner stages → agent_reports.stage values allowed by the schema check.
_DB_REPORT_STAGE = {"analysts": "analyst_market", "trader": "trader",
                    "portfolio_manager": "portfolio_manager"}
# Debate transcripts live in debate_messages, not agent_reports.
_DEBATE_STAGE = {"research_debate": "research", "risk_debate": "risk"}


def _start_health_server() -> None:
    # Render web services must hold $PORT open; background-worker deploys don't set it.
    port = os.getenv("PORT")
    if not port:
        return
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("0.0.0.0", int(port)), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True, name="health").start()
    print(f"health endpoint on :{port}", flush=True)


def persist_run(db: Db, job: dict, result: dict) -> str:
    ticker = job["payload"]["ticker"]
    trade_date = job["payload"]["trade_date"]
    ticker_row = db.select("tickers", {"symbol": f"eq.{ticker}"}, "id")
    ticker_id = ticker_row[0]["id"] if ticker_row else _ensure_ticker(db, ticker)
    run_id = str(uuid.uuid4())
    cfg = {"depth": job["payload"].get("depth", "standard"), "provider": SETTINGS.llm_provider,
           "quick": SETTINGS.quick_model, "deep": SETTINGS.deep_model, "stub": SETTINGS.stub_mode}
    db.insert("runs", {
        "id": run_id, "job_id": job["id"], "user_id": job.get("user_id"),
        "ticker_id": ticker_id, "trade_date": trade_date, "asset_type": "stock",
        "config": cfg, "config_hash": _hash_cfg(cfg), "llm_provider": SETTINGS.llm_provider,
        "quick_model": SETTINGS.quick_model, "deep_model": SETTINGS.deep_model,
        "depth_preset": job["payload"].get("depth", "standard"),
        "effective_provider": SETTINGS.llm_provider,
        "status": "succeeded",
        "prompt_tokens": result["tokens"]["prompt"], "completion_tokens": result["tokens"]["completion"],
        "tokens_cached": result["tokens"]["cached"], "tokens_uncached": result["tokens"]["uncached"],
        "tool_calls": result.get("tool_calls", 0), "elapsed_seconds": result.get("elapsed_seconds"),
        "cost_usd": result.get("cost_usd", 0), "framework_version": "0.5.1",
    }, prefer="return=minimal")
    for stage, md in (result.get("reports") or {}).items():
        if not md:
            continue
        if stage in _DEBATE_STAGE:
            db.insert("debate_messages", {
                "run_id": run_id, "debate_type": _DEBATE_STAGE[stage],
                "speaker": "neutral", "round": 1, "content": md,
            }, prefer="return=minimal")
        elif stage in _DB_REPORT_STAGE:
            db.insert("agent_reports", {
                "run_id": run_id, "stage": _DB_REPORT_STAGE[stage], "content_markdown": md,
            }, prefer="return=minimal")
    decision = result.get("decision") or {}
    if job.get("user_id") and not result.get("is_review"):
        dec_id = str(uuid.uuid4())
        db.insert("decisions", {
            "id": dec_id, "run_id": run_id, "user_id": job["user_id"], "ticker_id": ticker_id,
            "trade_date": trade_date, "rating": _rating_slug(result.get("rating")),
            "rating_rank": _rating_rank(result.get("rating")),
            "signal": _signal_slug(result.get("signal"), result.get("rating")),
            "is_review": False, "executive_summary": decision.get("executive_summary"),
            "price_target": decision.get("price_target"), "time_horizon": decision.get("time_horizon"),
            "full_decision": decision.get("full_decision") or {},
            "qc_verdict": "passed",
        }, prefer="return=minimal")
        # memory entry (pending) + settlement placeholders for configured horizons
        db.insert("memory_entries", {
            "user_id": job["user_id"], "ticker_id": ticker_id, "decision_id": dec_id,
            "entry_date": trade_date, "rating": _rating_slug(result.get("rating")),
            "status": "pending",
        }, prefer="return=minimal")
        for h in (5, 30):
            db.insert("settlements", {
                "decision_id": dec_id, "horizon_days": h, "status": "pending",
                "as_of_date": str(date.fromisoformat(trade_date) + timedelta(days=h)),
            }, prefer="return=minimal")
    return run_id


def _ensure_ticker(db: Db, symbol: str) -> str:
    tid = str(uuid.uuid4())
    db.insert("tickers", {"id": tid, "symbol": symbol, "native_symbol": symbol,
                          "asset_type": "stock"}, prefer="return=minimal")
    return tid


def _rating_slug(rating: str | None) -> str:
    return str(rating or "hold").lower().replace("overweight", "overweight").replace("underweight", "underweight")


def _rating_rank(rating: str | None) -> int:
    return {"sell": 1, "underweight": 2, "hold": 3, "overweight": 4, "buy": 5}.get(
        str(rating or "").lower(), 3)


def _signal_slug(signal: str | None, rating: str | None) -> str:
    """Engine signals may come back as 5-tier ratings ('overweight'); the schema's
    signal domain is buy/sell/hold/review — collapse from the rating when needed."""
    s = str(signal or "").lower()
    if s in ("buy", "sell", "hold", "review"):
        return s
    combined = f"{s} {str(rating or '').lower()}"
    if "review" in combined:
        return "review"
    if "buy" in combined or "overweight" in combined or "bull" in combined:
        return "buy"
    if "sell" in combined or "underweight" in combined or "bear" in combined:
        return "sell"
    return "hold"


def _hash_cfg(cfg: dict) -> str:
    import hashlib, json
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:16]


def rehydrate_crashed(db: Db, worker_id: str):
    """On boot, release jobs stuck 'running' from a dead worker. requeue_job
    decides pending-vs-failed by attempts — a deploy kill must not strand a job
    mid-queue, but it also can't retry forever."""
    stuck = db.select("jobs", {"status": "eq.running", "locked_by": f"neq.{worker_id}"}, "id")
    for row in stuck:
        try:
            db.requeue_job(str(row["id"]), "worker restarted mid-run")
        except Exception:
            db.update("jobs", f"id=eq.{row['id']}", {"status": "failed", "last_error": "worker restarted mid-run"})


def run_forever():
    wid = f"worker-{uuid.uuid4().hex[:8]}"
    _start_health_server()
    db = Db()
    missing = SETTINGS.missing_critical()
    if missing:
        raise SystemExit(f"missing env: {', '.join(missing)}")
    rehydrate_crashed(db, wid)
    runner = get_runner(model_pair_resolver=lambda: get_model_pair(db),
                        stub_resolver=lambda: get_runtime_flags(db)["stub"])
    inflight: dict[str, threading.Event] = {}
    print(f"[{datetime.utcnow().isoformat()}Z] worker {wid} up (stub_mode={SETTINGS.stub_mode})", flush=True)
    while True:
        job = None
        try:
            job = db.claim_job(wid, types=["analysis"])
        except Exception as e:  # queue hiccup: back off, keep alive
            print(f"claim error: {e}", flush=True)
            threading.Event().wait(SETTINGS.poll_interval_s)
            continue
        if not job:
            threading.Event().wait(SETTINGS.poll_interval_s)
            continue
        cancel = threading.Event()
        inflight[str(job["id"])] = cancel
        try:
            emit = Emitter(db, str(job["id"]))
            payload = job.get("payload") or {}
            ticker, trade_date = payload["ticker"], payload["trade_date"]
            depth = payload.get("depth", "standard")
            emit.emit("analysts", "started", f"{ticker} @ {trade_date} (depth={depth})")
            result = runner.run(ticker, trade_date, depth, payload.get("instructions"), emit, cancel)
            run_id = persist_run(db, job, result)
            db.finish_job(str(job["id"]), "succeeded", run_id=run_id)
            emit.emit("report_qc", "done", f"stored run {run_id[:8]}")
            try:
                from .enrich import enrich_run
                got = enrich_run(db, ticker)
                emit.emit("report_qc", "progress",
                          f"context: {got['bars']} bars · {got['news']} news · profile={'✓' if got['profile'] else '—'}")
            except Exception as e2:
                print(f"enrich (non-fatal): {e2}", flush=True)
            try:
                from .digest import build_digest
                dig = build_digest(db, run_id, ticker)
                if dig.get("stored"):
                    emit.emit("report_qc", "progress",
                              f"digest: {dig['evidence']} evidence · {dig['scenarios']} scenarios · "
                              f"{dig['news']} news reads · qc {dig['qc']} stages")
                else:
                    emit.emit("report_qc", "progress", f"digest skipped: {dig.get('reason')}")
            except Exception as e3:
                print(f"digest (non-fatal): {e3}", flush=True)
        except Cancelled:
            db.finish_job(str(job["id"]), "cancelled", error="cancelled")
        except Exception as e:
            err = str(e)[:500]
            print(f"job {job['id']} error: {err}", flush=True)
            try:
                db.requeue_job(str(job["id"]), err)
            except Exception as e2:
                db.finish_job(str(job["id"]), "failed", error=f"{err} / requeue failed: {e2}")
        finally:
            inflight.pop(str(job["id"]), None)


if __name__ == "__main__":
    run_forever()
