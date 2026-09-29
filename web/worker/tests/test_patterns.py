"""Phase D spike tests: planted synthetic patterns MUST be found; clean
random-ish series must not fire; harness math checks out end-to-end."""
import random

from tradingagents_worker.patterns import (DETECTORS, detect_double_bottom,
                                           detect_double_top,
                                           detect_horizontal_sr, run_report)


def _bars(closes):
    return [{"day": f"d{i:04d}", "o": c, "h": c * 1.005, "l": c * 0.995, "c": c,
             "v": 1e6} for i, c in enumerate(closes)]


def _planted_double_top():
    """Rise → peak 100 → trough 90 → peak 100.5 → breakdown to 85."""
    c = list(range(60, 100))                 # ramp up
    c += [100.0] * 6                          # peak 1 plateau (pivot-high block)
    c += [95 - i * 0.5 for i in range(10)]    # trough to ~90
    c += [96 + i * 0.45 for i in range(10)]   # rally back to ~100.5
    c += [100.5] * 6                          # peak 2 plateau
    c += [98, 94, 90, 86, 84]                 # breakdown through the trough
    return _bars(c)


def test_double_top_detected_on_planted_series():
    bars = _planted_double_top()
    det = detect_double_top(bars)
    assert det, "planted double top not found"
    assert det[0]["pattern"] == "double_top"
    assert det[0]["signal_index"] > len(bars) - 8  # confirms on the breakdown


def _planted_double_bottom():
    """Fall → trough 100 → rally 110 → trough 100.5 → breakout through 110."""
    c = list(range(140, 100, -1))            # ramp down
    c += [100.0] * 6                          # trough 1 plateau
    c += [104 + i * 0.6 for i in range(10)]   # rally to ~110
    c += [110.0] * 6                          # intervening peak plateau
    c += [106 - i * 0.5 for i in range(10)]   # back to ~101
    c += [100.5] * 6                          # trough 2 plateau
    c += [104, 108, 112, 114, 115]            # breakout through 110
    return _bars(c)


def test_double_bottom_is_mirror():
    det = detect_double_bottom(_planted_double_bottom())
    assert det, "planted double bottom not found"
    assert det[0]["pattern"] == "double_bottom"


def test_random_walk_base_rate_is_bounded():
    """The spike's first real measurement: the geometric definitions' FALSE
    positive base rate on pure noise. Measured (seed 42, 20 × 300-bar walks):
    double_top 36, double_bottom 34, horizontal_sr 54 → ~1.7–2.7 per walk.
    Bound = 4/walk average with margin; the production gate (edge vs baseline,
    n ≥ 200) is what actually protects users from these false positives."""
    rnd = random.Random(42)
    counts = {name: 0 for name in DETECTORS}
    for _ in range(20):
        walk, x = [], 100.0
        for _ in range(300):
            x *= 1 + rnd.gauss(0, 0.01)
            walk.append(x)
        bars = _bars(walk)
        for name, fn in DETECTORS.items():
            counts[name] += len(fn(bars))
    for name, total in counts.items():
        assert total <= 4 * 20, f"{name} over-fires: {total} in 20 walks (base rate shifted)"


def test_report_end_to_end_and_verdict():
    bars = _planted_double_top()
    rep = run_report({"US.AAPL": bars})
    assert rep["codes"] == 1
    assert rep["patterns"]["double_top"]["detections"] >= 1
    # tiny sample → the honest verdict is "insufficient", never a ship signal
    assert "insufficient" in rep["verdict"]


def test_gate_math():
    """Block series: 250 × (30 flat bars + 20 rising bars). Detections at each
    rise start gain ~+10% at h=10 while the all-bar baseline is ~flat →
    spread ≫ 25 bps, n ≥ 200, both halves positive → gate passes."""
    from tradingagents_worker.patterns import evaluate_pattern
    closes, det = [], []
    idx = 0
    for _ in range(250):
        start = 100.0 * (1.0 + len(closes) / 1e6)   # tiny drift, keeps prices positive
        closes += [start] * 30
        rise_idx = len(closes)
        closes += [start * (1.01 ** (i + 1)) for i in range(20)]
        det.append({"pattern": "x", "signal_index": rise_idx})
        idx += 1
    out = evaluate_pattern(closes, det)
    assert out["horizons"][10]["n"] >= 200
    assert out["horizons"][10]["median"] > 5.0       # signals sit on rising blocks
    assert out["spread_bps_h10"] > 25.0
    assert out["gate_passed"] is True
