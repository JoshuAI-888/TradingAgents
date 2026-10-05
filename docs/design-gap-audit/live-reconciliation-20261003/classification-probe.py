"""Bounded same-response public classification evidence; no inferred taxonomy."""

import json
from datetime import datetime, timezone
from pathlib import Path

import yfinance as yf

records = []
for code in ["US.PLD", "US.AMT", "US.SPY", "US.AAPL"]:
    symbol = code.split(".", 1)[1]
    try:
        info = yf.Ticker(symbol).info
        records.append(
            {
                "code": code,
                "requested_symbol": symbol,
                "identity_matches": info.get("symbol") == symbol,
                "raw_selected": {
                    k: info.get(k)
                    for k in [
                        "symbol",
                        "quoteType",
                        "typeDisp",
                        "sector",
                        "industry",
                        "currency",
                        "regularMarketTime",
                        "longName",
                    ]
                },
            }
        )
    except Exception as e:
        records.append({"code": code, "error_type": type(e).__name__})
result = {
    "captured_at": datetime.now(timezone.utc).isoformat(),
    "source": "yfinance info",
    "yfinance_version": yf.__version__,
    "records": records,
    "limits": "Four bounded same-response samples. Does not classify unsampled trust/fund rows or establish full universe membership.",
}
Path(__file__).with_name("classification-probe.json").write_text(
    json.dumps(result, indent=2, allow_nan=False) + "\n"
)
print(json.dumps(result))
