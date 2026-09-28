"""Stock-page routes: fixtures mode (offline), estimates stub, SPA catch-all.

No network, no keys — TA_STOCK_FIXTURES=1 serves recorded payloads.
"""
import os

import pytest
from fastapi.testclient import TestClient

from tradingagents_api import main as api


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("TA_STOCK_FIXTURES", "1")
    monkeypatch.setattr(api, "_screener_cache", None)
    monkeypatch.chdir(tmp_path)
    with TestClient(api.app) as c:
        yield c


def test_quote_returns_snapshot_item(client):
    r = client.get("/api/stock/CHE-US/quote")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert body["code"] == "US.CHE"
    assert body["last_price"] == 512.16
    for f in ("pe_ttm_ratio", "total_market_val", "highest52weeks_price",
              "turnover_rate", "pre_price", "after_price", "lot_size",
              "dividend_ratio_ttm"):
        assert f in body


def test_candles_ranges_and_validation(client):
    r = client.get("/api/stock/CHE/candles", params={"range": "D"})
    body = r.json()
    assert body["available"] is True and body["range"] == "D"
    assert len(body["bars"]) == 370
    assert {"time_key", "open", "close", "high", "low", "volume", "turnover"} <= set(body["bars"][0])
    r5 = client.get("/api/stock/CHE/candles", params={"range": "5D"}).json()
    assert r5["available"] and r5["bars"]
    assert client.get("/api/stock/CHE/candles", params={"range": "2W"}).status_code == 400


def test_intraday_sessions(client):
    body = client.get("/api/stock/CHE/intraday", params={"kind": "FULL"}).json()
    assert body["available"] is True
    pts = body["section_list"][0]["point_list"]
    assert len(pts) == 391 and "cur_price" in pts[0]
    assert client.get("/api/stock/CHE/intraday", params={"kind": "WEEKEND"}).status_code == 400


def test_capital_includes_distribution(client):
    body = client.get("/api/stock/CHE/capital", params={"period": "day"}).json()
    assert body["available"] is True
    assert body["flow"] and body["distribution"]["capital_in_super"] == 2237140.0


def test_options_chain_with_quotes(client):
    body = client.get("/api/stock/CHE/options").json()
    assert body["available"] is True
    assert body["expiry"] == "2026-10-16"
    assert len(body["expirations"]) == 4
    strikes = {c["strike_price"] for c in body["chain"]}
    assert 510.0 in strikes
    assert all(c["option_type"] in ("CALL", "PUT") for c in body["chain"])


def test_statements_pivot_source(client):
    body = client.get("/api/stock/CHE/financials/statements").json()
    assert body["available"] is True and isinstance(body["periods"], list)
    top = body["periods"][0]
    assert top["period_text"] == "2026/Q2" and top["accounting_standards"] == "US_GAAP"
    names = " | ".join(i["display_name"] for i in top["item_list"])
    assert "Total Revenue" in names and "Diluted EPS" in names
    assert top["item_list"][0]["data"] == 673250000  # live `data` field, full units
    assert client.get("/api/stock/CHE/financials/statements",
                      params={"statement_type": 9}).status_code == 400
    assert client.get("/api/stock/CHE/financials/statements",
                      params={"financial_type": 102}).status_code == 400


def test_revenue_breakdown_live_shape(client):
    body = client.get("/api/stock/CHE/financials/revenue").json()
    assert body["available"] is True
    dims = {b["type"]: b["item_list"] for b in body["breakdown_list"]}
    assert dims[8][0]["name"] == "VITAS"
    assert abs(dims[8][0]["ratio"] + dims[8][1]["ratio"] - 100) < 0.01
    assert dims[4][0]["main_oper_income"] == 2529978000
    assert body["screen_date_list"][0]["period_text"] == "2025/FY"


def test_earnings(client):
    body = client.get("/api/stock/CHE/earnings").json()
    assert body["available"] is True and len(body["list"]) == 3
    top = body["list"][0]
    assert top["pub_trading_day_str"] == "2026-07-28"
    assert top["close_price"] == 551.551 and top["last_close_price"] == 552.18


