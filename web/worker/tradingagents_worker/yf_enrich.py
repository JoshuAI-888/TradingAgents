"""Nightly yfinance enrichment fetcher. Lazy-imports yfinance (optional runtime
dep, mirroring the estimates route); failure to import raises EnrichUnavailable
so the cron logs a clean error instead of a traceback. Per-ticker failures are
skipped — a partial batch beats no batch (spec §5b: absent = no data).

Code mapping: US.AAPL → AAPL; HK.00700 → 0700.HK (Phase A runs US only; the
HK branch is here so the mapping rule lives in exactly one place).
"""
from __future__ import annotations

from datetime import datetime, timezone
import re
from collections import Counter

from .enrich_fields import YF_FIELDS, YF_FIELD_CONTRACTS, apply_transform, finite_number


class EnrichUnavailable(RuntimeError):
    pass


def to_yahoo_symbol(code: str, market: str = "US") -> str:
    if market not in ('US','HK') or not isinstance(code,str) or not re.fullmatch(re.escape(market)+r'\.[A-Z0-9][A-Z0-9._-]{0,30}',code):
        return ''
    sym = code.split(".", 1)[1]
    if market == "HK":
        if not sym.isdigit() or not 0<int(sym)<100000:return ''
        return str(int(sym)).zfill(4) + ".HK"  # moomoo 00700 → yahoo 0700.HK
    return sym.replace('.', '-')  # preserve canonical identity; Yahoo uses BRK-B.


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
    # Ignore malformed inputs before dictionary construction; retain each exact
    # canonical code once and fail closed on distinct codes sharing a Yahoo alias.
    codes = list(dict.fromkeys(c for c in codes if isinstance(c, str)))
    sym_of = {c: to_yahoo_symbol(c, market) for c in codes}
    aliases = Counter(sym_of.values())
    chunk_size = 200
    codes = [c for c in codes if sym_of[c] and aliases[sym_of[c]]==1]
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
            if info and info.get('symbol') != sym_of[code]:
                continue  # missing/wrong identity is a failed fetch, not empty success.
            data: dict = {}
            # Same-response aggregate money ratios avoid cross-provider prices
            # and per-share basis ambiguity. `prices` stays for caller compatibility.
            currency, financial_currency = info.get('currency'), info.get('financialCurrency')
            compatible = isinstance(currency,str) and bool(re.fullmatch(r'[A-Z]{3}',currency)) and currency==financial_currency
            mcap = finite_number(info.get('marketCap')) if compatible else None
            for ykey, (okey, transform) in YF_FIELDS.items():
                if isinstance(info.get(ykey), bool):
                    continue
                if okey == "_lt_de":
                    # staged: equity arrives as totalStockholderEquity on the
                    # same info dict; combine before exposing
                    # Zero/negative/invalid primary equity cannot borrow a
                    # positive alternate. Conflicting supplied legs are unknown.
                    primary, alternate = info.get("totalStockholderEquity"), info.get("StockholdersEquity")
                    if primary is not None and alternate is not None and primary != alternate:
                        continue
                    eq = primary if primary is not None else alternate
                    if eq is not None and not isinstance(eq, bool):
                        got = apply_transform({"lt": info.get(ykey), "eq": eq},
                                              transform)
                        if finite_number(got) is not None:
                            data["lt_debt_eq"] = got
                    continue
                got = apply_transform(info.get(ykey), transform,
                                      market_cap=mcap)
                text_field = okey in {"country", "sector", "industry", "website", "earnings_date", "ex_div_date"}
                if text_field:
                    if isinstance(got, str) and got.strip():
                        data[okey] = got.strip()
                elif finite_number(got) is not None:
                    data[okey] = got
            # Even an empty successful info response replaces vanished fields.
            # Transport/ticker failures above remain absent and keep the old clock.
            from .provider_context import info_context
            rows.append({"provider_context":info_context(info,code),"market": market, "code": code, "data": data,
                         "source": "yfinance", "field_contracts": dict(YF_FIELD_CONTRACTS),
                         "as_of": datetime.now(timezone.utc).isoformat()})
    return rows
