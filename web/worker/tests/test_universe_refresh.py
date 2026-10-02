"""Universe loader: plate enumeration → stored universe → snapshot quotes."""
from tradingagents_worker.universe_refresh import UniverseRefresher


class FakeMoomoo:
    def call(self, method, path, body=None, query=None, retries=2):
        if path == "/quote/plate-list":
            return {"plate_list": [{"code": "US.LIST1", "plate_name": "Software"},
                                    {"code": "US.LIST2", "plate_name": "Semis"}]}
        if path == "/quote/plate-stock":
            return {"stock_list": [{"code": "US.PLTR"}, {"code": "US.NVDA"}]}
        return {}

    def snapshot(self, codes):
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
        def snapshot(self,codes):
            out=super().snapshot(codes)
            for row in out['snapshot_list']:row['update_time']=stamp
            return out
    UniverseRefresher(fake_db,Provider(),'US').run()
    for stored in fake_db.select('screener_quotes',{'market':'eq.US'}):
        row=stored['row'];assert row['quote_observed_at']==datetime.fromtimestamp(stamp/1000,timezone.utc).isoformat()
        assert datetime.fromisoformat(stored['updated_at'])>datetime.fromisoformat(row['quote_observed_at'])
        assert row['field_observations']['price']['observed_at']==row['quote_observed_at']
