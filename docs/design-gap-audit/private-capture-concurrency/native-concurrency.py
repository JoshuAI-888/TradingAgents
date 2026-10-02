"""Actual overlapping PostgreSQL workers, in a disposable local database only."""

import json
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from tradingagents_api import capture_service, main, research_schedules

ROOT = Path(__file__).resolve().parents[3]
DB = "capture_concurrency_qualification"
BASE = [
    "/opt/homebrew/opt/postgresql@16/bin/psql",
    "-h",
    "/private/tmp/tradingagent-research-pg",
    "-p",
    "55439",
    "-v",
    "ON_ERROR_STOP=1",
    "-At",
]
OWNER = "00000000-0000-4000-8000-000000000001"
A = str(uuid.uuid4())
B = str(uuid.uuid4())


def sql(text, db=DB):
    return subprocess.run(
        BASE + ["-d", db, "-c", text], capture_output=True, text=True, check=True, timeout=20
    ).stdout.strip()


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


def rpc(name, args):
    return (
        "select coalesce(json_agg(t),'[]'::json) from public."
        + name
        + "("
        + ",".join(k + "=>" + literal(v) for k, v in args.items())
        + ") t;"
    )


def call(name, args):
    return json.loads(sql("set role service_role;" + rpc(name, args)).splitlines()[-1])


