"""Backup hygiene: snapshot everything EXCEPT secrets."""

import pytest
from tradingagents_worker.backup import BUCKET, TABLES, _ensure_bucket


def test_backup_excludes_secrets():
    assert "user_secrets" not in TABLES
    assert BUCKET == "backups"


def test_backup_covers_product_tables():
    for t in ("runs", "decisions", "run_digest", "price_bars", "news_items", "app_settings"):
        assert t in TABLES


class FakeResp:
    def __init__(self, status_code, text=""):
        self.status_code, self.text = status_code, text


class FakeSession:
    def __init__(self, resp):
        self.resp = resp

    def post(self, url, **kw):
        return self.resp


LIVE_ALREADY_EXISTS = (
    '400 {"statusCode":"409","error":"Duplicate",'
    '"message":"The resource already exists","code":"BucketAlreadyExists"}'
)


def test_ensure_bucket_tolerates_supabase_already_exists_shape():
    # Supabase Storage answers bucket-already-exists with HTTP 400 whose BODY
    # says statusCode 409 — the wire status is 400, so a plain 409 check
    # never matches (live failure 2026-09-28 03:00 UTC).
    r = FakeResp(400, LIVE_ALREADY_EXISTS)
    _ensure_bucket(FakeSession(r))


def test_ensure_bucket_tolerates_real_409():
    r = FakeResp(409, '{"code":"BucketAlreadyExists"}')
    _ensure_bucket(FakeSession(r))


def test_ensure_bucket_raises_on_real_failure():
    with pytest.raises(RuntimeError):
        _ensure_bucket(FakeSession(FakeResp(500, "boom")))


def test_backup_covers_pinned_generation_and_subtype_recovery_tables():
    from tradingagents_worker.backup import TABLE_ORDER

    expected = {
        "screener_refresh_runs",
        "screener_refresh_leases",
        "screener_generations",
        "screener_generation_rows",
        "screener_refresh_staged_rows",
        "instrument_subtype_cache",
        "instrument_subtype_runs",
        "instrument_subtype_leases",
    }
    assert expected <= set(TABLES)
    assert set(TABLE_ORDER) == set(TABLES)
    assert TABLE_ORDER["price_bars"] == "ticker_id.asc,bar_date.asc,source.asc,adjusted.asc"
    assert TABLE_ORDER["screener_generation_rows"] == "generation_id.asc,code.asc"
    assert TABLE_ORDER["screener_refresh_staged_rows"] == "run_id.asc,code.asc"
    assert TABLE_ORDER["instrument_subtype_cache"] == "market.asc,code.asc"


def test_large_table_pages_are_written_to_disk_without_retaining_previous_pages():
    import gzip
    import json
    import tempfile
    import weakref

    from tradingagents_worker.backup import _write_table

    class Row(dict):
        pass

    previous = []
    calls = []

    class Page:
        def __init__(self, rows):
            self.rows = rows

        def raise_for_status(self):
            pass

        def json(self):
            return self.rows

    class Session:
        def get(self, url, params, **kwargs):
            # A loop variable may retain one row; prior pages must be released.
            assert sum(reference() is not None for reference in previous) <= 1
            assert params["limit"] == 100
            assert params["order"] == "generation_id.asc,code.asc"
            offset = params["offset"]
            calls.append(offset)
            rows = [
                Row(
                    generation_id="run",
                    code=f"US.S{i:04d}",
                    row={"code": f"US.S{i:04d}", "evidence": "x" * 9000},
                )
                for i in range(offset, min(offset + 100, 205))
            ]
            previous[:] = [weakref.ref(row) for row in rows]
            return Page(rows)

    with tempfile.TemporaryFile(mode="w+b") as destination:
        assert _write_table(Session(), "screener_generation_rows", destination) == 205
        destination.seek(0)
        recovered = [json.loads(line) for line in gzip.GzipFile(fileobj=destination)]
    assert calls == [0, 100, 200]
    assert [row["code"] for row in recovered] == [f"US.S{i:04d}" for i in range(205)]
    assert all(len(row["row"]["evidence"]) == 9000 for row in recovered)


def test_backup_upload_stream_has_exact_length_and_requests_preserves_file_body(monkeypatch):
    import tempfile

    import requests
    from tradingagents_worker.backup import SETTINGS, _upload

    monkeypatch.setattr(SETTINGS, "supabase_url", "https://example.invalid")

    class Response:
        def raise_for_status(self):
            pass

    class Session:
        def post(self, url, data, headers, **kwargs):
            assert not isinstance(data, bytes)
            prepared = requests.Request("POST", url, data=data, headers=headers).prepare()
            assert prepared.body is data
            assert prepared.headers["Content-Length"] == "9"
            assert "Transfer-Encoding" not in prepared.headers
            assert data.read() == b"stream me"
            return Response()

    with tempfile.TemporaryFile(mode="w+b") as source:
        source.write(b"stream me")
        source.seek(0)
        _upload(Session(), "test/table.jsonl.gz", source)


