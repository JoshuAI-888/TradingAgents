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
    monkeypatch.setattr(api, '_stored_universe_cache', {})
    monkeypatch.setattr(api, '_merge_universe_meta', lambda rows,market:rows)

def test_all_22_existing_preset_definitions_are_unchanged():
    baseline=json.loads((Path(__file__).parent/'ui/presets-baseline.json').read_text())
    assert len(baseline)==22
    assert api.PRESET_SCREENERS==baseline

def test_average_volume_uses_verified_provider_period():
    f=api._server_filter('volume', {'min':100000, 'days':30})['cumulative_property_query']
    assert f['property']=={'name':3104,'periodAverage':30}
    assert f['days']==30 and f['lower']['value']==100000

def test_retrieval_preserves_distinct_requested_volume_windows():
    criteria=[{'field':'volume','days':10,'min':1},{'field':'volume','days':30,'min':2},{'field':'volume','days':10,'max':3}]
    assert api._server_retrieves(criteria)==[
        {'cumulative_property':{'name':3104,'periodAverage':10}},
        {'cumulative_property':{'name':3104,'periodAverage':30}}]
    results=[{'cumulative_property_result':{'property':{'name':3104,'periodAverage':30},'res':{'ival':'300'}}},
             {'cumulative_property_result':{'property':{'name':3104,'periodAverage':10},'res':{'ival':'100'}}}]
    evidence=api._screen_criterion_evidence('US.A',criteria,results,'clock')
    assert [e['value'] for e in evidence]==[100,300,100]
    assert [e['criterion'] for e in evidence]==criteria
    assert all(e['period'] is None and e['currency'] is None for e in evidence)
    for records in [[{'cumulative_property_result':{'property':{'name':3104},'res':{'ival':'999'}}}],results+results]:
        assert all(e['value'] is None for e in api._screen_criterion_evidence('US.A',criteria,records,'clock'))

@pytest.mark.parametrize('raw',[True,False,{},[],float('inf'),float('nan'),'NaN','',10**400])
def test_provider_invalid_numeric_evidence_cannot_become_a_factor(raw):
    assert api._screen_result_number({'res':{'ival':raw}}) is None

def test_provider_criterion_clock_is_independent_of_quote_hydration(monkeypatch):
    stamp=datetime.now(timezone.utc).isoformat()
    api.db._t('screener_quotes').append({'market':'US','code':'US.A','updated_at':stamp,
        'row':{'code':'US.A','symbol':'A','price':7,'volume':999,'stock_type':'STOCK'}})
    class Provider:
        def call(self,method,path,body):
            return {'items':[{'code':'US.A','results':[{'cumulative_property_result':{
                'property':{'name':3104,'periodAverage':30},'res':{'ival':'0'}}}]}]}
    monkeypatch.setattr(api,'_market_client',lambda:Provider())
    result=api.screener_execute('penny','US',300)
    row=result['rows'][0]
    evidence=next(e for e in row['criterion_evidence'] if e['criterion']['field']=='volume')
    assert evidence['value']==0 and evidence['code']=='US.A'
    assert row['volume']==999 and row['display_field_sources']['volume']['source']=='legacy_cache'
    assert evidence['retrieved_at']==result['retrieved_at']==row['criterion_retrieved_at']

def test_wrong_financial_basis_cannot_justify_requested_annual_criterion():
    criteria=[{'field':'roe','min':10}]
    result=[{'financial_property_result':{'property':{'name':4110,'term':1},'res':{'ival':'15000'}}}]
    assert api._screen_criterion_evidence('US.A',criteria,result,'clock')[0]['value'] is None

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


@pytest.mark.parametrize('contracts',[None,{},[],{'payout_ratio':'old'},{'pcf':'old'}])
def test_old_ratio_contracts_cannot_qualify_fresh_cache(contracts):
    now=datetime.now(timezone.utc).isoformat()
    values,origins=api._fresh_supplemental({'payout_ratio':0.6246,'pcf':0.002,'pfcf':10,
        'beta':0,'_meta':{'fundamentals_at':now,'field_contracts':contracts}},now)
    assert values=={'beta':0} and set(origins)=={'beta'}

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

def observed_rows(rows, stamp):
    return [{**r, 'quote_cache_at':stamp, 'quote_identity_status':'verified'} for r in rows]

def test_changes_require_complete_compatible_snapshots(monkeypatch):
    now=datetime.now(timezone.utc).isoformat()
    members=[{'code':'US.A','symbol':'A','name':'Alpha','price':10,'stock_type':'STOCK'}]
    def result(**kw):return {'available':True,'universe_loaded':True,'universe_as_of':now,'rows':observed_rows(members,now),'matched':len(members)}
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
    member=api.db._t('screen_captures')[0]['snapshot']['members'][0]
    assert member['evidence']['volume'] is None and member['evidence']['revenue_growth'] is None

