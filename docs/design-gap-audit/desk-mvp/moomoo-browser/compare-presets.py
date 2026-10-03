"""Compare all working US preset source pages with public deployed executions."""

import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).parent
KEYS = {
    1: "high-div",
    2: "blue-chip",
    3: "buffett",
    4: "undervalued",
    5: "growth",
    6: "pb-lt-1",
    7: "best-lt-high-div",
    8: "high-pe",
    9: "good-pe",
    10: "low-pe",
    12: "junk",
    14: "blue-chip-div",
    15: "speculative",
    16: "high-eps",
    17: "high-roe",
    18: "lt-high-div",
    19: "undervalued-semi",
    20: "undervalued-tech",
    21: "undervalued-banks",
}


def compare(item):
    index, key = item
    source = json.loads((ROOT / f"preset-{index}-us.json").read_text())
    url = f"https://tradingagents-portal.onrender.com/api/screener/execute?key={key}&market=US&limit=300"
    with urlopen(url, timeout=45) as response:
        api = json.load(response)
    (ROOT / f"preset-{index}-api.json").write_text(json.dumps(api, indent=2))
    source_rows = list(source["rows"])
    for page_file in sorted(
        ROOT.glob(f"preset-{index}-us-page*.json"),
        key=lambda p: int(re.search(r"page(\d+)", p.name)[1]),
    ):
        source_rows.extend(json.loads(page_file.read_text())["rows"])
    source_codes = [
        "US." + row["href"].split("/stock/")[1].rsplit("-", 1)[0] for row in source_rows
    ]
    api_codes = [row.get("code") for row in api.get("rows", [])]
    count_match = re.search(r"Result:\s*(\d+)\s*stocks", source["text"])
    count = int(count_match[1]) if count_match else None
    complete_source = (
        count is not None and len(source_codes) == count and len(set(source_codes)) == count
    )
    complete_api = api.get("available") is True and api.get("possibly_truncated") is False
    result = {
        "key": key,
        "source_url": source["url"],
        "source_observed_at": source["observed_at"],
        "api_url": url,
        "api_retrieved_at": api.get("retrieved_at"),
        "available": api.get("available"),
        "source_declared_count": count,
        "source_captured_count": len(source_codes),
        "api_captured_count": len(api_codes),
        "api_provider_total": api.get("provider_total"),
        "api_possibly_truncated": api.get("possibly_truncated"),
        "source_complete": complete_source,
        "api_complete": complete_api,
        "same_captured_prefix": api_codes[: len(source_codes)] == source_codes,
        "source_captured_members_absent_from_api_capture": sorted(
            set(source_codes) - set(api_codes)
        ),
        "full_membership_order_match": complete_source
        and complete_api
        and source_codes == api_codes,
        "full_count_matches": complete_api and len(api_codes) == count,
        "filters": api.get("filters"),
        "sort": api.get("sort"),
        "direction": api.get("direction"),
    }
    return result


with ThreadPoolExecutor(max_workers=4) as executor:
    comparisons = list(executor.map(compare, KEYS.items()))
report = {
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "comparisons": comparisons,
    "limits": "Public deployed build; sequential source clocks. Captured pagination completes smaller screens. Four large screens retain 50 source rows and at most 300 API rows. Prefix/count matches alone do not qualify full membership. Two RSI presets remain unavailable in agreed MVP.",
}
(ROOT / "preset-comparison.json").write_text(json.dumps(report, indent=2))
for row in comparisons:
    print(
        row["key"],
        row["source_declared_count"],
        row["api_captured_count"],
        "complete"
        if row["full_membership_order_match"]
        else "prefix"
        if row["same_captured_prefix"]
        else "DIFF",
        "count-match" if row["full_count_matches"] else "count-unproven",
    )
