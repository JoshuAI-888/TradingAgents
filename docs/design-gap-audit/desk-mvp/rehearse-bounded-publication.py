"""Synthetic bounded publication regression, disposable local PostgreSQL only.

Uses >90 MB of JSON quote evidence, with no provider/private data or HTTP calls.
A unique test database is always removed; an existing local test cluster is needed.
"""

import copy
import json
import pathlib
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone

ROOT = pathlib.Path(__file__).resolve().parents[3]
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
DB = "publication_bounded_" + uuid.uuid4().hex[:12]
CHECKS = []


def q(sql, db=DB, error=None):
    result = subprocess.run(
        BASE + ["-d", db], input=sql, text=True, capture_output=True, timeout=60
    )
    if error:
        assert result.returncode != 0 and error in result.stderr, result.stderr
        CHECKS.append(error)
        return None
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def lit(value):
    return "'" + json.dumps(value, separators=(",", ":")).replace("'", "''") + "'::jsonb"


def begin(market="US"):
    run = str(uuid.uuid4())
    q(f"set role service_role;select screener_refresh_begin('{market}','{run}');")
    return run


def stage(run, rows, market="US", error=None):
    return q(
        f"set role service_role;select screener_refresh_stage('{market}','{run}',{lit(rows)});",
        error=error,
    )


def publish(run, codes, result, market="US", error=None):
    return q(
        f"set role service_role;select screener_refresh_publish_staged('{market}','{run}',{lit(codes)},{lit(result)},true);",
        error=error,
    )


def pointer(market="US"):
    return q(
        f"select value->>'generation_id' from app_settings where key='universe_state_{market}';"
    )


def abort(run, market="US"):
    q(
        f"set role service_role;select screener_refresh_abort('{market}','{run}','publication','Synthetic test complete');"
    )


def row(code, stamp):
    # Realistic typed field observations make JSON large without one giant filler.
    observations = {
        f"field{k}": {
            "code": code,
            "field": f"field{k}",
            "value": k + 0.25,
            "source": "synthetic_snapshot",
            "period": "point_in_time",
            "unit": "currency",
            "currency": None,
            "observed_at": stamp,
            "clock": "quote_source",
            "provider_data_date": "2026-10-03",
            "timestamp_semantics": "provider_snapshot_update",
            "last_trade_time": None,
        }
        for k in range(35)
    }
    observations["price"] = {
        "code": code,
        "field": "price",
        "value": 12.25,
        "unit": "currency",
        "currency": "USD",
    }
    observations["invalid"] = {"currency": 123}
    return {
        "code": code,
        "row": {
            "code": code,
            "price": 12.25,
            "quote_observed_at": stamp,
            "timestamp_semantics": "provider_snapshot_update",
            "field_observations": observations,
            **{f"field{k}": k + 0.25 for k in range(35)},
        },
        "metadata": {
            "code": code,
            "market": code[:2],
            "stock_type": "STOCK",
            "plates": [],
            "name": "Synthetic instrument",
        },
        "quote_cache_at": stamp,
    }


