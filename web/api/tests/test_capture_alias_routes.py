import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_api import FakeDb
from test_research_reviews import PairStore
from tradingagents_api import main, research_auth, research_reviews

OWNER = "00000000-0000-4000-8000-000000000001"


@pytest.fixture
def aliases(monkeypatch):
    monkeypatch.setenv("DEFAULT_USER_ID", "alias-route-owner")
    monkeypatch.setenv("CAPTURE_DEFINITION_ALIASES_ENABLED", "1")
    monkeypatch.setattr(main, "db", FakeDb())
    notes = PairStore()
    monkeypatch.setattr(research_reviews, "db", notes)
    minimal = main.ScreenDefinition(filters=[{"field": "price", "max": 10}])
    decorated = main.ScreenDefinition(
        filters=[{"field": "price", "max": 10, "min": None, "_label": "Price"}]
    )
    key = main._snapshot_key(minimal)
    captures = []
    for hours, prices in ((2, [12, 6]), (0, [8, 14])):
        stamp = datetime.now(timezone.utc) - timedelta(hours=hours)
        rows = []
        for code, price in zip(("US.A", "US.B"), prices, strict=False):
            rows.append(
                {
                    "code": code,
                    "symbol": code[3:],
                    "stock_type": "STOCK",
                    "price": price,
                    "quote_identity_status": "verified",
                    "quote_cache_at": stamp.isoformat(),
                    "field_evidence": {
                        "c0": {
                            "criterion": minimal.filters[0],
                            "value": price,
                            "unit": "currency",
                            "currency": "USD",
                            "period": "point_in_time",
                            "source": "synthetic",
                            "clock": "quote_source",
                            "observed_at": (stamp - timedelta(minutes=1)).isoformat(),
                        }
                    },
                }
            )
        monkeypatch.setattr(
            main,
            "screener",
            lambda rows=rows, stamp=stamp, **kw: {
                "available": True,
                "universe_loaded": True,
                "universe_as_of": stamp.isoformat(),
                "rows": rows,
                "matched": 2,
            },
        )
        captures.append(main.build_screen_capture(minimal, uuid4()))
    metadata = [{**main._snapshot_meta(c), "history_key": key, "copies": 1} for c in captures]
    monkeypatch.setattr(
        main,
        "alias_history_page",
        lambda db, k, d, limit=100, offset=0: (
            deepcopy(metadata[-limit:]) if not offset else [],
            False,
        ),
    )
    monkeypatch.setattr(
        main,
        "alias_capture_get",
        lambda db, k, d, cid: next(
            (
                {
                    "history_key": key,
                    "id": cid,
                    "snapshot": deepcopy(c),
                    "copies": 1,
                    "conflicting": False,
                }
                for c in captures
                if c["id"] == cid
            ),
            None,
        ),
    )
    original_override = main.app.dependency_overrides.get(research_auth.require_research_owner)
    main.app.dependency_overrides[research_auth.require_research_owner] = lambda: (
        research_auth.ResearchOwner(OWNER)
    )
    yield TestClient(main.app), decorated, key, captures, notes
    if original_override is None:
        main.app.dependency_overrides.pop(research_auth.require_research_owner, None)
    else:
        main.app.dependency_overrides[research_auth.require_research_owner] = original_override


