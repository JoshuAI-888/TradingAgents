"""Compare exact recorded definitions and bounded rows, without claiming full coverage."""

import collections
import json
import math
import urllib.parse
from datetime import datetime
from pathlib import Path

from tradingagents_api.main import PRESET_SCREENERS
from tradingagents_worker.provider_context import info_context, validated_context

ROOT = Path(__file__).parent
x = json.loads((ROOT / "deployed-probe.json").read_text())
local = {p["key"]: p for p in PRESET_SCREENERS}
definitions = x["definitions"].get("payload", {}).get("presets", [])
assert len(definitions) == 22 and {p["key"] for p in definitions} == set(local)
for p in definitions:
    assert all(p.get(k) == local[p["key"]].get(k) for k in ("filters", "sort", "direction")), p[
        "key"
    ]
results = []
for e in x["executions"]:
    key = urllib.parse.parse_qs(urllib.parse.urlsplit(e["url"]).query)["key"][0]
    p = e.get("payload", {})
    rows = p.get("rows", [])
    finite = [
        r["pct"] for r in rows if type(r.get("pct")) in (int, float) and math.isfinite(r["pct"])
    ]
    results.append(
        {
            "key": key,
            "name": local[key]["name"],
            "available": p.get("available"),
            "pending": p.get("pending"),
            "provider_total": p.get("provider_total"),
            "retrieved_first_page": len(rows),
            "raw_classification_counts": dict(
                collections.Counter(r.get("stock_type", "UNKNOWN") for r in rows)
            ),
            "possibly_truncated": p.get("possibly_truncated"),
            "next_key_present": bool(p.get("next_key")),
            "pct_desc_inversions": sum(a < b for a, b in zip(finite, finite[1:], strict=False)),
            "retrieved_at": p.get("retrieved_at"),
            "canonical_duplicates": len(rows) - len({r.get("code") for r in rows}),
        }
    )
source = json.loads((ROOT / "classification-probe.json").read_text())
now = datetime.fromisoformat(source["captured_at"])
samples = []
for r in source["records"]:
    context = info_context(r["raw_selected"], r["code"], now)
    assert context and validated_context(context, r["code"], source["captured_at"], now) == context
    occurrences = [
        p["key"]
        for e in x["executions"]
        if (p := e["payload"]).get("key")
        and any(
            row.get("code") == r["code"] and row.get("stock_type") == "ETF"
            for row in p.get("rows", [])
        )
    ]
    samples.append(
        {
            "code": r["code"],
            "same_response_quote_type": context["fields"].get("quoteType"),
            "provider_context": context,
            "deployed_provider_ETF_occurrences": occurrences,
        }
    )
default = x["default"]["payload"]
cap = [
    r.get("market_cap")
    for r in default["rows"]
    if type(r.get("market_cap")) in (int, float) and math.isfinite(r["market_cap"])
]
result = {
    "verified_at": now.isoformat(),
    "definition_contracts_unchanged": 22,
    "preset_results": results,
    "default": {
        "declared_matched": default["matched"],
        "retrieved": len(default["rows"]),
        "source_universe_at": default.get("universe_as_of"),
        "stock_classification_only": all(r.get("stock_type") == "STOCK" for r in default["rows"]),
        "cap_desc_inversions": sum(a < b for a, b in zip(cap, cap[1:], strict=False)),
        "scope": "bounded first page of older deployed release; no immutable generation pin",
    },
    "same_response_classification_samples": samples,
    "moomoo_public_page_result": "403 operations too frequent; no fresh page counts or like-for-like membership reconciliation",
    "acceptance": "R02/R14 remain open; broad provider ETF trust/fund category is not verified ETF subtype; no stock-type override performed",
}
(ROOT / "verification.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
print(
    json.dumps(
        {
            "preserved_definitions": 22,
            "available": sum(p["available"] is True for p in results),
            "pending": [p["key"] for p in results if not p["available"]],
            "presets_with_raw_ETF_category": sum(
                p["raw_classification_counts"].get("ETF", 0) > 0 for p in results
            ),
            "default": result["default"],
        }
    )
)
