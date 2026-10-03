"""Shared screener row normalizer: moomoo snapshot item → the flat row the
screener API and the universe loader both use. Lives worker-side because the
API imports worker modules (never the reverse).
"""

from __future__ import annotations

import math

from .quote_observations import cloud_snapshot_time, snapshot_observations


def _number(value):
    if type(value) not in (int, float):
        return None
    try:
        return value if math.isfinite(value) else None
    except OverflowError:
        return None


def snapshot_to_row(s: dict) -> dict:
    """A moomoo snapshot item → a screener row with normalized fields."""
    last, prev = _number(s.get("last_price")), _number(s.get("prev_close_price"))
    pct = _number(s.get("pct_change"))
    high52, low52 = _number(s.get("highest52weeks_price")), _number(s.get("lowest52weeks_price"))
    if pct is None and last is not None and prev:
        pct = (float(last) - float(prev)) / float(prev) * 100
    row = {
        "symbol": (s.get("code") or "").split(".", 1)[-1],
        "code": s.get("code"),
        "name": s.get("name") or s.get("sc_name") or "",
        "price": last,
        "pct": None if pct is None else round(float(pct), 2),
        "chg": None if (last is None or prev is None) else round(float(last) - float(prev), 3),
        "market_cap": s.get("total_market_val"),
        "float_cap": s.get("circular_market_val"),
        "shares": s.get("outstanding_shares"),
        "open": s.get("open_price"),
        "high": s.get("high_price"),
        "low": s.get("low_price"),
        "volume": s.get("volume"),
        "turnover": s.get("turnover"),
        "turnover_rate": s.get("turnover_rate"),
        "volume_ratio": s.get("volume_ratio"),
        "pe": s.get("pe_ratio"),
        "pe_ttm": s.get("pe_ttm_ratio"),
        "pb": s.get("pb_ratio"),
        "div_yield": s.get("dividend_ratio_ttm"),
        "div_ttm": s.get("dividend_ttm"),
        "eps": s.get("earning_per_share"),
        "amplitude": s.get("amplitude"),
        "bid_ask_ratio": s.get("bid_ask_ratio"),
        "high52": high52,
        "low52": low52,
        "new_high": bool(high52 and last and last >= high52 * 0.999),
        "new_low": bool(low52 and last and last <= low52 * 1.001),
    }
    for field in row.keys() - {"symbol", "code", "name", "new_high", "new_low"}:
        row[field] = _number(row[field])
    row["quote_observed_at"] = cloud_snapshot_time(s.get("update_time"))
    row["quote_time_semantics"] = "provider_snapshot_update" if row["quote_observed_at"] else None
    row["field_observations"] = snapshot_observations(s, row)
    return row
