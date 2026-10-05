import csv
import io
import json
import xml.etree.ElementTree as ET

import pytest
from test_private_capture_history import history as history
from test_research_lists import OTHER, SID, client as client, headers
from test_research_schedules import URL, setup as setup
from test_scheduled_reviews import request, reviewed as reviewed
from tradingagents_api import research_auth as auth, scheduled_exports


def export_body(c, records, **kwargs):
    params = {k: request(records)[k] for k in ("previous_id", "current_id")}
    state = c.get(URL + "/" + SID + "/pair-reviews", headers=headers(), params=params).json()
    return {**params, "review_revision_hash": state["review_revision_hash"], **kwargs}


def parse(response):
    return list(csv.DictReader(io.StringIO(response.content.decode("utf-8-sig"))))


def test_exact_csv_excel_membership_metadata_notes_and_cleanup(reviewed, monkeypatch, tmp_path):
    c, store, records, rows, calls = reviewed
    reviewurl = URL + "/" + SID + "/pair-reviews"
    url = URL + "/" + SID + "/pair-export"
    note = '=HYPERLINK("bad")\nReview <cash> & quality'
    assert (
        c.patch(reviewurl, headers=headers(), json=request(records, note=note)).status_code == 200
    )
    original = scheduled_exports.tempfile.NamedTemporaryFile
    monkeypatch.setattr(
        scheduled_exports.tempfile, "NamedTemporaryFile", lambda **kw: original(dir=tmp_path, **kw)
    )
    body = export_body(c, records)
    response = c.post(url, headers=headers(), json=body)
    assert response.status_code == 200, response.text
    data = parse(response)
    assert len(data) == 1 and data[0]["code"] == "US.A"
    assert data[0]["private_note"] == "'" + note and data[0]["review_revision"] == "1"
    assert (
        data[0]["review_revision_hash"] == body["review_revision_hash"]
        and data[0]["capture_scope"] == "authenticated_owner"
    )
    assert data[0]["previous_id"] == records[0]["id"] and data[0]["current_id"] == records[1]["id"]
    for side, record in zip(("previous", "current"), records, strict=False):
        assert json.loads(data[0][side + "_definition_json"]) == record["snapshot"]["definition"]
        assert (
            json.loads(data[0][side + "_definition_identity"])
            == record["snapshot"]["definition_identity"]
        )
    # Private scheduled evidence must not acquire shared manual-history identifiers.
    assert all(
        data[0][k] == ""
        for k in ("previous_history_key", "current_history_key", "review_history_key")
    )
    assert (
        data[0]["export_scope"] == "all_filtered"
        and data[0]["observation_scope"] == "eligible_stored_universe"
    )
    assert response.headers["cache-control"] == "private, no-store" and not list(tmp_path.iterdir())
    excel = c.post(url, headers=headers(), json={**body, "format": "excel"})
    assert excel.status_code == 200
    root = ET.fromstring(excel.content)
    ns = {"s": "urn:schemas-microsoft-com:office:spreadsheet"}
    xmlrows = root.findall(".//s:Row", ns)
    assert len(xmlrows) == 2
    headings = [x.text for x in xmlrows[0].findall("s:Cell/s:Data", ns)]
    cells = xmlrows[1].findall("s:Cell/s:Data", ns)
    assert (
        cells[headings.index("private_note")].text == note
        and cells[headings.index("private_note")].attrib["{" + ns["s"] + "}Type"] == "String"
    )
    assert cells[headings.index("review_revision")].attrib["{" + ns["s"] + "}Type"] == "Number"
    for side, record in zip(("previous", "current"), records, strict=False):
        assert (
            json.loads(cells[headings.index(side + "_definition_json")].text)
            == record["snapshot"]["definition"]
        )
        assert (
            json.loads(cells[headings.index(side + "_definition_identity")].text)
            == record["snapshot"]["definition_identity"]
        )
    assert not list(tmp_path.iterdir())


