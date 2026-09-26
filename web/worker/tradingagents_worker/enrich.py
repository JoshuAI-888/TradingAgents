"""Post-run enrichment: persist the market context a report page needs.

After a successful run we store, for the analyzed ticker (best-effort, never
fails the run):
  * price_bars        — 1y daily OHLCV (yfinance) → chart + settlement math
  * news_items        — recent headlines with URLs → citable news panel
  * company_profiles  — identity/valuation snapshot → masthead KV
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone

from .config import SETTINGS
from .db import Db


def _log(db: Db, vendor: str, category: str, symbol: str, status: str,
         error: str | None = None, latency_ms: int | None = None):
    try:
        db.insert("data_fetch_log", {
            "vendor": vendor, "category": category, "symbol": symbol,
            "status": status, "error": (error or "")[:300] or None,
            "latency_ms": latency_ms,
        }, prefer="return=minimal")
    except Exception:
        pass


def _bars(db: Db, ticker_id: str, symbol: str, yf) -> int:
    t0 = datetime.now(timezone.utc)
    df = yf.Ticker(symbol).history(period="1y", interval="1d", auto_adjust=True)
    rows = []
    for idx, r in df.iterrows():
        try:
            rows.append({
                "ticker_id": ticker_id, "bar_date": str(idx.date()),
                "open": round(float(r["Open"]), 8), "high": round(float(r["High"]), 8),
                "low": round(float(r["Low"]), 8), "close": round(float(r["Close"]), 8),
                "volume": int(r["Volume"]) if r["Volume"] == r["Volume"] else None,
                "source": "yfinance", "adjusted": True,
            })
        except Exception:
            continue
    if rows:
        db.upsert("price_bars", "ticker_id,bar_date,source,adjusted", rows)
    dt = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    _log(db, "yfinance", "prices", symbol, "ok" if rows else "empty", latency_ms=dt)
    return len(rows)


def _news(db: Db, symbol: str, yf) -> int:
    t0 = datetime.now(timezone.utc)
    items = yf.Ticker(symbol).news or []
    stored = 0
    for n in items:
        # yfinance shape differs across versions: flat dicts (older) or
        # nested under 'content' (newer). Handle both defensively.
        c = n.get("content") if isinstance(n.get("content"), dict) else n
        title = c.get("title") or c.get("summary") or ""
        url = c.get("link") or c.get("url")
        if not url and isinstance(c.get("canonicalUrl"), dict):
            url = c["canonicalUrl"].get("url")
        if not title or not url:
            continue
        pub = (c.get("providerPublishTime") or c.get("pubDate"))
        published = datetime.now(timezone.utc)
        if isinstance(pub, (int, float)):
            published = datetime.fromtimestamp(pub, tz=timezone.utc)
        elif isinstance(pub, str):
            try:
                published = datetime.fromisoformat(pub.replace("Z", "+00:00"))
            except ValueError:
                pass
        provider = c.get("publisher")
        if isinstance(provider, dict):
            provider = provider.get("displayName")
        try:
            db.insert("news_items", {
                "source": "yfinance", "url": url,
                "url_hash": hashlib.sha256(url.encode()).hexdigest(),
                "published_at": published.isoformat(), "title": title[:300],
                "publisher": provider, "summary": (c.get("summary") or None),
                "tickers": [symbol],
            }, prefer="return=minimal")
            stored += 1
        except Exception:
            continue  # dedup violation → already known
    dt = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    _log(db, "yfinance", "news", symbol, "ok" if items else "empty", latency_ms=dt)
    return stored


_PROFILE_KEYS = ["shortName", "longName", "sector", "industry", "country", "currency",
                 "website", "marketCap", "trailingPE", "forwardPE", "trailingEps",
                 "sharesOutstanding", "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
                 "dividendYield", "beta", "averageVolume", "shortPercentOfFloat"]


def _profile(db: Db, ticker_id: str, symbol: str, yf) -> bool:
    t0 = datetime.now(timezone.utc)
    info = yf.Ticker(symbol).info or {}
    payload = {k: info[k] for k in _PROFILE_KEYS if info.get(k) is not None}
    ok = bool(payload)
    if ok:
        db.upsert("company_profiles", "ticker_id", {
            "ticker_id": ticker_id, "payload": payload,
            "as_of": datetime.now(timezone.utc).isoformat(), "source": "yfinance",
        })
    dt = int((datetime.now(timezone.utc) - t0).total_seconds() * 1000)
    _log(db, "yfinance", "fundamentals", symbol, "ok" if ok else "empty", latency_ms=dt)
    return ok


def enrich_run(db: Db, ticker: str, yf=None) -> dict:
    """Best-effort market-context persistence for the report page. Never raises."""
    out = {"bars": 0, "news": 0, "profile": False}
    try:
        if yf is None:
            import yfinance as yf  # framework dependency; lazy so stub mode never pays
        rows = db.select("tickers", {"symbol": f"eq.{ticker}"}, "id")
        ticker_id = rows[0]["id"] if rows else None
        if not ticker_id:
            return out
        out["bars"] = _bars(db, ticker_id, ticker, yf)
        out["news"] = _news(db, ticker, yf)
        out["profile"] = _profile(db, ticker_id, ticker, yf)
    except Exception as e:
        _log(db, "yfinance", "prices", ticker, "error", error=f"{type(e).__name__}: {e}")
    return out