def start(name, statement):
    return subprocess.Popen(
        BASE + ["-d", DB, "-c", "set application_name=" + literal(name) + ";" + statement],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def wait_state(name, condition, process):
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        if (
            sql(
                "select count(*) from pg_stat_activity where datname="
                + literal(DB)
                + " and application_name="
                + literal(name)
                + " and "
                + condition
            )
            == "1"
        ):
            return
        if process.poll() is not None:
            raise AssertionError("Expected live overlapping process ended")
        time.sleep(0.02)
    raise AssertionError("Expected overlap was not observed")


def finish(process):
    out, err = process.communicate(timeout=12)
    assert process.returncode == 0, err
    return [json.loads(line) for line in out.splitlines() if line.startswith("[")]


assert sql("select count(*) from pg_database where datname=" + literal(DB), "postgres") == "0", (
    "Disposable database already exists; inspect before running"
)
created = False
processes = []
started = time.monotonic()
try:
    sql("create database " + DB + " template postgres", "postgres")
    created = True
    for migration in [
        "20261002102231_private_capture_schedules.sql",
        "20261002103206_private_capture_occurrences.sql",
        "20261002103538_private_capture_leases.sql",
        "20261002103911_private_capture_publication.sql",
    ]:
        subprocess.run(
            BASE + ["-d", DB, "-f", str(ROOT / "supabase/migrations" / migration)],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        )
    definition, digest = research_schedules._definition(
        {"market": "US", "filters": [{"field": "price", "max": 5}]}
    )
    sid = str(uuid.uuid4())
    oid = str(uuid.uuid4())
    sql(
        "insert into public.research_capture_schedules(id,owner_id,definition_hash,definition,name,cadence,enabled,activated_at,next_due_at) values("
        + ",".join(
            map(
                literal,
                [
                    sid,
                    OWNER,
                    digest,
                    definition,
                    "Concurrent native qualification",
                    {"timezone": "UTC", "hour": 16, "minute": 0, "weekdays": [0, 1, 2, 3, 4]},
                ],
            )
        )
        + ",true,clock_timestamp()-interval '1 day',clock_timestamp()+interval '1 day')"
    )
    sql(
        "insert into public.research_capture_occurrences(id,schedule_id,owner_id,schedule_revision,due_at) values("
        + ",".join(map(literal, [oid, sid, OWNER]))
        + ",1,clock_timestamp())"
    )
    first = start(
        "capture_claim_one",
        "begin;set local role service_role;"
        + rpc("research_capture_claim", {"p_worker": A})
        + "select pg_sleep(2);commit;",
    )
    processes.append(first)
    wait_state("capture_claim_one", "wait_event='PgSleep'", first)
    second = start(
        "capture_claim_two",
        "set role service_role;" + rpc("research_capture_claim", {"p_worker": B}),
    )
    processes.append(second)
    second_rows = finish(second)
    first_rows = finish(first)
    assert second_rows == [[]] and len(first_rows) == 1 and len(first_rows[0]) == 1, (
        first_rows,
        second_rows,
    )
    claim = first_rows[0][0]
    assert claim["id"] == oid and claim["attempts"] == 1
    assert call("research_capture_claim", {"p_worker": B}) == []
    # Model a crashed worker whose durable lease expires; no elapsed-clock guess.
    sql(
        "update public.research_capture_occurrences set lease_until=clock_timestamp()-interval '1 second' where id="
        + literal(oid)
    )
    recovered = call("research_capture_claim", {"p_worker": B})[0]
    assert (
        recovered["id"] == oid
        and recovered["attempts"] == 2
        and recovered["lease_token"] != claim["lease_token"]
    )
    old = {"p_occurrence": oid, "p_worker": A, "p_token": claim["lease_token"]}
    assert call("research_capture_renew", old) == []
    assert (
        call("research_capture_fail", {**old, "p_error": "worker_interrupted", "p_retryable": True})
        == []
    )
    stamp = datetime.now(timezone.utc).isoformat()
    main.screener = lambda **kw: {
        "available": True,
        "universe_loaded": True,
        "universe_as_of": stamp,
        "matched": 2,
        "rows": [
            {
                "code": c,
                "stock_type": "STOCK",
                "price": p,
                "quote_identity_status": "verified",
                "quote_cache_at": stamp,
            }
            for c, p in [("US.A", 4), ("US.B", 7)]
        ],
    }
    parent = json.loads(
        sql(
            "select row_to_json(s) from public.research_capture_schedules s where id="
            + literal(sid)
        )
    )
    snapshot = capture_service.build(parent, oid)
    assert call("research_capture_publish", {**old, "p_snapshot": snapshot}) == []
    current = {
        "p_occurrence": oid,
        "p_worker": B,
        "p_token": recovered["lease_token"],
        "p_snapshot": snapshot,
    }
    pub1 = start(
        "capture_pub_one",
        "begin;set local role service_role;"
        + rpc("research_capture_publish", current)
        + "select pg_sleep(2);commit;",
    )
    processes.append(pub1)
    wait_state("capture_pub_one", "wait_event='PgSleep'", pub1)
    pub2 = start(
        "capture_pub_two", "set role service_role;" + rpc("research_capture_publish", current)
    )
    processes.append(pub2)
    wait_state("capture_pub_two", "wait_event_type='Lock'", pub2)
    published1 = finish(pub1)
    published2 = finish(pub2)
    assert published1[0][0]["id"] == published2[0][0]["id"] == oid
    assert sql("select count(*) from public.research_private_captures") == "1"
    assert (
        sql("select status from public.research_capture_occurrences where id=" + literal(oid))
        == "succeeded"
    )
    # The configuration transaction must win before a waiting stale publication.
    next_oid = str(uuid.uuid4())
    sql(
        "insert into public.research_capture_occurrences(id,schedule_id,owner_id,schedule_revision,due_at) values("
        + ",".join(map(literal, [next_oid, sid, OWNER]))
        + ",1,clock_timestamp())"
    )
    next_claim = call("research_capture_claim", {"p_worker": B})[0]
    assert next_claim["id"] == next_oid
    next_snapshot = capture_service.build(parent, next_oid)
    edit_args = {
        "p_owner": OWNER,
        "p_hash": digest,
        "p_revision": 1,
        "p_definition": definition,
        "p_name": "Disabled during publication",
        "p_cadence": parent["cadence"],
        "p_enabled": False,
        "p_next": None,
    }
    edit1 = start(
        "capture_edit_one",
        "begin;set local role service_role;"
        + rpc("research_capture_schedule_save", edit_args)
        + "select pg_sleep(2);commit;",
    )
    processes.append(edit1)
    wait_state("capture_edit_one", "wait_event='PgSleep'", edit1)
    stale_args = {
        "p_occurrence": next_oid,
        "p_worker": B,
        "p_token": next_claim["lease_token"],
        "p_snapshot": next_snapshot,
    }
    stale = start(
        "capture_pub_after_edit",
        "set role service_role;" + rpc("research_capture_publish", stale_args),
    )
    processes.append(stale)
    wait_state("capture_pub_after_edit", "wait_event_type='Lock'", stale)
    edit_rows = finish(edit1)
    stale_rows = finish(stale)
    assert (
        edit_rows[0][0]["revision"] == 2
        and edit_rows[0][0]["enabled"] is False
        and stale_rows == [[]]
    )
    assert (
        call("research_capture_renew", {k: v for k, v in stale_args.items() if k != "p_snapshot"})
        == []
    )
    assert call("research_capture_claim", {"p_worker": A}) == []
    assert (
        sql("select status from public.research_capture_occurrences where id=" + literal(next_oid))
        == "cancelled"
    )
    assert sql("select count(*) from public.research_private_captures") == "1"
    result = {
        "database": DB,
        "overlapping_claim_transactions_observed": True,
        "second_claim_skipped_live_schedule": True,
        "live_lease_not_reclaimed": True,
        "expired_lease_reclaimed_same_occurrence": True,
        "recovered_attempt": 2,
        "fresh_token": True,
        "stale_worker_renew_fail_publish_rejected": True,
        "publication_contender_observed_waiting_for_lock": True,
        "same_capture_confirmed_by_both_publishers": True,
        "persisted_captures": 1,
        "schedule_edit_lock_overlap_observed": True,
        "waiting_publication_after_disable_rejected": True,
        "obsolete_occurrence_cancelled": True,
        "prior_success_preserved": True,
        "actual_builder_members": ["US.A"],
        "synthetic_eligible_observations": 2,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "limits": "Native PostgreSQL processes and actual builder with synthetic two-stock source. Forced lease expiry models a crash; not an actual deployed worker restart, PostgREST, real Auth, market coverage or provider qualification.",
    }
finally:
    for process in processes:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=5)
    if created:
        sql("drop database " + DB, "postgres")
result["disposable_database_removed"] = True
Path(__file__).with_name("native-concurrency-result.json").write_text(
    json.dumps(result, indent=2) + "\n"
)
print(json.dumps(result))
