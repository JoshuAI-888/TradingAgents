"""Cloud quote-source clocks and truthful metric provenance."""

from datetime import datetime, timedelta, timezone

import pytest
from tradingagents_worker.quote_observations import cloud_snapshot_time
from tradingagents_worker.screener_rows import snapshot_to_row


@pytest.mark.parametrize(
    "bad",
    [
        None,
        True,
        False,
        0,
        1790919256,
        "2026-10-02 09:30:00",
        "2026-10-02T09:30:00Z",
        float("nan"),
        float("inf"),
        {},
        [],
        99999999999999999999,
    ],
)
def test_cloud_clock_rejects_missing_seconds_sdk_strings_and_invalid_values(bad):
    assert cloud_snapshot_time(bad) is None


def test_cloud_snapshot_retains_source_clock_without_inventing_currency_or_periods():
    stamp = int((datetime.now(timezone.utc) - timedelta(minutes=1)).timestamp() * 1000)
    row = snapshot_to_row(
        {
            "code": "US.BRK.B",
            "last_price": 12,
            "prev_close_price": 10,
            "update_time": stamp,
            "data_date": "2026-10-02",
            "currency": "USD",
            "total_market_val": 100,
            "volume": 123,
            "pe_ttm_ratio": 0,
            "pb_ratio": -1,
            "dividend_ratio_ttm": 0,
            "earning_per_share": 0,
            "outstanding_shares": 1000,
        }
    )
    assert (
        row["symbol"] == "BRK.B"
        and row["pe_ttm"] == 0
        and row["div_yield"] == 0
        and row["eps"] == 0
        and row["pb"] == -1
    )
    source = datetime.fromtimestamp(stamp / 1000, timezone.utc).isoformat()
    assert row["quote_observed_at"] == source and cloud_snapshot_time(str(stamp)) == source
    price = row["field_observations"]["price"]
    assert price["code"] == "US.BRK.B" and price["value"] == 12 and price["observed_at"] == source
    assert price["source"] == "moomoo_cloud_snapshot" and price["clock"] == "quote_source"
    assert price["currency"] is None and price["last_trade_time"] is None
    assert (
        price["period"] == "point_in_time"
        and price["timestamp_semantics"] == "provider_snapshot_update"
    )
    for field in ("pe_ttm", "pct", "volume"):
        assert row["field_observations"][field]["period"] is None
        assert row["field_observations"][field]["provider_data_date"] == "2026-10-02"
    assert row["field_observations"]["pct"]["unit"] == "percentage_points"
    assert row["field_observations"]["shares"]["unit"] == "shares"


def test_missing_source_clock_keeps_values_without_a_qualified_timestamp():
    row = snapshot_to_row(
        {"code": "HK.00700", "last_price": 1, "prev_close_price": 1, "update_time": None}
    )
    assert row["quote_observed_at"] is None
    assert row["field_observations"]["price"]["value"] == 1
    assert row["field_observations"]["price"]["clock"] is None
    assert row["field_observations"]["price"]["currency"] is None


@pytest.mark.parametrize("bad", [True, float("inf"), float("nan"), "not-a-number", {}, 10**1000])
def test_malformed_numeric_snapshot_does_not_become_json_or_numeric_evidence(bad):
    import json

    row = snapshot_to_row(
        {
            "code": "US.A",
            "last_price": bad,
            "prev_close_price": bad,
            "highest52weeks_price": bad,
            "lowest52weeks_price": bad,
            "pe_ttm_ratio": bad,
            "volume": bad,
        }
    )
    assert all(
        row[f] is None for f in ("price", "pct", "chg", "pe_ttm", "volume", "high52", "low52")
    )
    assert row["field_observations"] == {}
    json.dumps(row, allow_nan=False)
