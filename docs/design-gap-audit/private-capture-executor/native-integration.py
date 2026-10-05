"""Connected executor, real builder, native SQL; isolated disposable DB ONLY."""

import json
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import HTTPException
from tradingagents_api import capture_service, main as api, research_schedules
from tradingagents_worker.capture_dispatch import dispatch_schedule
from tradingagents_worker.capture_executor import CaptureExecutor

PSQL = [
    "/opt/homebrew/opt/postgresql@16/bin/psql",
    "-h",
    "/private/tmp/tradingagent-research-pg",
    "-p",
    "55439",
    "-d",
    "capture_executor_qualification",
    "-v",
    "ON_ERROR_STOP=1",
    "-At",
]
OWNER = "00000000-0000-4000-8000-000000000001"
WORKER = "00000000-0000-4000-8000-000000000040"


def literal(value):
    if value is None:
        return "NULL"
    if type(value) is bool:
        return "true" if value else "false"
    if type(value) is int:
        return str(value)
    if isinstance(value, (dict, list)):
        return "'" + json.dumps(value, allow_nan=False).replace("'", "''") + "'::jsonb"
    return "'" + str(value).replace("'", "''") + "'"


def query(sql):
    return subprocess.run(
        PSQL + ["-c", sql], capture_output=True, text=True, check=True, timeout=35
    ).stdout.strip()


class NativeDb:
    calls = []

    def _call(self, method, path, body=None, query=None):
        self.calls.append(path)
        if path.startswith("rpc/"):
            name = path[4:]
            assert name in {
                "research_capture_schedule_save",
                "research_capture_dispatch",
                "research_capture_claim",
                "research_capture_renew",
                "research_capture_fail",
                "research_capture_publish",
            }
            args = ",".join(k + "=>" + literal(v) for k, v in body.items())
            sql = f"select coalesce(json_agg(t),'[]'::json) from public.{name}({args}) t"
        else:
            assert (
                method == "GET"
                and path == "research_capture_schedules"
                and set(query) == {"id", "owner_id", "select", "limit"}
            )
            sql = (
                "select coalesce(json_agg(t),'[]'::json) from (select * from public.research_capture_schedules where id="
                + literal(str(uuid.UUID(query["id"][3:])))
                + " and owner_id="
                + literal(str(uuid.UUID(query["owner_id"][3:])))
                + " limit 1) t"
            )
        # Use the same service role as real queue transport.
        return json.loads(globals()["query"]("set role service_role;" + sql).splitlines()[-1])


db = NativeDb()
definition, digest = research_schedules._definition(
    {"market": "US", "filters": [{"field": "price", "max": 5}]}
)
now = datetime.now(timezone.utc)
due = now.replace(second=0, microsecond=0) - timedelta(minutes=2)
cadence = {"timezone": "UTC", "hour": due.hour, "minute": due.minute, "weekdays": list(range(7))}
schedule = db._call(
    "POST",
    "rpc/research_capture_schedule_save",
    body={
        "p_owner": OWNER,
        "p_hash": digest,
        "p_revision": 0,
        "p_definition": definition,
        "p_name": "Native executor synthetic cohort",
        "p_cadence": cadence,
        "p_enabled": False,
        "p_next": None,
    },
)[0]
query(
    "update public.research_capture_schedules set enabled=true,activated_at="
    + literal((due - timedelta(days=1)).isoformat())
    + ",next_due_at="
    + literal(due.isoformat())
    + " where id="
    + literal(schedule["id"])
)
schedule = db._call(
    "GET",
    "research_capture_schedules",
    query={"id": "eq." + schedule["id"], "owner_id": "eq." + OWNER, "select": "*", "limit": "1"},
)[0]
first = dispatch_schedule(db, schedule, now)
assert first
prices = {"US.A": 4, "US.B": 7}
build_count = 0


