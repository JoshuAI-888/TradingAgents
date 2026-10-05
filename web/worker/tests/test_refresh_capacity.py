"""Storage admission fails closed before run acquisition or provider calls."""

import copy

import pytest
from generation_fakes import GenerationDb
from test_universe_refresh import FakeMoomoo
from tradingagents_worker.db import Db
from tradingagents_worker.universe_refresh import UniverseRefresher, UniverseRefreshError

BUDGET = 500 * 1024 * 1024


def receipt(used=0, market="US"):
    return {
        "version": "screener_capacity_v1",
        "market": market,
        "used_bytes": used,
        "limit_bytes": BUDGET,
        "allowed": used < BUDGET,
        "relation_bytes": {"generation_rows": used, "staged_rows": 0, "generations": 0},
    }


class NoProvider:
    def __getattr__(self, name):
        pytest.fail("Capacity rejection must not access the provider")


@pytest.mark.parametrize("used", [BUDGET, BUDGET + 1, BUDGET * 2])
def test_full_capacity_repeated_attempts_do_not_grow_storage_or_change_pointer(used, monkeypatch):
    db = GenerationDb()
    prior = UniverseRefresher(db, FakeMoomoo()).run()
    before = copy.deepcopy(db.tables)
    leases = copy.deepcopy(db.leases)
    staged = copy.deepcopy(db.staged)
    calls = []

    def capacity_only(name, body):
        calls.append(name)
        assert name == "screener_refresh_capacity"
        return receipt(used)

    monkeypatch.setattr(db, "generation_rpc", capacity_only)
    events = []
    for _ in range(3):
        with pytest.raises(UniverseRefreshError, match="500 MiB admission budget"):
            UniverseRefresher(db, NoProvider(), emit=lambda *args: events.append(args)).run(
                force_enum=True
            )
    assert calls == ["screener_refresh_capacity"] * 3
    assert db.tables == before and db.leases == leases and db.staged == staged
    assert db._t("app_settings")[0]["value"]["generation_id"] == prior["generation_id"]
    assert len(events) == 3 and all(event[1] == "failed" for event in events)


@pytest.mark.parametrize(
    "patch",
    [
        {"used_bytes": -1},
        {"used_bytes": True},
        {"used_bytes": "0"},
        {"limit_bytes": -1},
        {"limit_bytes": BUDGET + 1},
        {"limit_bytes": float(BUDGET)},
        {"allowed": 1},
        {"allowed": False},
        {"market": "HK"},
        {"version": "other"},
        {"relation_bytes": {"generation_rows": -1, "staged_rows": 0, "generations": 1}},
        {"relation_bytes": {"generation_rows": 0}},
        {"relation_bytes": {"generation_rows": 1, "staged_rows": 0, "generations": 0}},
        {"relation_bytes": None},
    ],
)
def test_malformed_capacity_receipts_fail_closed(patch, monkeypatch):
    db = GenerationDb()
    bad = {**receipt(), **patch}
    calls = []
    monkeypatch.setattr(db, "generation_rpc", lambda name, body: calls.append(name) or bad)
    with pytest.raises(UniverseRefreshError, match="Invalid screener capacity acknowledgement"):
        UniverseRefresher(db, NoProvider()).run(force_enum=True)
    assert calls == ["screener_refresh_capacity"]
    assert not db.leases and not db.staged and not db._t("screener_generations")


@pytest.mark.parametrize("bad", [None, [], {}, "unavailable"])
def test_missing_capacity_receipt_stops_refresh(bad, monkeypatch):
    db = GenerationDb()
    monkeypatch.setattr(db, "generation_rpc", lambda name, body: bad)
    with pytest.raises(UniverseRefreshError, match="Invalid screener capacity acknowledgement"):
        UniverseRefresher(db, NoProvider()).run(force_enum=True)
    assert not db.leases


def test_capacity_rpc_error_is_sanitized_and_preserves_state(monkeypatch):
    db = GenerationDb()

    def failed(name, body):
        raise RuntimeError("sensitive transport details")

    monkeypatch.setattr(db, "generation_rpc", failed)
    with pytest.raises(UniverseRefreshError, match="capacity check unavailable") as failure:
        UniverseRefresher(db, NoProvider()).run(force_enum=True)
    assert "sensitive" not in str(failure.value)
    assert not db.leases and not db._t("app_settings")


@pytest.mark.parametrize("market", ["US", "HK"])
def test_under_budget_acknowledgement_precedes_acquisition_and_publication(market, monkeypatch):
    db = GenerationDb()
    original = db.generation_rpc

    def checked(name, body):
        if name == "screener_refresh_capacity":
            db.rpc_calls.append((name, copy.deepcopy(body)))
            return receipt(BUDGET - 1, market)
        return original(name, body)

    monkeypatch.setattr(db, "generation_rpc", checked)
    if market == "HK":
        from test_universe_refresh import WholeMarketMoomoo

        monkeypatch.setenv("UNIVERSE_ENUMERATION_MODE_HK", "screen")
        provider = WholeMarketMoomoo("HK")
    else:
        provider = FakeMoomoo()
    result = UniverseRefresher(db, provider, market).run(force_enum=True)
    assert result["generation_id"]
    assert [name for name, _ in db.rpc_calls][:2] == [
        "screener_refresh_capacity",
        "screener_refresh_begin",
    ]


def test_capacity_rpc_is_allowed_by_actual_transport_adapter(monkeypatch):
    db = Db(url="https://unused.invalid", key="test")
    calls = []
    monkeypatch.setattr(
        db, "_call", lambda *args, **kwargs: calls.append((args, kwargs)) or receipt()
    )
    assert db.generation_rpc("screener_refresh_capacity", {"p_market": "US"}) == receipt()
    assert calls == [(("POST", "rpc/screener_refresh_capacity"), {"body": {"p_market": "US"}})]