@pytest.mark.parametrize('stamp',['not-a-date','2026-10-02T01:00:00','2099-01-01T00:00:00Z'])
def test_snapshot_rejects_invalid_naive_and_future_source_without_writing(monkeypatch,stamp):
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'rows':[],'universe_as_of':stamp})
    with pytest.raises(HTTPException) as err:api.capture_screen_snapshot(api.ScreenDefinition())
    assert err.value.status_code==409 and not api.db._t('app_settings')

def test_change_pair_ids_history_and_unavailable_exit_evidence(monkeypatch):
    now=datetime.now(timezone.utc).isoformat();members=[{'code':'US.A','symbol':'A','stock_type':'STOCK','price':3}]
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'universe_as_of':now,'rows':observed_rows(members,now),'matched':len(members)})
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
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'universe_as_of':now,'rows':observed_rows(rows[:2],now),'matched':2})
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


def test_immutable_history_retains_legacy_and_every_new_capture(monkeypatch):
    import copy
    now=datetime.now(timezone.utc).isoformat();spec=api.ScreenDefinition()
    legacy={'id':'legacy-record','version':1,'at':'2026-09-30T00:00:00Z','complete':True,'members':[{'code':'US.LEGACY'}]}
    key=api._snapshot_key(spec);api.db._t('app_settings').append({'key':key,'value':{'snapshots':[legacy]}})
    old=copy.deepcopy(api.db._t('app_settings'))
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'universe_as_of':now,'rows':observed_rows([{'code':'US.A','symbol':'A','stock_type':'STOCK','price':1}],now),'matched':1})
    ids=[api.capture_screen_snapshot(spec)['id'] for _ in range(5)]
    assert api.db._t('app_settings')==old
    timeline=api.screen_snapshot_history(spec.model_dump_json(),limit=2)
    assert timeline['retained_limit'] is None and timeline['has_more'] and len(timeline['snapshots'])==2
    assert all('snapshot' not in row for row in timeline['snapshots'])
    pages=[api.screen_snapshot_history(spec.model_dump_json(),limit=2,offset=offset)['snapshots'] for offset in (0,2,4)]
    assert {row['id'] for page in pages for row in page}==set(ids+['legacy-record'])
    pair=api.screen_changes(spec.model_dump_json(),previous_id=ids[0],current_id=ids[-1])
    assert pair['comparable'] and pair['previous_id']==ids[0]
    # Unverified/changed legacy evidence contracts stay unavailable.
    assert not api.screen_changes(spec.model_dump_json(),previous_id='legacy-record',current_id=ids[-1])['comparable']
    monkeypatch.setenv('DEFAULT_USER_ID','other-history-owner')
    assert api._snapshot_get(api._snapshot_key(spec),ids[0]) is None
    api.capture_screen_snapshot(spec);api.capture_screen_snapshot(spec)
    with pytest.raises(HTTPException) as err:api.screen_changes(spec.model_dump_json(),previous_id=ids[0],current_id=ids[-1])
    assert err.value.status_code==404


@pytest.mark.parametrize("failure", [RuntimeError("lost response"), OSError("network timeout")])
def test_capture_request_is_idempotent_after_a_lost_response(monkeypatch, failure):
    import uuid
    now=datetime.now(timezone.utc).isoformat();spec=api.ScreenDefinition();request=uuid.uuid4()
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'universe_as_of':now,'rows':observed_rows([{'code':'US.A','stock_type':'STOCK'}],now),'matched':1})
    rpc=api.db._call
    def lost(*args,**kwargs):
        rpc(*args,**kwargs);raise failure
    monkeypatch.setattr(api.db,'_call',lost)
    first=api.capture_screen_snapshot(spec,request)
    assert first['captured'] and first['idempotent'] and first['id']==str(request)
    monkeypatch.setattr(api,'screener',lambda **kw:pytest.fail('Retry refetched the provider'))
    second=api.capture_screen_snapshot(spec,request)
    assert second==first and len(api.db._t('screen_captures'))==1


def test_capture_storage_failure_never_replaces_the_legacy_history(monkeypatch):
    import copy
    now=datetime.now(timezone.utc).isoformat();spec=api.ScreenDefinition();key=api._snapshot_key(spec)
    api.db._t('app_settings').append({'key':key,'value':{'snapshots':[]}});old=copy.deepcopy(api.db.tables)
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'universe_as_of':now,'rows':[],'matched':0})
    monkeypatch.setattr(api.db,'_call',lambda *args,**kwargs:(_ for _ in ()).throw(RuntimeError('secret database detail')))
    with pytest.raises(HTTPException) as e:api.capture_screen_snapshot(spec)
    assert e.value.status_code==503 and 'secret' not in e.value.detail
    assert api.db._t('app_settings')==old['app_settings'] and not api.db._t('screen_captures')


