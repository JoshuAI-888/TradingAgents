"""Phase D spike: chart-pattern detectors + backtest harness (spec §6b).

METHODOLOGY (agreed with the owner before any measurement):
1. Formal, deterministic geometric definitions over price pivots — no ML, no
   discretionary eyeballing. Every tolerance is an explicit constant.
2. Synthetic ground truth: bars with PLANTED patterns must be found; clean
   random walks must yield (near-)zero detections — validates the detector
   before any market claim.
3. Backtest = forward returns at 5/10/20/40 bars after each detection vs the
   same-period all-bar baseline, reported per pattern with n, median spread
   (bps), hit rate, and split-half stability.
4. ACCEPTANCE GATE (decided up front): a pattern ships as a screener signal
   only if median spread > 25 bps at h=10 with n ≥ 200 and the sign of the
   spread agrees across both halves of the sample. If nothing clears the
   gate, the honest result is "no shippable edge".

This module ships DETECTORS + MEASUREMENT. It ships no UI signals.
"""
from __future__ import annotations

import statistics
from datetime import datetime, timezone

# ── tolerances (explicit per spec §6b rule 2) ────────────────────────────────
PIVOT_ORDER = 5          # bars left+right for a fractal pivot
DT_TOL = 0.03            # double top/bottom: peaks within ±3%
DT_MIN_GAP = 20          # … and ≥20 bars apart
DT_TROUGH_DEPTH = 0.05   # intervening move ≥5% against the peaks
SR_TOL = 0.02            # horizontal S/R: touches within ±2%
CONFIRM_BARS = 2         # closes beyond the level, 2 bars running (false-break filter)
SR_TOUCHES = 3
HORIZONS = (5, 10, 20, 40)
GATE_SPREAD_BPS = 25.0
GATE_MIN_N = 200


def pivots(bars: list[dict], order: int = PIVOT_ORDER) -> tuple[list[int], list[int]]:
    """Fractal pivots with plateau support: a pivot high is the LAST bar of a
    local-maximum run (window max == close, and `order` bars later are lower) —
    real charts have equal-close plateaus, not just single spikes."""
    closes = [b["c"] for b in bars]
    highs, lows = [], []
    n = len(closes)
    for i in range(order, n - order):
        win = closes[i - order:i + order + 1]
        if closes[i] == max(win) and closes[i + order] < closes[i]:
            highs.append(i)
        if closes[i] == min(win) and closes[i + order] > closes[i]:
            lows.append(i)
    return highs, lows


def detect_double_top(bars: list[dict]) -> list[dict]:
    """Two pivot highs within DT_TOL, ≥DT_MIN_GAP bars apart, with an
    intervening trough DT_TROUGH_DEPTH below both. Signal bar = first close
    below the intervening trough after the second peak."""
    highs, _ = pivots(bars)
    closes = [b["c"] for b in bars]
    out = []
    for a_i in range(len(highs) - 1):
        for b_i in range(a_i + 1, len(highs)):
            i1, i2 = highs[a_i], highs[b_i]
            if i2 - i1 < DT_MIN_GAP:
                continue
            p1, p2 = closes[i1], closes[i2]
            if min(p1, p2) <= 0 or abs(p2 - p1) / min(p1, p2) > DT_TOL:
                break  # peaks too far apart in price; later peaks only worsen
            trough = min(closes[i1:i2])
            if trough >= min(p1, p2) * (1 - DT_TROUGH_DEPTH):
                continue  # neckline not deep enough
            neckline = trough
            for j in range(i2 + 1, len(closes) - CONFIRM_BARS + 1):
                if all(closes[j + k] < neckline for k in range(CONFIRM_BARS)):
                    out.append({"pattern": "double_top", "peak1": i1, "peak2": i2,
                                "signal_index": j,
                                "day": bars[j].get("day", "")})
                    break
            break  # only the nearest valid second peak per first peak
    return out


def detect_double_bottom(bars: list[dict]) -> list[dict]:
    """Mirror of double top: two pivot lows within tolerance, intervening
    rally ≥ depth, signal on a close above the intervening peak."""
    _, lows = pivots(bars)
    closes = [b["c"] for b in bars]
    out = []
    for a_i in range(len(lows) - 1):
        for b_i in range(a_i + 1, len(lows)):
            i1, i2 = lows[a_i], lows[b_i]
            if i2 - i1 < DT_MIN_GAP:
                continue
            p1, p2 = closes[i1], closes[i2]
            if min(p1, p2) <= 0 or abs(p2 - p1) / min(p1, p2) > DT_TOL:
                break
            peak = max(closes[i1:i2])
            if peak <= max(p1, p2) * (1 + DT_TROUGH_DEPTH):
                continue
            for j in range(i2 + 1, len(closes) - CONFIRM_BARS + 1):
                if all(closes[j + k] > peak for k in range(CONFIRM_BARS)):
                    out.append({"pattern": "double_bottom", "peak1": i1, "peak2": i2,
                                "signal_index": j,
                                "day": bars[j].get("day", "")})
                    break
            break
    return out