def test_main_backup_recovers_generation_pointer_dependencies_and_closes_streams(monkeypatch):
    import gzip
    import json

    import requests
    from tradingagents_worker import backup
    from tradingagents_worker.db import Db

    dataset = {
        "app_settings": [{"key": "universe_state_US", "value": {"generation_id": "generation"}}],
        "screener_refresh_runs": [{"id": "generation", "market": "US"}],
        "screener_refresh_leases": [{"market": "US", "run_id": "generation"}],
        "screener_generations": [{"id": "generation", "market": "US", "row_count": 1}],
        "screener_generation_rows": [
            {"generation_id": "generation", "code": "US.A", "row": {"code": "US.A"}}
        ],
        "screener_refresh_staged_rows": [
            {"run_id": "generation", "code": "US.A", "payload": {"code": "US.A"}}
        ],
        "instrument_subtype_runs": [{"id": "subtype", "market": "HK"}],
        "instrument_subtype_leases": [{"market": "HK", "run_id": "subtype"}],
        "instrument_subtype_cache": [
            {"market": "HK", "code": "HK.00001", "context": {"quoteType": "EQUITY"}}
        ],
    }
    uploaded, handles, saved = {}, [], []

    class Response:
        status_code = 200

        def __init__(self, rows=None):
            self.rows = rows

        def raise_for_status(self):
            pass

        def json(self):
            return self.rows

    class Session:
        def get(self, url, params, **kwargs):
            table = url.rsplit("/", 1)[-1]
            assert params["order"] == backup.TABLE_ORDER[table]
            return Response(
                dataset.get(table, [])[params["offset"] : params["offset"] + params["limit"]]
            )

        def post(self, url, data, **kwargs):
            name = url.rsplit("/", 1)[-1]
            if name.endswith(".jsonl.gz"):
                handles.append(data)
                assert kwargs["headers"]["Content-Length"] == str(data.seek(0, 2))
                data.seek(0)
                uploaded[name[:-9]] = [json.loads(line) for line in gzip.GzipFile(fileobj=data)]
            elif name == "_manifest.json":
                uploaded["manifest"] = json.loads(data)
            return Response()

    monkeypatch.setattr(requests, "Session", Session)
    monkeypatch.setattr(Db, "upsert", lambda *args: saved.append(args))
    monkeypatch.setattr(backup.SETTINGS, "supabase_url", "https://example.invalid")
    monkeypatch.setattr(backup.SETTINGS, "supabase_service_key", "test-only")
    manifest = backup.main()
    assert all(handle.closed for handle in handles)
    assert uploaded["screener_generation_rows"] == dataset["screener_generation_rows"]
    assert uploaded["screener_refresh_staged_rows"] == dataset["screener_refresh_staged_rows"]
    assert all(uploaded[table] == rows for table, rows in dataset.items())
    generation = uploaded["app_settings"][0]["value"]["generation_id"]
    assert (
        generation
        == uploaded["screener_generations"][0]["id"]
        == uploaded["screener_generation_rows"][0]["generation_id"]
    )
    assert manifest["tables"]["screener_generation_rows"] == 1
    assert "Nontransactional" in manifest["consistency"]
    assert saved[-1][-1]["value"] == manifest


def test_failed_backup_page_cannot_publish_manifest_or_success_pointer(monkeypatch):
    import requests
    from tradingagents_worker import backup
    from tradingagents_worker.db import Db

    class Response:
        status_code = 200

        def raise_for_status(self):
            pass

    class Session:
        def get(self, *args, **kwargs):
            raise RuntimeError("source unavailable")

        def post(self, url, **kwargs):
            assert "/storage/v1/bucket" in url
            return Response()

    monkeypatch.setattr(requests, "Session", Session)
    monkeypatch.setattr(
        Db, "upsert", lambda *args: pytest.fail("Failed export must not advance backup pointer")
    )
    monkeypatch.setattr(backup.SETTINGS, "supabase_url", "https://example.invalid")
    monkeypatch.setattr(backup.SETTINGS, "supabase_service_key", "test-only")
    with pytest.raises(RuntimeError, match="source unavailable"):
        backup.main()
