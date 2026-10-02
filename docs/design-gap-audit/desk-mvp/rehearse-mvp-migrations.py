"""Fixed disposable local PostgreSQL only; no URLs, credentials or production arguments."""

import hashlib
import json
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent
DB = "mvp_cutover_" + uuid.uuid4().hex[:12]
BASE = [
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
MIGRATIONS = [
    "20261002060206_screener_generation_publication.sql",
    "20261002142613_server_owned_data_access.sql",
    "20261002131807_instrument_subtype_cache.sql",
    "20261002132749_instrument_subtype_leases.sql",
]
TABLES = [
    "corporate_actions",
    "company_profiles",
    "fundamentals",
    "insider_transactions",
    "macro_series",
    "macro_observations",
    "social_posts",
    "prediction_market_quotes",
    "data_fetch_log",
    "backtest_runs",
    "embeddings",
    "vendor_budget_ledger",
]


def query(sql, database=DB):
    result = subprocess.run(
        BASE + ["-d", database], input=sql, text=True, capture_output=True, timeout=30, check=True
    )
    return result.stdout.strip()


report = {
    "scope": "Disposable PostgreSQL 16 synthetic schema; not production/PostgREST/provider qualification",
    "migrations": {},
    "checks": {},
}
query("create database " + DB, database="postgres")
try:
    report["postgres_version"] = query("show server_version;")
    bootstrap = (ROOT / "web/worker/tests/generation-db-bootstrap.sql").read_text()
    query(bootstrap.split("\\ir")[0])
    fixture = "".join(
        f"create table public.{name}(id integer primary key,payload text);"
        f"insert into public.{name} values(1,'retained');"
        f"grant all on public.{name} to anon,authenticated,service_role;"
        for name in TABLES
    )
    query(
        fixture + "create view public.v_decision_ledger as select * from public.backtest_runs;"
        "create view public.v_equity_curve as select * from public.v_decision_ledger;"
        "create materialized view public.vendor_health as select * from public.data_fetch_log;"
        "grant all on public.v_decision_ledger,public.v_equity_curve,public.vendor_health to anon,authenticated,service_role;"
    )
    for name in MIGRATIONS:
        raw = (ROOT / "supabase/migrations" / name).read_bytes()
        query(raw.decode())
        report["migrations"][name] = hashlib.sha256(raw).hexdigest()
    run = str(uuid.uuid4())
    begun = json.loads(
        query("set role service_role;select public.screener_refresh_begin('US','" + run + "');")
    )
    assert begun["run_id"] == run and begun["market"] == "US"
    assert (
        query(
            "set role service_role;select public.screener_refresh_abort('US','"
            + run
            + "','cohort_validation','Synthetic cutover rehearsal');"
        )
        == "t"
    )
    report["checks"]["generation_begin_abort_with_all_migrations"] = True
    token = str(uuid.uuid4())
    claimed = json.loads(
        query("set role service_role;select public.instrument_subtype_claim('HK','" + token + "');")
    )
    assert claimed["id"] == token and claimed["market"] == "HK"
    assert (
        query(
            "set role service_role;select public.instrument_subtype_release('HK','" + token + "');"
        )
        == "t"
    )
    report["checks"]["subtype_claim_release_with_core_migrations"] = True
    for name in TABLES:
        assert (
            query(
                f"set role service_role;select count(*) from public.{name} where payload='retained';"
            )
            == "1"
        )
        query(
            f"set role service_role;insert into public.{name} values(2,'new');"
            f"update public.{name} set payload='updated' where id=2;delete from public.{name} where id=2;"
        )
    for name in ["v_decision_ledger", "v_equity_curve", "vendor_health"]:
        assert query(f"set role service_role;select count(*) from public.{name};") == "1"
    report["checks"]["service_access_and_original_content_preserved"] = True
    denied = 0
    for role in ["anon", "authenticated"]:
        for target in TABLES + [
            "v_decision_ledger",
            "v_equity_curve",
            "vendor_health",
            "screener_generations",
            "screener_generation_rows",
            "instrument_subtype_cache",
        ]:
            try:
                query(f"set role {role};select * from public.{target};")
            except subprocess.CalledProcessError as error:
                assert "permission denied" in error.stderr
                denied += 1
            else:
                raise AssertionError("Unexpected browser access: " + role + "." + target)
    report["checks"]["browser_reads_denied"] = denied
    assert denied == 36
finally:
    query("drop database " + DB + " with (force)", database="postgres")
report["database_removed"] = (
    query("select count(*) from pg_database where datname='" + DB + "';", database="postgres")
    == "0"
)
assert report["database_removed"]
(OUT / "mvp-migration-rehearsal.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report))
