"""Universe loader: plate enumeration → stored universe → snapshot quotes."""
import pytest
from datetime import datetime, timezone, timedelta
from tradingagents_worker.universe_refresh import UniverseRefresher, UniverseRefreshError
from tradingagents_worker.screener_generations import GenerationError
from generation_fakes import GenerationDb


@pytest.fixture
def fake_db():
    return GenerationDb()


class FakeMoomoo:
    def call(self, method, path, body=None, query=None, retries=2):
        if path == "/quote/plate-list":
            return {"plate_list": [{"code": "US.LIST1", "plate_name": "Software"},
                                    {"code": "US.LIST2", "plate_name": "Semis"}]}
        if path == "/quote/plate-stock":
            return {"stock_list": [{"code": "US.PLTR"}, {"code": "US.NVDA"}]}
        if path == '/quote/stock-screen':
            return {'items': []}
        if path == '/quote/stock-basicinfo':
            return {'basic_list': [{'code': c, 'stock_type': 'STOCK', 'exchange': 'NASDAQ'}
                                   for c in body['code_list']]}
        return {}

    def snapshot(self, codes, retries=2):
        return {"snapshot_list": [{"code": c, "name": c.split(".")[1], "last_price": 10.0,
                                   "prev_close_price": 9.5} for c in codes]}


def test_refresh_enumerates_then_quotes(fake_db):
    r = UniverseRefresher(fake_db, FakeMoomoo(), "US").run()
    assert r["enum"]["plates"] == 6 and r["enum"]["codes"] == 2  # 3 classes x 2 fake plates
    assert r["quotes"]["quotes"] == 2 and r["quotes"]["batches"] == 1
    syms = fake_db.select("screener_universe", {"market": "eq.US"})
    assert {s["code"] for s in syms} == {"US.PLTR", "US.NVDA"}
    q = fake_db.select("screener_quotes", {"market": "eq.US"})
    assert len(q) == 2 and q[0]["row"]["price"] == 10.0
    assert abs(q[0]["row"]["pct"] - 5.26) < 0.01  # prev-close fallback


def test_second_run_skips_when_fresh(fake_db):
    ref = UniverseRefresher(fake_db, FakeMoomoo(), "US")
    ref.run()
    r2 = UniverseRefresher(fake_db, FakeMoomoo(), "US").run()
    # quotes are seconds old and interval_h defaults to 1h -> skip entirely
    assert "skipped" in r2 and "enum" not in r2 and "quotes" not in r2


def test_force_enum_reenumerates(fake_db):
    UniverseRefresher(fake_db, FakeMoomoo(), "US").run()
    r2 = UniverseRefresher(fake_db, FakeMoomoo(), "US").run(force_enum=True)
    assert r2["enum"]["codes"] == 2


def test_progress_events_emitted(fake_db):
    events = []
    UniverseRefresher(fake_db, FakeMoomoo(), "US", emit=lambda *a, **k: events.append(a)).run()
    stages = [e[0] for e in events]
    assert "universe" in stages and events[-1][1] == "done"


def test_plates_collect_all_memberships(fake_db):
    """Phase B: a code under two plates keeps the full list (concepts) and the
    first plate stays primary."""
    r = UniverseRefresher(fake_db, FakeMoomoo(), "US").run()
    rows = {s["code"]: s for s in fake_db.select("screener_universe", {"market": "eq.US"})}
    # FakeMoomoo lists both plates (Software, Semis) and both return the same codes
    assert rows["US.PLTR"]["plate"] == "Software"            # first stays primary
    assert rows["US.PLTR"]["plates"] == ["Software", "Semis"]
    assert r["enum"]["codes"] == 2


def test_snapshot_row_carries_session_ohlc(fake_db):
    """Technicals freshness: the stored row needs the session's open/high/low
    so the nightly job can synthesize today's partial bar without new calls."""
    from tradingagents_worker.screener_rows import snapshot_to_row
    row = snapshot_to_row({"code": "US.X", "last_price": 10.5, "prev_close_price": 9.5,
                           "open_price": 9.8, "high_price": 10.9, "low_price": 9.7,
                           "volume": 123.0})
    assert (row["open"], row["high"], row["low"]) == (9.8, 10.9, 9.7)


