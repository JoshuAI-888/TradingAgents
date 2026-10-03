"""Offline audit of complete captured public cohort; no provider or database calls."""

import hashlib
import json
from pathlib import Path

from tradingagents_api.main import PRESET_SCREENERS, _apply_filters, _sort_rows

root = Path(__file__).parent
raw = (root / "live-us-cohort.json").read_bytes()
payload = json.loads(raw)
rows = payload["rows"]
results = []
for preset in PRESET_SCREENERS:
    filters = preset["filters"]
    contextual = [
        f["field"] for f in filters if any(k in f for k in ("days", "period", "term", "plate_ids"))
    ]
    matched, missing = _apply_filters(rows, filters)
    missing = list(dict.fromkeys(missing + contextual))
    picked = (
        []
        if missing
        else _sort_rows(matched, preset.get("sort", "pct"), preset.get("direction", 2))[:3]
    )
    results.append(
        {
            "key": preset["key"],
            "missing_or_contextual_fields": missing,
            "preview_status": "unavailable" if missing else "local_snapshot",
            "top_ids": [r["code"] for r in picked],
            "provider_membership_qualified": False,
        }
    )
report = {
    "source_sha256": hashlib.sha256(raw).hexdigest(),
    "cohort_rows": len(rows),
    "source_universe_at": payload.get("universe_as_of"),
    "definitions": len(PRESET_SCREENERS),
    "presets": results,
    "limits": "Captured deployed stock labels are not independently classified. Local numeric snapshots cannot qualify provider membership, financial periods or direct Moomoo parity. Unavailable previews do not disable provider preset execution.",
}
(root / "preset-preview-reconciliation.json").write_text(
    json.dumps(report, indent=2, allow_nan=False) + "\n"
)
print(
    json.dumps(
        {
            "rows": len(rows),
            "presets": len(results),
            "unavailable_previews": sum(bool(r["missing_or_contextual_fields"]) for r in results),
        }
    )
)
