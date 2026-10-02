"""TradingAgents portal API (FastAPI).

Reads Supabase with the service key for writes the client can't do (enqueue),
and lets the browser read its own rows via the anon key + RLS directly
(Supabase JS) — this API exists for orchestration and cross-table joins.
"""
from __future__ import annotations

import json
import math
import hashlib
import os
import re
import tempfile
import time
import uuid
from typing import Annotated
from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tradingagents_worker.enrich_fields import TECH_FIELDS, YF_ONLY_FIELDS, YF_FIELD_CONTRACTS
from tradingagents_worker.quote_observations import CURRENCY_FIELDS, field_currency
from tradingagents_worker.config import SETTINGS
from tradingagents_worker.db import Db
from tradingagents_worker.screener_generations import read_generation, GenerationError, canonical_generation, aware_time
import copy
from tradingagents_worker.runner import demangle_debate
from tradingagents_worker.screener_rows import snapshot_to_row as _snapshot_to_row
from .screen_observations import capture_observation, paired_evidence, criterion_slots, numeric, validate_observation_capture

_AS_OF_RE = re.compile(r"\d{4}-\d{2}-\d{2}")

app = FastAPI(title="TradingAgents Portal API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=[o for o in os.getenv(
    "API_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o],
    allow_methods=["*"], allow_headers=["*"])

db = Db()


def require_cron(x_cron_secret: str = Header(default="")):
    if not SETTINGS.cron_secret or x_cron_secret != SETTINGS.cron_secret:
        raise HTTPException(401, "invalid cron secret")


class AnalyzeIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=16)
    trade_date: date
    depth: str = Field(default="standard", pattern="^(fast|standard|deep)$")
    instructions: str | None = Field(default=None, max_length=4000)


@app.get("/api/health")
def health():
    missing = SETTINGS.missing_critical()
    from tradingagents_worker.settings import get_runtime_flags
    return {"status": "ok" if not missing else "degraded", "missing": missing,
            "stub_mode": get_runtime_flags(db)["stub"]}


_universe_symbols_cache: tuple[float, dict] | None = (0.0, {})


def _universe_symbols() -> dict:
    """Stored-universe symbol → stock_type, cached 5 min (a 10k-row read per
    submit would be wasteful; a stale list for minutes only affects the hint)."""
    global _universe_symbols_cache
    now = time.time()
    if now - _universe_symbols_cache[0] < 300:
        return _universe_symbols_cache[1]
    try:
        rows = db.select_all("screener_universe", {}, "code,stock_type")
    except Exception:
        rows = []
    symbols = {}
    for r in rows:
        code = str(r.get("code") or "")
        if "." in code:
            symbols[code.split(".", 1)[1].upper()] = r.get("stock_type")
    _universe_symbols_cache = (now, symbols)
    return symbols


def _symbol_check(ticker: str) -> dict:
    """Best-effort known-symbol check with a did-you-mean suggestion. Soft:
    the analysis is still enqueued — an unknown symbol fails fast at the
    engine otherwise ('No market data'), so warn before tokens are spent."""
    sym = ticker.strip().upper()
    symbols = _universe_symbols()
    if not symbols or sym in symbols:
        return {"known": True}
    import difflib
    near = difflib.get_close_matches(sym, symbols.keys(), n=1, cutoff=0.72)
    note = f"{sym} is not in the stored market universe"
    if near:
        note += f" — did you mean {near[0]}?"
    return {"known": False, "suggestion": near[0] if near else None, "note": note}


@app.post("/api/analyses")
def submit(inp: AnalyzeIn, x_user_id: str = Header(default="")):
    """Enqueue an analysis. Idempotent per (ticker, date, depth) per day via idempotency_key."""
    if not SETTINGS.supabase_url:
        raise HTTPException(503, "SUPABASE_URL not configured")
    validation = _symbol_check(inp.ticker)
    key = f"analysis:{inp.ticker.upper()}:{inp.trade_date}:{inp.depth}"
    # Single-user Phase 0: unauthenticated submissions are owned by DEFAULT_USER_ID.
    user_id = x_user_id or os.getenv("DEFAULT_USER_ID") or None
    existing = db.select("jobs", {"idempotency_key": f"eq.{key}"}, "id,status")
    # A failed/cancelled job must not block re-running the same analysis.
    if existing and existing[0].get("status") not in ("failed", "cancelled"):
        return {"job_id": existing[0]["id"], "status": existing[0].get("status", "pending"),
                "deduplicated": True, "validation": validation}
    row = db.insert("jobs", {
        "job_type": "analysis", "user_id": user_id,
        "payload": {"ticker": inp.ticker.upper(), "trade_date": str(inp.trade_date),
                    "depth": inp.depth, "instructions": inp.instructions},
        "idempotency_key": key,
    }, prefer="return=representation")
    job = row if isinstance(row, dict) else (row or [{}])[0]
    return {"job_id": job.get("id"), "status": job.get("status", "pending"),
            "deduplicated": False, "validation": validation}


@app.get("/api/analyses/{job_id}")
def status(job_id: str):
    jobs = db.select("jobs", {"id": f"eq.{job_id}"}, "id,status,payload,run_id,last_error,created_at,started_at,finished_at")
    if not jobs:
        raise HTTPException(404, "job not found")
    job = jobs[0]
    events = db.select("job_events", {"job_id": f"eq.{job_id}", "order": "seq.asc"},
                       "seq,ts,stage,status,message,payload")
    return {"job": job, "events": events, "queue": _queue_context(job)}


def _worker_age() -> tuple[float | None, bool | None, float | None]:
    """Seconds since the worker's last heartbeat, whether it looks alive
    (heartbeat refreshes every ~20s; 120s = six missed beats), and its
    configured poll interval for the UI's 'checks the queue every Ns' note."""
    rows = db.select("app_settings", {"key": "eq.worker_state"}, "value")
    if not rows or not (rows[0].get("value") or {}).get("at"):
        return None, None, None
    value = rows[0]["value"]
    at = str(value["at"]).replace("Z", "+00:00")
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(at)).total_seconds()
    except ValueError:
        return None, None, None
    try:
        poll_s = float(value.get("poll_interval_s")) if value.get("poll_interval_s") else None
    except (TypeError, ValueError):
        poll_s = None
    return round(max(age, 0)), age < 120, poll_s


