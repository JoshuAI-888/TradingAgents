"""Bounded read-only deployed screener evidence. No refresh/auth/private writes."""

import concurrent.futures
import json
import ssl
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import certifi

BASE = "https://tradingagents-portal.onrender.com"
OUT = Path(__file__).parent


def get(path, params):
    started = datetime.now(timezone.utc).isoformat()
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    try:
        with urllib.request.urlopen(
            urllib.request.Request(
                url, headers={"User-Agent": "TradingAgents-release-verification/1"}
            ),
            timeout=45,
            context=ssl.create_default_context(cafile=certifi.where()),
        ) as r:
            return {
                "requested_at": started,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "url": url,
                "status": r.status,
                "payload": json.loads(r.read()),
            }
    except Exception as e:
        return {"requested_at": started, "url": url, "error": type(e).__name__, "detail": str(e)}


def run():
    definitions = get("/api/screener/presets", {"market": "US", "definitions_only": "true"})
    default = get(
        "/api/screener",
        {
            "market": "US",
            "watchlist_only": 0,
            "filters": json.dumps([{"field": "stock_type", "values": ["STOCK"]}]),
            "sort": "market_cap",
            "direction": 2,
            "limit": 500,
            "offset": 0,
            "src": "moo",
        },
    )
    presets = definitions.get("payload", {}).get("presets", [])
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        results = list(
            pool.map(
                lambda p: get(
                    "/api/screener/execute", {"key": p["key"], "market": "US", "limit": 300}
                ),
                presets,
            )
        )
    result = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "base": BASE,
        "definitions": definitions,
        "default": default,
        "executions": results,
        "limits": "Deployed older release only; no refresh flag or production writes. Provider retrieval time is not quote/session time. Results are bounded first pages and may be cached. Does not qualify local uncommitted build.",
    }
    (OUT / "deployed-probe.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                "preset_definitions": len(presets),
                "execution_responses": len(results),
                "errors": sum("error" in r for r in results),
                "default_status": default.get("status"),
                "default_keys": list(default.get("payload", {})),
            }
        )
    )


if __name__ == "__main__":
    run()
