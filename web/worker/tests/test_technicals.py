"""Computed technicals: known-value math on synthetic bars."""
from tradingagents_worker.enrich_fields import TECH_FIELDS
from tradingagents_worker.technicals import compute, rsi14, sma, perf


def _bars(closes, vols=None):
    vols = vols or [1_000_000.0] * len(closes)
    return [{"day": f"d{i:03d}", "o": c, "h": c * 1.01, "l": c * 0.99, "c": c, "v": v}
            for i, (c, v) in enumerate(zip(closes, vols))]


def test_sma_and_perf():
    closes = [float(i) for i in range(1, 51)]           # 1..50
    assert sma(closes, 20) == 40.5                      # mean of 31..50
    assert perf(closes, 20) == 66.6667                  # (50/30 − 1)×100, 4dp


def test_rsi_bounds():
    assert rsi14([100.0] * 20) is None                  # no moves → undefined
    rising = [100 + i for i in range(30)]               # all gains
    assert rsi14(rising) == 100.0
    falling = [200 - i for i in range(30)]
    assert rsi14(falling) == 0.0


def test_compute_windows_and_keys():
    closes = [100 + (i % 7) for i in range(260)]        # 260 trading days
    bars = _bars(closes)
    out = compute(bars)
    assert set(out) <= set(TECH_FIELDS)
    assert out["avg_vol3m"] == 1_000_000.0
    assert out["rel_vol"] == 1.0
    assert abs(out["sma20_pos"]) < 5.0                  # oscillating series ≈ flat
    assert abs(out["perf_w"] - (closes[-1] / closes[-6] - 1) * 100) < 1e-3


def test_short_series_yields_absent_keys_not_zeros():
    out = compute(_bars([100.0, 101.0]))                # 2 bars only
    assert "sma200_pos" not in out and "perf_y" not in out
    assert "rsi14" not in out                           # needs ≥15 closes


# ── snapshot-synthesized today-bar (round: fresher technicals, no new calls) ──
def _iso_bars(closes):
    return [{"day": f"2099-01-{i + 1:02d}", "o": c, "h": c * 1.01, "l": c * 0.99,
             "c": c, "v": 1_000_000.0} for i, c in enumerate(closes)]


def test_synthesized_today_bar_appended():
    from tradingagents_worker.technicals import append_snapshot_bar
    bars = _iso_bars([100.0, 101.0])                  # 2099-01-01, 2099-01-02
    quote = {"price": 103.0, "open": 101.5, "high": 104.0, "low": 101.0,
             "volume": 900_000.0, "updated_at": "2099-01-03T05:00:00+00:00"}
    out = append_snapshot_bar(bars, quote, today="2099-01-03")  # new session → append
    assert len(out) == 3
    last = out[-1]
    assert last["day"] == "2099-01-03"
    assert (last["o"], last["h"], last["l"], last["c"], last["v"]) == \
        (101.5, 104.0, 101.0, 103.0, 900_000.0)


def test_no_duplicate_when_klines_already_have_today():
    from tradingagents_worker.technicals import append_snapshot_bar
    bars = _iso_bars([100.0, 101.0])                  # last stored day = 2099-01-02
    quote = {"price": 103.0, "open": 101.5, "high": 104.0, "low": 101.0,
             "volume": 900_000.0, "updated_at": "2099-01-02T05:00:00+00:00"}
    out = append_snapshot_bar(bars, quote, today="2099-01-02")
    assert len(out) == 2 and out[-1]["c"] == 101.0    # real bar kept


def test_fallback_bar_without_ohlc():
    from tradingagents_worker.technicals import append_snapshot_bar
    bars = _iso_bars([100.0])                         # last day 2099-01-01
    quote = {"price": 102.0, "volume": 10.0, "updated_at": "2099-01-02T05:00:00+00:00"}
    out = append_snapshot_bar(bars, quote, today="2099-01-02")
    assert (out[-1]["o"], out[-1]["h"], out[-1]["l"], out[-1]["c"]) == (102.0, 102.0, 102.0, 102.0)


def test_stale_snapshot_not_appended():
    from tradingagents_worker.technicals import append_snapshot_bar
    bars = _iso_bars([100.0, 101.0])                  # last day 2099-01-02
    quote = {"price": 102.0, "updated_at": "2099-01-01T05:00:00+00:00"}  # older session
    out = append_snapshot_bar(bars, quote, today="2099-01-02")
    assert len(out) == 2                              # unchanged — session older than history
