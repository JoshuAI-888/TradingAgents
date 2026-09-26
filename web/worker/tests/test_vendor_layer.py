"""Vendor-layer tests: budget ledger, TTL cache, depth presets, discovery dedupe."""
from __future__ import annotations

import pytest

from tradingagents_worker.moomoo import Budget, RateLimited
from tradingagents_worker.runner import DEPTH_PRESETS
from tradingagents_worker.ttl_cache import TtlCache


def test_budget_keyed_by_template_and_fills():
    b = Budget(limit=3)
    for _ in range(3):
        b.reserve("/quote/snapshot")
    with pytest.raises(RateLimited):
        b.reserve("/quote/snapshot")
    # independent per template
    b.reserve("/quote/stock-screen")


def test_ttl_cache_roundtrip_and_ttl_categories():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        c = TtlCache(root=d)
        k = c.key("quotes", "snapshot", ["US.SPY"])
        c.put("quotes", k, {"a": 1})
        assert c.get("quotes", k) == {"a": 1}
        k2 = c.key("news", "find-news", "latest")   # different category → different key & window
        c.put("news", k2, [{"t": 1}])
        assert c.get("news", k2) == [{"t": 1}]
        assert c.get("news", c.key("news", "never-cached")) is None


def test_depth_presets_shape():
    assert DEPTH_PRESETS["fast"]["max_debate_rounds"] == 0
    assert len(DEPTH_PRESETS["fast"]["selected_analysts"]) == 2
    assert DEPTH_PRESETS["deep"]["max_risk_discuss_rounds"] == 2


def test_discovery_candidates_dedupe_and_shape(fake_db):
    from tradingagents_worker.discovery import _watchlist_candidates
    out = _watchlist_candidates(fake_db, ["NVDA", "MSFT", "0700.HK", "CSL.AX"])
    assert len(out) == 1 and "4 tickers" in out[0]["title"]
    assert out[0]["trigger_type"] == "watchlist"


def test_moomoo_signing_payload_shape():
    """Signing string must be ts\\nMETHOD\\npath\\nquery\\nsha256(body) — verify w/ a throwaway key."""
    import base64, hashlib
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives import serialization
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode()
    from tradingagents_worker.moomoo import MoomooClient
    c = MoomooClient("test-appkey", pem)
    ts, method, path, query, body = 1727000000000, "POST", "/quote/snapshot", "", b"{}"
    sig = c._sign(ts, method, path, query, body)
    pub = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    payload = f"{ts}\n{method}\n{path}\n{query}\n{hashlib.sha256(body).hexdigest()}"
    Ed25519PublicKey.from_public_bytes(pub).verify(base64.b64decode(sig), payload.encode())
    assert True  # verify() raises on mismatch
