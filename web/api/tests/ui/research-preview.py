"""Full offline API/browser harness. Synthetic rows and recorded stock responses.
Run with PYTHONPATH=web/api:web/worker python web/api/tests/ui/research-preview.py.
No live service calls or production writes; saved screens/history live in memory.
"""

import importlib.util
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.update(
    DEFAULT_USER_ID="offline-review",
    TA_STOCK_FIXTURES="1",
    SUPABASE_URL="https://example.supabase.co",
    SUPABASE_SERVICE_KEY="test",
    PORTAL_STATIC_DIR=str(Path(__file__).resolve().parents[2] / "static"),
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import uvicorn
from test_api import FakeDb
from tradingagents_api import main as api, stock_fixtures

spec = importlib.util.spec_from_file_location("fixture", Path(__file__).with_name("preview.py"))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
api.db = FakeDb()
# Synthetic account/store transport for UI verification only. No remote Auth.
import base64  # noqa: E402 - initialization must precede this import
import hashlib  # noqa: E402 - initialization must precede this import
import json  # noqa: E402 - initialization must precede this import
import time  # noqa: E402 - initialization must precede this import
import uuid  # noqa: E402 - initialization must precede this import

from fastapi import HTTPException  # noqa: E402 - initialization must precede this import
from tradingagents_api import (  # noqa: E402 - initialization must precede this import
    research_auth,
    research_lists,
    research_reviews,
    research_schedules,
    scheduled_reviews,
)

PREVIEW_OWNER = "00000000-0000-4000-8000-000000000001"


def preview_token(owner=PREVIEW_OWNER):
    payload = (
        base64.urlsafe_b64encode(
            json.dumps({"sub": owner, "session_id": str(uuid.uuid4())}).encode()
        )
        .decode()
        .rstrip("=")
    )
    return "preview." + payload + ".fixture"


def preview_auth(path, body=None, token=None):
    if path.startswith("logout"):
        return {}
    if path.endswith("password") and body.get("password") != "preview-password":
        raise HTTPException(401, "Invalid preview credentials.")
    return {
        "access_token": preview_token(),
        "refresh_token": "preview-refresh",
        "expires_in": 3600,
        "user": {"id": PREVIEW_OWNER, "email": "reviewer@example.test", "is_anonymous": False},
    }


research_auth._auth_exchange = preview_auth
research_auth._auth_user = lambda token: {"id": PREVIEW_OWNER, "is_anonymous": False}
research_auth._session_active = lambda owner, session: True


class PreviewResearchDb:
    def _call(self, method, path, body=None, query=None, prefer=None):
        if path == "rpc/research_capture_schedule_save":
            rows = api.db._t("research_capture_schedules")
            row = next(
                (
                    r
                    for r in rows
                    if r["owner_id"] == body["p_owner"] and r["definition_hash"] == body["p_hash"]
                ),
                None,
            )
            if (
                body["p_revision"] == 0
                and row
                or body["p_revision"]
                and (
                    not row
                    or row["revision"] != body["p_revision"]
                    or row["definition"] != body["p_definition"]
                )
            ):
                return []
            if not row:
                row = {
                    "id": str(uuid.uuid4()),
                    "owner_id": body["p_owner"],
                    "definition_hash": body["p_hash"],
                    "definition": body["p_definition"],
                }
                rows.append(row)
            row.update(
                name=body["p_name"],
                cadence=body["p_cadence"],
                enabled=body["p_enabled"],
                revision=body["p_revision"] + 1,
                next_due_at=body["p_next"],
            )
            return [dict(row)]
        if path == "rpc/research_scheduled_pair_review_read":
            keys = {
                "owner_id": body["p_owner"],
                "schedule_id": body["p_schedule"],
                "previous_id": body["p_previous"],
                "current_id": body["p_current"],
            }
            rows = sorted(
                [
                    dict(r)
                    for r in api.db._t("research_scheduled_pair_reviews")
                    if all(r[k] == v for k, v in keys.items())
                ],
                key=lambda r: r["code"],
            )
            metadata = [{k: r[k] for k in ("code", "revision", "review_status")} for r in rows]
            fingerprint = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
            confirmed = body["p_expected_hash"] is None or body["p_expected_hash"] == fingerprint
            return {
                "confirmed": confirmed,
                "revision_hash": fingerprint,
                "reviews": metadata if body["p_expected_hash"] is None else [],
                "notes": [
                    {k: r[k] for k in ("code", "revision", "review_status", "note")}
                    for r in rows
                    if r["code"] in body["p_codes"]
                ]
                if confirmed
                else [],
            }
        if path == "rpc/research_scheduled_pair_review_save":
            keys = {
                "owner_id": body["p_owner"],
                "schedule_id": body["p_schedule"],
                "previous_id": body["p_previous"],
                "current_id": body["p_current"],
                "code": body["p_code"],
            }
            rows = api.db._t("research_scheduled_pair_reviews")
            row = next((r for r in rows if all(r[k] == v for k, v in keys.items())), None)
            if row and row["revision"] != body["p_revision"] or not row and body["p_revision"] != 0:
                return []
            if not row:
                row = {**keys, "revision": 0}
                rows.append(row)
            row.update(
                note=body["p_note"], review_status=body["p_status"], revision=row["revision"] + 1
            )
            return [dict(row)]
        if path in (
            "rpc/research_cross_history_pair_review_read",
            "rpc/research_cross_history_pair_review_save",
        ):
            keys = {
                "owner_id": body["p_owner"],
                "previous_history_key": body["p_previous_key"],
                "current_history_key": body["p_current_key"],
                "previous_id": body["p_previous"],
                "current_id": body["p_current"],
            }
            rows = api.db._t("research_cross_history_pair_reviews")
            matching = [r for r in rows if all(r[k] == v for k, v in keys.items())]
            if path.endswith("_read"):
                return {"reviews": [dict(r) for r in matching]}
            row = next((r for r in matching if r["code"] == body["p_code"]), None)
            if row and row["revision"] != body["p_revision"] or not row and body["p_revision"] != 0:
                return []
            if not row:
                row = {**keys, "code": body["p_code"], "revision": 0}
                rows.append(row)
            row.update(
                note=body["p_note"], review_status=body["p_status"], revision=row["revision"] + 1
            )
            return [dict(row)]
        if path == "rpc/research_duplicate_pair_review_scopes":
            from copy import deepcopy

            captures = {
                (r["history_key"], r["id"]): r["snapshot"] for r in api.db._t("screen_captures")
            }
            before = captures.get((body["p_previous_key"], body["p_previous"]))
            after = captures.get((body["p_current_key"], body["p_current"]))
            if before is None or after is None:
                return {"alias_qualified": False, "reviews": []}
            rows = []
            for table in ("research_pair_reviews", "research_cross_history_pair_reviews"):
                for record in api.db._t(table):
                    if (
                        record["owner_id"] != body["p_owner"]
                        or record["previous_id"] != body["p_previous"]
                        or record["current_id"] != body["p_current"]
                    ):
                        continue
                    previous = record.get("previous_history_key", record.get("history_key"))
                    current = record.get("current_history_key", record.get("history_key"))
                    if (
                        captures.get((previous, body["p_previous"])) != before
                        or captures.get((current, body["p_current"])) != after
                    ):
                        continue
                    row = deepcopy(record)
                    row.pop("history_key", None)
                    row.update(
                        previous_history_key=previous,
                        current_history_key=current,
                        review_contract="same_history" if previous == current else "cross_history",
                        updated_at=row.get("updated_at", datetime.now(timezone.utc).isoformat()),
                    )
                    rows.append(row)
            return {
                "alias_qualified": True,
                "reviews": sorted(
                    rows,
                    key=lambda r: (r["code"], r["previous_history_key"], r["current_history_key"]),
                ),
            }
        if path == "rpc/research_pair_review_read":
            keys = {
                "owner_id": body["p_owner"],
                "history_key": body["p_key"],
                "previous_id": body["p_previous"],
                "current_id": body["p_current"],
            }
            return {
                "reviews": [
                    dict(r)
                    for r in api.db._t("research_pair_reviews")
                    if all(r[k] == v for k, v in keys.items())
                ]
            }
        if path == "rpc/research_pair_review_save":
            keys = {
                "owner_id": body["p_owner"],
                "history_key": body["p_key"],
                "previous_id": body["p_previous"],
                "current_id": body["p_current"],
                "code": body["p_code"],
            }
            rows = api.db._t("research_pair_reviews")
            row = next((r for r in rows if all(r[k] == v for k, v in keys.items())), None)
            if row and row["revision"] != body["p_revision"] or not row and body["p_revision"] != 0:
                return []
            if not row:
                row = {**keys, "revision": 0}
                rows.append(row)
            row.update(
                note=body["p_note"], review_status=body["p_status"], revision=row["revision"] + 1
            )
            return [dict(row)]
        if path == "rpc/research_list_search":
            text = body["p_query"].strip().casefold()
            names = {
                r["code"]: r["row"].get("name", "")
                for r in api.db._t("screener_quotes")
                if isinstance(r.get("row"), dict)
                and r["row"].get("code") == r["code"]
                and isinstance(r["row"].get("name"), str)
            }
            matches = [
                r
                for r in api.db._t("research_list_items")
                if r["list_id"] == body["p_list"]
                and r["owner_id"] == body["p_owner"]
                and (body["p_removed"] or r["active"])
                and (body["p_status"] == "all" or r["review_status"] == body["p_status"])
                and (not body["p_after"] or r["code"] > body["p_after"])
                and (text in r["code"].casefold() or text in names.get(r["code"], "").casefold())
            ]
            matches.sort(key=lambda r: r["code"])
            start = body["p_offset"]
            return [dict(r) for r in matches[start : start + body["p_limit"]]]
        if path.startswith("rpc/"):
            parent = next(
                (
                    r
                    for r in api.db._t("research_lists")
                    if r["id"] == body["p_list"]
                    and r["owner_id"] == body["p_owner"]
                    and r["active"]
                ),
                None,
            )
            if not parent:
                return []
            member = next(
                (
                    r
                    for r in api.db._t("research_list_items")
                    if r["list_id"] == body["p_list"] and r["code"] == body["p_code"]
                ),
                None,
            )
            if path.endswith("research_list_add"):
                if member and member["active"]:
                    return [dict(member)]
                if not member:
                    member = {
                        "list_id": parent["id"],
                        "owner_id": parent["owner_id"],
                        "code": body["p_code"],
                        "note": "",
                        "review_status": "unreviewed",
                        "active": True,
                        "revision": 1,
                    }
                    api.db._t("research_list_items").append(member)
                else:
                    member["active"] = True
                    member["revision"] += 1
            else:
                if not member or member["revision"] != body["p_revision"]:
                    return []
                for k, param in [
                    ("note", "p_note"),
                    ("review_status", "p_status"),
                    ("active", "p_active"),
                ]:
                    if body[param] is not None:
                        member[k] = body[param]
                member["revision"] += 1
            parent["revision"] += 1
            parent["updated_at"] = datetime.now(timezone.utc).isoformat()
            return [dict(member)]
        rows = api.db._t(path)
        matching = list(rows)
        for k, v in (query or {}).items():
            if str(v).startswith("eq."):
                matching = [r for r in matching if str(r.get(k)).lower() == v[3:].lower()]
            elif str(v).startswith("in.("):
                matching = [r for r in matching if r.get(k) in v[4:-1].split(",")]
            elif str(v).startswith("ilike.*"):
                matching = [
                    r
                    for r in matching
                    if v[7:-1].replace("\\_", "_").upper() in str(r.get(k, "")).upper()
                ]
            elif k == "and" and v.startswith("(code.gt."):
                matching = [r for r in matching if r["code"] > v[9:-1]]
        if method == "GET":
            matching.sort(key=lambda r: r.get("code") or r.get("name") or "")
            if (query or {}).get("order") == "published_at.desc,id.desc":
                matching.sort(key=lambda r: (r["published_at"], r["id"]), reverse=True)
            if (query or {}).get("order") == "due_at.desc,id.desc":
                matching.sort(key=lambda r: (r["due_at"], r["id"]), reverse=True)
            offset = int((query or {}).get("offset", 0))
            limit = int((query or {}).get("limit", 1000))
            return [dict(r) for r in matching[offset : offset + limit]]
        if method == "POST":
            if any(
                r["owner_id"] == body["owner_id"]
                and r["name"].casefold() == body["name"].casefold()
                and r["active"]
                for r in rows
            ):
                raise RuntimeError("supabase POST -> 409: duplicate")
            row = {
                **body,
                "id": str(uuid.uuid4()),
                "active": True,
                "revision": 1,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            rows.append(row)
            return [dict(row)]
        if method == "PATCH":
            for r in matching:
                r.update(body)
            return [dict(r) for r in matching]


research_lists.db = PreviewResearchDb()
research_reviews.db = research_lists.db
research_schedules.db = research_lists.db
scheduled_reviews.db = research_lists.db
api.db._t("research_lists").append(
    {
        "id": "00000000-0000-4000-8000-000000000003",
        "owner_id": PREVIEW_OWNER,
        "name": "Investment review fixture",
        "description": "Synthetic UI verification only",
        "active": True,
        "revision": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
)
api.db._t("research_list_items").append(
    {
        "list_id": "00000000-0000-4000-8000-000000000003",
        "owner_id": PREVIEW_OWNER,
        "code": "US.S0001",
        "note": "Review balance sheet quality",
        "review_status": "unreviewed",
        "active": True,
        "revision": 1,
    }
)
now = datetime.now(timezone.utc).isoformat()
if os.getenv("RESEARCH_COMPANY_CONTEXT_FIXTURE"):
    api.db._t("screener_enrichment").append(
        {
            "market": "US",
            "code": "US.S0001",
            "as_of": now,
            "data": {
                "sector": "Technology",
                "industry": "Synthetic classification",
                "website": "https://company.example/",
                "_meta": {"fundamentals_at": now},
            },
        }
    )
if os.getenv("RESEARCH_REFRESH_FAILURE_FIXTURE"):
    api.db._t("app_settings").extend(
        [
            {"key": "universe_state", "value": {"interval_h": 4}},
            {
                "key": "universe_state_US",
                "value": {
                    "last_quotes": (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat(),
                    "last_attempt": {
                        "status": "failed",
                        "stage": "quotes",
                        "reason": "Quote batch 2: 1 requested identities missing",
                    },
                },
            },
        ]
    )
for row in fixture.ROWS:
    api.db._t("screener_quotes").append(
        {"market": "US", "code": row["code"], "row": row.copy(), "updated_at": now}
    )
    api.db._t("screener_universe").append({"market": "US", **row})
if os.getenv("RESEARCH_HK_NAVIGATION_FIXTURE"):
    # Synthetic directory identities only. Recorded US company details are not
    # valid HK quotes; the real quote route's identity guard rejects them.
    for symbol in ("00700", "00005"):
        row = {
            **fixture.ROWS[0],
            "market": "HK",
            "code": "HK." + symbol,
            "symbol": symbol,
            "name": "Synthetic HK navigation " + symbol,
            "stock_type": "STOCK",
        }
        api.db._t("screener_quotes").append(
            {"market": "HK", "code": row["code"], "row": row, "updated_at": now}
        )
        api.db._t("screener_universe").append(row)
# Opt-in immutable-generation fixture for provenance/capture/download checks.
# Same synthetic securities; no live financial accuracy claim.
if os.getenv("RESEARCH_GENERATION_FIXTURE"):

    class GenerationPreviewDb(FakeDb):
        def select_all(self, table, query=None, columns="*", cap=20000):
            return self.select(table, query, columns)[:cap]

    generated = GenerationPreviewDb()
    generated.tables = api.db.tables
    api.db = generated
    gid = "11111111-1111-4111-8111-111111111111"
    codes = sorted(r["code"] for r in fixture.ROWS)
    result = {"quotes": {"market": "US", "quotes": len(codes)}}
    api.db._t("screener_generations").append(
        {
            "id": gid,
            "market": "US",
            "row_count": len(codes),
            "started_at": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            "published_at": now,
            "cohort_fingerprint": hashlib.sha256("\n".join(codes).encode()).hexdigest(),
            "result": result,
        }
    )
    for row in fixture.ROWS:
        api.db._t("screener_generation_rows").append(
            {
                "generation_id": gid,
                "code": row["code"],
                "row": row.copy(),
                "metadata": {
                    "code": row["code"],
                    "market": "US",
                    "name": row["name"],
                    "stock_type": row["stock_type"],
                    "plate": row.get("plate"),
                    "plates": row.get("plates") or [],
                    "exchange": row.get("exchange"),
                },
                "quote_cache_at": now,
            }
        )
    api.db.upsert(
        "app_settings",
        "key",
        {
            "key": "universe_state_US",
            "value": {"generation_id": gid, "last_quotes": now, "last_result": result},
        },
    )
# Optional public quote response retained from a bounded deployment read. Only
# the quote provenance is real; chart/other fixture responses remain synthetic.
if os.getenv("RESEARCH_PUBLIC_QUOTE_FIXTURE"):
    from tradingagents_worker.screener_rows import snapshot_to_row

    probe = json.loads(Path(os.environ["RESEARCH_PUBLIC_QUOTE_FIXTURE"]).read_text())
    if probe["quote"].get("code") != "US.AAPL":
        raise ValueError("Expected bounded AAPL quote fixture")
    row = {**snapshot_to_row(probe["quote"]), "stock_type": "STOCK"}
    api.db._t("screener_quotes").append(
        {"market": "US", "code": row["code"], "row": row, "updated_at": probe["retrieved_at"]}
    )
    api.db._t("screener_universe").append({"market": "US", **row})
# Controlled historical membership fixture: one exit, one entry, others retained.
# This is interaction evidence only, never a live data/count reconciliation.
change_definition = api.ScreenDefinition(filters=[{"field": "stock_type", "values": ["STOCK"]}])


def change_member(row):
    return {
        "code": row["code"],
        "symbol": row["symbol"],
        "name": row["name"],
        "metrics": {k: row.get(k) for k in ("price", "pct", "market_cap", "pe_ttm")},
        "evidence": {"stock_type": "STOCK"},
    }


before_members = [change_member(r) for r in fixture.ROWS if r["stock_type"] == "STOCK"]
after_members = before_members[1:] + [
    {
        "code": "US.S2001",
        "symbol": "S2001",
        "name": "Fixture New Company",
        "metrics": {"price": 20, "pct": 1, "market_cap": 2500000000, "pe_ttm": 20},
        "evidence": {"stock_type": "STOCK"},
    }
]
before_time = (datetime.now(timezone.utc) - timedelta(hours=20)).isoformat()
after_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
api.db._t("app_settings").append(
    {
        "key": api._snapshot_key(change_definition),
        "value": {
            "snapshots": [
                {
                    "id": "fixture-before",
                    "version": 2,
                    "at": before_time,
                    "source_at": before_time,
                    "source_clock": "stored_universe",
                    "definition": change_definition.model_dump(),
                    "members": before_members,
                    "complete": True,
                },
                {
                    "id": "fixture-after",
                    "version": 2,
                    "at": after_time,
                    "source_at": after_time,
                    "source_clock": "stored_universe",
                    "definition": change_definition.model_dump(),
                    "members": after_members,
                    "complete": True,
                },
            ]
        },
    }
)
# Optional large timeline for retained-history browser pagination only.
# These dated copies are synthetic observations, not market-history evidence.
if os.getenv("RESEARCH_HISTORY_PAGING") == "1":
    import copy

    capture_key = api._snapshot_key(change_definition)
    legacy = api.db._t("app_settings")[-1]["value"]["snapshots"]
    api.db._call(
        "POST",
        "rpc/screen_capture_append",
        body={"p_key": capture_key, "p_records": [{"id": s["id"], "snapshot": s} for s in legacy]},
    )
    paging_records = []
    for i in range(103):
        snapshot = copy.deepcopy(legacy[0])
        snapshot["id"] = f"paging-{i:03}"
        snapshot["at"] = (datetime.now(timezone.utc) - timedelta(days=i + 2)).isoformat()
        snapshot["source_at"] = snapshot["at"]
        paging_records.append({"id": snapshot["id"], "snapshot": snapshot})
    for offset in range(0, len(paging_records), 100):
        api.db._call(
            "POST",
            "rpc/screen_capture_append",
            body={"p_key": capture_key, "p_records": paging_records[offset : offset + 100]},
        )

api.db._t("saved_screeners").append(
    {
        "id": "saved",
        "user_id": "offline-review",
        "name": "Saved Price Ascending",
        "filters": [{"field": "price", "max": 10}],
        "sort": "price",
        "direction": 1,
        "market": "US",
        "settings": {},
    }
)
# Optional paired observations for browser review of the v3 evidence contract.
# Explicitly synthetic; this does not qualify any live provider's provenance.
if os.getenv("RESEARCH_OBSERVATION_FIXTURE") == "1":
    import copy

    from tradingagents_api.screen_observations import (
        capture_observation,
        validate_observation_capture,
    )

    observation_definition = api.ScreenDefinition(
        filters=[{"field": "price", "max": 10}, {"field": "stock_type", "values": ["STOCK"]}]
    )
    captures = []
    for side, hours in [("before", 20), ("after", 1)]:
        captured = datetime.now(timezone.utc) - timedelta(hours=hours)
        observed = (captured - timedelta(minutes=10)).isoformat()
        records = []
        for source in fixture.ROWS:
            if source["stock_type"] != "STOCK":
                continue
            row = copy.deepcopy(source)
            if row["code"] == "US.S0001":
                row["price"] = 12 if side == "before" else 8
            if row["code"] == "US.S0002":
                row["price"] = 6 if side == "before" else 14
            row["quote_cache_at"] = captured.isoformat()
            row["field_evidence"] = {
                "c0": {
                    "criterion": observation_definition.filters[0],
                    "value": row["price"],
                    "source": "synthetic_fixture",
                    "period": "point_in_time",
                    "unit": "currency",
                    "currency": "USD",
                    "clock": "quote_source",
                    "observed_at": observed,
                }
            }
            records.append(capture_observation(row, observation_definition.filters))
        snapshot = {
            "id": "observations-" + side,
            "version": 3,
            "at": captured.isoformat(),
            "source_at": captured.isoformat(),
            "source_clock": "stored_universe",
            "definition": observation_definition.model_dump(),
            "complete": True,
            "observation_scope": "eligible_stored_universe",
            "eligible_count": len(records),
            "observations": records,
            "members": [r for r in records if r["evidence"]["price"] <= 10],
        }
        validate_observation_capture(snapshot, observation_definition.model_dump())
        captures.append({"id": snapshot["id"], "snapshot": snapshot})
    if os.getenv("RESEARCH_CROSS_HISTORY_REVIEW_FIXTURE") == "1":
        os.environ["CROSS_HISTORY_PAIR_REVIEWS_ENABLED"] = "1"
        for record in captures:
            if record["id"].endswith("after"):
                snapshot = record["snapshot"]
                snapshot["definition"]["filters"][0].update(min=None, _label="Price")
                for observation in snapshot["observations"]:
                    observation["criterion_observations"]["c0"]["criterion"].update(
                        min=None, _label="Price"
                    )
                validate_observation_capture(snapshot, snapshot["definition"])
            definition = api.ScreenDefinition.model_validate(record["snapshot"]["definition"])
            api.db._call(
                "POST",
                "rpc/screen_capture_append",
                body={"p_key": api._snapshot_key(definition), "p_records": [record]},
            )
    else:
        api.db._call(
            "POST",
            "rpc/screen_capture_append",
            body={"p_key": api._snapshot_key(observation_definition), "p_records": captures},
        )
if os.getenv("RESEARCH_DUPLICATE_REVIEW_FIXTURE") == "1":
    os.environ.update(
        DUPLICATE_CAPTURE_REVIEW_SCOPES_ENABLED="1", CROSS_HISTORY_PAIR_REVIEWS_ENABLED="1"
    )
    original = next(
        r["history_key"] for r in api.db._t("screen_captures") if r["id"] == captures[0]["id"]
    )
    alternate = next(
        r["history_key"] for r in api.db._t("screen_captures") if r["id"] == captures[-1]["id"]
    )
    if original == alternate:
        raise ValueError("Duplicate review fixture requires cross-history observations")
    # Append the frozen stored payloads, not the construction objects whose
    # shared criterion dictionaries were subsequently relabelled for the after
    # capture. Duplicate identities must remain byte-for-byte equivalent.
    frozen = [
        {
            "id": record["id"],
            "snapshot": copy.deepcopy(
                next(
                    row["snapshot"]
                    for row in api.db._t("screen_captures")
                    if row["id"] == record["id"]
                )
            ),
        }
        for record in captures
    ]
    for history_key in (original, alternate):
        api.db._call(
            "POST", "rpc/screen_capture_append", body={"p_key": history_key, "p_records": frozen}
        )
    common = {
        "owner_id": PREVIEW_OWNER,
        "previous_id": captures[0]["id"],
        "current_id": captures[1]["id"],
        "code": "US.S0001",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    api.db._t("research_pair_reviews").append(
        {
            **common,
            "history_key": original,
            "revision": 2,
            "note": "Original same-history review: retain this investment question.",
            "review_status": "reviewed",
        }
    )
    api.db._t("research_cross_history_pair_reviews").append(
        {
            **common,
            "previous_history_key": original,
            "current_history_key": alternate,
            "revision": 4,
            "note": "Original cross-history review: independent second note.",
            "review_status": "in_review",
        }
    )


class MemoryCache:
    def key(self, *args):
        return str(args)

    def get(self, *args):
        return None

    def put(self, *args):
        pass


api._cache = lambda: MemoryCache()
api._merge_universe_meta = lambda rows, market: rows


class Provider:
    def call(self, method, path, body):
        if os.getenv("RESEARCH_PROVIDER_GENERATION_FIXTURE"):
            # Controlled membership/hydration transport, not financial-rule QA.
            # Keep the real API execute route and immutable quote reader active.
            if path.endswith("stock-screen"):
                codes = ["US.S0003"] if body.get("next_key") else ["US.S0001", "US.S0002", "US.OUT"]

                def criterion_results(code):
                    if not os.getenv("RESEARCH_CRITERION_EVIDENCE_FIXTURE") or code != "US.S0001":
                        return []
                    return [
                        {
                            "simple_property_result": {
                                "property": {"name": 2303},
                                "res": {"ival": "2500000"},
                            }
                        },
                        *[
                            {
                                "financial_property_result": {
                                    "property": {"name": pid, "term": 100},
                                    "res": {"ival": str(value)},
                                }
                            }
                            for pid, value in [(4606, 6000), (4219, 3000), (4107, 12000)]
                        ],
                    ]

                return {
                    "items": [{"code": code, "results": criterion_results(code)} for code in codes],
                    "pagination": {
                        "total": 4,
                        "has_more": not body.get("next_key"),
                        "next_key": None if body.get("next_key") else "fixture-page-2",
                    },
                }
            if path.endswith("stock-basicinfo"):
                return {"basic_list": [{"code": "US.WRONG", "stock_type": "STOCK"}]}
        if path.endswith("stock-screen"):
            return {"items": []}
        if path.endswith("stock-basicinfo"):
            return {"basic_list": []}
        return {}

    def snapshot(self, codes):
        if os.getenv("RESEARCH_PROVIDER_GENERATION_FIXTURE"):
            return {"snapshot_list": [{"code": "US.WRONG", "last_price": 999}]}
        return {"snapshot_list": [stock_fixtures._quote(c.split(".", 1)[-1]) for c in codes]}


api._market_client = lambda: Provider()


provider_page_attempts = {}


def execute(key="", market="US", limit=300, next_key="", **_kwargs):
    p = next(p for p in api.PRESET_SCREENERS if p["key"] == key)
    rows, _ = api._apply_filters([r.copy() for r in fixture.ROWS], p["filters"])
    rows = api._sort_rows(rows, p.get("sort", "pct"), p.get("direction", 2))
    for r in rows:
        r["criterion_values"] = {f["field"]: r.get(f["field"]) for f in p["filters"]}
    offset = int(next_key or 0)
    page = rows[offset : offset + limit]
    if os.getenv("RESEARCH_PROVIDER_PAGE_FAULT_FIXTURE") and next_key:
        identity = (key, market, next_key)
        attempt = provider_page_attempts.get(identity, 0) + 1
        provider_page_attempts[identity] = attempt
        if attempt == 1:
            return {"available": False, "reason": "Synthetic rate_limited; retry next page"}
        if attempt == 2:
            page = [rows[offset - 1], *page]
    cursor = str(offset + limit) if offset + limit < len(rows) else ""
    return {
        "available": True,
        "rows": page,
        "filters": p["filters"],
        "name": p["name"],
        "pending": [],
        "sort": p.get("sort", "pct"),
        "direction": p.get("direction", 2),
        "result_limit": limit,
        "provider_total": len(rows),
        "next_key": cursor,
        "possibly_truncated": bool(cursor),
        "retrieved_at": now,
    }


if not os.getenv("RESEARCH_PROVIDER_GENERATION_FIXTURE"):
    api.screener_execute = execute
    for route in api.app.routes:
        if getattr(route, "path", None) == "/api/screener/execute":
            route.endpoint = execute
            route.dependant.call = execute
api.market_state = lambda: {"available": False}
for route in api.app.routes:
    if getattr(route, "path", None) == "/api/market/state":
        route.endpoint = api.market_state
        route.dependant.call = api.market_state
# Offline settings fault injection: actual /api/models route, no vendor calls.
if os.getenv("RESEARCH_SETTINGS_FIXTURE"):
    catalog_ready = os.getenv("RESEARCH_SETTINGS_FIXTURE") == "unknown"

    def preview_catalog(force=False):
        global catalog_ready
        catalog_ready = catalog_ready or force
        if not catalog_ready:
            return None, "Synthetic catalog outage"
        return {
            "models": [
                {
                    "id": "openrouter/auto",
                    "in_per_m": -1,
                    "out_per_m": -1,
                    "est_per_run": -1,
                    "free": False,
                },
                {
                    "id": "fixture/free",
                    "in_per_m": 0,
                    "out_per_m": 0,
                    "est_per_run": 0,
                    "free": True,
                },
                {
                    "id": "fixture/paid",
                    "in_per_m": 2,
                    "out_per_m": 10,
                    "est_per_run": 5,
                    "free": False,
                },
            ],
            "count": 3,
            "stale": False,
            "est_run_basis": "synthetic fixture mix",
        }, None

    api.CATALOG.try_get = preview_catalog
# Recorded chart fixtures end in 2025. Shift only this offline harness's
# synthetic bars to the current date so range clipping can be exercised.
recorded_kline = stock_fixtures._kline


def preview_kline(*args, **kwargs):
    bars = recorded_kline(*args, **kwargs)
    if bars:
        shift = int(datetime.now(timezone.utc).timestamp() * 1000) - bars[-1]["time_key"]
        for bar in bars:
            bar["time_key"] += shift
    return bars


stock_fixtures._kline = preview_kline
orig = stock_fixtures.payload
stock_fixtures.payload = lambda key, sym: orig(
    key, sym.split(".", 1)[-1] if sym.startswith(("US.", "HK.")) else sym
)
# Owner-private captures built by the actual builder; only transport/data are synthetic.
if os.getenv("RESEARCH_PRIVATE_HISTORY_FIXTURE") == "1":
    from tradingagents_api import capture_service

    definition, digest = research_schedules._definition(change_definition.model_dump())
    schedule = {
        "id": "00000000-0000-4000-8000-000000000009",
        "owner_id": PREVIEW_OWNER,
        "definition": definition,
        "definition_hash": digest,
        "name": "Synthetic private screen",
        "cadence": {
            "timezone": "America/New_York",
            "hour": 16,
            "minute": 15,
            "weekdays": [0, 1, 2, 3, 4],
        },
        "enabled": False,
        "revision": 1,
        "next_due_at": None,
    }
    api.db._t("research_capture_schedules").append(schedule)
    original_screener = api.screener
    try:
        for side in ("before", "after"):
            rows = [r.copy() for r in fixture.ROWS]
            if side == "after":
                rows = [r for r in rows if r["code"] != "US.S0001"]
                rows.append(
                    {
                        **next(r for r in fixture.ROWS if r["stock_type"] == "STOCK"),
                        "code": "US.S2001",
                        "symbol": "S2001",
                        "name": "Fixture New Company",
                    }
                )
            stamp = datetime.now(timezone.utc).isoformat()
            for r in rows:
                r.update(quote_cache_at=stamp, quote_identity_status="verified")
            api.screener = lambda rows=rows, stamp=stamp, **kw: {
                "available": True,
                "universe_loaded": True,
                "universe_as_of": stamp,
                "matched": len(rows),
                "rows": rows,
            }
            cid = str(uuid.uuid4())
            snapshot = capture_service.build(schedule, cid)
            api.db._t("research_private_captures").append(
                {
                    "id": cid,
                    "schedule_id": schedule["id"],
                    "owner_id": PREVIEW_OWNER,
                    "schedule_revision": 1,
                    "definition_hash": digest,
                    "published_at": snapshot["at"],
                    "snapshot": snapshot,
                }
            )
    finally:
        api.screener = original_screener
    stamp = datetime.now(timezone.utc).isoformat()
    api.db._t("research_capture_occurrences").append(
        {
            "id": str(uuid.uuid4()),
            "schedule_id": schedule["id"],
            "owner_id": PREVIEW_OWNER,
            "schedule_revision": 1,
            "due_at": stamp,
            "status": "failed",
            "attempts": 3,
            "retry_at": stamp,
            "updated_at": stamp,
            "error_code": "incomplete_data",
            "lease_until": None,
        }
    )
# Synthetic adapter for the actual compatible-definition HTTP routes. Native
# SQL contracts verify storage behavior separately; this is browser evidence.
if os.getenv("RESEARCH_ALIAS_DISCOVERY_FIXTURE") == "1":
    from tradingagents_api.screen_definition_identity import (
        definition_identity,
        semantic_definition,
    )

    os.environ["CAPTURE_DEFINITION_ALIASES_ENABLED"] = "1"
    alias_original_call = api.db._call

    def preview_alias_call(method, path, body=None, **kwargs):
        if path == "rpc/screen_capture_append_with_alias":
            snapshot = next(
                r["snapshot"] for r in body["p_records"] if r["id"] == body["p_capture_id"]
            )
            if (
                semantic_definition(snapshot["definition"]) != body["p_screen"]
                or definition_identity(snapshot["definition"])["sha256"] != body["p_digest"]
            ):
                raise RuntimeError("Synthetic alias mismatch")
            return alias_original_call(
                method,
                "rpc/screen_capture_append",
                body={"p_key": body["p_key"], "p_records": body["p_records"]},
                **kwargs,
            )
        if path in ("rpc/screen_capture_alias_history", "rpc/screen_capture_alias_get"):
            records = []
            for record in api.db._t("screen_captures"):
                if record["history_key"].split(":")[1] != body["p_namespace"]:
                    continue
                snapshot = record["snapshot"]
                definition = snapshot.get("definition")
                if record["history_key"] != body["p_raw_key"] and (
                    not definition
                    or semantic_definition(definition) != body["p_screen"]
                    or definition_identity(definition)["sha256"] != body["p_digest"]
                ):
                    continue
                records.append(record)
            grouped = {}
            for record in records:
                grouped.setdefault(record["id"], []).append(record)
            selected = []
            for cid, copies in grouped.items():
                copies.sort(key=lambda r: (r["history_key"] != body["p_raw_key"], r["history_key"]))
                record = copies[0]
                if path == "rpc/screen_capture_alias_get":
                    if cid == body["p_id"]:
                        return [
                            {
                                "history_key": record["history_key"],
                                "id": cid,
                                "snapshot": record["snapshot"],
                                "copies": len(copies),
                                "conflicting": any(
                                    r["snapshot"] != record["snapshot"] for r in copies
                                ),
                            }
                        ]
                else:
                    selected.append(
                        {
                            **api._snapshot_meta(record["snapshot"]),
                            "history_key": record["history_key"],
                            "copies": len(copies),
                        }
                    )
            if path == "rpc/screen_capture_alias_get":
                return []
            selected.sort(key=lambda r: (r["at"], r["id"]), reverse=True)
            return selected[body["p_offset"] : body["p_offset"] + body["p_limit"] + 1]
        return alias_original_call(method, path, body=body, **kwargs)

    api.db._call = preview_alias_call
os.chdir(tempfile.mkdtemp(prefix="research-preview-"))
# One delayed HTTP failure on the first Exited request, then real-route recovery.
if os.getenv("RESEARCH_COMPARISON_FAILURE_FIXTURE"):
    from functools import wraps

    original_changes = api.screen_changes
    preview_changes_failed = False

    @wraps(original_changes)
    def failing_changes(*args, **kwargs):
        global preview_changes_failed
        if kwargs.get("status") == "exited" and not preview_changes_failed:
            preview_changes_failed = True
            time.sleep(2)
            raise HTTPException(503, "Synthetic comparison transport interruption")
        return original_changes(*args, **kwargs)

    api.screen_changes = failing_changes
    for route in api.app.routes:
        if getattr(route, "path", None) == "/api/screener/changes":
            route.endpoint = failing_changes
            route.dependant.call = failing_changes
# One chart source failure per symbol/window followed by recorded recovery.
# Opt-in, offline only; exercises the real API route and browser Retry action.
if os.getenv("RESEARCH_CHART_FAILURE_FIXTURE"):
    original_stock_fetch = api._stock_fetch
    failed_chart_keys = set()

    def preview_chart_failure(key, symbol, category, fetch):
        identity = (key, symbol)
        if (key == "intraday" or key.startswith("candles:")) and identity not in failed_chart_keys:
            failed_chart_keys.add(identity)
            mode = os.environ["RESEARCH_CHART_FAILURE_FIXTURE"]
            if mode == "failed":
                raise HTTPException(503, "Synthetic chart transport interruption")
            if mode == "empty":
                return (
                    {"kline_list": []}
                    if key.startswith("candles:")
                    else {"available": True, "section_list": []}
                )
            return {"available": False, "reason": "Synthetic chart source unavailable"}
        return original_stock_fetch(key, symbol, category, fetch)

    api._stock_fetch = preview_chart_failure
print(
    "Synthetic offline research workspace on port " + os.getenv("RESEARCH_PREVIEW_PORT", "8890"),
    flush=True,
)
uvicorn.run(
    api.app,
    host="127.0.0.1",
    port=int(os.getenv("RESEARCH_PREVIEW_PORT", "8890")),
    log_level="warning",
)
