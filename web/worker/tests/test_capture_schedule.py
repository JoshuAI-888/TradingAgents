from datetime import date, datetime

import pytest
from tradingagents_worker.capture_schedule import CaptureCadence, occurrence_id


def t(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_us_close_civil_time_tracks_dst_and_skips_weekends():
    schedule = CaptureCadence("America/New_York", 16, 15)
    assert schedule.next_after(t("2026-03-06T21:15:00Z")) == t("2026-03-09T20:15:00Z")
    assert schedule.next_after(t("2026-10-30T20:15:00Z")) == t("2026-11-02T21:15:00Z")
    assert schedule.latest_due(t("2026-10-04T12:00:00Z"), t("2026-09-01T00:00:00Z")) == t(
        "2026-10-02T20:15:00Z"
    )


def test_hk_time_and_creation_floor_do_not_backfill_old_capture_slots():
    schedule = CaptureCadence("Asia/Hong_Kong", 16, 15)
    assert schedule.next_after(t("2026-10-02T08:14:59Z")) == t("2026-10-02T08:15:00Z")
    assert schedule.latest_due(t("2026-10-05T08:16:00Z"), t("2026-10-05T08:15:01Z")) is None
    assert schedule.latest_due(t("2026-10-05T08:16:00Z"), t("2026-10-05T08:15:00Z")) == t(
        "2026-10-05T08:15:00Z"
    )
    assert schedule.latest_due(t("2026-10-05T08:16:00Z"), t("2026-10-06T00:00:00Z")) is None


def test_nonexistent_clock_skips_day_and_ambiguous_clock_runs_once_at_later_instant():
    gap = CaptureCadence("America/New_York", 2, 30, (6,))
    assert gap.occurrence(date(2026, 3, 8)) is None
    assert gap.next_after(t("2026-03-01T07:30:00Z")) == t("2026-03-15T06:30:00Z")
    fold = CaptureCadence("America/New_York", 1, 30, (6,))
    assert fold.occurrence(date(2026, 11, 1)) == t("2026-11-01T06:30:00Z")
    assert fold.latest_due(t("2026-11-01T05:45:00Z"), t("2026-10-01T00:00:00Z")) == t(
        "2026-10-25T05:30:00Z"
    )
    assert fold.next_after(t("2026-11-01T06:30:00Z")) == t("2026-11-08T06:30:00Z")


def test_latest_due_is_bounded_catchup_not_a_backlog():
    schedule = CaptureCadence("UTC", 12, 0)
    due = schedule.latest_due(t("2026-10-02T13:00:00Z"), t("2020-01-01T00:00:00Z"))
    assert due == t("2026-10-02T12:00:00Z")
    assert schedule.next_after(t("2026-10-02T13:00:00Z")) == t("2026-10-05T12:00:00Z")


@pytest.mark.parametrize(
    "args",
    [
        ("Not/A/Zone", 1, 0),
        ("../UTC", 1, 0),
        ("UTC", True, 0),
        ("UTC", 24, 0),
        ("UTC", 1, 60),
        ("UTC", 1, 0, ()),
        ("UTC", 1, 0, (0, 0)),
        ("UTC", 1, 0, (True,)),
        ("UTC", 1, 0, [0]),
    ],
)
def test_invalid_cadences_fail_closed(args):
    with pytest.raises(ValueError):
        CaptureCadence(*args)


def test_occurrence_identity_is_stable_across_timezone_representation_and_revision_scoped():
    sid = "00000000-0000-4000-8000-000000000003"
    first = occurrence_id(sid, 1, t("2026-10-02T12:00:00Z"))
    assert first == occurrence_id(sid, 1, t("2026-10-02T20:00:00+08:00"))
    assert first != occurrence_id(sid, 2, t("2026-10-02T12:00:00Z"))
    for due in [datetime(2026, 10, 2), None]:
        with pytest.raises(ValueError):
            occurrence_id(sid, 1, due)
    with pytest.raises(ValueError):
        occurrence_id(sid, True, t("2026-10-02T12:00:00Z"))
