"""Explicit unavailable values and loss-aware metadata for research downloads."""

import json
import math
import re

from tradingagents_worker.enrich_fields import TECH_FIELDS, YF_ONLY_FIELDS
from tradingagents_worker.quote_observations import CURRENCY_FIELDS

TEXT_FIELDS = {"country", "sector", "industry", "website", "earnings_date", "ex_div_date"}
NUMERIC_FIELDS = (
    set(TECH_FIELDS)
    | YF_ONLY_FIELDS
    | CURRENCY_FIELDS
    | {
        "pct",
        "shares",
        "volume",
        "turnover_rate",
        "volume_ratio",
        "pe",
        "pe_ttm",
        "pb",
        "div_yield",
        "amplitude",
        "bid_ask_ratio",
        "lt_debt_eq",
        "roe_yoy",
        "net_profit_growth",
        "op_profit_growth",
        "debt_ratio",
    }
) - TEXT_FIELDS
FLAG_FIELDS = {"new_high", "new_low", "new_low_10d"}


def finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def safe_json(value):
    if type(value) in (int, float) and not finite(value):
        return {"export_unavailable": "nonfinite_number", "source_value": str(value)}
    if isinstance(value, dict):
        return {k: safe_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [safe_json(v) for v in value]
    return value


def export_row(row, columns):
    result = dict(row)
    issues = []
    for field in columns:
        value = row.get(field)
        if field in NUMERIC_FIELDS:
            if finite(value):
                continue
            result[field] = "Unavailable"
            if value is not None:
                issues.append(
                    {"field": field, "reason": "invalid_numeric", "source_value": safe_json(value)}
                )
        elif field in FLAG_FIELDS:
            valid = (
                type(value) is bool
                or finite(value)
                and value in (0, 1)
                or type(value) is str
                and value in ("0", "1")
            )
            result[field] = ("Yes" if int(value) else "No") if valid else "Unavailable"
            if value is not None and not valid:
                issues.append(
                    {"field": field, "reason": "invalid_flag", "source_value": safe_json(value)}
                )
    result["export_value_issues"] = issues
    return result


def export_text(value):
    safe = safe_json(value)
    return (
        ""
        if safe is None
        else json.dumps(safe, ensure_ascii=False, allow_nan=False)
        if isinstance(safe, (dict, list))
        else str(safe)
    )


def csv_cell(value):
    text = export_text(value)
    if isinstance(value, str) and (re.match(r"^\s*[=+@-]", text) or re.match(r"^[\t\r\n]", text)):
        text = "'" + text
    return '"' + text.replace('"', '""') + '"' if any(c in text for c in ',"\r\n') else text


def xml_text(value):
    from xml.sax.saxutils import escape

    text = export_text(value)
    # XML 1.0 forbids these characters even in CDATA/character references.
    text = re.sub(
        r"[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]", lambda m: f"\\u{ord(m[0]):04x}", text
    )
    return escape(text)
