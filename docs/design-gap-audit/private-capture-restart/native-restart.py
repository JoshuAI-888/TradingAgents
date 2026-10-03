"""Kill/restart actual CaptureExecutor processes and await real lease expiry locally."""

import json
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from tradingagents_api import capture_service, main, research_schedules
from tradingagents_worker.capture_executor import CaptureExecutor

ROOT = Path(__file__).resolve().parents[3]
DB = "capture_restart_qualification"
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


def sql(text, db=DB):
    p = subprocess.run(BASE + ["-d", db, "-c", text], capture_output=True, text=True, timeout=20)
    if p.returncode:
        raise RuntimeError(p.stderr.strip())
    return p.stdout.strip()


class NativeDb:
    def _call(self, method, path, body=None, query=None):
        if path.startswith("rpc/"):
            name = path[4:]
            assert name in {
                "research_capture_claim",
                "research_capture_renew",
                "research_capture_fail",
                "research_capture_publish",
            }
            statement = (
                "select coalesce(json_agg(t),'[]'::json) from public."
                + name
                + "("
                + ",".join(k + "=>" + literal(v) for k, v in body.items())
                + ") t"
            )
        else:
            assert (
                method == "GET"
                and path == "research_capture_schedules"
                and set(query) == {"id", "owner_id", "select", "limit"}
            )
            sid = str(uuid.UUID(query["id"][3:]))
            owner = str(uuid.UUID(query["owner_id"][3:]))
            statement = (
                "select coalesce(json_agg(t),'[]'::json) from (select * from public.research_capture_schedules where id="
                + literal(sid)
                + " and owner_id="
                + literal(owner)
                + " limit 1) t"
            )
        return json.loads(sql("set role service_role;" + statement).splitlines()[-1])


def worker(config):
    def build(schedule, cid):
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
        snapshot = capture_service.build(schedule, cid)
        if config.get("barrier"):
            Path(config["barrier"]).write_text(json.dumps({"occurrence_id": cid, "built": True}))
            while True:
                time.sleep(1)
        return snapshot

    print(
        json.dumps(CaptureExecutor(NativeDb(), config["worker_id"], build).execute_one()),
        flush=True,
    )


if len(sys.argv) > 1 and sys.argv[1] == "--worker":
    worker(json.loads(Path(sys.argv[2]).read_text()))
    sys.exit(0)
