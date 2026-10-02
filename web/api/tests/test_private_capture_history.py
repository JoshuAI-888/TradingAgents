from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from test_research_lists import OTHER, OWNER, SID, client as client, headers
from test_research_schedules import URL, payload, setup as setup
from tradingagents_api import capture_service, main, research_auth as auth


@pytest.fixture
def history(setup, monkeypatch):
    c, store = setup
    r = c.post(URL, headers=headers(), json=payload())
    parent = r.json()["schedule"]
    records = []
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(
        main,
        "screener",
        lambda **kw: {
            "available": True,
            "universe_loaded": True,
            "universe_as_of": now,
            "matched": 1,
            "rows": [
                {
                    "code": "US.A",
                    "stock_type": "STOCK",
                    "price": 4,
                    "quote_identity_status": "verified",
                    "quote_cache_at": now,
                }
            ],
        },
    )
    for _ in range(2):
        cid = str(uuid4())
        snapshot = capture_service.build(parent, cid)
        records.append(
            {
                "id": cid,
                "schedule_id": SID,
                "owner_id": OWNER,
                "schedule_revision": 1,
                "definition_hash": parent["definition_hash"],
                "published_at": snapshot["at"],
                "snapshot": snapshot,
                "publish_token": "PRIVATE_TOKEN",
            }
        )
    original = store._call

    def call(method, path, body=None, query=None):
        if path != "research_private_captures":
            return original(method, path, body=body, query=query)
        store.calls.append((method, path, body, query))
        rows = [
            r
            for r in records
            if all(not str(v).startswith("eq.") or str(r.get(k)) == v[3:] for k, v in query.items())
        ]
        rows.sort(key=lambda r: (r["published_at"], r["id"]), reverse=True)
        start = int(query.get("offset", 0))
        rows = rows[start : start + int(query["limit"])]
        columns = query["select"].split(",")
        return [{k: deepcopy(row[k]) for k in columns} for row in rows]

    monkeypatch.setattr(store, "_call", call)
    return c, store, parent, records


def test_metadata_paging_and_detail_preserve_evidence_without_lease_tokens(history):
    c, store, parent, records = history
    base = URL + "/" + SID + "/captures"
    first = c.get(base, headers=headers(), params={"limit": 1})
    assert first.status_code == 200
    assert (
        first.json()["has_more"]
        and first.json()["scope"] == "authenticated_owner"
        and "snapshot" not in first.text
        and "PRIVATE_TOKEN" not in first.text
    )
    second = c.get(base, headers=headers(), params={"limit": 1, "offset": 1}).json()
    assert not second["has_more"]
    assert first.json()["captures"][0]["id"] != second["captures"][0]["id"]
    detail = c.get(base + "/" + records[0]["id"], headers=headers())
    assert detail.status_code == 200
    assert (
        detail.json()["snapshot"] == records[0]["snapshot"]
        and detail.json()["evidence_scope"] == "eligible_stored_universe"
    )
    assert (
        "PRIVATE_TOKEN" not in detail.text
        and detail.headers["cache-control"] == "private, no-store"
    )


def test_disabled_schedule_preserves_private_history(history):
    c, store, parent, records = history
    assert (
        c.patch(
            URL + "/" + SID, headers=headers(), json={"revision": 1, "enabled": False}
        ).status_code
        == 200
    )
    assert len(c.get(URL + "/" + SID + "/captures", headers=headers()).json()["captures"]) == 2


def test_auth_other_owner_and_missing_capture(history, monkeypatch):
    c, store, parent, records = history
    base = URL + "/" + SID + "/captures"
    assert c.get(base).status_code == 401
    assert c.get(base + "/" + str(uuid4()), headers=headers()).status_code == 404
    monkeypatch.setattr(auth, "_auth_user", lambda t: {"id": OTHER, "is_anonymous": False})
    assert c.get(base, headers=headers(OTHER)).status_code == 404
    assert c.get(base + "/" + records[0]["id"], headers=headers(OTHER)).status_code == 404


