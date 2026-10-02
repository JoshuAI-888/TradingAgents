"""Bounded private occurrence dispatch; not enabled in the service loop yet."""

from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from .capture_schedule import CaptureCadence, aware_utc, occurrence_id


def instant(value):
    if not isinstance(value, str):
        raise ValueError("Missing schedule timestamp")
    return aware_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def dispatch_schedule(db, schedule, now):
    """Dispatch only the latest due slot, atomically with next-due advancement.

    No public jobs, capture reads or provider requests occur here. Lost-response
    retries use the same schedule revision/slot identity; the database fences
    concurrent edits and duplicates. The slot is not a data observation time.
    """
    now = aware_utc(now)
    if not isinstance(schedule, dict) or type(schedule.get("enabled")) is not bool:
        raise ValueError("Invalid private schedule")
    if not schedule["enabled"]:
        return None
    sid = str(UUID(schedule["id"]))
    owner = str(UUID(schedule["owner_id"]))
    revision = schedule["revision"]
    if type(revision) is not int or revision < 1:
        raise ValueError("Invalid schedule revision")
    cadence = schedule["cadence"]
    if (
        not isinstance(cadence, dict)
        or set(cadence) != {"timezone", "hour", "minute", "weekdays"}
        or not isinstance(cadence["weekdays"], list)
    ):
        raise ValueError("Invalid cadence")
    calendar = CaptureCadence(
        cadence["timezone"], cadence["hour"], cadence["minute"], tuple(cadence["weekdays"])
    )
    expected = instant(schedule["next_due_at"])
    activated = instant(schedule["activated_at"])
    if expected < activated:
        raise ValueError("Schedule due precedes activation")
    if expected > now:
        return None
    due = calendar.latest_due(now, activated)
    if due is None or due < expected:
        raise ValueError("Stored due does not match a due cadence slot")
    # Stored next-due must itself be a valid slot, not an arbitrary past instant.
    if calendar.occurrence(expected.astimezone(ZoneInfo(calendar.timezone)).date()) != expected:
        raise ValueError("Stored due is not a cadence occurrence")
    next_due = calendar.next_after(now)
    oid = occurrence_id(sid, revision, due)
    rows = db._call(
        "POST",
        "rpc/research_capture_dispatch",
        body={
            "p_schedule": sid,
            "p_owner": owner,
            "p_revision": revision,
            "p_expected_due": expected.isoformat(),
            "p_due": due.isoformat(),
            "p_next": next_due.isoformat(),
            "p_occurrence": oid,
        },
    )
    if rows == []:
        return None  # Changed revision/due/disabled; never claim dispatch.
    if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
        raise RuntimeError("Unconfirmed private dispatch")
    row = rows[0]
    if (
        row.get("id") != oid
        or row.get("schedule_id") != sid
        or row.get("owner_id") != owner
        or type(row.get("schedule_revision")) is not int
        or row["schedule_revision"] != revision
        or instant(row.get("due_at")) != due
    ):
        raise RuntimeError("Unconfirmed private dispatch identity")
    return row
