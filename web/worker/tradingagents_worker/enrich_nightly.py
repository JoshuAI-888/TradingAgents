"""Nightly enrichment orchestrator (cron: after the last US-hours universe
refresh — spec §5b rule 3 keeps both stores on the same trading day).

Per run: (1) moomoo kline rotation slice (default ~1,400 codes), (2) yfinance
batch over the whole US universe, (3) technicals per code from its stored
bars — only for codes whose klines are fresh (KLINE_TTL_DAYS), capped at the
2,000 most-stale fresh codes per run (steady state ≈ the nightly rotation
slice); bars are read per code-chunk via PostgREST in.() filters, never the
whole table. Stale klines mean the technicals keys are absent — never
recomputed from old bars, never zero-filled (spec rule).
Writes one screener_enrichment row per code; state lands in app_settings.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from .config import SETTINGS
from .db import Db
from .kline_backfill import KLINE_TTL_DAYS, KlineBackfill
from .moomoo import MoomooClient
from .technicals import compute
from .yf_enrich import fetch_yf_enrichment

FRESH_CAP_PER_RUN = 2000
BAR_CHUNK = 100


def _parse(raw):
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


class EnrichNightly:
    def __init__(self, db: Db, yf_fetch=None, market: str = "US", emit=None):
        self.db = db
        self.market = market
        self.emit = emit or (lambda *a, **k: None)
        self._yf_fetch = yf_fetch or fetch_yf_enrichment

    def _universe_codes(self) -> list[str]:
        rows = self.db.select_all("screener_universe", {"market": f"eq.{self.market}"}, "code")
        return [r["code"] for r in rows if r.get("code")]

    def _client(self):
        return MoomooClient(SETTINGS.moomoo_appkey, SETTINGS.moomoo_private_key)

    def _state(self) -> dict:
        rows = self.db.select("app_settings", {"key": "eq.enrich_state"}, "value")
        return (rows[0].get("value") or {}) if rows else {}

    def _fresh_codes(self, codes: list[str]) -> list[str]:
        """Fresh-kline codes, most-stale first, capped per run (docstring)."""
        kstate = {r["code"]: r for r in self.db.select_all(
            "screener_kline_state", {"market": f"eq.{self.market}"}, "code,last_fetch")}
        cutoff = datetime.now(timezone.utc) - timedelta(days=KLINE_TTL_DAYS)
        fresh = []
        for c in codes:
            ts = _parse((kstate.get(c) or {}).get("last_fetch"))
            if ts is not None and ts >= cutoff:
                fresh.append((ts, c))
        fresh.sort()  # oldest fetch first = most stale of the fresh
        return [c for _, c in fresh[:FRESH_CAP_PER_RUN]]

    def _bars_for(self, codes: list[str]) -> dict[str, list]:
        bars: dict[str, list] = {}
        for i in range(0, len(codes), BAR_CHUNK):
            chunk = codes[i:i + BAR_CHUNK]
            if not chunk:
                continue
            rows = self.db.select_all(
                "screener_klines",
                {"market": f"eq.{self.market}", "code": f"in.({','.join(chunk)})"})
            for b in rows:
                bars.setdefault(b["code"], []).append(b)
        for code in bars:
            bars[code].sort(key=lambda b: b["day"])
        return bars

    def run(self, run_klines: bool = True) -> dict:
        out: dict = {"market": self.market,
                     "started_at": datetime.now(timezone.utc).isoformat()}
        codes = self._universe_codes()
        if not codes:
            out["skipped"] = "no stored universe — run the universe loader first"
            self.emit("enrich", "done", out["skipped"])
            return out
        state = self._state()

        if run_klines:
            kb = KlineBackfill(self.db, self._client(), self.market, self.emit)
            out["klines"] = kb.backfill(kb.stale_codes())

        prices = {r["code"]: (r.get("row") or {}).get("price")
                  for r in self.db.select_all("screener_quotes", {"market": f"eq.{self.market}"},
                                              "code,row")}
        prices = {k: v for k, v in prices.items() if v}
        yf_rows = self._yf_fetch(codes, prices, market=self.market) or []
        by_code = {r["code"]: dict(r.get("data") or {}) for r in yf_rows}

        fresh_codes = self._fresh_codes(codes)
        bars_by_code = self._bars_for(fresh_codes) if fresh_codes else {}

        now = datetime.now(timezone.utc).isoformat()
        upserts = []
        for code in codes:
            data = dict(by_code.get(code) or {})
            bars = bars_by_code.get(code)
            if bars:
                data.update(compute(bars))
            if not data:
                continue
            upserts.append({"market": self.market, "code": code, "data": data,
                            "source": "yfinance+computed", "as_of": now})
        for i in range(0, len(upserts), 400):
            self.db.upsert_many("screener_enrichment", "market,code",
                                upserts[i:i + 400])
            self.emit("enrich", "progress", f"enriched {min(i + 400, len(upserts))}/{len(upserts)}")

        out["enriched"] = len(upserts)
        out["finished_at"] = datetime.now(timezone.utc).isoformat()
        state.update({"last_run": out["finished_at"],
                      "last_result": {k: v for k, v in out.items()
                                      if k not in ("started_at", "finished_at")}})
        self.db.upsert("app_settings", "key", {"key": "enrich_state", "value": state})
        self.emit("enrich", "done", f"enrichment complete: {out['enriched']} rows")
        return out


def main(market: str = "US"):
    if not SETTINGS.moomoo_appkey or not SETTINGS.moomoo_private_key:
        raise SystemExit("MOOMOO keys not configured")
    db = Db()
    out = EnrichNightly(db, market=market).run()
    print(f"[enrich] done: {out}", flush=True)


if __name__ == "__main__":
    main(os.getenv("ENRICH_MARKET", "US"))
