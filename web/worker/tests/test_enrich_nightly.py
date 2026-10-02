"""Nightly orchestrator: yf batch + technicals from stored klines → one row/code."""
from datetime import datetime, timedelta, timezone

from tradingagents_worker.enrich_nightly import EnrichNightly


class FakeYf:
    def __init__(self, rows):
        self.rows = rows

    def __call__(self, codes, prices, market="US", yf_module=None):
        return [r for r in self.rows if r["code"] in codes]


def _seed(db):
    db.upsert_many("screener_universe", "market,code",
                   [{"market": "US", "code": "US.AAPL"}])
    fresh = datetime.now(timezone.utc).isoformat()
    db.upsert("screener_kline_state", "market,code",
              {"market": "US", "code": "US.AAPL", "last_fetch": fresh, "bars": 260})
    bars = [{"market": "US", "code": "US.AAPL", "day": f"2025-01-{d:02d}",
             "o": 100, "h": 102, "l": 99, "c": 100 + d, "v": 1_000_000}
            for d in range(1, 29)]
    db.upsert_many("screener_klines", "market,code,day", bars)
    db.upsert_many("screener_quotes", "code",
                   [{"code": "US.AAPL", "market": "US", "row": {"price": 128.0},
                     "updated_at": fresh}])


def test_run_writes_merged_enrichment(fake_db):
    _seed(fake_db)
    yf = FakeYf([{"market": "US", "code": "US.AAPL", "data": {"forward_pe": 30.0},
                  "source": "yfinance", "as_of": "2025-01-01T00:00:00+00:00"}])
    out = EnrichNightly(fake_db, yf_fetch=yf, market="US").run(run_klines=False)
    assert out["enriched"] == 1
    rows = fake_db.select("screener_enrichment", {"market": "eq.US"})
    data = rows[0]["data"]
    assert data["forward_pe"] == 30.0
    assert "rsi14" in data and "sma20_pos" in data      # klines fresh → technicals present
    assert rows[0]["source"] == "yfinance+computed"


def test_stale_klines_yield_no_technicals(fake_db):
    _seed(fake_db)
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    fake_db.upsert("screener_kline_state", "market,code",
                   {"market": "US", "code": "US.AAPL", "last_fetch": old, "bars": 260})
    yf = FakeYf([{"market": "US", "code": "US.AAPL", "data": {"forward_pe": 30.0},
                  "source": "yfinance", "as_of": "2025-01-01T00:00:00+00:00"}])
    EnrichNightly(fake_db, yf_fetch=yf, market="US").run(run_klines=False)
    data = fake_db.select("screener_enrichment", {"market": "eq.US"})[0]["data"]
    assert "forward_pe" in data and "rsi14" not in data  # absent, never stale-zero


def test_kline_rotation_runs_by_default(fake_db, monkeypatch):
    _seed(fake_db)
    ran = {}

    class SpyKb:
        def __init__(self, db, client, market="US", emit=None):
            pass

        def stale_codes(self, limit=1400):
            return ["US.AAPL"]

        def backfill(self, codes):
            ran["codes"] = codes
            return {"codes": len(codes), "bars": 2, "errors": 0}

    import tradingagents_worker.enrich_nightly as en
    monkeypatch.setattr(en, "KlineBackfill", SpyKb)
    yf = FakeYf([])
    out = EnrichNightly(fake_db, yf_fetch=yf, market="US").run()
    assert ran["codes"] == ["US.AAPL"] and "klines" in out


def test_prices_pulled_from_quotes_for_derived_ratios(fake_db):
    _seed(fake_db)
    seen = {}

    class SpyYf:
        def __call__(self, codes, prices, market="US", yf_module=None):
            seen.update(prices)
            return []

    EnrichNightly(fake_db, yf_fetch=SpyYf(), market="US").run(run_klines=False)
    assert seen.get("US.AAPL") == 128.0


