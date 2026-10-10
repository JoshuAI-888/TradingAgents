"""Kline store: fetch → upsert bars + rotation state; stale-first selection."""

from datetime import datetime, timedelta, timezone

import pytest
from tradingagents_worker.kline_backfill import KlineBackfill

DAY1 = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
DAY2 = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()


@pytest.fixture(autouse=True)
def cache_transport(fake_db, monkeypatch):
    import tradingagents_worker.kline_backfill as module

    monkeypatch.setattr(
        module,
        "current_codes",
        lambda db, market: [
            r["code"] for r in db.select("screener_universe", {"market": "eq." + market})
        ],
    )
    original = fake_db.select

    def select(table, query=None, columns="*"):
        if table == "rpc/screener_kline_cache_members":
            return [{"code": "US.AAPL"}]
        return original(table, query, columns)

    monkeypatch.setattr(fake_db, "select", select)

    def call(method, path, body=None, **kwargs):
        assert path == "rpc/screener_kline_cache_write"
        return fake_db.upsert_many("screener_klines", "market,code,day", body["p_rows"])

    monkeypatch.setattr(fake_db, "_call", call)


class FakeMoomoo:
    def __init__(self):
        self.calls = []

    def call(self, method, path, body=None, query=None, retries=2):
        self.calls.append(path)
        path.split("/")[2]
        return {
            "kline_list": [
                {
                    "day": DAY1,
                    "open_price": 10.0,
                    "high_price": 11.0,
                    "low_price": 9.5,
                    "close_price": 10.5,
                    "volume": 1000.0,
                },
                {
                    "day": DAY2,
                    "open_price": 10.5,
                    "high_price": 12.0,
                    "low_price": 10.0,
                    "close_price": 11.5,
                    "volume": 1200.0,
                },
            ]
        }


def test_backfill_writes_bars_and_state(fake_db):
    kb = KlineBackfill(fake_db, FakeMoomoo(), "US")
    out = kb.backfill(["US.AAPL"])
    assert out["codes"] == 1 and out["bars"] == 2
    bars = fake_db.select("screener_klines", {"market": "eq.US"})
    assert {(b["code"], b["day"]) for b in bars} == {
        ("US.AAPL", DAY1),
        ("US.AAPL", DAY2),
    }
    assert bars[0]["c"] == 10.5
    st = fake_db.select("screener_kline_state", {"market": "eq.US"})
    assert st and st[0]["bars"] == 2


def test_stale_codes_fresh_skip_then_pick(fake_db):
    kb = KlineBackfill(fake_db, FakeMoomoo(), "US")
    fake_db.upsert_many(
        "screener_universe",
        "market,code",
        [{"market": "US", "code": "US.AAPL"}, {"market": "US", "code": "US.OLD"}],
    )
    kb.backfill(["US.AAPL"])  # fresh now
    assert kb.stale_codes(10) == ["US.OLD"]  # never fetched → stale
    old = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    fake_db.upsert(
        "screener_kline_state", "market,code", {"market": "US", "code": "US.OLD", "last_fetch": old}
    )
    assert kb.stale_codes(10) == ["US.OLD"]  # 9d > 7d TTL
    fake_db.upsert(
        "screener_kline_state",
        "market,code",
        {"market": "US", "code": "US.OLD", "last_fetch": datetime.now(timezone.utc).isoformat()},
    )
    assert kb.stale_codes(10) == []  # everything fresh


def test_never_fetched_codes_rank_first(fake_db):
    kb = KlineBackfill(fake_db, FakeMoomoo(), "US")
    fake_db.upsert_many(
        "screener_universe",
        "market,code",
        [{"market": "US", "code": "US.AAPL"}, {"market": "US", "code": "US.NEW"}],
    )
    kb.backfill(["US.AAPL"])
    assert kb.stale_codes(10) == ["US.NEW"]


def test_per_symbol_failure_does_not_stop_batch(fake_db):
    class Flaky(FakeMoomoo):
        def call(self, method, path, body=None, query=None, retries=2):
            if "BAD" in path:
                raise RuntimeError("dead symbol")
            return super().call(method, path, body, query, retries)

    kb = KlineBackfill(fake_db, Flaky(), "US")
    out = kb.backfill(["US.BAD", "US.AAPL"])
    assert out["codes"] == 1 and out["errors"] == 1


