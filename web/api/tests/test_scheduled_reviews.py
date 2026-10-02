import copy
import hashlib
import json

import pytest
from test_private_capture_history import history as history
from test_research_lists import OTHER, SID, client as client, headers
from test_research_schedules import URL, setup as setup
from tradingagents_api import research_auth as auth


@pytest.fixture
def reviewed(history, monkeypatch):
    c, store, parent, records = history
    reviews = []
    original = store._call
    calls = []

    def call(method, path, body=None, query=None):
        if path == "rpc/research_scheduled_pair_review_save":
            calls.append(body)
            match = next(
                (
                    r
                    for r in reviews
                    if all(
                        r[k] == body[v]
                        for k, v in [
                            ("owner_id", "p_owner"),
                            ("schedule_id", "p_schedule"),
                            ("previous_id", "p_previous"),
                            ("current_id", "p_current"),
                            ("code", "p_code"),
                        ]
                    )
                ),
                None,
            )
            if (
                match
                and match["revision"] != body["p_revision"]
                or not match
                and body["p_revision"] != 0
            ):
                return []
            if match is None:
                match = {
                    k: body[v]
                    for k, v in [
                        ("owner_id", "p_owner"),
                        ("schedule_id", "p_schedule"),
                        ("previous_id", "p_previous"),
                        ("current_id", "p_current"),
                        ("code", "p_code"),
                    ]
                }
                reviews.append(match)
            match.update(
                revision=body["p_revision"] + 1, note=body["p_note"], review_status=body["p_status"]
            )
            return [copy.deepcopy(match)]
        if path == "rpc/research_scheduled_pair_review_read":
            calls.append(body)
            rows = [
                r
                for r in reviews
                if r["owner_id"] == body["p_owner"]
                and r["schedule_id"] == body["p_schedule"]
                and r["previous_id"] == body["p_previous"]
                and r["current_id"] == body["p_current"]
            ]
            rows.sort(key=lambda r: r["code"])
            meta = [{k: r[k] for k in ("code", "revision", "review_status")} for r in rows]
            h = hashlib.sha256(json.dumps(meta, sort_keys=True).encode()).hexdigest()
            expected = body["p_expected_hash"]
            confirmed = expected is None or expected == h
            return {
                "confirmed": confirmed,
                "revision_hash": h,
                "reviews": meta if expected is None else [],
                "notes": [
                    {k: r[k] for k in ("code", "revision", "review_status", "note")}
                    for r in rows
                    if r["code"] in body["p_codes"]
                ]
                if confirmed
                else [],
            }
        return original(method, path, body=body, query=query)

    monkeypatch.setattr(store, "_call", call)
    return c, store, records, reviews, calls


def request(records, revision=0, note="Review cash conversion"):
    return {
        "previous_id": records[0]["id"],
        "current_id": records[1]["id"],
        "code": "US.A",
        "revision": revision,
        "note": note,
        "review_status": "reviewed",
    }


def test_save_cas_review_filter_and_visible_note_state(reviewed):
    c, store, records, rows, calls = reviewed
    url = URL + "/" + SID + "/pair-reviews"
    body = request(records)
    assert c.patch(url, headers=headers(), json=body).json()["review"]["revision"] == 1
    assert c.patch(url, headers=headers(), json=body).status_code == 409
    assert (
        c.patch(url, headers=headers(), json=request(records, 1, "Updated draft")).json()["review"][
            "revision"
        ]
        == 2
    )
    params = {k: body[k] for k in ("previous_id", "current_id")}
    result = c.get(url, headers=headers(), params={**params, "review_status": "reviewed"})
    assert result.status_code == 200, result.text
    data = result.json()
    assert (
        data["rows"][0]["review"]["note"] == "Updated draft"
        and data["review_scope"] == "private_schedule_pair"
        and len(data["review_revision_hash"]) == 64
    )
    assert (
        calls[-1]["p_codes"] == ["US.A"]
        and calls[-1]["p_expected_hash"] == data["review_revision_hash"]
    )
    assert (
        c.get(url, headers=headers(), params={**params, "review_status": "unreviewed"}).json()[
            "matched"
        ]
        == 0
    )
    assert rows[0]["note"] == "Updated draft"


def test_other_owner_absent_member_and_invalid_revision_preserve_notes(reviewed, monkeypatch):
    c, store, records, rows, calls = reviewed
    url = URL + "/" + SID + "/pair-reviews"
    body = request(records)
    assert (
        c.patch(url, headers=headers(), json={**body, "code": "US.MISSING"}).status_code == 404
        and not rows
    )
    assert c.patch(url, headers=headers(), json={**body, "revision": True}).status_code == 422
    assert c.patch(url, headers=headers(), json={**body, "owner_id": OTHER}).status_code == 422
    assert c.patch(url, headers=headers(), json=body).status_code == 200
    monkeypatch.setattr(auth, "_auth_user", lambda t: {"id": OTHER, "is_anonymous": False})
    assert (
        c.patch(url, headers=headers(OTHER), json=request(records, 1, "Stolen")).status_code == 404
    )
    assert (
        c.get(
            url, headers=headers(OTHER), params={k: body[k] for k in ("previous_id", "current_id")}
        ).status_code
        == 404
    )
    assert rows[0]["note"] == "Review cash conversion"


