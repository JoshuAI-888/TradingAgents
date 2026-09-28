"""TradingAgents portal API (FastAPI).

Reads Supabase with the service key for writes the client can't do (enqueue),
and lets the browser read its own rows via the anon key + RLS directly
(Supabase JS) — this API exists for orchestration and cross-table joins.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tradingagents_worker.config import SETTINGS
from tradingagents_worker.db import Db
from tradingagents_worker.screener_rows import snapshot_to_row as _snapshot_to_row

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


@app.post("/api/analyses")
def submit(inp: AnalyzeIn, x_user_id: str = Header(default="")):
    """Enqueue an analysis. Idempotent per (ticker, date, depth) per day via idempotency_key."""
    if not SETTINGS.supabase_url:
        raise HTTPException(503, "SUPABASE_URL not configured")
    key = f"analysis:{inp.ticker.upper()}:{inp.trade_date}:{inp.depth}"
    # Single-user Phase 0: unauthenticated submissions are owned by DEFAULT_USER_ID.
    user_id = x_user_id or os.getenv("DEFAULT_USER_ID") or None
    existing = db.select("jobs", {"idempotency_key": f"eq.{key}"}, "id,status")
    # A failed/cancelled job must not block re-running the same analysis.
    if existing and existing[0].get("status") not in ("failed", "cancelled"):
        return {"job_id": existing[0]["id"], "status": existing[0].get("status", "pending"),
                "deduplicated": True}
    row = db.insert("jobs", {
        "job_type": "analysis", "user_id": user_id,
        "payload": {"ticker": inp.ticker.upper(), "trade_date": str(inp.trade_date),
                    "depth": inp.depth, "instructions": inp.instructions},
        "idempotency_key": key,
    }, prefer="return=representation")
    job = row if isinstance(row, dict) else (row or [{}])[0]
    return {"job_id": job.get("id"), "status": job.get("status", "pending"), "deduplicated": False}


@app.get("/api/analyses/{job_id}")
def status(job_id: str):
    jobs = db.select("jobs", {"id": f"eq.{job_id}"}, "id,status,run_id,last_error,created_at,finished_at")
    if not jobs:
        raise HTTPException(404, "job not found")
    job = jobs[0]
    events = db.select("job_events", {"job_id": f"eq.{job_id}", "order": "seq.asc"},
                       "seq,ts,stage,status,message,payload")
    return {"job": job, "events": events}


@app.get("/api/analyses/{ref}/report")
def report(ref: str):
    """Full dossier for the report page. `ref` is a job id or a decision id."""
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
    debates = db.select("debate_messages", {"run_id": f"eq.{run['id']}", "order": "created_at.asc"},
                        "debate_type,speaker,round,content")
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
def bars(symbol: str, days: int = 180):
    rows = db.select("tickers", {"symbol": f"eq.{symbol.upper()}"}, "id")
    if not rows:
        raise HTTPException(404, "unknown ticker")
    bars = db.select("price_bars", {"ticker_id": f"eq.{rows[0]['id']}",
                                    "order": "bar_date.desc", "limit": "400"},
                     "bar_date,open,high,low,close,volume")
    bars = list(reversed([b for b in bars if b.get("bar_date")]))
    if days > 0 and len(bars) > days:
        bars = bars[-days:]
    return {"symbol": symbol.upper(), "bars": bars}


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
    """Analyses queued or running right now — the ledger's 'In flight' panel."""
    jobs = db.select("jobs", {"status": "eq.pending", "order": "created_at.desc", "limit": "20"},
                     "id,status,payload,created_at,locked_by")
    jobs += db.select("jobs", {"status": "eq.running", "order": "created_at.desc", "limit": "20"},
                      "id,status,payload,created_at,locked_by")
    return {"jobs": jobs}


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

