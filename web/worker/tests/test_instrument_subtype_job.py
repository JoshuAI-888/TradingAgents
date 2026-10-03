import multiprocessing as mp
import time
from datetime import datetime, timezone

import pytest
from test_instrument_classification import TrustMoomoo
from test_instrument_subtype_store import StoreDb
from tradingagents_worker.instrument_subtype_job import fetch_bounded, main, run
from tradingagents_worker.instrument_subtypes import collect
from tradingagents_worker.universe_refresh import UniverseRefresher


def good(symbol):
    return {"symbol": symbol, "quoteType": "EQUITY", "private": "must not escape"}


def slow(symbol):
    time.sleep(5)
    return good(symbol)


def failed(symbol):
    raise RuntimeError("private provider exception")


def test_real_spawn_success_failure_timeout_and_child_cleanup():
    initial = {p.pid for p in mp.active_children()}
    assert fetch_bounded("PLD", timeout=5, fetch=good) == {"symbol": "PLD", "quoteType": "EQUITY"}
    with pytest.raises(RuntimeError, match="provider unavailable"):
        fetch_bounded("PLD", timeout=5, fetch=failed)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        fetch_bounded("PLD", timeout=0.15, fetch=slow)
    assert time.monotonic() - started < 3
    assert {p.pid for p in mp.active_children()} == initial


def test_job_reads_published_raw_metadata_and_preserves_old_on_retry(monkeypatch):
    monkeypatch.delenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED", raising=False)
    db = StoreDb()
    UniverseRefresher(db, TrustMoomoo(), "US").run()
    result = run(db, fetch=good)
    assert (
        result["attempted"] == 3 and result["saved"] == 3 and result["coverage_qualified"] is False
    )
    previous = db.tables["instrument_subtype_cache"].copy()
    again = run(db, fetch=lambda _: pytest.fail("fresh subtype must not refetch"))
    assert again["attempted"] == 0 and db.tables["instrument_subtype_cache"] == previous


def test_deferred_deadline_is_not_a_failed_retrieval():
    result = collect(
        [{"code": "US.PLD", "provider_stock_type": "ETF"}],
        fetch_info=lambda _: pytest.fail("must not fetch"),
        should_stop=lambda: True,
    )
    assert result["updates"] == {} and result["attempted"] == 0 and result["remaining"] == 1


def test_default_off_does_not_access_database_or_provider(monkeypatch, capsys):
    monkeypatch.delenv("INSTRUMENT_SUBTYPE_COLLECTION_ENABLED", raising=False)
    main()
    assert capsys.readouterr().out.strip() == '{"status": "disabled"}'
    with pytest.raises(ValueError):
        run(StoreDb(), market="BAD")
    with pytest.raises(ValueError):
        fetch_bounded("PLD", timeout=float("nan"))


def descendant_slow(conn):
    import os

    conn.send(os.getpid())
    time.sleep(10)


def grouped_slow(conn):
    import os

    os.setsid()
    child = mp.get_context("spawn").Process(target=descendant_slow, args=(conn,))
    child.start()
    time.sleep(10)


def test_whole_run_stop_kills_provider_process_group():
    from tradingagents_worker.instrument_subtype_job import _stop

    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    process = ctx.Process(target=grouped_slow, args=(child,))
    process.start()
    child.close()
    try:
        assert parent.poll(5)
        assert isinstance(parent.recv(), int)  # descendant is alive and owns pipe
        _stop(process, group=True)
        assert parent.poll(2)
        # EOF proves both the job and live provider descendant closed their
        # writer handles; killing only the leader leaves this pipe open.
        with pytest.raises(EOFError):
            parent.recv()
    finally:
        parent.close()


def test_uncertain_publication_restart_retains_committed_receipt_and_finishes_remaining(
    monkeypatch,
):
    monkeypatch.delenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED", raising=False)
    db = StoreDb()
    UniverseRefresher(db, TrustMoomoo(), "US").run()
    original = db._call

    def uncertain(method, path, body=None):
        result = original(method, path, body)
        if path == "rpc/instrument_subtype_save_leased":
            raise ConnectionError("lost receipt after commit")
        return result

    db._call = uncertain
    with pytest.raises(ConnectionError):
        run(db, fetch=good)
    assert len(db.tables["instrument_subtype_cache"]) == 1
    committed = db.tables["instrument_subtype_cache"][0].copy()
    db._call = original
    restarted = run(db, fetch=good)
    assert restarted["attempted"] == 2 and restarted["saved"] == 2
    assert len(db.tables["instrument_subtype_cache"]) == 3
    assert db.tables["instrument_subtype_cache"][0] == committed


def test_busy_market_skips_without_reading_cohort_or_fetching():
    from datetime import timedelta

    db = StoreDb()
    now = datetime.now(timezone.utc)
    db.subtype_leases["US"] = {
        "id": "30000000-0000-0000-0000-000000000001",
        "market": "US",
        "started_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=330)).isoformat(),
    }
    db.select_all = lambda *a, **kw: pytest.fail("busy market must not read cohort")
    result = run(db, fetch=lambda _: pytest.fail("busy market must not fetch"))
    assert result["skipped"] == "market_collection_already_running"


def test_invalid_claim_receipt_and_unconfirmed_completion_cannot_succeed(monkeypatch):
    monkeypatch.delenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED", raising=False)
    db = StoreDb()
    UniverseRefresher(db, TrustMoomoo(), "US").run()
    original = db._call

    def invalid(method, path, body=None):
        if path == "rpc/instrument_subtype_claim":
            return {"id": body["p_run"], "market": "HK"}
        return original(method, path, body)

    db._call = invalid
    with pytest.raises(ValueError, match="lease receipt"):
        run(db, fetch=lambda _: pytest.fail("must not fetch"))

    def release_failure(method, path, body=None):
        if path == "rpc/instrument_subtype_release":
            return False
        return original(method, path, body)

    db._call = release_failure
    with pytest.raises(RuntimeError, match="completion unconfirmed"):
        run(db, fetch=good)
    assert len(db.tables["instrument_subtype_cache"]) == 3


def throttled(symbol):
    from tradingagents_worker.instrument_subtypes import SubtypeRateLimited

    raise SubtypeRateLimited("safe provider throttle")


def test_actual_spawn_preserves_sanitized_throttle_signal():
    from tradingagents_worker.instrument_subtypes import SubtypeRateLimited

    with pytest.raises(SubtypeRateLimited, match="provider rate limited"):
        fetch_bounded("PLD", timeout=5, fetch=throttled)


def test_actual_yahoo_rate_limit_is_mapped_without_provider_message(monkeypatch):
    import yfinance as yf
    from tradingagents_worker.instrument_subtype_job import _yahoo_info
    from tradingagents_worker.instrument_subtypes import SubtypeRateLimited
    from yfinance.exceptions import YFRateLimitError

    class RateLimitedTicker:
        def get_info(self):
            raise YFRateLimitError()

    monkeypatch.setattr(yf, "Ticker", lambda _: RateLimitedTicker())
    with pytest.raises(SubtypeRateLimited, match="Subtype provider rate limited"):
        _yahoo_info("PLD")
