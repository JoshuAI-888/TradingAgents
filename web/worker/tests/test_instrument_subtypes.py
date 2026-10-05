from datetime import datetime, timedelta, timezone

import pytest
from tradingagents_worker.instrument_classification import classify
from tradingagents_worker.instrument_subtypes import collect, qualified_context

NOW = datetime(2026, 10, 3, tzinfo=timezone.utc)


def rows(*codes):
    return [{"code": c, "provider_stock_type": "ETF"} for c in codes]


def test_bounded_rotation_identity_and_classification_without_financial_payload():
    calls = []

    def fetch(symbol):
        calls.append(symbol)
        return {"symbol": symbol, "quoteType": "EQUITY", "marketCap": 99, "currency": "USD"}

    cohort = rows("US.PLD", "US.AMT", "US.SPY") + [
        {"code": "US.AAPL", "provider_stock_type": "STOCK"}
    ]
    first = collect(cohort, fetch_info=fetch, now=NOW, limit=2)
    assert first["attempted"] == 2 and first["remaining"] == 1
    second = collect(cohort, first["updates"], fetch, NOW, limit=2)
    assert second["attempted"] == 1 and len(calls) == 3 and "AAPL" not in calls
    for code, record in first["updates"].items():
        evidence = qualified_context(record, code, NOW)
        assert evidence["provider_context"]["fields"] == {"quoteType": "EQUITY"}
        result = classify(
            code,
            "ETF",
            NOW.isoformat(),
            evidence["provider_context"],
            evidence["fundamentals_at"],
            NOW,
        )
        assert result["stock_type"] == "STOCK"
    assert first["updates"]["US.PLD"]["context"]["fields"] == {"quoteType": "EQUITY"}


def test_failed_refresh_retains_old_receipt_and_retry_cooldown():
    initial = collect(
        rows("US.PLD"), fetch_info=lambda s: {"symbol": s, "quoteType": "EQUITY"}, now=NOW
    )["updates"]
    later = NOW + timedelta(days=8)

    def failed(symbol):
        raise RuntimeError("private provider detail")

    failed_result = collect(rows("US.PLD"), initial, failed, later)["updates"]
    record = failed_result["US.PLD"]
    assert record["status"] == "unavailable" and record["retrieved_at"] == NOW.isoformat()
    assert initial["US.PLD"]["attempted_at"] == NOW.isoformat()
    assert qualified_context(record, "US.PLD", later) is None
    assert (
        collect(rows("US.PLD"), failed_result, failed, later + timedelta(hours=1))["attempted"] == 0
    )
    assert (
        collect(rows("US.PLD"), failed_result, failed, later + timedelta(days=1))["attempted"] == 1
    )


@pytest.mark.parametrize(
    "info,status",
    [
        ({"symbol": "OTHER", "quoteType": "EQUITY"}, "identity_mismatch"),
        ({"symbol": "PLD"}, "invalid_subtype"),
        ({"symbol": "PLD", "quoteType": True}, "invalid_subtype"),
    ],
)
def test_bad_response_never_qualifies(info, status):
    record = collect(rows("US.PLD"), fetch_info=lambda _: info, now=NOW)["updates"]["US.PLD"]
    assert record["status"] == status and qualified_context(record, "US.PLD", NOW) is None


def test_hk_mapping_and_alias_collision_fail_before_fetch():
    record = collect(
        rows("HK.00700"), fetch_info=lambda s: {"symbol": s, "quoteType": "EQUITY"}, now=NOW
    )["updates"]["HK.00700"]
    assert record["context"]["provider_symbol"] == "0700.HK"
    for cohort in [rows("US.PLD", "US.PLD"), rows("US.BRK.B", "US.BRK-B"), rows("BAD")]:
        with pytest.raises(ValueError):
            collect(cohort, fetch_info=lambda _: pytest.fail("must not fetch"), now=NOW)
    with pytest.raises(ValueError):
        collect(rows("US.PLD"), now=NOW, limit=101)
    with pytest.raises(ValueError):
        qualified_context({**record, "code": "HK.00701"}, "HK.00700", NOW)


def test_cache_tampering_and_future_receipts_are_rejected():
    record = collect(
        rows("US.PLD"), fetch_info=lambda s: {"symbol": s, "quoteType": "EQUITY"}, now=NOW
    )["updates"]["US.PLD"]
    from copy import deepcopy

    bad = deepcopy(record)
    bad["context"]["provider_symbol"] = "OTHER"
    with pytest.raises(ValueError):
        qualified_context(bad, "US.PLD", NOW)
    bad = deepcopy(record)
    bad["attempted_at"] = (NOW + timedelta(seconds=1)).isoformat()
    with pytest.raises(ValueError):
        qualified_context(bad, "US.PLD", NOW)
    assert qualified_context(record, "US.PLD", NOW + timedelta(days=7)) is not None
    assert qualified_context(record, "US.PLD", NOW + timedelta(days=7, seconds=1)) is None


def test_unsupported_subtype_is_evidence_but_not_equity_inference():
    record = collect(
        rows("US.PLD"), fetch_info=lambda s: {"symbol": s, "quoteType": "NEW_TYPE"}, now=NOW
    )["updates"]["US.PLD"]
    evidence = qualified_context(record, "US.PLD", NOW)
    assert (
        classify(
            "US.PLD",
            "ETF",
            NOW.isoformat(),
            evidence["provider_context"],
            evidence["fundamentals_at"],
            NOW,
        )["stock_type"]
        == "UNKNOWN"
    )


def test_explicit_throttle_stops_run_and_defers_unrequested_instruments():
    from tradingagents_worker.instrument_subtypes import SubtypeRateLimited

    calls = []

    def throttled(symbol):
        calls.append(symbol)
        raise SubtypeRateLimited("safe provider throttle")

    result = collect(rows("US.PLD", "US.SPY", "US.AMT"), fetch_info=throttled, now=NOW)
    assert calls == ["AMT"] and result["attempted"] == 1 and result["remaining"] == 2
    assert result["stop_reason"] == "provider_rate_limited"
    assert list(result["updates"]) == ["US.AMT"]
    assert result["updates"]["US.AMT"]["status"] == "unavailable"
    assert result["updates"]["US.AMT"]["retrieved_at"] is None
