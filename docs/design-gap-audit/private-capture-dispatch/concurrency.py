"""Isolated disposable DB only; actual two-process PostgreSQL dispatch contention."""

import json
import subprocess
import time
from pathlib import Path

PSQL = [
    "/opt/homebrew/opt/postgresql@16/bin/psql",
    "-h",
    "/private/tmp/tradingagent-research-pg",
    "-p",
    "55439",
    "-d",
    "capture_dispatch_qualification",
    "-v",
    "ON_ERROR_STOP=1",
    "-At",
]
SID = "00000000-0000-4000-8000-000000000020"
OWNER = "00000000-0000-4000-8000-000000000001"
OID = "00000000-0000-4000-8000-000000000021"


def query(sql):
    return subprocess.run(
        PSQL + ["-c", sql], capture_output=True, text=True, check=True, timeout=15
    ).stdout.strip()


query(
    f"insert into public.research_capture_schedules(id,owner_id,definition_hash,definition,name,cadence,enabled,activated_at,next_due_at) values('{SID}','{OWNER}',repeat('a',64),'{{}}','Concurrent','{{}}',true,'2026-01-01T00:00:00Z','2026-01-02T00:00:00Z')"
)
sql = f"begin;set local role service_role;select id from public.research_capture_dispatch('{SID}','{OWNER}',1,'2026-01-02T00:00:00Z','2026-01-03T00:00:00Z','2099-01-01T00:00:00Z','{OID}');select pg_sleep(1);commit;"
start = time.monotonic()
first = subprocess.Popen(
    PSQL + ["-c", sql], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
)
# Confirm transaction holds schedule row lock before starting the contender.
for _ in range(100):
    locked = query(
        "select count(*) from pg_locks l join pg_stat_activity a on a.pid=l.pid where a.datname='capture_dispatch_qualification' and l.relation='public.research_capture_schedules'::regclass and l.mode='RowShareLock' and l.granted"
    )
    if locked != "0":
        break
    if first.poll() is not None:
        raise AssertionError("First transaction ended before overlap")
    time.sleep(0.01)
else:
    raise AssertionError("No confirmed live lock")
second = subprocess.Popen(
    PSQL + ["-c", sql], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
)
a, ae = first.communicate(timeout=15)
b, be = second.communicate(timeout=15)
assert first.returncode == second.returncode == 0, (ae, be)
assert a.splitlines().count(OID) == 1 and b.splitlines().count(OID) == 1, (a, b)
count = query(f"select count(*) from public.research_capture_occurrences where schedule_id='{SID}'")
assert count == "1", count
next_due = query(f"select next_due_at from public.research_capture_schedules where id='{SID}'")
assert next_due.startswith("2099-01-01"), next_due
result = {
    "isolated_database": "capture_dispatch_qualification",
    "confirmed_overlapping_schedule_lock": True,
    "process_exit_codes": [first.returncode, second.returncode],
    "same_occurrence_returned_twice": True,
    "persisted_occurrences": int(count),
    "next_due": next_due,
    "elapsed_seconds": round(time.monotonic() - start, 3),
    "limits": "Dispatch only; no lease/worker/publication or actual PostgREST qualification.",
}
Path(__file__).with_name("concurrency-result.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result))
