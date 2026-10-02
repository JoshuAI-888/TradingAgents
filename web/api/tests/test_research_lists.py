"""Private research authorization and optimistic concurrency, through HTTP."""
import base64
import json
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from tradingagents_api import main, research_auth as auth, research_lists as lists

OWNER = '00000000-0000-4000-8000-000000000001'
OTHER = '00000000-0000-4000-8000-000000000002'
SID = '00000000-0000-4000-8000-000000000003'
SESSION = '00000000-0000-4000-8000-000000000004'

def token(owner=OWNER, session=SESSION):
    payload = base64.urlsafe_b64encode(json.dumps({'sub':owner,'session_id':session}).encode()).decode().rstrip('=')
    return 'verified.' + payload + '.signature'

class Store:
    def __init__(self):
        self.records = [{'id':SID,'owner_id':OWNER,'name':'Quality','description':'','active':True,'revision':1}]
        self.members=[]
        self.calls=[]
    def _call(self, method, path, body=None, query=None, prefer=None):
        self.calls.append((method,path,body,query))
        if path == 'screener_universe':
            return [{'code':'US.BRK.B'}] if query['code']=='eq.US.BRK.B' else []
        if path == 'rpc/research_list_add':
            row=next((r for r in self.records if r['id']==body['p_list'] and r['owner_id']==body['p_owner'] and r['active']),None)
            if not row:return []
            existing=next((r for r in self.members if r['list_id']==row['id'] and r['code']==body['p_code']),None)
            if not existing:
                existing={'list_id':row['id'],'owner_id':row['owner_id'],'code':body['p_code'],'note':'','review_status':'unreviewed','active':True,'revision':1};self.members.append(existing)
            elif not existing['active']:
                existing['active']=True;existing['revision']+=1
            return [dict(existing)]
        if path == 'rpc/research_list_review':
            parent=next((r for r in self.records if r['id']==body['p_list'] and r['owner_id']==body['p_owner'] and r['active']),None)
            row=next((r for r in self.members if r['list_id']==body['p_list'] and r['owner_id']==body['p_owner'] and r['code']==body['p_code'] and r['revision']==body['p_revision']),None)
            if not parent or not row:return []
            row.update({k:v for k,v in {'note':body['p_note'],'review_status':body['p_status'],'active':body['p_active']}.items() if v is not None});row['revision']+=1
            return [dict(row)]
        rows=self.records if path=='research_lists' else self.members
        matching=[r for r in rows if all(not str(v).startswith('eq.') or str(r.get(k)).lower()==str(v)[3:].lower() for k,v in (query or {}).items())]
        if method=='GET':return [dict(r) for r in matching]
        if method=='POST':
            row={**body,'id':str(uuid4()),'active':True,'revision':1};rows.append(row);return [dict(row)]
        if method=='PATCH':
            for r in matching:r.update(body)
            return [dict(r) for r in matching]

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth.SETTINGS,'supabase_url','https://example.supabase.co')
    monkeypatch.setattr(auth.SETTINGS,'supabase_service_key','test')
    store=Store();monkeypatch.setattr(lists,'db',store)
    monkeypatch.setattr(auth,'_auth_user',lambda t:{'id':OWNER,'is_anonymous':False})
    monkeypatch.setattr(auth,'_session_active',lambda owner,session:True)
    with TestClient(main.app) as c:
        yield c,store

def headers(owner=OWNER):return {'Authorization':'Bearer '+token(owner)}

def test_private_endpoints_reject_missing_and_forged_owner(client):
    c,store=client
    assert c.get('/api/research/lists',headers={'X-User-ID':OWNER}).status_code==401
    assert c.get('/api/research/lists',headers=headers(OTHER)).status_code==401
    assert store.calls==[]

def test_verified_owner_and_revoked_session(client,monkeypatch):
    c,store=client
    assert c.get('/api/research/session',headers=headers()).json()=={'authenticated':True,'owner_id':OWNER}
    monkeypatch.setattr(auth,'_session_active',lambda owner,session:False)
    assert c.get('/api/research/lists',headers=headers()).status_code==401
    assert store.calls==[]

@pytest.mark.parametrize('user',[{'id':OWNER,'is_anonymous':True},{'id':OWNER},{'id':'filter,injection','is_anonymous':False}])
def test_unverified_or_anonymous_account_cannot_access_notes(client,monkeypatch,user):
    c,store=client;monkeypatch.setattr(auth,'_auth_user',lambda t:user)
    assert c.get('/api/research/lists',headers=headers()).status_code==401
    assert not store.calls

def test_two_owners_cannot_read_or_write_each_others_list(client,monkeypatch):
    c,store=client;monkeypatch.setattr(auth,'_auth_user',lambda t:{'id':OTHER,'is_anonymous':False})
    assert c.get('/api/research/lists',headers=headers(OTHER)).json()['lists']==[]
    for method,path,body in [('get',f'/api/research/lists/{SID}/items',None),('patch',f'/api/research/lists/{SID}',{'name':'Stolen','revision':1}),('post',f'/api/research/lists/{SID}/items',{'code':'US.BRK.B'})]:
        assert getattr(c,method)(path,headers=headers(OTHER),**({'json':body} if body else {})).status_code==404
    assert store.records[0]['name']=='Quality';assert not store.members