def test_capture_history_pages_are_metadata_only_and_keep_selected_old_pair(monkeypatch):
    spec=api.ScreenDefinition();key=api._snapshot_key(spec)
    from datetime import timedelta
    base=datetime(2026,1,1,tzinfo=timezone.utc)
    for i in range(105):
        s={'id':f'capture-{i:03}','at':(base+timedelta(days=i)).isoformat(),'complete':True,'version':2,'members':[{'code':'US.A','evidence':{'price':i}}]}
        api.db._call('POST','rpc/screen_capture_append',body={'p_key':key,'p_records':[{'id':s['id'],'snapshot':s}]})
    latest=api.screen_snapshot_history(spec.model_dump_json())
    assert latest['has_more'] and len(latest['snapshots'])==100
    assert not any('snapshot' in row for row in latest['snapshots'])
    older=api.screen_changes(spec.model_dump_json(),previous_id='capture-000',current_id='capture-104',history_offset=100)
    assert older['comparable'] and older['history_offset']==100 and not older['history_has_more']
    assert {m['id'] for m in older['history']}=={f'capture-{i:03}' for i in range(5)}|{'capture-104'}
    for limit,offset in ((0,0),(101,0),(1,-1),(1,40001)):
        with pytest.raises(HTTPException):api.screen_snapshot_history(spec.model_dump_json(),limit,offset)


def test_capture_http_idempotency_header_and_metadata_contract(monkeypatch):
    from fastapi.testclient import TestClient
    import uuid
    now=datetime.now(timezone.utc).isoformat();calls=[];spec=api.ScreenDefinition()
    def provider(**kwargs):
        calls.append(kwargs)
        return {'available':True,'universe_loaded':True,'universe_as_of':now,'rows':observed_rows([{'code':'US.A','stock_type':'STOCK'}],now),'matched':1}
    monkeypatch.setattr(api,'screener',provider)
    client=TestClient(api.app);request=str(uuid.uuid4())
    first=client.post('/api/screener/snapshots',json=spec.model_dump(),headers={'Idempotency-Key':request,'X-User-ID':'untrusted-owner'})
    assert first.status_code==200 and first.json()['id']==request
    second=client.post('/api/screener/snapshots',json=spec.model_dump(),headers={'Idempotency-Key':request})
    assert second.status_code==200 and second.json()['idempotent'] and len(calls)==1
    assert api.db._t('screen_captures')[0]['history_key']==api._snapshot_key(spec)
    history=client.get('/api/screener/snapshot-history',params={'definition':spec.model_dump_json()}).json()
    assert history['scope']=='deployment_owner' and history['retained_limit'] is None and history['snapshots'][0]['id']==request
    assert 'snapshot' not in history['snapshots'][0]
    assert client.post('/api/screener/snapshots',json=spec.model_dump(),headers={'Idempotency-Key':'bad'}).status_code==422
    assert len(calls)==1


def test_full_eligible_observations_retain_both_sides_of_entries_and_exits(monkeypatch):
    from datetime import timedelta
    criterion={'field':'price','max':5};spec=api.ScreenDefinition(filters=[criterion]);now=datetime.now(timezone.utc)
    rows=[]
    def source(**kw):return {'available':True,'universe_loaded':True,'universe_as_of':now.isoformat(),'matched':len(rows),'rows':observed_rows(rows,now.isoformat())}
    monkeypatch.setattr(api,'screener',source)
    def observation(code,value,hours):
        return {'code':code,'symbol':code[3:],'stock_type':'STOCK','price':value,'field_evidence':{'price':{'criterion':criterion,'value':value,'source':'moomoo_snapshot','period':'point_in_time','unit':'currency','currency':'USD','clock':'quote_source','observed_at':(now-timedelta(hours=hours)).isoformat()}}}
    rows[:]=[observation('US.A',6,2),observation('US.B',3,2)];before=api.capture_screen_snapshot(spec)
    rows[:]=[observation('US.A',4,1),observation('US.B',7,1)];after=api.capture_screen_snapshot(spec)
    captures=[r['snapshot'] for r in api.db._t('screen_captures')]
    assert all(s['version']==3 and s['eligible_count']==2 and len(s['observations'])==2 and len(s['members'])==1 for s in captures)
    result=api.screen_changes(spec.model_dump_json(),previous_id=before['id'],current_id=after['id'])
    by_code={r['code']:r for r in result['rows']}
    assert by_code['US.A']['status']=='new' and by_code['US.B']['status']=='exited'
    assert by_code['US.A']['evidence'][0]['assessment']=='rule_entered'
    assert by_code['US.B']['evidence'][0]['assessment']=='rule_exited'
    assert by_code['US.A']['previous']['evidence']['price']==6 and by_code['US.B']['current']['evidence']['price']==7
    assert result['counts']=={'new':1,'exited':1,'all':2,'unchanged':0}
    assert 'sole cause' in by_code['US.A']['reason']


