"""Pair-review HTTP behavior, using real comparison validation and owner authentication."""
import json
import pytest
from tradingagents_api import main, research_reviews as reviews, research_auth as auth
from test_research_lists import client,headers,OWNER,OTHER

class PairStore:
    def __init__(self):self.rows=[];self.calls=[]
    def _call(self,method,path,query=None,body=None):
        self.calls.append((method,path,query,body))
        if path=='rpc/research_pair_review_read':
            keys={'owner_id':body['p_owner'],'history_key':body['p_key'],'previous_id':body['p_previous'],'current_id':body['p_current']}
            return {'reviews':[dict(r) for r in self.rows if all(r[k]==v for k,v in keys.items())]}
        if method=='GET':
            rows=[r for r in self.rows if all(str(r.get(k))==v[3:] for k,v in query.items() if v.startswith('eq.'))]
            rows.sort(key=lambda r:r['code']);offset=int(query['offset']);return [dict(r) for r in rows[offset:offset+int(query['limit'])]]
        keys={'owner_id':body['p_owner'],'history_key':body['p_key'],'previous_id':body['p_previous'],'current_id':body['p_current'],'code':body['p_code']}
        row=next((r for r in self.rows if all(r[k]==v for k,v in keys.items())),None)
        if (row and row['revision']!=body['p_revision']) or (not row and body['p_revision']!=0):return []
        if not row:row={**keys,'revision':0};self.rows.append(row)
        row.update(note=body['p_note'],review_status=body['p_status'],revision=row['revision']+1)
        return [dict(row)]

@pytest.fixture
def pair_client(client,monkeypatch):
    c,_=client;monkeypatch.setenv("DEFAULT_USER_ID",OWNER);store=PairStore();monkeypatch.setattr(reviews,'db',store)
    members=[{'code':f'US.A{i:04}','symbol':f'A{i:04}','name':f'Company {i}'} for i in range(503)]
    snapshots=[{'id':str(i),'at':f'2026-10-0{i}T00:00:00Z','complete':True,'version':1,'members':members} for i in (1,2,3)]
    monkeypatch.setattr(main,'_snapshot_history',lambda key:snapshots[-2:])
    monkeypatch.setattr(main,'_snapshot_get',lambda key,sid:next((s for s in snapshots if s['id']==sid),None))
    monkeypatch.setattr(main,'_snapshot_metadata_page',lambda *a:([main._snapshot_meta(s) for s in snapshots],False))
    yield c,store,snapshots

def payload(**kwargs):return {'definition':{'market':'US','src':'yf'},'previous_id':'1','current_id':'2','code':'US.A0000','revision':0,'note':'First pair','review_status':'reviewed',**kwargs}
def params(**kwargs):return {'definition':json.dumps({'market':'US','src':'yf'}),'previous_id':'1','current_id':'2',**kwargs}

def test_pair_state_is_independent_and_cas_rejects_stale_draft(pair_client):
    c,store,_=pair_client
    first=c.patch('/api/research/pair-reviews',headers=headers(),json=payload());assert first.status_code==200
    assert first.json()['review']['revision']==1
    assert c.patch('/api/research/pair-reviews',headers=headers(),json=payload(note='stale draft')).status_code==409
    assert store.rows[0]['note']=='First pair'
    assert c.patch('/api/research/pair-reviews',headers=headers(),json=payload(previous_id='2',current_id='3',note='Different pair')).status_code==200
    assert len(store.rows)==2
    result=c.get('/api/research/pair-reviews',headers=headers(),params=params(limit=1)).json()
    assert result['rows'][0]['review']['note']=='First pair'
    assert result['review_scope']=='private_capture_pair'


def test_review_scope_filters_before_paging_and_can_find_next_after_500(pair_client):
    c,store,_=pair_client
    key=main._snapshot_key(main.ScreenDefinition(market='US',src='yf'))
    store.rows=[{'owner_id':OWNER,'history_key':key,'previous_id':'1','current_id':'2','code':f'US.A{i:04}','note':'','revision':1,'review_status':'reviewed'} for i in range(501)]
    response=c.get('/api/research/pair-reviews',headers=headers(),params=params(review_status='unreviewed',limit=1))
    assert response.status_code==200;data=response.json()
    assert data['matched']==2 and data['rows'][0]['code']=='US.A0501'
    assert data['rows'][0]['review']['revision']==0
    second=c.get('/api/research/pair-reviews',headers=headers(),params=params(review_status='unreviewed',limit=1,offset=1)).json()
    assert second['rows'][0]['code']=='US.A0502'
    assert c.get('/api/research/pair-reviews',headers=headers(),params=params(review_status='unreviewed',q='Company 502')).json()['matched']==1


