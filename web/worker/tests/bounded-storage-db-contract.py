"""Disposable native PostgreSQL contract test, never production.

STORAGE_TEST_DSN must point to a local cluster with the three Supabase roles.
"""

import json
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DSN = os.environ["STORAGE_TEST_DSN"]
assert "127.0.0.1" in DSN or "localhost" in DSN, "Local test cluster only"
NAME = "storage_" + uuid.uuid4().hex[:12]
BASE = ["psql", DSN, "-X", "-qAt", "-v", "ON_ERROR_STOP=1"]


def query(sql, db=NAME, error=None):
    args = BASE + ["-d", db]
    # -d database would discard a URI connection option, so pass PGHOST/PGPORT
    # through the isolated test environment and use an explicit local URI.
    args = ["psql", DSN.rsplit("/", 1)[0] + "/" + db, "-X", "-qAt", "-v", "ON_ERROR_STOP=1"]
    p = subprocess.run(args, input=sql, text=True, capture_output=True, timeout=60)
    if error:
        assert p.returncode and error in p.stderr, p.stderr
        return
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def lit(obj):
    return "'" + json.dumps(obj).replace("'", "''") + "'::jsonb"


query("create database " + NAME, "postgres")
try:
    query((ROOT / "web/worker/tests/generation-db-bootstrap.sql").read_text().split("\\ir")[0])
    for name in [
        "20261003105144_screener_generation_publication.sql",
        "20261003114454_screener_screen_publication.sql",
        "20261003120913_screener_bounded_staging.sql",
        "20261003124611_screener_refresh_capacity_guard.sql",
    ]:
        query((ROOT / "supabase/migrations" / name).read_text())
    query("""create table screener_klines(market text,code text,day date,o float8,h float8,l float8,c float8,v float8,primary key(market,code,day));
    create table screener_kline_state(market text,code text,last_fetch timestamptz,bars int,primary key(market,code));
    create table tickers(id uuid primary key,currency text,symbol text,native_symbol text);
    create table watchlist_items(ticker_id uuid,active boolean);
    grant select,insert,update,delete on all tables in schema public to service_role;""")
    query((ROOT / "supabase/migrations/20261010094127_bounded_market_storage.sql").read_text())
    query(
        (ROOT / "supabase/migrations/20261010101615_stored_publication_projection.sql").read_text()
    )
    definition = query(
        "select pg_get_functiondef('screener_refresh_publish_staged(text,uuid,jsonb,jsonb,boolean)'::regprocedure);"
    )
    assert "pg_column_size(payload)" in definition and "greatest(sum(" in definition
    for role in ["anon", "authenticated"]:
        query(
            f"set role {role}; select screener_kline_cache_write('US','US.A','[]');",
            error="permission denied",
        )
        query(f"set role {role}; select screener_storage_retention();", error="permission denied")
    query(
        "set role service_role; insert into screener_klines(market,code,day) values('US','US.A',current_date);",
        error="permission denied",
    )
    query("select screener_storage_check_growth(450000000);", error="Projected database storage")
    for market in ["US", "HK"]:
        token = str(uuid.uuid4())
        code = market + ".A"
        query(f"set role service_role; select screener_refresh_begin('{market}','{token}');")
        capacity = json.loads(
            query(f"select screener_refresh_capacity('{'HK' if market == 'US' else 'US'}');")
        )
        assert capacity["reserved_bytes"] == (150000000 if market == "US" else 50000000)
        assert capacity["used_bytes"] == int(query("select pg_database_size(current_database());"))
        stamp = datetime.now(timezone.utc).isoformat()
        row = {
            "code": code,
            "row": {"code": code, "price": 10, "observation_note": "provider observation;" * 2048},
            "metadata": {"code": code, "market": market, "stock_type": "STOCK", "plates": []},
            "quote_cache_at": stamp,
        }
        query(
            f"set role service_role;select screener_refresh_stage('{market}','{token}',{lit([row])});"
        )
        receipt = {
            "enum": {
                "scope": "exhausted_provider_market_screen",
                "codes": 1,
                "provider_total": 2,
                "pages": 1,
                "skipped_nonconforming": 1,
            }
        }
        bad = json.loads(json.dumps(receipt))
        bad["enum"]["skipped_nonconforming"] = 51
        query(
            f"select screener_refresh_publish_staged('{market}','{token}',{lit([code])},{lit(bad)},true);",
            error="Invalid exhausted screening receipt",
        )
        call = f"set role service_role;select screener_refresh_publish_staged('{market}','{token}',{lit([code])},{lit(receipt)},true);"
        saved = json.loads(query(call))
        assert saved["row_count"] == 1
        assert json.loads(query(call)) == saved  # exact replay remains intact
        query(
            f"delete from screener_generation_rows where generation_id='{token}';",
            error="protected",
        )
        query(
            f"delete from screener_refresh_staged_rows where run_id='{token}';", error="protected"
        )
    rows = [
        {
            "market": "US",
            "code": "US.A",
            "day": (datetime.now(timezone.utc).date() - timedelta(days=i)).isoformat(),
            "o": 10,
            "h": 11,
            "l": 9,
            "c": 10.5,
            "v": 100,
        }
        for i in range(260)
    ]
    call = f"set role service_role;select screener_kline_cache_write('US','US.A',{lit(rows)});"
    assert query(call) == "260"
    assert query(call) == "260"
    assert query("select count(*) from screener_klines;") == "260"
    query(
        f"select screener_kline_cache_write('US','US.A',{lit(rows + [rows[0]])});",
        error="Invalid or oversized",
    )
    outside = [{**r, "code": "US.OLD"} for r in rows]
    assert query(f"select screener_kline_cache_write('US','US.OLD',{lit(outside)});") == "0"
    query("select screener_storage_retention();")
    assert query("select count(*) from screener_generation_rows;") == "2"
    print(
        "PASS native storage migration: skipped receipt publication/replay, role isolation, whole-DB reservations, 260-bar cache, protected retention"
    )
finally:
    query("drop database " + NAME + " with (force)", "postgres")