@pytest.mark.parametrize('bad', ['stale','missing_clock','missing_criterion','duplicate','conflicting'])
def test_incomplete_nonmember_observations_cannot_produce_a_capture(monkeypatch,bad):
    now=datetime.now(timezone.utc).isoformat();criterion={'field':'price','max':5};spec=api.ScreenDefinition(filters=[criterion])
    rows=observed_rows([{'code':'US.A','stock_type':'STOCK','price':4},{'code':'US.B','stock_type':'STOCK','price':10}],now)
    if bad=='stale':rows[1]['quote_cache_at']='2020-01-01T00:00:00Z'
    if bad=='missing_clock':rows[1]['quote_cache_at']=None
    if bad=='missing_criterion':rows[1]['price']=None
    if bad=='duplicate':rows[1]['code']='US.A'
    if bad=='conflicting':rows[1]['field_evidence']={'price':{'criterion':criterion,'value':1}}
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'universe_as_of':now,'matched':2,'rows':rows})
    with pytest.raises(HTTPException) as e:api.capture_screen_snapshot(spec)
    assert e.value.status_code==409 and not api.db._t('screen_captures')


def test_distinct_windows_keep_independent_observations_and_sort_slots(monkeypatch):
    now=datetime.now(timezone.utc).isoformat();criteria=[{'field':'volume','days':30,'min':0},{'field':'volume','days':60,'min':0}]
    spec=api.ScreenDefinition(filters=criteria)
    def row(code,a,b):return {'code':code,'stock_type':'STOCK','volume':999,'field_evidence':{f'c{i}':{'criterion':c,'value':v,'period':f'{c["days"]}-day average'} for i,(c,v) in enumerate(zip(criteria,[a,b]))}}
    rows=observed_rows([row('US.A',1,100),row('US.B',100,1)],now)
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'universe_as_of':now,'matched':2,'rows':rows})
    api.capture_screen_snapshot(spec);api.capture_screen_snapshot(spec)
    for identifier,code in [('c0','US.A'),('c1','US.B')]:
        d=api.screen_changes(spec.model_dump_json(),sort='criterion:before:'+identifier)
        assert d['rows'][0]['code']==code
        assert d['rows'][0]['evidence'][0]['criterion_key']=='c0' and d['rows'][0]['evidence'][1]['criterion_key']=='c1'
    with pytest.raises(HTTPException):api.screen_changes(spec.model_dump_json(),sort='criterion:before:volume')
    for r in rows:r.pop('field_evidence')
    with pytest.raises(HTTPException):api.capture_screen_snapshot(spec)


@pytest.mark.parametrize('mutation', ['currency','period','source','unit','clock','missing_stamp','future_stamp','same_stamp'])
def test_numeric_rule_assessment_requires_compatible_actual_observation_contract(mutation):
    from tradingagents_api.screen_observations import capture_observation,paired_evidence
    from datetime import timedelta
    now=datetime.now(timezone.utc);criterion={'field':'price','max':5}
    def row(value,stamp):return capture_observation({'code':'US.A','price':value,'field_evidence':{'price':{'criterion':criterion,'value':value,'period':'point_in_time','source':'moomoo_snapshot','unit':'currency','currency':'USD','clock':'quote_source','observed_at':stamp}}},[criterion])
    a=row(6,(now-timedelta(hours=2)).isoformat());b=row(4,(now-timedelta(hours=1)).isoformat());o=b['criterion_observations']['c0']
    if mutation in ('currency','period','source','unit'):o[mutation]='different'
    if mutation=='clock':o['clock']='cache_update'
    if mutation=='missing_stamp':o['observed_at']=None
    if mutation=='future_stamp':o['observed_at']=(now+timedelta(days=1)).isoformat()
    if mutation=='same_stamp':o['observed_at']=a['criterion_observations']['c0']['observed_at']
    evidence=paired_evidence(a,b,[criterion],[now,now])[0]
    assert evidence['status']=='unavailable_pair' and evidence['assessment'] is None


