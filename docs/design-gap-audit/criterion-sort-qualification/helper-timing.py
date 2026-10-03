import inspect
import json
import statistics
import time
from datetime import datetime, timedelta, timezone

import tradingagents_api.screen_observations as module

fn = module.criterion_sort_qualification
source = inspect.getsource(fn).replace("def criterion_sort_qualification(", "def uncached(")
a = source.index("        if valid:\n            raw_stamp")
b = source.index("        if valid:\n            contracts.add", a)
source = (
    source[:a]
    + """        if valid:
            try:
                stamp = datetime.fromisoformat(str(observation.get('observed_at')).replace('Z', '+00:00'))
                valid = stamp.tzinfo is not None and 0 <= (captured_at-stamp).total_seconds() <= (7*86400 if observation['clock']=='financial_report' else 86400)
            except (TypeError, ValueError):
                valid = False
"""
    + source[b:]
)
namespace = vars(module).copy()
exec(source, namespace)
uncached = namespace["uncached"]
criterion = {"field": "price", "max": 10}
captured = datetime(2026, 10, 3, tzinfo=timezone.utc)


def record(i, unique):
    return {
        "criterion_observations": {
            "c0": {
                "criterion": criterion,
                "value": i + 1,
                "unit": "currency",
                "currency": "USD",
                "period": "point_in_time",
                "source": "synthetic",
                "clock": "quote_source",
                "observed_at": (captured - timedelta(seconds=i if unique else 1)).isoformat(),
            }
        }
    }


results = []
for unique in (False, True):
    rows = [record(i, unique) for i in range(40000)]
    for name, method in [("uncached", uncached), ("bounded_timestamp_cache", fn)]:
        runs = []
        for _ in range(3):
            start = time.perf_counter()
            for _side in range(12):
                result = method(rows, "c0", criterion, captured)
            runs.append(time.perf_counter() - start)
            assert result == uncached(rows, "c0", criterion, captured)
        results.append(
            {
                "method": name,
                "unique_timestamps": unique,
                "rows": 40000,
                "side_criterion_passes": 12,
                "runs_seconds": runs,
                "median_seconds": statistics.median(runs),
                "ready": result["ready"],
            }
        )
print(
    json.dumps(
        {"scope": "helper-only synthetic local timing; not HTTP/UI p95", "results": results},
        indent=2,
    )
)
