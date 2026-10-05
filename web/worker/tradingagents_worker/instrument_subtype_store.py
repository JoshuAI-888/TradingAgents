"""Service-only bounded cache reads and exact-replay optimistic publication."""

import uuid
from datetime import datetime, timedelta, timezone

from .instrument_subtypes import BATCH_CAP, COHORT_CAP, _cache, qualified_context
from .yf_enrich import to_yahoo_symbol


def read_cache(db, market, now=None):
    if market not in ("US", "HK"):
        raise ValueError("Unsupported subtype market")
    now = now or datetime.now(timezone.utc)
    rows = db.select_all(
        "instrument_subtype_cache",
        {"market": "eq." + market, "order": "code.asc"},
        "market,code,revision,record",
        cap=COHORT_CAP + 1,
    )
    if len(rows) > COHORT_CAP:
        raise ValueError("Subtype cache exceeds supported cohort")
    records, revisions = {}, {}
    for row in rows:
        code = row.get("code")
        if (
            row.get("market") != market
            or not to_yahoo_symbol(code, market)
            or code in records
            or type(row.get("revision")) is not int
            or row["revision"] < 1
        ):
            raise ValueError("Invalid subtype cache row")
        record = _cache(row.get("record"), code, now)
        if record is None:
            raise ValueError("Absent stored subtype record")
        records[code], revisions[code] = record, row["revision"]
    return records, revisions


def contexts(db, market, now=None):
    now = now or datetime.now(timezone.utc)
    records, _ = read_cache(db, market, now)
    return {
        code: evidence
        for code, record in records.items()
        if (evidence := qualified_context(record, code, now)) is not None
    }


def publish(db, market, updates, revisions, now=None, *, run_id):
    token = str(uuid.UUID(run_id))
    if token != run_id:
        raise ValueError("Invalid subtype run identity")
    if market not in ("US", "HK") or not isinstance(updates, dict) or len(updates) > BATCH_CAP:
        raise ValueError("Invalid subtype publication scope")
    now = now or datetime.now(timezone.utc)
    prepared = []
    for code, record in sorted(updates.items()):
        revision = revisions.get(code, 0)
        if not to_yahoo_symbol(code, market) or type(revision) is not int or revision < 0:
            raise ValueError("Invalid subtype publication identity or revision")
        valid = _cache(record, code, now)
        if valid is None:
            raise ValueError("Absent subtype publication")
        prepared.append(
            {
                "p_run": token,
                "p_market": market,
                "p_code": code,
                "p_revision": revision,
                "p_record": valid,
            }
        )
    saved, conflicts = [], []
    for body in prepared:
        result = db._call("POST", "rpc/instrument_subtype_save_leased", body=body)
        if result == []:
            conflicts.append(body["p_code"])
            continue
        if not isinstance(result, list) or len(result) != 1:
            raise ValueError("Invalid subtype publication response")
        row = result[0]
        if row != {
            "market": market,
            "code": body["p_code"],
            "revision": body["p_revision"] + 1,
            "record": body["p_record"],
        }:
            raise ValueError("Conflicting subtype publication receipt")
        saved.append(body["p_code"])
    return {"saved": saved, "conflicts": conflicts}


def claim(db, market, run_id, now=None):
    token = str(uuid.UUID(run_id))
    if token != run_id or market not in ("US", "HK"):
        raise ValueError("Invalid subtype lease identity")
    receipt = db._call(
        "POST", "rpc/instrument_subtype_claim", body={"p_market": market, "p_run": token}
    )
    if receipt is None:
        return None
    if (
        not isinstance(receipt, dict)
        or set(receipt) != {"id", "market", "started_at", "expires_at"}
        or receipt["id"] != token
        or receipt["market"] != market
    ):
        raise ValueError("Invalid subtype lease receipt")
    try:
        start = datetime.fromisoformat(receipt["started_at"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(receipt["expires_at"].replace("Z", "+00:00"))
        if start.tzinfo is None or end.tzinfo is None or end - start != timedelta(seconds=330):
            raise ValueError()
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("Invalid subtype lease clock") from error
    return receipt


def release(db, market, run_id):
    token = str(uuid.UUID(run_id))
    if token != run_id or market not in ("US", "HK"):
        raise ValueError("Invalid subtype release identity")
    result = db._call(
        "POST", "rpc/instrument_subtype_release", body={"p_market": market, "p_run": token}
    )
    if type(result) is not bool:
        raise ValueError("Invalid subtype release receipt")
    return result