@pytest.mark.parametrize('mutation', ['definition','count_bool','wrong_market','unknown_type','missing_cache',
    'stale_cache','missing_slot','extra_slot','wrong_criterion','nonfinite','flat_mismatch','cache_mismatch',
    'observations_not_list','slots_not_object','member_changed','member_missing','nonmember_added'])
def test_persisted_observation_contract_is_revalidated_before_membership_claims(monkeypatch,mutation):
    import copy
    now=datetime.now(timezone.utc).isoformat();spec=api.ScreenDefinition(filters=[{'field':'price','max':5}])
    rows=observed_rows([{'code':'US.A','stock_type':'STOCK','price':4},{'code':'US.B','stock_type':'STOCK','price':10}],now)
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'universe_as_of':now,'matched':2,'rows':rows})
    api.capture_screen_snapshot(spec);api.capture_screen_snapshot(spec)
    pair=copy.deepcopy([r['snapshot'] for r in api.db._t('screen_captures')]);snapshot=pair[1];record=snapshot['observations'][1]
    if mutation=='definition':snapshot['definition']['filters'][0]['max']=20
    if mutation=='count_bool':snapshot['eligible_count']=True
    if mutation=='wrong_market':record['code']='HK.B'
    if mutation=='unknown_type':record['instrument_type']='UNKNOWN'
    if mutation=='missing_cache':record['quote_cache_at']=None
    if mutation=='stale_cache':record['quote_cache_at']='2020-01-01T00:00:00Z'
    if mutation=='missing_slot':record['criterion_observations'].pop('c0')
    if mutation=='extra_slot':record['criterion_observations']['c1']={}
    if mutation=='wrong_criterion':record['criterion_observations']['c0']['criterion']={'field':'price','max':20}
    if mutation=='nonfinite':record['criterion_observations']['c0']['value']=float('inf')
    if mutation=='flat_mismatch':record['evidence']['price']=0
    if mutation=='cache_mismatch':record['criterion_observations']['c0']['cache_at']='2020-01-01T00:00:00Z'
    if mutation=='observations_not_list':snapshot['observations']={}
    if mutation=='slots_not_object':record['criterion_observations']=[]
    if mutation=='member_changed':snapshot['members'][0]=copy.deepcopy(snapshot['members'][0]);snapshot['members'][0]['metrics']['price']=999
    if mutation=='member_missing':snapshot['members']=[]
    if mutation=='nonmember_added':snapshot['members'].append(record)
    monkeypatch.setattr(api,'_snapshot_history',lambda key:pair)
    result=api.screen_changes(spec.model_dump_json())
    assert result['comparable'] is False and 'no changes inferred' in result['reason']
    assert 'rows' not in result and 'counts' not in result


def test_real_normalizer_metadata_binds_each_rule_without_claiming_absent_currency(monkeypatch):
    from datetime import timedelta
    now=datetime.now(timezone.utc);spec=api.ScreenDefinition(filters=[{'field':'price','max':5}]);current=[]
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'universe_as_of':now.isoformat(),'matched':1,'rows':observed_rows(current,now.isoformat())})
    for price,hours in [(6,2),(4,1)]:
        current[:]=[{**snapshot_to_row({'code':'US.A','last_price':price,'prev_close_price':5,'update_time':int((now-timedelta(hours=hours)).timestamp()*1000)}),'stock_type':'STOCK'}]
        api.capture_screen_snapshot(spec)
    row=api.screen_changes(spec.model_dump_json())['rows'][0];e=row['evidence'][0]
    assert row['status']=='new' and (e['previous'],e['current'])==(6,4)
    assert e['previous_observation']['source']=='moomoo_cloud_snapshot'
    assert e['previous_observation']['timestamp_semantics']=='provider_snapshot_update'
    assert e['status']=='unavailable_pair' and e['assessment'] is None
    assert e['previous_observation']['currency'] is None


def test_normalized_point_observation_supports_two_bounds_without_window_reuse(monkeypatch):
    from datetime import timedelta
    now=datetime.now(timezone.utc);criteria=[{'field':'shares','min':5},{'field':'shares','max':10}]
    spec=api.ScreenDefinition(filters=criteria);current=[]
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'universe_as_of':now.isoformat(),'matched':1,'rows':observed_rows(current,now.isoformat())})
    for shares,hours in [(4,2),(6,1)]:
        current[:]=[{**snapshot_to_row({'code':'US.A','last_price':1,'prev_close_price':1,'outstanding_shares':shares,'update_time':int((now-timedelta(hours=hours)).timestamp()*1000)}),'stock_type':'STOCK'}]
        api.capture_screen_snapshot(spec)
    row=api.screen_changes(spec.model_dump_json())['rows'][0]
    assert [e['assessment'] for e in row['evidence']]==['rule_entered','rule_retained']
    assert [e['criterion_key'] for e in row['evidence']]==['c0','c1']
    # A generic daily volume observation cannot satisfy a 30-day average rule.
    current[:]=[{**snapshot_to_row({'code':'US.A','last_price':1,'volume':100,'update_time':int(now.timestamp()*1000)}),'stock_type':'STOCK'}]
    with pytest.raises(HTTPException):api.capture_screen_snapshot(api.ScreenDefinition(filters=[{'field':'volume','days':30,'min':0}]))