# The 21 recommended screeners, transcribed 1:1 from moomoo's preset pages
# ("Applied Filters" text + the Selected chips, 2026-09-28). Filters over
# fields the snapshot doesn't carry (ROE, growth rates, margins, RSI, sector…)
# stay in the definition for fidelity — the filter engine skips them until the
# factor data lands, and responses report what was skipped.
PRESET_SCREENERS = [
    {"key": "penny", "page": 1, "name": "Penny Stocks",
     "description": "Spot undervalued, low-priced stocks for substantial returns.",
     "filters": [{"field": "price", "max": 5}, {"field": "market_cap", "max": 3e8},
                 {"field": "volume", "min": 1e5},
                 {"field": "revenue_growth", "min": 10, "needs": 1},
                 {"field": "net_profit_growth", "min": 5, "needs": 1},
                 {"field": "debt_ratio", "max": 40, "needs": 1}]},
    {"key": "high-div", "page": 1, "name": "High Dividend Stocks",
     "description": "Spot high-yield, stable dividend stocks for reliable income.",
     "filters": [{"field": "market_cap", "min": 2e9}, {"field": "pe_ttm", "max": 12},
                 {"field": "div_yield", "min": 8},
                 {"field": "debt_ratio", "max": 30, "needs": 1},
                 {"field": "revenue_growth", "min": 5, "needs": 1}]},
    {"key": "blue-chip", "page": 1, "name": "Blue Chip Stocks",
     "description": "Spot blue-chip stocks from well-established companies for reliable returns and low volatility.",
     "filters": [{"field": "price", "min": 50}, {"field": "market_cap", "min": 1e11},
                 {"field": "debt_ratio", "max": 50, "needs": 1},
                 {"field": "revenue_growth", "min": 5, "needs": 1}]},
    {"key": "buffett", "page": 1, "name": "Warren Buffett Strategy",
     "description": "Spot stocks with strong earnings, growth potential, and recognized value for strategic long-term investment.",
     "filters": [{"field": "float_cap", "min": 5e8},
                 {"field": "net_profit_growth", "min": 10, "needs": 1},
                 {"field": "gross_margin", "min": 50, "needs": 1},
                 {"field": "op_ebt", "min": 70, "needs": 1},
                 {"field": "roe", "min": 15, "needs": 1},
                 {"field": "roe_yoy", "min": 20, "needs": 1}]},
    {"key": "undervalued", "page": 1, "name": "Undervalued Stocks",
     "description": "Spot stable, undervalued stocks for long-term growth.",
     "filters": [{"field": "pe_ttm", "max": 15}, {"field": "pb", "max": 1.5},
                 {"field": "div_yield", "min": 4},
                 {"field": "debt_ratio", "max": 30, "needs": 1},
                 {"field": "roe", "min": 15, "needs": 1},
                 {"field": "revenue_growth", "min": 3, "needs": 1}]},
    {"key": "growth", "page": 1, "name": "Best Growth Stocks",
     "description": "Spot stocks with growth potential and solid financial standing.",
     "filters": [{"field": "float_cap", "min": 5e8},
                 {"field": "net_profit_growth", "min": 15, "needs": 1},
                 {"field": "gross_margin", "min": 50, "needs": 1},
                 {"field": "roe", "min": 15, "needs": 1},
                 {"field": "roe_yoy", "min": 50, "needs": 1}]},
    {"key": "pb-lt-1", "page": 1, "name": "P/B Ratio Less Than 1",
     "description": "Spot stocks with a price-to-book ratio (P/B) below 1. A lower P/B may indicate an undervaluation and a margin of safety.",
     "filters": [{"field": "pb", "max": 1}]},
    {"key": "high-pe", "page": 2, "name": "High P/E Ratio Stocks",
     "description": "Spot stocks with high P/E ratios, which suggest a profitable and sustainable business.",
     "filters": [{"field": "pe_ttm", "min": 25}, {"field": "roe_yoy", "min": 30, "needs": 1}]},
    {"key": "good-pe", "page": 2, "name": "Good P/E Ratio Stocks",
     "description": "Spot stocks with solid fundamentals and high P/E ratios for consistent profitability and returns.",
     "filters": [{"field": "pe_ttm", "min": 20}, {"field": "eps_growth", "min": 5, "needs": 1},
                 {"field": "div_yield", "min": 2}, {"field": "net_margin", "min": 10, "needs": 1}]},
    {"key": "low-pe", "page": 2, "name": "Low P/E Ratio Stocks",
     "description": "Spot stocks with low P/E ratios, which are potentially undervalued for stable gains and reduced risk.",
     "filters": [{"field": "pe_ttm", "max": 5}, {"field": "pb", "max": 3},
                 {"field": "debt_ratio", "max": 60, "needs": 1}]},
    {"key": "rsi-30", "page": 2, "name": "Below 30 RSI Stocks",
     "description": "Spot stocks with an RSI value under 30, which may indicate a rebound from negative market sentiment.",
     "filters": [{"field": "rsi14", "max": 30, "needs": 1}]},
    {"key": "junk", "page": 2, "name": "Junk Stocks",
     "description": "Spot small, high-risk, yet undervalued stocks with the potential for significant returns.",
     "filters": [{"field": "pe_ttm", "min": 0}, {"field": "price", "max": 5},
                 {"field": "market_cap", "max": 1e8}]},
    {"key": "small-growth", "page": 2, "name": "Small Cap Stocks with Huge Growth Potential",
     "description": "Spot small-cap stocks with significant growth potential.",
     "filters": [{"field": "price", "min": 1}, {"field": "market_cap", "min": 2.5e8, "max": 2e9},
                 {"field": "revenue_growth", "min": 20, "needs": 1},
                 {"field": "rsi14", "min": 50, "needs": 1}]},
    {"key": "blue-chip-div", "page": 2, "name": "Blue Chip Dividend Stocks",
     "description": "Spot familiar blue-chip stocks with high dividends for dependable income and value investment.",
     "filters": [{"field": "price", "min": 50}, {"field": "market_cap", "min": 1e11},
                 {"field": "debt_ratio", "max": 50, "needs": 1},
                 {"field": "div_yield", "min": 4}]},
    {"key": "speculative", "page": 3, "name": "Speculative Stocks",
     "description": "Spot high-risk, high-return stocks, including those at their recent 10-day low that may be undervalued and ready to rebound.",
     "filters": [{"field": "price", "min": 5}, {"field": "market_cap", "min": 1e8},
                 {"field": "net_margin", "min": 10, "needs": 1},
                 {"field": "debt_ratio", "max": 50, "needs": 1},
                 {"field": "new_low_10d", "min": 1, "needs": 1}]},
    {"key": "high-roe", "page": 3, "name": "High Return On Equity Stocks",
     "description": "Spot high-quality stocks with solid profitability, growth, and attractive dividends for long-term stability.",
     "filters": [{"field": "roe", "min": 20, "needs": 1},
                 {"field": "revenue_growth", "min": 5, "needs": 1},
                 {"field": "div_yield", "min": 2}, {"field": "pe_ttm", "max": 25}]},
    {"key": "lt-high-div", "page": 3, "name": "Low P/E High Dividend Stocks",
     "description": "Spot financially stable, consistently growing stocks for secure and steady long-term returns.",
     "filters": [{"field": "pe_ttm", "max": 15}, {"field": "div_yield", "min": 4},
                 {"field": "revenue_growth", "min": 3, "needs": 1},
                 {"field": "debt_ratio", "max": 50, "needs": 1}]},
    {"key": "undervalued-semi", "page": 3, "name": "Undervalued Semiconductor Stocks",
     "description": "Spot semiconductor sector stocks that are well-valued, financially robust, and profitable for attractive long-term returns.",
     "filters": [{"field": "sector", "needs": 1},
                 {"field": "pe_ttm", "max": 18}, {"field": "pb", "max": 5},
                 {"field": "roe", "min": 10, "needs": 1}]},
    {"key": "undervalued-tech", "page": 3, "name": "Undervalued Tech Stocks",
     "description": "Spot tech stocks that are undervalued by the market.",
     "filters": [{"field": "sector", "needs": 1},
                 {"field": "pe_ttm", "max": 15}, {"field": "pb", "max": 5},
                 {"field": "roe", "min": 10, "needs": 1}]},
    {"key": "undervalued-banks", "page": 3, "name": "Undervalued Bank Stocks",
     "description": "Spot bank stocks that are financially sound, reasonably valued, and highly profitable.",
     "filters": [{"field": "sector", "needs": 1},
                 {"field": "pe_ttm", "max": 10}, {"field": "pb", "max": 1},
                 {"field": "roe", "min": 12, "needs": 1}]},
    {"key": "high-eps", "page": 3, "name": "High EPS Stocks",
     "description": "Spot stocks with favorable financial footing and high profitability for investment.",
     "filters": [{"field": "price", "min": 5}, {"field": "market_cap", "min": 1e8},
                 {"field": "eps", "min": 10}, {"field": "debt_ratio", "max": 50, "needs": 1}]},
]


