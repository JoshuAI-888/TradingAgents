import json
from copy import deepcopy

from test_capture_alias_routes import OWNER, aliases as aliases
from tradingagents_api import main


def setup_discovery(aliases, monkeypatch):
    client, spec, original, captures, store = aliases
    selected = main._snapshot_key(spec)
    getter = main.alias_capture_get

    def choose(db, key, definition, cid):
        result = getter(db, key, definition, cid)
        if result:
            result.update(history_key=selected, copies=2)
        return result

    monkeypatch.setattr(main, "alias_capture_get", choose)
    monkeypatch.setenv("CROSS_HISTORY_PAIR_REVIEWS_ENABLED", "1")
    monkeypatch.setenv("DUPLICATE_CAPTURE_REVIEW_SCOPES_ENABLED", "1")
    old_call = store._call

    def call(method, path, query=None, body=None):
        if path == "rpc/research_duplicate_pair_review_scopes":
            rows = []
            for row in store.rows:
                if (
                    row["owner_id"] != body["p_owner"]
                    or row["previous_id"] != body["p_previous"]
                    or row["current_id"] != body["p_current"]
                ):
                    continue
                copy = deepcopy(row)
                key = copy.pop("history_key")
                copy.update(
                    previous_history_key=key,
                    current_history_key=key,
                    review_contract="same_history",
                    updated_at="2026-10-02T00:00:00Z",
                )
                rows.append(copy)
            return {
                "alias_qualified": True,
                "reviews": sorted(
                    rows,
                    key=lambda r: (r["code"], r["previous_history_key"], r["current_history_key"]),
                ),
            }
        return old_call(method, path, query=query, body=body)

    monkeypatch.setattr(store, "_call", call)
    pair = {
        "definition": spec.model_dump(),
        "previous_id": captures[0]["id"],
        "current_id": captures[1]["id"],
    }
    return client, pair, original, selected, store


def seed(store, pair, key, note, revision=1):
    store.rows.append(
        {
            "owner_id": OWNER,
            "history_key": key,
            "previous_id": pair["previous_id"],
            "current_id": pair["current_id"],
            "code": "US.A",
            "note": note,
            "revision": revision,
            "review_status": "reviewed",
        }
    )


def test_unique_note_representative_change_preserves_original_anchor_and_cas(aliases, monkeypatch):
    client, pair, original, selected, store = setup_discovery(aliases, monkeypatch)
    seed(store, pair, original, "Original scope", 2)
    params = {**pair, "definition": json.dumps(pair["definition"])}
    data = client.get("/api/research/pair-reviews", params=params).json()
    review = next(r for r in data["rows"] if r["code"] == "US.A")["review"]
    assert (
        data["previous_history_key"] == selected
        and review["review_anchor"]["previous_history_key"] == original
    )
    assert review["note"] == "Original scope" and review["revision"] == 2
    body = {
        **pair,
        "code": "US.A",
        "revision": 2,
        "note": "Retained original anchor",
        "review_status": "in_review",
        "review_anchor": review["review_anchor"],
    }
    response = client.patch("/api/research/pair-reviews", json=body)
    assert response.status_code == 200, response.text
    assert (
        len(store.rows) == 1
        and store.rows[0]["history_key"] == original
        and store.rows[0]["revision"] == 3
    )
    assert client.patch("/api/research/pair-reviews", json=body).status_code == 409
    updated = client.get("/api/research/pair-reviews", params=params).json()
    assert updated["review_revision_hash"] != data["review_revision_hash"]


