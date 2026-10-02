from datetime import datetime,timezone,timedelta
from tradingagents_worker.provider_context import info_context,validated_context


def test_same_response_context_keeps_currencies_distinct_and_calendar_separate():
    now=datetime.now(timezone.utc)
    context=info_context({'symbol':'0700.HK','currency':'HKD','financialCurrency':'CNY','mostRecentQuarter':1767139200},'HK.00700',now)
    assert context['fields']['currency']=='HKD' and context['fields']['financialCurrency']=='CNY'
    assert context['fields']['mostRecentQuarter']['date']=='2025-12-31'
    assert 'not per-metric periods' in context['scope']
    assert validated_context(context,'HK.00700',now.isoformat(),now)==context
    assert validated_context(context,'US.AAPL',now.isoformat(),now) is None
    assert validated_context(context,'HK.00700',(now-timedelta(days=8)).isoformat(),now) is None
    assert validated_context(context,'HK.00700',(now+timedelta(seconds=1)).isoformat(),now) is None


def test_context_rejects_wrong_identity_invalid_clocks_currency_and_tampered_dates():
    now=datetime.now(timezone.utc)
    assert info_context({'symbol':'OTHER'},'US.AAPL',now) is None
    for invalid in [True,'1767139200',[],{},float('inf'),-1,now.timestamp()+100,10**1000]:
        context=info_context({'symbol':'AAPL','lastFiscalYearEnd':invalid,'currency':'usd'},'US.AAPL',now)
        assert not context['fields']
    context=info_context({'symbol':'AAPL','lastFiscalYearEnd':1767139200},'US.AAPL',now)
    context['fields']['lastFiscalYearEnd']['date']='2000-01-01'
    assert validated_context(context,'US.AAPL') is None