def _eta_seconds(depth: str) -> tuple[float | None, int]:
    """Median wall-clock of the last succeeded analysis jobs at this depth —
    run row created (completion) minus job started (claim). None = no history."""
    jobs = db.select("jobs", {"status": "eq.succeeded", "job_type": "eq.analysis",
                              "payload->>depth": f"eq.{depth}",
                              "order": "created_at.desc", "limit": "6"}, "id,started_at")
    jobs = [j for j in jobs if j.get("started_at") and j.get("id")]
    if not jobs:
        return None, 0
    ids = ",".join(j["id"] for j in jobs)
    runs = db.select("runs", {"job_id": f"in.({ids})"}, "job_id,created_at")
    started = {j["id"]: j["started_at"] for j in jobs}
    elapsed = sorted(
        (datetime.fromisoformat(str(r["created_at"]).replace("Z", "+00:00"))
         - datetime.fromisoformat(str(started[r["job_id"]]).replace("Z", "+00:00"))
         ).total_seconds()
        for r in runs if r.get("job_id") in started and r.get("created_at"))
    elapsed = [e for e in elapsed if e > 0]
    if not elapsed:
        return None, 0
    return elapsed[len(elapsed) // 2], len(elapsed)


def _queue_context(job: dict) -> dict:
    """Queue position, ETA and worker liveness for the Analyze progress card."""
    ctx: dict = {"position": None, "ahead": 0, "eta_seconds": None, "eta_basis": 0,
                 "worker_age_s": None, "worker_alive": None, "worker_poll_s": None}
    try:
        if job.get("status") == "pending":
            pending = db.select("jobs", {"status": "eq.pending", "job_type": "eq.analysis",
                                         "order": "created_at.asc"}, "id,priority,created_at")
            pending.sort(key=lambda r: (-(int(r.get("priority") or 100)), str(r.get("created_at") or "")))
            idx = next((i for i, r in enumerate(pending) if r.get("id") == job["id"]), None)
            if idx is not None:
                ctx["ahead"], ctx["position"] = idx, idx + 1
        depth = "standard"
        payload = job.get("payload")
        if isinstance(payload, dict) and payload.get("depth"):
            depth = payload["depth"]
        ctx["eta_seconds"], ctx["eta_basis"] = _eta_seconds(depth)
        ctx["worker_age_s"], ctx["worker_alive"], ctx["worker_poll_s"] = _worker_age()
    except Exception:
        pass  # progress metadata is best-effort; the core status payload stands alone
    return ctx


def _run_debates(run_id: str) -> list:
    """Debate rows for the report. content_original arrived with migration 0010;
    until it is applied, retry without it rather than killing the whole report."""
    try:
        return db.select("debate_messages", {"run_id": f"eq.{run_id}", "order": "created_at.asc"},
                         "debate_type,speaker,round,content,content_original")
    except Exception:
        return [{**m, "content_original": None} for m in db.select(
            "debate_messages", {"run_id": f"eq.{run_id}", "order": "created_at.asc"},
            "debate_type,speaker,round,content")]


@app.get("/api/analyses/{ref}/report")
def report(ref: str):
    """Full dossier for the report page. `ref` is a job id or a decision id.
    A DB failure surfaces as a readable 502 (the page prints e.message) instead
    of a bare 'Internal Server Error'."""
    try:
        return _report_payload(ref)
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 — detail is the point; no secrets in db errors
        raise HTTPException(502, f"report data unavailable: {str(e)[:220]}")


def _report_payload(ref: str) -> dict:
    runs = db.select("runs", {"job_id": f"eq.{ref}"}, "*")
    if not runs:
        dec0 = db.select("decisions", {"id": f"eq.{ref}"}, "run_id")
        if dec0:
            runs = db.select("runs", {"id": f"eq.{dec0[0]['run_id']}"}, "*")
    if not runs:
        raise HTTPException(404, "no run for reference")
    run = runs[0]
    tick = db.select("tickers", {"id": f"eq.{run['ticker_id']}"}, "symbol,name,exchange,currency")
    reports = db.select("agent_reports", {"run_id": f"eq.{run['id']}", "order": "created_at.asc"},
                        "stage,content_markdown,quality_grade,quality_score,created_at")
    debates = _run_debates(run["id"])
    # Rows stored before the char-wise _join_history fix read one character per
    # line; demangle at read time (detector is strict, normal rows pass through).
    # The worker's repair pass restores real spacing and preserves the untouched
    # original in content_original — the UI notes repaired rows accordingly.
    debates = [{**m, "content": demangle_debate(m.get("content") or "")} for m in debates]
    decision = db.select("decisions", {"run_id": f"eq.{run['id']}"}, "*")
    settlements = []
    if decision:
        settlements = db.select("settlements", {"decision_id": f"eq.{decision[0]['id']}", "order": "horizon_days.asc"},
                                "horizon_days,status,as_of_date,entry_price,exit_price,raw_return_pct,benchmark_return_pct,alpha_pct")
    job = db.select("jobs", {"id": f"eq.{run['job_id']}"}, "id,status,payload,created_at,finished_at,last_error")
    events = db.select("job_events", {"job_id": f"eq.{run['job_id']}", "order": "seq.asc"},
                       "seq,ts,stage,status,message")
    run_pub = {k: v for k, v in run.items() if k not in ("portfolio_snapshot", "config")}
    digest = db.select("run_digest", {"run_id": f"eq.{run['id']}"}, "digest,model,created_at")
    return {"ticker": tick[0] if tick else {"symbol": "?"}, "run": run_pub,
            "decision": decision[0] if decision else None, "reports": reports,
            "debates": debates, "settlements": settlements,
            "digest": digest[0] if digest else None,
            "job": job[0] if job else None, "events": events}


@app.get("/api/bars/{symbol}")
def bars(symbol: str, days: int = 180, as_of: str | None = None):
    """Daily bars for the report chart. `as_of` (YYYY-MM-DD) truncates at that
    date so a run's chart shows the market as its agents saw it; omit = latest."""
    if as_of is not None and not _AS_OF_RE.fullmatch(as_of):
        raise HTTPException(400, "as_of must be YYYY-MM-DD")
    rows = db.select("tickers", {"symbol": f"eq.{symbol.upper()}"}, "id")
    if not rows:
        raise HTTPException(404, "unknown ticker")
    q = {"ticker_id": f"eq.{rows[0]['id']}", "order": "bar_date.desc", "limit": "400"}
    if as_of:
        q["bar_date"] = f"lte.{as_of}"
    bars = db.select("price_bars", q,
                     "bar_date,open,high,low,close,volume")
    bars = list(reversed([b for b in bars if b.get("bar_date")]))
    if days > 0 and len(bars) > days:
        bars = bars[-days:]
    return {"symbol": symbol.upper(), "as_of": as_of, "bars": bars}


@app.get("/api/analyses")
def list_analyses(symbol: str, limit: int = 10):
    """Runs most-recent-first for one symbol — the stock page's Analysis tab
    links each row into its full report dossier (openReport takes the job id)."""
    tick = db.select("tickers", {"symbol": f"eq.{symbol.upper()}"}, "id")
    if not tick:
        return {"symbol": symbol.upper(), "runs": []}
    runs = db.select("runs", {"ticker_id": f"eq.{tick[0]['id']}", "order": "started_at.desc",
                              "limit": str(min(limit, 25))},
                     "id,job_id,trade_date,status,depth_preset,started_at")
    return {"symbol": symbol.upper(), "runs": runs}


@app.get("/api/news/{symbol}")
def news(symbol: str, limit: int = 10):
    rows = db.select("news_items", {"tickers": f'cs.{{"{symbol.upper()}"}}',
                                    "order": "published_at.desc", "limit": str(min(limit, 30))},
                     "title,url,publisher,summary,published_at,sentiment")
    return {"news": rows}


@app.get("/api/fundamentals/{symbol}")
def fundamentals(symbol: str):
    rows = db.select("tickers", {"symbol": f"eq.{symbol.upper()}"}, "id")
    if not rows:
        raise HTTPException(404, "unknown ticker")
    prof = db.select("company_profiles", {"ticker_id": f"eq.{rows[0]['id']}"},
                     "payload,as_of,source")
    return {"symbol": symbol.upper(), "profile": prof[0] if prof else None}


class ReviewIn(BaseModel):
    user_rating: str | None = Field(default=None, pattern="^(agree|disagree)$")
    note: str | None = Field(default=None, max_length=2000)


@app.post("/api/decisions/{decision_id}/review")
def review(decision_id: str, inp: ReviewIn):
    if inp.user_rating is None and inp.note is None:
        raise HTTPException(400, "nothing to save")
    patch = {k: v for k, v in {"user_rating": inp.user_rating, "note": inp.note}.items() if v is not None}
    db.update("decisions", f"id=eq.{decision_id}", patch)
    return {"saved": True}


@app.get("/api/decisions")
def decisions(limit: int = 50):
    rows = db.select("v_decision_ledger", {"order": "trade_date.desc", "limit": str(min(limit, 200))})
    return {"decisions": rows}


@app.get("/api/jobs/active")
def active_jobs():
    """Analyses queued or running right now — the ledger's 'In flight' panel.
    Pending jobs carry their queue position (claim order: priority desc, then
    created_at); worker tells the UI whether the pipeline is picking jobs up."""
    pending = db.select("jobs", {"status": "eq.pending", "order": "created_at.asc", "limit": "20"},
                        "id,status,payload,created_at,locked_by")
    pending.sort(key=lambda j: (-(int(j.get("priority") or 100)), str(j.get("created_at") or "")))
    for i, j in enumerate(pending):
        j["position"] = i + 1
    running = db.select("jobs", {"status": "eq.running", "order": "created_at.desc", "limit": "20"},
                        "id,status,payload,created_at,locked_by")
    age, alive, poll_s = _worker_age()
    return {"jobs": pending + running,
            "worker": {"age_s": age, "alive": alive, "poll_s": poll_s}}


_MARKET_INDICES = [("US.SPY", "S&P 500"), ("US.QQQ", "Nasdaq 100"), ("US.IWM", "Russell 2000"),
                   ("US.VIXY", "VIX proxy"), ("HK.HSI", "Hang Seng")]
_MARKET_SECTORS = [("US.XLK", "Tech"), ("US.XLC", "Comms"), ("US.XLY", "Cons. Disc"),
                   ("US.XLF", "Financials"), ("US.XLV", "Health Care"), ("US.XLI", "Industrials"),
                   ("US.XLP", "Staples"), ("US.XLU", "Utilities"), ("US.XLRE", "Real Estate"),
                   ("US.XLE", "Energy"), ("US.XLB", "Materials")]
_market_cache = None


def _market_client():
    """Moomoo client from portal env, or None when keys are not configured."""
    if not SETTINGS.moomoo_appkey or not SETTINGS.moomoo_private_key:
        return None
    from tradingagents_worker.moomoo import MoomooClient
    return MoomooClient(SETTINGS.moomoo_appkey, SETTINGS.moomoo_private_key)


def _build_market_state(client) -> dict:
    """Indices tape + sector heat + calendar from two read-only moomoo calls."""
    codes = [c for c, _ in _MARKET_INDICES] + [c for c, _ in _MARKET_SECTORS]
    snap = (client.snapshot(codes) or {}).get("snapshot_list") or []
    by_code = {s.get("code"): s for s in snap if isinstance(s, dict)}

    def quote(code: str) -> dict:
        s = by_code.get(code) or {}
        last, prev, pct = s.get("last_price"), s.get("prev_close_price"), s.get("pct_change")
        # Off-session snapshots leave pct_change null — fall back to prev close.
        if pct is None and last is not None and prev:
            pct = (float(last) - float(prev)) / float(prev) * 100
        try:
            as_of = (datetime.fromtimestamp(float(s["update_time"]) / 1000, tz=timezone.utc).isoformat()
                     if s.get("update_time") else None)
        except (TypeError, ValueError, OSError):
            as_of = None
        return {"last": last, "pct": None if pct is None else round(float(pct), 2), "as_of": as_of}

    indices = [{"symbol": c.split(".")[-1], "name": name, **quote(c)}
               for c, name in _MARKET_INDICES if quote(c)["last"] is not None]
    sectors = [{"symbol": c.split(".")[-1], "name": name, **quote(c)}
               for c, name in _MARKET_SECTORS if quote(c)["last"] is not None]
    calendar = [{"event": it.get("event_text"), "country": it.get("country"),
                 "star": it.get("star"), "time": it.get("event_time"),
                 "forecast": it.get("predictive"), "actual": it.get("announce")}
                for it in (client.econ_calendar_hot() or [])[:8]]
    stamps = [q["as_of"] for q in indices + sectors if q.get("as_of")]
    return {"available": True, "indices": indices, "sectors": sectors,
            "calendar": calendar, "as_of": max(stamps) if stamps else None}


@app.get("/api/market/state")
def market_state():
    """Market Pulse market-state panel (moomoo snapshot + calendar; 5-min cache)."""
    global _market_cache
    client = _market_client()
    if client is None:
        return {"available": False, "reason": "moomoo keys not configured"}
    if _market_cache is None:
        from tradingagents_worker.ttl_cache import TtlCache  # noqa: E402
        _market_cache = TtlCache(root=os.path.join(tempfile.gettempdir(), "ta-ttl"))
    k = _market_cache.key("quotes", "market-state", "v1")
    hit = _market_cache.get("quotes", k)
    if hit is not None:
        return hit
    try:
        state = _build_market_state(client)
    except Exception as e:
        return {"available": False, "reason": str(e)[:120]}
    _market_cache.put("quotes", k, state)
    return state


# ── Screener (moomoo stock-screen + snapshot enrichment; watchlist universe) ──

SCREENER_COLUMNS = [
    ("price", "Price"), ("pct", "% Chg"), ("chg", "Chg"), ("market_cap", "Market Cap"),
    ("volume", "Volume"), ("turnover", "Turnover"), ("turnover_rate", "Turnover%"),
    ("volume_ratio", "Volume Ratio"), ("float_cap", "Float Cap"), ("shares", "Shares Out."),
    ("pe", "P/E (Static)"), ("pe_ttm", "P/E (TTM)"), ("pb", "P/B"), ("div_yield", "Div Yield TTM"),
    ("amplitude", "Range %"), ("bid_ask_ratio", "Bid/Ask Ratio %"), ("eps", "EPS"),
    ("high52", "52w High"), ("low52", "52w Low"),
]

# Market-mode server-side sort ids verified live (values are ×1000-scaled);
# keys match screener row field names.
_SCREEN_SORT_IDS = {"market_cap": 2301, "price": 2201, "pct": 2210}
_SCREEN_RETRIEVE_IDS = [2201, 2202, 2204, 2205, 2207, 2208, 2210, 2215, 2301]
_SCREEN_MARKET_ENUM = {"US": 2, "HK": 1}

# The 22 recommended screeners, transcribed from moomoo's preset pages
# ("Applied Filters" text + the Selected chips, 2026-09-28). Filters over
# fields the snapshot doesn't carry (ROE, growth rates, margins, RSI, sector…)
# stay in the definition for fidelity — the filter engine skips them until the
# factor data lands, and responses report what was skipped.
PRESET_SCREENERS = [
    {"key": "penny", "page": 1, "name": "Penny Stocks",
     "description": "Spot undervalued, low-priced stocks for substantial returns.",
     "filters": [{"field": "price", "max": 5}, {"field": "market_cap", "max": 3e8},
                 {"field": "volume", "min": 1e5, "days": 30},
                 {"field": "revenue_growth", "min": 10},
                 {"field": "net_profit_growth", "min": 5, "excl_min": 1},
                 {"field": "debt_ratio", "max": 40}]},
    {"key": "high-div", "page": 1, "name": "High Dividend Stocks",
     "description": "Spot high-yield, stable dividend stocks for reliable income.",
     "filters": [{"field": "market_cap", "min": 2e9, "excl_min": 1}, {"field": "pe_ttm", "max": 12},
                 {"field": "div_yield", "min": 8},
                 {"field": "debt_ratio", "max": 30},
                 {"field": "revenue_growth", "min": 5, "excl_min": 1}]},
    {"key": "blue-chip", "page": 1, "name": "Blue Chip Stocks",
     "description": "Spot blue-chip stocks from well-established companies for reliable returns and low volatility.",
     "filters": [{"field": "price", "min": 50}, {"field": "market_cap", "min": 1e11},
                 {"field": "debt_ratio", "max": 50},
                 {"field": "revenue_growth", "min": 5}]},
    {"key": "buffett", "page": 1, "name": "Warren Buffett Strategy",
     "description": "Spot stocks with strong earnings, growth potential, and recognized value for strategic long-term investment.",
     "filters": [{"field": "float_cap", "min": 5e8},
                 {"field": "net_profit_growth", "min": 10},
                 {"field": "gross_margin", "min": 50},
                 {"field": "op_ebt", "min": 70},
                 {"field": "roe", "min": 15},
                 {"field": "roe_yoy", "min": 20}]},
    {"key": "undervalued", "page": 1, "name": "Undervalued Stocks",
     "description": "Spot stable, undervalued stocks for long-term growth.",
     "filters": [{"field": "pe_ttm", "max": 15}, {"field": "pb", "max": 1.5},
                 {"field": "div_yield", "min": 4},
                 {"field": "debt_ratio", "max": 30},
                 {"field": "roe", "min": 15, "excl_min": 1},
                 {"field": "revenue_growth", "min": 3, "excl_min": 1}]},
    {"key": "growth", "page": 1, "name": "Best Growth Stocks",
     "description": "Spot stocks with growth potential and solid financial standing.",
     "filters": [{"field": "float_cap", "min": 5e8},
                 {"field": "net_profit_growth", "min": 15},
                 {"field": "gross_margin", "min": 50},
                 {"field": "roe", "min": 15},
                 {"field": "roe_yoy", "min": 50, "excl_min": 1}]},
    {"key": "pb-lt-1", "page": 1, "name": "P/B Ratio Less Than 1",
     "description": "Spot stocks with a price-to-book ratio (P/B) below 1. A lower P/B may indicate an undervaluation and a margin of safety.",
     "filters": [{"field": "pb", "max": 1}]},
    {"key": "best-lt-high-div", "page": 2, "name": "Best Long Term High Dividend Stocks",
     "description": "Spot stocks with reliable dividends and steady growth for secure long-term returns.",
     "filters": [{"field": "div_yield", "min": 4}, {"field": "pe_ttm", "max": 20},
                 {"field": "pb", "max": 1.5}, {"field": "debt_ratio", "max": 40},
                 {"field": "revenue_growth", "min": 3}]},
    {"key": "high-pe", "page": 2, "name": "High P/E Ratio Stocks",
     "description": "Spot stocks with high P/E ratios, which suggest a profitable and sustainable business.",
     "filters": [{"field": "pe_ttm", "min": 25}, {"field": "op_profit_growth", "min": 30, "excl_min": 1}]},
    {"key": "good-pe", "page": 2, "name": "Good P/E Ratio Stocks",
     "description": "Spot stocks with solid fundamentals and high P/E ratios for consistent profitability and returns.",
     "filters": [{"field": "pe_ttm", "min": 20}, {"field": "eps_growth", "min": 5},
                 {"field": "div_yield", "min": 2}, {"field": "net_margin", "min": 10}]},
    {"key": "low-pe", "page": 2, "name": "Low P/E Ratio Stocks",
     "description": "Spot stocks with low P/E ratios, which are potentially undervalued for stable gains and reduced risk.",
     "filters": [{"field": "pe_ttm", "max": 5, "excl_max": 1}, {"field": "pb", "max": 3, "excl_max": 1},
                 {"field": "debt_ratio", "max": 60, "excl_max": 1}]},
    {"key": "rsi-30", "page": 2, "name": "Below 30 RSI Stocks",
     "description": "Spot stocks with an RSI value under 30, which may indicate a rebound from negative market sentiment.",
     "filters": [{"field": "rsi14", "max": 30}]},
    {"key": "junk", "page": 2, "name": "Junk Stocks",
     "description": "Spot small, high-risk, yet undervalued stocks with the potential for significant returns.",
     "filters": [{"field": "pe_ttm", "min": 0}, {"field": "price", "max": 5},
                 {"field": "market_cap", "max": 1e8}]},
    {"key": "small-growth", "page": 2, "name": "Small Cap Stocks with Huge Growth Potential",
     "description": "Spot small-cap stocks with significant growth potential.",
     "filters": [{"field": "price", "min": 1}, {"field": "market_cap", "min": 2.5e8, "max": 2e9},
                 {"field": "revenue_growth", "min": 20},
                 {"field": "rsi14", "min": 50}]},
    {"key": "blue-chip-div", "page": 2, "name": "Blue Chip Dividend Stocks",
     "description": "Spot familiar blue-chip stocks with high dividends for dependable income and value investment.",
     "filters": [{"field": "price", "min": 50}, {"field": "market_cap", "min": 1e11},
                 {"field": "debt_ratio", "max": 50},
                 {"field": "div_yield", "min": 4}]},
    {"key": "speculative", "page": 3, "name": "Speculative Stocks",
     "description": "Spot high-risk, high-return stocks, including those at their recent 10-day low that may be undervalued and ready to rebound.",
     "filters": [{"field": "price", "min": 5}, {"field": "market_cap", "min": 1e8},
                 {"field": "net_margin", "min": 10},
                 {"field": "debt_ratio", "max": 50},
                 {"field": "new_low_10d", "min": 1}]},
    {"key": "high-roe", "page": 3, "name": "High Return On Equity Stocks",
     "description": "Spot high-quality stocks with solid profitability, growth, and attractive dividends for long-term stability.",
     "filters": [{"field": "roe", "min": 20},
                 {"field": "revenue_growth", "min": 5},
                 {"field": "div_yield", "min": 2}, {"field": "pe_ttm", "max": 25}]},
    {"key": "lt-high-div", "page": 3, "name": "Low P/E High Dividend Stocks",
     "description": "Spot financially stable, consistently growing stocks for secure and steady long-term returns.",
     "filters": [{"field": "pe_ttm", "max": 15}, {"field": "div_yield", "min": 4},
                 {"field": "revenue_growth", "min": 3},
                 {"field": "debt_ratio", "max": 50}]},
    {"key": "undervalued-semi", "page": 3, "name": "Undervalued Semiconductor Stocks",
     "description": "Spot semiconductor sector stocks that are well-valued, financially robust, and profitable for attractive long-term returns.",
     "filters": [{"field": "sector", "plate_ids": [10002016, 10002015]},
                 {"field": "pe_ttm", "max": 18}, {"field": "pb", "max": 5},
                 {"field": "roe", "min": 10}]},
    {"key": "undervalued-tech", "page": 3, "name": "Undervalued Tech Stocks",
     "description": "Spot tech stocks that are undervalued by the market.",
     "filters": [{"field": "sector", "plate_ids": [10002016, 10002072, 10002492, 10002470, 10002508, 10002252, 10002098, 10002004]},
                 {"field": "pe_ttm", "max": 15}, {"field": "pb", "max": 5},
                 {"field": "roe", "min": 10}]},
    {"key": "undervalued-banks", "page": 3, "name": "Undervalued Bank Stocks",
     "description": "Spot bank stocks that are financially sound, reasonably valued, and highly profitable.",
     "filters": [{"field": "sector", "plate_ids": [10002481, 10002456]},
                 {"field": "pe_ttm", "max": 10}, {"field": "pb", "max": 1},
                 {"field": "roe", "min": 12}]},
    {"key": "high-eps", "page": 3, "name": "High EPS Stocks",
     "description": "Spot stocks with favorable financial footing and high profitability for investment.",
     "filters": [{"field": "price", "min": 5}, {"field": "market_cap", "min": 1e8},
                 {"field": "eps", "min": 10}, {"field": "debt_ratio", "max": 50}]},
]


def _apply_filters(rows: list[dict], filters: list[dict], strict: bool = True) -> tuple[list[dict], list[str]]:
    """Fail closed when criterion data is absent. Non-strict mode is used only
    for explicitly partial library previews. Returns rows and missing fields."""
    if not rows:
        return [], []
    present: set[str] = set()
    for r in rows:
        present.update(k for k, v in r.items() if v is not None)
    active, skipped = [], []
    for f in filters or []:
        (active if f.get("field") in present else skipped).append(f)
    if skipped and strict:
        return [], [f.get("field") for f in skipped]
    def keep(r: dict) -> bool:
        for f in active:
            vals = f.get("values")
            if vals is not None:  # multi-select: keep on case-insensitive overlap
                v = r.get(f.get("field"))
                want = [str(x).lower() for x in vals]
                have = [str(x).lower() for x in v] if isinstance(v, list) else (
                    None if v is None else [str(v).lower()])
                if not have or not set(have) & set(want):
                    return False
                continue
            v = r.get(f.get("field"))
            lo, hi = f.get("min"), f.get("max")
            if v is None:
                return False
            try:
                v = float(v)
            except (TypeError, ValueError):
                return False
            if not math.isfinite(v):
                return False
            if lo is not None and (v < float(lo) or (f.get("excl_min") and v == float(lo))):
                return False
            if hi is not None and (v > float(hi) or (f.get("excl_max") and v == float(hi))):
                return False
        return True
    return [r for r in rows if keep(r)], [f.get("field") for f in skipped]


def _sort_rows(rows: list[dict], sort: str, direction: int) -> list[dict]:
    reverse = direction == 2
    keyed = [r for r in rows if r.get(sort) is not None]
    rest = [r for r in rows if r.get(sort) is None]
    keyed.sort(key=lambda r: float(r[sort]), reverse=reverse)
    return keyed + rest


def _watchlist_symbols() -> list[str]:
    user = os.getenv("DEFAULT_USER_ID") or ""
    wls = db.select("watchlists", {"user_id": f"eq.{user}"}, "id,is_default") if user else []
    if not wls:
        return []
    wl = next((w for w in wls if w.get("is_default")), wls[0])
    items = db.select("watchlist_items", {"watchlist_id": f"eq.{wl['id']}", "active": "eq.true"},
                      "ticker_id")
    if not items:
        return []
    ids = [i["ticker_id"] for i in items if i.get("ticker_id")]
    tickers = db.select("tickers", {"id": f"in.({','.join(ids)})"}, "symbol")
    return sorted({t["symbol"].upper() for t in tickers if t.get("symbol")})


_universe_meta_cache = None


_stored_universe_cache: dict[str, tuple[float, list, object]] = {}
_presets_cache: dict[str, tuple[float, dict]] = {}
_execute_cache: dict[str, tuple[float, dict]] = {}


def _generation_pointer(market: str):
    states = db.select('app_settings', {'key': f'eq.universe_state_{market}'}, 'value')
    state = states[0].get('value') if states else {}
    if not isinstance(state, dict):
        raise HTTPException(503, 'Stored universe state is invalid')
    if 'generation_id' not in state:
        return None, state
    try:
        return canonical_generation(state['generation_id']), state
    except GenerationError as error:
        raise HTTPException(503, str(error)) from error


def _stored_universe(market: str, max_age: float = 60.0, generation_id: str | None = None):
    """Return one validated immutable cohort, or legacy rows before migration.

    Resolve the pointer on every request. Cache immutable contents by identity,
    never market alone, and return copies so consumers cannot change the cache.
    Explicit generations let a caller keep paging/exporting the original cohort.
    """
    pointer, state = _generation_pointer(market)
    target = generation_id if generation_id is not None else pointer
    now = time.time()
    if target is not None:
        try:
            canonical_generation(target)
            key = f'{market}|{target}'
            hit = _stored_universe_cache.get(key)
            if hit and now - hit[0] < max_age:
                rows, header = hit[1], hit[2]
            else:
                header, records = read_generation(db, market, target)
                rows = []
                for record in records:
                    row = dict(record['row'])
                    meta = record['metadata']
                    row.update({k: meta.get(k) for k in ('stock_type', 'exchange', 'plate')})
                    row.update({'symbol': record['code'].split('.', 1)[1],
                                'concepts': [v for v in meta['plates'] if v != meta.get('plate')],
                                'quote_cache_at': record['quote_cache_at'],
                                'quote_identity_status': 'verified', 'generation_id': target})
                    if not row.get('name'):
                        row['name'] = meta.get('name')
                    rows.append(row)
                _stored_universe_cache[key] = (now, rows, header)
                # Bound process memory; generations remain addressable in SQL.
                while len(_stored_universe_cache) > 4:
                    _stored_universe_cache.pop(next(iter(_stored_universe_cache)), None)
            if target == pointer:
                if aware_time(state.get('last_quotes')) != aware_time(header['published_at']):
                    raise GenerationError('Generation success clock does not match its receipt')
                result = state.get('last_result')
                receipt = header.get('result')
                if not isinstance(result, dict) or not isinstance(receipt, dict) or not isinstance(receipt.get('quotes'), dict) \
                        or json.dumps(result.get('quotes'), sort_keys=True) != json.dumps(receipt['quotes'], sort_keys=True):
                    raise GenerationError('Generation success counts do not match its receipt')
            return copy.deepcopy(rows), header['published_at']
        except GenerationError as error:
            raise HTTPException(503, str(error)) from error
    hit = _stored_universe_cache.get(market)
    if hit and now - hit[0] < max_age:
        return copy.deepcopy(hit[1]), hit[2]
    stored = db.select_all("screener_quotes", {"market": f"eq.{market}"}, "code,row,updated_at")
    rows = [{**r['row'], 'quote_cache_at':r.get('updated_at'),
             'quote_identity_status':'verified' if r.get('code') == r['row'].get('code') and r.get('code') else 'unverified'}
            for r in stored if isinstance(r.get("row"), dict)]
    for row in rows:
        code = row.get("code") or ""
        if code.startswith(f"{market}."):
            row["symbol"] = code.split(".", 1)[1]
    stamps = [r.get("updated_at") for r in stored if r.get("updated_at")]
    as_of = max(stamps) if stamps else None
    _stored_universe_cache[market] = (now, rows, as_of)
    return copy.deepcopy(rows), as_of


def _merge_universe_meta(rows: list[dict], market: str) -> list[dict]:
    """Attach plate / stock_type / exchange from the stored universe (cached 5 min)."""
    if rows and all(r.get('generation_id') for r in rows):
        return rows
    global _universe_meta_cache
    if _universe_meta_cache is None:
        from tradingagents_worker.ttl_cache import TtlCache  # noqa: E402
        _universe_meta_cache = TtlCache(root=os.path.join(tempfile.gettempdir(), "ta-ttl"))
    k = _universe_meta_cache.key("quotes", "universe-meta", market)
    meta = _universe_meta_cache.get("quotes", k)
    if meta is None:
        stored = db.select_all("screener_universe", {"market": f"eq.{market}"},
                               "code,plate,plates,stock_type,exchange")
        meta = {r["code"]: r for r in stored if r.get("code")}
        _universe_meta_cache.put("quotes", k, meta)
    if not meta:
        return rows
    for r in rows:
        u = meta.get(r.get("code")) or meta.get(f"{market}.{r.get('symbol')}")
        if u:
            r.setdefault("plate", u.get("plate"))
            r.setdefault("stock_type", u.get("stock_type"))
            r.setdefault("exchange", u.get("exchange"))
            plates = u.get("plates")
            if plates:
                r.setdefault("concepts", [p for p in plates if p != u.get("plate")])
    return rows


@app.get("/api/screener/facets")
def screener_facets(field: str, market: str = "US", watchlist_only: int = 0):
    """Distinct values (+counts) of a screener column over the active universe —
    drives the multi-select filter checkboxes."""
    cache = _cache()
    uk = cache.key("quotes", "screener-universe", market, watchlist_only, "market_cap", 2)
    rows = cache.get("quotes", uk) if watchlist_only else None
    if rows is None:
        if watchlist_only:
            symbols = _watchlist_symbols()
            snap = (client_snapshot(market, symbols) or {}) if symbols else {}
            rows = [_snapshot_to_row(s) for s in (snap.get("snapshot_list") or [])]
        else:
            rows, _as_of = _stored_universe(market)
        if not rows and not watchlist_only:
            client = _market_client()
            if client:
                try:
                    rows = _market_rows(market, "market_cap", 2, client)
                except Exception:
                    rows = []
        cache.put("quotes", uk, rows)
    if rows:
        rows = _merge_universe_meta(rows, market)
    from collections import Counter
    counter: Counter = Counter()
    for r in rows:
        v = r.get(field)
        if v is None:
            continue
        for item in (v if isinstance(v, list) else [v]):  # list fields (concepts) flatten
            counter[str(item)] += 1
    return {"field": field, "values": [{"value": v, "count": n} for v, n in counter.most_common(80)]}


def client_snapshot(market: str, symbols: list[str]):
    client = _market_client()
    if client is None or not symbols:
        return {}
    return client.snapshot([f"{market}.{s}" for s in symbols[:400]])


def _market_rows(market: str, sort_key: str, direction: int, client,
                 per_page: int = 300) -> list[dict]:
    """Whole-market universe by slice union: moomoo returns up to 300 items per
    stock-screen call and no pagination cursor, so we union several server-side
    sorts — the caller's sort first, then mktcap-desc / top-gainers / top-losers
    slices — deduped in order, then snapshot-enriched in 400-code batches.
    4 sorts x 300 = up to ~1,200 unique stocks; ~4 screen + 3 snapshot calls per
    cache refresh, well inside the 30/min per-path budget."""
    slices = [(sort_key, direction)]
    for s, d in (("market_cap", 2), ("pct", 2), ("pct", 1)):
        if (s, d) not in slices and s in _SCREEN_SORT_IDS:
            slices.append((s, d))
    codes: list[str] = []
    for s, d in slices:
        body = {"limit": min(per_page, 300),
                "screen_queries": [{"simple_field_query": {
                    "simple_field": 1, "screen_value_list": [_SCREEN_MARKET_ENUM.get(market, 2)]}}],
                "sort": {"direction": d, "simple_property": {"name": _SCREEN_SORT_IDS.get(s, 2301)}}}
        out = client.call("POST", "/quote/stock-screen", body=body)
        for it in (out.get("items") or []) if isinstance(out, dict) else []:
            c = it.get("code")
            if c and c not in codes:
                codes.append(c)
    if not codes:
        return []
    rows = []
    for i in range(0, len(codes), 400):
        snap = (client.snapshot(codes[i:i + 400]) or {}).get("snapshot_list") or []
        rows.extend(_snapshot_to_row(s) for s in snap)
    order = {code: i for i, code in enumerate(codes)}
    rows = [r for r in rows if r.get("code") in order]
    rows.sort(key=lambda r: order.get(r["code"], 999))
    return rows


_screener_cache = None


def _cache():
    global _screener_cache
    if _screener_cache is None:
        from tradingagents_worker.ttl_cache import TtlCache  # noqa: E402
        _screener_cache = TtlCache(root=os.path.join(tempfile.gettempdir(), "ta-ttl"))
    return _screener_cache


# Shared worker registry controls supplemental availability; derived LT debt
# is also yfinance-only. Never accept metadata/identity keys as factor fields.
_groups_cache = None  # retained for old test/reset callers; Groups never reuses aggregates
_YF_ONLY_FIELDS = YF_ONLY_FIELDS | {"lt_debt_eq"}


def _fresh_supplemental(data, row_stamp, now=None):
    """Registered finite fields with independent category retrieval clocks."""
    if not isinstance(data, dict):
        return {}, {}
    meta = data.get('_meta') if isinstance(data.get('_meta'), dict) else {}
    now = now or datetime.now(timezone.utc)
    values, origins = {}, {}
    for field, value in data.items():
        if field not in _YF_ONLY_FIELDS and field not in TECH_FIELDS:
            continue
        contracts = meta.get('field_contracts')
        if field in YF_FIELD_CONTRACTS and (not isinstance(contracts, dict) or contracts.get(field) != YF_FIELD_CONTRACTS[field]):
            continue  # old units/derivations cannot qualify until corrected refresh
        technical = field in TECH_FIELDS
        stamp = meta.get('technicals_at' if technical else 'fundamentals_at') or row_stamp
        try:
            age = (now - datetime.fromisoformat(str(stamp).replace('Z', '+00:00'))).total_seconds()
        except (TypeError, ValueError):
            continue
        if not 0 <= age <= (86400 if technical else 7 * 86400):
            continue
        text = field in {'country', 'sector', 'industry', 'website', 'earnings_date', 'ex_div_date'}
        if (text and not (isinstance(value, str) and value.strip())) or (not text and not numeric(value)):
            continue
        values[field] = value.strip() if text else value
        origins[field] = {'source': 'computed_technicals' if technical else 'yfinance',
                          'cache_at': stamp, 'timestamp_semantics': 'retrieval_or_computation_not_reporting_period'}
        if field in YF_FIELD_CONTRACTS:
            origins[field]['field_contract'] = YF_FIELD_CONTRACTS[field]
    return values, origins


@app.get('/api/screener/company-context')
def screener_company_context(code: str):
    """Bounded public cached company context; no quote/provider fetch or fallback taxonomy."""
    if not re.fullmatch(r'(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}',code):
        raise HTTPException(400,'Invalid canonical security code')
    entries=db.select('screener_enrichment',{'market':f"eq.{code.split('.',1)[0]}",'code':f'eq.{code}'},'code,data,as_of')
    entry=entries[0] if len(entries)==1 and entries[0].get('code')==code else {}
    values,origins=_fresh_supplemental(entry.get('data'),entry.get('as_of'))
    fields={field:values[field] for field in ('sector','industry','country','website') if field in values}
    return {'code':code,'fields':fields,'origins':{field:origins[field] for field in fields},
            'scope':'Current cached yfinance company classifications; not pinned to the quote generation. Missing/stale values remain unavailable.'}


@app.get("/api/screener")
def screener(market: str = "US", watchlist_only: int = 1, filters: str = "[]",
             sort: str = "market_cap", direction: int = 2, limit: int = 500,
             offset: int = 0, export: str = "", scope: str = "all",
             src: str = "moo", generation_id: str | None = None):
    """Screener rows. watchlist universe = our saved watchlist (snapshot, all filters);
    market universe = moomoo stock-screen page sorted server-side, snapshot-enriched."""
    client = _market_client()
    if generation_id is not None and watchlist_only:
        raise HTTPException(400, "generation_id applies to the stored market universe")
    if client is None and watchlist_only:
        return {"available": False, "reason": "moomoo keys not configured", "rows": []}
    try:
        flt = json.loads(filters) if filters else []
    except ValueError:
        raise HTTPException(400, "filters must be JSON")
    cache = _cache()
    universe_key = cache.key("quotes", "screener-universe", market, watchlist_only, sort, direction)
    rows = cache.get("quotes", universe_key) if watchlist_only else None
    universe_loaded = False
    universe_as_of = None
    pinned_generation = None
    if rows is None and not watchlist_only:
        # Preferred whole-market source: the stored universe (loaded by the
        # universe_refresh job) — zero moomoo calls at view time, cached 60s.
        rows, universe_as_of = _stored_universe(market, generation_id=generation_id)
        if rows:
            universe_loaded = True
            pinned_generation = rows[0].get("generation_id")
    if rows is None:
        if watchlist_only:
            symbols = _watchlist_symbols()
            if not symbols:
                return {"available": True, "rows": [], "universe": "watchlist", "count": 0,
                        "presets": PRESET_SCREENERS, "watchlist": _watchlist_symbols()}
            snap = (client.snapshot([f"{market}.{s}" for s in symbols[:400]])
                    or {}).get("snapshot_list") or []
            rows = [_snapshot_to_row(s) for s in snap]
        else:
            try:
                # When a filter targets a sortable column, sort server-side so the
                # page budget lands on relevant stocks: max-only bound → ascending
                # (cheapest/smallest first), otherwise descending.
                flt_sort, flt_dir = sort, direction
                for f in flt:
                    if f.get("field") in _SCREEN_SORT_IDS and (f.get("min") is not None or f.get("max") is not None):
                        flt_sort = f["field"]
                        flt_dir = 1 if f.get("min") is None and f.get("max") is not None else 2
                        break
                rows = _market_rows(market, flt_sort, flt_dir, client)
            except Exception as e:
                return {"available": False, "reason": str(e)[:120], "rows": []}
        cache.put("quotes", universe_key, rows)
    if rows:
        rows = _merge_universe_meta(rows, market)
    unknown_classifications = sum(not r.get("stock_type") or str(r.get("stock_type")).upper() in
                                  ("UNKNOWN", "UNKNOW", "UNCLASSIFIED", "N/A") for r in rows)
    # Classify explicitly; the public Moomoo universe can differ by venue/session.
    # Our stored universe also holds ETFs/indices/warrants (for stock pages);
    # whole-market mode restricts to STOCK unless the user filters Type.
    # Watchlist mode is exempt — it shows exactly what the user starred.
    if not watchlist_only and not any(f.get("field") == "stock_type" for f in flt):
        rows = [r for r in rows if r.get("stock_type") == "STOCK"]
    # Data-source mode (spec §5b): src=yf merges screener_enrichment keys into
    # rows; src=moo (strict) leaves rows untouched — moomoo-carried fields
    # only. Yf-only filters under moo are deferred with an honest reason.
    rows = [dict(r) for r in rows]
    enrich_as_of = None
    if src == "yf" and rows:
        stored_enr = db.select_all("screener_enrichment", {"market": f"eq.{market}"},
                                   "code,data,as_of")
        emap = {r["code"]: (r.get("data") or {}, r.get("as_of")) for r in stored_enr}
        stamps = [a for _, a in emap.values() if a]
        enrich_as_of = max(stamps) if stamps else None
        for r in rows:
            data, row_stamp = emap.get(r.get("code")) or \
                emap.get(f"{market}.{r.get('symbol')}") or ({}, None)
            if not isinstance(data,dict):data = {}
            meta = data.get("_meta") if isinstance(data.get("_meta"),dict) else {}
            supplied, supplied_origins = _fresh_supplemental(data, row_stamp)
            for k, v in supplied.items():
                if r.get(k) is None or r.get(k) == "":
                    r[k] = v
                    origins = dict(r.get("display_field_sources") or {})
                    origins[k] = supplied_origins[k]
                    r["display_field_sources"] = origins
                    observations = dict(r.get("field_observations") or {})
                    observations.pop(k, None)
                    r["field_observations"] = observations
            r["enrichment_dates"] = {"fundamentals": meta.get("fundamentals_at") or row_stamp,
                                     "technicals": meta.get("technicals_at") or row_stamp}
    deferred = []
    if src != "yf":
        yf_flt = [f for f in flt if f.get("field") in _YF_ONLY_FIELDS]
        deferred = [f"{f['field']} (requires src=yf)" for f in yf_flt]
        flt = [f for f in flt if f.get("field") not in _YF_ONLY_FIELDS]
    rows, skipped = _apply_filters(rows, flt)
    if deferred:
        rows = []
    skipped = skipped + deferred
    # Always display-sort in Python: the server-side slices decide WHICH stocks
    # are in the universe; global ordering across the union happens here.
    rows = _sort_rows(rows, sort, direction)
    matched = len(rows)
    if export:
        # scope=all → the whole matched set (cap 20k); scope=page → the current
        # page (limit/offset). CSV for everything, Excel-compatible SpreadsheetML
        # so Excel opens it natively without imports.
        if scope == "page":
            rows = rows[max(0, offset):max(0, offset) + max(1, min(limit, 20000))]
        else:
            rows = rows[:20000]
        cols = ["symbol", "name", "stock_type", "plate", "price", "pct", "chg",
                "market_cap", "float_cap", "shares", "volume", "turnover",
                "turnover_rate", "volume_ratio", "pe", "pe_ttm", "pb",
                "div_yield", "div_ttm", "eps", "amplitude", "bid_ask_ratio",
                "high52", "low52", "new_high", "new_low"]
        cols += list(dict.fromkeys(k for row in rows for k in row if k not in cols))
        money_cols=[field for field in cols if field in CURRENCY_FIELDS]
        cols += [field+'_currency' for field in money_cols if field+'_currency' not in cols]
        rows=[{**row,**{field+'_currency':field_currency(row,field) or 'Unavailable' for field in money_cols}} for row in rows]
        from xml.sax.saxutils import escape as _x
        from fastapi.responses import Response
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        fname = f"screener_{market}_{matched}rows_{stamp}"
        if export == "csv":
            def cell(v):
                s = "" if v is None else json.dumps(v,ensure_ascii=False,allow_nan=False) if isinstance(v,(dict,list)) else str(v)
                if isinstance(v,str) and re.match(r'^[=+@\-\t\r]',s):s="'"+s
                return '"' + s.replace('"', '""') + '"' if any(ch in s for ch in ',"\n') else s
            lines = [",".join(cell(c) for c in cols)]
            lines += [",".join(cell(r.get(c)) for c in cols) for r in rows]
            return Response("\ufeff" + "\n".join(lines), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{fname}.csv"',
                                     **({"X-Screener-Generation": pinned_generation} if pinned_generation else {})})
        xml = ['<?xml version="1.0"?><?mso-application progid="Excel.Sheet"?>',
               '<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" '
               'xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet">'
               '<Worksheet ss:Name="Screener"><Table>',
               "<Row>" + "".join(f'<Cell><Data ss:Type="String">{_x(str(c))}</Data></Cell>' for c in cols) + "</Row>"]
        for r in rows:
            cells = []
            for c in cols:
                v = r.get(c)
                if v is None:
                    cells.append("<Cell/>")
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    cells.append(f'<Cell><Data ss:Type="Number">{v}</Data></Cell>')
                else:
                    s=json.dumps(v,ensure_ascii=False,allow_nan=False) if isinstance(v,(dict,list)) else str(v)
                    cells.append(f'<Cell><Data ss:Type="String">{_x(s)}</Data></Cell>')
            xml.append("<Row>" + "".join(cells) + "</Row>")
        xml.append("</Table></Worksheet></Workbook>")
        return Response("".join(xml), media_type="application/vnd.ms-excel",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.xls"',
                                 **({"X-Screener-Generation": pinned_generation} if pinned_generation else {})})
    # limit up to 20000: the portal fetches the WHOLE matched set once per
    # minute and filters/sorts/pager client-side for instant interactivity.
    page = rows[max(0, offset):max(0, offset) + max(1, min(limit, 20000))]
    return {"available": True, "universe": "watchlist" if watchlist_only else market,
            "rows": page, "count": matched, "matched": matched, "shown": len(page),
            "offset": max(0, offset),
            "skipped_filters": skipped,
            "enrich_as_of": enrich_as_of,
            "universe_loaded": universe_loaded, "universe_as_of": universe_as_of,
            "generation_id": pinned_generation,
            "unclassified_count": unknown_classifications,
            "presets": PRESET_SCREENERS,
            "watchlist": _watchlist_symbols()}