def test_yf_batch_is_missing_first_and_bounded(fake_db, monkeypatch):
    """Production guard: the nightly yf batch covers missing/oldest codes first
    and is capped per run — a full 13.5k-universe sweep would blow the cron's
    runtime. Fresh codes are skipped entirely."""
    import tradingagents_worker.enrich_nightly as en

    fresh = datetime.now(timezone.utc).isoformat()
    old = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    fake_db.upsert_many("screener_universe", "market,code",
                   [{"market": "US", "code": c} for c in ("US.A", "US.B", "US.C")])
    fake_db.upsert_many("screener_quotes", "code",
                   [{"code": c, "market": "US", "row": {"price": 10.0}, "updated_at": fresh}
                    for c in ("US.A", "US.B", "US.C")])
    fake_db.upsert_many("screener_enrichment", "market,code",
                   [{"market": "US", "code": "US.B", "data": {"beta": 1.0},
                     "source": "yfinance", "as_of": fresh}])
    fake_db.upsert_many("screener_enrichment", "market,code",
                   [{"market": "US", "code": "US.C", "data": {"beta": 2.0},
                     "source": "yfinance", "as_of": old}])
    seen = []

    class SpyYf:
        def __call__(self, codes, prices, market="US", yf_module=None):
            seen.append(list(codes))
            return []

    monkeypatch.setattr(en, "YF_BATCH_PER_RUN", 2)
    EnrichNightly(fake_db, yf_fetch=SpyYf(), market="US").run(run_klines=False)
    got = seen[0]
    assert "US.B" not in got                       # enriched 2h... fresh → skipped
    assert set(got) <= {"US.A", "US.C"}            # missing + stale only
    assert got[0] == "US.A" or got[0] == "US.C"    # missing/stale first
    assert len(got) == 2                           # cap respected


def test_technicals_stream_per_chunk_not_all_in_memory(fake_db, monkeypatch):
    """Regression (production 2026-10-01 00:04 UTC): loading every fresh code's
    bars into one dict OOM-killed the 512MiB cron at 3,254 codes. Bars must be
    read and computed per BAR_CHUNK, then discarded — verify one select per
    chunk and technicals landing for codes in every chunk."""
    import tradingagents_worker.enrich_nightly as en

    fresh = datetime.now(timezone.utc).isoformat()
    codes = [f"US.S{i}" for i in range(5)]
    fake_db.upsert_many("screener_universe", "market,code",
                        [{"market": "US", "code": c} for c in codes])
    fake_db.upsert_many("screener_kline_state", "market,code",
                        [{"market": "US", "code": c, "last_fetch": fresh} for c in codes])
    fake_db.upsert_many("screener_klines", "market,code,day",
                        [{"market": "US", "code": c, "day": f"2025-01-{d:02d}",
                          "o": 100, "h": 102, "l": 99, "c": 100 + d, "v": 1e6}
                         for c in codes for d in range(1, 29)])
    yf = FakeYf([])
    monkeypatch.setattr(en, "BAR_CHUNK", 2)

    kline_rows_read = [0]   # cumulative bars returned by the time each compute() runs
    orig_select_all = fake_db.select_all

    def counting_select_all(table, query=None, columns="*"):
        out = orig_select_all(table, query, columns)
        if table == "screener_klines":
            kline_rows_read[0] += len(out)
        return out

    monkeypatch.setattr(fake_db, "select_all", counting_select_all)

    compute_at = []
    orig_compute = en.compute

    def spy_compute(bars):
        compute_at.append(kline_rows_read[0])   # memory watermark: bars read so far
        return orig_compute(bars)

    monkeypatch.setattr(en, "compute", spy_compute)
    out = EnrichNightly(fake_db, yf_fetch=yf, market="US").run(run_klines=False)
    # ACCUMULATION mode: every select finishes before the first compute →
    # watermark at first compute = ALL 5*28=140 rows. STREAMING mode: only the
    # current chunk's rows exist → watermark <= 2 codes * 28 days.
    assert max(compute_at[:1]) <= 2 * 28, f"bars accumulated before compute: {compute_at[0]}"
    assert out["enriched"] == 5                        # every code still enriched
    rows = {r["code"]: r["data"] for r in fake_db.select("screener_enrichment", {"market": "eq.US"})}
    assert all("sma20_pos" in rows[c] for c in codes)  # technicals intact across chunks