def test_quote_refresh_persists_source_time_separately_from_cache_write(fake_db):
    from datetime import datetime,timezone,timedelta
    stamp=int((datetime.now(timezone.utc)-timedelta(hours=2)).timestamp()*1000)
    class Provider(FakeMoomoo):
        def snapshot(self,codes,retries=2):
            out=super().snapshot(codes)
            for row in out['snapshot_list']:row['update_time']=stamp
            return out
    UniverseRefresher(fake_db,Provider(),'US').run()
    for stored in fake_db.select('screener_quotes',{'market':'eq.US'}):
        row=stored['row'];assert row['quote_observed_at']==datetime.fromtimestamp(stamp/1000,timezone.utc).isoformat()
        assert datetime.fromisoformat(stored['updated_at'])>datetime.fromisoformat(row['quote_observed_at'])
        assert row['field_observations']['price']['observed_at']==row['quote_observed_at']


def seed_cohort(db, count=2, market='US'):
    now=datetime.now(timezone.utc).isoformat()
    rows=[{'market':market,'code':f'{market}.S{i:04}', 'stock_type':'STOCK'} for i in range(count)]
    db._t('screener_universe').extend(rows)
    db._t('screener_quotes').extend({'code':r['code'],'market':market,'row':{'code':r['code'],'price':99},'updated_at':'2020-01-01T00:00:00Z'} for r in rows)
    db.upsert('app_settings','key',{'key':f'universe_state_{market}','value':{'last_enum':now,'last_quotes':'2020-01-01T00:00:00Z','last_result':{'retained':True}}})
    return rows


@pytest.mark.parametrize('response', [None, {}, {'snapshot_list':{}}, {'snapshot_list':[None]},
    {'snapshot_list':[{'code':'US.S0000'}]},
    {'snapshot_list':[{'code':'US.S0000'},{'code':'US.S0000'}]},
    {'snapshot_list':[{'code':'US.S0000'},{'code':'HK.S0001'}]},
    {'snapshot_list':[{'code':'US.S0000'},{'code':['US.S0001']}]}])
def test_invalid_quote_batch_preserves_prior_rows_and_success(fake_db,response):
    seed_cohort(fake_db)
    class Provider(FakeMoomoo):
        def snapshot(self,codes,retries=2):return response
    events=[]
    ref=UniverseRefresher(fake_db,Provider(),emit=lambda *a:events.append(a))
    with pytest.raises(UniverseRefreshError):ref.run()
    assert all(r['row']['price']==99 for r in fake_db._t('screener_quotes'))
    state=ref._universe_state()
    assert state['last_quotes']=='2020-01-01T00:00:00Z' and state['last_result']=={'retained':True}
    assert state['last_attempt']['status']=='failed' and state['last_attempt']['stage']=='quotes'
    assert events[-1][1]=='failed' and not any(e[1]=='done' for e in events)


def test_partial_later_batch_failure_does_not_advance_success_and_retry_is_not_skipped(fake_db):
    seed_cohort(fake_db,401)
    stamp=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
    fake_db._t('app_settings')[0]['value']['last_quotes']=stamp
    class Provider(FakeMoomoo):
        def snapshot(self,codes,retries=2):
            return {'snapshot_list':[]} if len(codes)==1 else super().snapshot(codes)
    ref=UniverseRefresher(fake_db,Provider())
    with pytest.raises(UniverseRefreshError):ref.refresh_quotes()
    # run() skips fresh success by design; record a previous failed attempt to
    # exercise the retry path when the previous success clock is still recent.
    fake_db._t('app_settings')[0]['value']['last_attempt']={'status':'failed'}
    with pytest.raises(UniverseRefreshError):ref.run()
    assert ref._universe_state()['last_quotes']==stamp
    quotes=fake_db._t('screener_quotes')
    assert all(r['row']['price']==99 for r in quotes)
    assert not fake_db._t('screener_generations')
    result=UniverseRefresher(fake_db,FakeMoomoo()).run()
    assert result['quotes']['quotes']==401 and result['quotes']['batches']==2
    assert result['quotes']['requested']==401 and result['quotes']['scope']=='requested_stored_universe'
    assert all(r['row']['price']==10 for r in quotes)
    assert UniverseRefresher(fake_db,FakeMoomoo())._universe_state()['last_attempt']['status']=='succeeded'


