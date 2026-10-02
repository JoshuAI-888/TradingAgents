"""Do not drop the top-level cursor returned by the REST gateway."""
import json
from tradingagents_worker import moomoo

def test_top_level_pagination_is_retained(monkeypatch):
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps({'ret_code':0,'data':{'items':[]},'pagination':{'next_key':'300','total':3158,'has_more':True}}).encode()
    monkeypatch.setattr(moomoo,'urlopen',lambda *a,**k:Response())
    c=moomoo.MoomooClient('test','test');monkeypatch.setattr(c,'_sign',lambda *a:'test')
    assert c.call('POST','/quote/stock-screen',body={'limit':300})['pagination']['next_key']=='300'