def test_pair_review_rejects_absent_incompatible_and_untrusted_owner(pair_client,monkeypatch):
    c,store,snapshots=pair_client
    assert c.patch('/api/research/pair-reviews',headers=headers(),json=payload(code='US.MISSING')).status_code==404
    assert c.patch('/api/research/pair-reviews',headers=headers(),json=payload(owner_id=OTHER)).status_code==422
    assert c.get('/api/research/pair-reviews',headers=headers(OTHER),params=params()).status_code==401
    assert c.get('/api/research/pair-reviews',params=params()).status_code==401
    snapshots[0]['complete']=False
    assert c.patch('/api/research/pair-reviews',headers=headers(),json=payload()).status_code==409
    assert store.rows==[]
    snapshots[0]['complete']=True;monkeypatch.setattr(auth,'_session_active',lambda *a:False)
    assert c.patch('/api/research/pair-reviews',headers=headers(),json=payload()).status_code==401


def test_private_review_responses_are_not_cacheable(pair_client):
    c,_,_=pair_client
    response=c.get('/api/research/pair-reviews',headers=headers(),params=params())
    assert response.headers['Cache-Control']=='private, no-store'


def test_verified_second_owner_cannot_read_or_overwrite_first_owner_review(pair_client,monkeypatch):
    c,store,_=pair_client
    assert c.patch('/api/research/pair-reviews',headers=headers(),json=payload()).status_code==200
    monkeypatch.setattr(auth,'_auth_user',lambda t:{'id':OTHER,'is_anonymous':False})
    result=c.get('/api/research/pair-reviews',headers=headers(OTHER),params=params(limit=1)).json()
    assert result['rows'][0]['review']['revision']==0
    assert result['rows'][0]['review']['note']==''
    assert c.patch('/api/research/pair-reviews',headers=headers(OTHER),json=payload(revision=1,note='overwrite')).status_code==409
    assert c.patch('/api/research/pair-reviews',headers=headers(OTHER),json=payload(note='Other owner')).status_code==200
    assert len(store.rows)==2 and store.rows[0]['note']=='First pair'


def test_storage_failure_does_not_return_a_false_unreviewed_state(pair_client,monkeypatch):
    c,store,_=pair_client
    def failed(*a,**k):raise RuntimeError('private internal details')
    monkeypatch.setattr(store,'_call',failed)
    response=c.get('/api/research/pair-reviews',headers=headers(),params=params())
    assert response.status_code==503 and 'private internal details' not in response.text


def test_next_unreviewed_respects_sort_wrap_and_query(pair_client):
    c,_,_=pair_client
    first=c.get('/api/research/pair-reviews',headers=headers(),params=params(review_status='unreviewed',next_code='US.A0100',limit=100)).json()
    assert first['next_review_code']=='US.A0101' and first['offset']==100
    backwards=c.get('/api/research/pair-reviews',headers=headers(),params=params(review_status='unreviewed',next_code='US.A0100',direction=2,limit=100)).json()
    assert backwards['next_review_code']=='US.A0099' and backwards['offset']==400
    wrapped=c.get('/api/research/pair-reviews',headers=headers(),params=params(review_status='unreviewed',next_code='US.A0502')).json()
    assert wrapped['next_review_code']=='US.A0000'
    limited=c.get('/api/research/pair-reviews',headers=headers(),params=params(review_status='unreviewed',next_code='US.A0000',q='Company 502')).json()
    assert limited['next_review_code']=='US.A0502'
    assert c.get('/api/research/pair-reviews',headers=headers(),params=params(next_code='US.BAD,owner_id.eq.x')).status_code==422


def test_review_hash_detects_revision_changes_and_exact_code_reload(pair_client):
    c,_,_=pair_client
    original=c.get('/api/research/pair-reviews',headers=headers(),params=params(limit=1)).json()['review_revision_hash']
    assert c.patch('/api/research/pair-reviews',headers=headers(),json=payload()).status_code==200
    updated=c.get('/api/research/pair-reviews',headers=headers(),params=params(code='US.A0000',limit=1)).json()
    assert updated['review_revision_hash']!=original
    assert updated['matched']==1 and updated['rows'][0]['review']['note']=='First pair'
    same=c.get('/api/research/pair-reviews',headers=headers(),params=params(offset=400)).json()
    assert same['review_revision_hash']==updated['review_revision_hash']


def test_next_queue_start_does_not_require_an_invented_ticker(pair_client):
    c,_,_=pair_client
    data=c.get('/api/research/pair-reviews',headers=headers(),params=params(next_review=True,review_status='unreviewed')).json()
    assert data['next_review_code']=='US.A0000' and data['offset']==0
