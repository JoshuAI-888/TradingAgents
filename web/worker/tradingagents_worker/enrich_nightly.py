"""Enrich the current published stock cohort with fundamentals and technicals.

The provider-history rotation computes in memory, preserving full-history
indicator semantics without transferring bars into and back out of Supabase.
Only derived metrics and a bounded selected raw cache persist. Quote projections
are fetched once per run; legacy run_klines=False supports cached recomputation.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from .config import SETTINGS
from .current_universe import current_codes
from .db import Db
from .enrich_fields import TECH_FIELDS, YF_FIELD_CONTRACTS, YF_ONLY_FIELDS
from .kline_backfill import KLINE_TTL_DAYS, KlineBackfill
from .moomoo import MoomooClient
from .technicals import append_snapshot_bar, compute
from .yf_enrich import fetch_yf_enrichment

FRESH_CAP_PER_RUN = 4000  # = the kline rotation slice: technicals compute the night klines land
BAR_CHUNK = 100
YF_BATCH_PER_RUN = 6000  # bound the cron: full coverage in ~3 nights, then weekly refresh
YF_TTL_DAYS = 7  # fundamentals are slow; weekly yf refresh per code


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
        return current_codes(self.db, self.market)

    def _client(self):
        return MoomooClient(SETTINGS.moomoo_appkey, SETTINGS.moomoo_private_key)

    def _state(self) -> dict:
        rows = self.db.select("app_settings", {"key": "eq.enrich_state"}, "value")
        return (rows[0].get("value") or {}) if rows else {}

    def _fresh_codes(self, codes: list[str]) -> list[str]:
        """Fresh-kline codes, most-stale first, capped per run (docstring)."""
        kstate = {
            r["code"]: r
            for r in self.db.select_all(
                "screener_kline_state", {"market": f"eq.{self.market}"}, "code,last_fetch"
            )
        }
        cutoff = datetime.now(timezone.utc) - timedelta(days=KLINE_TTL_DAYS)
        fresh = []
        for c in codes:
            ts = _parse((kstate.get(c) or {}).get("last_fetch"))
            if ts is not None and ts >= cutoff:
                fresh.append((ts, c))
        fresh.sort()  # oldest fetch first = most stale of the fresh
        return [c for _, c in fresh[:FRESH_CAP_PER_RUN]]

    def _technical_data(self, fresh_codes: list[str], quotes: dict):
        """Stream: read bars for one BAR_CHUNK of codes, compute technicals,
        DISCARD the bars before the next chunk. Holding every fresh code's
        bars at once OOM-killed the 512MiB cron at ~3.2k codes (2026-10-01);
        a chunk is ~100 codes × ~780 bars ≈ tens of MB. Yields (code, data)."""
        for i in range(0, len(fresh_codes), BAR_CHUNK):
            chunk = fresh_codes[i : i + BAR_CHUNK]
            if not chunk:
                continue
            rows = self.db.select_all(
                "screener_klines",
                {
                    "market": f"eq.{self.market}",
                    "code": f"in.({','.join(chunk)})",
                    "order": "code.asc,day.asc",
                },
                cap=len(chunk) * 260 + 1,
            )
            by: dict[str, list] = {}
            for b in rows:
                by.setdefault(b["code"], []).append(b)
            for code in chunk:
                bars = sorted(by.get(code) or [], key=lambda b: b["day"])
                if not bars:
                    continue
                q = quotes.get(code)
                if q:
                    bars = append_snapshot_bar(bars, q)
                data = compute(bars)
                if data:
                    yield code, data

    def run(self, run_klines: bool = True) -> dict:
        out: dict = {"market": self.market, "started_at": datetime.now(timezone.utc).isoformat()}
        codes = self._universe_codes()
        if not codes:
            out["skipped"] = "no stored universe — run the universe loader first"
            self.emit("enrich", "done", out["skipped"])
            return out
        state = self._state()

        # Read each compact quote exactly once; avoid transferring observations
        # and the same complete quote cohort twice on every enrichment run.
        quotes = {}
        for i in range(0, len(codes), 400):
            for r in self.db.select_all(
                "screener_quotes",
                {
                    "market": f"eq.{self.market}",
                    "code": f"in.({','.join(codes[i : i + 400])})",
                    "order": "code.asc",
                },
                "code,updated_at,price:row->price,open:row->open,high:row->high,low:row->low,volume:row->volume,quote_observed_at:row->quote_observed_at",
            ):
                quotes[r["code"]] = r
        prices = {c: q["price"] for c, q in quotes.items() if q.get("price")}
        existing = {
            r["code"]: r
            for r in self.db.select_all(
                "screener_enrichment",
                {"market": f"eq.{self.market}", "order": "code.asc"},
                "code,data,as_of",
            )
        }

        def persist_technical(code, data):
            prior = existing.get(code) or {}
            payload = dict(prior.get("data") or {})
            meta = dict(payload.get("_meta") or {})
            # Preserve the original category clock before a technical-only
            # write changes as_of; it cannot make old fundamentals fresh.
            if not meta.get("fundamentals_at"):
                meta["fundamentals_at"] = prior.get("as_of")
            for field in TECH_FIELDS:
                payload.pop(field, None)
            payload.update(data)
            stamp = datetime.now(timezone.utc).isoformat()
            meta["technicals_at"] = stamp
            payload["_meta"] = meta
            row = {
                "market": self.market,
                "code": code,
                "data": payload,
                "source": "yfinance+computed",
                "as_of": stamp,
            }
            self.db.upsert("screener_enrichment", "market,code", row)
            existing[code] = row

        tech = {}
        if run_klines:
            kb = KlineBackfill(self.db, self._client(), self.market, self.emit)
            out["klines"] = kb.backfill(
                kb.stale_codes(codes=codes), quotes=quotes, on_technical=persist_technical
            )
            tech = out["klines"].pop("technicals", {})
        # Bound the yf sweep: missing codes first, then oldest as_of, capped.
        # A single-run full-universe sweep (13.5k Ticker.info calls) risks the
        # cron's runtime and Yahoo throttling; full coverage lands in ~5 nights
        # and later runs refresh the stalest slice.
        yf_ttl_cut = datetime.now(timezone.utc) - timedelta(days=YF_TTL_DAYS)

        def fundamental_stamp(r):
            data = r.get("data") or {}
            contracts = (data.get("_meta") or {}).get("field_contracts") or {}
            if not isinstance(contracts, dict) or any(
                data.get(k) is not None and contracts.get(k) != version
                for k, version in YF_FIELD_CONTRACTS.items()
            ):
                return None  # bounded priority refresh for legacy corrected fields
            # A technical-only update must never postpone a missing-fundamental retry.
            if not any(data.get(k) is not None for k in YF_ONLY_FIELDS):
                return None
            return _parse((data.get("_meta") or {}).get("fundamentals_at") or r.get("as_of"))

        enr_state = {c: fundamental_stamp(r) for c, r in existing.items()}

        def _enr_rank(c):
            ts = enr_state.get(c)
            return (0, datetime.min.replace(tzinfo=timezone.utc)) if ts is None else (1, ts)

        eligible = [c for c in codes if enr_state.get(c) is None or enr_state[c] < yf_ttl_cut]
        yf_codes = sorted(eligible, key=_enr_rank)[:YF_BATCH_PER_RUN]
        yf_rows = self._yf_fetch(yf_codes, prices, market=self.market) or []
        # A successful response replaces its fundamental category. Missing fields
        # must not inherit a new clock from an unrelated field or technical run.
        fundamental_fields = YF_ONLY_FIELDS | {"lt_debt_eq"}
        by_code, yf_stamps, yf_contracts, yf_contexts = {}, {}, {}, {}
        requested_codes = set(yf_codes)
        for row in yf_rows:
            if (
                not isinstance(row, dict)
                or row.get("code") not in requested_codes
                or row.get("market") != self.market
            ):
                continue
            stamp = _parse(row.get("as_of"))
            if (
                stamp is None
                or stamp.tzinfo is None
                or stamp > datetime.now(timezone.utc) + timedelta(minutes=5)
            ):
                continue
            payload = row.get("data")
            if not isinstance(payload, dict):
                continue
            by_code[row["code"]] = {
                k: v for k, v in payload.items() if k in fundamental_fields and v is not None
            }
            yf_stamps[row["code"]] = stamp.isoformat()
            from .provider_context import validated_context

            yf_contexts[row["code"]] = validated_context(row.get("provider_context"), row["code"])
            contracts = row.get("field_contracts")
            yf_contracts[row["code"]] = {
                field: version
                for field, version in YF_FIELD_CONTRACTS.items()
                if isinstance(contracts, dict) and contracts.get(field) == version
            }

        fresh_codes = self._fresh_codes(codes) if not run_klines else []
        # Freshness lift: append the current session's partial bar (from the
        # stored snapshot) to each code's history before computing technicals —
        # no extra vendor calls, technicals track the hourly quote refresh.
        if fresh_codes:
            for code, tdata in self._technical_data(fresh_codes, quotes):
                tech[code] = tdata

        now = datetime.now(timezone.utc).isoformat()
        upserts = []
        for code in codes:
            if code not in by_code and (code not in tech or run_klines):
                continue
            data = dict((existing.get(code) or {}).get("data") or {})
            meta = dict(data.get("_meta") or {})
            if not meta.get("fundamentals_at") and enr_state.get(code):
                meta["fundamentals_at"] = enr_state[code].isoformat()
            if code in by_code:
                for field in fundamental_fields:
                    data.pop(field, None)
                data.update(by_code[code])
                meta["fundamentals_at"] = yf_stamps[code]
                meta["field_contracts"] = yf_contracts[code]
                meta.pop("provider_context", None)
                if yf_contexts[code] is not None:
                    meta["provider_context"] = yf_contexts[code]
            if code in tech:
                for field in TECH_FIELDS:
                    data.pop(field, None)
                data.update(tech[code])
                if not run_klines:
                    meta["technicals_at"] = now
            data["_meta"] = meta
            upserts.append(
                {
                    "market": self.market,
                    "code": code,
                    "data": data,
                    "source": "yfinance+computed",
                    "as_of": now,
                }
            )
        for i in range(0, len(upserts), 400):
            self.db.upsert_many("screener_enrichment", "market,code", upserts[i : i + 400])
            self.emit("enrich", "progress", f"enriched {min(i + 400, len(upserts))}/{len(upserts)}")

        out["enriched"] = len(set(by_code) | set(tech))
        out["finished_at"] = datetime.now(timezone.utc).isoformat()
        state.update(
            {
                "last_run": out["finished_at"],
                "last_result": {
                    k: v for k, v in out.items() if k not in ("started_at", "finished_at")
                },
            }
        )
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
