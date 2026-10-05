"""Native generation storage/fencing contracts. ISOLATED LOCAL DATABASE ONLY.

Requires generation-db-bootstrap.sql installed in the fixed disposable database.
No production URL/connection arguments or secrets accepted. Uses native psql,
including two simultaneously live sessions to prove locking/MVCC visibility.
This is not a fake RPC model or live provider/PostgREST qualification.
"""

import copy
import hashlib
import json
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

PSQL = [
    "/opt/homebrew/bin/psql",
    "-h",
    "/private/tmp/tradingagent-research-pg",
    "-p",
    "55439",
    "-d",
    "screener_generation_contract",
    "-v",
    "ON_ERROR_STOP=1",
    "-qAt",
]
EVIDENCE = {"database": "isolated PostgreSQL", "contracts": []}


def query(sql, role="service_role", fail=None):
    out = subprocess.run(
        PSQL, input=f"SET ROLE {role};\n" + sql, text=True, capture_output=True, timeout=30
    )
    if fail:
        assert out.returncode != 0 and fail in out.stderr, out.stderr
        return
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def literal(value):
    return (
        "'"
        + json.dumps(value, allow_nan=False, separators=(",", ":")).replace("'", "''")
        + "'::jsonb"
    )


def begin(market="US", token=None):
    token = token or str(uuid.uuid4())
    receipt = json.loads(query(f"select public.screener_refresh_begin('{market}','{token}');"))
    assert receipt["run_id"] == token and receipt["market"] == market
    return token, receipt


def rows(market="US", count=2, price=10):
    stamp = datetime.now(timezone.utc).isoformat()
    return [
        {
            "code": f"{market}.S{i:05}",
            "row": {
                "code": f"{market}.S{i:05}",
                "price": price,
                "quote_observed_at": "2020-01-01T00:00:00Z",
            },
            "metadata": {
                "code": f"{market}.S{i:05}",
                "market": market,
                "name": "Company '" + str(i),
                "stock_type": "STOCK",
                "exchange": "NASDAQ" if market == "US" else "HKEX",
                "plate": "Software",
                "plates": ["Software", "Growth"],
            },
            "quote_cache_at": stamp,
        }
        for i in range(count)
    ]


def publish_sql(token, items, market="US", codes=None, result=None, enumerated=False):
    codes = [r["code"] for r in items] if codes is None else codes
    return (
        f"select public.screener_refresh_publish('{market}','{token}',{literal(codes)},"
        f"{literal(items)},{literal(result or {})},{str(enumerated).lower()});"
    )


def state(market="US"):
    return json.loads(
        query(f"select value from public.app_settings where key='universe_state_{market}';")
    )


def mark(name):
    EVIDENCE["contracts"].append(name)
    print("PASS:", name, flush=True)


