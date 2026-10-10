"""Compute technicals from full provider history, retaining a bounded raw cache.

Published STOCK membership drives a daily, 4,000-code rotation. Each
symbol's history is computed in memory and discarded; only selected cache
members may persist their newest 260 bars through server-side admission.
Kline-state freshness records computation, including uncached symbols.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from .current_universe import current_codes
from .db import Db
from .moomoo import MoomooClient, RateLimited
from .technicals import append_snapshot_bar, compute

KLINE_YEARS = 3
KLINE_TTL_DAYS = 1
ROTATION_LIMIT_DEFAULT = 4000


def _budgeted(fn, *args, **kwargs):
    while True:
        try:
            return fn(*args, **kwargs)
        except RateLimited as e:
            print(f"[klines] rate-limited on {e}; sleeping {e.retry_after:.0f}s", flush=True)
            time.sleep(max(e.retry_after, 1.0))


def _first(b: dict, *keys):
    """Live history-kline uses open/close/high/low/volume; older payloads used
    *_price names — accept both, first present wins (None-aware)."""
    for k in keys:
        v = b.get(k)
        if v is not None:
            return v
    return None


def _bar_day(b: dict) -> str | None:
    """Bar date: moomoo sends time_key as epoch MILLISECONDS (recorded live);
    tolerate epoch seconds and ISO/ISO-like strings. Returns YYYY-MM-DD."""
    raw = b.get("day") or b.get("time_key") or b.get("date")
    if raw is None:
        return None
    if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.strip().isdigit()):
        v = float(raw)
        if v > 1e11:  # epoch ms (13 digits) → seconds
            v /= 1000.0
        return datetime.fromtimestamp(v, tz=timezone.utc).date().isoformat()
    return str(raw).strip()[:10]


def _parse(raw) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


class KlineBackfill:
    def __init__(self, db: Db, client: MoomooClient, market: str = "US", emit=None):
        self.db = db
        self.client = client
        self.market = market
        self.emit = emit or (lambda *a, **k: None)

    def stale_codes(self, limit: int = ROTATION_LIMIT_DEFAULT, codes=None) -> list[str]:
        """Codes never fetched (first) or with last_fetch older than
        KLINE_TTL_DAYS, in universe order, capped at `limit`."""
        rows = self.db.select_all(
            "screener_kline_state",
            {"market": f"eq.{self.market}", "order": "code.asc"},
            "code,last_fetch",
        )
        cutoff = datetime.now(timezone.utc) - timedelta(days=KLINE_TTL_DAYS)
        fresh: set[str] = set()
        last_fetch = {}
        for r in rows:
            ts = _parse(r.get("last_fetch"))
            if ts is not None and ts.tzinfo is None:
                ts = None
            last_fetch[r["code"]] = ts
            if ts is not None and ts >= cutoff:
                fresh.add(r["code"])

        universe = codes if codes is not None else current_codes(self.db, self.market)
        ordered = [code for code in universe if code not in fresh]  # never-fetched + stale
        ordered.sort(
            key=lambda code: (
                last_fetch.get(code) or datetime.min.replace(tzinfo=timezone.utc),
                code,
            )
        )
        return ordered[:limit]

    def backfill(self, codes: list[str], quotes=None, on_technical=None) -> dict:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=int(KLINE_YEARS * 365.25))
        written_bars = errors = fetched_bars = 0
        technicals = {}
        cache_codes = {
            r["code"]
            for r in self.db.select(
                "rpc/screener_kline_cache_members", {"market": f"eq.{self.market}"}, "code"
            )
        }
        for i, code in enumerate(codes, 1):
            try:
                out = _budgeted(
                    self.client.call,
                    "GET",
                    f"/quote/{code}/history-kline",
                    query={
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "ktype": 2,
                        "autype": 1,
                        "count": 1000,
                    },
                )
                kl = out.get("kline_list") if isinstance(out, dict) else []
            except Exception as e:
                print(f"[klines] {code} failed: {e}", flush=True)
                errors += 1
                continue
            rows = []
            for b in kl or []:
                day = _bar_day(b)
                if not day:
                    continue
                rows.append(
                    {
                        "market": self.market,
                        "code": code,
                        "day": day,
                        "o": _first(b, "open_price", "open"),
                        "h": _first(b, "high_price", "high"),
                        "l": _first(b, "low_price", "low"),
                        "c": _first(b, "close_price", "close", "last_close"),
                        "v": _first(b, "volume"),
                    }
                )
            # Compute before discarding history. Only the selected working set
            # is cached; all other symbols keep derived metrics and freshness.
            rows = sorted({r["day"]: r for r in rows}.values(), key=lambda r: r["day"])
            fetched_bars += len(rows)
            if rows:
                bars = (
                    append_snapshot_bar(rows, (quotes or {})[code])
                    if (quotes or {}).get(code)
                    else rows
                )
                technicals[code] = compute(bars)
                if on_technical is not None:
                    on_technical(code, technicals[code])
                retained = [
                    r
                    for r in rows
                    if (end - timedelta(days=550)).isoformat() <= r["day"] <= end.isoformat()
                ][-260:]
                if code in cache_codes and retained:
                    saved = self.db._call(
                        "POST",
                        "rpc/screener_kline_cache_write",
                        body={"p_market": self.market, "p_code": code, "p_rows": retained},
                    )
                    if type(saved) is not int or not 0 <= saved <= 260:
                        raise ValueError("Invalid kline cache receipt")
                    written_bars += saved
            self.db.upsert(
                "screener_kline_state",
                "market,code",
                {
                    "market": self.market,
                    "code": code,
                    "last_fetch": datetime.now(timezone.utc).isoformat(),
                    "bars": len(rows),
                },
            )
            if i % 50 == 0:
                self.emit("enrich", "progress", f"klines {i}/{len(codes)} · {written_bars} bars")
        return {
            "codes": len(codes) - errors,
            "bars": written_bars,
            "fetched_bars": fetched_bars,
            "errors": errors,
            "technicals": technicals,
        }
