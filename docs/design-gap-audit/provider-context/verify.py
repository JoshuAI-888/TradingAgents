"""Replay the saved public samples through actual enrichment/context code."""

import json
from pathlib import Path

from tradingagents_worker.provider_context import validated_context
from tradingagents_worker.yf_enrich import fetch_yf_enrichment

root = Path(__file__).parent
probe = json.loads((root / "public-probe.json").read_text())
outputs = []
for record in probe["records"]:
    code = record["code"]
    info = record["raw_selected"]

    class Feed:
        def Tickers(self, names, info=info, record=record):
            class Ticker:
                pass

            ticker = Ticker()
            ticker.info = info

            class Batch:
                pass

            batch = Batch()
            batch.tickers = {record["requested_symbol"]: ticker}
            return batch

    fetched = fetch_yf_enrichment([code], {}, code.split(".", 1)[0], yf_module=Feed())
    assert len(fetched) == 1
    row = fetched[0]
    assert validated_context(row["provider_context"], code) == row["provider_context"]
    assert "lt_debt_eq" not in row["data"]
    outputs.append(
        {
            "code": code,
            "provider_context": row["provider_context"],
            "available_selected_factors": {
                k: row["data"][k]
                for k in (
                    "forward_pe",
                    "revenue_growth",
                    "eps_growth",
                    "roe",
                    "total_debt_eq",
                    "sector",
                    "industry",
                )
                if k in row["data"]
            },
            "lt_debt_eq": "Unavailable: same-response debt/equity inputs missing",
        }
    )
assert outputs[2]["provider_context"]["fields"]["currency"] == "HKD"
assert outputs[2]["provider_context"]["fields"]["financialCurrency"] == "CNY"
(root / "replay-verification.json").write_text(
    json.dumps(
        {
            "source": "public-probe.json",
            "outputs": outputs,
            "limits": "Same-response selected info replay only; no individual factor periods or full-market coverage established.",
        },
        indent=2,
        allow_nan=False,
    )
    + "\n"
)
print("Three public identities replayed; currencies distinct; LT debt ratio unavailable.")