def _apply_filters(rows: list[dict], filters: list[dict]) -> tuple[list[dict], list[str]]:
    """Filter rows; a field absent from the whole universe SKIPS its filter
    instead of failing every row (moomoo presets carry fundamental/technical
    factors the snapshot doesn't provide yet). Returns (rows, skipped_fields)."""
    present: set[str] = set()
    for r in rows[:50]:
        present.update(k for k, v in r.items() if v is not None)
    active, skipped = [], []
    for f in filters or []:
        (active if f.get("field") in present else skipped).append(f)
    def keep(r: dict) -> bool:
        for f in active:
            v = r.get(f.get("field"))
            lo, hi = f.get("min"), f.get("max")
            if v is None:
                return False
            try:
                v = float(v)
            except (TypeError, ValueError):
                return False
            if lo is not None and v < float(lo):
                return False
            if hi is not None and v > float(hi):
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


@app.get("/api/screener")
def screener(market: str = "US", watchlist_only: int = 1, filters: str = "[]",
             sort: str = "market_cap", direction: int = 2, limit: int = 500):
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
        # universe_refresh job) — zero moomoo calls at view time.
        stored = db.select_all("screener_quotes", {"market": f"eq.{market}"}, "row,updated_at")
        if stored:
            rows = [r["row"] for r in stored if isinstance(r.get("row"), dict)]
            stamps = [r.get("updated_at") for r in stored if r.get("updated_at")]
            universe_as_of = max(stamps) if stamps else None
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
    rows, skipped = _apply_filters(rows, flt)
    # Always display-sort in Python: the server-side slices decide WHICH stocks
    # are in the universe; global ordering across the union happens here.
    rows = _sort_rows(rows, sort, direction)
    matched = len(rows)
    rows = rows[:max(1, min(limit, 2000))]
    return {"available": True, "universe": "watchlist" if watchlist_only else market,
            "rows": rows, "count": matched, "matched": matched, "shown": len(rows),
            "skipped_filters": skipped,
            "universe_loaded": universe_loaded or bool(rows), "universe_as_of": universe_as_of,
            "presets": PRESET_SCREENERS,
            "watchlist": _watchlist_symbols()}


