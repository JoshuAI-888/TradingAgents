from datetime import datetime, timezone

import pytest
from tradingagents_worker.capture_dispatch import dispatch_schedule
from tradingagents_worker.capture_schedule import occurrence_id

SID = "00000000-0000-4000-8000-000000000010"
OWNER = "00000000-0000-4000-8000-000000000001"
NOW = datetime(2026, 10, 2, 18, tzinfo=timezone.utc)


def schedule():
    return {
        "id": SID,
        "owner_id": OWNER,
        "revision": 2,
        "enabled": True,
        "activated_at": "2026-09-28T00:00:00Z",
        "next_due_at": "2026-09-28T16:00:00Z",
        "cadence": {"timezone": "UTC", "hour": 16, "minute": 0, "weekdays": [0, 1, 2, 3, 4]},
    }


class Store:
    def __init__(self):
        self.calls = []

    def _call(self, method, path, body):
        self.calls.append((method, path, body))
        return [
            {
                "id": body["p_occurrence"],
                "owner_id": body["p_owner"],
                "schedule_id": body["p_schedule"],
                "schedule_revision": body["p_revision"],
                "due_at": body["p_due"],
                "status": "pending",
            }
        ]


def test_latest_only_and_stable_retry_no_public_jobs():
    db = Store()
    first = dispatch_schedule(db, schedule(), NOW)
    second = dispatch_schedule(db, schedule(), NOW)
    assert first == second and len(db.calls) == 2
    method, path, body = db.calls[0]
    assert method == "POST" and path == "rpc/research_capture_dispatch"
    assert (
        body["p_due"] == "2026-10-02T16:00:00+00:00"
        and body["p_next"] == "2026-10-05T16:00:00+00:00"
    )
    assert body["p_expected_due"] == "2026-09-28T16:00:00+00:00"
    assert first["id"] == occurrence_id(SID, 2, datetime(2026, 10, 2, 16, tzinfo=timezone.utc))


def test_disabled_and_future_do_not_touch_storage():
    db = Store()
    s = schedule()
    s["enabled"] = False
    assert dispatch_schedule(db, s, NOW) is None
    s["enabled"] = True
    s["next_due_at"] = "2026-10-05T16:00:00Z"
    assert dispatch_schedule(db, s, NOW) is None and not db.calls


def test_db_revision_fence_returns_no_dispatch():
    class Fenced:
        def _call(self, *a, **kw):
            return []

    assert dispatch_schedule(Fenced(), schedule(), NOW) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"revision": True},
        {"enabled": "true"},
        {"owner_id": "bad"},
        {"activated_at": "2026-10-02T16:00:00"},
        {"activated_at": "2026-10-01T00:00:00Z"},
        {"next_due_at": "2026-09-28T15:59:00Z"},
        {"cadence": {"timezone": "UTC", "hour": 16, "minute": 0, "weekdays": [True]}},
    ],
)
def test_malformed_schedule_fails_before_dispatch(changes):
    db = Store()
    s = schedule()
    s.update(changes)
    with pytest.raises((ValueError, TypeError)):
        dispatch_schedule(db, s, NOW)
    assert not db.calls


@pytest.mark.parametrize("damage", ["owner_id", "schedule_id", "id", "schedule_revision", "due_at"])
def test_unconfirmed_response_never_claims_success(damage):
    class Broken(Store):
        def _call(self, *a, **kw):
            rows = super()._call(*a, **kw)
            rows[0][damage] = (
                True
                if damage == "schedule_revision"
                else "00000000-0000-4000-8000-000000000099"
                if damage != "due_at"
                else "2026-10-01T16:00:00Z"
            )
            return rows

    with pytest.raises(RuntimeError):
        dispatch_schedule(Broken(), schedule(), NOW)


def test_dst_gap_skips_nonexistent_slot_and_folds_once():
    db = Store()
    s = schedule()
    s["cadence"] = {"timezone": "America/New_York", "hour": 2, "minute": 30, "weekdays": [6]}
    s["activated_at"] = "2026-03-01T00:00:00Z"
    s["next_due_at"] = "2026-03-01T07:30:00Z"
    dispatch_schedule(db, s, datetime(2026, 3, 8, 9, tzinfo=timezone.utc))
    assert (
        db.calls[-1][2]["p_due"] == "2026-03-01T07:30:00+00:00"
        and db.calls[-1][2]["p_next"] == "2026-03-15T06:30:00+00:00"
    )
    s["cadence"]["hour"] = 1
    s["activated_at"] = "2026-10-31T00:00:00Z"
    s["next_due_at"] = "2026-11-01T06:30:00Z"
    dispatch_schedule(db, s, datetime(2026, 11, 1, 7, tzinfo=timezone.utc))
    assert db.calls[-1][2]["p_due"] == "2026-11-01T06:30:00+00:00"
