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
            tickers = {s: FakeTicker({'symbol':s,**outer._infos[s]} if isinstance(outer._infos.get(s),dict) else outer._infos.get(s, RuntimeError("unexpected symbol")))
                       for s in syms}

        return TickersObj()


INFO_A = {"forwardPE": 22.5, "shortPercentOfFloat": 0.021, "country": "USA",
          "earningsTimestamp": 1747000000, "totalCashPerShare": 4.0,
          "totalCash":2000.0,"marketCap":100000.0,
          "regularMarketPrice":200.0,"currency":"USD","financialCurrency":"USD"}
INFO_B = {"beta": 1.1}


def test_company_website_is_retained_as_text_and_structured_values_are_rejected():
    rows=ye.fetch_yf_enrichment(['US.AAPL','US.MSFT'],prices={},yf_module=FakeYfModule({
        'AAPL':{'website':' https://company.example ','sector':'Technology'},'MSFT':{'website':{'url':'https://wrong.example'}}}))
    by={row['code']:row['data'] for row in rows}
    assert by['US.AAPL']['website']=='https://company.example'
    assert 'website' not in by['US.MSFT']


def test_fetch_maps_codes_and_transforms():
    yf = FakeYfModule({"AAPL": INFO_A, "MSFT": INFO_B})
    rows = ye.fetch_yf_enrichment(["US.AAPL", "US.MSFT"], prices={"US.AAPL": 200.0},
                                  yf_module=yf)
    by = {r["code"]: r for r in rows}
    assert by["US.AAPL"]["data"]["forward_pe"] == 22.5
    assert by["US.AAPL"]["data"]["short_float"] == 2.1
    assert by["US.AAPL"]["data"]["pcf"] == 50.0          # market cap / aggregate cash
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


def test_share_class_aliases_keep_canonical_identity_and_reject_collisions():
    assert ye.to_yahoo_symbol('US.BRK.B') == 'BRK-B'
    rows=ye.fetch_yf_enrichment(['US.BRK.B','US.BRK.B',None,{},'HK.00700','US.bad','US.'],prices={},
        yf_module=FakeYfModule({'BRK-B':{'beta':0}}))
    assert len(rows)==1 and rows[0]['code']=='US.BRK.B' and rows[0]['data']=={'beta':0}
    assert ye.fetch_yf_enrichment(['US.BRK.B','US.BRK-B'],prices={},
        yf_module=FakeYfModule({'BRK-B':{'beta':1}}))==[]
    for code in ['HK.00000','HK.100000','HK.AAPL','US.00700']:
        assert ye.to_yahoo_symbol(code,'HK')==''


def test_wrong_or_missing_response_identity_is_failed_fetch_not_empty_success():
    for identity in [None,'MSFT','brk-b']:
        assert ye.fetch_yf_enrichment(['US.BRK.B'],prices={},
            yf_module=FakeYfModule({'BRK-B':{'symbol':identity,'payoutRatio':0.5}}))==[]


def test_aggregate_cash_does_not_borrow_a_share_class_basis_or_stored_price():
    info={'totalCashPerShare':256115.53,'regularMarketPrice':500.5,
          'totalCash':400,'marketCap':1000,'freeCashflow':100,
          'currency':'USD','financialCurrency':'USD','payoutRatio':0.6246}
    row=ye.fetch_yf_enrichment(['US.BRK.B'],prices={'US.BRK.B':999999},
        yf_module=FakeYfModule({'BRK-B':info}))[0]
    assert row['data']['pcf']==2.5 and row['data']['pfcf']==10
    assert row['data']['payout_ratio']==62.46
    assert row['field_contracts']==ye.YF_FIELD_CONTRACTS
    del info['totalCash']
    assert 'pcf' not in ye.fetch_yf_enrichment(['US.BRK.B'],prices={'US.BRK.B':500.5},
        yf_module=FakeYfModule({'BRK-B':info}))[0]['data']


def test_money_ratios_require_explicit_same_currency_and_positive_legs():
    base={'totalCash':100,'marketCap':1000,'freeCashflow':50,'currency':'USD',
          'financialCurrency':'USD','payoutRatio':0}
    for change in [{'financialCurrency':'CNY'},{'currency':None},{'financialCurrency':None},
                   {'currency':'usd','financialCurrency':'usd'},{'marketCap':True},
                   {'marketCap':10**400},{'marketCap':float('inf')},{'marketCap':-10}]:
        data=ye.fetch_yf_enrichment(['US.AAPL'],prices={'US.AAPL':10},
            yf_module=FakeYfModule({'AAPL':base | change}))[0]['data']
        assert 'pcf' not in data and 'pfcf' not in data and data['payout_ratio']==0
    for value in [True,-1,0,{},'100',float('nan'),10**400]:
        data=ye.fetch_yf_enrichment(['US.AAPL'],prices={},
            yf_module=FakeYfModule({'AAPL':base | {'totalCash':value,'freeCashflow':value}}))[0]['data']
        assert 'pcf' not in data and 'pfcf' not in data


def test_untransformed_huge_vendor_number_cannot_abort_other_tickers():
    rows=ye.fetch_yf_enrichment(['US.AAPL','US.MSFT'],prices={},yf_module=FakeYfModule({
        'AAPL':{'forwardPE':10**400,'payoutRatio':1e308},'MSFT':{'payoutRatio':0}}))
    assert rows[0]['data']=={} and rows[1]['data']=={'payout_ratio':0}
