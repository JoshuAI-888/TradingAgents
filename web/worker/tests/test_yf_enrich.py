"""yfinance fetcher: code mapping, transforms, per-ticker failure isolation."""
import tradingagents_worker.yf_enrich as ye


class FakeInfo(dict):
    pass


class FakeTicker:
    def __init__(self, info):
        self._info = info

    @property
    def info(self):
        if isinstance(self._info, Exception):
            raise self._info
        return self._info


class FakeTickers:
    """Mimics yf.Tickers("A B").tickers[<sym>].info"""
    def __init__(self, infos):
        self.tickers = {s: FakeTicker(i) for s, i in infos.items()}


INFO_A = {"forwardPE": 22.5, "shortPercentOfFloat": 0.021, "country": "USA",
          "earningsTimestamp": 1747000000, "totalCashPerShare": 4.0}
INFO_B = {"beta": 1.1}


def test_fetch_maps_codes_and_transforms():
    yf = FakeTickers({"AAPL": INFO_A, "MSFT": INFO_B})
    rows = ye.fetch_yf_enrichment(["US.AAPL", "US.MSFT"], prices={"US.AAPL": 200.0},
                                  yf_module=yf)
    by = {r["code"]: r for r in rows}
    assert by["US.AAPL"]["data"]["forward_pe"] == 22.5
    assert by["US.AAPL"]["data"]["short_float"] == 2.1
    assert by["US.AAPL"]["data"]["pcf"] == 50.0          # price 200 / cash/share 4
    assert by["US.AAPL"]["data"]["country"] == "USA"
    assert by["US.AAPL"]["data"]["earnings_date"].startswith("2025-05")
    assert by["US.AAPL"]["source"] == "yfinance" and by["US.AAPL"]["market"] == "US"
    assert by["US.MSFT"]["data"]["beta"] == 1.1
    assert "_lt_de" not in by["US.AAPL"]["data"]         # staging keys never leak


def test_broken_ticker_is_skipped_not_fatal():
    yf = FakeTickers({"AAPL": RuntimeError("boom"), "MSFT": INFO_B})
    rows = ye.fetch_yf_enrichment(["US.AAPL", "US.MSFT"], prices={}, yf_module=yf)
    assert [r["code"] for r in rows] == ["US.MSFT"]


def test_missing_yfinance_dependency_raises_clear_error():
    import pytest
    with pytest.raises(ye.EnrichUnavailable):
        ye.fetch_yf_enrichment(["US.AAPL"], prices={}, yf_module=None,
                               import_fn=lambda: (_ for _ in ()).throw(ImportError("no yf")))


def test_lt_debt_staging_combines_with_equity():
    yf = FakeTickers({"AAPL": {"longTermDebt": 10.0, "totalStockholderEquity": 40.0}})
    rows = ye.fetch_yf_enrichment(["US.AAPL"], prices={}, yf_module=yf)
    assert rows[0]["data"]["lt_debt_eq"] == 25.0          # 10/40 in percent form


def test_hk_symbol_mapping():
    assert ye.to_yahoo_symbol("HK.00700", "HK") == "0700.HK"
    assert ye.to_yahoo_symbol("US.AAPL", "US") == "AAPL"