@pytest.mark.parametrize('mutation',['identity','value','field'])
def test_produced_quote_observation_conflicts_reject_capture(monkeypatch,mutation):
    now=datetime.now(timezone.utc).isoformat();row={**snapshot_to_row({'code':'US.A','last_price':1}),'stock_type':'STOCK'}
    entry=row['field_observations']['price']
    entry[{'identity':'code','value':'value','field':'field'}[mutation]]={'identity':'US.B','value':999,'field':'market_cap'}[mutation]
    monkeypatch.setattr(api,'screener',lambda **kw:{'available':True,'universe_loaded':True,'universe_as_of':now,'matched':1,'rows':observed_rows([row],now)})
    with pytest.raises(HTTPException) as e:api.capture_screen_snapshot(api.ScreenDefinition(filters=[{'field':'price','min':0}]))
    assert e.value.status_code==409 and not api.db._t('screen_captures')


def test_supplemental_merge_fills_absence_preserves_zero_and_rejects_unregistered_metadata(monkeypatch):
    from test_api import _seed_enrichment_rows, _fresh_caches
    _fresh_caches(monkeypatch);_seed_enrichment_rows(api.db)
    for quote in api.db._t('screener_quotes'):quote['row']['stock_type']='STOCK'
    monkeypatch.setattr(api,'_market_client',lambda:object())
    q=api.db._t('screener_quotes')[0]['row']
    q.update(code='US.AAPL',forward_pe=None,beta=0,roe=None,field_observations={'forward_pe':{'value':None}})
    stamp=api.db._t('screener_enrichment')[0]['as_of']
    api.db._t('screener_enrichment')[0]['data'].update(roe=12,sector='Technology',code='US.WRONG',
        generation_id='wrong',field_observations={'price':{'value':999}},quick_ratio=float('inf'),current_ratio=True)
    out=api.screener(watchlist_only=0,src='yf')
    row=next(r for r in out['rows'] if r['symbol']=='AAPL')
    assert row['code']=='US.AAPL' and row['forward_pe']==28 and row['beta']==0
    assert row['roe']==12 and row['sector']=='Technology'
    assert row['display_field_sources']['forward_pe']['source']=='yfinance'
    assert row['display_field_sources']['forward_pe']['cache_at']==stamp
    assert 'forward_pe' not in row['field_observations']
    assert 'generation_id' not in row and 'quick_ratio' not in row and 'current_ratio' not in row
    assert q['forward_pe'] is None and q['field_observations']=={'forward_pe':{'value':None}}


def test_supplemental_registry_matches_worker_and_does_not_infer_current_fundamentals_from_technicals(monkeypatch):
    from tradingagents_worker.enrich_fields import YF_ONLY_FIELDS
    from test_api import _seed_enrichment_rows, _fresh_caches
    from datetime import timedelta
    assert api._YF_ONLY_FIELDS==YF_ONLY_FIELDS | {'lt_debt_eq'}
    _fresh_caches(monkeypatch);_seed_enrichment_rows(api.db)
    for quote in api.db._t('screener_quotes'):quote['row']['stock_type']='STOCK'
    monkeypatch.setattr(api,'_market_client',lambda:object())
    now=datetime.now(timezone.utc).isoformat();old=(datetime.now(timezone.utc)-timedelta(days=9)).isoformat()
    for enr in api.db._t('screener_enrichment'):
        enr['as_of']=now;enr['data'].update(rsi14=20,_meta={'fundamentals_at':old,'technicals_at':now})
    out=api.screener(watchlist_only=0,src='yf',filters='[{"field":"forward_pe","max":40}]')
    assert out['rows']==[]
    technical=api.screener(watchlist_only=0,src='yf',filters='[{"field":"rsi14","max":30}]')
    assert len(technical['rows'])==2
    assert all('forward_pe' not in r and r['display_field_sources']['rsi14']['source']=='computed_technicals' for r in technical['rows'])


