"""Rehearse screened publication in disposable local PostgreSQL only."""

import json
import pathlib
import subprocess
import time
import uuid
from datetime import datetime, timezone

root = pathlib.Path(__file__).resolve().parents[3]
base = [
    "/opt/homebrew/opt/postgresql@16/bin/psql",
    "-X",
    "-h",
    "/private/tmp/tradingagent-research-pg",
    "-p",
    "55439",
    "-qAt",
    "-v",
    "ON_ERROR_STOP=1",
]


def q(s, db="postgres"):
    r = subprocess.run(base + ["-d", db], input=s, text=True, capture_output=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


q("""do $$ begin
if not exists(select 1 from pg_roles where rolname='anon') then create role anon; end if;
if not exists(select 1 from pg_roles where rolname='authenticated') then create role authenticated; end if;
if not exists(select 1 from pg_roles where rolname='service_role') then create role service_role bypassrls; end if;
end $$;""")
db = "publication_screen_" + uuid.uuid4().hex[:12]
q("create database " + db)
q((root / "web/worker/tests/generation-db-bootstrap.sql").read_text().split("\\ir")[0], db)
q((root / "supabase/migrations/20261003105144_screener_generation_publication.sql").read_text(), db)
q((root / "supabase/migrations/20261003114454_screener_screen_publication.sql").read_text(), db)
run = str(uuid.uuid4())
q(f"set role service_role;select screener_refresh_begin('US','{run}');", db)

stamp = datetime.now(timezone.utc).isoformat()
n = 9421
rows = [
    {
        "code": f"US.S{i}",
        "row": {"code": f"US.S{i}", **{f"field{k}": i + 0.1 for k in range(90)}},
        "metadata": {"code": f"US.S{i}", "market": "US", "stock_type": "STOCK", "plates": []},
        "quote_cache_at": stamp,
    }
    for i in range(n)
]
codes = [r["code"] for r in rows]


def lit(x):
    return "'" + json.dumps(x, separators=(",", ":")).replace("'", "''") + "'::jsonb"


sql = f"set role service_role;select screener_refresh_publish('US','{run}',{lit(codes)},{lit(rows)},{lit({'enum': {'scope': 'exhausted_provider_market_screen', 'codes': n, 'provider_total': n, 'pages': 32}})},true);"
bad_sql = sql.replace('"provider_total":9421', '"provider_total":9420')
bad = subprocess.run(base + ["-d", db], input=bad_sql, text=True, capture_output=True, timeout=60)
assert bad.returncode != 0 and "Invalid exhausted screening receipt" in bad.stderr
assert q("select count(*) from screener_generations;", db) == "0"
t = time.monotonic()
receipt = json.loads(q(sql, db))
secs = time.monotonic() - t
assert receipt["row_count"] == n
assert json.loads(q(sql, db)) == receipt
assert q("select count(*) from screener_generation_rows;", db) == str(n)
assert (
    q(
        "select prosecdef::text || ':' || has_function_privilege('anon',oid,'EXECUTE')::text from pg_proc where proname='screener_refresh_publish';",
        db,
    )
    == "false:false"
)
print(
    json.dumps(
        {
            "scope": "Isolated PostgreSQL synthetic cohort; not provider/platform qualification",
            "rows": n,
            "seconds": round(secs, 2),
            "same_payload_replay": True,
            "invoker_browser_denied": True,
        }
    )
)
q("drop database " + db + " with (force);")
