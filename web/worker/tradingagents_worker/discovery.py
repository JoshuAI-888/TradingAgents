"""Discovery engine (Market Pulse trigger feed): screens + news + calendar +
macro → deduped, scored candidates. ~7 moomoo calls per sweep (budget-aware).
Nothing auto-runs; candidates are surfaced for one-click analysis.
"""
from __future__ import annotations

from datetime import datetime, timezone

from .db import Db
from .moomoo import MoomooClient, MoomooError
from .ttl_cache import TtlCache

SECTOR_ETFS = ["US.SPY", "US.QQQ", "US.IWM", "US.XLK", "US.XLC", "US.XLY", "US.XLF",
               "US.XLV", "US.XLI", "US.XLP", "US.XLU", "US.XLRE", "US.XLE", "US.XLB", "US.VIXY"]


def sweep(db: Db, mm: MoomooClient | None, cache: TtlCache, watchlist: list[str] | None = None) -> list[dict]:
    candidates: list[dict] = []
    if mm is not None:
        candidates += _screen_candidates(mm, cache)
        candidates += _news_candidates(mm, cache)
        candidates += _calendar_candidates(mm, cache)
    candidates += _watchlist_candidates(db, watchlist or [])
    stored = []
    for c in candidates:
        try:
            rows = db.insert("discovery_candidates", c, prefer="return=representation")
            if rows:
                stored.append(rows if isinstance(rows, dict) else rows[0])
        except Exception:
            continue  # dedup violation → already known
    return stored


def market_state(mm: MoomooClient, cache: TtlCache) -> list[dict]:
    k = cache.key("quotes", "sector-state")
    hit, _ = cache.wrap("quotes", k)
    if hit:
        return hit
    snap = mm.snapshot(SECTOR_ETFS)
    items = (snap or {}).get("snapshot_list", [])
    out = []
    for it in items:
        code = it.get("code", "")
        out.append({"symbol": code.split(".")[-1], "last": it.get("last_price"),
                    "pct": it.get("pct_change"), "ts": it.get("update_time")})
    cache.put("quotes", k, out)
    return out


def _screen_candidates(mm: MoomooClient, cache: TtlCache) -> list[dict]:
    # stock-screen is verified live (2026-09-27): it works, and the market enum
    # is 1=HK 2=US with 2201=price×1000. But a true "movers" screen needs the
    # pct_change property id, discoverable only during a live US session — the
    # unsorted default order returns SPAC/warrant noise. Disabled until that id
    # is verified; the news + watchlist sources still feed candidates.
    return []


def _news_candidates(mm: MoomooClient, cache: TtlCache) -> list[dict]:
    k = cache.key("news", "find-news-latest")
    hit, _ = cache.wrap("news", k)
    items = hit if hit else mm.find_news("stock market", sort_type=2, limit=20)
    if not hit:
        cache.put("news", k, items)
    out = []
    for n in items[:6]:
        title = n.get("title", "")[:120]
        out.append({
            "trigger_type": "news", "symbol": None, "market": None,
            "title": f"News: {title}",
            "reason": "Headline from the news sweep — check whether it moves a watchlist name or opens a new candidate.",
            "score": 55,
            "sources": [{"vendor": "moomoo", "endpoint": "/quote/find-news", "url": n.get("url"),
                         "published_at": n.get("publish_time")}],
        })
    return out


def _calendar_candidates(mm: MoomooClient, cache: TtlCache) -> list[dict]:
    k = cache.key("other", "econ-calendar")
    hit, _ = cache.wrap("other", k)
    items = hit if hit else mm.econ_calendar_hot()
    if not hit:
        cache.put("other", k, items)
    out = []
    for ev in items[:4]:
        out.append({
            "trigger_type": "macro", "symbol": None, "market": None,
            "title": f"Macro: {ev.get('title', ev.get('event_name', 'event'))}",
            "reason": "Scheduled macro release — queue a post-print watchlist sweep; >consensus shifts multiples.",
            "score": 60,
            "sources": [{"vendor": "moomoo", "endpoint": "/quote/economic-calendar/hot"}],
        })
    return out


def _watchlist_candidates(db: Db, watchlist: list[str]) -> list[dict]:
    if not watchlist:
        return []
    return [{
        "trigger_type": "watchlist", "symbol": None, "market": None,
        "title": f"Nightly sweep: {len(watchlist)} tickers",
        "reason": "Scheduled re-underwrite of " + ", ".join(watchlist[:6]) + ".",
        "score": 50, "sources": [{"vendor": "cron"}],
    }]


def sweep_due(now: datetime | None = None) -> bool:
    """Market-hours 15-min gate; UTC for cron simplicity."""
    now = now or datetime.now(timezone.utc)
    return now.minute % 15 == 0
