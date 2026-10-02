"""Server exports must never silently truncate a matched cohort."""

import csv
import io

import pytest
from fastapi.testclient import TestClient
from test_api import FakeDb
from tradingagents_api import main as api


@pytest.fixture
def export_client(monkeypatch):
    rows = [
        {
            "code": f"US.S{index}",
            "symbol": f"S{index}",
            "stock_type": "STOCK",
            "price": index,
            "market_cap": 20001 - index,
        }
        for index in range(20001)
    ]
    monkeypatch.setattr(api, "db", FakeDb())
    monkeypatch.setattr(api, "_stored_universe", lambda *args, **kwargs: (rows, None))
    monkeypatch.setattr(api, "_merge_universe_meta", lambda rows, market: rows)
    monkeypatch.setattr(api, "_market_client", lambda: object())
    return TestClient(api.app), rows


@pytest.mark.parametrize("kind", ["csv", "xls"])
def test_oversized_all_export_rejects_without_creating_partial_download(
    export_client, monkeypatch, kind
):
    client, _ = export_client
    monkeypatch.setattr(
        api, "export_row", lambda *args: pytest.fail("Rejected export must not prepare file rows")
    )
    response = client.get(
        "/api/screener", params={"watchlist_only": 0, "export": kind, "scope": "all"}
    )
    assert response.status_code == 413
    assert "20,001 rows" in response.json()["detail"]
    assert "Narrow the filters or export the current page" in response.json()["detail"]
    assert "No partial file" in response.json()["detail"]
    assert "content-disposition" not in response.headers


@pytest.mark.parametrize("kind", ["csv", "xls"])
def test_exact_export_limit_preserves_all_matches(export_client, kind):
    client, rows = export_client
    rows.pop()
    response = client.get(
        "/api/screener", params={"watchlist_only": 0, "export": kind, "scope": "all"}
    )
    assert response.status_code == 200
    assert "20000rows_" in response.headers["content-disposition"]
    if kind == "csv":
        downloaded = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        assert len(downloaded) == 20000
        assert [downloaded[0]["code"], downloaded[-1]["code"]] == ["US.S0", "US.S19999"]
    else:
        assert response.text.count("<Row>") == 20001
        assert ">US.S0<" in response.text and ">US.S19999<" in response.text


@pytest.mark.parametrize("kind", ["csv", "xls"])
def test_page_export_remains_available_for_large_cohort(export_client, kind):
    client, _ = export_client
    response = client.get(
        "/api/screener",
        params={
            "watchlist_only": 0,
            "export": kind,
            "scope": "page",
            "limit": 100,
            "offset": 20000,
        },
    )
    assert response.status_code == 200
    if kind == "csv":
        downloaded = list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))
        assert [row["code"] for row in downloaded] == ["US.S20000"]
    else:
        assert response.text.count("<Row>") == 2
        assert ">US.S20000<" in response.text and ">US.S19999<" not in response.text
