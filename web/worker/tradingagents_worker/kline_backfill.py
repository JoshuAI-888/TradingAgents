"""Daily-bar store for computed technicals. One moomoo history-kline call per
symbol (3y daily ≈ 780 bars ≤ count 1000); rate-budgeted like the universe
loader. The kline_state table drives rotation: ~1,400 codes/night at the
30/min budget → the whole ~13.5k US universe refreshes roughly every 10
nights; the first full run is a manual, resumable backfill (state rows make
re-runs pick up where the last left off)."""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

from .db import Db
from .moomoo import MoomooClient, RateLimited

KLINE_YEARS = 3
KLINE_TTL_DAYS = 7
ROTATION_LIMIT_DEFAULT = 1400


def _budgeted(fn, *args, **kwargs):
    while True:
        try:
            return fn(*args, **kwargs)
        except RateLimited as e:
            print(f"[klines] rate-limited on {e}; sleeping {e.retry_after:.0f}s", flush=True)
            time.sleep(max(e.retry_after, 1.0))


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

    def stale_codes(self, limit: int = ROTATION_LIMIT_DEFAULT) -> list[str]:
        """Codes never fetched (first) or with last_fetch older than
        KLINE_TTL_DAYS, in universe order, capped at `limit`."""
        rows = self.db.select_all("screener_kline_state", {"market": f"eq.{self.market}"},
                                  "code,last_fetch")
        cutoff = datetime.now(timezone.utc) - timedelta(days=KLINE_TTL_DAYS)
        fresh: set[str] = set()
        stale: set[str] = set()
        for r in rows:
            ts = _parse(r.get("last_fetch"))
            if ts is not None and ts >= cutoff:
                fresh.add(r["code"])
            else:
                stale.add(r["code"])
        universe = self.db.select_all("screener_universe", {"market": f"eq.{self.market}"}, "code")
        ordered = [r["code"] for r in universe
                   if r.get("code") and r["code"] not in fresh]  # never-fetched + stale
        return ordered[:limit]

    def backfill(self, codes: list[str]) -> dict:
        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=int(KLINE_YEARS * 365.25))
        written_bars = errors = 0
        now = datetime.now(timezone.utc).isoformat()
        for i, code in enumerate(codes, 1):
            try:
                out = _budgeted(self.client.call, "GET", f"/quote/{code}/history-kline",
                                query={"start": start.isoformat(), "end": end.isoformat(),
                                       "ktype": 2, "autype": 1, "count": 1000})
                kl = out.get("kline_list") if isinstance(out, dict) else []
            except Exception as e:
                print(f"[klines] {code} failed: {e}", flush=True)
                errors += 1
                continue
            rows = []
            for b in kl or []:
                day = b.get("day") or b.get("time_key")
                if not day:
                    continue
                rows.append({"market": self.market, "code": code, "day": str(day)[:10],
                             "o": b.get("open_price"), "h": b.get("high_price"),
                             "l": b.get("low_price"), "c": b.get("close_price"),
                             "v": b.get("volume")})
            if rows:
                written_bars += self.db.upsert_many("screener_klines", "market,code,day", rows)
            self.db.upsert("screener_kline_state", "market,code",
                           {"market": self.market, "code": code,
                            "last_fetch": now, "bars": len(rows)})
            if i % 50 == 0:
                self.emit("enrich", "progress", f"klines {i}/{len(codes)} · {written_bars} bars")
        return {"codes": len(codes) - errors, "bars": written_bars, "errors": errors}
