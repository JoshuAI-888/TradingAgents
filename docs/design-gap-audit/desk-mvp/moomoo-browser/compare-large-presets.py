"""Read cursor chains and audit large public source captures without hiding drift."""

import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).parent
KEYS = {6: "pb-lt-1", 8: "high-pe", 10: "low-pe", 12: "junk"}


def audit(item):
    index, key = item
    files = [ROOT / f"preset-{index}-us.json"] + sorted(
        ROOT.glob(f"preset-{index}-us-page*.json"),
        key=lambda p: int(re.search(r"page(\d+)", p.name)[1]),
    )
    source = [json.loads(p.read_text()) for p in files]
    source_counts = [int(re.search(r"Result:\s*(\d+)\s*stocks", p["text"])[1]) for p in source]
    source_codes = [
        "US." + r["href"].split("/stock/")[1].rsplit("-", 1)[0] for p in source for r in p["rows"]
    ]
    api_pages = []
    cursor = ""
    seen = set()
    failure = None
    terminal = False
    if "--offline" in sys.argv:
        attempts = json.loads((ROOT / f"preset-{index}-api-chain.json").read_text())
        api_pages = [p for p in attempts if p["response"].get("available") is True]
        latest = attempts[-1]["response"]
        terminal = latest.get("possibly_truncated") is False and latest.get("next_key") in (
            None,
            "",
            "-1",
        )
        failure = latest.get("reason") if latest.get("available") is not True else None
    for _page_number in range(0 if "--offline" in sys.argv else 50):
        query = urlencode({"key": key, "market": "US", "limit": 300, "next_key": cursor})
        url = "https://tradingagents-portal.onrender.com/api/screener/execute?" + query
        with urlopen(url, timeout=45) as response:
            api = json.load(response)
        api_pages.append(
            {"observed_at": datetime.now(timezone.utc).isoformat(), "url": url, "response": api}
        )
        if api.get("available") is not True:
            failure = api.get("reason", "Unavailable page")
            break
        next_cursor = api.get("next_key")
        if api.get("possibly_truncated") is False:
            terminal = not next_cursor or next_cursor == "-1"
            if not terminal:
                failure = "Completion flag still has a cursor"
            break
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
            failure = "Missing or repeated continuation cursor"
            break
        seen.add(next_cursor)
        cursor = next_cursor
    else:
        if "--offline" not in sys.argv:
            failure = "Safety page limit reached"
    if "--offline" not in sys.argv:
        (ROOT / f"preset-{index}-api-chain.json").write_text(json.dumps(api_pages, indent=2))
    api_codes = [r.get("code") for p in api_pages for r in p["response"].get("rows", [])]
    api_totals = [p["response"].get("provider_total") for p in api_pages]
    source_duplicates = {c: n for c, n in Counter(source_codes).items() if n > 1}
    api_duplicates = {c: n for c, n in Counter(api_codes).items() if n > 1}
    source_stable = len(set(source_counts)) == 1
    api_stable = len(set(api_totals)) == 1
    source_complete = (
        source_stable and not source_duplicates and len(source_codes) == source_counts[0]
    )
    api_complete = (
        terminal
        and not failure
        and not api_duplicates
        and api_stable
        and (api_totals[0] is None or api_totals[0] == len(api_codes))
    )
    return {
        "key": key,
        "source_pages": len(source),
        "source_counts": source_counts,
        "source_count_stable": source_stable,
        "source_rows": len(source_codes),
        "source_unique_rows": len(set(source_codes)),
        "source_duplicates": source_duplicates,
        "source_complete": source_complete,
        "api_pages": len(api_pages),
        "api_rows": len(api_codes),
        "api_totals": api_totals,
        "api_duplicates": api_duplicates,
        "api_terminal": terminal,
        "api_failure": failure,
        "api_complete": api_complete,
        "same_captured_order": source_codes == api_codes,
        "source_only": sorted(set(source_codes) - set(api_codes)),
        "api_only": sorted(set(api_codes) - set(source_codes)),
        "full_qualified_match": source_complete and api_complete and source_codes == api_codes,
    }


with ThreadPoolExecutor(max_workers=2) as executor:
    results = list(executor.map(audit, KEYS.items()))
report = {
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "comparisons": results,
    "limits": "Sequential live observations; no source generation pin. Drift and duplicate boundaries invalidate a complete-snapshot claim. Public deployed API, not the unmerged candidate.",
}
(ROOT / "large-preset-comparison.json").write_text(json.dumps(report, indent=2))
for row in results:
    print(
        json.dumps(
            {
                k: row[k]
                for k in (
                    "key",
                    "source_rows",
                    "source_count_stable",
                    "api_rows",
                    "api_complete",
                    "same_captured_order",
                    "full_qualified_match",
                )
            }
        )
    )
