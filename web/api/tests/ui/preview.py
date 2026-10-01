"""Offline browser fixture for the real screener HTML; never calls live services.
Run: python3 web/api/tests/ui/preview.py (http://127.0.0.1:8876).
"""
import ast
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parents[2]
module = ast.parse((ROOT / 'tradingagents_api/main.py').read_text())
PRESETS = next(ast.literal_eval(n.value) for n in module.body if isinstance(n, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == 'PRESET_SCREENERS' for t in n.targets))
ROWS = [dict(symbol=f'S{i:04}', code=f'US.S{i:04}', name=f'Fixture Stock {i}',
             stock_type='ETF' if i % 50 == 0 else 'STOCK', market_cap=(1200-i)*1e7,
             price=i%100+1, pct=(i%100-50)/10, volume=2e5, turnover=2e6,
             plate='Semiconductors' if i%2 else 'Banks', concepts=['Growth'], exchange='US',
             pe_ttm=8, pb=.8, div_yield=10, revenue_growth=20, net_profit_growth=25,
             debt_ratio=20, rsi14=20 if i%2 else 80, volume_ratio=3,
             new_high=i%2==0, new_low=i%2==1, roe=25, gross_margin=60,
             eps=10, eps_growth=25, net_margin=25, float_cap=1e9, roe_yoy=25, op_ebt=80)
        for i in range(1200)]

def matches(row, filters):
    for f in filters:
        value = row.get(f['field'])
        if value is None:
            continue
        if 'values' in f:
            if not any(v in (value if isinstance(value,list) else [value]) for v in f['values']):
                return False
        elif (f.get('min') is not None and value < f['min']) or (f.get('max') is not None and value > f['max']):
            return False
    return True

class Handler(SimpleHTTPRequestHandler):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,directory=str(ROOT/'static'),**kwargs)
    def log_message(self,*args): pass
    def do_GET(self):
        p=urlparse(self.path); q=parse_qs(p.query)
        if not p.path.startswith('/api/'):
            return super().do_GET()
        data={}
        if p.path=='/api/health':data={'status':'ok'}
        elif p.path=='/api/meta':data={'spend':{}}
        elif p.path=='/api/candidates':data={'candidates':[]}
        elif p.path=='/api/decisions':data={'decisions':[]}
        elif p.path=='/api/market/state':data={'available':False}
        elif p.path=='/api/screeners':data={'screeners':[{'id':'saved','name':'Saved Price Ascending','filters':[{'field':'price','max':10}], 'sort':'price','direction':1,'market':'US'}]}
        elif p.path=='/api/screener/presets':
            data={'universe_rows':1200,'presets':[{**x,'sort':'pct','direction':2,'top':[]} for x in PRESETS]}
        elif p.path=='/api/screener/facets':
            field=q['field'][0]; data={'values':[{'value':x,'count':600} for x in (['Growth'] if field=='concepts' else ['Banks','Semiconductors'])]}
        elif p.path=='/api/screener':
            filters=json.loads(q.get('filters',['[]'])[0]);rows=[r for r in ROWS if matches(r,filters)]
            data={'available':True,'rows':rows,'matched':len(rows),'watchlist':['S0001','S0002'],'universe_as_of':'2026-10-01T23:00:00Z'}
        elif p.path=='/api/screener/execute':
            preset=next(x for x in PRESETS if x['key']==q['key'][0]); rows=[r for r in ROWS if matches(r,preset['filters'])]
            rows=sorted(rows,key=lambda r:r['pct'],reverse=True)[:300]
            data={'available':True,'rows':rows,'filters':preset['filters'],'name':preset['name'],'pending':[], 'result_limit':300,'possibly_truncated':len(rows)==300}
        self.send_response(200);self.send_header('Content-Type','application/json');self.end_headers()
        self.wfile.write(json.dumps(data).encode())

if __name__=='__main__':
    print('Offline screener preview: http://127.0.0.1:8876',flush=True)
    ThreadingHTTPServer(('127.0.0.1',8876),Handler).serve_forever()