@app.get("/api/screener/presets")
def screener_presets(market: str = "US", universe: str = "auto", definitions_only: bool = False):
    """ALL recommended screeners (one list) scored over the ACTIVE universe —
    whole-market (stored universe first, live slices as fallback) or watchlist.
    The stored universe needs no moomoo keys; only the live fallback does."""
    if definitions_only:
        return {"available": True, "presets": [{**p, "top": []} for p in PRESET_SCREENERS]}
    client = _market_client()
    cache = _cache()
    pointer, _state = _generation_pointer(market) if universe != "watchlist" else (None, {})
    if pointer:
        _stored_universe(market, generation_id=pointer)  # Validate current state even on preview cache hits.
    preview_key = f"{market}|{universe}|{pointer or 'legacy'}"
    hit = _presets_cache.get(preview_key)
    if hit and time.time() - hit[0] < 60.0:
        return hit[1]
    if universe == "watchlist":
        uk = cache.key("quotes", "screener-universe", market, 1, "market_cap", 2)
        rows = cache.get("quotes", uk)
        if rows is None:
            symbols = _watchlist_symbols()
            if client is None or not symbols:
                rows = []
            else:
                snap = (client.snapshot([f"{market}.{s}" for s in symbols[:400]])
                        or {}).get("snapshot_list") or []
                rows = [_snapshot_to_row(s) for s in snap]
            cache.put("quotes", uk, rows)
    else:
        try:
            rows, _as_of = _stored_universe(market, generation_id=pointer)
        except HTTPException:
            raise
        except Exception:
            rows = []
        if not rows:
            uk = cache.key("quotes", "screener-universe", market, 0, "market_cap", 2)
            rows = cache.get("quotes", uk)
            if rows is None:
                if client is None:
                    rows = []
                else:
                    try:
                        rows = _market_rows(market, "market_cap", 2, client)
                    except Exception:
                        rows = []
                    cache.put("quotes", uk, rows)
    # Presets execute server-side (see /api/screener/execute) — every filter in
    # every preset is backed by a verified stock-screen property, so there is
    # nothing to skip there. The card previews are scored here over the stored
    # universe, restricted to common stocks (classification lives in
    # screener_universe, not the quote rows, so merge it in first). Each card
    # ranks over ITS OWN filters by %chg — verified against moomoo.com/screener,
    # whose cards do headline +9,900% dead prints where they genuinely match
    # (P/B < 1) but keep them out of Penny Stocks via the 30-day-AVERAGE
    # volume filter. Our snapshot only has today's volume, so presets carrying
    # a days-averaged volume filter additionally require USD 10k turnover
    # today — a real 100k-shares/day name virtually never prints a $1k day.
    rows = _merge_universe_meta(rows, market)
    rows = [r for r in rows if r.get("stock_type") == "STOCK"]
    liquid = [r for r in rows if (r.get("turnover") or 0) >= 10_000]
    out = []
    for preset in PRESET_SCREENERS:
        pool = (liquid if any(f.get("field") == "volume" and f.get("days")
                              for f in preset.get("filters") or []) else rows)
        matched, _ = _apply_filters(pool, preset.get("filters") or [], strict=False)
        picked = _sort_rows(matched, preset.get("sort", "pct"), preset.get("direction", 2))[:3]
        out.append({**preset, "sort": preset.get("sort", "pct"), "direction": preset.get("direction", 2),
                    "top": [{"symbol": r["symbol"],
                             "name": str(r.get("name") or "")[:22],
                             "pct": r.get("pct")} for r in picked]})
    out_payload = {"available": True, "presets": out, "universe_rows": len(rows), "generation_id": pointer}
    _presets_cache[preview_key] = (time.time(), out_payload)
    return out_payload

