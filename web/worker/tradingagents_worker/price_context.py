"""Verified as-of price context: the bridge between the report chart and the agents.

At run start the worker renders the engine's verified market snapshot for
(ticker, trade_date) — the latest OHLCV row on or before the date, common
indicators, recent closes — and does two things with it:

  * passes the text into the graph (``price_context`` state field), so every
    debate and synthesis agent argues over the same exact numbers instead of
    only what the analysts happened to cite, and
  * persists the snapshot's own rows into price_bars, which /api/bars serves
    the report chart with the same as-of cutoff — the chart shows the data
    the agents were shown, not a lookalike from another vendor.

Never fails a run: any error returns None and the run proceeds without it
(pre-change behavior). Uses the same yfinance source as the per-run enrich,
so the post-run enrich refresh overwrites with identical same-day values.
"""

from __future__ import annotations


def build_price_context(ticker: str, trade_date: str) -> dict | None:
    """Verified snapshot for (ticker, trade_date): {text, rows, latest_date} or None."""
    try:
        from tradingagents.dataflows.vendors.yahoo.snapshot import snapshot_with_rows

        out = snapshot_with_rows(ticker, trade_date)
    except Exception as e:  # noqa: BLE001 — context is an enhancement, never a gate
        print(
            f"[price_context] {ticker} @ {trade_date}: unavailable ({e}); run proceeds without it",
            flush=True,
        )
        return None
    if not out.get("rows"):
        return None
    return {"text": out["text"], "rows": out["rows"], "latest_date": out.get("latest_date")}
