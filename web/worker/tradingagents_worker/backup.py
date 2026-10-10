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
import hashlib
import json
import re
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


def _checksum(source):
    digest = hashlib.sha256()
    while chunk := source.read(65536):
        digest.update(chunk)
    return digest.hexdigest()


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
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    _ensure_bucket(session)
    prune_verified_backups(session)
    bucket_bytes = backup_bucket_bytes(session)
    uploaded_bytes = 0
    manifest = {
        "date": stamp,
        "tables": {},
        "sha256": {},
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    for table in TABLES:
        with tempfile.TemporaryFile(mode="w+b") as buf:
            count = _write_table(session, table, buf)
            uploaded_bytes += buf.seek(0, 2)
            if bucket_bytes + uploaded_bytes > 750_000_000:
                raise ValueError("Backup bucket would exceed its 750 MB operating ceiling")
            buf.seek(0)
            manifest["sha256"][table] = _checksum(buf)
            buf.seek(0)
            _upload(session, f"{stamp}/{table}.jsonl.gz", buf)
        manifest["tables"][table] = count
        print(f"{table}: {count} rows", flush=True)
    manifest["finished_at"] = datetime.now(timezone.utc).isoformat()
    manifest["consistency"] = (
        "Nontransactional REST export; coordinate writers for a consistent recovery snapshot"
    )
    verify_backup(session, stamp, manifest)
    manifest["verified_at"] = datetime.now(timezone.utc).isoformat()
    manifest["bucket_bytes_before"] = bucket_bytes
    manifest["export_bytes"] = uploaded_bytes
    manifest["storage_warning"] = bucket_bytes + uploaded_bytes >= 250_000_000
    _upload(session, f"{stamp}/_manifest.json", json.dumps(manifest, indent=2).encode())
    from .db import Db

    Db().upsert("app_settings", "key", {"key": "backup_state", "value": manifest})
    prune_verified_backups(session)
    print(f"backup {stamp} complete: {sum(manifest['tables'].values())} rows", flush=True)
    return manifest


def verify_backup(session, prefix, manifest):
    """Download and decode every gzip/JSON row with counts and checksums.

    This qualifies object integrity, not transaction consistency or a full DB
    restore. Fail closed before publishing success or pruning older backups.
    """
    if set(manifest.get("tables", {})) != set(TABLES) or set(manifest.get("sha256", {})) != set(
        TABLES
    ):
        raise ValueError("Incomplete backup manifest")
    for table in TABLES:
        response = session.get(
            f"{SETTINGS.supabase_url}/storage/v1/object/{BUCKET}/{prefix}/{table}.jsonl.gz",
            headers=_headers(SETTINGS.supabase_service_key),
            stream=True,
            timeout=300,
        )
        response.raise_for_status()
        with tempfile.TemporaryFile(mode="w+b") as buf:
            for chunk in response.iter_content(chunk_size=65536):
                buf.write(chunk)
            response.close()
            buf.seek(0)
            if _checksum(buf) != manifest["sha256"][table]:
                raise ValueError("Backup object checksum mismatch")
            buf.seek(0)
            with gzip.GzipFile(fileobj=buf) as source:
                count = 0
                for line in source:
                    if not isinstance(json.loads(line), dict):
                        raise ValueError("Invalid recovered backup row")
                    count += 1
            if count != manifest["tables"][table]:
                raise ValueError("Backup object row count mismatch")


def _objects(session, prefix):
    result = []
    for offset in range(0, 10000, 100):
        response = session.post(
            f"{SETTINGS.supabase_url}/storage/v1/object/list/{BUCKET}",
            headers=_headers(SETTINGS.supabase_service_key),
            json={
                "prefix": prefix,
                "limit": 100,
                "offset": offset,
                "sortBy": {"column": "name", "order": "asc"},
            },
            timeout=60,
        )
        response.raise_for_status()
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("Invalid backup object listing")
        result.extend(rows)
        if len(rows) < 100:
            return result
    raise ValueError("Backup listing exceeds supported limit")


def prune_verified_backups(session, keep=4):
    verified, incomplete = [], []
    for obj in _objects(session, ""):
        prefix = obj.get("name", "")
        # Existing legacy exports are preserved until separately qualified.
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{6}Z", prefix):
            continue
        response = session.get(
            f"{SETTINGS.supabase_url}/storage/v1/object/{BUCKET}/{prefix}/_manifest.json",
            headers=_headers(SETTINGS.supabase_service_key),
            timeout=60,
        )
        if response.status_code == 404:
            stamp = datetime.strptime(prefix, "%Y-%m-%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            if (datetime.now(timezone.utc) - stamp).total_seconds() > 7 * 86400:
                incomplete.append(prefix)
            continue
        response.raise_for_status()
        manifest = response.json()
        if (
            manifest.get("verified_at")
            and set(manifest.get("tables", {})) == set(TABLES)
            and set(manifest.get("sha256", {})) == set(TABLES)
        ):
            verified.append((prefix, manifest))
    for prefix, manifest in sorted(verified, reverse=True)[keep:]:
        verify_backup(session, prefix, manifest)
        expected = {f"{table}.jsonl.gz" for table in TABLES} | {"_manifest.json"}
        if {o.get("name") for o in _objects(session, prefix)} != expected:
            raise ValueError("Unexpected objects in expiring backup")
        response = session.delete(
            f"{SETTINGS.supabase_url}/storage/v1/object/{BUCKET}",
            headers=_headers(SETTINGS.supabase_service_key),
            json={"prefixes": [f"{prefix}/{name}" for name in sorted(expected)]},
            timeout=60,
        )
        response.raise_for_status()
    if incomplete and verified:
        latest, manifest = max(verified)
        verify_backup(session, latest, manifest)
        allowed = {f"{table}.jsonl.gz" for table in TABLES}
        for prefix in incomplete:
            names = {o.get("name") for o in _objects(session, prefix)}
            if not names <= allowed:
                raise ValueError("Unexpected objects in incomplete backup")
            if names:
                response = session.delete(
                    f"{SETTINGS.supabase_url}/storage/v1/object/{BUCKET}",
                    headers=_headers(SETTINGS.supabase_service_key),
                    json={"prefixes": [f"{prefix}/{name}" for name in sorted(names)]},
                    timeout=60,
                )
                response.raise_for_status()


def backup_bucket_bytes(session):
    total = 0
    for root in _objects(session, ""):
        files = [root] if root.get("id") else _objects(session, root["name"])
        for obj in files:
            size = (obj.get("metadata") or {}).get("size")
            if type(size) is not int or size < 0:
                raise ValueError("Invalid backup object size")
            total += size
    return total


if __name__ == "__main__":
    main()