class ScheduleIn(BaseModel):
    interval_h: int


@app.get("/api/screener/schedule")
def screener_schedule_get(market: str = 'US'):
    """Universe-refresh cadence + current loader state (settings page + cron).
    stock_rows/other_rows explain the count gap vs moomoo's app total: the app
    counts every instrument type; the screener serves common stocks by default."""
    if market not in ('US', 'HK'):
        raise HTTPException(400, 'market must be US or HK')
    config = _universe_state()
    states = db.select('app_settings', {'key': f'eq.universe_state_{market}'}, 'value')
    state = (states[0].get('value') or {}) if states else {}
    if 'generation_id' in state:
        rows, _published_at = _stored_universe(market, generation_id=state['generation_id'])
        urows = rows
    else:
        rows = db.select_all("screener_quotes", {"market": f"eq.{market}"}, "code")
        urows = db.select_all("screener_universe", {"market": f"eq.{market}"}, "code,stock_type")
    stock_rows = sum(1 for r in urows if r.get("stock_type") == "STOCK")
    return {"market": market, "interval_h": float(config.get("interval_h") or 1),
            "last_quotes": state.get("last_quotes"), "last_enum": state.get("last_enum"),
            "last_result": state.get("last_result") or {},
            "last_attempt": state.get('last_attempt'),
            "generation_id": state.get("generation_id"),
            "quote_rows": len(rows), "universe_rows": len(urows),
            "stock_rows": stock_rows, "other_rows": len(urows) - stock_rows}


@app.put("/api/screener/schedule")
def screener_schedule_put(inp: ScheduleIn):
    if inp.interval_h not in (1, 2, 4, 8, 12, 24):
        raise HTTPException(400, "interval_h must be one of 1, 2, 4, 8, 12, 24")
    state = _universe_state()
    state["interval_h"] = inp.interval_h
    db.upsert("app_settings", "key", {"key": "universe_state", "value": state})
    return {"saved": True, "interval_h": inp.interval_h}


def _universe_state() -> dict:
    rows = db.select("app_settings", {"key": "eq.universe_state"}, "value")
    return (rows[0].get("value") or {}) if rows else {}


@app.post("/api/screener/probe")
def screener_probe(body: dict):
    """TEMP property-dictionary discovery for stock-screen (read-only).
    Passes the caller's payload straight through to the stock-screen API."""
    client = _market_client()
    if client is None:
        return {"available": False, "reason": "moomoo keys not configured"}
    try:
        data = client.call("POST", "/quote/stock-screen", body=body)
        return {"available": True, "data": data}
    except Exception as e:  # noqa: BLE001 — probe reports errors verbatim
        return {"available": True, "error": str(e)[:400]}


# ── server-side preset execution (moomoo's own screener semantics) ──────
# Property dictionary reverse-engineered live 2026-09-28 (probes vs known
# NVDA/AAPL/Tencent figures; Futu OpenAPI get-stock-screen reference):
#   simple: 2201 price(x1000 out) · 2301 market_cap(x1000 out) · 2305 div_yield_ttm(x1000)
#   cumulative: 3104 avg volume (days param)              [Penny's 30-day volume]
#   financial (term=100=annual, filter values x1000, percents as 10%->10000):
#     4102 net_profit_growth · 4106 revenue_growth · 4107 net_margin
#     4108 gross_margin · 4109 debt_to_asset · 4110 roe
#     4606 eps_yoy_growth · 4607 roe_yoy_growth · 4903 float_market_cap (raw $)
#     4801 basic_eps (x1000)
# RSI's documented query is rejected by the configured provider; fail closed.
# Ten-day lows use property 3108 with days inside the property query.
_FIELD_SERVER = {
    # scales verified against moomoo's own screener payloads (SSR 2026-09-28):
    # simple money x1000 · PE/PB x100000 · financial percents (10% -> 10000)
    # and financial money x1000 · RSI value x1000
    "price":              ("simple", 2201, 1000.0),
    "market_cap":         ("simple", 2301, 1000.0),
    "pe_ttm":             ("simple", 2303, 100000.0),
    "pb":                 ("simple", 2304, 100000.0),
    "div_yield":          ("financial", 4219, 1000.0),   # Dividends TTM ratio %
    "volume":             ("cumulative", 3104, 1.0),      # N-day avg volume, raw shares
    "net_profit_growth":  ("financial", 4102, 1000.0),
    "revenue_growth":     ("financial", 4106, 1000.0),
    "net_margin":         ("financial", 4107, 1000.0),
    "gross_margin":       ("financial", 4108, 1000.0),
    "debt_ratio":         ("financial", 4109, 1000.0),
    "roe":                ("financial", 4110, 1000.0),
    "eps_growth":         ("financial", 4606, 1000.0),

    "roe_yoy":            ("financial", 4607, 1000.0),
    "op_profit_growth":   ("financial", 4607, 1000.0),  # Preserved legacy preset key: Moomoo labels this ROE YOY.
    "op_ebt":             ("financial", 4702, 1000.0),
    "float_cap":          ("financial", 4903, 1000.0),   # raw dollars x1000
    "eps":                ("financial", 4801, 1000.0),
}
_FINANCIAL_TERM = 100  # annual


def _server_filter(field: str, f: dict) -> dict | None:
    """Our filter object -> stock-screen server query; None = not server-side.
    Special forms match moomoo's own payloads verbatim: RSI via
    indicatorPositionalQuery, 10-day new low via cumulative 3108, sectors via
    plateQuery plateIdList (numeric ids from moomoo's strategy payloads)."""
    if field == "rsi14":
        # Live probes: the legacy camel-case form ignores RSI; the published
        # snake-case form returns invalid_parameter. Never claim qualification
        # until this provider capability is verified.
        return None
    if field == "new_low_10d":
        return {"cumulative_property_query": {"property": {"name": 3108, "days": 10}, "days": 10,
                                              "upper": {"value": 0, "includes": False}}}
    if field == "sector":
        ids = f.get("plate_ids") or []
        if not ids:
            return None
        return {"plate_query": {"plateList": [{"plateIdList": [int(i) for i in ids]}]}}
    spec = _FIELD_SERVER.get(field)
    if not spec:
        return None
    kind, pid, scale = spec
    lo, hi = f.get("min"), f.get("max")
    rng = {}
    if lo is not None:
        rng["lower"] = {"value": round(float(lo) * scale, 6), "includes": not f.get("excl_min")}
    if hi is not None:
        rng["upper"] = {"value": round(float(hi) * scale, 6), "includes": not f.get("excl_max")}
    if not rng:
        return None
    if kind == "simple":
        return {"simple_property_query": {"property": {"name": pid}, **rng}}
    if kind == "cumulative":
        return {"cumulative_property_query": {"property": {"name": pid, "periodAverage": int(f.get("days") or 30)},
                                              "days": int(f.get("days") or 30),
                                              "periodAverage": int(f.get("days") or 30), **rng}}
    return {"financial_property_query": {"property": {"name": pid, "term": _FINANCIAL_TERM}, **rng}}


def _server_retrieves(fields: list[str | dict]) -> list[dict]:
    out = []
    for criterion in fields:
        f = criterion.get('field') if isinstance(criterion, dict) else criterion
        spec = _FIELD_SERVER.get(f)
        if not spec:
            continue
        kind, pid, _ = spec
        if kind == "simple":
            out.append({"simple_property": {"name": pid}})
        elif kind == "cumulative":
            out.append({"cumulative_property": {"name": pid, "periodAverage": int(criterion.get('days') or 30) if isinstance(criterion, dict) else 30}})
        else:
            out.append({"financial_property": {"name": pid, "term": _FINANCIAL_TERM}})
    return list({json.dumps(q, sort_keys=True):q for q in out}.values())


def _screen_result_number(record: dict) -> float | None:
    res = record.get('res') or record
    raw = res.get('ival')
    if raw is None:
        raw = res.get('dval')
    if raw is None and 'res' not in record:
        raw = record.get('value')
    if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
        return None
    try:
        value = float(raw)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _screen_criterion_evidence(code: str, filters: list[dict], results: list[dict], retrieved_at: str) -> list[dict]:
    """Attribute retrieval values to exact requested criteria, without inventing periods."""
    evidence = []
    for criterion in filters:
        field = criterion.get('field')
        spec = _FIELD_SERVER.get(field)
        candidates = []
        if spec:
            kind, pid, scale = spec
            windows = {int(c.get('days') or 30) for c in filters if _FIELD_SERVER.get(c.get('field'), ())[:2] == (kind,pid)}
            for result in results:
                result_kind, record = next(iter(result.items()))
                prop = record.get('property', {})
                if prop.get('name') != pid or result_kind != kind+'_property_result':
                    continue
                if kind == 'financial' and prop.get('term') not in (None, _FINANCIAL_TERM):
                    continue
                if kind == 'cumulative':
                    days = prop.get('periodAverage')
                    if days is None and len(windows) != 1:
                        continue
                    if days is not None and days != int(criterion.get('days') or 30):
                        continue
                candidates.append(_screen_result_number(record))
        value = candidates[0] / spec[2] if spec and len(candidates) == 1 and candidates[0] is not None else None
        evidence.append({'code':code, 'criterion':copy.deepcopy(criterion), 'value':value,
                         'source':'provider_screen', 'retrieved_at':retrieved_at,
                         'period':None, 'currency':None,
                         'status':'retrieved_value_unqualified' if value is not None else 'value_unavailable'})
    return evidence


