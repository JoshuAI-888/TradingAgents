from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest
from generation_fakes import GenerationDb
from test_universe_refresh import FakeMoomoo
from tradingagents_worker.instrument_classification import classify, validate
from tradingagents_worker.provider_context import info_context
from tradingagents_worker.screener_generations import GenerationError, read_generation
from tradingagents_worker.universe_refresh import UniverseRefresher


def test_broad_trust_category_requires_identity_matched_fresh_subtype():
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    for subtype, expected in [
        ("EQUITY", "STOCK"),
        ("ETF", "ETF"),
        ("MUTUALFUND", "MUTUALFUND"),
        ("UNSUPPORTED", "UNKNOWN"),
    ]:
        context = info_context({"symbol": "PLD", "quoteType": subtype}, "US.PLD", now)
        record = classify("US.PLD", "ETF", stamp, context, stamp, now)
        assert (
            record["stock_type"] == expected
            and record["provider_type"] == "ETF"
            and validate(record, "US.PLD", stamp)
        )
        context["fields"]["quoteType"] = "INDEX"
        assert record["subtype_context"]["fields"]["quoteType"] == subtype
    context = info_context({"symbol": "OTHER", "quoteType": "EQUITY"}, "US.OTHER", now)
    assert classify("US.PLD", "ETF", stamp, context, stamp, now)["stock_type"] == "UNKNOWN"
    for old in [
        (now - timedelta(days=8)).isoformat(),
        (now + timedelta(seconds=1)).isoformat(),
        "bad",
    ]:
        assert (
            classify(
                "US.PLD",
                "ETF",
                stamp,
                info_context({"symbol": "PLD", "quoteType": "EQUITY"}, "US.PLD", now),
                old,
                now,
            )["stock_type"]
            == "UNKNOWN"
        )
    assert classify("US.PLD", "ETF", stamp, now=now)["stock_type"] == "UNKNOWN"
    assert (
        classify("US.PLD", "STOCK", (now - timedelta(days=2)).isoformat(), now=now)["stock_type"]
        == "UNKNOWN"
    )
    assert (
        classify(
            "US.PLD",
            "STOCK",
            stamp,
            info_context({"symbol": "PLD", "quoteType": "ETF"}, "US.PLD", now),
            stamp,
            now,
        )["stock_type"]
        == "UNKNOWN"
    )


class TrustMoomoo(FakeMoomoo):
    def call(self, method, path, body=None, **kwargs):
        if path == "/quote/plate-stock":
            return {
                "stock_list": [{"code": c} for c in ["US.PLD", "US.SPY", "US.AAPL", "US.AMBIG"]]
            }
        if path == "/quote/stock-basicinfo":
            return {
                "basic_list": [
                    {
                        "code": c,
                        "stock_type": "STOCK" if c == "US.AAPL" else "ETF",
                        "exchange": "NYSE",
                    }
                    for c in body["code_list"]
                ]
            }
        return super().call(method, path, body=body, **kwargs)


def test_generation_stock_filter_csv_and_capture_keep_normalized_class_and_raw_evidence(
    monkeypatch,
):
    import csv
    import io
    import json

    from tradingagents_api import main as api
    from tradingagents_api.screen_observations import capture_observation

    monkeypatch.setenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED", "1")
    db = GenerationDb()
    stamp = datetime.now(timezone.utc).isoformat()
    for code, subtype in [("US.PLD", "EQUITY"), ("US.SPY", "ETF")]:
        context = info_context({"symbol": code[3:], "quoteType": subtype}, code)
        db.upsert(
            "screener_enrichment",
            "code",
            {
                "market": "US",
                "code": code,
                "data": {"_meta": {"provider_context": context, "fundamentals_at": stamp}},
            },
        )
    result = UniverseRefresher(db, TrustMoomoo(), "US").run()
    gid = result["generation_id"]
    header, records = read_generation(db, "US", gid)
    by = {r["code"]: r for r in records}
    assert {c: r["metadata"]["stock_type"] for c, r in by.items()} == {
        "US.PLD": "STOCK",
        "US.SPY": "ETF",
        "US.AAPL": "STOCK",
        "US.AMBIG": "UNKNOWN",
    }
    assert by["US.PLD"]["metadata"]["instrument_classification"]["provider_type"] == "ETF"
    monkeypatch.setattr(api, "db", db)
    monkeypatch.setattr(api, "_stored_universe_cache", {})
    monkeypatch.setattr(api, "_market_client", lambda: None)
    monkeypatch.setattr(api, "_merge_universe_meta", lambda rows, market: rows)
    monkeypatch.setattr(api, "_watchlist_symbols", lambda: [])
    data = api.screener(watchlist_only=0, generation_id=gid)
    assert {r["code"] for r in data["rows"]} == {"US.PLD", "US.AAPL"} and data[
        "unclassified_count"
    ] == 1
    csv_rows = list(
        csv.DictReader(
            io.StringIO(
                api.screener(watchlist_only=0, generation_id=gid, export="csv").body.decode(
                    "utf-8-sig"
                )
            )
        )
    )
    retained = json.loads(
        next(r for r in csv_rows if r["code"] == "US.PLD")["instrument_classification"]
    )
    assert retained == by["US.PLD"]["metadata"]["instrument_classification"]
    row = next(r for r in data["rows"] if r["code"] == "US.PLD")
    observed = capture_observation(row, [{"field": "stock_type", "values": ["STOCK"]}])
    assert observed["instrument_classification"] == retained
    row["instrument_classification"]["stock_type"] = "ETF"
    assert observed["instrument_classification"]["stock_type"] == "STOCK"
    with pytest.raises(ValueError, match="classification"):
        capture_observation(row, [])
    target = db._t("screener_generation_rows")[0]
    target["metadata"]["instrument_classification"]["reason"] = "fabricated"
    with pytest.raises(GenerationError, match="classification"):
        read_generation(db, "US", gid)


