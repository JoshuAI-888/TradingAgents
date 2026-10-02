"""Qualified instrument class, retaining the original broad provider category."""

import re
from copy import deepcopy
from datetime import datetime, timezone

from .provider_context import validated_context

VERSION = "instrument_classification_v1"


def _fresh(value, now, days):
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return stamp.tzinfo is not None and 0 <= (now - stamp).total_seconds() <= days * 86400
    except (AttributeError, ValueError, TypeError, OverflowError):
        return False


def classify(code, provider_type, provider_at, context=None, context_at=None, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(code, str) or not re.fullmatch(r"(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}", code):
        raise ValueError("Invalid classification identity")
    if not isinstance(provider_type, str) or not re.fullmatch(
        r"[A-Z][A-Z0-9_]{0,31}", provider_type
    ):
        raise ValueError("Invalid provider instrument type")
    valid = validated_context(context, code, context_at, now) if context_at else None
    subtype = (valid or {}).get("fields", {}).get("quoteType")
    normalized = "UNKNOWN"
    reason = "provider_classification_stale_or_unverified"
    if _fresh(provider_at, now, 1):
        if provider_type == "STOCK":
            normalized = "STOCK"
            reason = "provider_equity"
            if subtype in ("ETF", "MUTUALFUND"):
                normalized = "UNKNOWN"
                reason = "conflicting_explicit_equity_subtype"
        elif provider_type == "ETF":
            # Provider trust/fund bucket is not an exact ETF classification.
            normalized = {"EQUITY": "STOCK", "ETF": "ETF", "MUTUALFUND": "MUTUALFUND"}.get(
                subtype, "UNKNOWN"
            )
            reason = (
                "qualified_trust_fund_subtype"
                if normalized != "UNKNOWN"
                else "trust_fund_subtype_unavailable"
            )
        elif provider_type in ("IDX", "WARRANT", "BOND", "DRVT", "FUTURE", "CRYPTO", "BWRT"):
            normalized = provider_type
            reason = "provider_non_equity"
        else:
            reason = "provider_type_unavailable"
    return {
        "version": VERSION,
        "code": code,
        "provider_type": provider_type,
        "provider_at": provider_at,
        "provider_source": "moomoo_basicinfo",
        "provider_clock": "retrieval",
        "stock_type": normalized,
        "reason": reason,
        "subtype_context": deepcopy(valid),
        "subtype_at": context_at if valid else None,
    }


def validate(record, code, at):
    if (
        not isinstance(record, dict)
        or record.get("version") != VERSION
        or record.get("code") != code
    ):
        return False
    try:
        now = datetime.fromisoformat(at.replace("Z", "+00:00"))
        if now.tzinfo is None:
            return False
        expected = classify(
            code,
            record.get("provider_type"),
            record.get("provider_at"),
            record.get("subtype_context"),
            record.get("subtype_at"),
            now,
        )
        return expected == record
    except (ValueError, TypeError, AttributeError):
        return False