@app.get("/api/screener/presets")
def screener_presets(market: str = "US", universe: str = "auto"):
    """ALL recommended screeners (one list) scored over the ACTIVE universe —
    whole-market (stored universe first, live slices as fallback) or watchlist."""
    client = _market_client()
    if client is None:
        return {"available": False, "presets": []}
    cache = _cache()
    if universe == "watchlist":
        uk = cache.key("quotes", "screener-universe", market, 1, "market_cap", 2)
        rows = cache.get("quotes", uk)
        if rows is None:
            symbols = _watchlist_symbols()
            if symbols:
                snap = (client.snapshot([f"{market}.{s}" for s in symbols[:400]])
                        or {}).get("snapshot_list") or []
                rows = [_snapshot_to_row(s) for s in snap]
            else:
                rows = []
            cache.put("quotes", uk, rows)
    else:
        stored = db.select_all("screener_quotes", {"market": f"eq.{market}"}, "row")
        if stored:
            rows = [r["row"] for r in stored if isinstance(r.get("row"), dict)]
        else:
            uk = cache.key("quotes", "screener-universe", market, 0, "market_cap", 2)
            rows = cache.get("quotes", uk)
            if rows is None:
                try:
                    rows = _market_rows(market, "market_cap", 2, client)
                except Exception:
                    rows = []
                cache.put("quotes", uk, rows)
    out = []
    for preset in PRESET_SCREENERS:
        picked = _sort_rows(_apply_filters(rows, preset["filters"]), "pct", 2)[:3]
        out.append({**preset,
                    "top": [{"symbol": r["symbol"], "name": str(r.get("name") or "")[:22],
                             "pct": r.get("pct")} for r in picked]})
    return {"available": True, "presets": out, "universe_rows": len(rows)}


