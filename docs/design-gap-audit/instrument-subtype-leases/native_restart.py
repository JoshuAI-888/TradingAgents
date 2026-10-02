"""Actual runner SIGKILL and natural fixed lease expiry; disposable native DB.

Only lease/cache are native here; universe metadata and provider transport are
controlled fixtures. No live vendor, Auth, PostgREST or generation claim.
"""

import json
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from tradingagents_worker.instrument_subtype_job import run
from tradingagents_worker.instrument_subtype_store import claim, publish, read_cache, release
from tradingagents_worker.instrument_subtypes import collect

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent
PSQL = "/opt/homebrew/opt/postgresql@16/bin/psql"
BASE = "postgresql://joshmini@localhost/{database}?host=%2Fprivate%2Ftmp%2Ftradingagent-research-pg&port=55439"
METADATA = [
    {
        "code": "US.PLD",
        "market": "US",
        "stock_type": "ETF",
        "provider_stock_type": "ETF",
        "provider_classified_at": datetime.now(timezone.utc).isoformat(),
    },
    {
        "code": "US.SPY",
        "market": "US",
        "stock_type": "ETF",
        "provider_stock_type": "ETF",
        "provider_classified_at": datetime.now(timezone.utc).isoformat(),
    },
]


def query(database, sql):
    return subprocess.run(
        [PSQL, BASE.format(database=database), "-X", "-qAt", "-v", "ON_ERROR_STOP=1", "-c", sql],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
    ).stdout.strip()


def literal(value, kind):
    if kind == "integer":
        return str(value) + "::integer"
    raw = json.dumps(value) if kind == "jsonb" else value
    return "'" + raw.replace("'", "''") + "'::" + kind


class NativeDb:
    def __init__(self, database):
        self.database = database

    def _call(self, method, path, body=None):
        assert method == "POST"
        names = {
            "rpc/instrument_subtype_claim": ("instrument_subtype_claim", False),
            "rpc/instrument_subtype_release": ("instrument_subtype_release", False),
            "rpc/instrument_subtype_save_leased": ("instrument_subtype_save_leased", True),
        }
        function, many = names[path]
        types = {
            "p_market": "text",
            "p_run": "uuid",
            "p_code": "text",
            "p_revision": "integer",
            "p_record": "jsonb",
        }
        args = ",".join(key + " => " + literal(value, types[key]) for key, value in body.items())
        call = "public." + function + "(" + args + ")"
        sql = (
            "select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) from " + call + " r"
            if many
            else "select to_jsonb(" + call + ")"
        )
        raw = query(self.database, "set role service_role;" + sql)
        return json.loads(raw) if raw else None

    def select(self, table, query_args=None, columns="*"):
        assert table == "app_settings"
        return []

    def select_all(self, table, query_args=None, columns="*", cap=20000):
        if table == "screener_universe":
            return METADATA
        assert table == "instrument_subtype_cache"
        raw = query(
            self.database,
            "set role service_role;select coalesce(jsonb_agg(to_jsonb(r)),'[]'::jsonb) from (select * from public.instrument_subtype_cache where market='US' order by code limit "
            + str(cap)
            + ") r",
        )
        return json.loads(raw)


def good(symbol):
    return {"symbol": symbol, "quoteType": "ETF" if symbol == "SPY" else "EQUITY"}


def child(database, marker):
    def blocked(symbol):
        Path(marker).write_text(json.dumps({"symbol": symbol, "stage": "provider_pending"}))
        time.sleep(600)
        return good(symbol)

    run(NativeDb(database), fetch=blocked)


def parent():
    database = "instrument_subtype_restart_" + uuid.uuid4().hex[:10]
    marker = OUT / "restart-live-marker.json"
    marker.unlink(missing_ok=True)
    worker = None
    report = {}
    started = time.monotonic()
    query("postgres", "create database " + database)
    try:
        for name in (
            "20261002131807_instrument_subtype_cache.sql",
            "20261002132749_instrument_subtype_leases.sql",
        ):
            query(database, (ROOT / "supabase/migrations" / name).read_text())
        db = NativeDb(database)
        seed = str(uuid.uuid4())
        assert claim(db, "US", seed)
        prior = collect([METADATA[0]], fetch_info=good)["updates"]
        assert publish(db, "US", prior, {}, run_id=seed)["saved"] == ["US.PLD"]
        assert release(db, "US", seed)
        worker = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "child", database, str(marker)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        limit = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < limit:
            assert worker.poll() is None
            time.sleep(0.05)
        assert marker.exists() and json.loads(marker.read_text())["symbol"] == "SPY"
        lease = json.loads(
            query(
                database,
                "select to_jsonb(r) from public.instrument_subtype_runs r join public.instrument_subtype_leases l on l.run_id=r.id where l.market='US'",
            )
        )
        worker.kill()
        worker.communicate(timeout=5)
        assert worker.returncode < 0
        immediate = run(
            db, fetch=lambda _: (_ for _ in ()).throw(AssertionError("must remain idle"))
        )
        assert immediate["skipped"] == "market_collection_already_running"
        assert read_cache(db, "US")[0] == prior
        print(
            json.dumps(
                {
                    "stage": "killed_and_immediate_replacement_idle",
                    "lease": lease["id"],
                    "expires_at": lease["expires_at"],
                }
            ),
            flush=True,
        )
        # No DB clock edits, shorter lease, renewal or early release. Wait only
        # for this exact receipt's natural server-clock expiration.
        expiry = datetime.fromisoformat(lease["expires_at"])
        while datetime.now(timezone.utc) <= expiry:
            if worker.poll() is None:
                raise AssertionError("killed worker still running")
            time.sleep(
                min(5, max(0.01, (expiry - datetime.now(timezone.utc)).total_seconds() + 0.1))
            )
        recovered = run(db, fetch=good)
        assert recovered["attempted"] == 1 and recovered["saved"] == 1
        records, revisions = read_cache(db, "US")
        assert records["US.PLD"] == prior["US.PLD"] and revisions == {"US.PLD": 1, "US.SPY": 1}
        assert records["US.SPY"]["context"]["fields"]["quoteType"] == "ETF"
        idle = run(
            db,
            fetch=lambda _: (_ for _ in ()).throw(AssertionError("must not refetch fresh cache")),
        )
        assert idle["attempted"] == 0
        report = {
            "sigkill_returncode": worker.returncode,
            "immediate_replacement_idle": True,
            "lease_seconds": 330,
            "natural_expiry": True,
            "prior_record_exact": True,
            "recovered": recovered,
            "subsequent_attempted": idle["attempted"],
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    finally:
        if worker is not None and worker.poll() is None:
            worker.kill()
            worker.communicate(timeout=5)
        query("postgres", "drop database " + database + " with (force)")
        marker.unlink(missing_ok=True)
    report["database_removed"] = (
        query("postgres", "select count(*) from pg_database where datname='" + database + "'")
        == "0"
    )
    assert report["database_removed"]
    (OUT / "native-restart.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "child":
        child(sys.argv[2], sys.argv[3])
    else:
        parent()