def test_universe_state_is_market_scoped_and_legacy_cadence_only(fake_db):
    now=datetime.now(timezone.utc).isoformat()
    fake_db.upsert('app_settings','key',{'key':'universe_state','value':{'interval_h':8,'last_quotes':now,'last_enum':now}})
    seed_cohort(fake_db,1,'US');seed_cohort(fake_db,1,'HK')
    us=UniverseRefresher(fake_db,FakeMoomoo(),'US')
    hk=UniverseRefresher(fake_db,FakeMoomoo(),'HK')
    us.run()
    assert us._universe_state()['interval_h']==8
    assert hk._universe_state()['last_quotes']=='2020-01-01T00:00:00Z'
    assert 'skipped' not in hk.run()
    assert us._universe_state()['last_attempt']['status']=='succeeded'
    fake_db.tables['app_settings']=[r for r in fake_db._t('app_settings') if r['key']=='universe_state']
    assert 'last_quotes' not in us._universe_state() and 'last_enum' not in hk._universe_state()


@pytest.mark.parametrize('raw',['2026-10-02T12:00:00', 'bad-time',
    (datetime.now(timezone.utc)+timedelta(days=1)).isoformat()])
def test_invalid_or_future_state_clock_is_not_fresh(fake_db,raw):
    ref=UniverseRefresher(fake_db,FakeMoomoo())
    assert ref._quotes_age_h({'last_quotes':raw})==1e9
    assert ref._enum_age_h({'last_enum':raw})==1e9


@pytest.mark.parametrize('kind',['classification_missing','classification_duplicate','classification_wrong_market','plate_failure','slice_failure'])
def test_failed_enumeration_does_not_publish_partial_new_cohort(fake_db,kind):
    seed_cohort(fake_db,1)
    class Provider(FakeMoomoo):
        def call(self,method,path,**kw):
            if kind=='plate_failure' and path=='/quote/plate-stock':raise RuntimeError('provider unavailable')
            if kind=='slice_failure' and path=='/quote/stock-screen':return {}
            out=super().call(method,path,**kw)
            if path=='/quote/stock-basicinfo':
                if kind=='classification_missing':out['basic_list'].pop()
                if kind=='classification_duplicate':out['basic_list'].append(out['basic_list'][0])
                if kind=='classification_wrong_market':out['basic_list'][0]['code']='HK.BAD'
            return out
    ref=UniverseRefresher(fake_db,Provider())
    previous_enum=ref._universe_state()['last_enum']
    with pytest.raises((UniverseRefreshError,RuntimeError)):ref.run(force_enum=True)
    assert [r['code'] for r in fake_db._t('screener_universe')]==['US.S0000']
    state=ref._universe_state()
    assert state['last_enum']==previous_enum and state['last_attempt']['stage']=='enumeration'


@pytest.mark.parametrize('kind',['repeat_cursor','repeat_identity','empty_with_cursor','limit'])
def test_plate_paging_never_treats_truncation_as_exhaustion(fake_db,kind):
    class Provider(FakeMoomoo):
        n=0
        def call(self,method,path,**kw):
            self.n+=1
            code='US.SAME' if kind=='repeat_identity' else f'US.S{self.n}'
            return {'stock_list':[] if kind=='empty_with_cursor' else [{'code':code}],
                    'pagination':{'next_key':'again' if kind=='repeat_cursor' else str(self.n)}}
    with pytest.raises(UniverseRefreshError):UniverseRefresher(fake_db,Provider())._plate_codes('US.PLATE')


def test_stored_cohort_identity_and_cap_validation(fake_db,monkeypatch):
    import tradingagents_worker.universe_refresh as module
    ref=UniverseRefresher(fake_db,FakeMoomoo())
    seed_cohort(fake_db,2)
    fake_db._t('screener_universe').append(dict(fake_db._t('screener_universe')[0]))
    with pytest.raises(UniverseRefreshError):ref.run()
    assert ref._universe_state()['last_attempt']['stage']=='cohort_validation'
    fake_db._t('screener_universe').pop()
    monkeypatch.setattr(module,'UNIVERSE_CAP',1)
    with pytest.raises(UniverseRefreshError,match='limit'):ref.refresh_quotes()


def test_storage_ack_failure_preserves_last_success(fake_db,monkeypatch):
    seed_cohort(fake_db)
    original=fake_db.generation_rpc
    monkeypatch.setattr(fake_db,'generation_rpc',lambda name,body:{} if name=='screener_refresh_publish' else original(name,body))
    ref=UniverseRefresher(fake_db,FakeMoomoo())
    with pytest.raises(UniverseRefreshError,match='acknowledgement'):ref.run()
    assert ref._universe_state()['last_quotes']=='2020-01-01T00:00:00Z'