@app.get("/api/screener/execute")
def screener_execute(key: str = "", market: str = "US", limit: int = 60, next_key: str = "",
                     quote_generation_id: str | None = None, refresh: bool = False):
    """Execute provider-defined rules; hydrate display quotes from one cohort.

    Provider membership and retrieval time remain distinct from stored quote
    generation and financial/source times. Reconciliation requires live evidence.
    """
    if key.startswith("saved:"):
        sid = key.split(":", 1)[1]
        rows0 = db.select("saved_screeners", {"id": f"eq.{sid}"})
        if not rows0:
            raise HTTPException(404, "saved screener not found")
        s = rows0[0]
        market = s.get("market") or market
        filters = s.get("filters") or []
        name = s.get("name")
        sort, direction = s.get("sort", "market_cap"), s.get("direction", 2)
        description = s.get("description")
    else:
        preset = next((p for p in PRESET_SCREENERS if p["key"] == key), None)
        if not preset:
            raise HTTPException(404, "unknown preset")
        filters = preset["filters"]
        name, description = preset["name"], preset.get("description")
        sort, direction = preset.get("sort", "pct"), preset.get("direction", 2)
    market = market.upper()
    if market not in ('US', 'HK'):
        raise HTTPException(400, 'market must be US or HK')
    cohort, _published_at = _stored_universe(market, generation_id=quote_generation_id)
    quote_generation = cohort[0].get('generation_id') if cohort else None
    ck = json.dumps([key, market, min(limit,300), next_key, quote_generation, filters, sort, direction], sort_keys=True)
    hit = _execute_cache.get(ck)
    if not refresh and hit and time.time() - hit[0] < 60.0:
        return copy.deepcopy(hit[1])
    client = _market_client()
    if client is None:
        return {"available": False, "reason": "moomoo keys not configured"}
    mkt = {"US": 2, "HK": 1}.get(market.upper(), 2)
    queries: list[dict] = [{"simple_field_query": {"simple_field": 1, "screen_value_list": [mkt]}}]
    pending = []
    for f in filters:
        q = _server_filter(f.get("field"), f)
        if q is None:
            pending.append(f.get("field"))
        else:
            queries.append(q)
    if pending:
        return {"available": False, "rows": [], "pending": pending,
                "reason": "This screen cannot be fully evaluated: provider criteria unavailable (" + ", ".join(pending) + "). Its saved definition is preserved."}
    retrieves = _server_retrieves(filters)
    retrieves += [{"simple_property": {"name": 2201}}, {"simple_property": {"name": 2301}},
                  {"cumulative_property": {"name": 3102, "days": 1}}]
    sort_property = {"pct": 2210, "market_cap": 2301, "price": 2201, "pe_ttm": 2303, "pb": 2304}.get(sort, 2301)
    body = {"screen_queries": queries, "sort": ({"direction": direction, "cumulative_property": {"name": 3102, "days": 1}} if sort == "pct" else {"direction": direction, "simple_property": {"name": sort_property}}),
            "limit": max(1, min(limit, 300)), "retrieve_queries": retrieves}
    if next_key:
        body["next_key"] = next_key
    try:
        data = client.call("POST", "/quote/stock-screen", body=body)
    except Exception as e:  # noqa: BLE001
        return {"available": False, "reason": str(e)[:160]}
    if not isinstance(data, dict) or not isinstance(data.get('items'), list):
        return {'available':False,'rows':[],'reason':'Provider membership response is invalid'}
    items = data.get('items') or []
    identities = [it.get('code') if isinstance(it,dict) else None for it in items]
    if any(not isinstance(c,str) or not re.fullmatch(re.escape(market)+r'\.[A-Z0-9][A-Z0-9._-]{0,30}',c) for c in identities) or len(set(identities)) != len(identities):
        return {'available':False,'rows':[],'reason':'Provider membership identities are invalid or duplicated'}
    for item in items:
        results = item.get('results')
        if results is not None and not isinstance(results,list):
            return {'available':False,'rows':[],'reason':'Provider criterion response is invalid'}
        for result in results or []:
            if not isinstance(result,dict) or len(result) != 1:
                return {'available':False,'rows':[],'reason':'Provider criterion response is invalid'}
            record = next(iter(result.values()))
            if not isinstance(record,dict) or not isinstance(record.get('property',{}),dict) or ('res' in record and record['res'] is not None and not isinstance(record['res'],dict)):
                return {'available':False,'rows':[],'reason':'Provider criterion response is invalid'}
            pid = record.get('property', {}).get('name')
            if pid is not None and (isinstance(pid, bool) or not isinstance(pid, int)):
                return {'available':False,'rows':[],'reason':'Provider criterion property identity is invalid'}
    pagination = data.get('pagination')
    if pagination is not None and not isinstance(pagination,dict):
        return {'available':False,'rows':[],'reason':'Provider pagination response is invalid'}
    retrieved_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for it in items:
        vals = {}
        for r in it.get("results") or []:
            rr = list(r.values())[0]
            pid = rr.get("property", {}).get("name")
            # Legacy field-only values cannot identify repeated properties/windows.
            value = _screen_result_number(rr)
            if next(iter(r)) == 'financial_property_result' and rr.get('property', {}).get('term') not in (None, _FINANCIAL_TERM):
                value = None
            vals[pid] = None if pid in vals else value
        code = it.get("code") or ""
        pct = vals.get(3102, vals.get(2210))
        rows.append({
            "symbol": code.split(".", 1)[-1], "code": code, "name": it.get("name") or "",
            "price": vals[2201] / 1000 if vals.get(2201) is not None else None,
            "pct": pct / 1000 if pct is not None else None,
            "market_cap": vals[2301] / 1000 if vals.get(2301) is not None else None,
            "factors": {k: v for k, v in vals.items() if k not in (2201, 2301, 2210, 3102)},
            "criterion_values": {f: vals[spec[1]] / spec[2] for f, spec in _FIELD_SERVER.items()
                                 if vals.get(spec[1]) is not None},
            "criterion_evidence": _screen_criterion_evidence(code, filters, it.get('results') or [], retrieved_at),
            "criterion_retrieved_at": retrieved_at,
        })
        # Requested annual financial fields retain provider values; actual
        # reporting periods are unverified until independently supplied.
        # Period-averaged volume stays separate from the snapshot volume column.
        for field, value in rows[-1]["criterion_values"].items():
            if _FIELD_SERVER[field][0] == "financial":
                rows[-1][field] = value
    hydration_warnings = []
    codes = sorted({r['code'] for r in rows})
    if codes:
        by_code = {q.get('code'):q for q in cohort if q.get('code')}
        protected = {'code','symbol','criterion_values','criterion_evidence','criterion_retrieved_at','factors','generation_id'}
        for row in rows:
            original_fields = {k for k,v in row.items() if v is not None and v != ''}
            origins = {k:{'source':'provider_screen','retrieved_at':retrieved_at} for k in original_fields
                       if k not in ('code','symbol','criterion_values','criterion_evidence','criterion_retrieved_at','factors')}
            quote = by_code.get(row['code']) or {}
            for field,value in quote.items():
                if field in protected or value is None:
                    continue
                if row.get(field) is None or field == 'name' and not row.get('name'):
                    row[field] = copy.deepcopy(value)
                    origins[field] = {'source':'stored_generation' if quote_generation else 'legacy_cache',
                                      'generation_id':quote_generation,'cache_at':quote.get('quote_cache_at')}
            row['display_field_sources'] = origins
            row['quote_generation_id'] = quote_generation if quote else None
        # Outside-cohort screen members stay in provider membership. Hydration
        # is marked separately and cannot pretend to belong to the generation.
        missing = [r['code'] for r in rows if r.get('price') is None]
        if missing:
            try:
                snapshots = (client.snapshot(missing) or {}).get('snapshot_list') or []
                if not isinstance(snapshots,list) or any(not isinstance(q,dict) for q in snapshots):
                    raise ValueError('Invalid snapshot records')
                returned = [q.get('code') for q in snapshots]
                if len(returned) != len(set(returned)) or set(returned) != set(missing):
                    raise ValueError('Snapshot identities differ from request')
                cache_at = datetime.now(timezone.utc).isoformat()
                live = {q['code']:_snapshot_to_row(q) for q in snapshots}
                for row in rows:
                    for field,value in (live.get(row['code']) or {}).items():
                        if field not in protected and value is not None and row.get(field) is None:
                            row[field] = value
                            row['display_field_sources'][field] = {'source':'live_snapshot','cache_at':cache_at}
                    if row['code'] in live:
                        row['quote_cache_at'] = cache_at
            except Exception:
                hydration_warnings.append('Quote display data is unavailable or has mismatched identities; no values inferred')
        if not quote_generation:
            _merge_universe_meta(rows, market)
        unclassified = [r['code'] for r in rows if not r.get('stock_type')]
        if unclassified:
            try:
                basic = client.call('POST','/quote/stock-basicinfo',body={'code_list':unclassified}) or {}
                records = basic.get('basic_list') or []
                if not isinstance(records,list) or any(not isinstance(b,dict) for b in records):
                    raise ValueError('Invalid basic records')
                returned = [b.get('code') for b in records]
                if len(returned) != len(set(returned)) or set(returned) != set(unclassified):
                    raise ValueError('Classification identities differ from request')
                info = {b['code']:b for b in records}
                for row in rows:
                    for field in ('stock_type','exchange'):
                        if not row.get(field) and row['code'] in info:
                            row[field] = info[row['code']].get(field)
                            row['display_field_sources'][field] = {'source':'provider_basicinfo','retrieved_at':datetime.now(timezone.utc).isoformat()}
            except Exception:
                hydration_warnings.append('Instrument classification is unavailable or has mismatched identities; unknown instruments remain unclassified')
    for row in rows:
        # A provider-screen value must not inherit an observation for a different
        # snapshot value. Only copied metric observations retain their source.
        observations = row.get('field_observations')
        if isinstance(observations,dict):
            row['field_observations'] = {field:record for field,record in observations.items()
                if isinstance(record,dict) and record.get('code') == row['code']
                and record.get('value') == row.get(field)
                and (row.get('display_field_sources',{}).get(field) or {}).get('source') in
                    ('stored_generation','legacy_cache','live_snapshot')}
    pagination = data.get("pagination") or {}
    cursor = pagination.get("next_key") or data.get("next_key") or data.get("nextKey")
    has_more = pagination.get("has_more")
    if has_more is None:
        has_more = bool(data.get("has_more") or data.get("hasMore") or (cursor and cursor != "-1") or len(items) >= body["limit"])
    out_payload = {"available": True, "key": key, "name": name, "description": description,
                   "market": market, "pending": pending, "filters": filters,
                   "sort": sort, "direction": direction, "result_limit": body["limit"],
                   "possibly_truncated": bool(has_more), "next_key": cursor if cursor != "-1" else None,
                   "provider_total": pagination.get("total", data.get("total")), "retrieved_at": retrieved_at,
                   "quote_generation_id": quote_generation, "quote_scope": "display_hydration",
                   "hydration_warnings": hydration_warnings,
                   "unclassified_count": sum(not r.get("stock_type") or str(r.get("stock_type")).upper() in ("UNKNOWN","UNKNOW","UNCLASSIFIED","N/A") for r in rows),
                   "outside_quote_cohort": sum(r["code"] not in by_code for r in rows) if rows else 0,
                   "evidence_status": "provider_membership", "rows": rows, "shown": len(rows)}
    _execute_cache[ck] = (time.time(), copy.deepcopy(out_payload))
    while len(_execute_cache) > 64:
        _execute_cache.pop(next(iter(_execute_cache)), None)
    return out_payload


@app.post("/api/screener/refresh")
def screener_refresh(market: str = "US", force: int = 0):
    """Queue a full-market universe refresh as a worker job; progress streams
    to job_events ('universe' stage) — the UI polls it for the progress bar."""
    for status in ("pending", "running"):
        live = db.select("jobs", {"job_type": f"eq.universe_refresh", "status": f"eq.{status}"},
                         "id,status")
        if live:
            return {"queued": True, "job_id": live[0]["id"], "already_running": True}
    user = os.getenv("DEFAULT_USER_ID") or None
    row = db.insert("jobs", {
        "job_type": "universe_refresh", "user_id": user,
        "payload": {"market": market, **({"force": True} if force else {})},
        "idempotency_key": f"universe-refresh:{market}:{uuid.uuid4()}",
    }, prefer="return=representation")
    job = row if isinstance(row, dict) else (row or [{}])[0]
    return {"queued": True, "job_id": job.get("id")}


@app.post("/api/watchlist/{symbol}")
def watchlist_add(symbol: str, active: bool = True):
    """Set a ticker's star in the owner's default watchlist (soft removal)."""
    user = os.getenv("DEFAULT_USER_ID") or ""
    if not user:
        raise HTTPException(503, "DEFAULT_USER_ID not configured")
    sym = symbol.upper()
    wl = db.select("watchlists", {"user_id": f"eq.{user}"}, "id,is_default")
    if wl:
        wid = next((w for w in wl if w.get("is_default")), wl[0])["id"]
    else:
        wid = str(uuid.uuid4())
        db.insert("watchlists", {"id": wid, "user_id": user, "name": "Default",
                                 "is_default": True}, prefer="return=minimal")
    tk = db.select("tickers", {"symbol": f"eq.{sym}"}, "id")
    if tk:
        tid = tk[0]["id"]
    else:
        tid = str(uuid.uuid4())
        db.insert("tickers", {"id": tid, "symbol": sym, "native_symbol": sym,
                              "asset_type": "stock"}, prefer="return=minimal")
    db.upsert("watchlist_items", "watchlist_id,ticker_id",
              {"watchlist_id": wid, "ticker_id": tid, "active": active})
    return {"saved": True, "symbol": sym}


# ── Saved screeners ("Save Screener" + manage in the filter modal) ──────

class SavedScreenerIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=300)
    market: str = Field(default="US", pattern="^(US|HK)$")
    watchlist_only: bool = False
    filters: list[dict] = Field(default_factory=list, max_length=40)
    sort: str = "market_cap"
    direction: int = Field(default=2, ge=1, le=2)
    settings: dict = Field(default_factory=dict)


def _screener_owner() -> str:
    user = os.getenv("DEFAULT_USER_ID") or ""
    if not user:
        raise HTTPException(503, "DEFAULT_USER_ID not configured")
    return user


@app.get("/api/screeners")
def list_saved_screeners():
    user = _screener_owner()
    rows = db.select("saved_screeners", {"user_id": f"eq.{user}",
                                         "order": "updated_at.desc"})
    return {"screeners": rows}


@app.post("/api/screeners")
def save_screener(inp: SavedScreenerIn):
    user = _screener_owner()
    row = db.insert("saved_screeners", {
        "user_id": user, "name": inp.name.strip(), "description": inp.description,
        "market": inp.market, "watchlist_only": inp.watchlist_only,
        "filters": inp.filters, "sort": inp.sort, "direction": inp.direction, "settings": inp.settings,
    }, prefer="return=representation")
    return {"saved": True, "screener": (row if isinstance(row, dict) else (row or [{}])[0])}


@app.put("/api/screeners/{sid}")
def update_screener(sid: str, inp: SavedScreenerIn):
    user = _screener_owner()
    existing = db.select("saved_screeners", {"id": f"eq.{sid}", "user_id": f"eq.{user}"}, "id")
    if not existing:
        raise HTTPException(404, "screener not found")
    db.update("saved_screeners", f"id=eq.{sid}", {
        "name": inp.name.strip(), "description": inp.description,
        "market": inp.market, "watchlist_only": inp.watchlist_only,
        "filters": inp.filters, "sort": inp.sort, "direction": inp.direction,
        **({"settings": inp.settings} if "settings" in inp.model_fields_set else {}),
        "updated_at": datetime.now(timezone.utc).isoformat()})
    return {"saved": True, "id": sid}


@app.delete("/api/screeners/{sid}")
def delete_screener(sid: str):
    user = _screener_owner()
    existing = db.select("saved_screeners", {"id": f"eq.{sid}", "user_id": f"eq.{user}"}, "id")
    if not existing:
        raise HTTPException(404, "screener not found")
    db.delete("saved_screeners", f"id=eq.{sid}")
    return {"deleted": True}


@app.get("/api/candidates")
def candidates(status: str = "open"):
    return {"candidates": db.select("discovery_candidates",
                                    {"status": f"eq.{status}", "order": "score.desc,created_at.desc"})}


@app.post("/api/candidates/{cid}/queue")
def queue_candidate(cid: str, depth: str = "standard", _: None = Depends(require_cron)):
    rows = db.select("discovery_candidates", {"id": f"eq.{cid}"})
    if not rows:
        raise HTTPException(404, "candidate not found")
    c = rows[0]
    if not c.get("symbol"):
        raise HTTPException(400, "candidate has no symbol")
    job = submit(AnalyzeIn(ticker=c["symbol"], trade_date=date.today(), depth=depth))
    db.update("discovery_candidates", f"id=eq.{cid}", {"status": "run_queued", "job_id": job["job_id"]})
    return job


@app.get("/api/meta")
def meta():
    spend_available = True
    try:
        runs = db.select("runs", {"order": "created_at.desc", "limit": "500"},
                         "cost_usd,prompt_tokens,completion_tokens")
    except RuntimeError:
        runs = []
        spend_available = False
    spend = {"available": spend_available, "runs": len(runs),
             "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in runs), 4),
             "tokens_in": sum(int(r.get("prompt_tokens") or 0) for r in runs),
             "tokens_out": sum(int(r.get("completion_tokens") or 0) for r in runs)}
    return {"framework": "tradingagents 0.5.1", "markets": ["US", "HK", "ASX"],
            "vendors": {"live": "moomoo", "fallback": "yfinance", "fundamentals": "sec_edgar+yfinance",
                        "news": "yfinance+fmp", "macro": "fred", "prediction": "polymarket"},
            "stock_page": {"fixtures_mode": bool(os.getenv("TA_STOCK_FIXTURES")),
                           "info_page": "/#/info"},
            "stub_mode": SETTINGS.stub_mode, "spend": spend}


# Screen snapshots contain server-validated membership, never client-submitted rows.
class ScreenDefinition(BaseModel):
    market: str = Field(default="US", pattern="^(US|HK)$")
    src: str = Field(default="moo", pattern="^(moo|yf)$")
    etfs: bool = False
    watchlist_only: bool = False
    filters: list[dict] = Field(default_factory=list, max_length=60)
    preset: str | None = Field(default=None, max_length=100)


def _snapshot_key(definition: ScreenDefinition) -> str:
    spec = definition.model_dump()
    if definition.preset:
        p = next((p for p in PRESET_SCREENERS if p["key"] == definition.preset), None)
        if not p:
            raise HTTPException(400, "Only named recommended presets support provider snapshots")
        spec["preset_definition"] = p
    spec["version"] = 1
    digest = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
    owner = hashlib.sha256(_screener_owner().encode()).hexdigest()[:16]
    return "screen_history:" + owner + ":" + digest


def _capture_criteria(inp: ScreenDefinition) -> ScreenDefinition:
    if not inp.preset:
        return inp
    original = next(p['filters'] for p in PRESET_SCREENERS if p['key'] == inp.preset)
    return inp.model_copy(update={'filters':original+[c for c in inp.filters if c not in original]})


def _legacy_snapshot_history(key: str) -> list[dict]:
    try:
        rows = db.select("app_settings", {"key": f"eq.{key}"}, "value")
    except (RuntimeError, OSError):
        raise HTTPException(503, "Legacy capture storage is temporarily unavailable.") from None
    history = (rows[0].get("value") or {}).get("snapshots", []) if rows else []
    if not isinstance(history, list) or any(not isinstance(record, dict) for record in history):
        raise HTTPException(409, "Legacy capture history is invalid; no evidence replaced")
    return history


def _capture_select(query: dict, columns: str = "*") -> list[dict]:
    try:
        return db.select("screen_captures", query, columns)
    except (RuntimeError, OSError):
        raise HTTPException(503, "Capture storage is unavailable. Existing history has not been replaced.") from None


def _snapshot_history(key: str) -> list[dict]:
    records = _capture_select({"history_key": f"eq.{key}", "order": "at.desc,id.desc", "limit": "2"}, "snapshot")
    return [r['snapshot'] for r in reversed(records)] if records else _legacy_snapshot_history(key)


def _snapshot_get(key: str, sid: str) -> dict | None:
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', sid):
        raise HTTPException(400, "Invalid capture identity")
    records = _capture_select({"history_key": f"eq.{key}", "id": f"eq.{sid}", "limit": "1"}, "snapshot")
    if records:
        return records[0]['snapshot']
    return next((r for r in _legacy_snapshot_history(key) if _snapshot_id(r) == sid), None)


def _snapshot_metadata_page(key: str, limit: int = 100, offset: int = 0) -> tuple[list[dict], bool]:
    if not 1 <= limit <= 100 or not 0 <= offset <= 40000:
        raise HTTPException(400, "Invalid capture history pagination")
    columns = "id,at,source_at,source_clock,complete,members,version"
    records = _capture_select({"history_key": f"eq.{key}", "order": "at.desc,id.desc",
                               "limit": str(limit + 1), "offset": str(offset)}, columns)
    if not records:
        # Legacy fallback is only appropriate before the first successful import.
        exists = _capture_select({"history_key": f"eq.{key}", "limit": "1"}, "id")
        if not exists:
            records = list(reversed([_snapshot_meta(r) for r in _legacy_snapshot_history(key)]))[offset:offset+limit+1]
    return [{column: r.get(column) for column in columns.split(",")} for r in reversed(records[:limit])], len(records) > limit


