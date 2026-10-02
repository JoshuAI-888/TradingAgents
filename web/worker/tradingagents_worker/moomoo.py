"""Moomoo cloud REST client (worker-owned; AppKey Ed25519 signing) + read-only
quote operations per the verified exploration (ecosystem-survey/moomoo-api).

Implements: snapshot (batch 400), stock-screen (server-side sort), history-kline
(date-windowed paging), find-news (sort_type mandatory), economic calendar,
budget ledger keyed by PATH TEMPLATE (30/min shared across symbols), and the
HTTP-200 rate_limited handling. Ed25519 via cryptography; never logs key material.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
import uuid

from .net import urlopen
from datetime import datetime, timezone
from urllib import error as _err, request as _rq
from urllib.parse import urlencode

REST = "https://webapi.moomoo.com"
API = "/api/v1.0"  # part of the signed path — omitting it fails auth (-12006)


class MoomooError(RuntimeError):
    pass


class RateLimited(MoomooError):
    def __init__(self, retry_after: float, path: str):
        super().__init__(f"rate_limited on {path}; retry after {retry_after}s")
        self.retry_after = retry_after


class Budget:
    """MinuteBudget keyed by path TEMPLATE (never the concrete path)."""

    def __init__(self, limit: int = 30):
        self.limit = limit
        self._windows: dict[str, tuple[int, float]] = {}

    def reserve(self, template: str):
        minute = int(time.time() // 60)
        cur = self._windows.get(template)
        if cur and cur[0] == minute:
            if cur[1] >= self.limit:
                raise RateLimited((cur[0] + 1) * 60 - time.time() + 1, template)
            self._windows[template] = (minute, cur[1] + 1)
        else:
            self._windows[template] = (minute, 1)


class MoomooClient:
    def __init__(self, appkey: str, private_key_pem: str, budget: Budget | None = None, clock_offset_ms: int = 0):
        self.appkey = appkey
        self._key = private_key_pem
        self.budget = budget or Budget()
        self.offset = clock_offset_ms

    def _load_key(self):
        """Accept PEM, base64 PKCS#8 DER, or a raw 32-byte Ed25519 seed (HB §3.2)."""
        import base64 as _b64

        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import (
            load_der_private_key,
            load_pem_private_key,
        )
        raw = self._key.strip()
        if "-----BEGIN" in raw:
            key = load_pem_private_key(raw.encode(), password=None)
        else:
            try:
                der = _b64.b64decode(raw, validate=True)
            except Exception:
                der = b""
            if len(der) > 32:
                key = load_der_private_key(der, password=None)
            elif len(der) == 32:
                key = Ed25519PrivateKey.from_private_bytes(der)
            else:
                key = None
        if not isinstance(key, Ed25519PrivateKey):
            raise MoomooError(
                "MOOMOO_PRIVATE_KEY must be an Ed25519 key: PEM, base64 PKCS#8 DER, or raw 32-byte seed")
        return key

    # ── signing (Ed25519, per HB §3.2) ────────────────────────────────────
    def _sign(self, ts_ms: int, method: str, path: str, query: str, body: bytes) -> str:
        key = self._load_key()
        # A body-less request signs the EMPTY STRING, not sha256("") (HB §3.2:
        # `sha256_hex(body) or ''`) — hashing b"" fails every GET with -12006.
        body_part = hashlib.sha256(body).hexdigest() if body else ""
        payload = f"{ts_ms}\n{method}\n{path}\n{query}\n{body_part}"
        return base64.b64encode(key.sign(payload.encode())).decode()

    def call(self, method: str, path: str, body: dict | None = None,
             query: dict | None = None, retries: int = 2) -> dict:
        qs = urlencode(query) if query else ""
        sign_path = API + path
        full_path = sign_path + (f"?{qs}" if qs else "")
        # Compact separators — match the verified PoC byte-for-byte so the
        # body hash the server re-computes is the one we signed.
        payload = json.dumps(body, separators=(",", ":")).encode() if body is not None else b""
        template = path  # budget keyed by path template (symbol lives in path for some endpoints)
        for attempt in range(retries + 1):
            self.budget.reserve(template)
            ts = int(time.time() * 1000) + self.offset
            headers = {
                "X-Api-Key": self.appkey,
                "X-Timestamp": str(ts),
                "X-Nonce": uuid.uuid4().hex,
                "Authorization": self._sign(ts, method, sign_path, qs, payload),
                "Content-Type": "application/json",
            }
            req = _rq.Request(f"{REST}{full_path}", data=payload or None, method=method, headers=headers)
            try:
                with urlopen(req, timeout=20) as resp:
                    out = json.loads(resp.read())
            except _err.HTTPError as e:
                raise MoomooError(f"{method} {path} -> HTTP {e.code}: {e.read()[:200]!r}") from e
            # Refusals ride HTTP 200: ret_code -11 + error.code rate_limited (HB §17.8)
            if out.get("ret_code") == -11 and (out.get("error") or {}).get("code") == "rate_limited":
                retry_after = float((out.get("error") or {}).get("retry_after") or 5)
                if attempt >= retries:
                    raise RateLimited(retry_after, template)
                time.sleep(retry_after)
                continue
            if out.get("ret_code") != 0:
                raise MoomooError(f"{method} {path} -> ret_code {out.get('ret_code')}: {str(out.get('ret_msg'))[:200]}")
            data = out.get("data", {})
            # Screening pagination is a sibling of data, not part of data.items.
            # Retaining it enables complete cohorts without fabricating totals.
            if isinstance(data, dict) and isinstance(out.get("pagination"), dict):
                data = {**data, "pagination": out["pagination"]}
            return data
        raise MoomooError("unreachable")

    # ── read-only quote operations ────────────────────────────────────────
    def snapshot(self, symbols: list[str]) -> dict:
        """Batch market snapshot: up to 400 codes/call. Denied codes → data.skipped."""
        return self.call("POST", "/quote/snapshot", body={"code_list": symbols[:400]})

    def screen(self, screen_queries: list, retrieve_queries: list | None = None,
               sort: dict | None = None, limit: int = 50) -> list:
        """Server-side screen. Body is structured query objects (HB: screen_queries
        is mandatory; the response's matching rows are in `items`)."""
        body: dict = {"screen_queries": screen_queries, "limit": min(limit, 300)}
        if retrieve_queries:
            body["retrieve_queries"] = retrieve_queries
        if sort:
            body["sort"] = sort
        out = self.call("POST", "/quote/stock-screen", body=body)
        return (out.get("items") or []) if isinstance(out, dict) else []

    def history_kline(self, symbol: str, start: str, end: str, ktype: int = 2, autype: int = 1,
                      extended_time: int | None = None) -> list:
        """Date-windowed bars (ktype 1..9 = 1m/D/W/M/Y/5/15/30/60m). NOTE: has_more
        is unreliable — page by date windows. extended_time (US 1-min only):
        1 = include pre/after market, 2 = include overnight."""
        q = {"start": start, "end": end, "ktype": ktype, "autype": autype, "count": 1000}
        if extended_time is not None:
            q["extended_time"] = extended_time
        out = self.call("GET", f"/quote/{symbol}/history-kline", query=q)
        return out.get("kline_list", []) if isinstance(out, dict) else []

    def find_news(self, keyword: str, sort_type: int = 2, limit: int = 20,
                  news_type: int | None = None, lang: str | None = None) -> list:
        """Keyword search. The required param is confusingly named `symbol`; page
        size is `size`; `sort_type` 2 = latest (HB §17.13: empty without sort_type).
        `news_type` 1=News(POST) 2=Announcement(NOTICE) 3=Report(REPORT).
        `lang` en/zh-CN/zh-HK/ja — results come back provider-localized without it.
        Live data is a BARE LIST (no container key)."""
        q = {"symbol": keyword, "sort_type": sort_type, "size": min(limit, 50)}
        if news_type:
            q["news_type"] = news_type
        if lang:
            q["lang"] = lang
        out = self.call("GET", "/quote/find-news", query=q)
        if isinstance(out, list):
            return out
        if not isinstance(out, dict):
            return []
        return out.get("news_list") or out.get("list") or []

    def econ_calendar_hot(self) -> list:
        out = self.call("GET", "/quote/economic-calendar/hot")
        return out.get("list", []) if isinstance(out, dict) else []

    # ── stock detail page (read-only; one wrapper per path template) ─────
    # Each returns the raw `data` dict so the API layer owns normalization.
    def _get(self, path: str, **query) -> dict:
        q = {k: v for k, v in query.items() if v is not None}
        out = self.call("GET", path, query=q or None)
        return out if isinstance(out, dict) else {}

    def cur_kline(self, symbol: str, ktype: int = 2, autype: int = 1, count: int = 100) -> dict:
        """Latest forming bars incl. today (ktype: 1=1m 2=D 3=W 4=M 5=Y 6/7/8/9=5/15/30/60m)."""
        return self._get(f"/quote/{symbol}/cur-kline", ktype=ktype, autype=autype, count=count)

    def rt_data(self, symbol: str, kind: str = "FULL") -> dict:
        """Intraday minute line. kind: NORMAL/FULL/PREMARKET/AFTERHOURS (US)."""
        return self._get(f"/quote/{symbol}/rt-data", type=kind)

    def capital_flow(self, symbol: str) -> dict:
        return self._get(f"/quote/{symbol}/capital-flow")

    def capital_flow_history(self, symbol: str, period: str = "day") -> dict:
        return self._get(f"/quote/{symbol}/capital-flow/history", period=period)

    def capital_distribution(self, symbol: str) -> dict:
        """Today's in/out by order size (super/large/mid/small) — the XL/L/M/S buckets."""
        return self._get(f"/quote/{symbol}/capital-distribution")

    def option_expirations(self, symbol: str) -> dict:
        return self._get(f"/quote/{symbol}/option-expiration")

    def option_chain(self, symbol: str, start: str | None = None, end: str | None = None) -> dict:
        """Static contracts (≤20 expiries/call); prices come from snapshot on the codes."""
        return self._get(f"/quote/{symbol}/option-chain", start=start, end=end)

    def statements(self, symbol: str, statement_type: int, financial_type: int | None = None,
                   limit: int | None = None) -> dict:
        """F10 statements: statement_type 1/2/3/4; financial_type per naming
        dictionary (1=Q1 2=H1 3=Q3 4=Q4 5=cumH1 6=cum3Q 7=annual) — omit for the
        server default. Live rejects 102 despite docs; container is `report_list`."""
        return self._get(f"/quote/{symbol}/financials/statements",
                         statement_type=statement_type, financial_type=financial_type,
                         limit=limit)

    def revenue_breakdown(self, symbol: str, date: int | None = None,
                          financial_type: int | None = None) -> dict:
        """Period picker = screen_date_list entries {date (s), financial_type}."""
        return self._get(f"/quote/{symbol}/financials/revenue-breakdown",
                         date=date, financial_type=financial_type)

    def earnings_price_history(self, symbol: str) -> dict:
        return self._get(f"/quote/{symbol}/financials/earnings-price-history")

    def earnings_price_move(self, symbol: str) -> dict:
        return self._get(f"/quote/{symbol}/financials/earnings-price-move")

    def dividends(self, symbol: str) -> dict:
        """Dividend history (max 100, newest first): ex_date, dividend_per_share,
        currency — verified live (HB §9.12); container key is undocumented."""
        return self._get(f"/quote/{symbol}/corporate-actions/dividends")

    def analyst_consensus(self, symbol: str) -> dict:
        return self._get(f"/quote/{symbol}/research/analyst-consensus")

    def rating_summary(self, symbol: str) -> dict:
        return self._get(f"/quote/{symbol}/research/rating-summary")

    def company_profile(self, symbol: str) -> dict:
        return self._get(f"/quote/{symbol}/company/profile")

    def company_executives(self, symbol: str) -> dict:
        return self._get(f"/quote/{symbol}/company/executives")

    def find_community(self, keyword: str, community_type: int = 1,
                       sort_type: int = 2, size: int = 20, lang: str | None = None) -> list:
        """Community search (FEED/TOPIC/LIVE); no pagination — latest N only.
        `lang` en/zh-CN/zh-HK/ja (results come provider-localized without it).
        Live data is a BARE LIST (no container key)."""
        q = {"symbol": keyword, "community_type": community_type,
             "sort_type": sort_type, "size": min(size, 50)}
        if lang:
            q["lang"] = lang
        out = self.call("GET", "/quote/find-community", query=q)
        if isinstance(out, list):
            return out
        if not isinstance(out, dict):
            return []
        return out.get("community_list") or out.get("list") or []

    def plate_list(self, market: str, plate_class: str = "INDUSTRY") -> list:
        """Sector/plate list for a market (class: ALL/INDUSTRY/REGION/CONCEPT/OTHER;
        REGION is SH/SZ only). Live container: plate_list."""
        out = self.call("GET", "/quote/plate-list",
                        query={"market": market, "plate_class": plate_class})
        return (out or {}).get("plate_list") or [] if isinstance(out, dict) else []

    def plate_stocks(self, plate_code: str, limit: int = 60) -> list:
        """Members of a plate, market-cap desc. Live sort_field enum: MARKET_VAL
        ('MarketCapital' is rejected). Live container: stock_list."""
        out = self.call("GET", "/quote/plate-stock",
                        query={"plate_code": plate_code,
                               "sort_field": "MARKET_VAL",
                               "ascend": "false", "limit": min(limit, 1000)})
        return (out or {}).get("stock_list") or [] if isinstance(out, dict) else []

    @staticmethod
    def server_clock_offset_ms() -> int:
        with urlopen(f"{REST}{API}/server-time", timeout=10) as r:
            out = json.loads(r.read())

        def _find_ms(node):
            """The endpoint's shape moved across versions — accept timestamp /
            server_time_ms at any depth (handbook §3.1)."""
            if isinstance(node, dict):
                for k in ("timestamp", "server_time_ms"):
                    if k in node:
                        return int(node[k])
                for v in node.values():
                    got = _find_ms(v)
                    if got is not None:
                        return got
            elif isinstance(node, list):
                for v in node:
                    got = _find_ms(v)
                    if got is not None:
                        return got
            return None

        server_ms = _find_ms(out)
        if server_ms is None:
            raise MoomooError(f"server-time: unexpected shape {str(out)[:120]}")
        return server_ms - int(time.time() * 1000)