def test_groups_exclude_stale_enrichment_and_keep_missing_industry_unknown(monkeypatch):
    from datetime import timedelta
    now=datetime.now(timezone.utc).isoformat();old=(datetime.now(timezone.utc)-timedelta(days=9)).isoformat()
    rows=[{'code':'US.A','symbol':'A','stock_type':'STOCK','plate':'Provider banks','pe_ttm':8},
          {'code':'US.B','symbol':'B','stock_type':'STOCK','plate':'Provider banks','pe_ttm':0},
          {'code':'US.C','symbol':'C','stock_type':'STOCK','plate':'Provider banks','pe_ttm':float('inf')}]
    monkeypatch.setattr(api,'_stored_universe',lambda *a,**k:(rows,now))
    api.db._t('screener_enrichment').extend([
        {'market':'US','code':'US.A','data':{'sector':'Technology','industry':'Software','forward_pe':12},'as_of':old},
        {'market':'US','code':'US.B','data':{'sector':'Financial Services','forward_pe':16},'as_of':now}])
    result=api.groups(group_by='industry');assert len(result['rows'])==1
    group=result['rows'][0];assert group['key']=='Unknown' and group['stocks']==3 and not group['drillable']
    assert group['avgs']=={'pe_ttm':8,'forward_pe':16}
    assert group['coverage']['pe_ttm']==group['coverage']['forward_pe']==1
    assert group['cap_sum'] is None and group['coverage']['market_cap']==0
    # Read fresh classification after a successful update; no old aggregate cache.
    api.db._t('screener_enrichment')[0]['as_of']=now
    groups=api.groups(group_by='industry')['rows'];assert {r['key'] for r in groups}=={'Software','Unknown'}


def test_groups_currency_coverage_does_not_sum_mixed_or_unqualified_caps(monkeypatch):
    now=datetime.now(timezone.utc).isoformat()
    def row(code,value,currency):
        return {'code':code,'stock_type':'STOCK','plate':'P','market_cap':value,'pct':0,'volume':0,
                'field_observations':{'market_cap':{'code':code,'field':'market_cap','value':value,'unit':'currency','currency':currency}}}
    rows=[row('US.A',100,'USD'),row('US.B',200,'HKD'),row('US.C',300,None)]
    monkeypatch.setattr(api,'_stored_universe',lambda *a,**k:(rows,now))
    group=api.groups()['rows'][0]
    assert group['cap_sum'] is None and group['cap_currency'] is None
    assert group['cap_by_currency']=={'USD':100,'HKD':200} and group['coverage']['market_cap']==2
    assert group['coverage']['pct']==3 and group['chg_avg']==0 and group['coverage']['volume']==3
    rows[1]['field_observations']['market_cap']['currency']='USD'
    rows[2]['field_observations']['market_cap']['currency']='USD'
    group=api.groups()['rows'][0];assert group['cap_sum']==600 and group['cap_currency']=='USD'
    rows[2]['field_observations']['market_cap']['code']='US.WRONG'
    assert api.groups()['rows'][0]['cap_sum'] is None
    assert api._group_cap_currency(row('US.A',1,'USD'))=='USD'
    malformed=row('US.A',1,'USD');malformed['field_observations']['market_cap']['value']=True
    assert api._group_cap_currency(malformed) is None
    malformed=row(None,1,'USD');assert api._group_cap_currency(malformed) is None


def test_group_inputs_and_missing_ordering_are_explicit(monkeypatch):
    for kwargs in [{'group_by':'invalid'},{'stock_type':'WARRANT'},{'direction':3},{'market':'invalid'},{'order_by':'invalid'}]:
        with pytest.raises(HTTPException) as error:api.groups(**kwargs)
        assert error.value.status_code==400
    rows=[{'code':'US.A','stock_type':'STOCK','plate':'Missing'},
          {'code':'US.B','stock_type':'STOCK','plate':'Zero','pct':0},
          {'code':'US.C','stock_type':'UNKNOWN','plate':'Unknown','pct':99}]
    monkeypatch.setattr(api,'_stored_universe',lambda *a,**k:(rows,None))
    for direction in [1,2]:
        result=api.groups(order_by='chg_avg',direction=direction)
        assert [r['key'] for r in result['rows']]==['Zero','Missing']
        assert result['unclassified_count']==1