def test_archive_restore_and_revision_conflict_preserve_list(client):
    c,store=client
    url=f'/api/research/lists/{SID}'
    assert c.patch(url,headers=headers(),json={'name':'Quality','revision':1,'active':False}).status_code==200
    assert c.get('/api/research/lists',headers=headers()).json()['lists']==[]
    assert c.get('/api/research/lists?include_archived=true',headers=headers()).json()['lists'][0]['revision']==2
    assert c.patch(url,headers=headers(),json={'name':'Stale edit','revision':1}).status_code==409
    assert c.patch(url,headers=headers(),json={'name':'Quality','revision':2,'active':True}).status_code==200
    assert store.records[0]['revision']==3

def test_add_restore_preserves_notes_status_and_share_class_identity(client):
    c,store=client;url=f'/api/research/lists/{SID}/items'
    r=c.post(url,headers=headers(),json={'code':'US.BRK.B'});assert r.status_code==200
    edit=url+'/US.BRK.B'
    assert c.patch(edit,headers=headers(),json={'revision':1,'note':'Review cash conversion','review_status':'reviewed','active':False}).status_code==200
    assert c.post(url,headers=headers(),json={'code':'US.BRK.B'}).json()['item']['note']=='Review cash conversion'
    assert store.members[0]['review_status']=='reviewed';assert store.members[0]['revision']==3
    assert c.patch(edit,headers=headers(),json={'revision':2,'note':'Stale overwrite'}).status_code==409
    assert store.members[0]['note']=='Review cash conversion'
    assert len(c.get(url,headers=headers()).json()['items'])==1

def test_validation_rejects_blank_names_unknown_or_injected_codes(client):
    c,_=client
    assert c.post('/api/research/lists',headers=headers(),json={'name':'   '}).status_code==422
    url=f'/api/research/lists/{SID}/items'
    for code in ['BRK.B','US.UNKNOWN','US.A,owner_id.eq.other']:
        assert c.post(url,headers=headers(),json={'code':code}).status_code==422
    assert c.patch(url+'/US.A,owner_id.eq.other',headers=headers(),json={'revision':1}).status_code==422

def test_storage_error_does_not_disclose_raw_notes(client,monkeypatch):
    c,store=client
    def broken(*a,**kw):raise RuntimeError('Secret provider details/private note')
    monkeypatch.setattr(store,'_call',broken)
    r=c.get('/api/research/lists',headers=headers());assert r.status_code==503;assert 'Secret' not in r.text

@pytest.mark.parametrize('header',['Basic token','Bearer','Bearer a b','Bearer '+('x'*8192)])
def test_malformed_authorization_is_rejected_before_network(client,monkeypatch,header):
    c,_=client
    def must_not_call(_):pytest.fail('Malformed headers reached Auth')
    monkeypatch.setattr(auth,'_auth_user',must_not_call)
    assert c.get('/api/research/lists',headers={'Authorization':header}).status_code==401

def test_auth_issuer_and_session_lookup_errors_fail_closed(client,monkeypatch):
    from fastapi import HTTPException
    c,store=client
    def unavailable(_):raise HTTPException(503,'Authentication is temporarily unavailable.')
    monkeypatch.setattr(auth,'_auth_user',unavailable)
    assert c.get('/api/research/lists',headers=headers()).status_code==503
    assert store.calls==[]

def test_auth_transport_uses_token_only_at_fixed_issuer_and_sanitizes_errors(monkeypatch):
    from urllib.error import HTTPError, URLError
    from fastapi import HTTPException
    monkeypatch.setattr(auth.SETTINGS,'supabase_url','https://example.supabase.co')
    monkeypatch.setattr(auth.SETTINGS,'supabase_service_key','server-secret')
    seen=[]
    def denied(req,timeout):
        seen.append(req)
        raise HTTPError(req.full_url,401,'Raw sensitive details',{},None)
    monkeypatch.setattr(auth.request,'urlopen',denied)
    with pytest.raises(HTTPException) as exc:auth._auth_user('user-token')
    assert exc.value.status_code==401;assert 'Raw' not in exc.value.detail
    assert seen[0].full_url=='https://example.supabase.co/auth/v1/user'
    assert seen[0].get_header('Authorization')=='Bearer user-token'
    def offline(*args,**kwargs):raise URLError('Sensitive infrastructure details')
    monkeypatch.setattr(auth.request,'urlopen',offline)
    with pytest.raises(HTTPException) as exc:auth._auth_user('user-token')
    assert exc.value.status_code==503;assert 'Sensitive' not in exc.value.detail

def test_partial_edits_preserve_other_review_fields_and_list_description(client):
    c,store=client;store.records[0]['description']='Original thesis'
    url=f'/api/research/lists/{SID}'
    assert c.patch(url,headers=headers(),json={'name':'Renamed','revision':1}).status_code==200
    assert store.records[0]['description']=='Original thesis'
    assert c.post(url+'/items',headers=headers(),json={'code':'US.BRK.B'}).status_code==200
    edit=url+'/items/US.BRK.B'
    assert c.patch(edit,headers=headers(),json={'revision':1,'note':'Thesis'}).status_code==200
    assert c.patch(edit,headers=headers(),json={'revision':2,'review_status':'reviewed'}).status_code==200
    assert store.members[0]['note']=='Thesis';assert store.members[0]['review_status']=='reviewed'
    assert c.patch(edit,headers=headers(),json={'revision':3}).status_code==422
    assert c.patch(edit,headers=headers(),json={'revision':3,'note':None}).status_code==422

def test_client_cannot_assign_a_list_to_another_owner(client):
    c,store=client
    r=c.post('/api/research/lists',headers=headers(),json={'name':'My shortlist','owner_id':OTHER,'user_metadata':{'owner_id':OTHER}})
    assert r.status_code==201;assert r.json()['list']['owner_id']==OWNER
