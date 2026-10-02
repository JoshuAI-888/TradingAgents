"""Investment workspace contracts: preservation, provider evidence and safe history."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi import HTTPException
from tradingagents_api import main as api
from tradingagents_worker.screener_rows import snapshot_to_row
from test_api import FakeDb

@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv('DEFAULT_USER_ID', 'research-owner')
    monkeypatch.setattr(api, 'db', FakeDb())
    monkeypatch.setattr(api, '_execute_cache', {})
    monkeypatch.setattr(api, '_merge_universe_meta', lambda rows,market:rows)

def test_all_22_existing_preset_definitions_are_unchanged():
    baseline=json.loads((Path(__file__).parent/'ui/presets-baseline.json').read_text())
    assert len(baseline)==22
    assert api.PRESET_SCREENERS==baseline

def test_average_volume_uses_verified_provider_period():
    f=api._server_filter('volume', {'min':100000, 'days':30})['cumulative_property_query']
    assert f['property']=={'name':3104,'periodAverage':30}
    assert f['days']==30 and f['lower']['value']==100000

def test_exclusive_bounds_and_missing_data_are_enforced():
    rows=[{'profit':5},{'profit':5.1},{'profit':None}]
    assert api._apply_filters(rows,[{'field':'profit','min':5,'excl_min':True}])[0]==[{'profit':5.1}]
    assert api._apply_filters(rows,[{'field':'absent','min':0}])==([],['absent'])
    late=[{}]*60+[{'profit':6}]
    assert len(api._apply_filters(late,[{'field':'profit','min':5}])[0])==1

def test_share_class_codes_do_not_collapse():
    assert snapshot_to_row({'code':'US.BRK.B'})['symbol']=='BRK.B'
    assert api._stock_code('BRK.B')=='US.BRK.B'
    assert api._stock_code('HK.00700')=='HK.00700'

def test_legacy_saved_screen_edit_preserves_presentation():
    api.db._t('saved_screeners').append({'id':'one','user_id':'research-owner','settings':{'cols':['symbol','price'],'etfs':False,'preset':'penny'}})
    api.update_screener('one',api.SavedScreenerIn(name='Renamed',filters=[{'field':'price','max':5}]))
    assert api.db._t('saved_screeners')[0]['settings']['preset']=='penny'
    api.update_screener('one',api.SavedScreenerIn(name='Renamed',settings={'presentation':'explore'}))
    assert api.db._t('saved_screeners')[0]['settings']=={'presentation':'explore'}

def test_nested_provider_results_are_scaled_and_unclassified_rows_hydrated(monkeypatch):
    class Provider:
        def call(self, method,path,body):
            if path.endswith('stock-basicinfo'):
                return {'basic_list':[{'code':'US.BRK.B','stock_type':'STOCK','exchange':'NYSE'}]}
            return {'items':[{'code':'US.BRK.B','name':'Berkshire','results':[
                {'simple_property_result':{'property':{'name':2201},'res':{'ival':'1500'}}},
                {'financial_property_result':{'property':{'name':4106},'res':{'ival':'43960'}}}]}]}
    monkeypatch.setattr(api,'_market_client',lambda:Provider())
    row=api.screener_execute('penny', 'US',300)['rows'][0]
    assert row['symbol']=='BRK.B' and row['price']==1.5 and row['stock_type']=='STOCK'
    assert row['criterion_values']['revenue_growth']==43.96
    assert row['revenue_growth']==43.96

def test_changes_require_complete_compatible_snapshots(monkeypatch):
    now=datetime.now(timezone.utc).isoformat()
    members=[{'code':'US.A','symbol':'A','name':'Alpha','price':10,'stock_type':'STOCK'}]
    def result(**kw):return {'available':True,'universe_loaded':True,'universe_as_of':now,'rows':members.copy(),'matched':len(members)}
    monkeypatch.setattr(api,'screener',result)
    spec=api.ScreenDefinition()
    assert not api.screen_changes(spec.model_dump_json())['comparable']
    assert api.capture_screen_snapshot(spec)['baseline']
    members[:]=[{'code':'US.B','symbol':'B','name':'Beta','stock_type':'STOCK'}]
    api.capture_screen_snapshot(spec)
    changes=api.screen_changes(spec.model_dump_json())
    assert changes['comparable'] and changes['added'][0]['symbol']=='B' and changes['exited'][0]['symbol']=='A'
    assert not api.screen_changes(api.ScreenDefinition(etfs=True).model_dump_json())['comparable']

def test_snapshot_rejects_truncated_provider_and_stale_universe(monkeypatch):
    monkeypatch.setattr(api,'screener_execute',lambda *args:{'available':True,'possibly_truncated':True})
    with pytest.raises(HTTPException) as e:api.capture_screen_snapshot(api.ScreenDefinition(preset='penny'))
    assert e.value.status_code==409 and not api.db._t('app_settings')
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'rows':[],'universe_as_of':'2020-01-01T00:00:00Z'})
    with pytest.raises(HTTPException):api.capture_screen_snapshot(api.ScreenDefinition())
    assert not api.db._t('app_settings')

def test_provider_cursor_is_forwarded_and_explicit_last_page_is_complete(monkeypatch):
    class Provider:
        def call(self,method,path,body):
            assert body['next_key']=='opaque-cursor'
            return {'items':[],'pagination':{'total':600,'has_more':False,'next_key':'-1'}}
    monkeypatch.setattr(api,'_market_client',lambda:Provider())
    out=api.screener_execute('penny','US',300,'opaque-cursor')
    assert out['provider_total']==600 and not out['possibly_truncated'] and out['next_key'] is None


def test_unverified_technical_criteria_do_not_return_unqualified_matches(monkeypatch):
    monkeypatch.setattr(api,'_market_client',lambda:object())
    out=api.screener_execute('rsi-30','US',300)
    assert not out['available'] and out['rows']==[] and 'rsi14' in out['pending']

def test_growth_factor_and_ten_day_low_use_verified_fields():
    assert api._FIELD_SERVER['roe_yoy'][1]==4607
    assert api._FIELD_SERVER['op_profit_growth'][1]==4607
    assert api._server_filter('new_low_10d',{'min':1})['cumulative_property_query']['property']['days']==10


def test_stale_technical_data_cannot_qualify_a_screen(monkeypatch):
    from test_api import _seed_enrichment_rows, _fresh_caches
    _fresh_caches(monkeypatch)
    _seed_enrichment_rows(api.db)
    monkeypatch.setattr(api,'_market_client',lambda:object())
    for q in api.db._t('screener_quotes'):q['row']['stock_type']='STOCK'
    d=api.db._t('screener_enrichment')[0]['data']
    d.update(rsi14=20,_meta={'fundamentals_at':datetime.now(timezone.utc).isoformat(),'technicals_at':'2020-01-01T00:00:00Z'})
    out=api.screener(watchlist_only=0,src='yf',filters='[{"field":"rsi14","max":30}]')
    assert out['rows']==[]
    unfiltered=api.screener(watchlist_only=0,src='yf')
    apple=next(r for r in unfiltered['rows'] if r['symbol']=='AAPL')
    assert apple['forward_pe']==28 and 'rsi14' not in apple


def test_library_definitions_do_not_depend_on_market_or_database(monkeypatch):
    def unavailable(*args, **kwargs):
        raise AssertionError('definition library must not fetch quote data')
    monkeypatch.setattr(api, '_market_client', unavailable)
    monkeypatch.setattr(api, '_stored_universe', unavailable)
    payload = api.screener_presets(definitions_only=True)
    assert len(payload['presets']) == 22
    assert [{k:v for k,v in p.items() if k != 'top'} for p in payload['presets']] == api.PRESET_SCREENERS


def test_legacy_stored_rows_recover_share_class_symbols(monkeypatch):
    monkeypatch.setattr(api, '_stored_universe_cache', {})
    original = {'code':'US.BRK.B','symbol':'B','market_cap':100}
    monkeypatch.setattr(api.db, 'select_all', lambda *a, **k:[{'row':original,'updated_at':'2026-10-02T01:00:00Z'}])
    rows, _ = api._stored_universe('US')
    assert rows[0]['symbol'] == 'BRK.B'
    assert original['symbol'] == 'B'


def test_read_only_provider_probe_preserves_explicit_cursor(monkeypatch):
    class Provider:
        def call(self, method, path, body):
            assert body == {'next_key':'cursor', 'limit':1}
            return {'items':[]}
    monkeypatch.setattr(api, '_market_client', lambda:Provider())
    assert api.screener_probe({'next_key':'cursor', 'limit':1})['data']=={'items':[]}