def test_real_live_kline_shape_is_normalized(fake_db):
    """Regression (production, 2026-09-30 00:06 UTC): moomoo history-kline bars
    carry time_key as epoch MILLISECONDS and open/close/high/low/volume keys —
    not ISO day + *_price. Epochs must normalize to a date; the *_price key
    guesses produced all-NULL bars."""

    class LiveShape(FakeMoomoo):
        def call(self, method, path, body=None, query=None, retries=2):
            return {
                "kline_list": [
                    {
                        "time_key": int(
                            datetime.fromisoformat(DAY1).replace(tzinfo=timezone.utc).timestamp()
                            * 1000
                        ),
                        "date": 0,
                        "time_zone": -300,
                        "open": 10.0,
                        "close": 10.5,
                        "high": 11.0,
                        "low": 9.5,
                        "volume": 1000.0,
                        "turnover": 10500.0,
                        "last_close": 10.0,
                    },
                    {
                        "time_key": int(
                            datetime.fromisoformat(DAY2).replace(tzinfo=timezone.utc).timestamp()
                            * 1000
                        ),
                        "date": 0,
                        "time_zone": -300,
                        "open": 10.5,
                        "close": 11.5,
                        "high": 12.0,
                        "low": 10.0,
                        "volume": 1200.0,
                        "turnover": 13800.0,
                        "last_close": 10.5,
                    },
                ]
            }

    kb = KlineBackfill(fake_db, LiveShape(), "US")
    out = kb.backfill(["US.AAPL"])
    assert out["codes"] == 1 and out["bars"] == 2
    bars = sorted(fake_db.select("screener_klines", {"market": "eq.US"}), key=lambda b: b["day"])
    assert [b["day"] for b in bars] == [DAY1, DAY2]  # ms → date
    assert bars[0]["c"] == 10.5 and bars[0]["o"] == 10.0 and bars[0]["v"] == 1000.0
    assert bars[0]["h"] == 11.0 and bars[0]["l"] == 9.5


def test_iso_day_still_supported(fake_db):
    kb = KlineBackfill(fake_db, FakeMoomoo(), "US")
    kb.backfill(["US.AAPL"])
    days = sorted(b["day"] for b in fake_db.select("screener_klines", {"market": "eq.US"}))
    assert days == [DAY1, DAY2]


def test_full_history_computes_year_metrics_but_cache_is_only_260_bars(fake_db):
    class History(FakeMoomoo):
        def call(self, *args, **kwargs):
            end = datetime.now(timezone.utc).date()
            return {
                "kline_list": [
                    {
                        "day": (end - timedelta(days=400 - i)).isoformat(),
                        "open": 100 + i,
                        "high": 102 + i,
                        "low": 99 + i,
                        "close": 101 + i,
                        "volume": 1000,
                    }
                    for i in range(400)
                ]
            }

    out = KlineBackfill(fake_db, History()).backfill(["US.AAPL"])
    assert out["fetched_bars"] == 400 and out["bars"] == 260
    assert "perf_y" in out["technicals"]["US.AAPL"]
    assert len(fake_db.tables["screener_klines"]) == 260


def test_uncached_current_symbol_still_gets_technicals(fake_db):
    out = KlineBackfill(fake_db, FakeMoomoo()).backfill(["US.UNCACHED"])
    assert out["fetched_bars"] == 2 and out["bars"] == 0
    assert "US.UNCACHED" in out["technicals"]
    assert not fake_db._t("screener_klines")


def test_failed_technical_persistence_does_not_mark_computation_fresh(fake_db):
    def failed(code, data):
        raise RuntimeError("persistence unavailable")

    with pytest.raises(RuntimeError, match="persistence"):
        KlineBackfill(fake_db, FakeMoomoo()).backfill(["US.AAPL"], on_technical=failed)
    assert not fake_db._t("screener_kline_state")