def test_published_cohort_does_not_adopt_legacy_mirror_additions(fake_db):
    seed_cohort(fake_db)
    ref=UniverseRefresher(fake_db,FakeMoomoo())
    first=ref.run()
    assert 'skipped' in ref.run()
    fake_db._t('screener_universe').append({'market':'US','code':'US.NEW','stock_type':'STOCK'})
    second=ref.run()
    assert 'skipped' in second and second['generation_id']==first['generation_id']
    assert ref._stored_codes()==['US.S0000','US.S0001']
    assert not any(r['code']=='US.NEW' for r in fake_db._t('screener_quotes'))


def test_enumeration_and_first_quote_batch_do_not_publish_on_later_failure(fake_db):
    seed_cohort(fake_db,1)
    before=dict(fake_db._t('app_settings')[0]['value'])
    class Provider(FakeMoomoo):
        def call(self,method,path,**kw):
            if path=='/quote/plate-stock':return {'stock_list':[{'code':f'US.NEW{i:04}'} for i in range(401)]}
            return super().call(method,path,**kw)
        def snapshot(self,codes,retries=2):
            assert [r['code'] for r in fake_db._t('screener_universe')]==['US.S0000']
            assert fake_db._t('screener_quotes')[0]['row']['price']==99
            return {'snapshot_list':[]} if len(codes)==1 else super().snapshot(codes)
    with pytest.raises(UniverseRefreshError):UniverseRefresher(fake_db,Provider()).run(force_enum=True)
    state=UniverseRefresher(fake_db,Provider())._universe_state()
    assert state['last_enum']==before['last_enum'] and state['last_quotes']==before['last_quotes']
    assert not fake_db._t('screener_generation_rows')


def test_busy_market_does_not_call_provider_or_overwrite_running_owner(fake_db):
    seed_cohort(fake_db)
    fake_db.generation_rpc('screener_refresh_begin',{'p_market':'US','p_run':'owner'})
    class Provider(FakeMoomoo):
        def snapshot(self,codes,retries=2):raise AssertionError('busy owner must not collect')
    with pytest.raises(RuntimeError,match='owned'):UniverseRefresher(fake_db,Provider()).run()
    state=UniverseRefresher(fake_db,Provider())._universe_state()
    assert state['last_attempt']['run_id']=='owner' and state['last_attempt']['status']=='running'


def test_generation_corruption_never_falls_back_to_legacy_mirror(fake_db):
    first=UniverseRefresher(fake_db,FakeMoomoo()).run()
    fake_db._t('screener_generation_rows').pop()
    with pytest.raises(GenerationError,match='incomplete'):UniverseRefresher(fake_db,FakeMoomoo()).run()
    assert len(fake_db._t('screener_quotes'))==2
    assert fake_db._t('app_settings')[0]['value']['generation_id']==first['generation_id']


def test_quote_only_refresh_uses_exact_pinned_cohort_and_metadata(fake_db):
    first=UniverseRefresher(fake_db,FakeMoomoo()).run()
    fake_db._t('app_settings')[0]['value']['last_attempt']={'status':'failed'}
    fake_db._t('screener_universe').append({'market':'US','code':'US.UNRELATED','stock_type':'STOCK'})
    second=UniverseRefresher(fake_db,FakeMoomoo()).run()
    assert 'enum' not in second and second['quotes']['requested']==2
    assert second['generation_id']!=first['generation_id']
    assert all(r['row']['stock_type']=='STOCK' and r['metadata']['plates']==['Software','Semis']
        for r in fake_db._t('screener_generation_rows'))


def test_rate_limit_wait_renews_lease_in_bounded_segments(fake_db,monkeypatch):
    import tradingagents_worker.universe_refresh as module
    from tradingagents_worker.moomoo import RateLimited
    seed_cohort(fake_db)
    waits=[]
    monkeypatch.setattr(module.time,'sleep',waits.append)
    class Provider(FakeMoomoo):
        calls=0
        def snapshot(self,codes,retries=2):
            assert retries==0  # loader owns HTTP-200 retry waits too
            self.calls+=1
            if self.calls==1:raise RateLimited(65,'snapshot')
            return super().snapshot(codes)
    provider=Provider()
    result=UniverseRefresher(fake_db,provider).run()
    assert waits==[30,30,5] and provider.calls==2 and result['quotes']['quotes']==2
    assert sum(name=='screener_refresh_renew' for name,_ in fake_db.rpc_calls)>=6


