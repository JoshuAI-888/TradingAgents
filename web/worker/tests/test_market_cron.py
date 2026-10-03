from datetime import datetime, timedelta, timezone

import pytest
from tradingagents_worker.market_cron import main, scheduled_market


@pytest.mark.parametrize(
    "kind,hour,market",
    [
        ("universe", 1, "HK"),
        ("universe", 8, "HK"),
        ("universe", 13, "US"),
        ("universe", 21, "US"),
        ("enrich", 8, "HK"),
        ("enrich", 21, "US"),
    ],
)
def test_session_boundaries(kind, hour, market):
    utc = datetime(2026, 10, 5, hour, 45, tzinfo=timezone.utc)
    assert scheduled_market(kind, utc) == market
    assert scheduled_market(kind, utc.astimezone(timezone(timedelta(hours=13)))) == market


@pytest.mark.parametrize(
    "kind,hour",
    [
        ("universe", 0),
        ("universe", 9),
        ("universe", 22),
        ("enrich", 9),
        ("enrich", 20),
        ("other", 8),
    ],
)
def test_outside_windows_fail_closed(kind, hour):
    with pytest.raises(ValueError):
        scheduled_market(kind, datetime(2026, 10, 5, hour, tzinfo=timezone.utc))


def test_weekend_and_naive_fail_closed():
    for now in [datetime(2026, 10, 3, 8, tzinfo=timezone.utc), datetime(2026, 10, 5, 8)]:
        with pytest.raises(ValueError):
            scheduled_market("universe", now)


@pytest.mark.parametrize(
    "kind,module", [("universe", "universe_refresh"), ("enrich", "enrich_nightly")]
)
def test_manual_override_dispatches_only_requested_market(monkeypatch, kind, module):
    called = []
    monkeypatch.setattr(f"tradingagents_worker.{module}.main", called.append)
    main([kind, "--market", "HK"])
    assert called == ["HK"]


def test_enrichment_qualifies_subtypes_for_the_same_market_before_factors(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "tradingagents_worker.instrument_subtype_job.main",
        lambda market=None: calls.append(("subtypes", market)),
    )
    monkeypatch.setattr(
        "tradingagents_worker.enrich_nightly.main", lambda market: calls.append(("factors", market))
    )
    for market in ["HK", "US"]:
        main(["enrich", "--market", market])
    assert calls == [("subtypes", "HK"), ("factors", "HK"), ("subtypes", "US"), ("factors", "US")]