q("create database " + DB, db="postgres")
try:
    q((ROOT / "web/worker/tests/generation-db-bootstrap.sql").read_text().split("\\ir")[0])
    for migration in [
        "20261003105144_screener_generation_publication.sql",
        "20261003114454_screener_screen_publication.sql",
        "20261003120913_screener_bounded_staging.sql",
    ]:
        q((ROOT / "supabase/migrations" / migration).read_text())
    run = begin()
    stamp = datetime.now(timezone.utc).isoformat()
    n = 9421
    rows = [row(f"US.S{i}", stamp) for i in range(n)]
    codes = [r["code"] for r in rows]
    size = len(json.dumps(rows, separators=(",", ":")).encode())
    assert size > 90_000_000, size
    result = {
        "enum": {
            "scope": "exhausted_provider_market_screen",
            "codes": n,
            "provider_total": n,
            "pages": 32,
        }
    }
    stage(run, rows[:401], error="oversized staging batch")
    stage(run, rows[:1] * 2, error="classified requested cohort")
    large = copy.deepcopy(rows[:1])
    large[0]["row"]["oversize"] = "a" * 8_388_608
    stage(run, large, error="oversized staging batch")
    bad = copy.deepcopy(rows[:1])
    bad[0]["metadata"]["code"] = "US.WRONG"
    stage(run, bad, error="classified requested cohort")
    bad = copy.deepcopy(rows[:1])
    bad[0]["code"] = bad[0]["row"]["code"] = bad[0]["metadata"]["code"] = "US..INVALID"
    stage(run, bad, error="classified requested cohort")
    bad = copy.deepcopy(rows[:1])
    bad[0]["quote_cache_at"] = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    stage(run, bad, error="outside the refresh interval")
    t = time.monotonic()
    batch_bytes = []
    for offset in range(0, n, 400):
        batch = rows[offset : offset + 400]
        batch_bytes.append(len(json.dumps(batch, separators=(",", ":")).encode()))
        receipt = json.loads(stage(run, batch))
        assert receipt == {"run_id": run, "market": "US", "staged": len(batch)}
        if offset == 0:
            assert json.loads(stage(run, batch)) == receipt
            publish(run, codes, result, error="does not match the requested cohort")
            assert pointer() == ""
            assert q("select count(*) from screener_generation_rows;") == "0"
    stage_seconds = time.monotonic() - t
    changed = copy.deepcopy(rows[:1])
    changed[0]["row"]["price"] = 999
    stage(run, changed, error="Conflicting replay")
    wrong = codes[:-1] + ["US.WRONG"]
    publish(run, wrong, result, error="does not match the requested cohort")
    bad_result = copy.deepcopy(result)
    bad_result["enum"]["provider_total"] -= 1
    publish(run, codes, bad_result, error="Invalid exhausted screening receipt")
    bad_result = copy.deepcopy(result)
    bad_result["enum"]["pages"] = 1
    publish(run, codes, bad_result, error="Invalid exhausted screening receipt")
    bad_result = copy.deepcopy(result)
    bad_result["enum"]["pages"] = 69
    publish(run, codes, bad_result, error="Invalid exhausted screening receipt")
    t = time.monotonic()
    receipt = json.loads(publish(run, codes, result))
    publish_seconds = time.monotonic() - t
    assert receipt["row_count"] == n and pointer() == run
    assert q("select count(*) from screener_generation_rows;") == str(n)
    assert q("select count(*) from screener_quotes;") == str(n)
    assert json.loads(publish(run, codes, result)) == receipt
    assert json.loads(stage(run, rows[:400]))["staged"] == 400
    payload = row("US.LATE", datetime.now(timezone.utc).isoformat())
    q(
        f"set role service_role;insert into screener_refresh_staged_rows(run_id,code,payload,fingerprint) values ('{run}','US.LATE',{lit(payload)},encode(sha256(convert_to({lit(payload)}::text,'UTF8')),'hex'));",
        error="finished, expired or superseded",
    )
    stage(run, changed, error="Conflicting replay")
    publish(run, list(reversed(codes)), result, error="Conflicting replay")
    projection = json.loads(
        q(
            "select jsonb_build_object('row',d.row,'metadata_equal',d.metadata=g.metadata,'cache_equal',d.quote_cache_at=g.quote_cache_at,'original_fields',jsonb_object_length_test) from screener_generation_display_rows d join screener_generation_rows g using(generation_id,code) cross join lateral (select count(*) as jsonb_object_length_test from jsonb_object_keys(g.row->'field_observations')) x where d.code='US.S0';"
        )
    )
    assert set(projection["row"]["field_observations"]) == {"price"}
    assert (
        projection["row"] | {"field_observations": rows[0]["row"]["field_observations"]}
        == rows[0]["row"]
    )
    assert (
        projection["metadata_equal"]
        and projection["cache_equal"]
        and projection["original_fields"] == 37
    )
    # Aborted/expired owners cannot stage or publish, and preserve the last complete pointer.
    old = begin()
    small = [row("US.NEXT", datetime.now(timezone.utc).isoformat())]
    stage(old, small)
    q(
        f"update app_settings set value=jsonb_set(value,'{{generation_id}}',to_jsonb('{uuid.uuid4()}'::text)) where key='universe_state_US';"
    )
    stage(old, small, error="does not belong to this run")
    publish(
        old,
        ["US.NEXT"],
        {"enum": {"scope": "observed_plate_and_screen_slice_union", "codes": 1}},
        error="changed during refresh",
    )
    q(
        f"update app_settings set value=jsonb_set(value,'{{generation_id}}',to_jsonb('{run}'::text)) where key='universe_state_US';"
    )
    abort(old)
    successor = begin()
    stage(old, small, error="expired or superseded")
    publish(
        old,
        ["US.NEXT"],
        {"enum": {"scope": "observed_plate_and_screen_slice_union", "codes": 1}},
        error="expired or superseded",
    )
    assert pointer() == run
    abort(successor)
    # Plate scope remains valid, and quote-only receipt cannot masquerade as enumeration.
    hk = begin("HK")
    small = [row("HK.00001", datetime.now(timezone.utc).isoformat())]
    stage(hk, small, "HK")
    assert (
        json.loads(
            publish(
                hk,
                ["HK.00001"],
                {"enum": {"scope": "observed_plate_and_screen_slice_union", "codes": 1}},
                "HK",
            )
        )["row_count"]
        == 1
    )
    security = json.loads(
        q(
            "select jsonb_build_object('staging_rls',(select relrowsecurity from pg_class where oid='screener_refresh_staged_rows'::regclass),'browser_table',has_table_privilege('anon','screener_refresh_staged_rows','SELECT'),'browser_view',has_table_privilege('authenticated','screener_generation_display_rows','SELECT'),'service_view',has_table_privilege('service_role','screener_generation_display_rows','SELECT'),'view_invoker',(select reloptions @> array['security_invoker=true'] from pg_class where oid='screener_generation_display_rows'::regclass),'rpcs',(select jsonb_agg(jsonb_build_object('name',proname,'invoker',not prosecdef,'anon_execute',has_function_privilege('anon',oid,'EXECUTE'),'service_execute',has_function_privilege('service_role',oid,'EXECUTE'))) from pg_proc where proname in ('screener_refresh_stage','screener_refresh_publish_staged')));"
        )
    )
    assert security["staging_rls"] and security["view_invoker"] and security["service_view"]
    assert not security["browser_table"] and not security["browser_view"]
    assert all(
        r["invoker"] and r["service_execute"] and not r["anon_execute"] for r in security["rpcs"]
    )
    q("set role anon;select * from screener_refresh_staged_rows;", error="permission denied")
    q(
        "set role authenticated;select * from screener_generation_display_rows;",
        error="permission denied",
    )
    q(
        f"set role service_role;update screener_refresh_staged_rows set code=code where run_id='{run}';",
        error="permission denied",
    )
    evidence = {
        "scope": "Isolated PostgreSQL synthetic data; no provider or production qualification",
        "rows": n,
        "aggregate_json_bytes": size,
        "max_batch_json_bytes": max(batch_bytes),
        "staging_seconds": round(stage_seconds, 2),
        "publish_seconds": round(publish_seconds, 2),
        "replay_identical": True,
        "previous_pointer_preserved_on_failure": True,
        "projection_retains_values_clocks_classification_and_string_currency_evidence": True,
        "security": security,
        "expected_rejection_checks": CHECKS,
    }
    print(json.dumps(evidence, indent=2))
finally:
    q("drop database " + DB + " with (force);", db="postgres")
