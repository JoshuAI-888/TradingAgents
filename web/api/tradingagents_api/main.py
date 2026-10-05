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
from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tradingagents_worker.enrich_fields import TECH_FIELDS
from tradingagents_worker.config import SETTINGS
from tradingagents_worker.db import Db
from tradingagents_worker.runner import demangle_debate
from tradingagents_worker.screener_rows import snapshot_to_row as _snapshot_to_row

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


_stored_universe_cache: dict[str, tuple[float, list, str | None]] = {}
_presets_cache: dict[str, tuple[float, dict]] = {}
_execute_cache: dict[str, tuple[float, dict]] = {}


def _stored_universe(market: str, max_age: float = 60.0):
    """screener_quotes rows + newest updated_at for a market, cached in-process
    for 60s. The loader refreshes hourly, but every screener/presets request
    re-read ~15k rows across 16 PostgREST pages (~3s) because the response
    cache only covered the live-fallback branch. (rows, as_of)."""
    now = time.time()
    hit = _stored_universe_cache.get(market)
    if hit and now - hit[0] < max_age:
        return hit[1], hit[2]
    stored = db.select_all("screener_quotes", {"market": f"eq.{market}"}, "row,updated_at")
    rows = [dict(r["row"]) for r in stored if isinstance(r.get("row"), dict)]
    for row in rows:
        code = row.get("code") or ""
        if code.startswith(f"{market}."):
            row["symbol"] = code.split(".", 1)[1]
    stamps = [r.get("updated_at") for r in stored if r.get("updated_at")]
    as_of = max(stamps) if stamps else None
    _stored_universe_cache[market] = (now, rows, as_of)
    return rows, as_of


def _merge_universe_meta(rows: list[dict], market: str) -> list[dict]:
    """Attach plate / stock_type / exchange from the stored universe (cached 5 min)."""
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
    rows = cache.get("quotes", uk)
    if rows is None:
        if watchlist_only:
            symbols = _watchlist_symbols()
            snap = (client_snapshot(market, symbols) or {}) if symbols else {}
            rows = [_snapshot_to_row(s) for s in (snap.get("snapshot_list") or [])]
        else:
            stored = db.select_all("screener_quotes", {"market": f"eq.{market}"}, "row")
            rows = [r["row"] for r in stored if isinstance(r.get("row"), dict)]
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


# Enrichment availability — MUST mirror web/worker/tradingagents_worker/
# enrich_fields.YF_ONLY_FIELDS (the registry is the source of truth; the API
# and worker don't import each other in this repo).
_groups_cache = None  # lazy /api/groups TTL cache

_YF_ONLY_FIELDS = {
    "forward_pe", "peg", "ps", "pcf", "pfcf", "ev", "ev_ebitda", "ev_sales",
    "roa", "current_ratio", "quick_ratio", "lt_debt_eq", "total_debt_eq",
    "shares_short", "short_float", "inst_own", "insider_own", "beta",
    "target_price", "analyst_recom", "country", "employees", "earnings_date",
    "ex_div_date", "payout_ratio", "sector", "industry",
}