def test_research(client):
    body = client.get("/api/stock/CHE/research").json()
    assert body["available"] is True
    c = body["consensus"]
    assert (c["buy"], c["hold"], c["sell"]) == (50.0, 50.0, 0.0)
    assert c["average"] == 584.5 and c["num_of_target_analysts"] == 4
    assert len(body["detail"]["inst_rating_summary_list"]) == 4


def test_news_types(client):
    for t, marker in (("news", "post:"), ("notice", "notice:"), ("report", "post:")):
        body = client.get("/api/stock/CHE/news", params={"type": t}).json()
        assert body["available"] is True and body["news_list"]
    assert client.get("/api/stock/CHE/news", params={"type": "x"}).status_code == 400


def test_company_and_community(client):
    comp = client.get("/api/stock/CHE/company").json()
    assert comp["available"] is True
    items = {l["name"]: l["value"] for l in comp["profile"]["items"]}
    assert items["ISIN"] == "US16359R1032"
    assert comp["executives"][0]["name"] == "Kevin J. Mcnamara"
    com = client.get("/api/stock/CHE/community").json()
    assert com["available"] is True and com["community_list"][0]["community_type"] == "FEED"


def test_upstream_error_becomes_available_false(client, monkeypatch):
    """A flaky moomoo endpoint must degrade, never 500 the stock tab."""

    class Boom:
        def snapshot(self, codes):
            raise RuntimeError("gateway timeout")

    monkeypatch.delenv("TA_STOCK_FIXTURES", raising=False)
    monkeypatch.setattr(api, "_market_client", lambda: Boom())
    r = client.get("/api/stock/CHE-US/quote")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "gateway timeout" in body["reason"]


def test_estimates_empty_becomes_unavailable(client, monkeypatch):
    monkeypatch.delenv("TA_STOCK_FIXTURES", raising=False)
    monkeypatch.setattr(api, "_estimates_fetch", lambda s: {
        "symbol": s.upper(), "revenue_estimate": [], "earnings_estimate": [],
        "eps_trend": [], "earnings_history": [], "calendar": {}})
    body = client.get("/api/stock/CHE/estimates").json()
    assert body["available"] is False
    assert "no data" in body["reason"]


def test_meta_exposes_stock_page_mode(client):
    body = client.get("/api/meta").json()
    assert body["stock_page"]["fixtures_mode"] is True


def test_estimates_stubbed(client, monkeypatch):
    monkeypatch.setattr(api, "_estimates_fetch", lambda s: {
        "symbol": s.upper(), "revenue_estimate": [{"period": "0q", "avg": 685036720}],
        "earnings_estimate": [], "eps_trend": [], "earnings_history": [], "calendar": {}})
    body = client.get("/api/stock/CHE/estimates").json()
    assert body["available"] is True
    assert body["revenue_estimate"][0]["avg"] == 685036720


def test_estimates_fixture_mode(client):
    body = client.get("/api/stock/CHE/estimates").json()
    assert body["available"] is True and body["earnings_history"][0]["eps_actual"] == 5.27


def test_spa_catch_all_serves_index(client, monkeypatch, tmp_path):
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html><div id='page'></div></html>")
    monkeypatch.setenv("PORTAL_STATIC_DIR", str(static))
    r = client.get("/stock/CHE-US")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "id='page'" in r.text
    assert client.get("/stock/CHE-US/options-chain").status_code == 200


def test_stock_code_normalization():
    assert api._stock_code("CHE-US") == "US.CHE"
    assert api._stock_code("che") == "US.CHE"
    assert api._stock_code("HK.00700") == "HK.00700"


def test_sectors_and_members(client):
    s = client.get("/api/sectors", params={"market": "US"}).json()
    assert s["available"] is True and s["sectors"][0]["plate_name"] == "Pharmaceuticals"
    r = client.get("/api/sectors/stocks",
                   params={"plate": "US.LIST2470"}).json()
    assert r["available"] is True and r["rows"][0]["symbol"] == "NVDA"
    assert "price" in r["rows"][0] and "pct" in r["rows"][0]
