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
from urllib import error as _err
from urllib.parse import urlencode

REST = "https://webapi.moomoo.com/api/v1.0"


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

    # ── signing (Ed25519, per HB §3.2) ────────────────────────────────────
    def _sign(self, ts_ms: int, method: str, path: str, query: str, body: bytes) -> str:
        from cryptography.hazmat.primitives.serialization import load_pem_private_key
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        key = load_pem_private_key(self._key.encode(), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise MoomooError("MOOMOO_PRIVATE_KEY must be an Ed25519 private key (PEM)")
        payload = f"{ts_ms}\n{method}\n{path}\n{query}\n{hashlib.sha256(body).hexdigest()}"
        return base64.b64encode(key.sign(payload.encode())).decode()

    def call(self, method: str, path: str, body: dict | None = None,
             query: dict | None = None, retries: int = 2) -> dict:
        qs = urlencode(query) if query else ""
        full_path = path + (f"?{qs}" if qs else "")
        payload = json.dumps(body).encode() if body is not None else b""
        template = path  # budget keyed by path template (symbol lives in path for some endpoints)
        for attempt in range(retries + 1):
            self.budget.reserve(template)
            ts = int(time.time() * 1000) + self.offset
            headers = {
                "X-Api-Key": self.appkey,
                "X-Timestamp": str(ts),
                "X-Nonce": uuid.uuid4().hex,
                "Authorization": self._sign(ts, method, path, qs, payload),
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
            return out.get("data", {})
        raise MoomooError("unreachable")

    # ── read-only quote operations ────────────────────────────────────────
    def snapshot(self, symbols: list[str]) -> dict:
        """Batch market snapshot: up to 400 codes/call. Denied codes → data.skipped."""
        return self.call("POST", "/quote/snapshot", body={"code_list": symbols[:400]})

    def screen(self, market: str, query: dict, limit: int = 50) -> list:
        """Server-side filter+sort (movers, volume surge, patterns). 300 rows/page max."""
        out = self.call("POST", "/quote/stock-screen", body={
            "market": market, "page": 1, "limit": min(limit, 300), **query})
        return out.get("list", []) if isinstance(out, dict) else out

    def history_kline(self, symbol: str, start: str, end: str, ktype: int = 2, autype: int = 1) -> list:
        """Date-windowed daily bars. NOTE: has_more is unreliable — page by date windows."""
        out = self.call("GET", f"/quote/{symbol}/history-kline",
                        query={"start": start, "end": end, "ktype": ktype, "autype": autype,
                               "count": 1000})
        return out.get("kline_list", []) if isinstance(out, dict) else []

    def find_news(self, keyword: str, sort_type: int = 2, limit: int = 20) -> list:
        """sort_type is mandatory in practice (1=reads, 2=latest) — HB §17.13."""
        out = self.call("GET", "/quote/find-news",
                        query={"keyword": keyword, "sort_type": sort_type, "limit": limit})
        return out.get("news_list", []) if isinstance(out, dict) else []

    def econ_calendar_hot(self) -> list:
        out = self.call("GET", "/quote/economic-calendar/hot")
        return out.get("list", []) if isinstance(out, dict) else []

    @staticmethod
    def server_clock_offset_ms() -> int:
        with urlopen(f"{REST}/server-time", timeout=10) as r:
            server_ms = int(json.loads(r.read())["data"]["timestamp"])
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
    check("US screen gainers", lambda: len(client.screen("US", {"basic_filter": {"sort_field": "pct_change", "sort_type": 1}})))
    check("history-kline SPY 5y window", lambda: len(client.history_kline("US.SPY", "2021-01-01", "2021-01-31")))
    check("find-news NVDA", lambda: len(client.find_news("NVDA")))
    return out
