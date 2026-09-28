"""Stock-page wrapper tests: every new MoomooClient method hits the right path
template with the right method/query — no network (call is monkeypatched)."""
import pytest

from tradingagents_worker.moomoo import MoomooClient


@pytest.fixture()
def client():
    c = MoomooClient("appkey-test", "a" * 32)
    calls = []

    def fake_call(method, path, body=None, query=None, retries=2):
        calls.append({"method": method, "path": path, "body": body, "query": query})
        return {}

    c.call = fake_call  # type: ignore[method-assign]
    c.calls = calls
    return c


def test_cur_kline(client):
    client.cur_kline("US.CHE", ktype=6, autype=1, count=200)
    c = client.calls[-1]
    assert (c["method"], c["path"]) == ("GET", "/quote/US.CHE/cur-kline")
    assert c["query"] == {"ktype": 6, "autype": 1, "count": 200}


def test_rt_data_session_kinds(client):
    client.rt_data("US.CHE", kind="PREMARKET")
    assert client.calls[-1]["path"] == "/quote/US.CHE/rt-data"
    assert client.calls[-1]["query"] == {"type": "PREMARKET"}


def test_capital_flow_family(client):
    client.capital_flow("US.CHE")
    assert client.calls[-1]["path"] == "/quote/US.CHE/capital-flow"
    client.capital_flow_history("US.CHE", period="week")
    assert client.calls[-1]["path"] == "/quote/US.CHE/capital-flow/history"
    assert client.calls[-1]["query"] == {"period": "week"}
    client.capital_distribution("US.CHE")
    assert client.calls[-1]["path"] == "/quote/US.CHE/capital-distribution"


def test_option_chain_omits_none_bounds(client):
    client.option_chain("US.CHE")
    assert client.calls[-1]["path"] == "/quote/US.CHE/option-chain"
    assert not client.calls[-1]["query"]
    client.option_chain("US.CHE", start="2026-10-01", end="2026-12-18")
    assert client.calls[-1]["query"] == {"start": "2026-10-01", "end": "2026-12-18"}
    client.option_expirations("US.CHE")
    assert client.calls[-1]["path"] == "/quote/US.CHE/option-expiration"


def test_financial_statements_params(client):
    client.statements("US.CHE", statement_type=1, financial_type=102)
    c = client.calls[-1]
    assert c["path"] == "/quote/US.CHE/financials/statements"
    assert c["query"] == {"statement_type": 1, "financial_type": 102}


def test_revenue_breakdown_period_optional(client):
    client.revenue_breakdown("US.CHE")
    assert not client.calls[-1]["query"]
    client.revenue_breakdown("US.CHE", date=1767110400, financial_type=7)
    assert client.calls[-1]["query"] == {"date": 1767110400, "financial_type": 7}


def test_research_and_company(client):
    client.analyst_consensus("US.CHE")
    assert client.calls[-1]["path"] == "/quote/US.CHE/research/analyst-consensus"
    client.rating_summary("US.CHE")
    assert client.calls[-1]["path"] == "/quote/US.CHE/research/rating-summary"
    client.company_profile("US.CHE")
    assert client.calls[-1]["path"] == "/quote/US.CHE/company/profile"
    client.company_executives("US.CHE")
    assert client.calls[-1]["path"] == "/quote/US.CHE/company/executives"
    client.earnings_price_history("US.CHE")
    assert client.calls[-1]["path"] == "/quote/US.CHE/financials/earnings-price-history"
    client.earnings_price_move("US.CHE")
    assert client.calls[-1]["path"] == "/quote/US.CHE/financials/earnings-price-move"


def test_find_news_news_type_and_community(client):
    client.find_news("CHE", news_type=2)
    assert client.calls[-1]["query"] == {"symbol": "CHE", "sort_type": 2, "size": 20,
                                         "news_type": 2}
    client.find_community("CHE", community_type=1, sort_type=1, size=50)
    c = client.calls[-1]
    assert c["path"] == "/quote/find-community"
    assert c["query"] == {"symbol": "CHE", "community_type": 1, "sort_type": 1, "size": 50}


def test_plate_endpoints(client):
    client.plate_list("US", "INDUSTRY")
    c = client.calls[-1]
    assert c["path"] == "/quote/plate-list"
    assert c["query"] == {"market": "US", "plate_class": "INDUSTRY"}
    client.plate_stocks("US.LIST2470", limit=60)
    c = client.calls[-1]
    assert c["path"] == "/quote/plate-stock"
    assert c["query"] == {"plate_code": "US.LIST2470", "sort_field": "MarketCapital",
                          "ascend": "false", "limit": 60}


def test_find_community_lang(client):
    client.find_community("MSFT", lang="en")
    assert client.calls[-1]["query"]["lang"] == "en"
