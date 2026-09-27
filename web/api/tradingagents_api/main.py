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
from datetime import date, datetime, timezone

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from tradingagents_worker.config import SETTINGS
from tradingagents_worker.db import Db

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

PRESET_SCREENERS = [
    {"key": "penny", "page": 1, "name": "Penny Stocks", "filters": [{"field": "price", "max": 5}]},
    {"key": "high-div", "page": 1, "name": "High Dividend Stocks",
     "filters": [{"field": "div_yield", "min": 5}]},
    {"key": "blue-chip", "page": 1, "name": "Blue Chip Stocks",
     "filters": [{"field": "market_cap", "min": 5e10}]},
    {"key": "buffett", "page": 1, "name": "Warren Buffett Strategy",
     "filters": [{"field": "market_cap", "min": 1e10}, {"field": "pe_ttm", "min": 0.01, "max": 15},
                 {"field": "div_yield", "min": 1}]},
    {"key": "undervalued", "page": 1, "name": "Undervalued Stocks",
     "filters": [{"field": "pe_ttm", "min": 0.01, "max": 15}, {"field": "pb", "min": 0.01, "max": 1.5}]},
    {"key": "growth", "page": 1, "name": "Best Growth Stocks",
     "filters": [{"field": "pct", "min": 0}, {"field": "volume_ratio", "min": 1.2},
                 {"field": "pe_ttm", "min": 0.01}]},
    {"key": "pb-lt-1", "page": 1, "name": "P/B Ratio Less Than 1",
     "filters": [{"field": "pb", "min": 0.01, "max": 1}]},
    {"key": "lt-high-div", "page": 1, "name": "Best Long Term High Dividend Stocks",
     "filters": [{"field": "div_yield", "min": 3}, {"field": "market_cap", "min": 2e9}]},
    {"key": "high-pe", "page": 2, "name": "High P/E Ratio Stocks",
     "filters": [{"field": "pe_ttm", "min": 100}]},
    {"key": "good-pe", "page": 2, "name": "Good P/E Ratio Stocks",
     "filters": [{"field": "pe_ttm", "min": 5, "max": 25}]},
    {"key": "low-pe", "page": 2, "name": "Low P/E Ratio Stocks",
     "filters": [{"field": "pe_ttm", "min": 0.01, "max": 10}]},
    {"key": "rsi-30", "page": 2, "name": "Below 30 RSI Stocks",
     "filters": [{"field": "rsi14", "max": 30}]},
    {"key": "junk", "page": 2, "name": "Junk Stocks", "filters": [{"field": "price", "max": 1}]},
    {"key": "small-growth", "page": 2, "name": "Small Cap Stocks with Huge Growth Potential",
     "filters": [{"field": "market_cap", "max": 2e9}, {"field": "pct", "min": 1}]},
    {"key": "blue-chip-div", "page": 2, "name": "Blue Chip Dividend Stocks",
     "filters": [{"field": "market_cap", "min": 1e10}, {"field": "div_yield", "min": 2}]},
]


def _snapshot_to_row(s: dict) -> dict:
    """A moomoo snapshot item → a screener row with normalized fields."""
    last, prev = s.get("last_price"), s.get("prev_close_price")
    pct = s.get("pct_change")
    if pct is None and last is not None and prev:
        pct = (float(last) - float(prev)) / float(prev) * 100
    return {
        "symbol": (s.get("code") or "").split(".")[-1],
        "code": s.get("code"),
        "name": s.get("name") or s.get("sc_name") or "",
        "price": last,
        "pct": None if pct is None else round(float(pct), 2),
        "chg": None if (last is None or prev is None) else round(float(last) - float(prev), 3),
        "market_cap": s.get("total_market_val"),
        "float_cap": s.get("circular_market_val"),
        "shares": s.get("outstanding_shares"),
        "volume": s.get("volume"),
        "turnover": s.get("turnover"),
        "turnover_rate": s.get("turnover_rate"),
        "volume_ratio": s.get("volume_ratio"),
        "pe": s.get("pe_ratio") or None,
        "pe_ttm": s.get("pe_ttm_ratio") or None,
        "pb": s.get("pb_ratio") or None,
        "div_yield": s.get("dividend_ratio_ttm") or None,
        "div_ttm": s.get("dividend_ttm") or None,
        "eps": s.get("earning_per_share") or None,
        "amplitude": s.get("amplitude"),
        "bid_ask_ratio": s.get("bid_ask_ratio"),
        "high52": s.get("highest52weeks_price"),
        "low52": s.get("lowest52weeks_price"),
        "new_high": bool(s.get("highest52weeks_price") and last
                         and float(last) >= float(s["highest52weeks_price"]) * 0.999),
        "new_low": bool(s.get("lowest52weeks_price") and last
                        and float(last) <= float(s["lowest52weeks_price"]) * 1.001),
    }


