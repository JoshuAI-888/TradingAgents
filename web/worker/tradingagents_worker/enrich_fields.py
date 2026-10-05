"""Screener-enrichment field registry: the single source of truth for which
fields exist, where they come from (moo/calc/yf), and how raw vendor values
become our units. The nightly job writes exactly these keys; /api/screener's
src=moo|yf switch reads YF_ONLY_FIELDS to decide availability (spec §5b).

Transforms (yfinance raw → ours):
  pct            ratio → percent (×100)
  pct_of_float   shortPercentOfFloat ratio → percent
  unix_date      epoch seconds → ISO date string
  div_price      price ÷ per-share ingredient (legacy helper; not used by fetcher)
  div_mcap_flow  market cap ÷ aggregate cash or free cash flow
  best_effort_lt_de {"lt","eq"} dict → ratio; None leg → None (no fake data)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

# Corrections must not reinterpret pre-correction cached values as current units.
YF_FIELD_CONTRACTS = {
    "payout_ratio": "ratio_to_percent_v1",
    "pcf": "market_cap_over_total_cash_same_currency_v1",
    "pfcf": "market_cap_over_free_cashflow_same_currency_v1",
    "lt_debt_eq": "nonnegative_long_term_debt_over_positive_equity_percent_v1",
    "total_debt_eq": "provider_debt_to_equity_nonnegative_percent_v1",
}


def finite_number(value):
    """Finite vendor numbers only, including zero; reject bool/coercion/overflow."""
    if type(value) not in (int, float):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (OverflowError, ValueError):
        return None


# yfinance Ticker.info key → (our key, transform, is-best-effort)
YF_FIELDS: dict[str, tuple[str, str | None]] = {
    "forwardPE": ("forward_pe", None),
    "trailingPegRatio": ("peg", None),
    "priceToSalesTrailing12Months": ("ps", None),
    # Aggregate cash avoids a per-share basis mismatch across share classes.
    "totalCash": ("pcf", "div_mcap_flow"),
    "freeCashflow": ("pfcf", "div_mcap_flow"),
    "enterpriseValue": ("ev", None),
    "enterpriseToEbitda": ("ev_ebitda", None),
    "enterpriseToRevenue": ("ev_sales", None),
    "returnOnAssets": ("roa", "pct"),
    "currentRatio": ("current_ratio", None),
    "quickRatio": ("quick_ratio", None),
    "longTermDebt": ("_lt_de", "best_effort_lt_de"),
    "debtToEquity": (
        "total_debt_eq",
        "nonnegative",
    ),  # provider percent; not a derived total-debt ratio
    "sharesShort": ("shares_short", None),
    "shortPercentOfFloat": ("short_float", "pct_of_float"),
    "heldPercentInstitutions": ("inst_own", "pct"),
    "heldPercentInsiders": ("insider_own", "pct"),
    "beta": ("beta", None),
    "targetMeanPrice": ("target_price", None),
    "recommendationMean": ("analyst_recom", None),  # 1=strong buy … 5=sell
    "country": ("country", None),
    "fullTimeEmployees": ("employees", None),
    "earningsTimestamp": ("earnings_date", "unix_date"),
    "exDividendDate": ("ex_div_date", "unix_date"),
    "payoutRatio": ("payout_ratio", "pct"),
    "returnOnEquity": ("roe", "pct"),
    "grossMargins": ("gross_margin", "pct"),
    "operatingMargins": ("operating_margin", "pct"),
    "profitMargins": ("net_margin", "pct"),
    "revenueGrowth": ("revenue_growth", "pct"),
    "earningsGrowth": ("eps_growth", "pct"),
    "sector": ("sector", None),
    "industry": ("industry", None),
    "website": ("website", None),
}

# Computed from stored moomoo daily klines (available in BOTH modes).
TECH_FIELDS = [
    "perf_w",
    "perf_m",
    "perf_q",
    "perf_h",
    "perf_y",
    "perf_ytd",
    "vol_w",
    "vol_m",
    "sma20_pos",
    "sma50_pos",
    "sma200_pos",
    "rsi14",
    "atr14",
    "avg_vol3m",
    "rel_vol",
    "pos_52w",
]

# Carried by the moomoo snapshot already — present in both modes.
MOO_FREE_FIELDS = ["pe_ttm", "pb", "div_yield", "pct", "market_cap", "volume"]

FIELD_LABELS = {
    "forward_pe": "Fwd P/E",
    "peg": "PEG",
    "ps": "P/S",
    "pcf": "P/C",
    "pfcf": "P/FCF",
    "ev": "Enterprise Value",
    "ev_ebitda": "EV/EBITDA",
    "ev_sales": "EV/Sales",
    "roa": "ROA %",
    "current_ratio": "Current Ratio",
    "quick_ratio": "Quick Ratio",
    "lt_debt_eq": "LT Debt/Equity %",
    "total_debt_eq": "Total Debt/Equity %",
    "shares_short": "Shares Short",
    "short_float": "Short Float %",
    "inst_own": "Inst. Own %",
    "insider_own": "Insider Own %",
    "beta": "Beta",
    "target_price": "Target Price",
    "analyst_recom": "Analyst Recom.",
    "country": "Country",
    "employees": "Employees",
    "earnings_date": "Earnings Date",
    "ex_div_date": "Div Ex-Date",
    "payout_ratio": "Payout Ratio",
    "sector": "Sector",
    "industry": "Industry",
    "website": "Website",
    "roe": "ROE %",
    "gross_margin": "Gross Margin %",
    "operating_margin": "Operating Margin %",
    "net_margin": "Net Margin %",
    "revenue_growth": "Revenue Growth %",
    "eps_growth": "EPS Growth %",
    **{k: k.replace("_", " ").title() for k in TECH_FIELDS},
    **{k: k for k in MOO_FREE_FIELDS},
}

FIELD_SOURCE = {
    **{v[0]: "yf" for v in YF_FIELDS.values() if not v[0].startswith("_")},
    **dict.fromkeys(TECH_FIELDS, "calc"),
    **dict.fromkeys(MOO_FREE_FIELDS, "moo"),
}

# Everything yfinance-served, hidden in strict moo mode (spec §5b rule 1).
YF_ONLY_FIELDS = {v[0] for v in YF_FIELDS.values() if not v[0].startswith("_")} - set(
    MOO_FREE_FIELDS
)


def _unix_date(ts) -> str | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def apply_transform(
    raw, transform: str | None, price: float | None = None, market_cap: float | None = None
):
    if raw is None or isinstance(raw, bool):
        return None
    if transform is None:
        return raw
    if transform == "nonnegative":
        number = finite_number(raw)
        return number if number is not None and number >= 0 else None
    if transform in ("pct", "pct_of_float"):
        number = finite_number(raw)
        result = finite_number(number * 100) if number is not None else None
        return round(result, 4) if result is not None else None
    if transform == "unix_date":
        return _unix_date(raw) if finite_number(raw) is not None else None
    if transform in ("div_price", "div_mcap_flow"):
        numerator = finite_number(price if transform == "div_price" else market_cap)
        denominator = finite_number(raw)
        if numerator is None or denominator is None or numerator <= 0 or denominator <= 0:
            return None
        result = finite_number(numerator / denominator)
        return round(result, 4) if result is not None else None
    if transform == "best_effort_lt_de":
        if not isinstance(raw, dict):
            return None
        eq, lt = finite_number(raw.get("eq")), finite_number(raw.get("lt"))
        if eq is None or eq <= 0 or lt is None or lt < 0:
            return None
        result = finite_number(lt / eq * 100)
        return round(result, 4) if result is not None else None
    raise ValueError(f"unknown transform {transform!r}")