def probe(client: MoomooClient) -> dict:
    """Read-only Phase-0 probe: verify tier, markets, live-ness. No secrets echoed."""
    out: dict = {"checked_at": datetime.now(timezone.utc).isoformat(), "checks": []}
    def check(name, fn):
        try:
            v = fn()
            out["checks"].append({"name": name, "ok": True, "summary": v})
        except Exception as e:
            out["checks"].append({"name": name, "ok": False, "error": str(e)[:200]})
    check("server-time", lambda: f"offset {client.server_clock_offset_ms()}ms")
    check("US snapshot (SPY,QQQ,NVDA)", lambda: len((client.snapshot(["US.SPY", "US.QQQ", "US.NVDA"]) or {}).get("snapshot_list", [])))
    check("HK snapshot (00700)", lambda: len((client.snapshot(["HK.00700"]) or {}).get("snapshot_list", [])))
    check("AU snapshot real-time? (CBA.AX)", lambda: len((client.snapshot(["AU.CBA"]) or {}).get("snapshot_list", [])))
    check("stock-screen (verified HK query)", lambda: len(client.screen(
        [{"simple_field_query": {"simple_field": 1, "screen_value_list": [1]}}], limit=3)))
    check("history-kline SPY 5y window", lambda: len(client.history_kline("US.SPY", "2021-01-01", "2021-01-31")))
    check("find-news NVDA", lambda: len(client.find_news("NVDA")))
    check("economic calendar", lambda: len(client.econ_calendar_hot()))
    return out
