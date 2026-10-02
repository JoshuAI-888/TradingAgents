"""Read the actual worker-published native generation through the actual API loader.

Uses only the fixed isolated socket/database adapter. No HTTP or provider calls.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from tradingagents_api import main as api

adapter = (
    Path("web/worker/tests/generation-worker-contract.py").read_text().split("\ndb=NativeDb()")[0]
)
namespace = {}
exec(compile(adapter, "isolated-native-adapter", "exec"), namespace)
api.db = namespace["NativeDb"]()
api._stored_universe_cache = {}
state = api.db.select("app_settings", {"key": "eq.universe_state_US"}, "value")[0]["value"]
rows, published = api._stored_universe("US")
assert len(rows) == 401 and all(r["generation_id"] == state["generation_id"] for r in rows)
assert "US.LEGACY" not in {r["code"] for r in rows}
assert all(r["stock_type"] == "STOCK" and r["quote_identity_status"] == "verified" for r in rows)
assert published == state["last_quotes"]
rows[0]["price"] = -100
again, _ = api._stored_universe("US", generation_id=state["generation_id"])
assert again[0]["price"] == 12
print(
    "PASS actual API loader reads exact 401-row worker-published immutable generation, excludes legacy history and protects cached rows"
)
Path("/private/tmp/screener-generation-reader-evidence.json").write_text(
    json.dumps(
        {
            "scope": "actual API loader + worker-published native PostgreSQL generation; synthetic provider; no PostgREST",
            "generation_id": state["generation_id"],
            "rows": len(again),
            "published_at": published,
            "contracts": [
                "native_worker_api_roundtrip",
                "retained_legacy_exclusion",
                "cache_mutation_isolation",
            ],
            "completed_at": datetime.now(timezone.utc).isoformat(),
        },
        indent=2,
    )
    + "\n"
)
