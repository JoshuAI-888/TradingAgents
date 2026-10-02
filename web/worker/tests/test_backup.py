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