@pytest.mark.parametrize(
    "damage", ["definition", "members", "observations", "complete", "source_time", "source_clock"]
)
def test_invalid_persisted_capture_is_not_trusted(history, damage):
    c, store, parent, records = history
    snapshot = records[0]["snapshot"]
    if damage == "definition":
        snapshot["definition"]["market"] = "HK"
    elif damage == "members":
        snapshot["members"] = []
    elif damage == "observations":
        snapshot["eligible_count"] = 2
    elif damage == "complete":
        snapshot["complete"] = 1
    elif damage == "source_clock":
        snapshot["source_clock"] = "provider_retrieval"
    else:
        snapshot["source_at"] = "2020-01-01T00:00:00Z"
    response = c.get(URL + "/" + SID + "/captures/" + records[0]["id"], headers=headers())
    assert response.status_code == 409 and "No changes can be inferred" in response.text


def test_wrong_parent_digest_fails_before_history_read(history):
    c, store, parent, records = history
    store.rows[0]["definition_hash"] = "f" * 64
    before = len(store.calls)
    assert c.get(URL + "/" + SID + "/captures", headers=headers()).status_code == 503
    assert all(path != "research_private_captures" for _, path, _, _ in store.calls[before:])


def test_private_comparison_uses_shared_engine_without_shared_history(history, monkeypatch):
    c, store, parent, records = history

    def forbidden(*args, **kwargs):
        pytest.fail("Private comparison accessed shared history")

    for name in ("_snapshot_key", "_snapshot_history", "_snapshot_get", "_snapshot_metadata_page"):
        monkeypatch.setattr(main, name, forbidden)
    response = c.get(
        URL + "/" + SID + "/changes",
        headers=headers(),
        params={"previous_id": records[0]["id"], "current_id": records[1]["id"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["comparable"] and body["counts"] == {
        "new": 0,
        "exited": 0,
        "all": 1,
        "unchanged": 1,
    }
    assert body["scope"] == "authenticated_owner" and body["history_scope"] == "selected_pair"
    assert (
        body["observation_coverage"]["scope"] == "eligible_stored_universe"
        and "added" not in body
        and "exited" not in body
    )
    assert body["rows"][0]["code"] == "US.A" and body["review_scope"] == "unavailable"
    assert (
        len(
            [
                1
                for method, path, _, _ in store.calls
                if method == "GET" and path == "research_capture_schedules"
            ]
        )
        == 1
    )


def test_private_pair_reversed_identical_missing_and_other_owner(history, monkeypatch):
    c, store, parent, records = history
    url = URL + "/" + SID + "/changes"
    for ids, expected in [
        ((records[1]["id"], records[0]["id"]), 400),
        ((records[0]["id"], records[0]["id"]), 400),
        ((str(uuid4()), records[1]["id"]), 404),
    ]:
        assert (
            c.get(
                url,
                headers=headers(),
                params=dict(zip(("previous_id", "current_id"), ids, strict=False)),
            ).status_code
            == expected
        )
    monkeypatch.setattr(auth, "_auth_user", lambda t: {"id": OTHER, "is_anonymous": False})
    assert (
        c.get(
            url,
            headers=headers(OTHER),
            params={"previous_id": records[0]["id"], "current_id": records[1]["id"]},
        ).status_code
        == 404
    )


def test_private_pair_search_sort_and_paging(history):
    c, store, parent, records = history
    url = URL + "/" + SID + "/changes"
    params = {"previous_id": records[0]["id"], "current_id": records[1]["id"]}
    assert c.get(url, headers=headers(), params={**params, "offset": 1}).json()["rows"] == []
    assert c.get(url, headers=headers(), params={**params, "status": "new"}).json()["matched"] == 0
    assert c.get(url, headers=headers(), params={**params, "q": "missing"}).json()["matched"] == 0
    assert c.get(url, headers=headers(), params={**params, "sort": "bad"}).status_code == 400
    assert c.get(url, headers=headers(), params={**params, "limit": 501}).status_code == 422


def test_private_entries_exits_and_criterion_sort_from_actual_builder(history, monkeypatch):
    c, store, parent, records = history
    from tradingagents_api import research_schedules

    definition, digest = research_schedules._definition(
        {"market": "US", "filters": [{"field": "price", "max": 5}]}
    )
    store.rows[0].update(definition=definition, definition_hash=digest)
    for record, prices in zip(records, ([4, 7], [6, 4]), strict=False):
        stamp = datetime.now(timezone.utc).isoformat()
        rows = [
            {
                "code": code,
                "symbol": code[3:],
                "stock_type": "STOCK",
                "price": price,
                "quote_identity_status": "verified",
                "quote_cache_at": stamp,
            }
            for code, price in zip(("US.A", "US.B"), prices, strict=False)
        ]
        for row in rows:
            row["field_evidence"] = {
                "price": {
                    "criterion": definition["screen"]["filters"][0],
                    "value": row["price"],
                    "unit": "currency",
                    "currency": "USD",
                    "period": "point_in_time",
                    "source": "synthetic",
                    "clock": "quote_source",
                    "observed_at": stamp,
                }
            }
        monkeypatch.setattr(
            main,
            "screener",
            lambda rows=rows, stamp=stamp, **kw: {
                "available": True,
                "universe_loaded": True,
                "universe_as_of": stamp,
                "rows": rows,
                "matched": 2,
            },
        )
        snapshot = capture_service.build(store.rows[0], record["id"])
        record.update(snapshot=snapshot, definition_hash=digest, published_at=snapshot["at"])
        from tradingagents_api.screen_definition_identity import definition_identity

        assert snapshot["definition_identity"] == definition_identity(snapshot["definition"])
    params = {
        "previous_id": records[0]["id"],
        "current_id": records[1]["id"],
        "sort": "criterion:after:price",
        "limit": 1,
    }
    response = c.get(URL + "/" + SID + "/changes", headers=headers(), params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert (
        body["counts"] == {"new": 1, "exited": 1, "all": 2, "unchanged": 0} and body["matched"] == 2
    )
    assert body["rows"][0]["code"] == "US.B" and body["rows"][0]["status"] == "new"
    assert body["rows"][0]["previous"]["criterion_observations"]["c0"]["value"] == 7
    next_page = c.get(
        URL + "/" + SID + "/changes", headers=headers(), params={**params, "offset": 1}
    ).json()
    assert next_page["rows"][0]["code"] == "US.A" and next_page["rows"][0]["status"] == "exited"


def test_capture_status_retains_success_and_omits_worker_secrets(history, monkeypatch):
    c, store, parent, records = history
    original = store._call
    stamp = datetime.now(timezone.utc).isoformat()
    row = {
        "id": str(uuid4()),
        "owner_id": OWNER,
        "schedule_id": SID,
        "schedule_revision": 1,
        "due_at": stamp,
        "status": "running",
        "attempts": 1,
        "retry_at": stamp,
        "updated_at": stamp,
        "error_code": None,
        "lease_until": "2020-01-01T00:00:00Z",
        "lease_token": "SECRET",
        "worker_id": "SECRET",
    }

    def call(method, path, **kw):
        return (
            [deepcopy(row)]
            if path == "research_capture_occurrences"
            else original(method, path, **kw)
        )

    monkeypatch.setattr(store, "_call", call)
    response = c.get(URL + "/" + SID + "/status", headers=headers())
    assert response.status_code == 200, response.text
    data = response.json()
    assert (
        data["latest_occurrence"]["display_status"] == "awaiting_recovery"
        and data["runtime_available"] is False
    )
    assert (
        data["last_success"]["id"] == records[-1]["id"]
        and "SECRET" not in response.text
        and "lease_until" not in response.text
    )
    row.update(status="failed", error_code="incomplete_data")
    assert (
        c.get(URL + "/" + SID + "/status", headers=headers()).json()["last_success"]
        == data["last_success"]
    )
    assert c.get(URL + "/" + SID + "/status").status_code == 401
    row["owner_id"] = OTHER
    assert c.get(URL + "/" + SID + "/status", headers=headers()).status_code == 503


@pytest.mark.parametrize(
    "damage",
    [
        {"status": "unknown"},
        {"attempts": True},
        {"error_code": "raw provider failure"},
        {"schedule_revision": 2},
        {"due_at": "2026-10-03T00:00:00"},
        {"lease_until": None},
    ],
)
def test_capture_status_malformed_state_fails_closed(history, monkeypatch, damage):
    c, store, parent, records = history
    original = store._call
    stamp = datetime.now(timezone.utc).isoformat()
    row = {
        "id": str(uuid4()),
        "owner_id": OWNER,
        "schedule_id": SID,
        "schedule_revision": 1,
        "due_at": stamp,
        "status": "running",
        "attempts": 1,
        "retry_at": stamp,
        "updated_at": stamp,
        "error_code": None,
        "lease_until": stamp,
        **damage,
    }
    monkeypatch.setattr(
        store,
        "_call",
        lambda method, path, **kw: (
            [row] if path == "research_capture_occurrences" else original(method, path, **kw)
        ),
    )
    assert c.get(URL + "/" + SID + "/status", headers=headers()).status_code == 503