def screen(**kwargs):
    stamp = datetime.now(timezone.utc).isoformat()
    rows = [
        {
            "code": code,
            "stock_type": "STOCK",
            "price": price,
            "quote_identity_status": "verified",
            "quote_cache_at": stamp,
        }
        for code, price in prices.items()
    ]
    return {
        "available": True,
        "universe_loaded": True,
        "universe_as_of": stamp,
        "rows": rows,
        "matched": len(rows),
    }


api.screener = screen


def builder(schedule, cid):
    global build_count
    build_count += 1
    return capture_service.build(schedule, cid)


executor = CaptureExecutor(db, WORKER, builder)
first_result = executor.execute_one()
assert first_result["state"] == "succeeded", first_result
saved = json.loads(
    query("select snapshot from public.research_private_captures where id=" + literal(first["id"]))
)
assert [r["code"] for r in saved["members"]] == ["US.A"] and len(saved["observations"]) == 2


def enqueue(revision):
    oid = str(uuid.uuid4())
    query(
        "insert into public.research_capture_occurrences(id,schedule_id,owner_id,schedule_revision,due_at) values("
        + ",".join(
            map(
                literal,
                [oid, schedule["id"], OWNER, revision, datetime.now(timezone.utc).isoformat()],
            )
        )
        + ")"
    )
    return oid


# Inject one lost response AFTER actual native commit. Same payload retry must confirm.
second = enqueue(1)
prices.update({"US.A": 6, "US.B": 4})
original = db._call
lost = False
publication_requests = []


def transport(method, path, body=None, query=None):
    global lost
    result = original(method, path, body=body, query=query)
    if path == "rpc/research_capture_publish":
        publication_requests.append(json.dumps(body, sort_keys=True))
        if not lost:
            lost = True
            raise OSError("Synthetic lost post-commit response")
    return result


db._call = transport
second_result = executor.execute_one()
assert second_result["state"] == "succeeded", second_result
assert (
    len(publication_requests) == 2
    and publication_requests[0] == publication_requests[1]
    and build_count == 2
)
assert query("select count(*) from public.research_private_captures") == "2"
assert (
    query("select status from public.research_capture_occurrences where id=" + literal(second))
    == "succeeded"
)
# A concurrent edit after actual build must prevent publication.
third = enqueue(1)


def edited(schedule, cid):
    snapshot = builder(schedule, cid)
    query(
        "update public.research_capture_schedules set revision=revision+1 where id="
        + literal(schedule["id"])
    )
    return snapshot


obsolete = CaptureExecutor(db, WORKER, edited).execute_one()
assert obsolete["state"] == "obsolete", obsolete
assert query("select count(*) from public.research_private_captures") == "2"
# Current-revision incomplete-data failure is retryable and publishes nothing.
fourth = enqueue(2)


def incomplete(*args):
    raise HTTPException(409, "Synthetic incomplete source")


failed = CaptureExecutor(db, WORKER, incomplete).execute_one()
assert failed["state"] == "pending", failed
assert (
    query("select status from public.research_capture_occurrences where id=" + literal(third))
    == "cancelled"
)
assert query("select count(*) from public.research_private_captures") == "2"
assert (
    query("select error_code from public.research_capture_occurrences where id=" + literal(fourth))
    == "incomplete_data"
)
result = {
    "database": "capture_executor_qualification",
    "actual_native_claim_renew_read_build_publish": True,
    "first_members": ["US.A"],
    "eligible_observations": 2,
    "post_commit_response_loss_exact_retry": True,
    "builds_for_two_successes": 2,
    "persisted_successful_captures": 2,
    "revision_edit_after_build": "obsolete/no publication",
    "incomplete_data": "pending retry/no publication",
    "previous_success_preserved": True,
    "limits": "Synthetic two-stock source; native SQL transport, not PostgREST, real Auth, real provider or deployed runtime.",
}
Path(__file__).with_name("native-integration-result.json").write_text(
    json.dumps(result, indent=2) + "\n"
)
print(json.dumps(result))
