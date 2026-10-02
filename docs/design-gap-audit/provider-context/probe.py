"""Bounded public provider probe; no database writes or private credentials."""

import json
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf
from tradingagents_worker.yf_enrich import to_yahoo_symbol

requested = ["US.AAPL", "US.KO", "HK.00700"]
keys = [
    "symbol",
    "currency",
    "financialCurrency",
    "marketCap",
    "regularMarketTime",
    "mostRecentQuarter",
    "lastFiscalYearEnd",
    "nextFiscalYearEnd",
    "forwardPE",
    "revenueGrowth",
    "earningsGrowth",
    "returnOnEquity",
    "sector",
    "industry",
    "longTermDebt",
    "totalStockholderEquity",
    "StockholdersEquity",
    "debtToEquity",
]
records = []
for code in requested:
    market = code.split(".", 1)[0]
    symbol = to_yahoo_symbol(code, market)
    try:
        info = yf.Ticker(symbol).info
        selected = {k: info.get(k) for k in keys}
        records.append(
            {
                "code": code,
                "requested_symbol": symbol,
                "identity_matches": info.get("symbol") == symbol,
                "raw_selected": selected,
            }
        )
    except Exception as error:
        records.append(
            {"code": code, "requested_symbol": symbol, "error_type": type(error).__name__}
        )
result = {
    "captured_at": datetime.now(timezone.utc).isoformat(),
    "yfinance_version": yf.__version__,
    "records": records,
    "limits": "Three public same-response info samples. General fiscal dates do not qualify individual metric periods; quote currency does not qualify another provider cap. Not full-market or Moomoo reconciliation.",
}
Path(__file__).with_name("public-probe.json").write_text(
    json.dumps(result, indent=2, allow_nan=False) + "\n"
)
print(
    json.dumps(
        {
            "samples": len(records),
            "identity_matches": sum(r.get("identity_matches", False) for r in records),
            "errors": sum("error_type" in r for r in records),
        }
    )
)
