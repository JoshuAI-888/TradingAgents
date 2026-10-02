"""Generation-consistent public readers: publication between requests and corruption."""
import hashlib
import uuid
import pytest
from fastapi.testclient import TestClient
from tradingagents_api import main as api
from test_api import FakeDb


class GenerationDb(FakeDb):
    def select_all(self, table, query=None, columns='*', cap=20000):
        return self.select(table, query, columns)[:cap]


def publish(db, codes=('US.A', 'US.B'), price=10):
    gid = str(uuid.uuid4())
    stamp = '2026-10-02T06:00:00+00:00'
    result = {'quotes': {'market': 'US', 'quotes': len(codes)}}
    db._t('screener_generations').append({'id': gid, 'market': 'US', 'row_count': len(codes),
        'started_at': '2026-10-02T05:59:00+00:00', 'published_at': stamp,
        'cohort_fingerprint': hashlib.sha256('\n'.join(sorted(codes)).encode()).hexdigest(), 'result': result})
    for i, code in enumerate(codes):
        db._t('screener_generation_rows').append({'generation_id': gid, 'code': code,
            'row': {'code': code, 'price': price+i, 'market_cap': 100-i, 'stock_type': 'ETF', 'plate': 'WRONG'},
            'metadata': {'code': code, 'market': 'US', 'name': code, 'stock_type': 'STOCK',
                         'plate': 'Pinned', 'plates': ['Pinned', 'Theme'], 'exchange': 'NASDAQ'},
            'quote_cache_at': stamp})
    db.upsert('app_settings', 'key', {'key': 'universe_state_US', 'value': {
        'generation_id': gid, 'last_quotes': stamp, 'last_result': result}})
    return gid


@pytest.fixture
def setup(monkeypatch):
    db = GenerationDb()
    monkeypatch.setattr(api, 'db', db)
    monkeypatch.setattr(api, '_stored_universe_cache', {})
    monkeypatch.setattr(api, '_presets_cache', {})
    monkeypatch.setattr(api, '_market_client', lambda: None)
    monkeypatch.setattr(api, '_watchlist_symbols', lambda: [])
    db._t('screener_quotes').append({'code': 'US.LEGACY', 'row': {'code': 'US.LEGACY', 'stock_type': 'STOCK'}})
    return db, TestClient(api.app)


def test_pointer_change_bypasses_market_cache_and_old_generation_stays_pinned(setup):
    db, client = setup
    first = publish(db)
    a = client.get('/api/screener?watchlist_only=0&limit=1').json()
    assert a['available'] and a['generation_id'] == first
    assert [r['code'] for r in a['rows']] == ['US.A']
    second = publish(db, ('US.C', 'US.D'), 20)
    current = client.get('/api/screener?watchlist_only=0&limit=1&offset=1').json()
    original = client.get(f'/api/screener?watchlist_only=0&limit=1&offset=1&generation_id={first}').json()
    assert current['generation_id'] == second and current['rows'][0]['code'] == 'US.D'
    assert original['generation_id'] == first and original['rows'][0]['code'] == 'US.B'
    assert original['rows'][0]['price'] == 11


def test_metadata_and_mutation_do_not_mix_generations(setup):
    db, _ = setup
    gid = publish(db)
    a, _ = api._stored_universe('US')
    assert a[0]['stock_type'] == 'STOCK' and a[0]['plate'] == 'Pinned'
    assert a[0]['concepts'] == ['Theme']
    a[0]['concepts'].append('Uncommitted')
    a[0]['price'] = 999
    db._t('screener_universe').append({'code': 'US.A', 'stock_type': 'ETF', 'plate': 'Mixed'})
    b, _ = api._stored_universe('US')
    assert b[0]['price'] == 10 and b[0]['concepts'] == ['Theme']
    assert api._merge_universe_meta(b, 'US')[0]['generation_id'] == gid


@pytest.mark.parametrize('damage', ['null_pointer', 'missing_header', 'missing_row', 'fingerprint', 'clock', 'metadata'])
def test_corrupt_generation_fails_closed_without_legacy_or_vendor_fallback(setup, damage):
    db, client = setup
    publish(db)
    if damage == 'null_pointer': db.tables['app_settings'][0]['value']['generation_id'] = None
    elif damage == 'missing_header': db.tables['screener_generations'] = []
    elif damage == 'missing_row': db.tables['screener_generation_rows'].pop()
    elif damage == 'fingerprint': db.tables['screener_generations'][0]['cohort_fingerprint'] = 'bad'
    elif damage == 'clock': db.tables['app_settings'][0]['value']['last_quotes'] = '2026-10-02T06:00:01Z'
    else: db.tables['screener_generation_rows'][0]['metadata']['market'] = 'HK'
    assert client.get('/api/screener?watchlist_only=0').status_code == 503
    assert client.get('/api/screener/presets').status_code == 503
    assert client.get('/api/screener/facets?field=plate').status_code == 503


def test_empty_filter_and_download_keep_generation_identity(setup):
    db, client = setup
    gid = publish(db)
    empty = client.get('/api/screener', params={'watchlist_only': 0,
        'filters': '[{"field":"price","min":999}]'}).json()
    assert empty['count'] == 0 and empty['generation_id'] == gid
    csv = client.get('/api/screener', params={'watchlist_only':0, 'export':'csv', 'generation_id':gid})
    assert csv.status_code == 200 and csv.headers['X-Screener-Generation'] == gid
    assert 'US.LEGACY' not in csv.text and gid in csv.text


def test_generation_bound_to_market_and_watchlist(setup):
    db, client = setup
    gid = publish(db)
    assert client.get(f'/api/screener?market=HK&watchlist_only=0&generation_id={gid}').status_code == 503
    # Reject explicit market generation before making any watchlist request.
    assert client.get(f'/api/screener?watchlist_only=1&generation_id={gid}').status_code == 400


def test_read_full_cohort_over_postgrest_page_size(setup):
    db, _ = setup
    codes = tuple(f'US.A{i:04}' for i in range(1201))
    publish(db, codes)
    rows, _ = api._stored_universe('US')
    assert len(rows) == 1201 and {r['code'] for r in rows} == set(codes)


def test_schedule_and_groups_exclude_retained_legacy_rows(setup):
    db, client = setup
    gid = publish(db)
    db._t('screener_universe').append({'code': 'US.LEGACY', 'market': 'US', 'stock_type': 'STOCK'})
    counts = client.get('/api/screener/schedule').json()
    assert counts['generation_id'] == gid
    assert counts['quote_rows'] == counts['universe_rows'] == counts['stock_rows'] == 2
    group = client.get('/api/groups?group_by=plate').json()
    assert group['available'] and group['rows'][0]['stocks'] == 2 and group['generation_id'] == gid


def test_cached_preview_cannot_mask_corrupt_success_state(setup):
    db, client = setup
    publish(db)
    assert client.get('/api/screener/presets').status_code == 200
    db.tables['app_settings'][0]['value']['last_quotes'] = '2026-10-02T06:00:01Z'
    assert client.get('/api/screener/presets').status_code == 503