@app.post("/api/screener/snapshots")
def capture_screen_snapshot(inp: ScreenDefinition,
                            request_id: Annotated[uuid.UUID | None, Header(alias="Idempotency-Key")] = None,
                            generation_id: Annotated[uuid.UUID | None, Header(alias="X-Screener-Generation")] = None):
    pinned_generation = str(generation_id) if generation_id is not None else None
    if pinned_generation and (inp.preset or inp.watchlist_only):
        raise HTTPException(400, "Generation pinning requires a stored market screen")
    key = _snapshot_key(inp)
    if request_id:
        existing = _snapshot_get(key, str(request_id))
        if existing:
            if pinned_generation and existing.get("source_generation_id") != pinned_generation:
                raise HTTPException(409, "Capture request already belongs to a different generation")
            return _capture_reply(key, existing, True)
    inp = _capture_criteria(inp)
    observations = None
    if inp.preset:
        result = screener_execute(inp.preset, inp.market, 300)
        combined = list(result.get("rows") or [])
        hydration_generation = result.get("quote_generation_id")
        cursors = set()
        while result.get("available") and result.get("possibly_truncated") and result.get("next_key") and len(cursors) < 24:
            cursor = result["next_key"]
            if cursor in cursors:
                break
            cursors.add(cursor)
            result = screener_execute(inp.preset, inp.market, 300, cursor, **({"quote_generation_id":hydration_generation} if hydration_generation else {}))
            if result.get("quote_generation_id") != hydration_generation:
                raise HTTPException(409, "Quote display cohort changed during provider capture; retry from a new baseline")
            combined.extend(result.get("rows") or [])
        if not result.get("available") or result.get("possibly_truncated") or result.get("pending"):
            raise HTTPException(409, "Provider results are unavailable, incomplete or have unapplied criteria; no snapshot captured")
        if any(not r.get("stock_type") or str(r.get("stock_type")).upper() in
               ("UNKNOWN", "UNKNOW", "UNCLASSIFIED", "N/A") for r in combined):
            raise HTTPException(409, "Instrument classification is incomplete; no snapshot captured")
        filters = inp.filters
        original = result.get("filters") or []
        extra = [f for f in filters if f not in original]
        rows, missing = _apply_filters(combined, extra)
        if missing:
            raise HTTPException(409, "Additional criteria lack data; no snapshot captured")
        if inp.watchlist_only:
            wl = set(_watchlist_symbols())
            rows = [r for r in rows if r.get("symbol") in wl]
        source_at = result.get("retrieved_at")
    else:
        result = screener(market=inp.market, watchlist_only=int(inp.watchlist_only),
                          filters=json.dumps([{'field':'stock_type','values':['STOCK','ETF'] if inp.etfs else ['STOCK']}]), sort="market_cap", direction=2,
                          limit=20000, offset=0, src=inp.src, generation_id=pinned_generation)
        if (not result.get("available") or not result.get("universe_loaded")
                or result.get("skipped_filters") or result.get("unclassified_count", 0) or result.get("matched", 0) > len(result.get("rows") or [])):
            raise HTTPException(409, "Stored universe is unavailable, incomplete or lacks criterion data; no snapshot captured")
        eligible = result.get("rows") or []
        eligible = [r for r in eligible if inp.etfs or r.get('stock_type') == 'STOCK']
        eligible_codes = [r.get('code') for r in eligible]
        if any(not isinstance(c,str) or not re.fullmatch(r'(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}',c) or not c.startswith(inp.market+'.') for c in eligible_codes) or len(eligible_codes) != len(set(eligible_codes)):
            raise HTTPException(409, 'Eligible quote identities are incomplete or duplicated; no snapshot captured')
        if any(r.get('quote_identity_status') != 'verified' for r in eligible):
            raise HTTPException(409, 'Stored quote identities are unverified; no snapshot captured')
        for r in eligible:
            try:
                stamp = datetime.fromisoformat(str(r.get('quote_cache_at')).replace('Z','+00:00'))
                age = (datetime.now(timezone.utc)-stamp).total_seconds()
                if stamp.tzinfo is None or not -300 <= age <= 86400:
                    raise ValueError('invalid cache time')
            except (TypeError, ValueError):
                raise HTTPException(409, 'An eligible quote cache is stale or has no valid timestamp; no snapshot captured') from None
        try:
            observations = [capture_observation(r,inp.filters) for r in eligible]
        except ValueError:
            raise HTTPException(409, 'Stored field values conflict with criterion observations; no snapshot captured') from None
        rows = []
        for raw, observation in zip(eligible,observations):
            qualifies = True
            for slot, criterion in criterion_slots(inp.filters):
                value = observation['criterion_observations'][slot]['value']
                if value is None or (criterion.get('values') is None and not numeric(value) and not (
                    type(value) is bool and all(bound in (None,0,1) for bound in (criterion.get('min'),criterion.get('max'))))):
                    raise HTTPException(409, 'Eligible-universe criterion observations are incomplete or ambiguous; no snapshot captured')
                matches, missing = _apply_filters([{criterion.get('field'):value}],[criterion])
                qualifies = qualifies and bool(matches) and not missing
            if qualifies:
                rows.append(raw)
        source_at = result.get("universe_as_of")
    if not inp.etfs:
        rows = [r for r in rows if r.get("stock_type") == "STOCK"]
    codes = [r.get("code") for r in rows]
    if any(not c for c in codes) or len(codes) != len(set(codes)):
        raise HTTPException(409, "Result identities are incomplete or duplicated; no snapshot captured")
    if not source_at:
        raise HTTPException(409, "Source timestamp is unavailable; no comparable snapshot captured")
    try:
        source_time = datetime.fromisoformat(source_at.replace("Z", "+00:00"))
        if source_time.tzinfo is None:
            raise ValueError("timezone missing")
        source_age = (datetime.now(timezone.utc) - source_time).total_seconds()
    except (TypeError, ValueError):
        raise HTTPException(409, "Source timestamp is invalid or lacks a timezone; no snapshot captured")
    if source_age > 86400 or source_age < -300:
        raise HTTPException(409, "Source time is older than 24 hours or in the future; refresh before capturing changes")
    snapshot = {"id": str(request_id or uuid.uuid4()), "version": 3 if observations is not None else 2,
                "at": datetime.now(timezone.utc).isoformat(), "source_at": source_at,
                "source_clock": "provider_retrieval" if inp.preset else "generation_publication" if result.get("generation_id") else "stored_universe",
                "definition": inp.model_dump(),
                "members": [{"code": r["code"], "symbol": r.get("symbol"), "name": r.get("name"),
                             "metrics": {k: r.get(k) for k in ("price", "pct", "market_cap", "pe_ttm")},
                             "evidence": {f.get("field"): (r.get("criterion_values") or {}).get(f.get("field"))
                                          if inp.preset else r.get(f.get("field"))
                                          for f in inp.filters}}
                            for r in rows], "complete": True}
    if not inp.preset and result.get("generation_id"):
        snapshot["source_generation_id"] = result["generation_id"]
    if observations is not None:
        selected = {r['code'] for r in rows}
        snapshot['observations'] = observations
        snapshot['members'] = [r for r in observations if r['code'] in selected]
        snapshot['observation_scope'] = 'eligible_stored_universe'
        snapshot['eligible_count'] = len(observations)
        try:
            validate_observation_capture(snapshot,inp.model_dump())
        except (KeyError,TypeError,ValueError):
            raise HTTPException(409, 'Eligible observation contract is invalid or inconsistent; no snapshot captured') from None
    legacy = _legacy_snapshot_history(key)
    records = [{"id": _snapshot_id(s), "snapshot": s} for s in legacy] + [{"id": snapshot["id"], "snapshot": snapshot}]
    try:
        inserted = db._call("POST", "rpc/screen_capture_append", body={"p_key": key, "p_records": records})
        if type(inserted) is not int or not 0 <= inserted <= len(records):
            raise RuntimeError("Unconfirmed capture append")
    except (RuntimeError, OSError):
        existing = _snapshot_get(key, snapshot["id"])
        if existing:
            if existing.get("source_generation_id") != snapshot.get("source_generation_id"):
                raise HTTPException(409, "Capture request already belongs to a different generation")
            return _capture_reply(key, existing, True)
        raise HTTPException(503, "Capture was not confirmed. Retry with the same capture request.") from None
    return _capture_reply(key, snapshot)


def _capture_reply(key: str, snapshot: dict, idempotent: bool = False) -> dict:
    history = _snapshot_history(key)
    return {"captured": True, "id": _snapshot_id(snapshot), "members": len(snapshot['members']),
            "at": snapshot["at"], "source_generation_id": snapshot.get("source_generation_id"),
            "baseline": len(history) == 1, "idempotent": idempotent}


def _snapshot_id(snapshot: dict) -> str:
    return snapshot.get("id") or "legacy-" + hashlib.sha256(
        json.dumps(snapshot, sort_keys=True).encode()).hexdigest()[:24]


def _snapshot_meta(snapshot: dict) -> dict:
    return {"id": _snapshot_id(snapshot), "at": snapshot.get("at"),
            "source_at": snapshot.get("source_at"), "source_clock": snapshot.get("source_clock", "unverified"),
            "complete": bool(snapshot.get("complete")), "members": len(snapshot.get("members") or []),
            "version": snapshot.get("version", 1)}


@app.get("/api/screener/snapshot-history")
def screen_snapshot_history(definition: str, limit: int = 100, offset: int = 0):
    try:
        inp = ScreenDefinition.model_validate_json(definition)
    except ValueError:
        raise HTTPException(400, "Invalid screen definition")
    metadata, more = _snapshot_metadata_page(_snapshot_key(inp), limit, offset)
    return {"snapshots": metadata, "has_more": more, "offset": offset, "limit": limit,
            "retained_limit": None, "scope": "deployment_owner"}


def _change_evidence(before: dict | None, after: dict | None, inp: ScreenDefinition) -> list[dict]:
    evidence = []
    for criterion in inp.filters:
        field = criterion.get("field")
        unique = sum(c.get('field') == field for c in inp.filters) == 1
        prior = (before or {}).get("evidence", {}).get(field) if unique else None
        current = (after or {}).get("evidence", {}).get(field) if unique else None
        period = (str(criterion["days"]) + "-day window requested; actual observation window unverified") if criterion.get("days") else (
            "TTM definition; reported period not supplied" if field == "pe_ttm" else "Annual basis requested; reported period not supplied" if inp.preset and
            field in ("revenue_growth", "net_profit_growth", "roe", "roe_yoy", "debt_ratio", "eps_growth") else "Period not supplied")
        evidence.append({"field": field, "previous": prior, "current": current,
                         "criterion": criterion, "period": period,
                         "source": "provider criterion" if inp.preset else "stored screener field",
                         "status": "paired" if prior is not None and current is not None else "unavailable_pair"})
    return evidence


@app.get("/api/screener/changes")
def screen_changes(definition: str, previous_id: str | None = None, current_id: str | None = None,
                   status: str = "all", q: str = "", sort: str = "symbol", direction: int = 1,
                   limit: int = 100, offset: int = 0, history_offset: int = 0):
    if status not in ("new", "exited", "all"):
        raise HTTPException(400, "Invalid review filter or sort")
    if direction not in (1, 2) or not 1 <= limit <= 500 or not 0 <= offset <= 40000 or len(q) > 100:
        raise HTTPException(400, "Invalid review pagination")
    try:
        inp = ScreenDefinition.model_validate_json(definition)
    except ValueError:
        raise HTTPException(400, "Invalid screen definition")
    key = _snapshot_key(inp)
    inp = _capture_criteria(inp)
    criterion_sort = re.fullmatch(r"criterion:(before|after):([a-z][a-z0-9_]{0,63})", sort)
    numeric_criteria = {key:c for key,c in criterion_slots(inp.filters)
                        if c.get('values') is None and (c.get('min') is not None or c.get('max') is not None)}
    numeric_criteria.update({c['field']:c for c in list(numeric_criteria.values()) if sum(f.get('field')==c['field'] for f in inp.filters)==1})
    if sort not in ("symbol", "name", "status", "market_cap") and (
            not criterion_sort or criterion_sort.group(2) not in numeric_criteria):
        raise HTTPException(400, "Choose a captured numeric criterion to sort")
    history = _snapshot_history(key)
    metadata, history_more = _snapshot_metadata_page(key, 100, history_offset)
    # Preserve injected/offline and unimported legacy history metadata.
    if not metadata and history_offset == 0:
        metadata = [_snapshot_meta(s) for s in history]
    history_meta = {"history": metadata, "history_has_more": history_more, "history_offset": history_offset,
                    "history_limit": 100, "retained_limit": None, "scope": "deployment_owner"}
    if len(history) < 2:
        return {"comparable": False, **history_meta, "reason":
                "Baseline captured. Capture another complete snapshot to compare." if history else
                "No baseline yet. Capture a complete snapshot to start."}
    by_id = {_snapshot_id(s): s for s in history}
    previous = (by_id.get(previous_id) or _snapshot_get(key, previous_id)) if previous_id else history[-2]
    current = (by_id.get(current_id) or _snapshot_get(key, current_id)) if current_id else history[-1]
    if previous and current:
        known = {m['id'] for m in metadata}
        metadata.extend(_snapshot_meta(s) for s in (previous, current) if _snapshot_id(s) not in known)
        metadata.sort(key=lambda s: (s.get('at') or '', s['id']))
    if not previous or not current:
        raise HTTPException(404, "Snapshot pair not retained for this screen")
    try:
        times = [datetime.fromisoformat(s["at"].replace("Z", "+00:00")) for s in (previous, current)]
        if any(t.tzinfo is None for t in times):
            raise ValueError("timezone missing")
    except (KeyError, TypeError, ValueError):
        return {"comparable": False, **history_meta, "reason": "Snapshot capture times are invalid; no changes inferred."}
    if _snapshot_id(previous) == _snapshot_id(current) or times[0] >= times[1]:
        raise HTTPException(400, "Choose distinct snapshots in chronological order")
    if not previous.get("complete") or not current.get("complete"):
        return {"comparable": False, **history_meta, "reason": "Incomplete snapshots cannot establish entries or exits."}
    if previous.get("version", 1) != current.get("version", 1):
        return {"comparable": False, **history_meta, "reason": "Snapshot evidence contract changed. Capture another matching baseline."}
    for snapshot in (previous, current):
        members = snapshot.get("members")
        if not isinstance(members, list) or any(not isinstance(r, dict) or not isinstance(r.get("code"), str) or not r.get("code") for r in members):
            return {"comparable": False, **history_meta, "reason": "Snapshot identities are incomplete; no changes inferred."}
        if len({r["code"] for r in members}) != len(members):
            return {"comparable": False, **history_meta, "reason": "Snapshot identities are duplicated; no changes inferred."}
    a = {r["code"]: r for r in previous["members"]}
    b = {r["code"]: r for r in current["members"]}
    observed = []
    if previous.get('version') == 3:
        for snapshot in (previous,current):
            try:
                lookup = validate_observation_capture(snapshot,inp.model_dump())
            except (KeyError,TypeError,ValueError):
                return {'comparable':False, **history_meta, 'reason':'Eligible observation contract is invalid or inconsistent; no changes inferred.'}
            if any(lookup.get(r['code']) != r for r in snapshot['members']):
                return {'comparable':False, **history_meta, 'reason':'Member evidence differs from captured universe observations; no changes inferred.'}
            qualifying = set()
            for code,record in lookup.items():
                if all(_apply_filters([{c['field']:record['criterion_observations'][slot]['value']}],[c])[0]
                       for slot,c in criterion_slots(inp.filters)):
                    qualifying.add(code)
            if qualifying != {r['code'] for r in snapshot['members']}:
                return {'comparable':False, **history_meta, 'reason':'Captured membership disagrees with criterion observations; no changes inferred.'}
            observed.append(lookup)
    changes = []
    for code in sorted(a.keys() | b.keys()):
        member_status = "new" if code not in a else "exited" if code not in b else "unchanged"
        before, after = (observed[0].get(code),observed[1].get(code)) if observed else (a.get(code),b.get(code))
        member = b.get(code) or a.get(code)
        changes.append({"code": code, "symbol": member.get("symbol"), "name": member.get("name"),
                        "status": member_status, "previous": before, "current": after,
                        "reason": "Membership retained" if member_status == "unchanged" else
                        "Membership changed; numeric cause unavailable"})
    counts = {"new": len(b.keys() - a.keys()), "exited": len(a.keys() - b.keys()), "all": len(a.keys() | b.keys()), "unchanged": len(a.keys() & b.keys())}
    needle = q.strip().casefold()
    filtered = [r for r in changes if (status == "all" or r["status"] == status) and
                (not needle or needle in str(r.get("symbol") or "").casefold() or needle in str(r.get("name") or "").casefold())]
    def sort_value(row):
        if criterion_sort:
            side, identifier = criterion_sort.groups()
            criterion = numeric_criteria[identifier]
            field = criterion['field']
            observation = row.get("previous" if side == "before" else "current") or {}
            key = identifier if identifier.startswith('c') and identifier in dict(criterion_slots(inp.filters)) else next(key for key,c in criterion_slots(inp.filters) if c == criterion)
            value = (observation.get('criterion_observations',{}).get(key) or {}).get('value') if observed else (
                (observation.get('evidence') or {}).get(field) if sum(c.get('field')==field for c in inp.filters)==1 else None)
            return float(value) if type(value) in (int, float) and math.isfinite(value) else None
        if sort == "market_cap":
            value = ((row.get("current") or row.get("previous") or {}).get("metrics") or {}).get("market_cap")
            return float(value) if type(value) in (int, float) and math.isfinite(value) else None
        return str(row.get(sort) or "").casefold()
    known = [r for r in filtered if sort_value(r) is not None]
    missing = [r for r in filtered if sort_value(r) is None]
    known.sort(key=lambda r: (sort_value(r), r["code"]), reverse=direction == 2)
    selected = (known + missing)[offset:offset + limit]
    for row in selected:
        row["evidence"] = paired_evidence(row['previous'],row['current'],inp.filters,times) if observed else _change_evidence(row["previous"], row["current"], inp)
        if row['status'] != 'unchanged' and any(e.get('status') == 'comparable' for e in row['evidence']):
            row['reason'] = 'Membership changed; comparable captured rule results are available. This does not establish a sole cause.'
    return {"comparable": True, **history_meta,
            'observation_coverage':{'previous':len(observed[0]),'current':len(observed[1]),'scope':'eligible_stored_universe'} if observed else {'scope':'legacy_member_only'},
            "previous_id": _snapshot_id(previous), "current_id": _snapshot_id(current),
            "previous_at": previous["at"], "current_at": current["at"],
            "previous_source_at": previous.get("source_at"), "current_source_at": current.get("source_at"),
            "previous_generation_id": previous.get("source_generation_id"), "current_generation_id": current.get("source_generation_id"),
            "previous_source_clock": previous.get("source_clock", "unverified"), "current_source_clock": current.get("source_clock", "unverified"),
            "rows": selected, "counts": counts, "matched": len(filtered), "offset": offset, "limit": limit,
            "definition": inp.model_dump(), "added": [b[k] for k in sorted(b.keys() - a.keys())],
            "exited": [a[k] for k in sorted(a.keys() - b.keys())], "unchanged": len(a.keys() & b.keys())}


# ── model catalog + settings ─────────────────────────────────────────────
from tradingagents_worker.openrouter import CATALOG  # noqa: E402
from tradingagents_worker.settings import (  # noqa: E402
    get_model_pair, save_model_pair, get_runtime_flags, save_runtime_flags)


