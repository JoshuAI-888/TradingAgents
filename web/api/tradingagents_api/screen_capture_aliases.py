"""Trusted manual-capture alias writes; rollout remains off until qualification.

No authenticated-owner schedules or team scopes are included here. The original
append RPC and raw history keys remain the rollback path.
"""

import os

from .screen_definition_identity import (
    definition_identity,
    semantic_definition,
    validate_definition_identity,
)


def append_capture_batch(db, key, records, snapshot):
    body = {"p_key": key, "p_records": records}
    if os.getenv("CAPTURE_DEFINITION_ALIASES_ENABLED") != "1":
        return db._call("POST", "rpc/screen_capture_append", body=body)
    validate_definition_identity(snapshot)
    identity = definition_identity(snapshot["definition"])
    return db._call(
        "POST",
        "rpc/screen_capture_append_with_alias",
        body={
            **body,
            "p_capture_id": snapshot["id"],
            "p_digest": identity["sha256"],
            "p_screen": semantic_definition(snapshot["definition"]),
        },
    )


def backfill_page(db, namespace, *, cursor=None, page_size=20, apply=False):
    """One resumable metadata page. A complete scan is not a qualified cutover.

    Concurrent legacy imports can land behind the cursor. Drain old writers and
    repeat a complete scan after enabling atomic alias publication before
    claiming coverage. Unknown legacy definitions remain separate and visible
    through their original history keys.
    """
    import json
    import re

    from .main import ScreenDefinition

    if (
        not isinstance(namespace, str)
        or not re.fullmatch(r"[a-f0-9]{16,64}", namespace)
        or type(page_size) is not int
        or not 1 <= page_size <= 100
        or type(apply) is not bool
    ):
        raise ValueError("Invalid backfill scope")

    def position(row):
        key = row.get("history_key")
        capture_id = row.get("capture_id")
        if (
            not isinstance(key, str)
            or not re.fullmatch(r"screen_history:" + namespace + r":[a-f0-9]{64}", key)
            or not isinstance(capture_id, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", capture_id)
        ):
            raise ValueError("Backfill identity is invalid or outside its namespace")
        return key, capture_id

    after = position(cursor) if cursor is not None else (None, None)
    rows = db._call(
        "POST",
        "rpc/screen_capture_alias_backfill_page",
        body={
            "p_namespace": namespace,
            "p_after_key": after[0],
            "p_after_id": after[1],
            "p_limit": page_size,
        },
    )
    if (
        not isinstance(rows, list)
        or len(rows) > page_size + 1
        or any(not isinstance(row, dict) for row in rows)
    ):
        raise RuntimeError("Unconfirmed backfill page")
    positions = [position(row) for row in rows]
    if positions != sorted(set(positions)) or (
        cursor is not None and any(p <= after for p in positions)
    ):
        raise RuntimeError("Backfill paging is inconsistent")
    summary = {
        "scanned": 0,
        "eligible": 0,
        "inserted": 0,
        "already_mapped": 0,
        "unprovable": 0,
        "apply": apply,
        "has_more": len(rows) > page_size,
        "next_cursor": None,
        "scope": "deployment_shared_manual",
    }
    for row in rows[:page_size]:
        summary["scanned"] += 1
        definition = row.get("definition")
        try:
            if (
                not isinstance(definition, dict)
                or set(definition) != set(ScreenDefinition.model_fields)
                or len(json.dumps(definition, allow_nan=False).encode("utf-8")) > 32768
                or type(row.get("identity_present")) is not bool
            ):
                raise ValueError("Original definition is incomplete")
            ScreenDefinition.model_validate(definition, strict=True)
            supplied = {"definition": definition}
            if row["identity_present"]:
                supplied["definition_identity"] = row.get("definition_identity")
            validate_definition_identity(supplied)
            identity = definition_identity(definition)
            canonical = semantic_definition(definition)
        except (ValueError, TypeError):
            summary["unprovable"] += 1
            continue
        summary["eligible"] += 1
        if apply:
            inserted = db._call(
                "POST",
                "rpc/screen_capture_definition_alias_register",
                body={
                    "p_key": row["history_key"],
                    "p_capture_id": row["capture_id"],
                    "p_digest": identity["sha256"],
                    "p_screen": canonical,
                },
            )
            if type(inserted) is not bool:
                raise RuntimeError("Alias registration was not confirmed")
            summary["inserted" if inserted else "already_mapped"] += 1
    if rows[:page_size]:
        last = rows[min(len(rows), page_size) - 1]
        summary["next_cursor"] = {
            "history_key": last["history_key"],
            "capture_id": last["capture_id"],
        }
    return summary


def discovery_parameters(key, definition):
    import re

    match = (
        re.fullmatch(r"screen_history:([a-f0-9]{16,64}):[a-f0-9]{64}", key)
        if isinstance(key, str)
        else None
    )
    if not match:
        raise ValueError("Invalid history namespace")
    return {
        "p_namespace": match.group(1),
        "p_digest": definition_identity(definition)["sha256"],
        "p_screen": semantic_definition(definition),
        "p_raw_key": key,
    }


def alias_history_page(db, key, definition, *, limit=100, offset=0):
    """Metadata only; copies >1 require exact detail validation before inference."""
    import re
    from datetime import datetime

    if (
        type(limit) is not int
        or not 1 <= limit <= 100
        or type(offset) is not int
        or not 0 <= offset <= 40000
    ):
        raise ValueError("Invalid history discovery pagination")
    params = discovery_parameters(key, definition)
    rows = db._call(
        "POST",
        "rpc/screen_capture_alias_history",
        body={**params, "p_limit": limit, "p_offset": offset},
    )
    if not isinstance(rows, list) or len(rows) > limit + 1:
        raise RuntimeError("History discovery page was not confirmed")
    seen = set()
    order = []
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("history_key"), str)
            or not re.fullmatch(
                r"screen_history:" + params["p_namespace"] + r":[a-f0-9]{64}", row["history_key"]
            )
            or not isinstance(row.get("id"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", row["id"])
            or row["id"] in seen
            or type(row.get("copies")) is not int
            or row["copies"] < 1
            or type(row.get("complete")) is not bool
            or type(row.get("members")) is not int
            or row["members"] < 0
            or type(row.get("version")) is not int
            or row["version"] < 1
            or not isinstance(row.get("at"), str)
        ):
            raise RuntimeError("History discovery metadata is inconsistent")
        try:
            stamp = datetime.fromisoformat(row["at"].replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                raise ValueError("Missing timezone")
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("History discovery time is invalid") from None
        order.append((stamp, row["id"]))
        seen.add(row["id"])
    if order != sorted(order, reverse=True):
        raise RuntimeError("History discovery ordering is inconsistent")
    return list(reversed(rows[:limit])), len(rows) > limit


def alias_capture_get(db, key, definition, capture_id):
    import re

    if not isinstance(capture_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", capture_id):
        raise ValueError("Invalid capture identity")
    params = discovery_parameters(key, definition)
    rows = db._call("POST", "rpc/screen_capture_alias_get", body={**params, "p_id": capture_id})
    if not isinstance(rows, list) or len(rows) > 1:
        raise RuntimeError("Capture discovery was not confirmed")
    if not rows:
        return None
    row = rows[0]
    if (
        not isinstance(row, dict)
        or row.get("id") != capture_id
        or not isinstance(row.get("history_key"), str)
        or not re.fullmatch(
            r"screen_history:" + params["p_namespace"] + r":[a-f0-9]{64}", row["history_key"]
        )
        or type(row.get("conflicting")) is not bool
        or type(row.get("copies")) is not int
        or row["copies"] < 1
        or not isinstance(row.get("snapshot"), dict)
    ):
        raise RuntimeError("Discovered capture scope is inconsistent")
    if row["conflicting"]:
        raise ValueError("Capture identity has divergent immutable evidence across histories")
    snapshot = row["snapshot"]
    validate_definition_identity(snapshot)
    if snapshot.get("id", capture_id) != capture_id:
        raise ValueError("Discovered capture identity differs from its record")
    # The requested raw key can include unverifiable legacy records. Keep these
    # discoverable only at that original key; alias records must prove semantics.
    if (
        row["history_key"] != key
        and semantic_definition(snapshot.get("definition")) != params["p_screen"]
    ):
        raise ValueError("Discovered capture definition is incompatible")
    return row
