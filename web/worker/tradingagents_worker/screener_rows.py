"""Shared screener row normalizer: moomoo snapshot item → the flat row the
screener API and the universe loader both use. Lives worker-side because the
API imports worker modules (never the reverse).
"""
from __future__ import annotations


def snapshot_to_row(s: dict) -> dict:
    """A moomoo snapshot item → a screener row with normalized fields."""
    last, prev = s.get("last_price"), s.get("prev_close_price")
    pct = s.get("pct_change")
    if pct is None and last is not None and prev:
        pct = (float(last) - float(prev)) / float(prev) * 100
    return {
        "symbol": (s.get("code") or "").split(".")[-1],
        "code": s.get("code"),
        "name": s.get("name") or s.get("sc_name") or "",
        "price": last,
        "pct": None if pct is None else round(float(pct), 2),
        "chg": None if (last is None or prev is None) else round(float(last) - float(prev), 3),
        "market_cap": s.get("total_market_val"),
        "float_cap": s.get("circular_market_val"),
        "shares": s.get("outstanding_shares"),
        "volume": s.get("volume"),
        "turnover": s.get("turnover"),
        "turnover_rate": s.get("turnover_rate"),
        "volume_ratio": s.get("volume_ratio"),
        "pe": s.get("pe_ratio") or None,
        "pe_ttm": s.get("pe_ttm_ratio") or None,
        "pb": s.get("pb_ratio") or None,
        "div_yield": s.get("dividend_ratio_ttm") or None,
        "div_ttm": s.get("dividend_ttm") or None,
        "eps": s.get("earning_per_share") or None,
        "amplitude": s.get("amplitude"),
        "bid_ask_ratio": s.get("bid_ask_ratio"),
        "high52": s.get("highest52weeks_price"),
        "low52": s.get("lowest52weeks_price"),
        "new_high": bool(s.get("highest52weeks_price") and last
                         and float(last) >= float(s["highest52weeks_price"]) * 0.999),
        "new_low": bool(s.get("lowest52weeks_price") and last
                        and float(last) <= float(s["lowest52weeks_price"]) * 1.001),
    }