def test_default_off_keeps_original_provider_classification(monkeypatch):
    monkeypatch.delenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED", raising=False)
    db = GenerationDb()
    result = UniverseRefresher(db, TrustMoomoo(), "US").run()
    _, records = read_generation(db, "US", result["generation_id"])
    assert next(r for r in records if r["code"] == "US.PLD")["metadata"]["stock_type"] == "ETF"
    assert all("instrument_classification" not in r["metadata"] for r in records)


def test_flag_activation_and_rollback_publish_new_cohort_without_rewriting_prior_generation(
    monkeypatch,
):
    db = GenerationDb()
    ref = UniverseRefresher(db, TrustMoomoo(), "US")
    monkeypatch.delenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED", raising=False)
    first = ref.run()
    first_id = first["generation_id"]
    _, original = read_generation(db, "US", first_id)
    monkeypatch.setenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED", "1")
    normalized = ref.run()
    normalized_id = normalized["generation_id"]
    assert normalized_id != first_id
    _, records = read_generation(db, "US", normalized_id)
    assert next(r for r in records if r["code"] == "US.PLD")["metadata"]["stock_type"] == "UNKNOWN"
    monkeypatch.delenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED", raising=False)
    reverted = ref.run()
    assert reverted["generation_id"] not in (first_id, normalized_id)
    _, legacy = read_generation(db, "US", reverted["generation_id"])
    assert next(r for r in legacy if r["code"] == "US.PLD")["metadata"]["stock_type"] == "ETF"
    assert all("instrument_classification" not in r["metadata"] for r in legacy)
    assert read_generation(db, "US", first_id)[1] == original
    assert read_generation(db, "US", normalized_id)[1] == records


def test_old_raw_receipt_forces_new_enumeration_even_when_publication_and_quotes_are_fresh(
    monkeypatch,
):
    monkeypatch.setenv("NORMALIZED_INSTRUMENT_CLASSES_ENABLED", "1")
    db = GenerationDb()
    ref = UniverseRefresher(db, TrustMoomoo(), "US")
    first = ref.run()
    old = (datetime.now(timezone.utc) - timedelta(hours=23)).isoformat()
    # Controlled published fixture: quotes/publication are fresh but basic-info
    # receipt is approaching its own one-day validity limit.
    for item in db._t("screener_generation_rows"):
        meta = item["metadata"]
        meta["provider_classified_at"] = old
        classification = classify(
            item["code"],
            meta["provider_stock_type"],
            old,
            now=datetime.fromisoformat(item["quote_cache_at"]),
        )
        meta["instrument_classification"] = deepcopy(classification)
        item["row"]["instrument_classification"] = deepcopy(classification)
    second = ref.run()
    assert second["generation_id"] != first["generation_id"] and second["enum"]["codes"] == 4
    _, records = read_generation(db, "US", second["generation_id"])
    assert all(
        datetime.fromisoformat(r["metadata"]["provider_classified_at"])
        > datetime.fromisoformat(old)
        for r in records
    )