def test_selected_scope_and_missing_identity_rejected(reviewed):
    c, store, records, rows, calls = reviewed
    url = URL + "/" + SID + "/pair-export"
    body = export_body(c, records, scope="selected", codes=["US.A"])
    result = c.post(url, headers=headers(), json=body)
    assert result.status_code == 200 and parse(result)[0]["export_scope"] == "selected"
    assert c.post(url, headers=headers(), json={**body, "codes": ["US.MISSING"]}).status_code == 409
    assert (
        c.post(url, headers=headers(), json={**body, "codes": ["US.A", "US.A"]}).status_code == 422
    )
    assert c.post(url, headers=headers(), json={**body, "codes": []}).status_code == 422


def test_stale_view_and_notes_race_return_no_file(reviewed, monkeypatch, tmp_path):
    c, store, records, rows, calls = reviewed
    url = URL + "/" + SID + "/pair-export"
    body = export_body(c, records)
    c.patch(URL + "/" + SID + "/pair-reviews", headers=headers(), json=request(records))
    assert c.post(url, headers=headers(), json=body).status_code == 409
    body = export_body(c, records)
    original_call = store._call
    original_file = scheduled_exports.tempfile.NamedTemporaryFile
    monkeypatch.setattr(
        scheduled_exports.tempfile,
        "NamedTemporaryFile",
        lambda **kw: original_file(dir=tmp_path, **kw),
    )

    def raced(method, path, body=None, query=None):
        if (
            path == "rpc/research_scheduled_pair_review_read"
            and body["p_expected_hash"] is not None
        ):
            rows[0]["revision"] += 1
        return original_call(method, path, body=body, query=query)

    monkeypatch.setattr(store, "_call", raced)
    response = c.post(url, headers=headers(), json=body)
    assert response.status_code == 409 and "content-disposition" not in response.headers
    assert not list(tmp_path.iterdir())


def test_session_revoked_before_download_returns_no_file(reviewed, monkeypatch, tmp_path):
    c, store, records, rows, calls = reviewed
    body = export_body(c, records)
    original_call = store._call
    original_file = scheduled_exports.tempfile.NamedTemporaryFile
    monkeypatch.setattr(
        scheduled_exports.tempfile,
        "NamedTemporaryFile",
        lambda **kw: original_file(dir=tmp_path, **kw),
    )

    def revoked(method, path, body=None, query=None):
        result = original_call(method, path, body=body, query=query)
        if (
            path == "rpc/research_scheduled_pair_review_read"
            and body["p_expected_hash"] is not None
            and body["p_codes"] == []
        ):
            monkeypatch.setattr(auth, "_session_active", lambda *a: False)
        return result

    monkeypatch.setattr(store, "_call", revoked)
    response = c.post(URL + "/" + SID + "/pair-export", headers=headers(), json=body)
    assert response.status_code == 401 and not list(tmp_path.iterdir())


def test_filter_empty_export_and_strict_format_scope(reviewed):
    c, store, records, rows, calls = reviewed
    url = URL + "/" + SID + "/pair-export"
    body = export_body(c, records, status="new")
    response = c.post(url, headers=headers(), json=body)
    assert response.status_code == 200 and parse(response) == []
    for changes in [
        {"direction": True},
        {"format": "xlsx"},
        {"scope": "all_filtered", "codes": ["US.A"]},
        {"review_revision_hash": "bad"},
        {"owner_id": OTHER},
    ]:
        assert c.post(url, headers=headers(), json={**body, **changes}).status_code == 422
    assert c.post(url, json=body).status_code == 401


def test_501_rows_batches_exact_order_and_selected_order(reviewed, monkeypatch):
    from datetime import datetime, timezone

    from tradingagents_api import capture_service, main

    c, store, records, reviews, calls = reviewed
    parent = store.rows[0]
    source = [
        {
            "code": "US.A" + str(i).zfill(4),
            "symbol": "A" + str(i).zfill(4),
            "stock_type": "STOCK",
            "price": 4,
        }
        for i in range(501)
    ]
    for record in records:
        stamp = datetime.now(timezone.utc).isoformat()
        observed = [
            {**row, "quote_identity_status": "verified", "quote_cache_at": stamp} for row in source
        ]
        monkeypatch.setattr(
            main,
            "screener",
            lambda observed=observed, stamp=stamp, **kw: {
                "available": True,
                "universe_loaded": True,
                "universe_as_of": stamp,
                "matched": 501,
                "rows": observed,
            },
        )
        snapshot = capture_service.build(parent, record["id"])
        record.update(snapshot=snapshot, published_at=snapshot["at"])
    body = export_body(c, records)
    url = URL + "/" + SID + "/pair-export"
    calls.clear()
    response = c.post(url, headers=headers(), json=body)
    assert response.status_code == 200, response.text
    rows = parse(response)
    assert [row["code"] for row in rows] == [r["code"] for r in source]
    batches = [
        b for b in calls if "p_codes" in b and b["p_expected_hash"] is not None and b["p_codes"]
    ]
    assert [len(b["p_codes"]) for b in batches] == [500, 1]
    chosen = [source[-1]["code"], source[0]["code"]]
    response = c.post(url, headers=headers(), json={**body, "scope": "selected", "codes": chosen})
    assert response.status_code == 200
    assert [row["code"] for row in parse(response)] == list(reversed(chosen))
    import json

    first = parse(response)[0]
    assert json.loads(first["previous_observation"])["code"] == source[0]["code"]
    assert json.loads(first["query_json"])["sort"] == "symbol" and first["review_revision"] == "0"