@app.get("/api/screener")
def screener(market: str = "US", watchlist_only: int = 1, filters: str = "[]",
             sort: str = "market_cap", direction: int = 2, limit: int = 500,
             offset: int = 0, export: str = "", scope: str = "all",
             src: str = "moo"):
    """Screener rows. watchlist universe = our saved watchlist (snapshot, all filters);
    market universe = moomoo stock-screen page sorted server-side, snapshot-enriched."""
    client = _market_client()
    if client is None:
        return {"available": False, "reason": "moomoo keys not configured", "rows": []}
    try:
        flt = json.loads(filters) if filters else []
    except ValueError:
        raise HTTPException(400, "filters must be JSON")
    cache = _cache()
    universe_key = cache.key("quotes", "screener-universe", market, watchlist_only, sort, direction)
    rows = cache.get("quotes", universe_key)
    universe_loaded = False
    universe_as_of = None
    if rows is None and not watchlist_only:
        # Preferred whole-market source: the stored universe (loaded by the
        # universe_refresh job) — zero moomoo calls at view time, cached 60s.
        rows, universe_as_of = _stored_universe(market)
        if rows:
            universe_loaded = True
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
            meta = data.get("_meta") or {}
            for k, v in data.items():
                if k == "_meta":
                    continue
                stamp = meta.get("technicals_at" if k in TECH_FIELDS else "fundamentals_at") or row_stamp
                try:
                    age = (datetime.now(timezone.utc) - datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))).total_seconds()
                except (TypeError, ValueError):
                    continue
                if 0 <= age <= (86400 if k in TECH_FIELDS else 7 * 86400):
                    r.setdefault(k, v)
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
        cols += [k for k in (rows[0] if rows else {}) if k not in cols]
        from xml.sax.saxutils import escape as _x
        from fastapi.responses import Response
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
        fname = f"screener_{market}_{matched}rows_{stamp}"
        if export == "csv":
            def cell(v):
                s = "" if v is None else str(v)
                return '"' + s.replace('"', '""') + '"' if any(ch in s for ch in ',"\n') else s
            lines = [",".join(cell(c) for c in cols)]
            lines += [",".join(cell(r.get(c)) for c in cols) for r in rows]
            return Response("\ufeff" + "\n".join(lines), media_type="text/csv; charset=utf-8",
                            headers={"Content-Disposition": f'attachment; filename="{fname}.csv"'})
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
                    cells.append(f'<Cell><Data ss:Type="String">{_x(str(v))}</Data></Cell>')
            xml.append("<Row>" + "".join(cells) + "</Row>")
        xml.append("</Table></Worksheet></Workbook>")
        return Response("".join(xml), media_type="application/vnd.ms-excel",
                        headers={"Content-Disposition": f'attachment; filename="{fname}.xls"'})
    # limit up to 20000: the portal fetches the WHOLE matched set once per
    # minute and filters/sorts/pager client-side for instant interactivity.
    page = rows[max(0, offset):max(0, offset) + max(1, min(limit, 20000))]
    return {"available": True, "universe": "watchlist" if watchlist_only else market,
            "rows": page, "count": matched, "matched": matched, "shown": len(page),
            "offset": max(0, offset),
            "skipped_filters": skipped,
            "enrich_as_of": enrich_as_of,
            "universe_loaded": universe_loaded or bool(rows), "universe_as_of": universe_as_of,
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
    hit = _presets_cache.get(f"{market}|{universe}")
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
            rows, _as_of = _stored_universe(market)
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
    out_payload = {"available": True, "presets": out, "universe_rows": len(rows)}
    _presets_cache[f"{market}|{universe}"] = (time.time(), out_payload)
    return out_payload

@app.get("/api/screener/schedule")
def screener_schedule_get():
    """Universe-refresh cadence + current loader state (settings page + cron).
    stock_rows/other_rows explain the count gap vs moomoo's app total: the app
    counts every instrument type; the screener serves common stocks by default."""
    state = _universe_state()
    rows = db.select_all("screener_quotes", {"market": "eq.US"}, "code")
    urows = db.select_all("screener_universe", {"market": "eq.US"}, "code,stock_type")
    stock_rows = sum(1 for r in urows if r.get("stock_type") == "STOCK")
    return {"interval_h": float(state.get("interval_h") or 1),
            "last_quotes": state.get("last_quotes"), "last_enum": state.get("last_enum"),
            "last_result": state.get("last_result") or {},
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


def _server_retrieves(fields: list[str]) -> list[dict]:
    out = []
    for f in fields:
        spec = _FIELD_SERVER.get(f)
        if not spec:
            continue
        kind, pid, _ = spec
        if kind == "simple":
            out.append({"simple_property": {"name": pid}})
        elif kind == "cumulative":
            out.append({"cumulative_property": {"name": pid, "periodAverage": 30}})
        else:
            out.append({"financial_property": {"name": pid, "term": _FINANCIAL_TERM}})
    return out


@app.get("/api/screener/execute")
def screener_execute(key: str = "", market: str = "US", limit: int = 60, next_key: str = ""):
    """Execute a preset (or saved screener by ?key=saved:<id>) SERVER-SIDE — the
    same screening backend moomoo's own screener page uses, so results and
    result counts reconcile with moomoo.com/screener."""
    ck = f"{key}|{market}|{min(limit, 300)}|{next_key}"
    hit = _execute_cache.get(ck)
    if hit and time.time() - hit[0] < 60.0:
        return hit[1]
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
    retrieves = _server_retrieves([f.get("field") for f in filters])
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
    items = (data or {}).get("items") or []
    rows = []
    for it in items:
        vals = {}
        for r in it.get("results") or []:
            rr = list(r.values())[0]
            res = rr.get("res") or rr
            raw = res.get("ival")
            if raw is None:
                raw = res.get("dval")
            if raw is None and "res" not in rr:
                raw = rr.get("value")  # Legacy flat response only; empty typed res is unavailable.
            try:
                value = float(raw) if raw not in (None, "") else None
                if value is not None and not math.isfinite(value):
                    value = None
            except (ValueError, TypeError):
                value = None
            vals[rr.get("property", {}).get("name")] = value
        code = it.get("code") or ""
        pct = vals.get(3102, vals.get(2210))
        rows.append({
            "symbol": code.split(".", 1)[-1], "code": code, "name": it.get("name") or "",
            "price": (vals.get(2201) or 0) / 1000 or None,
            "pct": pct / 1000 if pct is not None else None,
            "market_cap": (vals.get(2301) or 0) / 1000 or None,
            "factors": {k: v for k, v in vals.items() if k not in (2201, 2301, 2210, 3102)},
            "criterion_values": {f: vals[spec[1]] / spec[2] for f, spec in _FIELD_SERVER.items()
                                 if vals.get(spec[1]) is not None},
        })
        # Expose verified annual financial evidence in the existing columns.
        # Period-averaged volume stays separate from the snapshot volume column.
        for field, value in rows[-1]["criterion_values"].items():
            if _FIELD_SERVER[field][0] == "financial":
                rows[-1][field] = value
    # moomoo's stock-screen retrieves can come back all-null for every item
    # (2026-09-29), which left preset tables blank — display fields are filled
    # from the stored snapshot the universe loader keeps fresh; screen values
    # fill any gap the snapshot doesn't cover.
    codes = sorted({r["code"] for r in rows if r["code"]})
    if codes:
        stored = db.select("screener_quotes", {"market": f"eq.{market}",
                                               "code": f"in.({','.join(codes)})"}, "row")
        by_code = {q["row"].get("code"): q["row"] for q in stored if isinstance(q.get("row"), dict)}
        for r in rows:
            for k, v in (by_code.get(r["code"]) or {}).items():
                if r.get(k) is None:
                    r[k] = v
        # The screen can match listings our plate enumeration never captured
        # (OTC/pink-sheet tail) — one live snapshot call fills those gaps.
        missing = [r["code"] for r in rows if r.get("price") is None]
        if missing:
            try:
                snap = (client.snapshot(missing) or {}).get("snapshot_list") or []
                live = {q.get("code"): q for q in (_snapshot_to_row(s) for s in snap)}
                for r in rows:
                    for k, v in (live.get(r["code"]) or {}).items():
                        if r.get(k) is None:
                            r[k] = v
            except Exception:
                pass
        _merge_universe_meta(rows, market)
        unclassified = [r["code"] for r in rows if not r.get("stock_type")]
        if unclassified:
            try:
                basic = client.call("POST", "/quote/stock-basicinfo", body={"code_list": unclassified}) or {}
                info = {b.get("code"): b for b in basic.get("basic_list") or []}
                for r in rows:
                    b = info.get(r["code"]) or {}
                    if not r.get("stock_type"):
                        r["stock_type"] = b.get("stock_type")
                    if not r.get("exchange"):
                        r["exchange"] = b.get("exchange")
            except Exception:
                pass  # Unclassified instruments remain excluded by the stock-only view.
    pagination = data.get("pagination") or {}
    cursor = pagination.get("next_key") or data.get("next_key") or data.get("nextKey")
    has_more = pagination.get("has_more")
    if has_more is None:
        has_more = bool(data.get("has_more") or data.get("hasMore") or (cursor and cursor != "-1") or len(items) >= body["limit"])
    out_payload = {"available": True, "key": key, "name": name, "description": description,
                   "market": market, "pending": pending, "filters": filters,
                   "sort": sort, "direction": direction, "result_limit": body["limit"],
                   "possibly_truncated": bool(has_more), "next_key": cursor if cursor != "-1" else None,
                   "provider_total": pagination.get("total", data.get("total")), "retrieved_at": datetime.now(timezone.utc).isoformat(),
                   "evidence_status": "provider_membership", "rows": rows, "shown": len(rows)}
    _execute_cache[ck] = (time.time(), out_payload)
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


def _snapshot_history(key: str) -> list[dict]:
    rows = db.select("app_settings", {"key": f"eq.{key}"}, "value")
    return (rows[0].get("value") or {}).get("snapshots", []) if rows else []


@app.post("/api/screener/snapshots")
def capture_screen_snapshot(inp: ScreenDefinition):
    key = _snapshot_key(inp)
    if inp.preset:
        result = screener_execute(inp.preset, inp.market, 300)
        combined = list(result.get("rows") or [])
        cursors = set()
        while result.get("available") and result.get("possibly_truncated") and result.get("next_key") and len(cursors) < 24:
            cursor = result["next_key"]
            if cursor in cursors:
                break
            cursors.add(cursor)
            result = screener_execute(inp.preset, inp.market, 300, cursor)
            combined.extend(result.get("rows") or [])
        if not result.get("available") or result.get("possibly_truncated") or result.get("pending"):
            raise HTTPException(409, "Provider results are unavailable, incomplete or have unapplied criteria; no snapshot captured")
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
                          filters=json.dumps(inp.filters), sort="market_cap", direction=2,
                          limit=20000, offset=0, src=inp.src)
        if (not result.get("available") or not result.get("universe_loaded")
                or result.get("skipped_filters") or result.get("matched", 0) > len(result.get("rows") or [])):
            raise HTTPException(409, "Stored universe is unavailable, incomplete or lacks criterion data; no snapshot captured")
        rows = result.get("rows") or []
        source_at = result.get("universe_as_of")
    codes = [r.get("code") for r in rows]
    if any(not c for c in codes) or len(codes) != len(set(codes)):
        raise HTTPException(409, "Result identities are incomplete or duplicated; no snapshot captured")
    if not source_at:
        raise HTTPException(409, "Source timestamp is unavailable; no comparable snapshot captured")
    source_age = (datetime.now(timezone.utc) - datetime.fromisoformat(source_at.replace("Z", "+00:00"))).total_seconds()
    if source_age > 86400:
        raise HTTPException(409, "Source data is older than 24 hours; refresh before capturing changes")
    snapshot = {"at": datetime.now(timezone.utc).isoformat(), "source_at": source_at,
                "members": [{"code": r["code"], "symbol": r.get("symbol"), "name": r.get("name"),
                             "evidence": {f.get("field"): (r.get("criterion_values") or {}).get(f.get("field"), r.get(f.get("field")))
                                          for f in inp.filters}}
                            for r in rows], "complete": True}
    history = _snapshot_history(key)
    history = (history + [snapshot])[-2:]
    db.upsert("app_settings", "key", {"key": key, "value": {"snapshots": history}})
    return {"captured": True, "members": len(rows), "at": snapshot["at"], "baseline": len(history) == 1}


@app.get("/api/screener/changes")
def screen_changes(definition: str):
    try:
        inp = ScreenDefinition.model_validate_json(definition)
    except ValueError:
        raise HTTPException(400, "Invalid screen definition")
    history = _snapshot_history(_snapshot_key(inp))
    if len(history) < 2:
        return {"comparable": False, "reason": "Baseline captured. Capture another complete snapshot to compare." if history else
                "No baseline yet. Capture a complete snapshot to start."}
    previous, current = history[-2:]
    if not previous.get("complete") or not current.get("complete"):
        return {"comparable": False, "reason": "Incomplete snapshots cannot establish entries or exits."}
    a = {r["code"]: r for r in previous["members"]}
    b = {r["code"]: r for r in current["members"]}
    return {"comparable": True, "previous_at": previous["at"], "current_at": current["at"],
            "added": [b[k] for k in sorted(b.keys() - a.keys())],
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


class ScheduleIn(BaseModel):
    interval_h: int


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
# 8=30min 9=60min 10=3min 26=10min 14=120min 29=180min 15=240min. The old set
# had Daily and 1Y both at ktype 2/~380d — identical data, so switching
# horizons "did nothing". Each horizon now maps to distinct data; 1d/15m added
# for the Compare page's intraday timeframes; 3m/10m/1h/2h/3h/4h are the
# native bar-size intervals for the v10 chart engine.
_KLINE_WINDOWS = {"1d": ("candles:1d", 1, 2), "5D": ("candles:5D", 6, 10),
                  "3m": ("candles:3m", 10, 45), "10m": ("candles:10m", 26, 90),
                  "15m": ("candles:15m", 7, 30),
                  "1M": ("candles:1M", 8, 45), "1h": ("candles:1h", 9, 120),
                  "2h": ("candles:2h", 14, 240), "3h": ("candles:3h", 29, 300),
                  "4h": ("candles:4h", 15, 380),
                  "3M": ("candles:3M", 9, 120), "Q": ("candles:Q", 2, 105),
                  "6M": ("candles:6M", 2, 190), "Y": ("candles:Y", 2, 380),
                  "W": ("candles:W", 3, 3400), "M": ("candles:M", 4, 4200),
                  "10Y": ("candles:10Y", 5, 4200)}
# Intraday ktypes go stale fast — 60 s TTL instead of the 24 h daily-bar TTL.
_KTYPE_LIVE = {1, 6, 10, 26, 7, 8, 9, 14, 29, 15}
# Bar-size interval names for the chart engine's DataLoader paging.
_KTYPE_ENUM = {"K_1M": 1, "K_3M": 10, "K_5M": 6, "K_10M": 26, "K_15M": 7,
               "K_30M": 8, "K_60M": 9, "K_120M": 14, "K_180M": 29,
               "K_240M": 15, "K_D": 2, "K_W": 3, "K_M": 4}
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

    category = "ohlcv_live" if ktype in _KTYPE_LIVE else "ohlcv"
    out = _stock_fetch(key, symbol, category, fetch)
    if isinstance(out, dict) and "kline_list" in out:
        out = {"available": True, "range": range, "bars": out["kline_list"]}
    return _stock_out(out)


@app.get("/api/stock/{symbol}/candles/back")
def stock_candles_back(symbol: str, ktype: str = "K_D",
                       before: int | None = None, count: int = 300):
    """Paged history for the chart's DataLoader backward loading: ascending
    bars strictly older than `before` (epoch ms; omitted = newest). Each page
    is one date-windowed upstream call kept behind the TTL cache, so long
    scroll-backs stay inside the 30 req/min/path budget."""
    if ktype not in _KTYPE_ENUM:
        raise HTTPException(400, "ktype must be one of " + ",".join(_KTYPE_ENUM))
    if not isinstance(count, int) or count <= 0:
        raise HTTPException(400, "count must be a positive integer")
    count = min(count, 1000)
    if os.getenv("TA_STOCK_FIXTURES"):
        from tradingagents_api import stock_fixtures
        return stock_fixtures.candles_back(ktype, before, count)
    kt = _KTYPE_ENUM[ktype]
    if kt in (2, 3, 4, 5):
        days = min(4200, int(count * {2: 1.7, 3: 11, 4: 32, 5: 370}[kt]) + 4)
    else:
        step_s = {1: 60, 10: 180, 6: 300, 26: 600, 7: 900, 8: 1800,
                  9: 3600, 14: 7200, 29: 10800, 15: 14400}[kt]
        days = min(30, max(2, int(count * step_s / (6.5 * 3600)) + 2))
    end_date = datetime.fromtimestamp((before or time.time() * 1000) / 1000,
                                      tz=timezone.utc).date()
    start = (end_date - timedelta(days=days)).isoformat()

    def fetch(c):
        return {"kline_list": c.history_kline(
            _stock_code(symbol), start, end_date.isoformat(), ktype=kt)}

    category = "ohlcv_live" if kt in _KTYPE_LIVE else "ohlcv"
    out = _stock_fetch(f"candles-back:{ktype}:{before}:{count}", symbol,
                       category, fetch)
    if isinstance(out, dict) and "kline_list" in out:
        bars = [b for b in out["kline_list"]
                if not before or b.get("time_key", 0) < before]
        return {"available": True, "ktype": ktype, "bars": bars[-count:]}
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


@app.get("/api/groups")
def groups(market: str = "US", group_by: str = "plate", order_by: str = "stocks",
           direction: int = 2, stock_type: str = "STOCK"):
    """Finviz-style group aggregates over stored data — zero vendor calls at
    view time (spec §4c / Phase A). group_by: plate | sector | industry |
    exchange | cap_bucket; sector/industry need yf enrichment rows."""
    global _groups_cache
    if _groups_cache is None:
        from tradingagents_worker.ttl_cache import TtlCache  # noqa: E402
        _groups_cache = TtlCache(root=os.path.join(tempfile.gettempdir(), "ta-ttl-groups"))
    key = _groups_cache.key("other", "groups", market, group_by, order_by, direction, stock_type)
    cached = _groups_cache.get("other", key)
    if cached is not None:
        return cached
    # NOTE: code must be selected explicitly — PostgREST returns only the
    # requested columns, and the meta/enrichment lookups key on it.
    stored = db.select_all("screener_quotes", {"market": f"eq.{market}"}, "code,row,updated_at")
    if not stored:
        return {"available": False, "reason": "no stored universe — run the loader", "rows": []}
    meta = {r["code"]: r for r in db.select_all(
        "screener_universe", {"market": f"eq.{market}"}, "code,plate,stock_type,exchange")}
    enr = {r["code"]: (r.get("data") or {}) for r in
           db.select_all("screener_enrichment", {"market": f"eq.{market}"}, "code,data")}
    stamps = [r.get("updated_at") for r in stored if r.get("updated_at")]
    acc: dict[str, dict] = {}
    for s in stored:
        row = s.get("row") or {}
        code = s.get("code")
        u = meta.get(code) or {}
        if stock_type and u.get("stock_type") != stock_type:
            continue  # mirror /api/screener: unclassified rows are excluded
        en = enr.get(code) or {}
        gkey = {"plate": u.get("plate") or "—",
                "sector": en.get("sector") or "—",
                "industry": en.get("industry") or u.get("plate") or "—",
                "exchange": u.get("exchange") or "—",
                "cap_bucket": _cap_bucket(row.get("market_cap"))}[group_by]
        g = acc.setdefault(gkey, {"key": gkey, "stocks": 0, "cap_sum": 0.0, "chg_sum": 0.0,
                                  "chg_n": 0, "adv": 0, "decl": 0, "vol_sum": 0.0,
                                  "acc": {f: [0.0, 0] for f in _GROUPS_AVG_FIELDS}})
        g["stocks"] += 1
        g["cap_sum"] += row.get("market_cap") or 0
        g["vol_sum"] += row.get("volume") or 0
        pct = row.get("pct")
        if pct is not None:
            g["chg_sum"] += pct
            g["chg_n"] += 1
            g["adv"] += 1 if pct > 0 else 0
            g["decl"] += 1 if pct < 0 else 0
        for f in _GROUPS_AVG_FIELDS:
            v = row.get(f, en.get(f))
            try:
                v = float(v)
            except (TypeError, ValueError):
                continue
            g["acc"][f][0] += v
            g["acc"][f][1] += 1
    rows = []
    for g in acc.values():
        avgs = {f: round(s / n, 4) for f, (s, n) in g["acc"].items() if n}
        rows.append({"key": g["key"], "stocks": g["stocks"],
                     "cap_sum": round(g["cap_sum"], 2), "vol_sum": round(g["vol_sum"], 2),
                     "chg_avg": round(g["chg_sum"] / g["chg_n"], 4) if g["chg_n"] else None,
                     "adv": g["adv"], "decl": g["decl"], "avgs": avgs})

    def sort_key(r):
        if order_by == "name":
            return r["key"]
        if order_by in ("stocks", "cap_sum", "chg_avg", "vol_sum"):
            v = r.get(order_by)
            return 0 if v is None else v
        if order_by in _GROUPS_AVG_FIELDS:
            return (r.get("avgs") or {}).get(order_by, 0)
        return r["stocks"]

    rows.sort(key=sort_key, reverse=direction == 2)
    out = {"available": True, "group_by": group_by,
           "as_of": max(stamps) if stamps else None, "rows": rows}
    _groups_cache.put("other", key, out)
    return out


@app.get("/stock/{rest:path}", include_in_schema=False)
def stock_spa(rest: str):
    """Pretty shareable URLs serve the SPA; the router reads the path client-side."""
    idx = _portal_index()
    if idx:
        return FileResponse(idx, media_type="text/html")
    raise HTTPException(404, "portal static not configured")


# Static portal (built SPA) — mounted last so /api wins.
_static = os.getenv("PORTAL_STATIC_DIR", "")
if _static and os.path.isdir(_static):
    app.mount("/", StaticFiles(directory=_static, html=True), name="portal")
