"""Stored-universe loader for the screener.

Collects observed listings via moomoo's plate endpoints (plate-list → plate-stock
per industry plate, ≤1000/page with next_key), stages classification and
snapshot quotes in memory, then publishes one immutable generation under a
fenced market lease. Compatibility mirrors change in the same transaction. The union does
not prove complete exchange coverage; failed traversals are not successes. Progress goes to
job_events when run as a queued job (manual refresh button), or to stdout when
run as the hourly/daily cron.

Rate limits: every call goes through the client's MinuteBudget (30/min per path
template); template-level RateLimited raises are retried with the server's
Retry-After. Internal HTTP-200 retries are disabled here so all retry waits
remain bounded and keep the refresh lease alive.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
import time
import uuid
from datetime import datetime, timezone

from .config import SETTINGS
from .db import Db
from .moomoo import MoomooClient, RateLimited
from .screener_generations import GenerationError, aware_time, read_generation

ENUM_TTL_H = 24  # re-enumerate plates once a day; quotes refresh every run
UNIVERSE_CAP = 20000
MAX_RATE_LIMIT_WAIT_SECONDS = 900
MAX_RUN_SECONDS = 7200


class UniverseRefreshError(ValueError):
    """A bounded provider/cohort validation failed; no successful refresh claim."""


def cohort_fingerprint(codes: list[str]) -> str:
    return hashlib.sha256("\n".join(sorted(codes)).encode()).hexdigest()


class UniverseRefresher:
    def __init__(self, db: Db, client: MoomooClient, market: str = "US", emit=None):
        self.db = db
        self.client = client
        if market not in ("US", "HK"):
            raise UniverseRefreshError("Unsupported universe market")
        self.market = market
        self.emit = emit or (lambda *a, **k: None)
        self._run_id = None
        self._run_started = None

    def _renew(self):
        if self._run_id:
            if (
                self._run_started is not None
                and time.monotonic() - self._run_started > MAX_RUN_SECONDS
            ):
                raise UniverseRefreshError("Refresh exceeded the bounded run duration")
            expires = self.db.generation_rpc(
                "screener_refresh_renew", {"p_market": self.market, "p_run": self._run_id}
            )
            if aware_time(expires) <= datetime.now(timezone.utc):
                raise UniverseRefreshError("Refresh lease acknowledgement is expired")

    def _provider(self, fn, *args, **kwargs):
        waited = 0.0
        # Otherwise the client sleeps internally without renewing our lease.
        kwargs["retries"] = 0
        while True:
            self._renew()
            try:
                result = fn(*args, **kwargs)
            except RateLimited as error:
                delay = error.retry_after
                if (
                    isinstance(delay, bool)
                    or not isinstance(delay, (int, float))
                    or not math.isfinite(delay)
                    or delay < 0
                ):
                    raise UniverseRefreshError("Invalid provider retry interval") from error
                # Heartbeat while waiting rather than sleeping beyond lease expiry.
                remaining = max(delay, 1.0)
                waited += remaining
                if waited > MAX_RATE_LIMIT_WAIT_SECONDS:
                    raise UniverseRefreshError(
                        "Provider retry wait exceeded the qualified bound"
                    ) from error
                while remaining > 0:
                    self._renew()
                    step = min(remaining, 30.0)
                    time.sleep(step)
                    remaining -= step
                continue
            self._renew()  # refuse to stage a response after ownership expired
            return result

    # ── enumeration ───────────────────────────────────────────────────────
    def _plates_for(self, cls: str) -> list[dict]:
        out = self._provider(
            self.client.call,
            "GET",
            "/quote/plate-list",
            query={"market": self.market, "plate_class": cls},
        )
        items = out.get("plate_list") if isinstance(out, dict) else None
        if not isinstance(items, list) or any(
            not isinstance(p, dict) or not isinstance(p.get("code"), str) or not p["code"]
            for p in items
        ):
            raise UniverseRefreshError("Invalid plate-list response")
        return items

    def _plate_codes(self, plate_code: str) -> list[str]:
        codes: list[str] = []
        next_key = ""
        visited = set()
        for _ in range(10):  # qualified page bound; reaching it with a cursor is failure
            q = {"market": self.market, "plate_code": plate_code, "limit": 1000}
            if next_key:
                q["next_key"] = next_key
            out = self._provider(self.client.call, "GET", "/quote/plate-stock", query=q)
            items = out.get("stock_list") if isinstance(out, dict) else None
            if (
                not isinstance(items, list)
                or len(items) > 1000
                or any(
                    not isinstance(it, dict)
                    or not isinstance(it.get("code"), str)
                    or not re.fullmatch(self.market + r"\.[A-Z0-9][A-Z0-9._-]{0,30}", it["code"])
                    for it in items
                )
            ):
                raise UniverseRefreshError("Invalid plate-stock identities or response")
            page_codes = [it["code"] for it in items]
            if len(set(page_codes)) != len(page_codes) or set(page_codes).intersection(codes):
                raise UniverseRefreshError("Repeated plate-stock identities across pages")
            codes.extend(page_codes)
            pag = out.get("pagination")
            if pag is None:
                pag = {}
            if not isinstance(pag, dict):
                raise UniverseRefreshError("Invalid plate-stock pagination")
            next_key = pag.get("next_key")
            if next_key in (None, "", "-1"):
                return codes
            if not isinstance(next_key, str) or next_key in visited or not items:
                raise UniverseRefreshError("Plate-stock cursor did not advance")
            visited.add(next_key)
        raise UniverseRefreshError("Plate-stock paging limit reached before exhaustion")

    # enum values verified live: simple_field 1 → 1=HK 2=US 3=BJ; sort ids
    # 2301=market_cap, 2201=price, 2210=pct_change (values x1000)
    SLICES = [(2301, 2), (2301, 1), (2201, 2), (2201, 1), (2210, 2), (2210, 1)]

    def enumerate_universe(self) -> tuple[dict, list[dict]]:
        seen: dict[str, list[str]] = {}
        plate_total = 0
        for cls in ("INDUSTRY", "CONCEPT", "OTHER"):
            plates = self._plates_for(cls)
            plate_total += len(plates)
            self.emit(
                "universe",
                "progress",
                f"plates {cls.lower()} {len(plates)} · {len(seen)} stocks so far",
            )
            for i, p in enumerate(plates, 1):
                pcode = p.get("code") or ""
                pname = p.get("plate_name") or p.get("name") or ""
                if not pcode:
                    continue
                codes = self._plate_codes(pcode)
                for c in codes:
                    seen.setdefault(c, [])
                    if pname not in seen[c]:
                        seen[c].append(pname)
                if i % 25 == 0:
                    self.emit(
                        "universe",
                        "progress",
                        f"plates {cls.lower()} {i}/{len(plates)} · {len(seen)} stocks so far",
                    )
        # screen-slice union: the tail plates miss (OTC, ETFs, warrants, fresh IPOs)
        for sl, (sort_id, direction) in enumerate(self.SLICES, start=1):
            try:
                out = self._provider(
                    self.client.call,
                    "POST",
                    "/quote/stock-screen",
                    body={
                        "limit": 300,
                        "screen_queries": [
                            {
                                "simple_field_query": {
                                    "simple_field": 1,
                                    "screen_value_list": [{"US": 2, "HK": 1}.get(self.market, 2)],
                                }
                            }
                        ],
                        "sort": {"direction": direction, "simple_property": {"name": sort_id}},
                    },
                )
                items = out.get("items") if isinstance(out, dict) else None
                if (
                    not isinstance(items, list)
                    or len(items) > 300
                    or any(
                        not isinstance(it, dict) or not isinstance(it.get("code"), str)
                        for it in items
                    )
                ):
                    raise UniverseRefreshError("Invalid universe slice response")
                for it in items:
                    c = it.get("code")
                    if c:
                        seen.setdefault(c, [])
                        if "screen-slice" not in seen[c]:
                            seen[c].append("screen-slice")
                self.emit(
                    "universe",
                    "progress",
                    f"slice {sl}/{len(self.SLICES)} · {len(seen)} stocks so far",
                )
            except Exception as e:
                raise UniverseRefreshError(f"Universe slice {sort_id}/{direction} failed") from e
        rows = [
            {
                "market": self.market,
                "code": c,
                "name": None,
                "plate": plates[0] if plates else None,
                "plates": plates,
            }
            for c, plates in seen.items()
        ]
        if not rows or len(rows) > UNIVERSE_CAP:
            raise UniverseRefreshError("Enumerated universe is empty or exceeds qualified limit")
        if any(
            not re.fullmatch(self.market + r"\.[A-Z0-9][A-Z0-9._-]{0,30}", r["code"]) for r in rows
        ):
            raise UniverseRefreshError("Enumerated universe contains invalid identities")
        # security classification for the multi-select filters (stock_type/exchange):
        # /quote/stock-basicinfo, 400 codes per call, rate-budgeted
        codes = [r["code"] for r in rows]
        for i in range(0, len(codes), 400):
            batch = codes[i : i + 400]
            try:
                out = self._provider(
                    self.client.call, "POST", "/quote/stock-basicinfo", body={"code_list": batch}
                )
            except Exception as e:
                raise UniverseRefreshError(
                    f"Universe classification batch {i // 400 + 1} failed"
                ) from e
            items = out.get("basic_list") if isinstance(out, dict) else None
            if not isinstance(items, list) or any(
                not isinstance(b, dict)
                or b.get("code") not in batch
                or not isinstance(b.get("stock_type"), str)
                or not b["stock_type"]
                for b in items
            ):
                raise UniverseRefreshError("Invalid classification response or identity")
            info = {b["code"]: b for b in items}
            if len(info) != len(items) or set(info) != set(batch):
                raise UniverseRefreshError("Missing or duplicate classification identities")
            for row in rows[i : i + 400]:
                row.update({k: info[row["code"]].get(k) for k in ("stock_type", "exchange")})
                row.update(
                    provider_stock_type=row["stock_type"],
                    provider_classified_at=datetime.now(timezone.utc).isoformat(),
                )
            if (i // 400) % 5 == 0:
                self.emit(
                    "universe",
                    "progress",
                    f"classification {min(i + 400, len(codes))}/{len(codes)}",
                )
        return (
            {
                "plates": plate_total,
                "slices": len(self.SLICES),
                "codes": len(rows),
                "scope": "observed_plate_and_screen_slice_union",
            },
            rows,
        )

    # ── quotes ────────────────────────────────────────────────────────────
    def _stored_metadata(self, state=None) -> list[dict]:
        state = self._universe_state() if state is None else state
        if "generation_id" in state:
            header, records = read_generation(self.db, self.market, state["generation_id"])
            if aware_time(state.get("last_quotes")) != aware_time(header["published_at"]) or (
                state.get("last_result") or {}
            ).get("quotes") != header.get("result", {}).get("quotes"):
                raise GenerationError("Generation pointer does not match its successful receipt")
            return [dict(r["metadata"]) for r in records]
        rows = self.db.select_all(
            "screener_universe",
            {"market": f"eq.{self.market}", "order": "code.asc"},
            "*",
            cap=UNIVERSE_CAP + 1,
        )
        if len(rows) > UNIVERSE_CAP:
            raise UniverseRefreshError("Stored universe exceeds qualified refresh limit")
        codes = [r.get("code") for r in rows]
        if any(
            not isinstance(c, str)
            or not re.fullmatch(self.market + r"\.[A-Z0-9][A-Z0-9._-]{0,30}", c)
            for c in codes
        ) or len(set(codes)) != len(codes):
            raise UniverseRefreshError("Stored universe has invalid or duplicate identities")
        return [{**r, "market": self.market, "plates": r.get("plates") or []} for r in rows]

    def _stored_codes(self) -> list[str]:
        return [r["code"] for r in self._stored_metadata()]

    def _classification_enum_due(self, metadata):
        if os.getenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED") != "1":
            return False
        from .instrument_classification import _fresh

        # Basic-info receipt qualifies for one day. Leave the maximum bounded
        # refresh duration for enumeration/quotes before that evidence expires;
        # the later successful publication clock cannot refresh an old receipt.
        horizon = (86400 - MAX_RUN_SECONDS) / 86400
        now = datetime.now(timezone.utc)
        return any(
            not row.get("provider_stock_type")
            or not _fresh(row.get("provider_classified_at"), now, horizon)
            for row in metadata
        )

    def _classification_contexts(self):
        if os.getenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED") != "1":
            return None
        rows = self.db.select_all(
            "screener_enrichment",
            {"market": "eq." + self.market},
            "code,data",
            cap=UNIVERSE_CAP + 1,
        )
        if len(rows) > UNIVERSE_CAP:
            raise UniverseRefreshError("Classification context exceeds supported cohort")
        contexts = {}
        for r in rows:
            code = r.get("code")
            if (
                not isinstance(code, str)
                or not re.fullmatch(self.market + r"\.[A-Z0-9][A-Z0-9._-]{0,30}", code)
                or code in contexts
            ):
                raise UniverseRefreshError("Invalid or duplicate classification context identity")
            data = r.get("data") or {}
            meta = data.get("_meta") if isinstance(data, dict) else None
            contexts[code] = meta if isinstance(meta, dict) else {}
        if os.getenv("INSTRUMENT_SUBTYPE_CACHE_ENABLED") == "1":
            from .instrument_subtype_store import contexts as subtype_contexts
            from .provider_context import validated_context

            current = datetime.now(timezone.utc)
            for code, evidence in subtype_contexts(self.db, self.market, current).items():
                prior = contexts.get(code, {})
                valid = (
                    validated_context(
                        prior.get("provider_context"), code, prior.get("fundamentals_at"), current
                    )
                    if prior.get("fundamentals_at")
                    else None
                )
                if valid and datetime.fromisoformat(
                    prior["fundamentals_at"].replace("Z", "+00:00")
                ) > datetime.fromisoformat(evidence["fundamentals_at"].replace("Z", "+00:00")):
                    continue
                contexts[code] = evidence
        return contexts

    def refresh_quotes(self, metadata=None) -> tuple[dict, list[dict]]:
        """Prepare a complete quote payload; never publish a successful batch alone."""
        from .screener_rows import snapshot_to_row

        metadata = self._stored_metadata() if metadata is None else metadata
        codes = [r["code"] for r in metadata]
        if not codes or len(codes) > UNIVERSE_CAP:
            raise UniverseRefreshError(
                "Stored universe is empty or exceeds qualified refresh limit"
            )
        by_code = {r["code"]: r for r in metadata}
        classification_contexts = self._classification_contexts()
        batches = [codes[i : i + 400] for i in range(0, len(codes), 400)]
        prepared = []
        for i, batch in enumerate(batches, 1):
            snap = self._provider(self.client.snapshot, batch)
            items = snap.get("snapshot_list") if isinstance(snap, dict) else None
            if not isinstance(items, list) or any(not isinstance(s, dict) for s in items):
                raise UniverseRefreshError(f"Quote batch {i}: invalid response shape")
            received = [s.get("code") for s in items]
            if any(not isinstance(c, str) or c not in batch for c in received):
                raise UniverseRefreshError(f"Quote batch {i}: unrequested or invalid identity")
            if len(set(received)) != len(received):
                raise UniverseRefreshError(f"Quote batch {i}: duplicate identities")
            missing = len(set(batch) - set(received))
            if missing:
                raise UniverseRefreshError(
                    f"Quote batch {i}: {missing} requested identities missing"
                )
            now = datetime.now(timezone.utc).isoformat()
            for snapshot in items:
                row = snapshot_to_row(snapshot)
                meta = {
                    k: by_code[row["code"]].get(k)
                    for k in (
                        "code",
                        "market",
                        "name",
                        "plate",
                        "plates",
                        "stock_type",
                        "exchange",
                        "provider_stock_type",
                        "provider_classified_at",
                    )
                }
                meta["name"] = row.get("name") or meta["name"]
                if classification_contexts is None and meta.get("provider_stock_type"):
                    meta["stock_type"] = meta["provider_stock_type"]
                row.update({k: meta[k] for k in ("stock_type", "exchange", "plate")})
                if classification_contexts is not None:
                    from .instrument_classification import classify

                    context = classification_contexts.get(row["code"], {})
                    try:
                        classification = classify(
                            row["code"],
                            meta["provider_stock_type"],
                            meta["provider_classified_at"],
                            context.get("provider_context"),
                            context.get("fundamentals_at"),
                            datetime.fromisoformat(now),
                        )
                    except ValueError as error:
                        raise UniverseRefreshError("Invalid raw classification metadata") from error
                    meta.update(
                        stock_type=classification["stock_type"],
                        instrument_classification=classification,
                    )
                    row.update(
                        stock_type=classification["stock_type"],
                        instrument_classification=classification,
                    )
                row["concepts"] = [p for p in meta["plates"] if p != meta["plate"]]
                prepared.append(
                    {"code": row["code"], "row": row, "metadata": meta, "quote_cache_at": now}
                )
            self.emit(
                "universe",
                "progress",
                f"quotes batch {i}/{len(batches)} · {len(prepared)} rows staged",
            )
        return (
            {
                "quotes": len(prepared),
                "batches": len(batches),
                "requested": len(codes),
                "cohort_fingerprint": cohort_fingerprint(codes),
                "scope": "requested_stored_universe",
            },
            prepared,
        )

    def run(self, force_enum: bool = False) -> dict:
        state = self._universe_state()
        # A coherent immutable cohort may be reused without obtaining a write lease.
        # Legacy success clocks do not permit skipping the first generation.
        validation_error = None
        try:
            metadata = self._stored_metadata(state)
        except (UniverseRefreshError, GenerationError) as error:
            metadata, validation_error = [], error
        codes = [r["code"] for r in metadata]
        interval_h = float(state.get("interval_h") or 1)
        prior_quotes = (state.get("last_result") or {}).get("quotes") or {}
        classification_ready = not self._classification_enum_due(metadata) and all(
            bool(r.get("instrument_classification"))
            == (os.getenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED") == "1")
            for r in metadata
        )
        if (
            classification_ready
            and not force_enum
            and not validation_error
            and state.get("generation_id")
            and codes
            and self._enum_age_h(state) < ENUM_TTL_H
            and self._quotes_age_h(state) < interval_h
            and prior_quotes.get("cohort_fingerprint") == cohort_fingerprint(codes)
            and (state.get("last_attempt") or {}).get("status") == "succeeded"
        ):
            skipped = f"quotes fresh ({self._quotes_age_h(state):.1f}h < {interval_h:g}h interval) — nothing to do"
            self.emit("universe", "done", skipped)
            return {
                "market": self.market,
                "skipped": skipped,
                "generation_id": state["generation_id"],
            }
        token = str(uuid.uuid4())
        stage = "cohort_validation"
        self._run_id = token
        self._run_started = time.monotonic()
        try:
            lease = self.db.generation_rpc(
                "screener_refresh_begin", {"p_market": self.market, "p_run": token}
            )
            if (
                not isinstance(lease, dict)
                or lease.get("run_id") != token
                or lease.get("market") != self.market
            ):
                raise UniverseRefreshError("Invalid refresh lease acknowledgement")
            if aware_time(lease.get("expires_at")) <= aware_time(lease.get("started_at")):
                raise UniverseRefreshError("Refresh lease expires before its start")
            out = {"market": self.market, "started_at": lease["started_at"]}
            if lease.get("base_generation_id") != state.get("generation_id"):
                state = self._universe_state()
                metadata = self._stored_metadata(state)
                validation_error = None
                if state.get("generation_id") != lease.get("base_generation_id"):
                    raise UniverseRefreshError("Refresh base generation changed before collection")
            if validation_error:
                raise validation_error
            need_enum = (
                force_enum
                or not metadata
                or self._classification_enum_due(metadata)
                or self._enum_age_h(state) >= ENUM_TTL_H
                or any(
                    not isinstance(r.get("stock_type"), str) or not r["stock_type"]
                    for r in metadata
                )
            )
            if need_enum:
                stage = "enumeration"
                out["enum"], metadata = self.enumerate_universe()
            stage = "quotes"
            expected, prepared = self.refresh_quotes(metadata)
            stage = "publication"
            self._renew()
            receipt = self.db.generation_rpc(
                "screener_refresh_publish",
                {
                    "p_market": self.market,
                    "p_run": token,
                    "p_codes": [r["code"] for r in metadata],
                    "p_rows": prepared,
                    "p_result": {k: v for k, v in out.items() if k != "started_at"},
                    "p_enumerated": need_enum,
                },
            )
            actual_quotes = (
                receipt.get("result", {}).get("quotes")
                if isinstance(receipt, dict) and isinstance(receipt.get("result"), dict)
                else None
            )
            if (
                not isinstance(receipt, dict)
                or receipt.get("generation_id") != token
                or receipt.get("market") != self.market
                or type(receipt.get("row_count")) is not int
                or receipt.get("row_count") != len(prepared)
                or receipt.get("cohort_fingerprint") != expected["cohort_fingerprint"]
                or actual_quotes != expected
                or any(type(actual_quotes[k]) is not type(v) for k, v in expected.items())
            ):
                raise UniverseRefreshError("Invalid generation publication acknowledgement")
            aware_time(receipt.get("published_at"))
            out.update(
                {"quotes": expected, "generation_id": token, "finished_at": receipt["published_at"]}
            )
            self.emit("universe", "done", f"universe refresh complete: {len(prepared)} quotes")
            return out
        except Exception as error:
            reason = (
                str(error)[:500]
                if isinstance(error, (UniverseRefreshError, GenerationError))
                else f"{stage} failed ({type(error).__name__})"
            )
            try:
                self.db.generation_rpc(
                    "screener_refresh_abort",
                    {"p_market": self.market, "p_run": token, "p_stage": stage, "p_reason": reason},
                )
            except Exception:
                # Ownership/transport may be gone; never use an unfenced state upsert.
                self.emit(
                    "universe",
                    "progress",
                    "Failure receipt unavailable; lease expiry or next attempt will reconcile state",
                )
            self.emit("universe", "failed", reason)
            raise
        finally:
            self._run_id = None
            self._run_started = None

    # ── state helpers ─────────────────────────────────────────────────────
    def _universe_state(self) -> dict:
        rows = self.db.select("app_settings", {"key": f"eq.universe_state_{self.market}"}, "value")
        raw = rows[0].get("value") if rows else {}
        if not isinstance(raw, dict):
            raise UniverseRefreshError("Invalid stored market refresh state")
        state = dict(raw)
        settings = self.db.select("app_settings", {"key": "eq.universe_state"}, "value")
        config = (settings[0].get("value") or {}) if settings else {}
        if not isinstance(config, dict):
            raise UniverseRefreshError("Invalid refresh cadence configuration")
        state["interval_h"] = config.get("interval_h") or 1
        return state

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
