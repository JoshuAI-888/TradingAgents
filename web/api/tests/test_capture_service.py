from datetime import datetime, timezone

import pytest
from tradingagents_api import (
    capture_service as service,
    main as api,
    research_schedules as schedules,
)
from tradingagents_worker.capture_executor import PermanentCaptureError


def test_runtime_requires_explicit_infrastructure_opt_in(monkeypatch):
    monkeypatch.delenv("PRIVATE_CAPTURE_RUNTIME_ENABLED", raising=False)
    with pytest.raises(SystemExit, match="disabled"):
        service.main()


def test_actual_capture_adapter_preserves_stored_nonmember_evidence(monkeypatch):
    from uuid import uuid4

    now = datetime.now(timezone.utc).isoformat()
    definition, digest = schedules._definition(
        {"market": "US", "filters": [{"field": "price", "max": 5}]}
    )
    rows = [
        {"code": "US.A", "stock_type": "STOCK", "price": 4},
        {"code": "US.B", "stock_type": "STOCK", "price": 7},
    ]
    rows = [{**r, "quote_identity_status": "verified", "quote_cache_at": now} for r in rows]
    monkeypatch.setattr(
        api,
        "screener",
        lambda **kw: {
            "available": True,
            "universe_loaded": True,
            "universe_as_of": now,
            "rows": rows,
            "matched": 2,
        },
    )
    result = service.build({"definition": definition, "definition_hash": digest}, str(uuid4()))
    assert result["complete"] and [r["code"] for r in result["members"]] == ["US.A"]
    assert [r["code"] for r in result["observations"]] == ["US.A", "US.B"]


def test_adapter_tampering_is_permanent_before_provider(monkeypatch):
    definition, digest = schedules._definition({"market": "US"})
    definition["screen"]["market"] = "HK"

    def forbidden(*a, **kw):
        pytest.fail("Changed definition reached provider")

    monkeypatch.setattr(api, "screener", forbidden)
    with pytest.raises(PermanentCaptureError):
        service.build(
            {"definition": definition, "definition_hash": digest},
            "00000000-0000-4000-8000-000000000001",
        )


def test_dispatch_is_bounded_and_invalid_schedule_does_not_block_next(monkeypatch):
    calls = []

    class Db:
        def _call(self, method, path, query):
            assert (
                method == "GET"
                and path == "research_capture_schedules"
                and query["limit"] == "100"
                and query["enabled"] == "eq.true"
            )
            return [{"id": "bad"}, {"id": "valid"}]

    def dispatch(db, row, now):
        calls.append(row["id"])
        if row["id"] == "bad":
            raise ValueError("Private raw content")
        return {"id": "valid"}

    monkeypatch.setattr(service, "dispatch_schedule", dispatch)
    assert service.dispatch_due(Db(), datetime.now(timezone.utc)) == {
        "dispatched": 1,
        "invalid": 1,
        "fenced": 0,
    }
    assert calls == ["bad", "valid"]