def test_successful_fundamental_refresh_removes_disappeared_fields_and_keeps_provider_clock(fake_db):
    _seed(fake_db)
    old = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    fetched = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    fake_db.upsert("screener_enrichment", "market,code", {"market":"US", "code":"US.AAPL",
        "as_of":old, "data":{"forward_pe":30, "sector":"Old sector", "lt_debt_eq":25,
                             "beta":1, "_meta":{"fundamentals_at":old}}})
    yf=FakeYf([{"market":"US", "code":"US.AAPL", "as_of":fetched,
                "data":{"beta":0, "forward_pe":None, "rsi14":999, "_meta":{"fundamentals_at":"bad"}}}])
    EnrichNightly(fake_db,yf_fetch=yf).run(run_klines=False)
    data=fake_db.select("screener_enrichment", {"market":"eq.US"})[0]["data"]
    assert data["beta"] == 0
    assert "forward_pe" not in data and "sector" not in data and "lt_debt_eq" not in data
    assert data["rsi14"] != 999
    assert data["_meta"]["fundamentals_at"] == fetched
    assert data["_meta"]["technicals_at"] != fetched


def test_failed_fundamental_fetch_cannot_renew_old_fields_with_a_technical_update(fake_db):
    _seed(fake_db)
    old=(datetime.now(timezone.utc)-timedelta(days=9)).isoformat()
    fake_db.upsert("screener_enrichment", "market,code", {"market":"US", "code":"US.AAPL",
        "as_of":old, "data":{"forward_pe":30, "_meta":{"fundamentals_at":old}}})
    EnrichNightly(fake_db,yf_fetch=FakeYf([])).run(run_klines=False)
    row=fake_db.select("screener_enrichment", {"market":"eq.US"})[0]
    assert row["data"]["forward_pe"] == 30  # retained cache, still old and ineligible
    assert row["data"]["_meta"]["fundamentals_at"] == old
    assert row["data"]["_meta"]["technicals_at"] == row["as_of"]


def test_fundamental_refresh_rejects_other_market_naive_or_future_clocks(fake_db):
    _seed(fake_db)
    future=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
    for market,stamp in [("HK",datetime.now(timezone.utc).isoformat()),("US","2026-01-01T00:00:00"),("US",future)]:
        out=EnrichNightly(fake_db,yf_fetch=FakeYf([{"market":market,"code":"US.AAPL","as_of":stamp,"data":{"beta":99}}])).run(run_klines=False)
        assert out["enriched"] == 1  # technical category still progresses
        data=fake_db.select("screener_enrichment", {"market":"eq.US"})[0]["data"]
        assert "beta" not in data


def test_worker_refresh_output_cannot_qualify_disappeared_factors_in_actual_api(fake_db,monkeypatch):
    from tradingagents_api import main as api
    _seed(fake_db)
    old=(datetime.now(timezone.utc)-timedelta(days=9)).isoformat()
    fetched=(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()
    fake_db.upsert('screener_enrichment','market,code',{'market':'US','code':'US.AAPL','as_of':old,
        'data':{'forward_pe':30,'_meta':{'fundamentals_at':old}}})
    EnrichNightly(fake_db,yf_fetch=FakeYf([{'market':'US','code':'US.AAPL','as_of':fetched,'data':{'beta':0}}])).run(run_klines=False)
    monkeypatch.setattr(api,'db',fake_db)
    monkeypatch.setattr(api,'_market_client',lambda:object())
    monkeypatch.setattr(api,'_merge_universe_meta',lambda rows,market:rows)
    monkeypatch.setattr(api,'_stored_universe',lambda *args,**kwargs:([{'code':'US.AAPL','symbol':'AAPL','stock_type':'STOCK','price':128}],fetched))
    result=api.screener(watchlist_only=0,src='yf')
    row=result['rows'][0]
    assert row['beta']==0 and 'forward_pe' not in row
    assert row['display_field_sources']['beta']['cache_at']==fetched
    assert api.screener(watchlist_only=0,src='yf',filters='[{"field":"forward_pe","max":40}]')['rows']==[]


def test_empty_success_clears_prior_fundamentals_without_removing_technicals(fake_db):
    _seed(fake_db)
    old=(datetime.now(timezone.utc)-timedelta(days=9)).isoformat();now=datetime.now(timezone.utc).isoformat()
    fake_db.upsert('screener_enrichment','market,code',{'market':'US','code':'US.AAPL','as_of':old,
        'data':{'forward_pe':30,'sector':'Technology','_meta':{'fundamentals_at':old}}})
    EnrichNightly(fake_db,yf_fetch=FakeYf([{'market':'US','code':'US.AAPL','as_of':now,'data':{}}])).run(run_klines=False)
    data=fake_db.select('screener_enrichment',{'market':'eq.US'})[0]['data']
    assert 'forward_pe' not in data and 'sector' not in data and 'rsi14' in data
    assert data['_meta']['fundamentals_at']==now