def test_final_revision_check_discards_already_assembled_file(reviewed, monkeypatch, tmp_path):
    c, store, records, rows, calls = reviewed
    c.patch(URL + "/" + SID + "/pair-reviews", headers=headers(), json=request(records))
    body = export_body(c, records)
    original = store._call
    file_factory = scheduled_exports.tempfile.NamedTemporaryFile
    monkeypatch.setattr(
        scheduled_exports.tempfile,
        "NamedTemporaryFile",
        lambda **kw: file_factory(dir=tmp_path, **kw),
    )

    def raced(method, path, body=None, query=None):
        if (
            path == "rpc/research_scheduled_pair_review_read"
            and body["p_expected_hash"] is not None
            and body["p_codes"] == []
        ):
            rows[0]["revision"] += 1
        return original(method, path, body=body, query=query)

    monkeypatch.setattr(store, "_call", raced)
    response = c.post(URL + "/" + SID + "/pair-export", headers=headers(), json=body)
    assert response.status_code == 409 and not list(tmp_path.iterdir())


def test_interrupted_file_transfer_removes_private_temporary_file(tmp_path):
    import asyncio

    path = tmp_path / "private-pair-interrupted.csv"
    path.write_text("private note")
    response = scheduled_exports.PrivateFileResponse(path)

    async def interrupted():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message):
            raise RuntimeError("Synthetic disconnected client")

        await response(
            {"type": "http", "method": "GET", "headers": [], "asgi": {"spec_version": "2.4"}},
            receive,
            send,
        )

    with pytest.raises(RuntimeError, match="disconnected"):
        asyncio.run(interrupted())
    assert not path.exists()


def test_downloads_retain_captured_instrument_classification_on_each_side(reviewed):
    from datetime import datetime

    from tradingagents_worker.instrument_classification import classify

    c, store, records, rows, calls = reviewed
    for record in records:
        snapshot = record["snapshot"]
        for observation in snapshot["observations"] + snapshot["members"]:
            at = observation["quote_cache_at"]
            observation["instrument_classification"] = classify(
                observation["code"], "STOCK", at, now=datetime.fromisoformat(at)
            )
    body = export_body(c, records)
    url = URL + "/" + SID + "/pair-export"
    response = c.post(url, headers=headers(), json=body)
    assert response.status_code == 200, response.text
    row = parse(response)[0]
    for side, record in zip(("previous", "current"), records, strict=False):
        assert (
            json.loads(row[side + "_instrument_classification"])
            == record["snapshot"]["members"][0]["instrument_classification"]
        )
    excel = c.post(url, headers=headers(), json={**body, "format": "excel"})
    assert excel.status_code == 200, excel.text
    root = ET.fromstring(excel.content)
    ns = {"s": "urn:schemas-microsoft-com:office:spreadsheet"}
    xmlrows = root.findall(".//s:Row", ns)
    headings = [x.text for x in xmlrows[0].findall("s:Cell/s:Data", ns)]
    cells = xmlrows[1].findall("s:Cell/s:Data", ns)
    for side, record in zip(("previous", "current"), records, strict=False):
        assert (
            json.loads(cells[headings.index(side + "_instrument_classification")].text)
            == record["snapshot"]["members"][0]["instrument_classification"]
        )