def test_changed_note_fingerprint_returns_conflict_instead_of_mixed_page(reviewed, monkeypatch):
    c, store, records, rows, calls = reviewed
    url = URL + "/" + SID + "/pair-reviews"
    body = request(records)
    c.patch(url, headers=headers(), json=body)
    original = store._call

    def raced(method, path, body=None, query=None):
        if (
            path == "rpc/research_scheduled_pair_review_read"
            and body["p_expected_hash"] is not None
        ):
            rows[0]["revision"] += 1
            rows[0]["note"] = "Concurrent"
        return original(method, path, body=body, query=query)

    monkeypatch.setattr(store, "_call", raced)
    response = c.get(
        url, headers=headers(), params={k: body[k] for k in ("previous_id", "current_id")}
    )
    assert response.status_code == 409 and "Keep your draft" in response.text


def test_unreviewed_default_has_empty_note_and_missing_auth(reviewed):
    c, store, records, rows, calls = reviewed
    url = URL + "/" + SID + "/pair-reviews"
    body = request(records)
    params = {k: body[k] for k in ("previous_id", "current_id")}
    assert c.get(url, params=params).status_code == 401
    data = c.get(url, headers=headers(), params=params).json()
    assert data["rows"][0]["review"] == {
        "code": "US.A",
        "revision": 0,
        "note": "",
        "review_status": "unreviewed",
    }


@pytest.mark.parametrize("damage", ["confirmed", "hash", "status", "revision", "duplicate"])
def test_malformed_review_state_returns_safe_error(reviewed, monkeypatch, damage):
    c, store, records, rows, calls = reviewed
    url = URL + "/" + SID + "/pair-reviews"
    body = request(records)
    c.patch(url, headers=headers(), json=body)
    original = store._call

    def broken(method, path, body=None, query=None):
        result = original(method, path, body=body, query=query)
        if path == "rpc/research_scheduled_pair_review_read" and body["p_expected_hash"] is None:
            if damage == "confirmed":
                result["confirmed"] = 1
            elif damage == "hash":
                result["revision_hash"] = "bad"
            elif damage == "status":
                result["reviews"][0]["review_status"] = {}
            elif damage == "revision":
                result["reviews"][0]["revision"] = True
            else:
                result["reviews"].append(copy.deepcopy(result["reviews"][0]))
        return result

    monkeypatch.setattr(store, "_call", broken)
    response = c.get(
        url, headers=headers(), params={k: body[k] for k in ("previous_id", "current_id")}
    )
    assert response.status_code == 503


def test_next_unreviewed_respects_pair_filter(reviewed):
    c, store, records, rows, calls = reviewed
    url = URL + "/" + SID + "/pair-reviews"
    body = request(records)
    params = {k: body[k] for k in ("previous_id", "current_id")}
    data = c.get(
        url,
        headers=headers(),
        params={**params, "next_review": True, "review_status": "unreviewed"},
    ).json()
    assert data["next_review_code"] == "US.A"
    c.patch(url, headers=headers(), json=body)
    data = c.get(
        url,
        headers=headers(),
        params={**params, "next_review": True, "review_status": "unreviewed"},
    ).json()
    assert data["rows"] == [] and data["next_review_code"] is None


def test_exact_code_reload_finds_review_and_rejects_invalid_identity(reviewed, monkeypatch):
    from datetime import datetime, timezone

    from tradingagents_api import capture_service, main

    c, store, records, rows, calls = reviewed
    # Build two real comparison rows; A is beyond the first page in descending order.
    for record in records:
        stamp = datetime.now(timezone.utc).isoformat()
        cohort = [
            {
                "code": code,
                "symbol": code[3:],
                "stock_type": "STOCK",
                "price": 4,
                "quote_identity_status": "verified",
                "quote_cache_at": stamp,
            }
            for code in ("US.A", "US.B")
        ]
        monkeypatch.setattr(
            main,
            "screener",
            lambda cohort=cohort, stamp=stamp, **kw: {
                "available": True,
                "universe_loaded": True,
                "universe_as_of": stamp,
                "matched": 2,
                "rows": cohort,
            },
        )
        snapshot = capture_service.build(store.rows[0], record["id"])
        record.update(snapshot=snapshot, published_at=snapshot["at"])
    url = URL + "/" + SID + "/pair-reviews"
    body = request(records)
    assert c.patch(url, headers=headers(), json=body).status_code == 200
    params = {k: body[k] for k in ("previous_id", "current_id")}
    assert (
        c.get(
            url, headers=headers(), params={**params, "status": "all", "direction": 2, "limit": 1}
        ).json()["rows"][0]["code"]
        == "US.B"
    )
    result = c.get(
        url,
        headers=headers(),
        params={**params, "status": "all", "code": "US.A", "offset": 0, "limit": 1},
    )
    assert result.status_code == 200, result.text
    assert result.json()["rows"][0]["review"]["note"] == body["note"]
    assert (
        c.get(url, headers=headers(), params={**params, "code": "US.MISSING"}).json()["rows"] == []
    )
    assert c.get(url, headers=headers(), params={**params, "code": "A"}).status_code == 422
