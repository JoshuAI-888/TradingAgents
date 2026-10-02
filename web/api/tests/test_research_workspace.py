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

def test_provider_snapshot_does_not_substitute_snapshot_volume_for_average_evidence(monkeypatch):
    now=datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(api,'screener_execute',lambda *args:{'available':True,'retrieved_at':now,'filters':api.PRESET_SCREENERS[0]['filters'],'rows':[{'code':'US.A','symbol':'A','stock_type':'STOCK','volume':123,'revenue_growth':99}]})
    api.capture_screen_snapshot(api.ScreenDefinition(preset='penny',filters=api.PRESET_SCREENERS[0]['filters']))
    member=api.db._t('app_settings')[0]['value']['snapshots'][0]['members'][0]
    assert member['evidence']['volume'] is None and member['evidence']['revenue_growth'] is None

@pytest.mark.parametrize('stamp',['not-a-date','2026-10-02T01:00:00','2099-01-01T00:00:00Z'])
def test_snapshot_rejects_invalid_naive_and_future_source_without_writing(monkeypatch,stamp):
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'rows':[],'universe_as_of':stamp})
    with pytest.raises(HTTPException) as err:api.capture_screen_snapshot(api.ScreenDefinition())
    assert err.value.status_code==409 and not api.db._t('app_settings')

def test_change_pair_ids_history_and_unavailable_exit_evidence(monkeypatch):
    now=datetime.now(timezone.utc).isoformat();members=[{'code':'US.A','symbol':'A','stock_type':'STOCK','price':3}]
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'universe_as_of':now,'rows':members.copy(),'matched':len(members)})
    spec=api.ScreenDefinition(filters=[{'field':'price','max':5}]);first=api.capture_screen_snapshot(spec)
    members[:]=[{'code':'US.B','symbol':'B','stock_type':'STOCK','price':4}];second=api.capture_screen_snapshot(spec)
    assert first['id']!=second['id'];history=api.screen_snapshot_history(spec.model_dump_json());assert len(history['snapshots'])==2
    pair=api.screen_changes(spec.model_dump_json(),first['id'],second['id']);assert pair['previous_id']==first['id'] and pair['current_id']==second['id']
    exit_row=next(r for r in pair['rows'] if r['status']=='exited');assert exit_row['evidence'][0]['previous']==3 and exit_row['evidence'][0]['current'] is None
    assert exit_row['evidence'][0]['status']=='unavailable_pair' and 'unavailable' in exit_row['reason']
    with pytest.raises(HTTPException) as err:api.screen_changes(spec.model_dump_json(),second['id'],first['id'])
    assert err.value.status_code==400
    with pytest.raises(HTTPException) as err:api.screen_changes(spec.model_dump_json(),'other-owner-id',second['id'])
    assert err.value.status_code==404

def test_snapshot_stock_only_scope_excludes_etfs_and_unknown_types(monkeypatch):
    now=datetime.now(timezone.utc).isoformat();rows=[{'code':'US.A','stock_type':'STOCK'},{'code':'US.B','stock_type':'ETF'},{'code':'US.C'}]
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'universe_as_of':now,'rows':rows,'matched':3})
    assert api.capture_screen_snapshot(api.ScreenDefinition())['members']==1

def test_review_pages_search_and_sorts_missing_caps_last_in_both_directions(monkeypatch):
    now=datetime.now(timezone.utc).isoformat();spec=api.ScreenDefinition()
    previous={'id':'before','version':2,'at':'2026-10-01T00:00:00Z','complete':True,'members':[{'code':'US.A','symbol':'A','name':'Alpha','metrics':{'market_cap':10}},{'code':'US.B','symbol':'B','name':'Beta'}]}
    current={'id':'after','version':2,'at':'2026-10-02T00:00:00Z','complete':True,'members':[{'code':'US.A','symbol':'A','name':'Alpha','metrics':{'market_cap':20}},{'code':'US.C','symbol':'C','name':'Gamma','metrics':{'market_cap':5}}]}
    monkeypatch.setattr(api,'_snapshot_history',lambda key:[previous,current])
    result=api.screen_changes(spec.model_dump_json(),status='all',limit=1,offset=1,sort='market_cap',direction=2)
    assert result['counts']=={'new':1,'exited':1,'all':3,'unchanged':1} and result['matched']==3 and result['rows'][0]['code']=='US.C'
    for direction in (1,2):assert api.screen_changes(spec.model_dump_json(),sort='market_cap',direction=direction)['rows'][-1]['code']=='US.B'
    result=api.screen_changes(spec.model_dump_json(),q='gAmMa',status='new');assert result['matched']==1 and result['rows'][0]['symbol']=='C'
    with pytest.raises(HTTPException):api.screen_changes(spec.model_dump_json(),limit=0)


def test_corrupt_or_changed_contract_history_does_not_infer_false_exits(monkeypatch):
    spec=api.ScreenDefinition();before={'id':'a','at':'2026-10-01T00:00:00Z','version':2,'complete':True,'members':[{'code':'US.A'}]}
    after={'id':'b','at':'2026-10-02T00:00:00Z','version':2,'complete':True,'members':[{'code':'US.B'},{'code':'US.B'}]}
    monkeypatch.setattr(api,'_snapshot_history',lambda key:[before,after]);assert not api.screen_changes(spec.model_dump_json())['comparable']
    after['members']=[{'code':'US.B'}];after['version']=1;assert not api.screen_changes(spec.model_dump_json())['comparable']
    after['version']=2;after['at']='invalid';assert not api.screen_changes(spec.model_dump_json())['comparable']

def test_snapshot_rejects_missing_instrument_classification_before_inference(monkeypatch):
    now=datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'universe_as_of':now,'rows':[],'unclassified_count':1})
    with pytest.raises(HTTPException):api.capture_screen_snapshot(api.ScreenDefinition())
    monkeypatch.setattr(api,'screener_execute',lambda *a:{'available':True,'retrieved_at':now,'rows':[{'code':'US.A'}]})
    with pytest.raises(HTTPException):api.capture_screen_snapshot(api.ScreenDefinition(preset='penny'))
    assert not api.db._t('app_settings')


def test_review_criterion_sort_uses_exact_capture_side_before_pagination(monkeypatch):
    spec=api.ScreenDefinition(filters=[{'field':'pe_ttm','max':12}])
    def row(code,value):return {'code':code,'symbol':code[3:],'evidence':{'pe_ttm':value},'metrics':{'pe_ttm':999}}
    before={'id':'before','version':2,'at':'2026-10-01T00:00:00Z','complete':True,'members':[row('US.A',0),row('US.B',10),row('US.D',float('nan'))]}
    after={'id':'after','version':2,'at':'2026-10-02T00:00:00Z','complete':True,'members':[row('US.A',8),row('US.C',-1),row('US.D',True)]}
    monkeypatch.setattr(api,'_snapshot_history',lambda key:[before,after])
    for side,first in [('before','US.A'),('after','US.C')]:
        result=api.screen_changes(spec.model_dump_json(),sort='criterion:'+side+':pe_ttm',limit=1)
        assert result['rows'][0]['code']==first and result['matched']==4
        for direction in (1,2):
            rows=api.screen_changes(spec.model_dump_json(),sort='criterion:'+side+':pe_ttm',direction=direction)['rows']
            assert {r['code'] for r in rows[-2:]}==({'US.C','US.D'} if side=='before' else {'US.B','US.D'})
    for sort in ['criterion:after:roe','criterion:latest:pe_ttm','criterion:after:pe_ttm;drop','arbitrary']:
        with pytest.raises(HTTPException):api.screen_changes(spec.model_dump_json(),sort=sort)
