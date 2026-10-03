from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from generation_fakes import GenerationDb
from test_instrument_classification import TrustMoomoo
from tradingagents_worker.instrument_subtype_store import contexts, publish, read_cache
from tradingagents_worker.instrument_subtypes import collect
from tradingagents_worker.screener_generations import read_generation
from tradingagents_worker.universe_refresh import UniverseRefresher


def evidence(now=None):
    now = now or datetime.now(timezone.utc)
    return collect(
        [{"code": "US.PLD", "provider_stock_type": "ETF"}],
        fetch_info=lambda s: {"symbol": s, "quoteType": "EQUITY"},
        now=now,
    )["updates"]


FIXTURE_TOKEN = "00000000-0000-0000-0000-000000000001"


class StoreDb(GenerationDb):
    def __init__(self):
        super().__init__()
        self.subtype_leases = {}

    def _call(self, method, path, body=None):
        assert method == "POST"
        if path == "rpc/instrument_subtype_claim":
            existing = self.subtype_leases.get(body["p_market"])
            if existing is not None:
                return None
            now = datetime.now(timezone.utc)
            receipt = {
                "id": body["p_run"],
                "market": body["p_market"],
                "started_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=330)).isoformat(),
            }
            self.subtype_leases[body["p_market"]] = receipt
            return deepcopy(receipt)
        if path == "rpc/instrument_subtype_release":
            existing = self.subtype_leases.get(body["p_market"])
            if existing and existing["id"] == body["p_run"]:
                del self.subtype_leases[body["p_market"]]
                return True
            return False
        assert path == "rpc/instrument_subtype_save_leased"
        # Adapter-only fixture assumes the explicit fixture token owns a lease;
        # job tests acquire a distinct actual token through the RPC double.
        if body["p_run"] != FIXTURE_TOKEN:
            assert self.subtype_leases[body["p_market"]]["id"] == body["p_run"]
        table = self._t("instrument_subtype_cache")
        old = next(
            (r for r in table if r["market"] == body["p_market"] and r["code"] == body["p_code"]),
            None,
        )
        expected = body["p_revision"]
        current = old["revision"] if old else 0
        if current == expected:
            row = {
                "market": body["p_market"],
                "code": body["p_code"],
                "revision": expected + 1,
                "record": deepcopy(body["p_record"]),
            }
            self.upsert("instrument_subtype_cache", "market,code", row)
            return [deepcopy(row)]
        if current == expected + 1 and old["record"] == body["p_record"]:
            return [deepcopy(old)]
        return []


def test_store_read_publish_replay_and_stale_conflict():
    db = StoreDb()
    now = datetime.now(timezone.utc)
    updates = evidence(now)
    result = publish(db, "US", updates, {}, now, run_id=FIXTURE_TOKEN)
    assert result == {"saved": ["US.PLD"], "conflicts": []}
    assert publish(db, "US", updates, {}, now, run_id=FIXTURE_TOKEN) == result
    records, revisions = read_cache(db, "US", now)
    assert records == updates and revisions == {"US.PLD": 1}
    newer = evidence(now + timedelta(seconds=1))
    assert (
        publish(db, "US", newer, revisions, now + timedelta(seconds=1), run_id=FIXTURE_TOKEN)
        == result
    )
    assert publish(
        db, "US", updates, revisions, now + timedelta(seconds=1), run_id=FIXTURE_TOKEN
    ) == {"saved": [], "conflicts": ["US.PLD"]}
    assert contexts(db, "US", now + timedelta(days=8)) == {}
    records["US.PLD"]["context"]["fields"]["quoteType"] = "ETF"
    assert (
        db._t("instrument_subtype_cache")[0]["record"]["context"]["fields"]["quoteType"] == "EQUITY"
    )


def test_invalid_reads_and_scope_are_rejected():
    db = StoreDb()
    now = datetime.now(timezone.utc)
    publish(db, "US", evidence(now), {}, now, run_id=FIXTURE_TOKEN)
    original = deepcopy(db._t("instrument_subtype_cache"))
    for key, value in [("market", "HK"), ("revision", True), ("record", None)]:
        db.tables["instrument_subtype_cache"] = deepcopy(original)
        db.tables["instrument_subtype_cache"][0][key] = value
        # Market mismatch is filtered out by the database; use a raw response
        # override to exercise validation of an unexpected response.
        db.select_all = lambda *a, **k: db.tables["instrument_subtype_cache"]
        with pytest.raises(ValueError):
            read_cache(db, "US", now)
    with pytest.raises(ValueError):
        publish(db, "HK", evidence(now), {}, now, run_id=FIXTURE_TOKEN)
    with pytest.raises(ValueError):
        publish(db, "US", evidence(now), {"US.PLD": True}, now, run_id=FIXTURE_TOKEN)