assert sql("select count(*) from pg_database where datname=" + literal(DB), "postgres") == "0", (
    "Existing disposable DB requires inspection"
)
created = False
children = []
started = time.monotonic()
with tempfile.TemporaryDirectory(prefix="capture-restart-") as temp:

    def launch(config):
        path = Path(temp) / (str(uuid.uuid4()) + ".json")
        path.write_text(json.dumps(config))
        child = subprocess.Popen(
            [sys.executable, __file__, "--worker", str(path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        children.append(child)
        return child

    def finish(child):
        out, err = child.communicate(timeout=25)
        assert child.returncode == 0, err
        return json.loads(out.strip())

    try:
        sql("create database " + DB + " template postgres", "postgres")
        created = True
        for migration in [
            "20261002102231_private_capture_schedules.sql",
            "20261002103206_private_capture_occurrences.sql",
            "20261002103538_private_capture_leases.sql",
            "20261002103911_private_capture_publication.sql",
        ]:
            p = subprocess.run(
                BASE + ["-d", DB, "-f", str(ROOT / "supabase/migrations" / migration)],
                capture_output=True,
                text=True,
                timeout=20,
            )
            assert p.returncode == 0, p.stderr
        definition, digest = research_schedules._definition(
            {"market": "US", "filters": [{"field": "price", "max": 5}]}
        )
        sid = str(uuid.uuid4())
        sql(
            "insert into public.research_capture_schedules(id,owner_id,definition_hash,definition,name,cadence,enabled,next_due_at) values("
            + ",".join(
                map(
                    literal,
                    [
                        sid,
                        OWNER,
                        digest,
                        definition,
                        "Process restart qualification",
                        {"timezone": "UTC", "hour": 16, "minute": 0, "weekdays": [0, 1, 2, 3, 4]},
                    ],
                )
            )
            + ",true,clock_timestamp()+interval '1 day')"
        )

        def enqueue():
            oid = str(uuid.uuid4())
            sql(
                "insert into public.research_capture_occurrences(id,schedule_id,owner_id,schedule_revision,due_at) values("
                + ",".join(map(literal, [oid, sid, OWNER]))
                + ",1,clock_timestamp())"
            )
            return oid

        prior = enqueue()
        baseline = finish(launch({"worker_id": str(uuid.uuid4())}))
        assert baseline == {"occurrence_id": prior, "state": "succeeded"}
        crashed_id = enqueue()
        barrier = Path(temp) / "built.json"
        crashed = launch({"worker_id": str(uuid.uuid4()), "barrier": str(barrier)})
        deadline = time.monotonic() + 15
        while not barrier.exists():
            assert crashed.poll() is None, "Worker terminated before build barrier"
            assert time.monotonic() < deadline, "Build barrier timed out"
            time.sleep(0.05)
        assert json.loads(barrier.read_text()) == {"occurrence_id": crashed_id, "built": True}
        before = json.loads(
            sql(
                "select row_to_json(o) from public.research_capture_occurrences o where id="
                + literal(crashed_id)
            )
        )
        assert before["status"] == "running" and before["attempts"] == 1 and crashed.poll() is None
        crashed.kill()
        crashed.communicate(timeout=10)
        assert crashed.returncode == -9
        assert sql("select count(*) from public.research_private_captures") == "1"
        early = finish(launch({"worker_id": str(uuid.uuid4())}))
        assert early == {"state": "idle"}
        print(
            json.dumps(
                {
                    "progress": "confirmed killed worker; waiting for unmodified durable lease expiry",
                    "early_restart": "idle",
                    "prior_captures": 1,
                }
            ),
            flush=True,
        )
        # The SQL expiry clock is authoritative. Never shorten/update the lease.
        deadline = time.monotonic() + 135
        last_notice = time.monotonic()
        while (
            sql(
                "select lease_until>clock_timestamp() from public.research_capture_occurrences where id="
                + literal(crashed_id)
            )
            == "t"
        ):
            assert time.monotonic() < deadline, "Actual lease failed to expire"
            if time.monotonic() - last_notice >= 20:
                print(
                    json.dumps(
                        {
                            "progress": "lease still live; prior capture retained",
                            "wait_seconds": round(time.monotonic() - started),
                        }
                    ),
                    flush=True,
                )
                last_notice = time.monotonic()
            time.sleep(0.5)
        recovery = finish(launch({"worker_id": str(uuid.uuid4())}))
        assert recovery == {"occurrence_id": crashed_id, "state": "succeeded"}, recovery
        after = json.loads(
            sql(
                "select row_to_json(o) from public.research_capture_occurrences o where id="
                + literal(crashed_id)
            )
        )
        assert after["status"] == "succeeded" and after["attempts"] == 2
        assert sql("select count(*) from public.research_private_captures") == "2"
        assert (
            sql(
                "select count(*) from public.research_private_captures where id="
                + literal(crashed_id)
            )
            == "1"
        )
        assert (
            sql("select count(*) from public.research_private_captures where id=" + literal(prior))
            == "1"
        )
        duplicate = finish(launch({"worker_id": str(uuid.uuid4())}))
        assert duplicate == {"state": "idle"}
        result = {
            "database": DB,
            "worker_killed_after_actual_build": True,
            "process_exit_code": -9,
            "immediate_restart": "idle/live lease preserved",
            "lease_expiry": "actual 120 seconds; never modified",
            "restart_result": "same occurrence succeeded",
            "recovered_attempt": 2,
            "new_capture_rows": 1,
            "total_capture_rows": 2,
            "prior_success_preserved": True,
            "subsequent_restart": "idle/no duplicate",
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "limits": "Actual CaptureExecutor subprocess crash/restart and native PostgreSQL; synthetic two-stock provider/store transport. Not deployed service, PostgREST, real Auth or financial/provider qualification.",
        }
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)
        if created:
            sql("drop database " + DB, "postgres")
result["disposable_database_removed"] = True
Path(__file__).with_name("native-restart-result.json").write_text(
    json.dumps(result, indent=2) + "\n"
)
print(json.dumps(result), flush=True)
