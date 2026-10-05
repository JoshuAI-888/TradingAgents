"""Bounded subtype-only acquisition; no fundamentals, prices or bars are emitted.

Returns cache updates for a durable adapter to publish. Retrieval timestamps are
local receipts, never vendor effective dates. Failed attempts retain aged evidence.
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone

from .provider_context import info_context, validated_context
from .yf_enrich import to_yahoo_symbol

VERSION = "instrument_subtype_cache_v1"
COHORT_CAP = 20000
BATCH_CAP = 100
TTL_SECONDS = 7 * 86400
RETRY_SECONDS = 86400


class SubtypeRateLimited(RuntimeError):
    """Provider explicitly denied additional requests; remaining work is deferred."""


def _age(value, now):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        age = (now - stamp).total_seconds()
        return age if stamp.tzinfo is not None and age >= 0 else None
    except (AttributeError, ValueError, TypeError, OverflowError):
        return None


def _cache(record, code, now):
    if record is None:
        return None
    if (
        not isinstance(record, dict)
        or set(record) != {"version", "code", "context", "retrieved_at", "attempted_at", "status"}
        or record.get("version") != VERSION
        or record.get("code") != code
    ):
        raise ValueError("Invalid subtype cache identity or shape")
    if _age(record["attempted_at"], now) is None or record["status"] not in (
        "success",
        "unavailable",
        "identity_mismatch",
        "invalid_subtype",
    ):
        raise ValueError("Invalid subtype attempt")
    context, stamp = record["context"], record["retrieved_at"]
    if context is None:
        if stamp is not None or record["status"] == "success":
            raise ValueError("Invalid absent subtype evidence")
    else:
        age = _age(stamp, now)
        # Validate old evidence at its original receipt, rather than pretending
        # that a failed refresh makes the old response fresh again.
        if age is None or _age(record["attempted_at"], now) > age:
            raise ValueError("Invalid subtype receipt chronology")
        receipt = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        if (
            validated_context(context, code, stamp, receipt) is None
            or "quoteType" not in context["fields"]
        ):
            raise ValueError("Invalid subtype evidence")
        if record["status"] == "success" and stamp != record["attempted_at"]:
            raise ValueError("Successful subtype attempt must retain its receipt")
    return deepcopy(record)


def qualified_context(record, code, now=None):
    now = now or datetime.now(timezone.utc)
    record = _cache(record, code, now)
    if record is None or record["context"] is None:
        return None
    valid = validated_context(record["context"], code, record["retrieved_at"], now)
    return {"provider_context": valid, "fundamentals_at": record["retrieved_at"]} if valid else None


def collect(metadata, cache=None, fetch_info=None, now=None, limit=BATCH_CAP, should_stop=None):
    """Oldest-attempt-first trust/fund slice; exact canonical/Yahoo identity.

    A caller persists updates independently of quote publication. This function
    does not enable normalized classes or accept incomplete market coverage.
    """
    fixed_clock = now is not None
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or type(limit) is not int or not 1 <= limit <= BATCH_CAP:
        raise ValueError("Invalid subtype collection clock or bound")
    if not isinstance(metadata, list) or not 0 < len(metadata) <= COHORT_CAP:
        raise ValueError("Invalid subtype cohort")
    cache = {} if cache is None else cache
    if not isinstance(cache, dict) or len(cache) > COHORT_CAP:
        raise ValueError("Invalid subtype cache bound")
    symbols, seen, candidates = {}, set(), []
    for row in metadata:
        code = row.get("code") if isinstance(row, dict) else None
        symbol = to_yahoo_symbol(code, code.split(".", 1)[0]) if isinstance(code, str) else ""
        if not symbol or code in seen:
            raise ValueError("Invalid or duplicate subtype cohort identity")
        seen.add(code)
        symbols[code] = symbol
        record = _cache(cache.get(code), code, now)
        if row.get("provider_stock_type") != "ETF":
            continue
        if record and qualified_context(record, code, now):
            continue
        age = _age(record["attempted_at"], now) if record else None
        if age is not None and age < RETRY_SECONDS:
            continue
        candidates.append((-(age if age is not None else float("inf")), code, record))
    aliases = Counter(symbols.values())
    if any(count > 1 for count in aliases.values()):
        raise ValueError("Ambiguous Yahoo subtype alias")
    if fetch_info is None:
        import yfinance as yf

        def fetch_info(symbol):
            return yf.Ticker(symbol).get_info()

    updates = {}
    stop_reason = None
    for _, code, prior in sorted(candidates)[:limit]:
        if should_stop is not None and should_stop():
            break
        status, context = "unavailable", None
        try:
            info = fetch_info(symbols[code])
            if isinstance(info, dict) and info.get("symbol") != symbols[code]:
                status = "identity_mismatch"
            elif isinstance(info, dict):
                # Only identity/type evidence enters this cache. Do not attach
                # currencies, financial periods or unrelated financial fields.
                context = info_context(
                    {"symbol": info.get("symbol"), "quoteType": info.get("quoteType")}, code, now
                )
                status = (
                    "success" if context and "quoteType" in context["fields"] else "invalid_subtype"
                )
        except SubtypeRateLimited:
            stop_reason = "provider_rate_limited"
        except Exception:
            pass  # no provider exception text, secrets or inferred classification
        stamp = (now if fixed_clock else datetime.now(timezone.utc)).isoformat()
        updates[code] = {
            "version": VERSION,
            "code": code,
            "context": context if status == "success" else deepcopy((prior or {}).get("context")),
            "retrieved_at": stamp if status == "success" else (prior or {}).get("retrieved_at"),
            "attempted_at": stamp,
            "status": status,
        }
        if stop_reason is not None:
            break
    return {
        "updates": updates,
        "eligible": len(candidates),
        "attempted": len(updates),
        "remaining": max(0, len(candidates) - len(updates)),
        "scope": "bounded_raw_provider_trust_fund_subtypes",
        "clock": "retrieval",
        "stop_reason": stop_reason,
    }
