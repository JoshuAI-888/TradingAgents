"""Nightly yfinance enrichment fetcher. Lazy-imports yfinance (optional runtime
dep, mirroring the estimates route); failure to import raises EnrichUnavailable
so the cron logs a clean error instead of a traceback. Per-ticker failures are
skipped — a partial batch beats no batch (spec §5b: absent = no data).

Code mapping: US.AAPL → AAPL; HK.00700 → 0700.HK (Phase A runs US only; the
HK branch is here so the mapping rule lives in exactly one place).
"""
from __future__ import annotations

from datetime import datetime, timezone
import math

from .enrich_fields import YF_FIELDS, apply_transform


class EnrichUnavailable(RuntimeError):
    pass


def to_yahoo_symbol(code: str, market: str = "US") -> str:
    sym = code.split(".", 1)[1] if "." in code else code
    if market == "HK":
        return str(int(sym)).zfill(4) + ".HK"  # moomoo 00700 → yahoo 0700.HK
    return sym


def _default_import():
    import yfinance as yf  # lazy: optional runtime dependency
    return yf


def fetch_yf_enrichment(codes: list[str], prices: dict[str, float],
                        market: str = "US", yf_module=None,
                        import_fn=_default_import) -> list[dict]:
    yf = yf_module
    if yf is None:
        try:
            yf = import_fn()
        except ImportError as e:
            raise EnrichUnavailable(f"yfinance not installed: {e}") from e
    rows: list[dict] = []
    sym_of = {c: to_yahoo_symbol(c, market) for c in codes}
    chunk_size = 200
    codes = [c for c in codes if sym_of[c]]
    for i in range(0, len(codes), chunk_size):
        chunk = codes[i:i + chunk_size]
        try:
            tk = yf.Tickers(" ".join(sym_of[c] for c in chunk))
        except Exception:
            continue  # a dead batch must not kill the nightly run
        for code in chunk:
            try:
                info = tk.tickers[sym_of[code]].info
            except Exception:
                continue
            if not isinstance(info, dict):
                continue
            data: dict = {}
            price = prices.get(code)
            mcap = None
            try:
                mcap = float(info.get("marketCap")) if info.get("marketCap") else None
            except (TypeError, ValueError):
                pass
            for ykey, (okey, transform) in YF_FIELDS.items():
                if isinstance(info.get(ykey), bool):
                    continue
                if okey == "_lt_de":
                    # staged: equity arrives as totalStockholderEquity on the
                    # same info dict; combine before exposing
                    eq = info.get("totalStockholderEquity") or info.get("StockholdersEquity")
                    if eq is not None and not isinstance(eq, bool):
                        got = apply_transform({"lt": info.get(ykey), "eq": eq},
                                              transform)
                        if type(got) in (int, float) and math.isfinite(got):
                            data["lt_debt_eq"] = got
                    continue
                got = apply_transform(info.get(ykey), transform,
                                      price=price, market_cap=mcap)
                text_field = okey in {"country", "sector", "industry", "website", "earnings_date", "ex_div_date"}
                if text_field:
                    if isinstance(got, str) and got.strip():
                        data[okey] = got.strip()
                elif type(got) in (int, float) and math.isfinite(got):
                    data[okey] = got
            # Even an empty successful info response replaces vanished fields.
            # Transport/ticker failures above remain absent and keep the old clock.
            rows.append({"market": market, "code": code, "data": data,
                         "source": "yfinance", "as_of": datetime.now(timezone.utc).isoformat()})
    return rows