def test_groups_do_not_rank_unlike_currencies_or_serialize_aggregate_overflow(monkeypatch):
    import json
    def row(code,plate,currency,cap):
        return {'code':code,'stock_type':'STOCK','plate':plate,'market_cap':cap,'pct':1e308,'volume':1e308,
                'pe_ttm':1e308,'field_observations':{'market_cap':{
                    'code':code,'field':'market_cap','value':cap,'unit':'currency','currency':currency}}}
    rows=[row('US.A','Dollars','USD',100),row('US.B','HK dollars','HKD',1000)]
    monkeypatch.setattr(api,'_stored_universe',lambda *a,**k:(rows,None))
    with pytest.raises(HTTPException) as error:api.groups(order_by='cap_sum')
    assert error.value.status_code==400
    result=api.groups(order_by='cap_sum',cap_currency='USD')
    assert [r['key'] for r in result['rows']]==['Dollars','HK dollars']
    assert result['ordering']['cap_currency']=='USD'
    with pytest.raises(HTTPException):api.groups(cap_currency='usd')
    rows[:]=[row('US.A','P','USD',1e308),row('US.B','P','USD',1e308)]
    result=api.groups();group=result['rows'][0]
    assert group['cap_sum'] is None and group['cap_by_currency']=={'USD':None}
    assert group['vol_sum'] is None and group['coverage']['volume']==2
    assert group['chg_avg']==group['avgs']['pe_ttm']==1e308
    json.dumps(result,allow_nan=False)


def test_malformed_supplemental_and_observations_fail_closed(monkeypatch):
    from test_api import _seed_enrichment_rows, _fresh_caches
    _fresh_caches(monkeypatch);_seed_enrichment_rows(api.db)
    for quote in api.db._t('screener_quotes'):
        quote['row']['stock_type']='STOCK';quote['row']['field_observations']='malformed'
    for enr in api.db._t('screener_enrichment'):enr['data']=['not','a','field','map']
    monkeypatch.setattr(api,'_market_client',lambda:object())
    result=api.screener(watchlist_only=0,src='yf',filters='[{"field":"forward_pe","max":40}]')
    assert result['rows']==[]
    groups=api.groups();assert all(r['cap_sum'] is None for r in groups['rows'])


def test_field_currency_and_server_exports_preserve_attribution_without_inference(monkeypatch):
    import csv,io,json
    from tradingagents_worker.quote_observations import field_currency
    rows=[{'code':'US.BRK.B','symbol':'BRK.B','stock_type':'STOCK','name':'=1+1','price':0,'market_cap':1000,'currency':'USD'},
          {'code':'HK.0005','symbol':'0005','stock_type':'STOCK','price':2,'market_cap':900,
           'field_observations':{'price':{'code':'HK.0005','field':'price','value':2,'unit':'currency','currency':'HKD'}}}]
    assert field_currency(rows[0],'market_cap') is None
    assert field_currency(rows[1],'price')=='HKD'
    for mutation in [{'value':True},{'value':3},{'code':'US.0005'},{'unit':'multiple'},{'currency':'usd'}]:
        bad={**rows[1],'field_observations':{'price':{**rows[1]['field_observations']['price'],**mutation}}}
        assert field_currency(bad,'price') is None
    assert field_currency({'code':'US.A','market_cap':10**400},'market_cap') is None
    monkeypatch.setattr(api,'_stored_universe',lambda *a,**k:(rows,None))
    monkeypatch.setattr(api,'_market_client',lambda:object())
    result=api.screener(watchlist_only=0,export='csv')
    data=list(csv.DictReader(io.StringIO(result.body.decode('utf-8-sig'))))
    assert data[0]['price']=='0' and data[0]['name']=="'=1+1"
    assert data[0]['price_currency']==data[0]['market_cap_currency']=='Unavailable'
    assert data[1]['price_currency']=='HKD' and data[1]['market_cap_currency']=='Unavailable'
    assert json.loads(data[1]['field_observations'])['price']['currency']=='HKD'
    xml=api.screener(watchlist_only=0,export='xls').body.decode()
    assert 'price_currency' in xml and '>HKD<' in xml and '"currency": "HKD"' in xml


def test_company_context_has_exact_identity_freshness_and_no_provider_list_fallback():
    from datetime import timedelta
    now=datetime.now(timezone.utc).isoformat();old=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
    api.db._t('screener_enrichment').append({'code':'US.BRK.B','market':'US','as_of':now,
        'data':{'sector':' Financial Services ','industry':'Insurance','website':'https://company.example',
                'plate':'Banks','price':999,'_meta':{'fundamentals_at':now}}})
    out=api.screener_company_context('US.BRK.B')
    assert out['fields']=={'sector':'Financial Services','industry':'Insurance','website':'https://company.example'}
    assert out['origins']['website']['cache_at']==now
    assert api.screener_company_context('US.BRK.A')['fields']=={}
    api.db._t('screener_enrichment')[0]['data']['_meta']['fundamentals_at']=old
    assert api.screener_company_context('US.BRK.B')['fields']=={}
    with pytest.raises(HTTPException):api.screener_company_context('BRK.B')