def test_lost_ownership_after_provider_response_cannot_publish(fake_db):
    seed_cohort(fake_db)
    class Provider(FakeMoomoo):
        def snapshot(self,codes,retries=2):
            fake_db.leases['US']['run_id']='successor'
            fake_db._t('app_settings')[0]['value']['last_attempt']={'run_id':'successor','status':'running'}
            return super().snapshot(codes)
    with pytest.raises(RuntimeError,match='superseded'):UniverseRefresher(fake_db,Provider()).run()
    assert not fake_db._t('screener_generations')
    assert all(r['row']['price']==99 for r in fake_db._t('screener_quotes'))
    assert fake_db._t('app_settings')[0]['value']['last_attempt']['run_id']=='successor'


def test_1201_row_pinned_worker_read_is_not_truncated(fake_db):
    seed_cohort(fake_db,1201)
    first=UniverseRefresher(fake_db,FakeMoomoo()).run()
    assert first['quotes']['quotes']==1201 and first['quotes']['batches']==4
    assert len(UniverseRefresher(fake_db,FakeMoomoo())._stored_codes())==1201


def test_success_clock_must_match_immutable_publication_receipt(fake_db):
    UniverseRefresher(fake_db,FakeMoomoo()).run()
    fake_db._t('app_settings')[0]['value']['last_quotes']='2020-01-01T00:00:00Z'
    with pytest.raises(GenerationError,match='successful receipt'):UniverseRefresher(fake_db,FakeMoomoo()).run()


def test_provider_retry_wait_cannot_hold_market_lease_forever(fake_db,monkeypatch):
    import tradingagents_worker.universe_refresh as module
    from tradingagents_worker.moomoo import RateLimited
    seed_cohort(fake_db)
    monkeypatch.setattr(module.time,'sleep',lambda _:pytest.fail('overbound wait must not sleep'))
    class Provider(FakeMoomoo):
        def snapshot(self,codes,retries=2):raise RateLimited(901,'snapshot')
    with pytest.raises(UniverseRefreshError,match='retry wait'):UniverseRefresher(fake_db,Provider()).run()
    assert fake_db._t('app_settings')[0]['value']['last_attempt']['status']=='failed'
    assert not fake_db._t('screener_generations')


def test_run_duration_bound_releases_failure_without_collecting(fake_db,monkeypatch):
    import tradingagents_worker.universe_refresh as module
    seed_cohort(fake_db)
    monkeypatch.setattr(module,'MAX_RUN_SECONDS',-1)
    with pytest.raises(UniverseRefreshError,match='run duration'):UniverseRefresher(fake_db,FakeMoomoo()).run()
    assert not fake_db._t('screener_generations')
    assert not fake_db.leases['US']['active']


def test_actual_cloud_client_http_200_retry_does_not_sleep_inside_lease(fake_db,monkeypatch):
    import tradingagents_worker.moomoo as cloud
    import json
    client=cloud.MoomooClient.__new__(cloud.MoomooClient)
    client.appkey='test-only';client.offset=0;client.budget=cloud.Budget();client._sign=lambda *a:'test'
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps({'ret_code':-11,'error':{'code':'rate_limited','retry_after':901}}).encode()
    monkeypatch.setattr(cloud,'urlopen',lambda *a,**kw:Response())
    monkeypatch.setattr(cloud.time,'sleep',lambda _:pytest.fail('cloud client must let loader manage the retry'))
    with pytest.raises(UniverseRefreshError,match='retry wait'):
        UniverseRefresher(fake_db,client)._provider(client.snapshot,['US.A'])


def test_valid_plate_pages_exhaust_explicitly_and_keep_all_members(fake_db):
    class Provider(FakeMoomoo):
        queries=[]
        def call(self,method,path,query=None,**kw):
            self.queries.append(query)
            if 'next_key' not in query:return {'stock_list':[{'code':'US.A'}], 'pagination':{'next_key':'page2'}}
            assert query['next_key']=='page2'
            return {'stock_list':[{'code':'US.B'}], 'pagination':{'next_key':'-1'}}
    provider=Provider()
    assert UniverseRefresher(fake_db,provider)._plate_codes('US.PLATE')==['US.A','US.B']
    assert len(provider.queries)==2


@pytest.mark.parametrize('pagination',[False,[],{'next_key':0},{'next_key':-1},{'next_key':True}])
def test_ambiguous_pagination_never_means_terminal(fake_db,pagination):
    class Provider(FakeMoomoo):
        def call(self,*a,**kw):return {'stock_list':[{'code':'US.A'}],'pagination':pagination}
    with pytest.raises(UniverseRefreshError):UniverseRefresher(fake_db,Provider())._plate_codes('US.PLATE')
