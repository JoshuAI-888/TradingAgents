from datetime import datetime, timedelta, timezone

from tradingagents_worker.provider_context import info_context, validated_context


def test_same_response_context_keeps_currencies_distinct_and_calendar_separate():
    now = datetime.now(timezone.utc)
    context = info_context(
        {
            "symbol": "0700.HK",
            "currency": "HKD",
            "financialCurrency": "CNY",
            "mostRecentQuarter": 1767139200,
        },
        "HK.00700",
        now,
    )
    assert (
        context["fields"]["currency"] == "HKD" and context["fields"]["financialCurrency"] == "CNY"
    )
    assert context["fields"]["mostRecentQuarter"]["date"] == "2025-12-31"
    assert "not per-metric periods" in context["scope"]
    assert validated_context(context, "HK.00700", now.isoformat(), now) == context
    assert validated_context(context, "US.AAPL", now.isoformat(), now) is None
    assert (
        validated_context(context, "HK.00700", (now - timedelta(days=8)).isoformat(), now) is None
    )
    assert (
        validated_context(context, "HK.00700", (now + timedelta(seconds=1)).isoformat(), now)
        is None
    )


def test_context_rejects_wrong_identity_invalid_clocks_currency_and_tampered_dates():
    now = datetime.now(timezone.utc)
    assert info_context({"symbol": "OTHER"}, "US.AAPL", now) is None
    for invalid in [True, "1767139200", [], {}, float("inf"), -1, now.timestamp() + 100, 10**1000]:
        context = info_context(
            {"symbol": "AAPL", "lastFiscalYearEnd": invalid, "currency": "usd"}, "US.AAPL", now
        )
        assert not context["fields"]
    context = info_context({"symbol": "AAPL", "lastFiscalYearEnd": 1767139200}, "US.AAPL", now)
    context["fields"]["lastFiscalYearEnd"]["date"] = "2000-01-01"
    assert validated_context(context, "US.AAPL") is None


def test_same_response_instrument_type_is_retained_without_reclassifying_other_provider():
    from copy import deepcopy

    now = datetime.now(timezone.utc)
    for symbol, quote_type in [
        ("PLD", "EQUITY"),
        ("AMT", "EQUITY"),
        ("SPY", "ETF"),
        ("UNKNOWN", "FUTURE_NEW_TYPE"),
    ]:
        context = info_context({"symbol": symbol, "quoteType": quote_type}, "US." + symbol, now)
        assert context["fields"]["quoteType"] == quote_type
        assert "does not reinterpret" in context["classification_scope"]
        assert validated_context(context, "US." + symbol, now.isoformat(), now) == context
        damaged = deepcopy(context)
        damaged["classification_scope"] = "This is a verified Moomoo ETF classification"
        assert validated_context(damaged, "US." + symbol, now.isoformat(), now) is None
        assert (
            validated_context(context, "US." + symbol, (now - timedelta(days=8)).isoformat(), now)
            is None
        )
    for invalid in [True, {}, [], None, "equity", "ETF;DROP", "A" * 33]:
        context = info_context({"symbol": "PLD", "quoteType": invalid}, "US.PLD", now)
        assert "quoteType" not in context["fields"] and "classification_scope" not in context
    legacy = info_context({"symbol": "PLD", "currency": "USD"}, "US.PLD", now)
    assert validated_context(legacy, "US.PLD", now.isoformat(), now) == legacy
