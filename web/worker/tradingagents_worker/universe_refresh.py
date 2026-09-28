"""Full-market universe loader for the screener.

Enumerates every listing via moomoo's plate endpoints (plate-list → plate-stock
per industry plate, ≤1000/page with next_key), upserts screener_universe, then
snapshot-enriches every code in 400-code batches into screener_quotes — the
normalized rows /api/screener serves whole-market mode from. Progress goes to
job_events when run as a queued job (manual refresh button), or to stdout when
run as the hourly/daily cron.

Rate limits: every call goes through the client's MinuteBudget (30/min per path
template); template-level RateLimited raises are retried with the server's
Retry-After, and HTTP-200 rate_limited responses are retried inside call().
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

from .config import SETTINGS
from .db import Db
from .moomoo import MoomooClient, RateLimited

ENUM_TTL_H = 24  # re-enumerate plates once a day; quotes refresh every run


def _budgeted(fn, *args, **kwargs):
    """Run a client call, sleeping through template-level rate-limit refusals."""
    while True:
        try:
            return fn(*args, **kwargs)
        except RateLimited as e:
            print(f"[universe] rate-limited on {e}; sleeping {e.retry_after:.0f}s", flush=True)
            time.sleep(max(e.retry_after, 1.0))


class UniverseRefresher:
    def __init__(self, db: Db, client: MoomooClient, market: str = "US",
                 emit=None):
        self.db = db
        self.client = client
        self.market = market
        self.emit = emit or (lambda *a, **k: None)

    # ── enumeration ───────────────────────────────────────────────────────
    def _plates_for(self, cls: str) -> list[dict]:
        out = _budgeted(self.client.call, "GET", "/quote/plate-list",
                        query={"market": self.market, "plate_class": cls})
        return out.get("plate_list") or []  # verified live: top-level plate_list

    def _plate_codes(self, plate_code: str) -> list[str]:
        codes: list[str] = []
        next_key = ""
        for _ in range(10):  # 10 pages x 1000 = plenty for any plate
            q = {"market": self.market, "plate_code": plate_code, "limit": 1000}
            if next_key:
                q["next_key"] = next_key
            out = _budgeted(self.client.call, "GET", "/quote/plate-stock", query=q)
            items = out.get("stock_list") or []  # verified live: top-level stock_list
            codes.extend(it.get("code") for it in items if it.get("code"))
            pag = (out.get("pagination") or {}) if isinstance(out, dict) else {}
            next_key = pag.get("next_key") or ""
            if not next_key or next_key == "-1" or not items:
                break
        return codes

    # enum values verified live: simple_field 1 → 1=HK 2=US 3=BJ; sort ids
    # 2301=market_cap, 2201=price, 2210=pct_change (values x1000)
    SLICES = [(2301, 2), (2301, 1), (2201, 2), (2201, 1), (2210, 2), (2210, 1)]

    def enumerate_universe(self) -> dict:
        seen: dict[str, str] = {}
        plate_total = 0
        for cls in ("INDUSTRY", "CONCEPT", "OTHER"):
            plates = _budgeted(self._plates_for, cls)
            plate_total += len(plates)
            self.emit("universe", "progress",
                      f"plates {cls.lower()} {len(plates)} · {len(seen)} stocks so far")
            for i, p in enumerate(plates, 1):
                pcode = p.get("code") or ""
                pname = p.get("plate_name") or p.get("name") or ""
                if not pcode:
                    continue
                try:
                    codes = _budgeted(self._plate_codes, pcode)
                except Exception as e:
                    print(f"[universe] plate {pcode} failed: {e}", flush=True)
                    continue
                for c in codes:
                    seen.setdefault(c, pname)
                if i % 25 == 0:
                    self.emit("universe", "progress",
                              f"plates {cls.lower()} {i}/{len(plates)} · {len(seen)} stocks so far")
        # screen-slice union: the tail plates miss (OTC, ETFs, warrants, fresh IPOs)
        sl = 0
        for sort_id, direction in self.SLICES:
            sl += 1
            try:
                out = _budgeted(self.client.call, "POST", "/quote/stock-screen", body={
                    "limit": 300,
                    "screen_queries": [{"simple_field_query": {"simple_field": 1,
                        "screen_value_list": [{"US": 2, "HK": 1}.get(self.market, 2)]}}],
                    "sort": {"direction": direction, "simple_property": {"name": sort_id}}})
                for it in (out.get("items") or []):
                    c = it.get("code")
                    if c:
                        seen.setdefault(c, "screen-slice")
                self.emit("universe", "progress",
                          f"slice {sl}/{len(self.SLICES)} · {len(seen)} stocks so far")
            except Exception as e:
                print(f"[universe] slice {sort_id}/{direction} failed: {e}", flush=True)
        rows = [{"market": self.market, "code": c, "name": None, "plate": plate}
                for c, plate in seen.items()]
        self.db.upsert_many("screener_universe", "market,code", rows)
        return {"plates": plate_total, "slices": len(self.SLICES), "codes": len(rows)}

    # ── quotes ────────────────────────────────────────────────────────────
    def _stored_codes(self) -> list[str]:
        rows = self.db.select_all("screener_universe", {"market": f"eq.{self.market}"}, "code")
        return [r["code"] for r in rows]

    def refresh_quotes(self) -> dict:
        from .screener_rows import snapshot_to_row  # shared normalizer
        codes = self._stored_codes()
        if not codes:
            return {"quotes": 0}
        batches = [codes[i:i + 400] for i in range(0, len(codes), 400)]
        now = datetime.now(timezone.utc).isoformat()
        written = 0
        for i, batch in enumerate(batches, 1):
            snap = _budgeted(self.client.snapshot, batch) or {}
            qrows = [{"code": s.get("code"), "market": self.market,
                      "row": snapshot_to_row(s), "updated_at": now}
                     for s in (snap.get("snapshot_list") or []) if s.get("code")]
            written += self.db.upsert_many("screener_quotes", "code", qrows)
            self.emit("universe", "progress", f"quotes batch {i}/{len(batches)} · {written} rows")
        return {"quotes": written, "batches": len(batches)}

    def run(self, force_enum: bool = False) -> dict:
        out: dict = {"market": self.market, "started_at": datetime.now(timezone.utc).isoformat()}
        state = self._universe_state()
        need_enum = force_enum or not self._stored_codes() or self._enum_age_h(state) >= ENUM_TTL_H
        interval_h = float(state.get("interval_h") or 1)
        fresh = self._quotes_age_h(state) < interval_h
        if fresh and not need_enum and not force_enum:
            out["skipped"] = (f"quotes fresh ({self._quotes_age_h(state):.1f}h < "
                              f"{interval_h:g}h interval) — nothing to do")
            self.emit("universe", "done", out["skipped"])
            return out
        if need_enum:
            out["enum"] = self.enumerate_universe()
            state = {**state, "last_enum": out["started_at"]}
        out["quotes"] = self.refresh_quotes()
        state["last_quotes"] = datetime.now(timezone.utc).isoformat()
        state["last_result"] = {k: v for k, v in out.items() if k != "started_at"}
        self.db.upsert("app_settings", "key", {"key": "universe_state", "value": state})
        out["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.emit("universe", "done", f"universe refresh complete: {out['quotes'].get('quotes')} quotes")
        return out

    # ── state helpers ─────────────────────────────────────────────────────
    def _universe_state(self) -> dict:
        rows = self.db.select("app_settings", {"key": "eq.universe_state"}, "value")
        return (rows[0].get("value") or {}) if rows else {}

    def _quotes_age_h(self, state: dict) -> float:
        raw = state.get("last_quotes")
        if not raw:
            return 1e9
        try:
            then = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - then).total_seconds() / 3600
        except ValueError:
            return 1e9

    def _enum_age_h(self, state: dict) -> float:
        raw = state.get("last_enum")
        if not raw:
            return 1e9
        try:
            then = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return (datetime.now(timezone.utc) - then).total_seconds() / 3600
        except ValueError:
            return 1e9


def main(market: str = "US"):
    """Cron entry: python -m tradingagents_worker.universe_refresh."""
    if not SETTINGS.moomoo_appkey or not SETTINGS.moomoo_private_key:
        raise SystemExit("MOOMOO keys not configured")
    db = Db()
    client = MoomooClient(SETTINGS.moomoo_appkey, SETTINGS.moomoo_private_key)
    out = UniverseRefresher(db, client, market).run()
    print(f"[universe] done: {out}", flush=True)


if __name__ == "__main__":
    main(os.getenv("UNIVERSE_MARKET", "US"))
