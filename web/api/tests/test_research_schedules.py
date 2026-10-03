"""Authenticated schedule configuration; automation remains unavailable until wired."""

import copy

import pytest
from test_research_lists import OTHER, SID, client as client, headers
from tradingagents_api import main, research_auth as auth, research_schedules as schedules


class Store:
    def __init__(self):
        self.rows = []
        self.calls = []

    def _call(self, method, path, body=None, query=None):
        self.calls.append((method, path, copy.deepcopy(body), query))
        if method == "GET":
            rows = [
                r
                for r in self.rows
                if all(
                    not str(v).startswith("eq.") or str(r.get(k)) == v[3:] for k, v in query.items()
                )
            ]
            return copy.deepcopy(
                rows[
                    int(query.get("offset", 0)) : int(query.get("offset", 0)) + int(query["limit"])
                ]
            )
        row = next(
            (
                r
                for r in self.rows
                if r["owner_id"] == body["p_owner"] and r["definition_hash"] == body["p_hash"]
            ),
            None,
        )
        if (body["p_revision"] == 0 and row) or (
            body["p_revision"]
            and (
                not row
                or row["revision"] != body["p_revision"]
                or row["definition"] != body["p_definition"]
            )
        ):
            return []
        if not row:
            row = {
                "id": SID,
                "owner_id": body["p_owner"],
                "definition_hash": body["p_hash"],
                "definition": body["p_definition"],
            }
            self.rows.append(row)
        row.update(
            name=body["p_name"],
            cadence=body["p_cadence"],
            enabled=body["p_enabled"],
            revision=body["p_revision"] + 1,
            next_due_at=body["p_next"],
        )
        return copy.deepcopy([row])


@pytest.fixture
def setup(client, monkeypatch):
    c, _ = client
    store = Store()
    monkeypatch.setattr(schedules, "db", store)
    return c, store


def payload():
    return {
        "definition": {"market": "US"},
        "name": " Quality ",
        "cadence": {"timezone": "America/New_York", "hour": 16, "minute": 15, "weekdays": [4, 0]},
    }


URL = "/api/research/capture-schedules"


def test_create_conflict_revision_edit_and_disable(setup):
    c, store = setup
    r = c.post(URL, headers=headers(), json=payload())
    assert r.status_code == 200
    row = r.json()["schedule"]
    assert (
        row["name"] == "Quality" and row["cadence"]["weekdays"] == [0, 4] and row["revision"] == 1
    )
    assert r.json()["runtime_available"] is False and row["next_due_at"] is None
    assert c.post(URL, headers=headers(), json=payload()).status_code == 409
    assert (
        c.patch(URL + "/" + SID, headers=headers(), json={"revision": 1, "name": "Updated"}).json()[
            "schedule"
        ]["revision"]
        == 2
    )
    assert (
        c.patch(
            URL + "/" + SID, headers=headers(), json={"revision": 1, "name": "Stale"}
        ).status_code
        == 409
    )
    assert store.rows[0]["name"] == "Updated"
    assert (
        c.patch(
            URL + "/" + SID, headers=headers(), json={"revision": 2, "enabled": False}
        ).status_code
        == 200
    )


def test_auth_and_ownership(setup, monkeypatch):
    c, store = setup
    assert c.get(URL).status_code == 401 and not store.calls
    assert c.post(URL, headers=headers(), json=payload()).status_code == 200
    monkeypatch.setattr(auth, "_auth_user", lambda t: {"id": OTHER, "is_anonymous": False})
    assert c.get(URL, headers=headers(OTHER)).json()["schedules"] == []
    assert (
        c.patch(
            URL + "/" + SID, headers=headers(OTHER), json={"revision": 1, "name": "Stolen"}
        ).status_code
        == 404
    )
    monkeypatch.setattr(auth, "_session_active", lambda *args: False)
    assert c.get(URL, headers=headers(OTHER)).status_code == 401
    assert store.rows[0]["name"] == "Quality"


def test_enable_is_explicitly_gated_without_storage_write(setup):
    c, store = setup
    p = payload()
    p["enabled"] = True
    assert c.post(URL, headers=headers(), json=p).status_code == 409 and not store.calls


@pytest.mark.parametrize(
    "edit",
    [
        {"hour": True},
        {"minute": 60},
        {"weekdays": [0, 0]},
        {"weekdays": [True]},
        {"timezone": "Unknown/Zone"},
    ],
)
def test_invalid_cadence_rejected(setup, edit):
    c, store = setup
    p = payload()
    p["cadence"].update(edit)
    assert c.post(URL, headers=headers(), json=p).status_code == 422 and not store.calls


@pytest.mark.parametrize(
    "definition",
    [
        {"owner_id": OTHER},
        {"watchlist_only": True},
        {"preset": "missing"},
        {"etfs": "false"},
        {"filters": [{"field": ""}]},
    ],
)
def test_invalid_or_shared_definition_rejected(setup, definition):
    c, store = setup
    p = payload()
    p["definition"] = definition
    assert c.post(URL, headers=headers(), json=p).status_code == 422 and not store.calls


