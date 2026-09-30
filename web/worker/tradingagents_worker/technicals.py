"""Computed technicals over stored moomoo daily bars — pure functions, no IO.

Available in BOTH source modes (spec §5b): they are derived from moomoo
klines, not yfinance. Windows with insufficient bars yield ABSENT keys —
never zeros (spec rule). Definitions:
  perf_w/m/q/h/y  % return vs the close 5/21/63/126/252 bars back
  perf_ytd        % return vs the first close of the current calendar year
  vol_w/vol_m     annualized stdev of daily returns over the window, in %
  sma{n}_pos      last close ÷ SMA{n} − 1, in %
  rsi14           Wilder's RSI
  atr14           Wilder's ATR (absolute, price units)
  avg_vol3m       mean volume over the last 63 bars
  rel_vol         last volume ÷ avg_vol3m
  pos_52w         (last − min252) ÷ (max252 − min252) × 100
"""
from __future__ import annotations

import math
from datetime import datetime, timezone


def _closes(bars):
    return [b["c"] for b in bars if b.get("c") is not None]


def sma(closes: list[float], n: int) -> float | None:
    if len(closes) < n:
        return None
    return sum(closes[-n:]) / n


def _wilder_smooth(values: list[float], n: int) -> float | None:
    if len(values) < n + 1:
        return None
    out = sum(values[:n]) / n
    for v in values[n:]:
        out = (out * (n - 1) + v) / n
    return out


def rsi14(closes: list[float]) -> float | None:
    if len(closes) < 15:
        return None
    gains, losses = [], []
    for a, b in zip(closes, closes[1:]):
        gains.append(max(b - a, 0.0))
        losses.append(max(a - b, 0.0))
    ag, al = _wilder_smooth(gains, 14), _wilder_smooth(losses, 14)
    if ag is None or al is None:
        return None
    if al == 0 and ag == 0:
        return None
    if al == 0:
        return 100.0
    rs = ag / al
    return round(100 - 100 / (1 + rs), 2)


def atr14(bars: list[dict]) -> float | None:
    trs: list[float] = []
    prev_c = None
    for b in bars:
        h, l, c = b.get("h"), b.get("l"), b.get("c")
        if h is None or l is None or c is None:
            continue
        trs.append(h - l if prev_c is None else max(h - l, abs(h - prev_c), abs(l - prev_c)))
        prev_c = c
    out = _wilder_smooth(trs, 14)
    return round(out, 4) if out is not None else None


def perf(closes: list[float], n: int) -> float | None:
    if len(closes) < n + 1 or closes[-1 - n] == 0:
        return None
    return round((closes[-1] / closes[-1 - n] - 1) * 100, 4)


def _stdev_pct(closes: list[float], n: int) -> float | None:
    if len(closes) < n + 1:
        return None
    rets = [b / a - 1 for a, b in zip(closes[-n - 1:], closes[-n:])]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1) if len(rets) > 1 else 0.0
    return round(math.sqrt(var) * math.sqrt(252) * 100, 4)


def perf_ytd(bars: list[dict]) -> float | None:
    closes = _closes(bars)
    if not closes:
        return None
    year = str(datetime.now(timezone.utc).year)
    first = next((b["c"] for b in bars if str(b.get("day", "")).startswith(year)), None)
    if not first:
        return None
    return round((closes[-1] / first - 1) * 100, 4)


def append_snapshot_bar(bars: list[dict], quote: dict,
                        today: str | None = None) -> list[dict]:
    """Synthesize the current session's partial bar from the stored snapshot
    quote and append it, so computed technicals are as fresh as the hourly
    quote refresh — zero extra vendor calls. Rules:
      - session date = the quote's updated_at UTC date (the session the
        snapshot describes), not wall-clock now;
      - appended only when strictly newer than the last stored kline (the
        real daily bar, once the kline fetcher writes it, always wins);
      - without session OHLC the bar falls back to o=h=l=c=price (close-based
        indicators are exact; ATR slightly conservative for that one bar)."""
    bars = list(bars)
    session = today or (str(quote.get("updated_at") or "")[:10] or None)
    if not session or not bars:
        return bars
    if session <= bars[-1].get("day", ""):
        return bars  # real bar already stored, or snapshot older than history
    price = quote.get("price")
    if price is None:
        return bars
    price = float(price)
    o = quote.get("open")
    h = quote.get("high")
    l = quote.get("low")
    bars.append({"day": session,
                 "o": float(o) if o is not None else price,
                 "h": float(h) if h is not None else price,
                 "l": float(l) if l is not None else price,
                 "c": price,
                 "v": quote.get("volume") or 0.0})
    return bars


def compute(bars: list[dict]) -> dict:
    """bars ascending by day. Returns only keys the data actually supports."""
    closes = _closes(bars)
    out: dict = {}
    if len(closes) < 2:
        return out
    last = closes[-1]
    for key, n in (("perf_w", 5), ("perf_m", 21), ("perf_q", 63),
                   ("perf_h", 126), ("perf_y", 252)):
        v = perf(closes, n)
        if v is not None:
            out[key] = v
    y = perf_ytd(bars)
    if y is not None:
        out["perf_ytd"] = y
    for key, n in (("vol_w", 5), ("vol_m", 21)):
        v = _stdev_pct(closes, n)
        if v is not None:
            out[key] = v
    for key, n in (("sma20_pos", 20), ("sma50_pos", 50), ("sma200_pos", 200)):
        s = sma(closes, n)
        if s:
            out[key] = round((last / s - 1) * 100, 4)
    r = rsi14(closes)
    if r is not None:
        out["rsi14"] = r
    a = atr14(bars)
    if a is not None:
        out["atr14"] = a
    vols = [b["v"] for b in bars if b.get("v") is not None]
    if len(vols) >= 63 and sum(vols[-63:]) > 0:
        avg = sum(vols[-63:]) / 63
        out["avg_vol3m"] = round(avg, 2)
        if vols[-1]:
            out["rel_vol"] = round(vols[-1] / avg, 4)
    if len(closes) >= 2:
        lo, hi = min(closes[-252:]), max(closes[-252:])
        if hi > lo:
            out["pos_52w"] = round((last - lo) / (hi - lo) * 100, 4)
    return out