def _apply_filters(rows: list[dict], filters: list[dict]) -> list[dict]:
    def keep(r: dict) -> bool:
        for f in filters or []:
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
    return [r for r in rows if keep(r)]


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


def _market_rows(market: str, sort_key: str, direction: int, client) -> list[dict]:
    """One whole-market page: stock-screen for universe+order, snapshot for fields."""
    sort_id = _SCREEN_SORT_IDS.get(sort_key, 2301)
    body = {"limit": 100,
            "screen_queries": [{"simple_field_query": {
                "simple_field": 1, "screen_value_list": [_SCREEN_MARKET_ENUM.get(market, 2)]}}],
            "sort": {"direction": direction, "simple_property": {"name": sort_id}}}
    out = client.call("POST", "/quote/stock-screen", body=body)
    items = (out.get("items") or [])[:100]
    codes = [i.get("code") for i in items if i.get("code")]
    if not codes:
        return []
    snap = (client.snapshot(codes) or {}).get("snapshot_list") or []
    order = {code: i for i, code in enumerate(codes)}
    rows = [_snapshot_to_row(s) for s in snap if s.get("code") in order]
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
             sort: str = "market_cap", direction: int = 2, limit: int = 100):
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
    if rows is None:
        if watchlist_only:
            symbols = _watchlist_symbols()
            if not symbols:
                return {"available": True, "rows": [], "universe": "watchlist", "count": 0,
                        "presets": PRESET_SCREENERS}
            snap = (client.snapshot([f"{market}.{s}" for s in symbols[:400]])
                    or {}).get("snapshot_list") or []
            rows = [_snapshot_to_row(s) for s in snap]
        else:
            try:
                rows = _market_rows(market, sort, direction, client)
            except Exception as e:
                return {"available": False, "reason": str(e)[:120], "rows": []}
        cache.put("quotes", universe_key, rows)
    rows = _apply_filters(rows, flt)
    if watchlist_only or sort not in _SCREEN_SORT_IDS:
        # Watchlist universe sorts in Python (any column); market mode keeps the
        # server-side order unless the requested column has no verified sort id.
        rows = _sort_rows(rows, sort, direction)
    rows = rows[:max(1, min(limit, 300))]
    return {"available": True, "universe": "watchlist" if watchlist_only else market,
            "rows": rows, "count": len(rows), "presets": PRESET_SCREENERS,
            "watchlist": _watchlist_symbols()}


@app.get("/api/screener/presets")
def screener_presets(market: str = "US", page: int = 0):
    """Recommended screeners (both pages) with each preset's top-3 from the
    watchlist universe — the moomoo screener rail, on our data."""
    client = _market_client()
    if client is None:
        return {"available": False, "presets": []}
    cache = _cache()
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
    out = []
    for preset in PRESET_SCREENERS:
        if page and preset["page"] != page:
            continue
        picked = _sort_rows(_apply_filters(rows, preset["filters"]), "pct", 2)[:3]
        out.append({**preset, "top": [{"symbol": r["symbol"], "name": r["name"][:22],
                                       "pct": r["pct"]} for r in picked]})
    return {"available": True, "presets": out}


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


# Static portal (built SPA) — mounted last so /api wins.
_static = os.getenv("PORTAL_STATIC_DIR", "")
if _static and os.path.isdir(_static):
    app.mount("/", StaticFiles(directory=_static, html=True), name="portal")
