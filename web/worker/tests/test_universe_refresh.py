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
    assert r["enum"]["plates"] == 2 and r["enum"]["codes"] == 2
    assert r["quotes"]["quotes"] == 2 and r["quotes"]["batches"] == 1
    syms = fake_db.select("screener_universe", {"market": "eq.US"})
    assert {s["code"] for s in syms} == {"US.PLTR", "US.NVDA"}
    q = fake_db.select("screener_quotes", {"market": "eq.US"})
    assert len(q) == 2 and q[0]["row"]["price"] == 10.0
    assert abs(q[0]["row"]["pct"] - 5.26) < 0.01  # prev-close fallback


def test_second_run_skips_enumeration_within_ttl(fake_db):
    ref = UniverseRefresher(fake_db, FakeMoomoo(), "US")
    ref.run()
    r2 = UniverseRefresher(fake_db, FakeMoomoo(), "US").run()
    assert "enum" not in r2 and r2["quotes"]["quotes"] == 2


def test_force_enum_reenumerates(fake_db):
    UniverseRefresher(fake_db, FakeMoomoo(), "US").run()
    r2 = UniverseRefresher(fake_db, FakeMoomoo(), "US").run(force_enum=True)
    assert r2["enum"]["codes"] == 2


def test_progress_events_emitted(fake_db):
    events = []
    UniverseRefresher(fake_db, FakeMoomoo(), "US", emit=lambda *a, **k: events.append(a)).run()
    stages = [e[0] for e in events]
    assert "universe" in stages and events[-1][1] == "done"