def test_actual_dedicated_cache_to_generation_and_stock_only_api(monkeypatch):
    monkeypatch.setenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED", "1")
    monkeypatch.setenv("INSTRUMENT_SUBTYPE_CACHE_ENABLED", "1")
    db = StoreDb()
    publish(db, "US", evidence(), {}, run_id=FIXTURE_TOKEN)
    result = UniverseRefresher(db, TrustMoomoo(), market="US").run(force_enum=True)
    _, records = read_generation(db, "US", result["generation_id"])
    by = {r["code"]: r for r in records}
    assert by["US.PLD"]["row"]["stock_type"] == "STOCK"
    assert by["US.PLD"]["row"]["instrument_classification"]["subtype_context"]["fields"] == {
        "quoteType": "EQUITY"
    }
    from tradingagents_api import main

    monkeypatch.setattr(main, "db", db)
    monkeypatch.setattr(main, "_stored_universe_cache", {})
    monkeypatch.setattr(main, "_market_client", lambda: None)
    monkeypatch.setattr(main, "_merge_universe_meta", lambda rows, market: rows)
    monkeypatch.setattr(main, "_watchlist_symbols", lambda: [])
    response = main.screener(watchlist_only=0, generation_id=result["generation_id"])
    assert "US.PLD" in {r["code"] for r in response["rows"]}


def test_newer_same_provider_context_wins_without_mutating_either_cache(monkeypatch):
    from tradingagents_worker.provider_context import info_context

    monkeypatch.setenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED", "1")
    monkeypatch.setenv("INSTRUMENT_SUBTYPE_CACHE_ENABLED", "1")
    now = datetime.now(timezone.utc)
    db = StoreDb()
    publish(db, "US", evidence(now - timedelta(minutes=20)), {}, now, run_id=FIXTURE_TOKEN)
    newer = (now - timedelta(minutes=10)).isoformat()
    context = info_context({"symbol": "PLD", "quoteType": "ETF"}, "US.PLD", now)
    db.upsert(
        "screener_enrichment",
        "code",
        {
            "market": "US",
            "code": "US.PLD",
            "data": {"_meta": {"provider_context": context, "fundamentals_at": newer}},
        },
    )
    original = deepcopy(db.tables)
    result = UniverseRefresher(db, TrustMoomoo(), "US")._classification_contexts()
    assert result["US.PLD"]["provider_context"]["fields"]["quoteType"] == "ETF"
    assert db.tables == original


def test_default_off_does_not_read_dedicated_storage(monkeypatch):
    monkeypatch.setenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED", "1")
    monkeypatch.delenv("INSTRUMENT_SUBTYPE_CACHE_ENABLED", raising=False)
    db = StoreDb()
    original = db.select_all

    def read(table, *a, **kw):
        assert table != "instrument_subtype_cache"
        return original(table, *a, **kw)

    db.select_all = read
    assert UniverseRefresher(db, TrustMoomoo(), "US")._classification_contexts() == {}


def test_unrelated_legacy_enrichment_cannot_block_requested_stock_cohort(monkeypatch):
    monkeypatch.setenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED", "1")
    monkeypatch.delenv("INSTRUMENT_SUBTYPE_CACHE_ENABLED", raising=False)
    db = StoreDb()
    db.upsert("screener_enrichment", "code", {"market": "US", "code": "AU..XJO", "data": {}})
    db.upsert(
        "screener_enrichment",
        "code",
        {"market": "US", "code": "US.PLD", "data": {"_meta": {"marker": "retained"}}},
    )
    original = deepcopy(db.tables)
    result = UniverseRefresher(db, TrustMoomoo(), "US")._classification_contexts(["US.PLD"])
    assert result == {"US.PLD": {"marker": "retained"}}
    assert db.tables == original


def test_duplicate_requested_classification_context_still_fails(monkeypatch):
    from tradingagents_worker.universe_refresh import UniverseRefreshError

    monkeypatch.setenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED", "1")
    db = StoreDb()
    db.tables["screener_enrichment"] = [{"code": "US.PLD", "market": "US", "data": {}}] * 2
    with pytest.raises(UniverseRefreshError, match="duplicate classification context"):
        UniverseRefresher(db, TrustMoomoo(), "US")._classification_contexts(["US.PLD"])