@app.get("/api/models")
def models(refresh: int = 0):
    """OpenRouter catalog, sorted recommended-first, cost-annotated.

    Cached 1h server-side; ?refresh=1 forces a re-fetch. Falls back to the last
    good copy (flagged stale) if OpenRouter is unreachable.
    """
    data, err = CATALOG.try_get(force=bool(refresh))
    if data is None:
        raise HTTPException(502, f"OpenRouter catalog unavailable: {err}")
    return {**data, "active": get_model_pair(db)}


class ModelPairIn(BaseModel):
    provider: str = Field(default="openrouter", min_length=2, max_length=32)
    quick: str = Field(min_length=2, max_length=120)
    deep: str = Field(min_length=2, max_length=120)


class SettingsIn(BaseModel):
    provider: str = Field(default="openrouter", min_length=2, max_length=32)
    quick: str = Field(min_length=2, max_length=120)
    deep: str = Field(min_length=2, max_length=120)
    stub: bool | None = None


@app.get("/api/settings")
def get_settings():
    return {"models": get_model_pair(db), "runtime": get_runtime_flags(db)}


@app.put("/api/settings")
def put_settings(inp: SettingsIn):
    if not SETTINGS.supabase_url:
        raise HTTPException(503, "SUPABASE_URL not configured")
    saved = save_model_pair(db, inp.provider, inp.quick, inp.deep)
    runtime = None
    if inp.stub is not None:
        runtime = save_runtime_flags(db, inp.stub)
    return {"saved": True, "models": saved, "runtime": runtime}


# ── agent prompt store (Settings → Agent prompts; versions + active choice) ──
# The engine resolves saved versions per run (tradingagents.agents.prompts);
# version 1 rows are seeded by the worker with the engine's stock text, so
# this API stays DB-only (no engine import — the API image doesn't ship it).

PROMPT_AGENTS = [
    {"key": "market_analyst", "label": "Market / Technical Analyst", "model": "quick"},
    {"key": "sentiment_analyst", "label": "Sentiment Analyst", "model": "quick"},
    {"key": "news_analyst", "label": "News & Macro Analyst", "model": "quick"},
    {"key": "fundamentals_analyst", "label": "Fundamentals Analyst", "model": "quick"},
    {"key": "bull_researcher", "label": "Bull Researcher", "model": "quick"},
    {"key": "bear_researcher", "label": "Bear Researcher", "model": "quick"},
    {"key": "research_manager", "label": "Research Manager", "model": "deep"},
    {"key": "trader", "label": "Trader", "model": "quick"},
    {"key": "aggressive_analyst", "label": "Aggressive Risk Analyst", "model": "quick"},
    {"key": "neutral_analyst", "label": "Neutral Risk Analyst", "model": "quick"},
    {"key": "conservative_analyst", "label": "Conservative Risk Analyst", "model": "quick"},
    {"key": "portfolio_manager", "label": "Portfolio Manager", "model": "deep"},
]


def _prompt_selection() -> dict:
    rows = db.select("app_settings", {"key": "eq.prompts"}, "value")
    return (rows[0].get("value") or {}) if rows else {}


def _prompt_agents_payload(with_content: bool):
    sel = _prompt_selection()
    try:
        versions = db.select_all("prompt_versions", {}, "agent_key,version,note,created_at,content")
    except Exception:
        return {"agents": []}  # migration 0009 not applied yet
    by_agent: dict[str, list] = {}
    for v in versions:
        by_agent.setdefault(v["agent_key"], []).append(v)
    agents = []
    for meta in PROMPT_AGENTS:
        key = meta["key"]
        rows = sorted(by_agent.get(key, []), key=lambda v: v["version"])
        active_version = sel.get(key)
        active = next((v for v in rows if v["version"] == active_version), None)
        stock = next((v for v in rows if v["note"] == "engine stock prompt"), None)
        entry = {**meta, "active_version": active_version,
                 "versions": [{k: v.get(k) for k in ("version", "note", "created_at", "content")}
                              for v in rows]}
        if with_content:
            entry["active_content"] = (active or stock or {}).get("content")
            entry["default_content"] = (stock or {}).get("content")
        else:
            for v in entry["versions"]:
                v.pop("content", None)
        agents.append(entry)
    return {"agents": agents}


@app.get("/api/prompts")
def prompts_index():
    return _prompt_agents_payload(with_content=True)


class PromptVersionIn(BaseModel):
    content: str = Field(min_length=1, max_length=40000)
    note: str | None = Field(default=None, max_length=200)


def _prompt_agent_key(key: str) -> str:
    if key not in {a["key"] for a in PROMPT_AGENTS}:
        raise HTTPException(404, "unknown agent")
    return key


@app.post("/api/prompts/{key}/versions")
def prompt_save_version(key: str, inp: PromptVersionIn):
    """Save the editor text as the next version and make it active — applies
    to runs queued after this save."""
    _prompt_agent_key(key)
    try:
        existing = db.select("prompt_versions", {"agent_key": f"eq.{key}"}, "version")
    except Exception:
        raise HTTPException(503, "prompt_versions table missing — run migration 0009")
    next_version = max((int(v["version"]) for v in existing), default=0) + 1
    db.insert("prompt_versions", {"agent_key": key, "version": next_version,
                                  "content": inp.content, "note": inp.note},
              prefer="return=minimal")
    sel = _prompt_selection()
    sel[key] = next_version
    db.upsert("app_settings", "key", {"key": "prompts", "value": sel})
    return {"saved": True, "agent_key": key, "version": next_version}


class PromptActiveIn(BaseModel):
    version: int | None = None  # null = back to the engine stock prompt


@app.put("/api/prompts/{key}/active")
def prompt_activate(key: str, inp: PromptActiveIn):
    _prompt_agent_key(key)
    sel = _prompt_selection()
    if inp.version is None:
        sel.pop(key, None)
    else:
        rows = db.select("prompt_versions", {"agent_key": f"eq.{key}",
                                             "version": f"eq.{inp.version}"}, "version")
        if not rows:
            raise HTTPException(404, "version not found")
        sel[key] = inp.version
    db.upsert("app_settings", "key", {"key": "prompts", "value": sel})
    return {"saved": True, "agent_key": key, "active_version": sel.get(key)}


@app.post("/api/candidates/refresh")
def candidates_refresh():
    """Run a discovery sweep now (Market Pulse refresh button).

    Uses moomoo screens/news/calendar when keys are configured; watchlist
    candidates always available. Bounded: a few vendor calls, seconds.
    """
    if not SETTINGS.supabase_url:
        raise HTTPException(503, "SUPABASE_URL not configured")
    from tradingagents_worker.discovery import sweep  # noqa: E402
    from tradingagents_worker.moomoo import Budget, MoomooClient  # noqa: E402
    from tradingagents_worker.ttl_cache import TtlCache  # noqa: E402
    mm = None
    if SETTINGS.moomoo_appkey and SETTINGS.moomoo_private_key:
        try:
            mm = MoomooClient(SETTINGS.moomoo_appkey, SETTINGS.moomoo_private_key,
                              Budget(limit=30))
        except Exception:
            mm = None  # never surface key material
    cache = TtlCache(root=os.path.join(tempfile.gettempdir(), "ta-ttl"))
    rows = sweep(db, mm, cache, watchlist=["NVDA", "MSFT", "0700.HK", "CSL.AX"])
    return {"refreshed": True, "moomoo": mm is not None, "candidates_stored": len(rows)}


# ── Stock detail page (moomoo per-symbol surface; read-only; fixtures mode) ──
# Every route: TA_STOCK_FIXTURES=1 → recorded payload (stock_fixtures.py); else
# TTL-cached live moomoo; no keys → {"available": false}. Element→endpoint map:
# web/STOCK_PAGE_FEASIBILITY.md §2.

from fastapi.responses import FileResponse  # noqa: E402

# ktype enum (verified): 1=1min 2=Day 3=Week 4=Month 5=Year 6=5min 7=15min
# 8=30min 9=60min. The old set had Daily and 1Y both at ktype 2/~380d —
# identical data, so switching horizons "did nothing". Each horizon now maps
# to distinct data; 1d/15m added for the Compare page's intraday timeframes.
_KLINE_WINDOWS = {"1d": ("candles:1d", 1, 2), "5D": ("candles:5D", 6, 10),
                  "15m": ("candles:15m", 7, 30),
                  "1M": ("candles:1M", 8, 45),
                  "3M": ("candles:3M", 9, 120), "Q": ("candles:Q", 2, 105),
                  "6M": ("candles:6M", 2, 190), "Y": ("candles:Y", 2, 380),
                  "W": ("candles:W", 3, 3400), "M": ("candles:M", 4, 4200),
                  "10Y": ("candles:10Y", 5, 4200)}
_SESSION_KINDS = {"FULL", "NORMAL", "PREMARKET", "AFTERHOURS"}
_NEWS_TYPES = {"news": 1, "notice": 2, "report": 3}


def _stock_code(symbol: str) -> str:
    s = symbol.strip().upper()
    if s.endswith("-US"):
        s = s[:-3]
    return s if re.match(r"^(US|HK|SH|SZ|AU)\.", s) else f"US.{s}"


def _stock_fetch(key: str, symbol: str, category: str, fetch):
    """Fixture payload, or the TTL-cached result of fetch(client); None w/o keys.
    Upstream errors become {"available": false, "reason"} instead of HTTP 500 —
    one flaky endpoint must never take the whole stock tab down."""
    if os.getenv("TA_STOCK_FIXTURES"):
        from tradingagents_api import stock_fixtures
        data = stock_fixtures.payload(key, symbol)
        if data is None:
            raise HTTPException(404, f"no fixture for {key}")
        return data
    client = _market_client()
    if client is None:
        return None
    cache = _cache()
    ck = cache.key(category, "stock-page", key, symbol.upper())
    hit = cache.get(category, ck)
    if hit is not None:
        return hit
    try:
        out = fetch(client)
    except Exception as e:  # noqa: BLE001 — surface, don't crash the section
        return {"available": False, "reason": f"moomoo error: {str(e)[:140]}"}
    cache.put(category, ck, out)
    return out


def _is_unavailable(out) -> bool:
    return isinstance(out, dict) and out.get("available") is False


def _stock_out(data) -> dict:
    return data if data is not None else {
        "available": False, "reason": "moomoo keys not configured"}


@app.get("/api/stock/quotes")
def stock_quotes(symbols: str):
    """Batched header quotes for the Compare page — ONE snapshot call covers
    every panel symbol (snapshot accepts up to 400 codes)."""
    syms = [s.strip().upper() for s in symbols.split(",") if s.strip()][:12]
    if not syms:
        raise HTTPException(400, "symbols required")
    if os.getenv("TA_STOCK_FIXTURES"):
        from tradingagents_api import stock_fixtures
        return {"available": True, "quotes": stock_fixtures.quotes_batch(syms)}
    client = _market_client()
    if client is None:
        return {"available": False, "reason": "moomoo keys not configured"}
    try:
        snap = (client.snapshot([_stock_code(s) for s in syms]) or {}).get("snapshot_list") or []
    except Exception as e:  # noqa: BLE001 — headers degrade, the page must not
        return {"available": False, "reason": f"moomoo error: {str(e)[:140]}"}
    by_code = {}
    for item in snap:
        if isinstance(item, dict) and item.get("code"):
            by_code[str(item["code"]).split(".")[-1].upper()] = item
    return {"available": True, "quotes": {s: by_code.get(s) for s in syms}}


@app.get("/api/stock/{symbol}/quote")
def stock_quote(symbol: str):
    code = _stock_code(symbol)

    def fetch(c):
        return ((c.snapshot([code]) or {}).get("snapshot_list") or [None])[0]

    item = _stock_fetch("quote", symbol, "quotes", fetch)
    out = _stock_out(item)
    if isinstance(out, dict):
        out.setdefault("available", True)
    return out


@app.get("/api/stock/{symbol}/candles")
def stock_candles(symbol: str, range: str = "5D", ext: int = 0):
    if range not in _KLINE_WINDOWS:
        raise HTTPException(400, "range must be one of " + ",".join(_KLINE_WINDOWS))
    key, ktype, days = _KLINE_WINDOWS[range]
    start = (date.today() - timedelta(days=days)).isoformat()

    def fetch(c):
        # extended_time (pre/after) only takes effect for US 1-min bars (ktype 1).
        return {"kline_list": c.history_kline(
            _stock_code(symbol), start, date.today().isoformat(), ktype=ktype,
            extended_time=(ext or None) if ktype == 1 else None)}

    out = _stock_fetch(key, symbol, "ohlcv", fetch)
    if isinstance(out, dict) and "kline_list" in out:
        out = {"available": True, "range": range, "bars": out["kline_list"]}
    return _stock_out(out)


@app.get("/api/stock/{symbol}/intraday")
def stock_intraday(symbol: str, kind: str = "FULL"):
    if kind not in _SESSION_KINDS:
        raise HTTPException(400, "kind must be one of " + ",".join(_SESSION_KINDS))
    out = _stock_fetch("intraday", symbol, "quotes",
                       lambda c: c.rt_data(_stock_code(symbol), kind=kind))
    if isinstance(out, dict):
        out.setdefault("available", True)
    return _stock_out(out)


@app.get("/api/stock/{symbol}/capital")
def stock_capital(symbol: str, period: str = "intraday"):
    if period not in ("intraday", "day", "week", "month"):
        raise HTTPException(400, "period must be intraday|day|week|month")
    code = _stock_code(symbol)

    def flow(c):
        if period == "intraday":
            return c.capital_flow(code)
        return c.capital_flow_history(code, period=period)

    fl = _stock_fetch(f"capital:{period}", symbol, "quotes", flow)
    dist = _stock_fetch("distribution", symbol, "quotes", lambda c: c.capital_distribution(code))
    for part in (fl, dist):
        if part is None:
            return _stock_out(None)
        if _is_unavailable(part):
            return part
    out = {"available": True, "flow": (fl or {}).get("flow_list") or [],
           "distribution": dist or {}}
    return out


@app.get("/api/stock/{symbol}/options")
def stock_options(symbol: str, expiry: str = "auto"):
    code = _stock_code(symbol)
    exps = _stock_fetch("expirations", symbol, "quotes",
                        lambda c: c.option_expirations(code)) or {}
    if _is_unavailable(exps):
        return exps
    # Live container is expiration_list (verified POC); keep the docs' alias.
    dates = exps.get("expiration_list") or exps.get("expire_date_list") or []
    exp = expiry if expiry != "auto" else (dates[0].get("strike_time") if dates else None)
    if not exp:
        return {"available": True, "expirations": dates, "expiry": None,
                "chain": [], "quotes": {}}
    chain = _stock_fetch("chain", symbol, "quotes",
                         lambda c: c.option_chain(code, start=exp, end=exp)) or {}
    if _is_unavailable(chain):
        return chain
    rows = chain.get("option_chain") or []
    codes = [r.get("code") for r in rows if r.get("code")][:80]
    quotes = {}
    if codes:
        snap = _stock_fetch("chain-quotes", symbol, "quotes",
                            lambda c: c.snapshot(codes)) or {}
        if not _is_unavailable(snap):
            quotes = {s.get("code"): s for s in snap.get("snapshot_list") or []
                      if isinstance(s, dict)}
    return {"available": True, "expirations": dates, "expiry": exp,
            "chain": rows, "quotes": quotes}


@app.get("/api/stock/{symbol}/financials/statements")
def stock_statements(symbol: str, statement_type: int = 1, financial_type: int = 0):
    """financial_type: 0 = server default (quarterly mix), 7 = annual; live enum is
    1..7/9 (the docs' '102' value is rejected — handbook inaccuracy)."""
    if statement_type not in (1, 2, 3, 4) or financial_type not in (0, 1, 2, 3, 4, 5, 6, 7, 9):
        raise HTTPException(400, "statement_type 1-4; financial_type 0|1..7|9")
    key = f"statements:{statement_type}:{financial_type}"
    out = _stock_fetch(key, symbol, "fundamentals",
                       lambda c: c.statements(_stock_code(symbol), statement_type,
                                              financial_type or None, limit=12))
    if out is None:
        return _stock_out(None)
    if _is_unavailable(out):
        return out
    if isinstance(out, dict):  # live container is report_list (paginated)
        out = out.get("report_list") or []
    return {"available": True, "periods": out}


# Moomoo returns revenue segment names provider-localized — Chinese even for US
# filers (e.g. MSFT's segments arrive as 智能云). The revenue-breakdown endpoint
# has no language parameter (unlike find-news's lang=en), so known names are
# mapped to English here; anything unmapped passes through untouched.
_ZH_SEGMENT_EN = {
    # countries / regions
    "美国": "United States", "中国": "China", "中国大陆": "Mainland China",
    "其他国家": "Other Countries", "其他国家/地区": "Other Countries/Regions",
    "其他地区": "Other Regions", "海外": "Overseas", "国际": "International",
    "国内": "Domestic", "中国香港": "Hong Kong", "中国台湾": "Taiwan",
    "中国澳门": "Macao", "日本": "Japan", "韩国": "South Korea", "印度": "India",
    "新加坡": "Singapore", "德国": "Germany", "英国": "United Kingdom",
    "法国": "France", "荷兰": "Netherlands", "爱尔兰": "Ireland",
    "瑞士": "Switzerland", "瑞典": "Sweden", "西班牙": "Spain", "意大利": "Italy",
    "加拿大": "Canada", "澳大利亚": "Australia", "巴西": "Brazil",
    "墨西哥": "Mexico", "亚洲": "Asia", "欧洲": "Europe", "北美洲": "North America",
    "南美洲": "South America", "中东": "Middle East", "非洲": "Africa",
    "大洋洲": "Oceania", "全球": "Global",
    # common business / product segments
    "智能云": "Intelligent Cloud", "生产力与业务流程": "Productivity and Business Processes",
    "生产力和业务流程": "Productivity and Business Processes",
    "更多个人计算": "More Personal Computing", "更加个人计算": "More Personal Computing",
    "个人计算": "Personal Computing", "服务及其他": "Services and Other",
    "服务": "Services", "产品": "Products", "硬件": "Hardware", "软件": "Software",
    "广告": "Advertising", "广告服务": "Advertising Services",
    "云服务": "Cloud Services", "电子商务": "E-commerce", "游戏": "Gaming",
    "数据中心": "Data Center", "专业可视化": "Professional Visualization",
    "汽车": "Automotive", "汽车业务": "Automotive",
    "能源生产及储存": "Energy Generation and Storage",
    "可穿戴、家居及配件": "Wearables, Home and Accessories",
    "可穿戴设备、家居及配件": "Wearables, Home and Accessories",
    "谷歌服务": "Google Services", "谷歌云": "Google Cloud", "其他赌注": "Other Bets",
    "网络服务": "Web Services", "金融科技": "Fintech", "数字内容": "Digital Content",
    "流媒体": "Streaming", "其他": "Others", "其他业务": "Other Businesses",
    "未分配": "Unallocated", "抵销": "Eliminations",
    "公司间抵销": "Intersegment Eliminations", "总计": "Total", "合计": "Total",
}


