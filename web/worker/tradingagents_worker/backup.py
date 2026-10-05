"""Weekly logical backup: selected product/recovery tables → gzip → Supabase Storage
bucket `backups/<date>/<table>.jsonl.gz`, plus a manifest and an app_settings
pointer. Pure REST (PostgREST + Storage) — no pg_dump binary needed.

Runs as a Render cron (`python -m tradingagents_worker.backup`). Uses only
SUPABASE_URL + SUPABASE_SERVICE_KEY, which the worker already carries.

user_secrets is deliberately EXCLUDED — secrets never leave the database, not
even into our own Storage bucket.
"""

from __future__ import annotations

import gzip
import json
import tempfile
from datetime import datetime, timezone
from typing import BinaryIO

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
    "screener_refresh_runs",
    "screener_refresh_leases",
    "screener_generations",
    "screener_generation_rows",
    "screener_refresh_staged_rows",
    "instrument_subtype_runs",
    "instrument_subtype_leases",
    "instrument_subtype_cache",
]
BUCKET = "backups"
PAGE = 1000
# Every order is an actual primary key; composite keys include every component.
TABLE_ORDER = dict.fromkeys(TABLES, "id.asc")
TABLE_ORDER.update(
    {
        "app_settings": "key.asc",
        "price_bars": "ticker_id.asc,bar_date.asc,source.asc,adjusted.asc",
        "company_profiles": "ticker_id.asc",
        "run_digest": "run_id.asc",
        "vendor_budget_ledger": "vendor.asc,path_template.asc,window_start.asc",
        "screener_refresh_leases": "market.asc",
        "screener_generation_rows": "generation_id.asc,code.asc",
        "screener_refresh_staged_rows": "run_id.asc,code.asc",
        "instrument_subtype_leases": "market.asc",
        "instrument_subtype_cache": "market.asc,code.asc",
    }
)
EVIDENCE_TABLES = {"screener_generation_rows", "screener_refresh_staged_rows"}


def _headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}"}


def _write_table(session, table: str, destination: BinaryIO) -> int:
    """Write each REST page directly to gzip; memory is bounded by one page.

    Unique ordering stabilizes pagination. This is still a nontransactional
    export, so recovery qualification must account for concurrent writers.
    """
    count = 0
    page_size = 100 if table in EVIDENCE_TABLES else PAGE
    with gzip.GzipFile(fileobj=destination, mode="wb", mtime=0) as gz:
        while True:
            response = session.get(
                f"{SETTINGS.supabase_url}/rest/v1/{table}",
                params={
                    "select": "*",
                    "limit": page_size,
                    "offset": count,
                    "order": TABLE_ORDER[table],
                },
                headers=_headers(SETTINGS.supabase_service_key),
                timeout=120,
            )
            response.raise_for_status()
            chunk = response.json()
            if (
                not isinstance(chunk, list)
                or len(chunk) > page_size
                or any(not isinstance(row, dict) for row in chunk)
            ):
                raise RuntimeError(f"Invalid backup page for {table}")
            for row in chunk:
                gz.write((json.dumps(row, default=str, allow_nan=False) + "\n").encode())
            count += len(chunk)
            if len(chunk) < page_size:
                return count
            # Release page objects before requesting/decoding the next page.
            del chunk, response


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


def _upload(session, path: str, data: bytes | BinaryIO) -> None:
    if isinstance(data, bytes):
        length = len(data)
    else:
        start = data.tell()
        data.seek(0, 2)
        length = data.tell() - start
        data.seek(start)
    r = session.post(
        f"{SETTINGS.supabase_url}/storage/v1/object/{BUCKET}/{path}",
        data=data,
        headers={
            **_headers(SETTINGS.supabase_service_key),
            "Content-Type": "application/octet-stream",
            "Content-Length": str(length),
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
        with tempfile.TemporaryFile(mode="w+b") as buf:
            count = _write_table(session, table, buf)
            buf.seek(0)
            _upload(session, f"{stamp}/{table}.jsonl.gz", buf)
        manifest["tables"][table] = count
        print(f"{table}: {count} rows", flush=True)
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["consistency"] = (
        "Nontransactional REST export; coordinate writers for a consistent recovery snapshot"
    )
    _upload(session, f"{stamp}/_manifest.json", json.dumps(manifest, indent=2).encode())
    from .db import Db

    Db().upsert("app_settings", "key", {"key": "backup_state", "value": manifest})
    print(f"backup {stamp} complete: {sum(manifest['tables'].values())} rows", flush=True)
    return manifest


if __name__ == "__main__":
    main()
