"""Weekly logical backup: every product table → gzipped JSONL → Supabase Storage
bucket `backups/<date>/<table>.jsonl.gz`, plus a manifest and an app_settings
pointer. Pure REST (PostgREST + Storage) — no pg_dump binary needed.

Runs as a Render cron (`python -m tradingagents_worker.backup`). Uses only
SUPABASE_URL + SUPABASE_SERVICE_KEY, which the worker already carries.

user_secrets is deliberately EXCLUDED — secrets never leave the database, not
even into our own Storage bucket.
"""

from __future__ import annotations

import gzip
import io
import json
from datetime import datetime, timezone

from .config import SETTINGS

TABLES = [
    "tickers",
    "watchlists",
    "watchlist_items",
    "app_settings",
    "jobs",
    "job_events",
    "runs",
    "agent_reports",
    "debate_messages",
    "decisions",
    "memory_entries",
    "settlements",
    "run_digest",
    "news_items",
    "price_bars",
    "company_profiles",
    "data_fetch_log",
    "discovery_candidates",
    "vendor_budget_ledger",
]
BUCKET = "backups"
PAGE = 1000


def _headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _fetch_all(session, table: str) -> list:
    rows: list = []
    offset = 0
    while True:
        r = session.get(
            f"{SETTINGS.supabase_url}/rest/v1/{table}",
            params={"select": "*", "limit": PAGE, "offset": offset},
            headers=_headers(SETTINGS.supabase_service_key),
            timeout=120,
        )
        r.raise_for_status()
        chunk = r.json()
        rows.extend(chunk)
        if len(chunk) < PAGE:
            return rows
        offset += PAGE


def _ensure_bucket(session) -> None:
    r = session.post(
        f"{SETTINGS.supabase_url}/storage/v1/bucket",
        data=json.dumps({"name": BUCKET, "public": False}),
        headers={**_headers(SETTINGS.supabase_service_key), "Content-Type": "application/json"},
        timeout=60,
    )
    if r.status_code in (200, 201):
        return
    # Supabase Storage answers bucket-already-exists with HTTP 400 whose body
    # code is BucketAlreadyExists (the body's statusCode says 409 — the wire
    # status does not), so a plain 409 check never matches.
    if r.status_code in (400, 409) and "BucketAlreadyExists" in r.text:
        return
    raise RuntimeError(f"bucket create failed: {r.status_code} {r.text[:200]}")


def _upload(session, path: str, data: bytes) -> None:
    r = session.post(
        f"{SETTINGS.supabase_url}/storage/v1/object/{BUCKET}/{path}",
        data=data,
        headers={
            **_headers(SETTINGS.supabase_service_key),
            "Content-Type": "application/octet-stream",
            "x-upsert": "true",
        },
        timeout=300,
    )
    r.raise_for_status()


def main() -> dict:
    if not SETTINGS.supabase_url or not SETTINGS.supabase_service_key:
        raise SystemExit("SUPABASE_URL / SUPABASE_SERVICE_KEY not configured")
    import requests  # local import: tests can stub it

    session = requests.Session()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    _ensure_bucket(session)
    manifest = {"date": stamp, "tables": {}, "finished_at": datetime.now(timezone.utc).isoformat()}
    for table in TABLES:
        rows = _fetch_all(session, table)
        buf = io.BytesIO()
        with gzip.GzipFile(fileobj=buf, mode="wb", mtime=0) as gz:
            for row in rows:
                gz.write((json.dumps(row, default=str) + "\n").encode())
        _upload(session, f"{stamp}/{table}.jsonl.gz", buf.getvalue())
        manifest["tables"][table] = len(rows)
        print(f"{table}: {len(rows)} rows", flush=True)
    _upload(session, f"{stamp}/_manifest.json", json.dumps(manifest, indent=2).encode())
    from .db import Db

    Db().upsert("app_settings", "key", {"key": "backup_state", "value": manifest})
    print(f"backup {stamp} complete: {sum(manifest['tables'].values())} rows", flush=True)
    return manifest


if __name__ == "__main__":
    main()
