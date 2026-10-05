from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from test_api import FakeDb
from tradingagents_api import main
from tradingagents_api.screen_capture_aliases import append_capture_batch
from tradingagents_api.screen_definition_identity import definition_identity, semantic_definition


class CaptureCalls:
    def __init__(self):
        self.calls = []

    def _call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return 1


def snapshot():
    definition = main.ScreenDefinition(
        filters=[{"field": "price", "min": None, "max": 10, "_label": "Price"}]
    ).model_dump()
    return {
        "id": str(uuid4()),
        "definition": definition,
        "definition_identity": definition_identity(definition),
    }


def test_default_off_retains_original_rpc_and_raw_records(monkeypatch):
    monkeypatch.delenv("CAPTURE_DEFINITION_ALIASES_ENABLED", raising=False)
    s = snapshot()
    records = [{"id": s["id"], "snapshot": s}]
    original = deepcopy(records)
    db = CaptureCalls()
    assert append_capture_batch(db, "raw-key", records, s) == 1
    assert db.calls == [
        (
            ("POST", "rpc/screen_capture_append"),
            {"body": {"p_key": "raw-key", "p_records": records}},
        )
    ]
    assert records == original


def test_enabled_writer_passes_canonical_identity_and_preserves_original_evidence(monkeypatch):
    monkeypatch.setenv("CAPTURE_DEFINITION_ALIASES_ENABLED", "1")
    s = snapshot()
    original = deepcopy(s)
    db = CaptureCalls()
    append_capture_batch(db, "raw-key", [{"id": s["id"], "snapshot": s}], s)
    args, kwargs = db.calls[0]
    body = kwargs["body"]
    assert args == ("POST", "rpc/screen_capture_append_with_alias")
    assert (
        body["p_capture_id"] == s["id"]
        and body["p_digest"] == definition_identity(s["definition"])["sha256"]
    )
    assert body["p_screen"] == semantic_definition(s["definition"])
    assert s == original and body["p_records"][0]["snapshot"] == original


def test_tampered_identity_never_reaches_alias_rpc(monkeypatch):
    monkeypatch.setenv("CAPTURE_DEFINITION_ALIASES_ENABLED", "1")
    s = snapshot()
    s["definition_identity"]["sha256"] = "0" * 64
    db = CaptureCalls()
    with pytest.raises(ValueError):
        append_capture_batch(db, "raw-key", [], s)
    assert db.calls == []


def test_actual_capture_writer_uses_alias_transaction_and_keeps_raw_key(monkeypatch):
    monkeypatch.setenv("CAPTURE_DEFINITION_ALIASES_ENABLED", "1")
    monkeypatch.setenv("DEFAULT_USER_ID", "alias-test-owner")
    store = FakeDb()
    monkeypatch.setattr(main, "db", store)
    calls = []
    raw = store._call

    def transaction(method, path, body=None, **kwargs):
        calls.append((method, path, deepcopy(body)))
        assert path == "rpc/screen_capture_append_with_alias"
        # Native SQL test proves transactionality; this checks actual route wiring.
        assert body["p_screen"] == semantic_definition(
            body["p_records"][-1]["snapshot"]["definition"]
        )
        return raw(method, "rpc/screen_capture_append", body=body, **kwargs)

    store._call = transaction
    stamp = datetime.now(timezone.utc).isoformat()
    spec = main.ScreenDefinition(
        filters=[{"field": "price", "min": None, "max": 10, "_label": "Price"}]
    )
    rows = [
        {
            "code": "US.A",
            "symbol": "A",
            "stock_type": "STOCK",
            "price": 2,
            "quote_identity_status": "verified",
            "quote_cache_at": stamp,
        }
    ]
    monkeypatch.setattr(
        main,
        "screener",
        lambda **kwargs: {
            "available": True,
            "universe_loaded": True,
            "universe_as_of": stamp,
            "rows": rows,
            "matched": 1,
        },
    )
    request = uuid4()
    result = main.capture_screen_snapshot(spec, request_id=request)
    assert result["captured"] and result["id"] == str(request)
    assert calls[0][2]["p_key"] == main._snapshot_key(spec)
    stored = store.tables["screen_captures"][0]["snapshot"]
    assert stored["definition"]["filters"] == spec.filters
    assert stored["definition_identity"] == definition_identity(stored["definition"])
    retry = main.capture_screen_snapshot(spec, request_id=request)
    assert retry["idempotent"] and len(calls) == 1 and len(store.tables["screen_captures"]) == 1