def test_original_preset_snapshot_and_equivalent_definition_lookup(setup):
    c, store = setup
    p = payload()
    preset = main.PRESET_SCREENERS[0]
    p["definition"]["preset"] = preset["key"]
    r = c.post(URL, headers=headers(), json=p)
    assert r.status_code == 200
    row = r.json()["schedule"]
    assert row["definition"]["preset_definition"] == preset
    assert row["definition"]["screen"]["filters"] == preset["filters"]
    import json

    assert (
        len(
            c.get(
                URL, headers=headers(), params={"definition": json.dumps(p["definition"])}
            ).json()["schedules"]
        )
        == 1
    )
    assert c.get(URL, headers=headers(), params={"definition": "invalid"}).status_code == 422


def test_storage_failure_bad_scope_and_malformed_configuration_fail_closed(setup, monkeypatch):
    c, store = setup
    c.post(URL, headers=headers(), json=payload())
    store.rows[0]["cadence"] = {"timezone": "Invalid"}
    assert (
        c.patch(
            URL + "/" + SID, headers=headers(), json={"revision": 1, "name": "Keep"}
        ).status_code
        == 503
    )
    store.rows[0]["owner_id"] = OTHER
    monkeypatch.setattr(store, "_call", lambda *args, **kwargs: copy.deepcopy(store.rows))
    response = c.get(URL, headers=headers())
    assert response.status_code == 503 and OTHER not in response.text
    monkeypatch.setattr(store, "_call", lambda *args, **kwargs: {"private": "secret"})
    assert c.get(URL, headers=headers()).status_code == 503


def test_paging_and_corrupt_save_confirmation(setup, monkeypatch):
    c, store = setup
    c.post(URL, headers=headers(), json=payload())
    store.rows.append(
        {**copy.deepcopy(store.rows[0]), "id": "00000000-0000-4000-8000-000000000005"}
    )
    first = c.get(URL, headers=headers(), params={"limit": 1}).json()
    assert first["has_more"] and len(first["schedules"]) == 1
    second = c.get(URL, headers=headers(), params={"limit": 1, "offset": 1}).json()
    assert not second["has_more"] and second["schedules"][0]["id"] != first["schedules"][0]["id"]
    original = store._call

    def corrupted(method, path, **kwargs):
        rows = original(method, path, **kwargs)
        if method == "POST" and rows:
            rows[0]["revision"] = 999
        return rows

    monkeypatch.setattr(store, "_call", corrupted)
    r = c.patch(URL + "/" + SID, headers=headers(), json={"revision": 1, "name": "Changed"})
    assert r.status_code == 503 and "Reload before retrying" in r.text


@pytest.mark.parametrize(
    "body",
    [
        {"revision": 1},
        {"revision": True, "name": "Wrong"},
        {"revision": 1, "name": None},
        {"revision": 1, "owner_id": OTHER},
        {"revision": 1, "name": "\nBad"},
    ],
)
def test_invalid_edits_never_reach_storage(setup, body):
    c, store = setup
    assert (
        c.patch(URL + "/" + SID, headers=headers(), json=body).status_code == 422
        and not store.calls
    )


def test_scheduled_builder_preserves_definition_and_never_silently_adopts_preset_changes(
    monkeypatch,
):
    from uuid import uuid4

    from fastapi import HTTPException

    definition, digest = schedules._definition(
        {"market": "US", "preset": main.PRESET_SCREENERS[0]["key"]}
    )
    cid = uuid4()
    calls = []

    def builder(spec, identity):
        calls.append((spec, identity))
        return {"id": str(identity), "definition": spec.model_dump(), "complete": True}

    monkeypatch.setattr(main, "build_screen_capture", builder)
    assert schedules.build_schedule_capture(definition, digest, cid)["id"] == str(cid)
    assert calls[0][0].filters == main.PRESET_SCREENERS[0]["filters"]
    changed = copy.deepcopy(main.PRESET_SCREENERS)
    changed[0]["filters"][0]["min"] = 123456
    monkeypatch.setattr(main, "PRESET_SCREENERS", changed)
    with pytest.raises(HTTPException) as exc:
        schedules.build_schedule_capture(definition, digest, cid)
    assert exc.value.status_code == 409 and len(calls) == 1


@pytest.mark.parametrize("change", ["hash", "version", "boolean_version", "extra", "criteria"])
def test_scheduled_builder_rejects_tampered_definition_before_capture(monkeypatch, change):
    from uuid import uuid4

    from fastapi import HTTPException

    definition, digest = schedules._definition({"market": "US"})
    if change == "hash":
        digest = "f" * 64
    elif change == "version":
        definition["schema_version"] = 2
    elif change == "boolean_version":
        definition["schema_version"] = True
    elif change == "extra":
        definition["owner_id"] = OTHER
    else:
        definition["screen"]["filters"] = [{"field": "price", "min": 5}]

    def forbidden(*args):
        pytest.fail("Tampered definition reached capture builder")

    monkeypatch.setattr(main, "build_screen_capture", forbidden)
    with pytest.raises(HTTPException) as exc:
        schedules.build_schedule_capture(definition, digest, uuid4())
    assert exc.value.status_code == 409


def test_schedule_routes_remain_reachable_with_production_static_mount(tmp_path):
    import os
    import subprocess
    import sys

    script = """from fastapi.testclient import TestClient
from tradingagents_api.main import app
with TestClient(app) as client:
    response=client.get('/api/research/capture-schedules')
    assert response.status_code==401,(response.status_code,response.text)
    assert response.headers['cache-control']=='private, no-store'
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env={**os.environ, "PORTAL_STATIC_DIR": str(tmp_path)},
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