def test_ui_equivalent_definition_discovers_and_compares_original_captures(aliases):
    client, spec, key, captures, notes = aliases
    history = client.get(
        "/api/screener/snapshot-history", params={"definition": spec.model_dump_json()}
    )
    assert history.status_code == 200 and {r["id"] for r in history.json()["snapshots"]} == {
        c["id"] for c in captures
    }
    response = client.get(
        "/api/screener/changes",
        params={"definition": spec.model_dump_json(), "sort": "criterion:after:price"},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["comparable"] and result["counts"]["new"] == 1 and result["counts"]["exited"] == 1
    assert result["review_history_key"] == key != main._snapshot_key(spec)
    for side, capture in zip(("previous", "current"), captures, strict=False):
        assert result[side + "_definition"] == capture["definition"]
        assert result[side + "_definition_identity"] == capture["definition_identity"]
        assert result[side + "_history_key"] == key
    assert (
        result["rows"][0]["code"] == "US.A"
        and result["rows"][0]["evidence"][0]["status"] == "comparable"
    )
    assert (
        "_label" not in result["rows"][0]["previous"]["criterion_observations"]["c0"]["criterion"]
    )


def test_existing_private_notes_save_and_reload_under_original_common_key(aliases):
    client, spec, key, captures, notes = aliases
    pair = {
        "definition": spec.model_dump(),
        "previous_id": captures[0]["id"],
        "current_id": captures[1]["id"],
    }
    body = {
        **pair,
        "code": "US.A",
        "revision": 0,
        "note": "Original pair scope retained",
        "review_status": "reviewed",
    }
    saved = client.patch("/api/research/pair-reviews", json=body)
    assert saved.status_code == 200, saved.text
    assert notes.rows[0]["history_key"] == key
    result = client.get(
        "/api/research/pair-reviews", params={**pair, "definition": json.dumps(pair["definition"])}
    ).json()
    assert result["review_scope"] == "private_capture_pair" and result["review_history_key"] == key
    assert next(r for r in result["rows"] if r["code"] == "US.A")["review"]["note"] == body["note"]
    assert len(notes.rows) == 1


def test_cross_history_comparison_never_reassigns_existing_review_notes(aliases, monkeypatch):
    client, spec, key, captures, notes = aliases
    original = main.alias_capture_get

    def cross(db, k, d, cid):
        row = original(db, k, d, cid)
        if row and cid == captures[1]["id"]:
            row["history_key"] = main._snapshot_key(spec)
        return row

    monkeypatch.setattr(main, "alias_capture_get", cross)
    pair = {
        "definition": spec.model_dump(),
        "previous_id": captures[0]["id"],
        "current_id": captures[1]["id"],
    }
    result = client.get(
        "/api/research/pair-reviews", params={**pair, "definition": json.dumps(pair["definition"])}
    )
    assert result.status_code == 200, result.text
    data = result.json()
    assert (
        data["comparable"]
        and data["review_scope"] == "unavailable"
        and data["review_history_key"] is None
    )
    assert "separate compatible histories" in data["review_unavailable_reason"] and not notes.calls
    saved = client.patch(
        "/api/research/pair-reviews",
        json={
            **pair,
            "code": "US.A",
            "revision": 0,
            "note": "Do not remap",
            "review_status": "reviewed",
        },
    )
    assert saved.status_code == 409 and not notes.calls


def test_discovery_conflict_and_storage_failure_do_not_infer_membership(aliases, monkeypatch):
    client, spec, key, captures, notes = aliases

    def conflict(*args, **kwargs):
        raise ValueError("divergent")

    monkeypatch.setattr(main, "alias_capture_get", conflict)
    assert (
        client.get(
            "/api/screener/changes", params={"definition": spec.model_dump_json()}
        ).status_code
        == 409
    )

    def fail(*args, **kwargs):
        raise RuntimeError("unconfirmed")

    monkeypatch.setattr(main, "alias_history_page", fail)
    assert (
        client.get(
            "/api/screener/changes", params={"definition": spec.model_dump_json()}
        ).status_code
        == 503
    )
    assert not notes.calls


def test_enabled_cross_history_review_retains_both_keys_cas_and_owner_scope(aliases, monkeypatch):
    client, spec, key, captures, notes = aliases
    original = main.alias_capture_get
    cross_key = main._snapshot_key(spec)
    monkeypatch.setenv("CROSS_HISTORY_PAIR_REVIEWS_ENABLED", "1")

    def cross(db, k, d, cid):
        row = original(db, k, d, cid)
        if row and cid == captures[1]["id"]:
            row["history_key"] = cross_key
        return row

    monkeypatch.setattr(main, "alias_capture_get", cross)
    cross_rows = []
    original_call = notes._call

    def call(method, path, query=None, body=None):
        if path not in (
            "rpc/research_cross_history_pair_review_read",
            "rpc/research_cross_history_pair_review_save",
        ):
            return original_call(method, path, query=query, body=body)
        keys = {
            k: body[v]
            for k, v in [
                ("owner_id", "p_owner"),
                ("previous_history_key", "p_previous_key"),
                ("current_history_key", "p_current_key"),
                ("previous_id", "p_previous"),
                ("current_id", "p_current"),
            ]
        }
        matching = [r for r in cross_rows if all(r[k] == v for k, v in keys.items())]
        if path.endswith("_read"):
            return {"reviews": deepcopy(matching)}
        row = next((r for r in matching if r["code"] == body["p_code"]), None)
        if row and row["revision"] != body["p_revision"] or not row and body["p_revision"] != 0:
            return []
        if row is None:
            row = {**keys, "code": body["p_code"], "revision": 0}
            cross_rows.append(row)
        row.update(
            revision=row["revision"] + 1, note=body["p_note"], review_status=body["p_status"]
        )
        return [deepcopy(row)]

    monkeypatch.setattr(notes, "_call", call)
    pair = {
        "definition": spec.model_dump(),
        "previous_id": captures[0]["id"],
        "current_id": captures[1]["id"],
    }
    body = {
        **pair,
        "code": "US.A",
        "revision": 0,
        "note": "Across original captures",
        "review_status": "reviewed",
    }
    assert (
        client.patch("/api/research/pair-reviews", json={**body, "revision": False}).status_code
        == 422
    )
    assert client.patch("/api/research/pair-reviews", json=body).status_code == 200
    assert (
        client.patch("/api/research/pair-reviews", json={**body, "note": "Stale"}).status_code
        == 409
    )
    params = {**pair, "definition": json.dumps(pair["definition"]), "review_status": "reviewed"}
    result = client.get("/api/research/pair-reviews", params=params)
    assert result.status_code == 200, result.text
    data = result.json()
    assert (
        data["review_contract"] == "cross_history"
        and data["review_scope"] == "private_capture_pair"
    )
    assert (
        data["matched"] == 1
        and data["rows"][0]["review"]["note"] == body["note"]
        and len(data["review_revision_hash"]) == 64
    )
    assert data["review_history_key"] is None and "review_unavailable_reason" not in data
    assert (
        cross_rows[0]["previous_history_key"] == key
        and cross_rows[0]["current_history_key"] == cross_key
    )
    assert not notes.rows and not notes.calls
    main.app.dependency_overrides[research_auth.require_research_owner] = lambda: (
        research_auth.ResearchOwner("00000000-0000-4000-8000-000000000002")
    )
    assert client.get("/api/research/pair-reviews", params=params).json()["matched"] == 0