@app.post("/api/screener/refresh")
def screener_refresh(market: str = "US"):
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
        "payload": {"market": market},
        "idempotency_key": f"universe-refresh:{market}:{uuid.uuid4()}",
    }, prefer="return=representation")
    job = row if isinstance(row, dict) else (row or [{}])[0]
    return {"queued": True, "job_id": job.get("id")}


@app.post("/api/watchlist/{symbol}")
def watchlist_add(symbol: str):
    """Star a ticker in the portal: upsert into the owner's default watchlist."""
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
              {"watchlist_id": wid, "ticker_id": tid, "active": True})
    return {"saved": True, "symbol": sym}


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
    runs = db.select("runs", {"order": "created_at.desc", "limit": "500"},
                     "cost_usd,prompt_tokens,completion_tokens")
    spend = {"runs": len(runs),
             "cost_usd": round(sum(float(r.get("cost_usd") or 0) for r in runs), 4),
             "tokens_in": sum(int(r.get("prompt_tokens") or 0) for r in runs),
             "tokens_out": sum(int(r.get("completion_tokens") or 0) for r in runs)}
    return {"framework": "tradingagents 0.5.1", "markets": ["US", "HK", "ASX"],
            "vendors": {"live": "moomoo", "fallback": "yfinance", "fundamentals": "sec_edgar+yfinance",
                        "news": "yfinance+fmp", "macro": "fred", "prediction": "polymarket"},
            "stock_page": {"fixtures_mode": bool(os.getenv("TA_STOCK_FIXTURES")),
                           "info_page": "/#/info"},
            "stub_mode": SETTINGS.stub_mode, "spend": spend}


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

_KLINE_WINDOWS = {"5D": ("candles:5D", 6, 8), "D": ("candles:D", 2, 380),
                  "W": ("candles:W", 3, 1500), "M": ("candles:M", 4, 2500),
                  "Q": ("candles:Q", 2, 105), "Y": ("candles:Y", 2, 380)}
_SESSION_KINDS = {"FULL", "NORMAL", "PREMARKET", "AFTERHOURS"}
_NEWS_TYPES = {"news": 1, "notice": 2, "report": 3}


def _stock_code(symbol: str) -> str:
    s = symbol.strip().upper()
    if s.endswith("-US"):
        s = s[:-3]
    return s if "." in s else f"US.{s}"


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
def stock_candles(symbol: str, range: str = "D"):
    if range not in _KLINE_WINDOWS:
        raise HTTPException(400, "range must be one of " + ",".join(_KLINE_WINDOWS))
    key, ktype, days = _KLINE_WINDOWS[range]
    start = (date.today() - timedelta(days=days)).isoformat()

    def fetch(c):
        return {"kline_list": c.history_kline(_stock_code(symbol), start,
                                              date.today().isoformat(), ktype=ktype)}

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