def actor(sql, name):
    process = subprocess.Popen(
        PSQL, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    process.stdin.write(f"set application_name='{name}'; set role service_role; begin;\n" + sql)
    process.stdin.close()
    return process


def observe(name, event):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        live = query(
            f"select count(*) from pg_catalog.pg_stat_activity where "
            f"application_name='{name}' and wait_event='{event}';",
            role="joshmini",
        )
        if live == "1":
            return
        time.sleep(0.03)
    raise AssertionError(f"No live session observed: {name}/{event}")


def finish(process, failure=None):
    process.wait(timeout=10)
    stdout, stderr = process.stdout.read(), process.stderr.read()
    if failure:
        assert process.returncode != 0 and failure in stderr, stderr
    else:
        assert process.returncode == 0, stderr
    return stdout


# Assert actual catalog grants/RLS/function execution access, not SQL text.
query(
    """do $$ declare t text; f text; begin
  foreach t in array array['screener_refresh_runs','screener_generations','screener_generation_rows','screener_refresh_leases'] loop
    assert (select relrowsecurity from pg_class where oid=('public.'||t)::regclass);
    assert not has_table_privilege('anon','public.'||t,'SELECT');
    assert not has_table_privilege('authenticated','public.'||t,'INSERT');
    assert not has_table_privilege('service_role','public.'||t,'DELETE');
    assert not has_table_privilege('service_role','public.'||t,'TRUNCATE');
  end loop;
  foreach t in array array['screener_refresh_runs','screener_generations','screener_generation_rows'] loop
    assert not has_table_privilege('service_role','public.'||t,'UPDATE');
  end loop;
  foreach f in array array['screener_refresh_begin(text,uuid,integer)','screener_refresh_renew(text,uuid,integer)',
    'screener_refresh_publish(text,uuid,jsonb,jsonb,jsonb,boolean)','screener_refresh_abort(text,uuid,text,text)'] loop
    assert not has_function_privilege('anon','public.'||f,'EXECUTE');
    assert not has_function_privilege('authenticated','public.'||f,'EXECUTE');
    assert has_function_privilege('service_role','public.'||f,'EXECUTE');
    assert not (select prosecdef from pg_proc where oid=('public.'||f)::regprocedure);
  end loop;
end $$;""",
    role="joshmini",
)
query(
    "select public.screener_refresh_begin('US',gen_random_uuid());",
    role="anon",
    fail="permission denied",
)
mark("RLS and service-only invoker functions; no anonymous/private-role access")

query(
    "insert into public.app_settings(key,value) values('universe_state', '{\"interval_h\":4}') on conflict(key) do nothing;"
)
token, first = begin()
assert json.loads(query(f"select public.screener_refresh_begin('US','{token}');")) == first
query("select public.screener_refresh_begin('US',gen_random_uuid());", fail="already owns")
query(f"select public.screener_refresh_renew('US','{uuid.uuid4()}');", fail="expired or superseded")
assert query(f"select public.screener_refresh_renew('US','{token}');")
items = rows()
receipt = json.loads(query(publish_sql(token, items)))
assert receipt["row_count"] == 2 and state()["generation_id"] == token
fingerprint = hashlib.sha256("\n".join(sorted(r["code"] for r in items)).encode()).hexdigest()
assert receipt["cohort_fingerprint"] == fingerprint
assert receipt["result"]["quotes"]["requested"] == 2
assert json.loads(query(publish_sql(token, items))) == receipt
assert (
    query("select value->>'interval_h' from public.app_settings where key='universe_state';") == "4"
)
assert (
    query(
        f"select row->>'quote_observed_at' from public.screener_generation_rows where generation_id='{token}' limit 1;"
    )
    == "2020-01-01T00:00:00Z"
)
mark(
    "Exact publication/replay, Python cohort hash, separate source/cache clocks and preserved cadence"
)
changed = copy.deepcopy(items)
changed[0]["row"]["price"] = 11
query(publish_sql(token, changed), fail="Conflicting replay")
query(
    f"select public.screener_refresh_begin('US','{token}');", fail="finished, expired or superseded"
)
for table in ["screener_refresh_runs", "screener_generations", "screener_generation_rows"]:
    column = "generation_id" if table.endswith("_rows") else "id"
    query(f"delete from public.{table} where {column}='{token}';", fail="permission denied")
    query(
        f"update public.{table} set {column}={column} where {column}='{token}';",
        role="joshmini",
        fail="immutable",
    )
    query(
        f"delete from public.{table} where {column}='{token}';", role="joshmini", fail="immutable"
    )
    query(f"truncate public.{table} cascade;", role="joshmini", fail="immutable")
mark("Conflicting replay, token reuse and update/delete/truncate immutability safeguards")

bad_token, _ = begin()
assert json.loads(query(publish_sql(token, items))) == receipt
assert state()["last_attempt"]["run_id"] == bad_token
good = rows()
variants = []
for key, value in [
    ("code", "HK.BAD"),
    ("quote_cache_at", "2026-10-02T01:00:00"),
    ("quote_cache_at", "2020-01-01T00:00:00Z"),
    ("quote_cache_at", (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()),
]:
    bad = copy.deepcopy(good)
    bad[0][key] = value
    variants.append(bad)
bad = copy.deepcopy(good)
bad[0]["row"]["code"] = "US.UNRELATED"
variants.append(bad)
bad = copy.deepcopy(good)
bad[0]["metadata"]["stock_type"] = ""
variants.append(bad)
bad = copy.deepcopy(good)
bad[0]["metadata"]["plates"] = [{}]
variants.append(bad)
bad = copy.deepcopy(good)
bad[0]["metadata"]["market"] = "HK"
variants.append(bad)
bad = copy.deepcopy(good)
bad[0]["metadata"]["exchange"] = {}
variants.append(bad)
bad = copy.deepcopy(good)
bad[1] = bad[0]
variants.append(bad)
baseline = state()["last_quotes"]
for bad in variants:
    query(publish_sql(bad_token, bad), fail="ERROR:")
    assert query(f"select count(*) from public.screener_generations where id='{bad_token}';") == "0"
    assert state()["generation_id"] == token and state()["last_quotes"] == baseline
query(publish_sql(bad_token, good, codes=["US.S00000"]), fail="Incomplete")
query(publish_sql(bad_token, good, codes=["US.S00000", "US.S00000"]), fail="duplicate requested")
query(
    publish_sql(bad_token, good, result={"enum": {"codes": 999}}, enumerated=True),
    fail="enumeration receipt",
)
assert (
    query(
        f"select public.screener_refresh_abort('US','{bad_token}','quotes','provider batch missing identity');"
    )
    == "t"
)
assert state()["last_attempt"]["status"] == "failed" and state()["generation_id"] == token
assert (
    query(f"select public.screener_refresh_abort('US','{bad_token}','quotes','late failure');")
    == "f"
)
mark(
    "Malformed/duplicate/missing identities and bad clocks/classification roll back; abort preserves last success"
)

# Superseded owners cannot renew, publish or overwrite newer attempt/success.
expired, _ = begin()
expired_rows = rows()
query(
    "update public.screener_refresh_leases set expires_at=clock_timestamp()-interval '1 second' where market='US';"
)
successor, _ = begin()
new_state = state()
query(f"select public.screener_refresh_renew('US','{expired}');", fail="expired or superseded")
query(publish_sql(expired, expired_rows), fail="expired or superseded")
assert query(f"select public.screener_refresh_abort('US','{expired}','quotes','old owner');") == "f"
assert state() == new_state
query(f"select public.screener_refresh_abort('US','{successor}','quotes','end fixture');")
mark("Expired/superseded owner fencing prevents late publication and failure-state corruption")

abandoned, _ = begin()
query(
    "update public.screener_refresh_leases set expires_at=clock_timestamp()-interval '1 second' where market='US';"
)
query(f"select public.screener_refresh_renew('US','{abandoned}');", fail="expired or superseded")
assert (
    query(
        f"select public.screener_refresh_abort('US','{abandoned}','quotes','lease expired before publication');"
    )
    == "t"
)
assert state()["last_attempt"]["status"] == "failed" and state()["generation_id"] == token
mark("Expired unsuperseded owner can record failure without renewing or advancing success")

# Real concurrent acquisition: owner holds uncommitted lease, contender blocks.
owner = str(uuid.uuid4())
contender = str(uuid.uuid4())
p1 = actor(
    f"select public.screener_refresh_begin('US','{owner}'); select pg_sleep(1.5); commit;",
    "generation-acquire-owner",
)
observe("generation-acquire-owner", "PgSleep")
p2 = actor(
    f"select public.screener_refresh_begin('US','{contender}'); commit;",
    "generation-acquire-contender",
)
observe("generation-acquire-contender", "advisory")
hk, _ = begin("HK")
hk_rows = rows("HK")
assert json.loads(query(publish_sql(hk, hk_rows, "HK")))["row_count"] == 2
finish(p1)
finish(p2, "already owns")
assert state()["last_attempt"]["run_id"] == owner
query(f"select public.screener_refresh_abort('US','{owner}','quotes','end concurrent fixture');")
mark("Observed two-session same-market serialization; HK publication remains independent")

# Atomic MVCC publication: before commit readers see old pointer/rows/mirrors;
# after commit new pointer; paged reads pinned to the old ID remain unchanged.
new, _ = begin()
large = rows(count=1201, price=42)
old_page = query(
    f"select code from public.screener_generation_rows where generation_id='{token}' order by code;"
)
p = actor(publish_sql(new, large) + " select pg_sleep(1.5); commit;", "generation-publish-owner")
observe("generation-publish-owner", "PgSleep")
assert state()["generation_id"] == token
assert (
    query(f"select count(*) from public.screener_generation_rows where generation_id='{new}';")
    == "0"
)
assert query("select row->>'price' from public.screener_quotes where code='US.S00000';") == "10"
finish(p)
assert state()["generation_id"] == new
assert (
    query(f"select count(*) from public.screener_generation_rows where generation_id='{new}';")
    == "1201"
)
assert (
    query(
        f"select code from public.screener_generation_rows where generation_id='{token}' order by code;"
    )
    == old_page
)
assert query("select row->>'price' from public.screener_quotes where code='US.S00000';") == "42"
mark("Observed atomic pointer/rows/mirror visibility and immutable old-generation paged reads")

# An actual error after header/row inserts must roll everything back, including
# mirror writes and the success pointer (not merely reject before any insert).
failure, _ = begin()
failed_rows = rows(price=77)
query(
    """create function public.fixture_reject_quote() returns trigger language plpgsql as $$
begin raise exception 'injected mirror failure'; end $$;
create trigger fixture_reject_quote before insert on public.screener_quotes
for each statement execute function public.fixture_reject_quote();""",
    role="joshmini",
)
query(publish_sql(failure, failed_rows), fail="injected mirror failure")
assert state()["generation_id"] == new
assert query(f"select count(*) from public.screener_generations where id='{failure}';") == "0"
assert (
    query(f"select count(*) from public.screener_generation_rows where generation_id='{failure}';")
    == "0"
)
assert query("select row->>'price' from public.screener_quotes where code='US.S00000';") == "42"
query(
    "drop trigger fixture_reject_quote on public.screener_quotes; drop function public.fixture_reject_quote();",
    role="joshmini",
)
query(
    f"select public.screener_refresh_abort('US','{failure}','publication','injected mirror failure');"
)
mark("Injected post-insert mirror error rolls back generation rows/header/pointer and all mirrors")

# Qualified maximum count and bounded JSON payload on native PostgreSQL.
maximum, _ = begin()
max_rows = rows(count=20000, price=88)
size = len(json.dumps(max_rows).encode())
started = time.monotonic()
max_receipt = json.loads(query(publish_sql(maximum, max_rows)))
elapsed = time.monotonic() - started
assert max_receipt["row_count"] == 20000
assert (
    query(f"select count(*) from public.screener_generation_rows where generation_id='{maximum}';")
    == "20000"
)
EVIDENCE["maximum_fixture"] = {
    "rows": 20000,
    "json_bytes": size,
    "native_publication_seconds": round(elapsed, 3),
    "scope": "local database/storage only; excludes HTTP/PostgREST, provider work and real-device p95",
}
mark("Native 20,000-row generation publication succeeds; no reader truncation at storage boundary")
assert (
    query(
        f"select count(*) from public.screener_generation_rows where generation_id='{maximum}' and code>'US.S00999';"
    )
    == "19000"
)
overflow, _ = begin()
query(publish_sql(overflow, rows(count=20001)), fail="oversized")
query(
    f"select public.screener_refresh_abort('US','{overflow}','quotes','qualified row cap exceeded');"
)
assert state()["generation_id"] == maximum
mark("20,001-row input fails closed and preserves the published generation")
saved_state = state()
query("update public.app_settings set value='[]'::jsonb where key='universe_state_US';")
query(
    "select public.screener_refresh_begin('US',gen_random_uuid());",
    fail="Invalid stored market refresh state",
)
query(f"update public.app_settings set value={literal(saved_state)} where key='universe_state_US';")
assert state() == saved_state
for market, duration in [("ASX", "900"), ("US", "29"), ("US", "901"), ("US", "null")]:
    query(
        f"select public.screener_refresh_begin('{market}',gen_random_uuid(),{duration});",
        fail="Invalid screener refresh lease request",
    )
mark("Malformed persisted state and invalid market/lease parameters fail before acquisition")
EVIDENCE["postgres_version"] = query("show server_version;", role="joshmini")
EVIDENCE["completed_at"] = datetime.now(timezone.utc).isoformat()
Path("/private/tmp/screener-generation-contract-evidence.json").write_text(
    json.dumps(EVIDENCE, indent=2)
)
print(json.dumps(EVIDENCE["maximum_fixture"]), flush=True)
