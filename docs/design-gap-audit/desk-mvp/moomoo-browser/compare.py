"""Read public deployed pages and compare saved visible Moomoo observations."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

ROOT = Path(__file__).parent
result = {"checked_at": datetime.now(timezone.utc).isoformat(), "markets": []}
for market in ("US", "HK"):
    source = json.loads((ROOT / f"{market.lower()}-cap.json").read_text())
    query = urlencode(
        {
            "market": market,
            "watchlist_only": 0,
            "limit": 50,
            "offset": 0,
            "src": "moo",
            "sort": "market_cap",
            "direction": 2,
            "filters": json.dumps([{"field": "stock_type", "values": ["STOCK"]}]),
        }
    )
    url = "https://tradingagents-portal.onrender.com/api/screener?" + query
    with urlopen(url, timeout=45) as response:
        deployed = json.load(response)
    (ROOT / f"{market.lower()}-deployed.json").write_text(json.dumps(deployed, indent=2))
    source_codes = [
        market + "." + urlsplit(row["href"]).path.split("/stock/")[1].rsplit("-", 1)[0]
        for row in source["rows"]
    ]
    deployed_codes = [row.get("code") for row in deployed.get("rows", [])]
    count = re.search(r"Result:\s*(\d+)\s*stocks", source["text"])
    result["markets"].append(
        {
            "market": market,
            "source_url": source["url"],
            "api_url": url,
            "source_observed_at": source["observed_at"],
            "source_declared_count": int(count[1]) if count else None,
            "deployed_matched": deployed.get("matched"),
            "deployed_available": deployed.get("available"),
            "deployed_universe_as_of": deployed.get("universe_as_of"),
            "source_visible_codes": source_codes,
            "deployed_visible_codes": deployed_codes,
            "same_visible_order": source_codes == deployed_codes,
            "source_page_only_codes": [code for code in source_codes if code not in deployed_codes],
            "deployed_page_only_codes": [
                code for code in deployed_codes if code not in source_codes
            ],
        }
    )
with urlopen(
    "https://tradingagents-portal.onrender.com/api/screener/execute?key=penny&market=US&limit=300",
    timeout=45,
) as response:
    penny = json.load(response)
(ROOT / "penny-us-deployed.json").write_text(json.dumps(penny, indent=2))
source_penny = []
for page in (1, 2):
    source_penny.extend(json.loads((ROOT / f"penny-us-page{page}.json").read_text())["rows"])
source_penny_codes = [
    "US." + urlsplit(row["href"]).path.split("/stock/")[1].rsplit("-", 1)[0] for row in source_penny
]
api_penny_codes = [row.get("code") for row in penny.get("rows", [])]
api_penny_by_code = {row.get("code"): row for row in penny.get("rows", [])}
financial_checks = []
for source_row, code in zip(source_penny, source_penny_codes, strict=True):
    cells = source_row["text"].splitlines()
    api_row = api_penny_by_code.get(code, {})
    for field, index in (("net_profit_growth", 8), ("revenue_growth", 9), ("debt_ratio", 10)):
        shown = cells[index] if len(cells) > index else None
        raw = api_row.get("criterion_values", {}).get(field)
        comparable = shown is not None and shown.endswith("%") and isinstance(raw, (int, float))
        difference = abs(float(shown[:-1]) - raw) if comparable else None
        financial_checks.append(
            {
                "code": code,
                "field": field,
                "source_display": shown,
                "api_criterion_value": raw,
                "within_display_rounding": difference is not None and difference <= 0.005001,
            }
        )
(ROOT / "penny-financial-checks.json").write_text(json.dumps(financial_checks, indent=2))
result["penny_us"] = {
    "source_declared_count": 57,
    "source_captured_count": len(source_penny_codes),
    "source_unique_count": len(set(source_penny_codes)),
    "api_metadata": {k: v for k, v in penny.items() if k not in ("rows", "presets")},
    "api_captured_count": len(api_penny_codes),
    "source_only_codes": sorted(set(source_penny_codes) - set(api_penny_codes)),
    "api_only_codes": sorted(set(api_penny_codes) - set(source_penny_codes)),
    "same_order": source_penny_codes == api_penny_codes,
    "financial_display_checks": len(financial_checks),
    "financial_display_rounding_matches": sum(
        row["within_display_rounding"] for row in financial_checks
    ),
}
result["limits"] = [
    "Page-only differences do not establish whole-universe omissions.",
    "Observations are sequential, not a shared pinned source generation.",
    "Moomoo web instrument taxonomy/currency and API stock exclusion require qualification.",
    "This public deployed API is not the unmerged candidate build.",
]
(ROOT / "comparison.json").write_text(json.dumps(result, indent=2))
print(
    json.dumps(
        [
            {
                k: row[k]
                for k in (
                    "market",
                    "source_declared_count",
                    "deployed_matched",
                    "deployed_available",
                    "same_visible_order",
                )
            }
            for row in result["markets"]
        ],
        indent=2,
    )
)
