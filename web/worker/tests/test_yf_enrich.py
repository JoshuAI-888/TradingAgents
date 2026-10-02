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


class FakeYfModule:
    """Stands in for the yfinance module: yf.Tickers('A B').tickers[<sym>].info"""
    def __init__(self, infos):
        self._infos = infos

    def Tickers(self, names):
        outer = self
        syms = names.split()

        class TickersObj:
            tickers = {s: FakeTicker(outer._infos.get(s, RuntimeError("unexpected symbol")))
                       for s in syms}

        return TickersObj()


INFO_A = {"forwardPE": 22.5, "shortPercentOfFloat": 0.021, "country": "USA",
          "earningsTimestamp": 1747000000, "totalCashPerShare": 4.0}
INFO_B = {"beta": 1.1}


def test_fetch_maps_codes_and_transforms():
    yf = FakeYfModule({"AAPL": INFO_A, "MSFT": INFO_B})
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
    yf = FakeYfModule({"AAPL": RuntimeError("boom"), "MSFT": INFO_B})
    rows = ye.fetch_yf_enrichment(["US.AAPL", "US.MSFT"], prices={}, yf_module=yf)
    assert [r["code"] for r in rows] == ["US.MSFT"]


def test_missing_yfinance_dependency_raises_clear_error():
    import pytest
    with pytest.raises(ye.EnrichUnavailable):
        ye.fetch_yf_enrichment(["US.AAPL"], prices={}, yf_module=None,
                               import_fn=lambda: (_ for _ in ()).throw(ImportError("no yf")))


def test_lt_debt_staging_combines_with_equity():
    yf = FakeYfModule({"AAPL": {"longTermDebt": 10.0, "totalStockholderEquity": 40.0}})
    rows = ye.fetch_yf_enrichment(["US.AAPL"], prices={}, yf_module=yf)
    assert rows[0]["data"]["lt_debt_eq"] == 25.0          # 10/40 in percent form


def test_hk_symbol_mapping():
    assert ye.to_yahoo_symbol("HK.00700", "HK") == "0700.HK"
    assert ye.to_yahoo_symbol("US.AAPL", "US") == "AAPL"


def test_fetch_rejects_nonfinite_boolean_blank_and_structured_factor_values():
    yf=FakeYfModule({"AAPL":{"forwardPE":float('inf'),"beta":True,"returnOnEquity":float('nan'),
                             "sector":{"name":"Technology"},"industry":"  ","country":" USA ",
                             "currentRatio":0,"shortPercentOfFloat":0,"grossMargins":True,"earningsTimestamp":float("inf")}})
    data=ye.fetch_yf_enrichment(["US.AAPL"],prices={},yf_module=yf)[0]['data']
    assert data=={'country':'USA','current_ratio':0,'short_float':0}


def test_empty_success_is_distinct_from_failed_fetch_for_replacement():
    yf=FakeYfModule({'AAPL':{},'MSFT':RuntimeError('offline')})
    rows=ye.fetch_yf_enrichment(['US.AAPL','US.MSFT'],prices={},yf_module=yf)
    assert len(rows)==1 and rows[0]['code']=='US.AAPL' and rows[0]['data']=={}
    assert rows[0]['as_of']
