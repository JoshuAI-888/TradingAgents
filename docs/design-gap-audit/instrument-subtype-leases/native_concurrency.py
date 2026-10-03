"""Disposable native DB; two real overlapping psql sessions, no production writes."""

import json
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"
BASE = "postgresql://joshmini@localhost/{database}?host=%2Fprivate%2Ftmp%2Ftradingagent-research-pg&port=55439"
DATABASE = "instrument_subtype_overlap_" + uuid.uuid4().hex[:10]
A = "20000000-0000-0000-0000-000000000001"
B = "20000000-0000-0000-0000-000000000002"


def query(sql, database=DATABASE):
    return subprocess.run(
        [PSQL, BASE.format(database=database), "-X", "-At", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    ).stdout.strip()


def start(sql):
    return subprocess.Popen(
        [PSQL, BASE.format(database=DATABASE), "-X", "-At", "-v", "ON_ERROR_STOP=1", "-c", sql],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def wait_event(marker, blocking=False):
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        clause = "cardinality(pg_blocking_pids(pid))>0" if blocking else "wait_event='PgSleep'"
        if (
            query(
                "select count(*) from pg_stat_activity where datname='"
                + DATABASE
                + "' and pid<>pg_backend_pid() and query like '%"
                + marker
                + "%' and "
                + clause
            )
            != "0"
        ):
            return True
        time.sleep(0.03)
    return False


def done(process):
    out, err = process.communicate(timeout=8)
    if process.returncode:
        raise RuntimeError(err)
    return out.strip()


processes = []
report = {}
query("create database " + DATABASE, database="postgres")
try:
    for name in (
        "20261003105155_instrument_subtype_cache.sql",
        "20261003105208_instrument_subtype_leases.sql",
    ):
        query((ROOT / "supabase/migrations" / name).read_text())
    first = start(
        "begin;set local role service_role;select public.instrument_subtype_claim('US','"
        + A
        + "');select pg_sleep(3) /* subtype_overlap_a */;commit;"
    )
    processes.append(first)
    assert wait_event("subtype_overlap_a")
    contender = start(
        "set role service_role;select coalesce(public.instrument_subtype_claim('US','"
        + B
        + "')::text,'null') /* subtype_overlap_b */;"
    )
    processes.append(contender)
    assert wait_event("subtype_overlap_b", blocking=True)
    first_out = done(first)
    contender_out = done(contender)
    assert '"id": "' + A + '"' in first_out and contender_out.endswith("null")
    report["claim_overlap"] = {"actual_blocking_observed": True, "contender_acquired": False}
    stamp = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    context = {
        "version": "yfinance_info_context_v1",
        "code": "US.PLD",
        "provider_symbol": "PLD",
        "source": "yfinance",
        "fields": {"quoteType": "EQUITY"},
        "scope": "Same-response provider info calendar and currencies; not per-metric periods or cross-provider currency attribution",
        "classification_scope": "Same-response Yahoo quoteType; does not reinterpret another provider trust/fund category",
    }
    record = {
        "version": "instrument_subtype_cache_v1",
        "code": "US.PLD",
        "context": context,
        "retrieved_at": stamp,
        "attempted_at": stamp,
        "status": "success",
    }
    payload = json.dumps(record).replace("'", "''")
    saver = start(
        "begin;set local role service_role;select revision from public.instrument_subtype_save_leased('US','"
        + A
        + "','US.PLD',0,'"
        + payload
        + "'::jsonb);select pg_sleep(3) /* subtype_save_a */;commit;"
    )
    processes.append(saver)
    assert wait_event("subtype_save_a")
    releaser = start(
        "set role service_role;select public.instrument_subtype_release('US','"
        + A
        + "') /* subtype_release_b */;"
    )
    processes.append(releaser)
    assert wait_event("subtype_release_b", blocking=True)
    assert "1" in done(saver).splitlines() and done(releaser).endswith("t")
    assert query("select revision from public.instrument_subtype_cache where code='US.PLD'") == "1"
    assert query(
        "set role service_role;select public.instrument_subtype_claim('US','"
        + B
        + "') is not null;"
    ).endswith("t")
    query(
        "set role service_role;do $$ begin begin perform public.instrument_subtype_save_leased('US','"
        + A
        + "','US.PLD',0,'"
        + payload
        + "'::jsonb);raise exception 'stale publisher accepted';exception when object_not_in_prerequisite_state then null;end;end;$$;"
    )
    assert (
        json.loads(query("select record from public.instrument_subtype_cache where code='US.PLD'"))
        == record
    )
    report["publication_release_overlap"] = {
        "actual_blocking_observed": True,
        "revision": 1,
        "successor_acquired": True,
        "stale_publisher_rejected": True,
        "prior_record_exact": True,
    }
finally:
    for process in processes:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=3)
    query("drop database " + DATABASE + " with (force)", database="postgres")
report["database_removed"] = (
    query("select count(*) from pg_database where datname='" + DATABASE + "'", database="postgres")
    == "0"
)
assert report["database_removed"]
(Path(__file__).parent / "native-concurrency.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
