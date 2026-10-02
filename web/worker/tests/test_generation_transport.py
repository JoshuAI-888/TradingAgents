import copy
from http.client import IncompleteRead
from urllib.error import URLError

import pytest

from tradingagents_worker.db import Db


def test_uncertain_transport_replays_exact_rpc_payload_once(monkeypatch):
    db=Db(url='http://unused.invalid',key='test-only')
    calls=[]
    body={'p_market':'US','p_run':'same-token','p_rows':[{'code':'US.A','row':{'price':0}}]}
    def call(method,path,body):
        calls.append((method,path,copy.deepcopy(body)))
        if len(calls)==1:raise URLError('response lost')
        return {'generation_id':'same-token'}
    monkeypatch.setattr(db,'_call',call)
    assert db.generation_rpc('screener_refresh_publish',body)=={'generation_id':'same-token'}
    assert len(calls)==2 and calls[0]==calls[1]


def test_sql_error_is_not_retried_as_uncertain_transport(monkeypatch):
    db=Db(url='http://unused.invalid',key='test-only'); calls=[]
    def call(*args,**kw):
        calls.append(args); raise RuntimeError('superseded lease')
    monkeypatch.setattr(db,'_call',call)
    with pytest.raises(RuntimeError):db.generation_rpc('screener_refresh_publish',{})
    assert len(calls)==1


def test_nan_is_rejected_before_network_mutation(monkeypatch):
    db=Db(url='http://unused.invalid',key='test-only')
    monkeypatch.setattr(db,'_call',lambda *a,**kw:pytest.fail('must not send NaN'))
    with pytest.raises(ValueError):db.generation_rpc('screener_refresh_publish',{'price':float('nan')})


def test_repeated_transport_failure_is_bounded(monkeypatch):
    db=Db(url='http://unused.invalid',key='test-only'); calls=[]
    def call(*args,**kw):
        calls.append(args); raise TimeoutError('response unavailable')
    monkeypatch.setattr(db,'_call',call)
    with pytest.raises(TimeoutError):db.generation_rpc('screener_refresh_begin',{})
    assert len(calls)==2


def test_partial_publication_response_retries_same_identity(monkeypatch):
    db=Db(url='http://unused.invalid',key='test-only'); calls=[]
    body={'p_market':'US','p_run':'same-token'}
    def call(*args,**kwargs):
        calls.append(copy.deepcopy(kwargs['body']))
        if len(calls)==1:raise IncompleteRead(b'{"generation_id":',50)
        return {'generation_id':'same-token'}
    monkeypatch.setattr(db,'_call',call)
    assert db.generation_rpc('screener_refresh_publish',body)['generation_id']=='same-token'
    assert calls==[body,body]
