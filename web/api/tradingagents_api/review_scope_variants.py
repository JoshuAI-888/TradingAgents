"""Owner-private original anchors across exact duplicate capture evidence.

No representative preference, merging, note writes or revision renumbering.
Route and explicit variant-selection integration are separately qualified.
"""

import re
import uuid
from copy import deepcopy
from datetime import datetime

CAP = 40000


def read_variants(db, owner_id, previous_key, current_key, previous_id, current_id):
    if not isinstance(owner_id, str) or str(uuid.UUID(owner_id)) != owner_id:
        raise ValueError("Invalid review owner identity")
    namespace = None
    for key in (previous_key, current_key):
        match = (
            re.fullmatch(r"screen_history:([a-f0-9]{16,64}):[a-f0-9]{64}", key)
            if isinstance(key, str)
            else None
        )
        if not match or namespace is not None and match.group(1) != namespace:
            raise ValueError("Invalid review namespace")
        namespace = match.group(1)
    if previous_id == current_id or any(
        not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", cid)
        for cid in (previous_id, current_id)
    ):
        raise ValueError("Invalid review capture identities")
    payload = db._call(
        "POST",
        "rpc/research_duplicate_pair_review_scopes",
        body={
            "p_owner": owner_id,
            "p_previous_key": previous_key,
            "p_current_key": current_key,
            "p_previous": previous_id,
            "p_current": current_id,
        },
    )
    if (
        not isinstance(payload, dict)
        or set(payload) != {"alias_qualified", "reviews"}
        or type(payload["alias_qualified"]) is not bool
        or not isinstance(payload["reviews"], list)
    ):
        raise RuntimeError("Review scope discovery unconfirmed")
    rows = payload["reviews"]
    if len(rows) > CAP:
        raise ValueError("Review scope exceeds supported bound")
    if not payload["alias_qualified"] and rows:
        raise RuntimeError("Unqualified review scopes supplied")
    variants = {}
    seen = set()
    positions = []
    for row in rows:
        fields = {
            "owner_id",
            "previous_history_key",
            "current_history_key",
            "previous_id",
            "current_id",
            "code",
            "note",
            "review_status",
            "revision",
            "updated_at",
            "review_contract",
        }
        if (
            not isinstance(row, dict)
            or set(row) != fields
            or row["owner_id"] != owner_id
            or row["previous_id"] != previous_id
            or row["current_id"] != current_id
        ):
            raise RuntimeError("Review variant scope is inconsistent")
        keys = (row["previous_history_key"], row["current_history_key"])
        if any(
            not isinstance(key, str)
            or not re.fullmatch(r"screen_history:" + namespace + r":[a-f0-9]{64}", key)
            for key in keys
        ):
            raise RuntimeError("Review variant namespace is inconsistent")
        contract = "same_history" if keys[0] == keys[1] else "cross_history"
        if (
            row["review_contract"] != contract
            or not isinstance(row["code"], str)
            or not re.fullmatch(r"(US|HK|AU|SH|SZ|SG)\.[A-Z0-9][A-Z0-9._-]{0,30}", row["code"])
            or type(row["revision"]) is not int
            or row["revision"] < 1
            or not isinstance(row["note"], str)
            or len(row["note"]) > 4000
            or row["review_status"] not in ("unreviewed", "in_review", "reviewed")
        ):
            raise RuntimeError("Invalid review variant content")
        try:
            if datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00")).tzinfo is None:
                raise ValueError()
        except (AttributeError, TypeError, ValueError):
            raise RuntimeError("Invalid review variant clock") from None
        position = (row["code"], *keys)
        if position in seen:
            raise RuntimeError("Duplicate review variant anchor")
        positions.append(position)
        seen.add(position)
        variants.setdefault(row["code"], []).append(deepcopy(row))
    if positions != sorted(positions):
        raise RuntimeError("Review variant ordering is inconsistent")
    return {
        "alias_qualified": payload["alias_qualified"],
        "variants": variants,
        "ambiguous_codes": [code for code, records in variants.items() if len(records) > 1],
    }
