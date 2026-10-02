"""Dedicated private capture service. Runtime opt-in remains off by default.

Run from repository root with PYTHONPATH=web/api:web/worker after schema/platform
qualification. This process shares the actual API capture builder; it does not
start the public API or put private jobs into the analysis queue.
"""

import os
import signal
import uuid
from datetime import datetime, timezone
from threading import Event

from fastapi import HTTPException
from tradingagents_worker.capture_dispatch import dispatch_schedule
from tradingagents_worker.capture_executor import CaptureExecutor, PermanentCaptureError

from . import main as api
from .research_schedules import _definition, build_schedule_capture


def build(schedule, capture_id):
    definition = schedule.get("definition")
    try:
        if (
            not isinstance(definition, dict)
            or type(definition.get("schema_version")) is not int
            or definition["schema_version"] != 1
        ):
            raise ValueError("Invalid definition")
        current, digest = _definition(definition.get("screen"))
        if current != definition or digest != schedule.get("definition_hash"):
            raise ValueError("Pinned definition changed")
    except (HTTPException, ValueError, TypeError):
        raise PermanentCaptureError("definition_changed") from None
    return build_schedule_capture(definition, digest, capture_id)


def dispatch_due(db, now):
    rows = db._call(
        "GET",
        "research_capture_schedules",
        query={
            "enabled": "eq.true",
            "next_due_at": "lte." + now.isoformat(),
            "select": "*",
            "order": "next_due_at.asc,id.asc",
            "limit": "100",
        },
    )
    if not isinstance(rows, list) or len(rows) > 100 or any(not isinstance(r, dict) for r in rows):
        raise RuntimeError("Unconfirmed due schedules")
    summary = {"dispatched": 0, "fenced": 0, "invalid": 0}
    for row in rows:
        try:
            outcome = dispatch_schedule(db, row, now)
            summary["dispatched" if outcome else "fenced"] += 1
        except (ValueError, KeyError, TypeError):
            summary["invalid"] += 1
    return summary


def main():
    if os.getenv("PRIVATE_CAPTURE_RUNTIME_ENABLED") != "1":
        raise SystemExit(
            "Private capture runtime is disabled. Complete schema/platform qualification before opting in."
        )
    stop = Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())
    executor = CaptureExecutor(api.db, str(uuid.uuid4()), build)
    while not stop.is_set():
        try:
            dispatch_due(api.db, datetime.now(timezone.utc))
            result = executor.execute_one(stop)
            # No definitions, provider payloads, owner IDs, notes or raw errors.
            print("private capture state=" + result["state"], flush=True)
        except (RuntimeError, OSError, ValueError):
            print("private capture storage unavailable", flush=True)
        stop.wait(30)


if __name__ == "__main__":
    main()
