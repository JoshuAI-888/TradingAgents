"""Stored-universe loader for the screener.

Collects observed listings via moomoo's plate endpoints (plate-list → plate-stock
per industry plate, ≤1000/page with next_key), upserts screener_universe, then
snapshot-enriches every code in 400-code batches into screener_quotes — the
normalized rows /api/screener serves stored-universe mode from. The union does
not prove complete exchange coverage; failed traversals are not successes. Progress goes to
job_events when run as a queued job (manual refresh button), or to stdout when
run as the hourly/daily cron.

Rate limits: every call goes through the client's MinuteBudget (30/min per path
template); template-level RateLimited raises are retried with the server's
Retry-After, and HTTP-200 rate_limited responses are retried inside call().
"""
from __future__ import annotations

import os
import re
import hashlib
import time
from datetime import datetime, timezone

from .config import SETTINGS
from .db import Db
from .moomoo import MoomooClient, RateLimited

ENUM_TTL_H = 24  # re-enumerate plates once a day; quotes refresh every run
UNIVERSE_CAP = 20000


class UniverseRefreshError(ValueError):
    """A bounded provider/cohort validation failed; no successful refresh claim."""


def cohort_fingerprint(codes: list[str]) -> str:
    return hashlib.sha256('\n'.join(sorted(codes)).encode()).hexdigest()


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
        if market not in ('US', 'HK'):
            raise UniverseRefreshError('Unsupported universe market')
        self.market = market
        self.emit = emit or (lambda *a, **k: None)

    # ── enumeration ───────────────────────────────────────────────────────
    def _plates_for(self, cls: str) -> list[dict]:
        out = _budgeted(self.client.call, "GET", "/quote/plate-list",
                        query={"market": self.market, "plate_class": cls})
        items = out.get('plate_list') if isinstance(out, dict) else None
        if not isinstance(items, list) or any(not isinstance(p, dict) or
                not isinstance(p.get('code'), str) or not p['code'] for p in items):
            raise UniverseRefreshError('Invalid plate-list response')
        return items

    def _plate_codes(self, plate_code: str) -> list[str]:
        codes: list[str] = []
        next_key = ""
        visited = set()
        for _ in range(10):  # qualified page bound; reaching it with a cursor is failure
            q = {"market": self.market, "plate_code": plate_code, "limit": 1000}
            if next_key:
                q["next_key"] = next_key
            out = _budgeted(self.client.call, "GET", "/quote/plate-stock", query=q)
            items = out.get('stock_list') if isinstance(out, dict) else None
            if not isinstance(items, list) or len(items) > 1000 or any(not isinstance(it, dict) or
                    not isinstance(it.get('code'), str) or not re.fullmatch(
                        self.market + r'\.[A-Z0-9][A-Z0-9._-]{0,30}', it['code']) for it in items):
                raise UniverseRefreshError('Invalid plate-stock identities or response')
            page_codes = [it['code'] for it in items]
            if len(set(page_codes)) != len(page_codes) or set(page_codes).intersection(codes):
                raise UniverseRefreshError('Repeated plate-stock identities across pages')
            codes.extend(page_codes)
            pag = out.get('pagination')
            if pag is None:
                pag = {}
            if not isinstance(pag, dict):
                raise UniverseRefreshError('Invalid plate-stock pagination')
            next_key = pag.get("next_key")
            if next_key in (None, '', '-1'):
                return codes
            if not isinstance(next_key, str) or next_key in visited or not items:
                raise UniverseRefreshError('Plate-stock cursor did not advance')
            visited.add(next_key)
        raise UniverseRefreshError('Plate-stock paging limit reached before exhaustion')

    # enum values verified live: simple_field 1 → 1=HK 2=US 3=BJ; sort ids
    # 2301=market_cap, 2201=price, 2210=pct_change (values x1000)
    SLICES = [(2301, 2), (2301, 1), (2201, 2), (2201, 1), (2210, 2), (2210, 1)]

    def enumerate_universe(self) -> dict:
        seen: dict[str, list[str]] = {}
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
                codes = _budgeted(self._plate_codes, pcode)
                for c in codes:
                    seen.setdefault(c, [])
                    if pname not in seen[c]:
                        seen[c].append(pname)
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
                items = out.get('items') if isinstance(out, dict) else None
                if not isinstance(items, list) or len(items) > 300 or any(not isinstance(it, dict) or
                        not isinstance(it.get('code'), str) for it in items):
                    raise UniverseRefreshError('Invalid universe slice response')
                for it in items:
                    c = it.get("code")
                    if c:
                        seen.setdefault(c, [])
                        if "screen-slice" not in seen[c]:
                            seen[c].append("screen-slice")
                self.emit("universe", "progress",
                          f"slice {sl}/{len(self.SLICES)} · {len(seen)} stocks so far")
            except Exception as e:
                raise UniverseRefreshError(f'Universe slice {sort_id}/{direction} failed') from e
        rows = [{"market": self.market, "code": c, "name": None,
                 "plate": plates[0] if plates else None, "plates": plates}
                for c, plates in seen.items()]
        if not rows or len(rows) > UNIVERSE_CAP:
            raise UniverseRefreshError('Enumerated universe is empty or exceeds qualified limit')
        if any(not re.fullmatch(self.market + r'\.[A-Z0-9][A-Z0-9._-]{0,30}', r['code']) for r in rows):
            raise UniverseRefreshError('Enumerated universe contains invalid identities')
        # security classification for the multi-select filters (stock_type/exchange):
        # /quote/stock-basicinfo, 400 codes per call, rate-budgeted
        codes = [r["code"] for r in rows]
        for i in range(0, len(codes), 400):
            batch = codes[i:i + 400]
            try:
                out = _budgeted(self.client.call, "POST", "/quote/stock-basicinfo",
                                body={"code_list": batch})
            except Exception as e:
                raise UniverseRefreshError(f'Universe classification batch {i // 400 + 1} failed') from e
            items = out.get('basic_list') if isinstance(out, dict) else None
            if not isinstance(items, list) or any(not isinstance(b, dict) or b.get('code') not in batch
                    or not isinstance(b.get('stock_type'), str) or not b['stock_type'] for b in items):
                raise UniverseRefreshError('Invalid classification response or identity')
            info = {b['code']: b for b in items}
            if len(info) != len(items) or set(info) != set(batch):
                raise UniverseRefreshError('Missing or duplicate classification identities')
            for row in rows[i:i + 400]:
                row.update({k: info[row['code']].get(k) for k in ('stock_type', 'exchange')})
            if (i // 400) % 5 == 0:
                self.emit("universe", "progress",
                          f"classification {min(i + 400, len(codes))}/{len(codes)}")
        count = self.db.upsert_many("screener_universe", "market,code", rows)
        if count != len(rows):
            raise UniverseRefreshError('Incomplete universe storage acknowledgement')
        return {"plates": plate_total, "slices": len(self.SLICES), "codes": len(rows),
                'scope': 'observed_plate_and_screen_slice_union'}

    # ── quotes ────────────────────────────────────────────────────────────
    def _stored_codes(self) -> list[str]:
        rows = self.db.select_all("screener_universe", {"market": f"eq.{self.market}",
                                  "order": "code.asc"}, "code", cap=UNIVERSE_CAP + 1)
        if len(rows) > UNIVERSE_CAP:
            raise UniverseRefreshError('Stored universe exceeds qualified refresh limit')
        codes = [r.get('code') for r in rows]
        if any(not isinstance(c, str) or not re.fullmatch(self.market + r'\.[A-Z0-9][A-Z0-9._-]{0,30}', c)
               for c in codes) or len(set(codes)) != len(codes):
            raise UniverseRefreshError('Stored universe has invalid or duplicate identities')
        return codes

    def refresh_quotes(self) -> dict:
        from .screener_rows import snapshot_to_row  # shared normalizer
        codes = self._stored_codes()
        if not codes:
            raise UniverseRefreshError('Stored universe is empty; refresh completeness is unknown')
        batches = [codes[i:i + 400] for i in range(0, len(codes), 400)]
        written = 0
        for i, batch in enumerate(batches, 1):
            snap = _budgeted(self.client.snapshot, batch)
            items = snap.get('snapshot_list') if isinstance(snap, dict) else None
            if not isinstance(items, list) or any(not isinstance(s, dict) for s in items):
                raise UniverseRefreshError(f'Quote batch {i}: invalid response shape')
            received = [s.get('code') for s in items]
            if any(not isinstance(c, str) or c not in batch for c in received):
                raise UniverseRefreshError(f'Quote batch {i}: unrequested or invalid identity')
            if len(set(received)) != len(received):
                raise UniverseRefreshError(f'Quote batch {i}: duplicate identities')
            missing = len(set(batch) - set(received))
            if missing:
                raise UniverseRefreshError(f'Quote batch {i}: {missing} requested identities missing')
            now = datetime.now(timezone.utc).isoformat()
            qrows = [{"code": s.get("code"), "market": self.market,
                      "row": snapshot_to_row(s), "updated_at": now}
                     for s in items]
            count = self.db.upsert_many("screener_quotes", "code", qrows)
            if count != len(batch):
                raise UniverseRefreshError(f'Quote batch {i}: incomplete storage acknowledgement')
            written += count
            self.emit("universe", "progress", f"quotes batch {i}/{len(batches)} · {written} rows")
        return {"quotes": written, "batches": len(batches), 'requested': len(codes),
                'cohort_fingerprint': cohort_fingerprint(codes),
                'scope': 'requested_stored_universe'}

    def run(self, force_enum: bool = False) -> dict:
        out: dict = {"market": self.market, "started_at": datetime.now(timezone.utc).isoformat()}
        state = self._universe_state()
        stage = 'cohort_validation'
        try:
            stored_codes = self._stored_codes()
            need_enum = force_enum or not stored_codes or self._enum_age_h(state) >= ENUM_TTL_H
            interval_h = float(state.get("interval_h") or 1)
            fresh = self._quotes_age_h(state) < interval_h
            prior_quotes = (state.get('last_result') or {}).get('quotes') or {}
            same_cohort = prior_quotes.get('cohort_fingerprint') == cohort_fingerprint(stored_codes)
            if fresh and same_cohort and not need_enum and not force_enum and (state.get('last_attempt') or {}).get('status') != 'failed':
                out["skipped"] = (f"quotes fresh ({self._quotes_age_h(state):.1f}h < "
                                  f"{interval_h:g}h interval) — nothing to do")
                self.emit("universe", "done", out["skipped"])
                return out
            stage = 'enumeration' if need_enum else 'quotes'
            if need_enum:
                out["enum"] = self.enumerate_universe()
                state = {**state, "last_enum": datetime.now(timezone.utc).isoformat()}
            stage = 'quotes'
            out["quotes"] = self.refresh_quotes()
        except Exception as error:
            # A prior batch may have landed. Its cache clock is still accurate,
            # but this run must not advance whole-market last-success freshness.
            state['last_attempt'] = {'started_at': out['started_at'],
                'finished_at': datetime.now(timezone.utc).isoformat(), 'status': 'failed',
                'stage': stage, 'reason': str(error) if isinstance(error, UniverseRefreshError)
                else f'{stage} failed ({type(error).__name__})'}
            self._save_state(state)
            self.emit('universe', 'failed', state['last_attempt']['reason'])
            raise
        state["last_quotes"] = datetime.now(timezone.utc).isoformat()
        state["last_result"] = {k: v for k, v in out.items() if k != "started_at"}
        state['last_attempt'] = {'started_at': out['started_at'],
            'finished_at': state['last_quotes'], 'status': 'succeeded', 'stage': 'quotes'}
        self._save_state(state)
        out["finished_at"] = datetime.now(timezone.utc).isoformat()
        self.emit("universe", "done", f"universe refresh complete: {out['quotes'].get('quotes')} quotes")
        return out

    # ── state helpers ─────────────────────────────────────────────────────
    def _universe_state(self) -> dict:
        rows = self.db.select("app_settings", {"key": f"eq.universe_state_{self.market}"}, "value")
        state = dict((rows[0].get("value") or {}) if rows else {})
        settings = self.db.select("app_settings", {"key": "eq.universe_state"}, "value")
        # Legacy shared clocks cannot prove either market's freshness. Preserve
        # its configured cadence only; each market earns a new success clock.
        config = (settings[0].get('value') or {}) if settings else {}
        state['interval_h'] = config.get('interval_h') or 1
        return state

    def _save_state(self, state: dict):
        self.db.upsert('app_settings', 'key', {'key': f'universe_state_{self.market}',
                                              'value': state})

    def _quotes_age_h(self, state: dict) -> float:
        raw = state.get("last_quotes")
        if not raw:
            return 1e9
        try:
            then = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - then).total_seconds() / 3600
            return age if age >= 0 else 1e9
        except (ValueError, TypeError, OverflowError):
            return 1e9

    def _enum_age_h(self, state: dict) -> float:
        raw = state.get("last_enum")
        if not raw:
            return 1e9
        try:
            then = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            age = (datetime.now(timezone.utc) - then).total_seconds() / 3600
            return age if age >= 0 else 1e9
        except (ValueError, TypeError, OverflowError):
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