def detect_horizontal_sr(bars: list[dict]) -> list[dict]:
    """A price level touched ≥SR_TOUCHES times within ±SR_TOL, then broken.
    Signal bar = first close beyond the level after the last touch."""
    highs, lows = pivots(bars)
    closes = [b["c"] for b in bars]
    out = []
    for kind, idxs in (("resistance", highs), ("support", lows)):
        used_until = -1
        for i in idxs:
            if i < used_until:
                continue  # a prior level already claimed this zone
            level = closes[i]
            tol = level * SR_TOL
            touches = [j for j in idxs if abs(closes[j] - level) <= tol]
            if len(touches) < SR_TOUCHES:
                continue
            # a real level persists: first→last touch spans ≥ DT_MIN_GAP bars
            if max(touches) - min(touches) < DT_MIN_GAP:
                continue
            last_touch = max(touches)
            direction = 1 if kind == "resistance" else -1
            for j in range(last_touch + 1, len(closes)):
                if ((closes[j] - level) * direction > level * 0.01
                        and j - last_touch >= PIVOT_ORDER):
                    out.append({"pattern": f"horizontal_{kind}", "level_index": i,
                                "touches": len(touches), "signal_index": j,
                                "day": bars[j].get("day", "")})
                    used_until = j
                    break
    return out


DETECTORS = {
    "double_top": detect_double_top,
    "double_bottom": detect_double_bottom,
    "horizontal_sr": detect_horizontal_sr,
}


# ── backtest harness ─────────────────────────────────────────────────────────
def _forward(closes: list[float], idx: int, h: int) -> float | None:
    if idx + h >= len(closes) or closes[idx] <= 0:
        return None
    return (closes[idx + h] / closes[idx] - 1) * 100


def evaluate_pattern(closes: list[float], detections: list[dict],
                     horizons=HORIZONS) -> dict:
    """Forward-return stats per pattern vs the all-bar baseline, plus
    split-half stability at h=10 (spec §6b rule 3)."""
    per_h = {}
    for h in horizons:
        base = statistics.median([v for v in (_forward(closes, i, h) for i in range(len(closes)))
                                  if v is not None]) if len(closes) > h else None
        fw = [v for v in (_forward(closes, d["signal_index"], h) for d in detections)
              if v is not None]
        per_h[h] = {
            "n": len(fw),
            "median": round(statistics.median(fw), 4) if fw else None,
            "baseline": round(base, 4) if base is not None else None,
            "hit_rate": round(sum(1 for v in fw if v > 0) / len(fw), 4) if fw else None,
        }
    # split-half stability at h=10
    mid = len(detections) // 2
    halves = []
    for part in (detections[:mid], detections[mid:]):
        fw = [v for v in (_forward(closes, d["signal_index"], 10) for d in part) if v is not None]
        halves.append(statistics.median(fw) if fw else None)
    spread = None
    if per_h[10]["median"] is not None and per_h[10]["baseline"] is not None:
        spread = round((per_h[10]["median"] - per_h[10]["baseline"]) * 100, 1)  # bps
    gate = (spread is not None and spread > GATE_SPREAD_BPS
            and per_h[10]["n"] >= GATE_MIN_N
            and halves[0] is not None and halves[1] is not None
            and (halves[0] - per_h[10]["baseline"]) * (halves[1] - per_h[10]["baseline"]) > 0)
    return {"horizons": per_h, "spread_bps_h10": spread,
            "halves_h10": [round(h, 4) if h is not None else None for h in halves],
            "gate_passed": gate}


def run_report(bars_by_code: dict[str, list[dict]]) -> dict:
    """Full spike report over a code→bars store (screener_klines)."""
    report = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "codes": len(bars_by_code), "patterns": {}}
    for name, fn in DETECTORS.items():
        agg_closes: list[float] = []
        detections = []
        for code, bars in bars_by_code.items():
            det = fn(bars)
            if det:
                detections.extend(det)
                # pooled baseline: interleave each code's closes behind its detections
                agg_closes.extend([b["c"] for b in bars])
        report["patterns"][name] = {
            "detections": len(detections),
            **evaluate_pattern(agg_closes, detections),
        }
    any_pass = any(p.get("gate_passed") for p in report["patterns"].values())
    enough = all(p["detections"] >= GATE_MIN_N for p in report["patterns"].values())
    report["verdict"] = ("gate passed — patterns may ship as signals" if any_pass and enough
                         else "insufficient data or no edge — do NOT ship (spec §6b rule 4)"
                         if enough else "insufficient detections — run the kline backfill, then re-run")
    return report


if __name__ == "__main__":
    # After the Phase-A kline backfill has data:
    #   cd web/worker && python -m tradingagents_worker.patterns
    # Prints the §6b spike report; the verdict line is the ship/no-ship call.
    import json

    from .config import SETTINGS
    from .db import Db

    if not SETTINGS.supabase_url:
        raise SystemExit("SUPABASE_URL not configured")
    db = Db()
    codes = [r["code"] for r in db.select_all("screener_universe", {"market": "eq.US"}, "code")]
    bars_by_code: dict[str, list] = {}
    for i in range(0, len(codes), 100):
        chunk = codes[i:i + 100]
        rows = db.select_all("screener_klines",
                             {"market": "eq.US", "code": f"in.({','.join(chunk)})"})
        for b in rows:
            bars_by_code.setdefault(b["code"], []).append(b)
    bars_by_code = {c: sorted(v, key=lambda b: b["day"]) for c, v in bars_by_code.items()}
    print(json.dumps(run_report(bars_by_code), indent=2))