def _en_segment_name(name):
    """zh segment names → English where mapped; pass through otherwise."""
    if not isinstance(name, str) or not name:
        return name
    n = name.strip()
    if not any("\u4e00" <= ch <= "\u9fff" for ch in n):
        return name
    return _ZH_SEGMENT_EN.get(n, name)


@app.get("/api/stock/{symbol}/financials/revenue")
def stock_revenue(symbol: str, date: int | None = None, financial_type: int | None = None):
    """Live shape: breakdown_list[type: 1=Product 2=Industry 4=Region 8=Business],
    screen_date_list = available periods (date s + financial_type)."""
    key = f"revenue:{date}:{financial_type}" if (date or financial_type) else "revenue"
    out = _stock_fetch(key, symbol, "fundamentals",
                       lambda c: c.revenue_breakdown(_stock_code(symbol),
                                                     date=date, financial_type=financial_type))
    if out is None:
        return _stock_out(None)
    if _is_unavailable(out):
        return out
    if isinstance(out, dict):
        for br in out.get("breakdown_list") or []:
            if isinstance(br, dict):
                for it in br.get("item_list") or []:
                    if isinstance(it, dict) and "name" in it:
                        it["name"] = _en_segment_name(it["name"])
    out.setdefault("available", True)
    return out


@app.get("/api/stock/{symbol}/earnings")
def stock_earnings(symbol: str):
    out = _stock_fetch("earnings-history", symbol, "fundamentals",
                       lambda c: c.earnings_price_history(_stock_code(symbol)))
    if out is None:
        return _stock_out(None)
    if _is_unavailable(out):
        return out
    if isinstance(out, dict):  # live container is `records` (verified POC)
        out = {"list": out.get("records") or out.get("list") or []}
    if isinstance(out, dict):
        out.setdefault("available", True)
    return out


@app.get("/api/stock/{symbol}/dividends")
def stock_dividends(symbol: str):
    """Dividend history for E/D chart markers. The live container key is
    undocumented (HB §9.12: docs table lists only totals; verified rows carry
    ex_date/dividend_per_share/currency) — accept the common shapes."""
    out = _stock_fetch("dividends", symbol, "fundamentals",
                       lambda c: c.dividends(_stock_code(symbol)))
    if out is None:
        return _stock_out(None)
    if _is_unavailable(out):
        return out
    if isinstance(out, list):
        rows = out
    elif isinstance(out, dict):
        rows = (out.get("list") or out.get("dividend_list") or out.get("records"))
        if rows is None:  # unknown container key: first list-shaped value
            rows = next((v for v in out.values() if isinstance(v, list)), [])
    else:
        rows = []
    # Live wire format is "2026/08/10" — normalize to ISO so chart event
    # markers can match bars by date string.
    for r in rows:
        if isinstance(r, dict) and r.get("ex_date"):
            r["ex_date"] = str(r["ex_date"]).replace("/", "-")
    return {"available": True, "list": rows}


@app.get("/api/stock/{symbol}/research")
def stock_research(symbol: str):
    code = _stock_code(symbol)

    def fetch(c):
        return {"consensus": c.analyst_consensus(code) or {},
                "detail": c.rating_summary(code) or {}}

    out = _stock_fetch("research", symbol, "other", fetch)
    if isinstance(out, dict):
        out.setdefault("available", True)
    return _stock_out(out)


@app.get("/api/stock/{symbol}/news")
def stock_news(symbol: str, type: str = "news", limit: int = 20):
    if type not in _NEWS_TYPES:
        raise HTTPException(400, "type must be news|notice|report")
    kw = _stock_code(symbol).split(".")[-1]
    out = _stock_fetch(f"news:{_NEWS_TYPES[type]}", symbol, "news",
                       lambda c: {"news_list": c.find_news(kw, news_type=_NEWS_TYPES[type],
                                                           limit=limit, lang="en")})
    if isinstance(out, dict):
        out.setdefault("available", True)
    return _stock_out(out)


@app.get("/api/stock/{symbol}/company")
def stock_company(symbol: str):
    code = _stock_code(symbol)

    def fetch(c):
        return {"profile": c.company_profile(code) or {},
                "executives": (c.company_executives(code) or {}).get("executives") or []}

    out = _stock_fetch("company", symbol, "fundamentals", fetch)
    if isinstance(out, dict):
        out.setdefault("available", True)
    return _stock_out(out)


@app.get("/api/stock/{symbol}/community")
def stock_community(symbol: str):
    kw = _stock_code(symbol).split(".")[-1]
    out = _stock_fetch("community", symbol, "other",
                       lambda c: {"community_list": c.find_community(kw, lang="en")})
    if isinstance(out, dict):
        out.setdefault("available", True)
    return _stock_out(out)


# ── symbol directory for the Quotes picker / ticker switcher ─────────

@app.get("/api/sectors")
def sectors(market: str = "US", plate_class: str = "INDUSTRY"):
    """Sector (plate) list for the picker dropdown. Weekly-fresh data, cached."""
    out = _stock_fetch(f"plates:{market}:{plate_class}", market, "other",
                       lambda c: c.plate_list(market.upper(), plate_class))
    if out is None:
        return _stock_out(None)
    if _is_unavailable(out):
        return out
    return {"available": True, "sectors": out}


@app.get("/api/sectors/stocks")
def sector_stocks(plate: str, limit: int = 60):
    """Members of a sector, market-cap desc, snapshot-enriched (price/pct)."""
    code = plate.strip().upper()

    def fetch(c):
        members = c.plate_stocks(code, limit=min(limit, 100))
        codes = [m.get("code") for m in members if m.get("code")]
        snap = (c.snapshot(codes) or {}).get("snapshot_list") or [] if codes else []
        by = {s.get("code"): s for s in snap if isinstance(s, dict)}
        rows = []
        for m in members:
            s = by.get(m.get("code")) or {}
            last, prev = s.get("last_price"), s.get("prev_close_price")
            pct = s.get("pct_change")
            if pct is None and last is not None and prev:
                pct = (float(last) - float(prev)) / float(prev) * 100
            rows.append({"symbol": (m.get("code") or "").split(".")[-1],
                         "name": m.get("name") or s.get("name") or "",
                         "price": last, "pct": None if pct is None else round(float(pct), 2),
                         "market_cap": s.get("total_market_val")})
        return rows

    out = _stock_fetch(f"plate-stocks:{code}", plate, "quotes", fetch)
    if out is None:
        return _stock_out(None)
    if _is_unavailable(out):
        return out
    return {"available": True, "rows": out}


def _estimates_fetch(symbol: str) -> dict:
    """Street estimates — S&P Global Market Intelligence via Yahoo (yfinance).

    Lazy import: yfinance is an optional runtime dep; failure → available=false.
    """
    import math

    import yfinance as yf
    t = yf.Ticker(symbol)

    def clean(o):
        if isinstance(o, dict):
            return {k: clean(v) for k, v in o.items()}
        if isinstance(o, list):
            return [clean(v) for v in o]
        if isinstance(o, float) and not math.isfinite(o):
            return None
        if isinstance(o, (date, datetime)):
            return o.isoformat()
        return o

    def rows(df):
        recs = df.reset_index().to_dict("records")
        return [{k: (None if v != v else clean(v)) for k, v in r.items()} for r in recs]

    hist = t.earnings_history
    hist_recs = []
    for r in rows(hist) if hist is not None else []:
        q = r.get("quarter") or r.get("index")
        hist_recs.append({"quarter": str(q)[:10] if q else None,
                          "eps_estimate": r.get("epsEstimate"), "eps_actual": r.get("epsActual"),
                          "surprise_pct": (round(r["surprisePercent"] * 100, 2)
                                           if isinstance(r.get("surprisePercent"), (int, float))
                                           and abs(r["surprisePercent"]) < 1
                                           else r.get("surprisePercent"))})
    cal = clean(t.calendar) or {}
    return {"symbol": symbol.upper(),
            "revenue_estimate": rows(t.revenue_estimate),
            "earnings_estimate": rows(t.earnings_estimate),
            "eps_trend": rows(t.eps_trend),
            "earnings_history": hist_recs,
            "calendar": cal}


@app.get("/api/stock/{symbol}/estimates")
def stock_estimates(symbol: str):
    if os.getenv("TA_STOCK_FIXTURES"):
        from tradingagents_api import stock_fixtures
        return stock_fixtures.estimates(symbol)
    cache = _cache()
    ck = cache.key("other", "stock-estimates", symbol.upper())
    hit = cache.get("other", ck)
    if hit is not None:
        return hit
    try:
        out = _estimates_fetch(symbol)
    except Exception as e:
        return {"available": False, "reason": f"estimates unavailable: {str(e)[:120]}"}
    # Yahoo sometimes returns empty frames (egress rate-limited) without raising —
    # report that as unavailable rather than a page of blank tables.
    if not (out.get("revenue_estimate") or out.get("earnings_estimate")
            or out.get("earnings_history")):
        return {"available": False,
                "reason": "estimates provider returned no data (Yahoo egress may be "
                          "rate-limited from this host); retry later"}
    out["available"] = True
    cache.put("other", ck, out)
    return out


def _portal_index() -> str | None:
    d = os.getenv("PORTAL_STATIC_DIR", "")
    p = os.path.join(d, "index.html") if d else ""
    return p if p and os.path.isfile(p) else None


_GROUPS_AVG_FIELDS = ["pe_ttm", "pb", "div_yield", "forward_pe", "peg",
                      "short_float", "analyst_recom"]
_CAP_BUCKETS = [("mega (≥200B)", 2e11), ("large (≥10B)", 1e10), ("mid (≥2B)", 2e9),
                ("small (≥300M)", 3e8), ("micro (<300M)", 0.0)]


def _cap_bucket(cap):
    for name, floor in _CAP_BUCKETS:
        if (cap or 0) >= floor:
            return name
    return "micro (<300M)"


def _group_cap_currency(row):
    value = row.get('market_cap')
    return field_currency(row,'market_cap') if numeric(value) and value>0 else None


def _group_sum(values):
    """Finite inputs can overflow as an aggregate; never serialize Infinity."""
    if not values:return None
    try:
        result = math.fsum(values)
    except (OverflowError,ValueError):
        return None
    return round(result,4) if math.isfinite(result) else None


def _group_mean(values):
    # Divide before summing so a representable mean survives a sum overflow.
    return _group_sum([v/len(values) for v in values]) if values else None


@app.get("/api/groups")
def groups(market: str = "US", group_by: str = "plate", order_by: str = "stocks",
           direction: int = 2, stock_type: str = "STOCK", cap_currency: str | None = None):
    """Coverage-labelled aggregates of one stored quote cohort; no vendor calls.

    Supplemental classification/factors use the screener's category freshness
    contract. No classification fallback or cross-currency capitalization sum.
    """
    if market not in ('US','HK') or group_by not in ('plate','sector','industry','exchange','cap_bucket'):
        raise HTTPException(400,'Invalid market or group classification')
    if direction not in (1,2) or stock_type not in ('STOCK','ETF','') or order_by not in ('name','stocks','cap_sum','chg_avg','vol_sum',*_GROUPS_AVG_FIELDS):
        raise HTTPException(400,'Invalid group ordering or instrument type')
    if cap_currency is not None and not re.fullmatch(r'[A-Z]{3}',cap_currency):
        raise HTTPException(400,'cap_currency must be an explicit three-letter currency')
    cohort, published = _stored_universe(market)
    if not cohort:
        return {'available':False,'reason':'no stored universe — run the loader','rows':[]}
    cohort = _merge_universe_meta(cohort,market)
    generation = cohort[0].get('generation_id')
    enrichment = {r['code']:r for r in db.select_all('screener_enrichment',{'market':f'eq.{market}'},'code,data,as_of')}
    acc, unclassified = {}, 0
    now = datetime.now(timezone.utc)
    for row in cohort:
        if row.get('stock_type') not in ('STOCK','ETF'):
            unclassified += 1
            continue
        if stock_type and row.get('stock_type') != stock_type:
            continue
        code = row.get('code') or f"{market}.{row.get('symbol')}"
        entry = enrichment.get(code) or {}
        supplemental,_ = _fresh_supplemental(entry.get('data'),entry.get('as_of'),now)
        currency = _group_cap_currency(row)
        cap = row.get('market_cap')
        classification = {'plate':row.get('plate'),'sector':supplemental.get('sector'),
                          'industry':supplemental.get('industry'),'exchange':row.get('exchange'),
                          'cap_bucket':currency+' · '+_cap_bucket(cap) if currency else None}[group_by]
        # Preserve provider filter values exactly; supplemental text was already
        # normalized by the shared helper used by screener and Groups alike.
        gkey = classification if isinstance(classification,str) and classification.strip() else 'Unknown'
        g = acc.setdefault(gkey,{'key':gkey,'stocks':0,'changes':[],'adv':0,'decl':0,
                                'volumes':[],'currencies':{},'cap_n':0,
                                'acc':{f:[] for f in _GROUPS_AVG_FIELDS}})
        g['stocks'] += 1
        if currency:
            g['currencies'].setdefault(currency,[]).append(cap)
            g['cap_n'] += 1
        volume = row.get('volume')
        if numeric(volume) and volume >= 0:
            g['volumes'].append(volume)
        pct = row.get('pct')
        if numeric(pct):
            g['changes'].append(pct)
            g['adv'] += int(pct>0);g['decl'] += int(pct<0)
        for field in _GROUPS_AVG_FIELDS:
            value = row.get(field)
            if value is None or value == '':value = supplemental.get(field)
            if not numeric(value):continue
            if field in ('pe_ttm','pb','forward_pe','peg') and value <= 0:continue
            if field in ('div_yield','short_float') and value < 0:continue
            if field == 'analyst_recom' and not 1 <= value <= 5:continue
            g['acc'][field].append(value)
    rows=[]
    for g in acc.values():
        single = len(g['currencies'])==1 and g['cap_n']==g['stocks']
        currency = next(iter(g['currencies'])) if single else None
        rows.append({'key':g['key'],'stocks':g['stocks'],
            'cap_sum':_group_sum(g['currencies'][currency]) if single else None,'cap_currency':currency,
            'cap_by_currency':{c:_group_sum(v) for c,v in g['currencies'].items()},
            'vol_sum':_group_sum(g['volumes']),
            'chg_avg':_group_mean(g['changes']),
            'adv':g['adv'],'decl':g['decl'],
            'avgs':{f:_group_mean(values) for f,values in g['acc'].items() if values},
            'coverage':{'market_cap':g['cap_n'],'volume':len(g['volumes']),'pct':len(g['changes']),
                        **{f:len(values) for f,values in g['acc'].items()}},
            'drillable':g['key']!='Unknown' and group_by!='cap_bucket'})
    currencies = {r['cap_currency'] for r in rows if r['cap_sum'] is not None}
    if order_by=='cap_sum' and cap_currency is None and len(currencies)>1:
        raise HTTPException(400,'Market cap ordering requires cap_currency when groups use different currencies')
    def sort_value(row):
        if order_by=='cap_sum' and cap_currency and row['cap_currency']!=cap_currency:return None
        return row['key'] if order_by=='name' else row.get(order_by) if order_by in ('stocks','cap_sum','chg_avg','vol_sum') else row['avgs'].get(order_by)
    known=[r for r in rows if sort_value(r) is not None];missing=[r for r in rows if sort_value(r) is None]
    known.sort(key=sort_value,reverse=direction==2);rows=known+missing
    return {'available':True,'market':market,'group_by':group_by,'generation_id':generation,
            'as_of':published,'rows':rows,'unclassified_count':unclassified,
            'ordering':{'field':order_by,'direction':direction,'cap_currency':cap_currency,
                        'missing_last':True},
            'scope':'Eligible stored instruments; supplemental factors are current retrievals, not pinned to the quote generation',
            'classification_source':'yfinance' if group_by in ('sector','industry') else 'provider_list' if group_by=='plate' else 'stored_quote_metadata',
            'aggregation':'Descriptive unweighted means over finite eligible cached values; financial periods are not qualified for peer ranking. Coverage counts are per field. Market cap sum requires complete coverage and one identity-checked currency; bucket thresholds use that currency. Aggregate overflow is unavailable.'}


@app.get("/stock/{rest:path}", include_in_schema=False)
def stock_spa(rest: str):
    """Pretty shareable URLs serve the SPA; the router reads the path client-side."""
    idx = _portal_index()
    if idx:
        return FileResponse(idx, media_type="text/html")
    raise HTTPException(404, "portal static not configured")


from .research_lists import router as research_lists_router
app.include_router(research_lists_router)
from .research_auth import router as research_auth_router
app.include_router(research_auth_router)

@app.middleware("http")
async def private_research_no_cache(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/research/"):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Pragma"] = "no-cache"
    return response

# Static portal (built SPA) — mounted last so /api wins.
_static = os.getenv("PORTAL_STATIC_DIR", "")
if _static and os.path.isdir(_static):
    app.mount("/", StaticFiles(directory=_static, html=True), name="portal")