def test_multiple_notes_are_explicit_and_only_selected_anchor_changes(aliases, monkeypatch):
    client, pair, original, selected, store = setup_discovery(aliases, monkeypatch)
    seed(store, pair, original, "First original", 2)
    seed(store, pair, selected, "Second original", 4)
    params = {**pair, "definition": json.dumps(pair["definition"])}
    data = client.get("/api/research/pair-reviews", params=params).json()
    review = next(r for r in data["rows"] if r["code"] == "US.A")["review"]
    assert (
        data["review_scope_conflicts"] == 1
        and review["scope_conflict"]
        and review["review_status"] == "scope_conflict"
    )
    assert {v["note"] for v in review["review_variants"]} == {"First original", "Second original"}
    assert (
        client.get(
            "/api/research/pair-reviews", params={**params, "review_status": "scope_conflict"}
        ).json()["matched"]
        == 1
    )
    assert (
        client.get(
            "/api/research/pair-reviews", params={**params, "review_status": "reviewed"}
        ).json()["matched"]
        == 0
    )
    body = {
        **pair,
        "code": "US.A",
        "revision": 4,
        "note": "Selected original edited",
        "review_status": "in_review",
    }
    assert client.patch("/api/research/pair-reviews", json=body).status_code == 409
    wanted = {"previous_history_key": selected, "current_history_key": selected}
    response = client.patch("/api/research/pair-reviews", json={**body, "review_anchor": wanted})
    assert response.status_code == 200, response.text
    assert next(r for r in store.rows if r["history_key"] == original)["note"] == "First original"
    assert next(r for r in store.rows if r["history_key"] == selected)["revision"] == 5
    assert len(store.rows) == 2


def test_forged_anchor_and_unavailable_discovery_fail_without_writes(aliases, monkeypatch):
    client, pair, original, selected, store = setup_discovery(aliases, monkeypatch)
    seed(store, pair, original, "Keep note", 2)
    bad = selected[:-64] + "f" * 64
    body = {
        **pair,
        "code": "US.A",
        "revision": 2,
        "note": "Forbidden",
        "review_status": "reviewed",
        "review_anchor": {"previous_history_key": bad, "current_history_key": bad},
    }
    assert client.patch("/api/research/pair-reviews", json=body).status_code == 409
    previous = deepcopy(store.rows)
    old_call = store._call

    def unavailable(method, path, **kw):
        if path == "rpc/research_duplicate_pair_review_scopes":
            raise RuntimeError("storage unavailable")
        return old_call(method, path, **kw)

    monkeypatch.setattr(store, "_call", unavailable)
    params = {**pair, "definition": json.dumps(pair["definition"])}
    assert client.get("/api/research/pair-reviews", params=params).status_code == 503
    assert store.rows == previous


def test_unique_cross_anchor_routes_save_to_both_original_keys(aliases, monkeypatch):
    client, pair, original, selected, store = setup_discovery(aliases, monkeypatch)
    cross = {
        "owner_id": OWNER,
        "previous_history_key": original,
        "current_history_key": selected,
        "previous_id": pair["previous_id"],
        "current_id": pair["current_id"],
        "code": "US.A",
        "note": "Cross original",
        "revision": 3,
        "review_status": "in_review",
        "updated_at": "2026-10-02T00:00:00Z",
        "review_contract": "cross_history",
    }
    previous_call = store._call

    def call(method, path, query=None, body=None):
        if path == "rpc/research_duplicate_pair_review_scopes":
            return {"alias_qualified": True, "reviews": [deepcopy(cross)]}
        if path == "rpc/research_cross_history_pair_review_save":
            assert (
                body["p_previous_key"] == original
                and body["p_current_key"] == selected
                and body["p_owner"] == OWNER
            )
            if body["p_revision"] != cross["revision"]:
                return []
            cross.update(
                note=body["p_note"], review_status=body["p_status"], revision=cross["revision"] + 1
            )
            return [deepcopy(cross)]
        return previous_call(method, path, query=query, body=body)

    monkeypatch.setattr(store, "_call", call)
    params = {**pair, "definition": json.dumps(pair["definition"])}
    data = client.get("/api/research/pair-reviews", params=params).json()
    review = next(r for r in data["rows"] if r["code"] == "US.A")["review"]
    assert review["review_anchor"] == {
        "previous_history_key": original,
        "current_history_key": selected,
    }
    response = client.patch(
        "/api/research/pair-reviews",
        json={
            **pair,
            "code": "US.A",
            "revision": 3,
            "note": "Cross retained",
            "review_status": "reviewed",
            "review_anchor": review["review_anchor"],
        },
    )
    assert response.status_code == 200, response.text
    assert cross["revision"] == 4 and cross["note"] == "Cross retained" and store.rows == []
