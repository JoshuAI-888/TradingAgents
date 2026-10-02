"""Full offline API/browser harness. Synthetic rows and recorded stock responses.
Run with PYTHONPATH=web/api:web/worker python web/api/tests/ui/research-preview.py.
No live service calls or production writes; saved screens/history live in memory.
"""
import os,sys,importlib.util,tempfile
from pathlib import Path
from datetime import datetime,timezone
os.environ.update(DEFAULT_USER_ID='offline-review',TA_STOCK_FIXTURES='1',SUPABASE_URL='https://example.supabase.co',SUPABASE_SERVICE_KEY='test',PORTAL_STATIC_DIR=str(Path(__file__).resolve().parents[2]/'static'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_api import FakeDb
from tradingagents_api import main as api,stock_fixtures
import uvicorn
spec=importlib.util.spec_from_file_location('fixture',Path(__file__).with_name('preview.py'));fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
api.db=FakeDb()
now=datetime.now(timezone.utc).isoformat()
for row in fixture.ROWS:
    api.db._t('screener_quotes').append({'market':'US','code':row['code'],'row':row.copy(),'updated_at':now})
    api.db._t('screener_universe').append({'market':'US',**row})
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
def execute(key='',market='US',limit=300):
    p=next(p for p in api.PRESET_SCREENERS if p['key']==key)
    rows,_=api._apply_filters([r.copy() for r in fixture.ROWS],p['filters'])
    rows=api._sort_rows(rows,p.get('sort','pct'),p.get('direction',2))
    for r in rows:r['criterion_values']={f['field']:r.get(f['field']) for f in p['filters']}
    return {'available':True,'rows':rows[:limit],'filters':p['filters'],'name':p['name'],'pending':[],'sort':p.get('sort','pct'),'direction':p.get('direction',2),'result_limit':limit,'possibly_truncated':len(rows)>=limit,'retrieved_at':now}
api.screener_execute=execute
for route in api.app.routes:
    if getattr(route,'path',None)=='/api/screener/execute':route.endpoint=execute;route.dependant.call=execute
api.market_state=lambda:{'available':False}
for route in api.app.routes:
    if getattr(route,'path',None)=='/api/market/state':route.endpoint=api.market_state;route.dependant.call=api.market_state
orig=stock_fixtures.payload
stock_fixtures.payload=lambda key,sym:orig(key,sym.split('.',1)[-1] if sym.startswith(('US.','HK.')) else sym)
os.chdir(tempfile.mkdtemp(prefix='research-preview-'))
print('Synthetic offline research workspace: http://127.0.0.1:8890',flush=True)
uvicorn.run(api.app,host='127.0.0.1',port=8890,log_level='warning')
