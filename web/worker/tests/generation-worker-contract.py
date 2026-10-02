"""Execute the real refresh worker against installed RPCs in isolated PostgreSQL.

Fixed socket/database only; no production arguments/credentials. The adapter
uses native SQL instead of PostgREST: it qualifies worker/SQL integration, not
HTTP/platform/provider coverage. Fixture provider work is read-only synthetic.
"""

import copy
import json
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError

from tradingagents_worker.db import Db
from tradingagents_worker.universe_refresh import UniverseRefresher, UniverseRefreshError

PSQL = [
    "/opt/homebrew/bin/psql",
    "-h",
    "/private/tmp/tradingagent-research-pg",
    "-p",
    "55439",
    "-d",
    "screener_generation_migration_verification",
    "-v",
    "ON_ERROR_STOP=1",
    "-qAt",
]


def query(sql):
    result = subprocess.run(
        PSQL, input="set role service_role;\n" + sql, text=True, capture_output=True, timeout=30
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def text_literal(value):
    return "'" + value.replace("'", "''") + "'"


def sql_literal(value):
    if isinstance(value, (dict, list)):
        return text_literal(json.dumps(value, allow_nan=False)) + "::jsonb"
    if isinstance(value, bool):
        return str(value).lower()
    if value is None:
        return "null"
    if isinstance(value, int):
        return str(value)
    return text_literal(value)


class NativeDb(Db):
    def __init__(self):
        self.calls = []
        self.lose_publish_response = False

    def _call(self, method, path, body=None, **kwargs):
        assert method == "POST" and path.startswith("rpc/screener_refresh_")
        self.calls.append((path, copy.deepcopy(body)))
        args = ",".join(k + " => " + sql_literal(v) for k, v in body.items())
        response = json.loads(query(f"select to_jsonb(public.{path[4:]}({args}));"))
        if path == "rpc/screener_refresh_publish" and self.lose_publish_response:
            self.lose_publish_response = False
            raise URLError("injected response loss AFTER native commit")
        return response

    def select(self, table, params=None, columns="*"):
        assert table in {
            "app_settings",
            "screener_universe",
            "screener_quotes",
            "screener_generations",
            "screener_generation_rows",
        }
        where = []
        suffix = ""
        for key, value in (params or {}).items():
            if key in ("limit", "offset", "order"):
                continue
            assert key in {"id", "key", "market", "code", "generation_id"} and value.startswith(
                "eq."
            )
            where.append(key + "=" + text_literal(value[3:]))
        if (params or {}).get("order"):
            assert params["order"] == "code.asc"
            suffix = ' order by code collate "C"'
        for key in ("limit", "offset"):
            if key in (params or {}):
                suffix += f" {key} {int(params[key])}"
        condition = " where " + " and ".join(where) if where else ""
        return json.loads(
            query(
                f"select coalesce(jsonb_agg(to_jsonb(t)),'[]'::jsonb) from "
                f"(select * from public.{table}{condition}{suffix}) t;"
            )
        )

    def upsert(self, *args, **kwargs):
        raise AssertionError("worker must not write outside fenced RPC")

    def upsert_many(self, *args, **kwargs):
        raise AssertionError("worker must not publish batches")


class Provider:
    def __init__(self, fail=False, supersede=False):
        self.fail = fail
        self.supersede = supersede
        self.snapshots = 0
        self.successor = None

    def call(self, method, path, body=None, query=None, retries=2):
        if path == "/quote/plate-list":
            return {"plate_list": [{"code": "US.TEST", "name": "Synthetic software"}]}
        if path == "/quote/plate-stock":
            return {"stock_list": [{"code": f"US.W{i:04}"} for i in range(401)]}
        if path == "/quote/stock-screen":
            return {"items": []}
        if path == "/quote/stock-basicinfo":
            return {
                "basic_list": [
                    {"code": c, "stock_type": "STOCK", "exchange": "NASDAQ"}
                    for c in body["code_list"]
                ]
            }
        raise AssertionError(path)

    def snapshot(self, codes, retries=2):
        self.snapshots += 1
        if self.supersede:
            self.supersede = False
            query(
                "update public.screener_refresh_leases set expires_at=clock_timestamp()-interval '1 second' where market='US';"
            )
            self.successor = str(uuid.uuid4())
            query(f"select public.screener_refresh_begin('US','{self.successor}');")
        if self.fail and len(codes) == 1:
            return {"snapshot_list": []}
        return {
            "snapshot_list": [
                {
                    "code": c,
                    "name": "Synthetic " + c,
                    "last_price": 12,
                    "prev_close_price": 10,
                    "update_time": int(datetime.now(timezone.utc).timestamp() * 1000),
                }
                for c in codes
            ]
        }


db = NativeDb()
query("""insert into public.screener_universe(market,code,plates,stock_type)
values ('US','US.LEGACY','["Historical"]','STOCK') on conflict do nothing;
insert into public.screener_quotes(code,market,row,updated_at)
values('US.LEGACY','US','{"code":"US.LEGACY","price":99}','2020-01-01T00:00:00Z') on conflict do nothing;
insert into public.app_settings(key,value) values('universe_state_US',
jsonb_build_object('last_enum',clock_timestamp(),'last_quotes','2020-01-01T00:00:00Z','last_result','{}'::jsonb)) on conflict do nothing;""")
before = copy.deepcopy(db.select("screener_quotes"))
old = db.select("app_settings", {"key": "eq.universe_state_US"})[0]["value"]
provider = Provider(fail=True)
try:
    UniverseRefresher(db, provider).run(force_enum=True)
    raise AssertionError("partial provider response succeeded")
except UniverseRefreshError:
    pass
assert db.select("screener_quotes") == before
failed = db.select("app_settings", {"key": "eq.universe_state_US"})[0]["value"]
assert failed["last_quotes"] == old["last_quotes"] and failed["last_enum"] == old["last_enum"]
assert failed["last_attempt"]["status"] == "failed" and provider.snapshots == 2
print(
    "PASS: native worker later-batch failure preserves every legacy quote, enumeration and success",
    flush=True,
)

result = UniverseRefresher(db, Provider()).run(force_enum=True)
assert result["quotes"]["quotes"] == 401 and result["quotes"]["batches"] == 2
state = db.select("app_settings", {"key": "eq.universe_state_US"})[0]["value"]
assert (
    state["generation_id"] == result["generation_id"]
    and state["last_attempt"]["status"] == "succeeded"
)
assert "US.LEGACY" not in UniverseRefresher(db, Provider())._stored_codes()
assert db.select("screener_quotes", {"code": "eq.US.LEGACY"})[0]["row"]["price"] == 99
assert "skipped" in UniverseRefresher(db, Provider()).run()
print(
    "PASS: native worker publishes exact classified 401-row generation; legacy history retained and excluded from new cohort",
    flush=True,
)

db.lose_publish_response = True
provider = Provider()
replayed = UniverseRefresher(db, provider).run(force_enum=True)
calls = [body for path, body in db.calls if path == "rpc/screener_refresh_publish"]
assert calls[-1] == calls[-2] and provider.snapshots == 2
assert len(db.select("screener_generations", {"id": "eq." + replayed["generation_id"]})) == 1
print(
    "PASS: lost native commit response retries the exact payload and creates one generation",
    flush=True,
)

provider = Provider(supersede=True)
try:
    UniverseRefresher(db, provider).run(force_enum=True)
    raise AssertionError("superseded worker succeeded")
except RuntimeError:
    pass
state = db.select("app_settings", {"key": "eq.universe_state_US"})[0]["value"]
assert (
    state["generation_id"] == replayed["generation_id"]
    and state["last_attempt"]["run_id"] == provider.successor
)
assert state["last_attempt"]["status"] == "running"
query(
    f"select public.screener_refresh_abort('US','{provider.successor}','quotes','end isolated successor fixture');"
)
quote_only = UniverseRefresher(db, Provider()).run()
assert "enum" not in quote_only and quote_only["quotes"]["requested"] == 401
print(
    "PASS: real expiry/successor fencing prevents stale publication or failure overwrite; quote-only retry uses pinned metadata",
    flush=True,
)

evidence = {
    "scope": "real worker + native PostgreSQL 16.14 RPCs; synthetic provider; no PostgREST or production qualification",
    "contracts": [
        "later_batch_failure_no_publication",
        "exact_classified_generation_and_retained_history",
        "fresh_pinned_cohort_skip",
        "lost_commit_response_exact_replay",
        "expired_successor_fencing",
        "quote_only_pinned_metadata_retry",
    ],
    "generation_rows": 401,
    "provider_batches": 2,
    "completed_at": datetime.now(timezone.utc).isoformat(),
}
Path("/private/tmp/screener-generation-worker-evidence.json").write_text(
    json.dumps(evidence, indent=2) + "\n"
)
