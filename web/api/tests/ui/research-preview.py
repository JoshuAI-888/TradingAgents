"""Full offline API/browser harness. Synthetic rows and recorded stock responses.
Run with PYTHONPATH=web/api:web/worker python web/api/tests/ui/research-preview.py.
No live service calls or production writes; saved screens/history live in memory.
"""
import os,sys,importlib.util,tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
os.environ.update(DEFAULT_USER_ID='offline-review',TA_STOCK_FIXTURES='1',SUPABASE_URL='https://example.supabase.co',SUPABASE_SERVICE_KEY='test',PORTAL_STATIC_DIR=str(Path(__file__).resolve().parents[2]/'static'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_api import FakeDb
from tradingagents_api import main as api,stock_fixtures
import uvicorn
spec=importlib.util.spec_from_file_location('fixture',Path(__file__).with_name('preview.py'));fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
api.db=FakeDb()
# Synthetic account/store transport for UI verification only. No remote Auth.
from tradingagents_api import research_auth, research_lists
from fastapi import HTTPException
import json,base64,uuid,time
PREVIEW_OWNER='00000000-0000-4000-8000-000000000001'
def preview_token(owner=PREVIEW_OWNER):
    payload=base64.urlsafe_b64encode(json.dumps({'sub':owner,'session_id':str(uuid.uuid4())}).encode()).decode().rstrip('=')
    return 'preview.'+payload+'.fixture'
def preview_auth(path,body=None,token=None):
    if path.startswith('logout'):return {}
    if path.endswith('password') and body.get('password')!='preview-password':raise HTTPException(401,'Invalid preview credentials.')
    return {'access_token':preview_token(),'refresh_token':'preview-refresh','expires_in':3600,
            'user':{'id':PREVIEW_OWNER,'email':'reviewer@example.test','is_anonymous':False}}
research_auth._auth_exchange=preview_auth
research_auth._auth_user=lambda token:{'id':PREVIEW_OWNER,'is_anonymous':False}
research_auth._session_active=lambda owner,session:True
class PreviewResearchDb:
    def _call(self,method,path,body=None,query=None,prefer=None):
        if path.startswith('rpc/'):
            parent=next((r for r in api.db._t('research_lists') if r['id']==body['p_list'] and r['owner_id']==body['p_owner'] and r['active']),None)
            if not parent:return []
            member=next((r for r in api.db._t('research_list_items') if r['list_id']==body['p_list'] and r['code']==body['p_code']),None)
            if path.endswith('research_list_add'):
                if member and member['active']:return [dict(member)]
                if not member:
                    member={'list_id':parent['id'],'owner_id':parent['owner_id'],'code':body['p_code'],'note':'','review_status':'unreviewed','active':True,'revision':1};api.db._t('research_list_items').append(member)
                else:member['active']=True;member['revision']+=1
            else:
                if not member or member['revision']!=body['p_revision']:return []
                for k,param in [('note','p_note'),('review_status','p_status'),('active','p_active')]:
                    if body[param] is not None:member[k]=body[param]
                member['revision']+=1
            parent['revision']+=1;parent['updated_at']=datetime.now(timezone.utc).isoformat();return [dict(member)]
        rows=api.db._t(path)
        matching=list(rows)
        for k,v in (query or {}).items():
            if str(v).startswith('eq.'):matching=[r for r in matching if str(r.get(k)).lower()==v[3:].lower()]
            elif str(v).startswith('in.('):matching=[r for r in matching if r.get(k) in v[4:-1].split(',')]
            elif str(v).startswith('ilike.*'):matching=[r for r in matching if v[7:-1].replace('\\_', '_').upper() in str(r.get(k,'')).upper()]
            elif k=='and' and v.startswith('(code.gt.'):matching=[r for r in matching if r['code']>v[9:-1]]
        if method=='GET':
            matching.sort(key=lambda r:r.get('code') or r.get('name') or '')
            offset=int((query or {}).get('offset',0));limit=int((query or {}).get('limit',1000))
            return [dict(r) for r in matching[offset:offset+limit]]
        if method=='POST':
            if any(r['owner_id']==body['owner_id'] and r['name'].casefold()==body['name'].casefold() and r['active'] for r in rows):raise RuntimeError('supabase POST -> 409: duplicate')
            row={**body,'id':str(uuid.uuid4()),'active':True,'revision':1,'updated_at':datetime.now(timezone.utc).isoformat()};rows.append(row);return [dict(row)]
        if method=='PATCH':
            for r in matching:r.update(body)
            return [dict(r) for r in matching]
research_lists.db=PreviewResearchDb()
api.db._t('research_lists').append({'id':'00000000-0000-4000-8000-000000000003','owner_id':PREVIEW_OWNER,'name':'Investment review fixture','description':'Synthetic UI verification only','active':True,'revision':1,'updated_at':datetime.now(timezone.utc).isoformat()})
api.db._t('research_list_items').append({'list_id':'00000000-0000-4000-8000-000000000003','owner_id':PREVIEW_OWNER,'code':'US.S0001','note':'Review balance sheet quality','review_status':'unreviewed','active':True,'revision':1})
now=datetime.now(timezone.utc).isoformat()
for row in fixture.ROWS:
    api.db._t('screener_quotes').append({'market':'US','code':row['code'],'row':row.copy(),'updated_at':now})
    api.db._t('screener_universe').append({'market':'US',**row})
# Controlled historical membership fixture: one exit, one entry, others retained.
# This is interaction evidence only, never a live data/count reconciliation.
change_definition=api.ScreenDefinition(filters=[{'field':'stock_type','values':['STOCK']}])
def change_member(row):
    return {'code':row['code'],'symbol':row['symbol'],'name':row['name'],
            'metrics':{k:row.get(k) for k in ('price','pct','market_cap','pe_ttm')},
            'evidence':{'stock_type':'STOCK'}}
before_members=[change_member(r) for r in fixture.ROWS if r['stock_type']=='STOCK']
after_members=before_members[1:]+[{'code':'US.S2001','symbol':'S2001','name':'Fixture New Company','metrics':{'price':20,'pct':1,'market_cap':2500000000,'pe_ttm':20},'evidence':{'stock_type':'STOCK'}}]
before_time=(datetime.now(timezone.utc)-timedelta(hours=20)).isoformat()
after_time=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
api.db._t('app_settings').append({'key':api._snapshot_key(change_definition),'value':{'snapshots':[
    {'id':'fixture-before','version':2,'at':before_time,'source_at':before_time,'source_clock':'stored_universe','definition':change_definition.model_dump(),'members':before_members,'complete':True},
    {'id':'fixture-after','version':2,'at':after_time,'source_at':after_time,'source_clock':'stored_universe','definition':change_definition.model_dump(),'members':after_members,'complete':True}]}})
api.db._t('saved_screeners').append({'id':'saved','user_id':'offline-review','name':'Saved Price Ascending','filters':[{'field':'price','max':10}],'sort':'price','direction':1,'market':'US','settings':{}})
class MemoryCache:
    def key(self,*args):return str(args)
    def get(self,*args):return None
    def put(self,*args):pass
api._cache=lambda:MemoryCache()
api._merge_universe_meta=lambda rows,market:rows
class Provider:
    def call(self,method,path,body):
        if path.endswith('stock-screen'):return {'items':[]}
        if path.endswith('stock-basicinfo'):return {'basic_list':[]}
        return {}
    def snapshot(self,codes):return {'snapshot_list':[stock_fixtures._quote(c.split('.',1)[-1]) for c in codes]}
api._market_client=lambda:Provider()
def execute(key='',market='US',limit=300,next_key=''):
    p=next(p for p in api.PRESET_SCREENERS if p['key']==key)
    rows,_=api._apply_filters([r.copy() for r in fixture.ROWS],p['filters'])
    rows=api._sort_rows(rows,p.get('sort','pct'),p.get('direction',2))
    for r in rows:r['criterion_values']={f['field']:r.get(f['field']) for f in p['filters']}
    offset=int(next_key or 0)
    page=rows[offset:offset+limit]
    cursor=str(offset+limit) if offset+limit<len(rows) else ''
    return {'available':True,'rows':page,'filters':p['filters'],'name':p['name'],'pending':[],'sort':p.get('sort','pct'),'direction':p.get('direction',2),'result_limit':limit,'provider_total':len(rows),'next_key':cursor,'possibly_truncated':bool(cursor),'retrieved_at':now}
api.screener_execute=execute
for route in api.app.routes:
    if getattr(route,'path',None)=='/api/screener/execute':route.endpoint=execute;route.dependant.call=execute
api.market_state=lambda:{'available':False}
for route in api.app.routes:
    if getattr(route,'path',None)=='/api/market/state':route.endpoint=api.market_state;route.dependant.call=api.market_state
# Recorded chart fixtures end in 2025. Shift only this offline harness's
# synthetic bars to the current date so range clipping can be exercised.
recorded_kline=stock_fixtures._kline
def preview_kline(*args,**kwargs):
    bars=recorded_kline(*args,**kwargs)
    if bars:
        shift=int(datetime.now(timezone.utc).timestamp()*1000)-bars[-1]['time_key']
        for bar in bars:bar['time_key']+=shift
    return bars
stock_fixtures._kline=preview_kline
orig=stock_fixtures.payload
stock_fixtures.payload=lambda key,sym:orig(key,sym.split('.',1)[-1] if sym.startswith(('US.','HK.')) else sym)
os.chdir(tempfile.mkdtemp(prefix='research-preview-'))
print('Synthetic offline research workspace on port '+os.getenv('RESEARCH_PREVIEW_PORT','8890'),flush=True)
uvicorn.run(api.app,host='127.0.0.1',port=int(os.getenv('RESEARCH_PREVIEW_PORT','8890')),log_level='warning')
