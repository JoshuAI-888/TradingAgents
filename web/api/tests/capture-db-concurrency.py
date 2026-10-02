"""ISOLATED LOCAL DATABASE ONLY: concurrent append/import preserves both captures.
The fixture key is fixed and cleanup restores its temporarily disabled local row
trigger within one transaction. Never run against Supabase or another database.
"""

import json
import subprocess
import time

PSQL = [
    "/opt/homebrew/opt/postgresql@16/bin/psql",
    "-h",
    "/private/tmp/tradingagent-research-pg",
    "-p",
    "55439",
    "-d",
    "postgres",
    "-v",
    "ON_ERROR_STOP=1",
    "-qAt",
]
KEY = "screen_history:" + "c" * 16 + ":" + "d" * 64


def sql(query):
    return subprocess.check_output(PSQL + ["-c", query], text=True).strip()


def record(sid, stamp):
    return {
        "id": sid,
        "snapshot": {
            "id": sid,
            "at": stamp,
            "version": 2,
            "complete": True,
            "members": [{"code": "US.BRK.B"}],
        },
    }


LEGACY = record("concurrent-legacy", "2026-10-01T00:00:00Z")
A = [LEGACY, record("concurrent-a", "2026-10-02T00:00:00Z")]
B = [LEGACY, record("concurrent-b", "2026-10-02T00:00:01Z")]


def append(records):
    return f"select public.screen_capture_append('{KEY}',$capture${json.dumps(records)}$capture$::jsonb);"


first = second = None
try:
    assert sql(f"select count(*) from public.screen_captures where history_key='{KEY}'") == "0", (
        "Fixture key already exists"
    )
    first = subprocess.Popen(
        PSQL
        + [
            "-c",
            "set application_name='capture-append-a';begin;set local role service_role;"
            + append(A)
            + "select pg_sleep(2);commit;",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    observed = False
    for _ in range(40):
        if (
            sql(
                "select count(*) from pg_stat_activity where application_name='capture-append-a' and wait_event='PgSleep'"
            )
            == "1"
        ):
            observed = True
            break
        time.sleep(0.05)
    assert observed, "First append did not reach its uncommitted state"
    second = subprocess.Popen(
        PSQL + ["-c", "set application_name='capture-append-b';set role service_role;" + append(B)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    waited = False
    for _ in range(40):
        if (
            sql(
                "select count(*) from pg_stat_activity where application_name='capture-append-b' and wait_event_type='Lock'"
            )
            == "1"
        ):
            waited = True
            break
        time.sleep(0.05)
    assert waited, "Second import did not wait for the shared legacy identity"
    out, err = first.communicate(timeout=10)
    assert first.returncode == 0, err
    out, err = second.communicate(timeout=10)
    assert second.returncode == 0, err
    assert out.strip() == "1", out
    assert (
        sql(
            f"select string_agg(id,',' order by id) from public.screen_captures where history_key='{KEY}'"
        )
        == "concurrent-a,concurrent-b,concurrent-legacy"
    )
    assert sql("set role service_role;" + append(A)) == "0", "Exact replay created a new record"
    print(
        "concurrent capture append passed: shared legacy import serialized; both new captures retained"
    )
finally:
    for process in (first, second):
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
    # Administrative cleanup of disposable fixtures in this isolated cluster only.
    sql(
        f"begin;alter table public.screen_captures disable trigger screen_capture_immutable;delete from public.screen_captures where history_key='{KEY}';alter table public.screen_captures enable trigger screen_capture_immutable;commit;"
    )
