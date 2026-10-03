"""Three public same-response type samples through actual bounded fetch transport."""

import json
from datetime import datetime, timezone
from pathlib import Path

from tradingagents_worker.instrument_subtype_job import fetch_bounded
from tradingagents_worker.instrument_subtypes import SubtypeRateLimited
from tradingagents_worker.provider_context import info_context


def main():
    report = {
        "scope": "three_public_same_response_type_samples_not_full_market_or_moomoo_reconciliation",
        "samples": [],
    }
    for code in ["US.PLD", "US.AMT", "US.SPY"]:
        stamp = datetime.now(timezone.utc).isoformat()
        try:
            info = fetch_bounded(code[3:])
            stamp = datetime.now(timezone.utc).isoformat()
            context = info_context(info, code)
            report["samples"].append(
                {
                    "code": code,
                    "receipt_at": stamp,
                    "context": context,
                    "status": "identity_matched" if context else "unverified",
                }
            )
        except SubtypeRateLimited:
            report["samples"].append(
                {"code": code, "receipt_at": stamp, "status": "provider_rate_limited"}
            )
            break
        except Exception:
            report["samples"].append({"code": code, "receipt_at": stamp, "status": "unavailable"})
    (Path(__file__).parent / "public-provider-probe.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
