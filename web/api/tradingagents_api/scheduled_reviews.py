"""Owner-private scheduled pair review, with bounded visible-note reads."""

import re
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from . import research_schedules as schedules
from .research_auth import ResearchOwner, require_research_owner

router = APIRouter(prefix="/api/research/capture-schedules", tags=["Private research"])
STATUSES = {"unreviewed", "in_review", "reviewed"}


class ReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    previous_id: UUID
    current_id: UUID
    code: str = Field(pattern=r"^(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}$", strict=True)
    revision: int = Field(ge=0, strict=True)
    note: str = Field(max_length=4000, strict=True)
    review_status: Literal["unreviewed", "in_review", "reviewed"]


def _call(path, body):
    try:
        return schedules.db._call("POST", path, body=body)
    except (RuntimeError, OSError):
        raise HTTPException(
            503,
            "Private pair review storage is unavailable. Keep your draft; no save was confirmed.",
        ) from None


def _state(owner, sid, previous, current, codes=None, expected=None):
    payload = _call(
        "rpc/research_scheduled_pair_review_read",
        {
            "p_owner": owner.id,
            "p_schedule": str(sid),
            "p_previous": str(previous),
            "p_current": str(current),
            "p_codes": codes or [],
            "p_expected_hash": expected,
        },
    )
    if (
        not isinstance(payload, dict)
        or type(payload.get("confirmed")) is not bool
        or not isinstance(payload.get("revision_hash"), str)
        or not re.fullmatch(r"[a-f0-9]{64}", payload["revision_hash"])
    ):
        raise HTTPException(503, "Private pair review state was not confirmed.")
    if payload["confirmed"] is not True or expected and payload["revision_hash"] != expected:
        raise HTTPException(409, "Pair review changed during loading. Keep your draft and reload.")
    rows = payload.get("notes" if expected is not None else "reviews")
    if not isinstance(rows, list) or len(rows) > (len(codes or []) if expected else 40000):
        raise HTTPException(503, "Private pair review state exceeds the confirmed scope.")
    seen = set()
    for row in rows:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("code"), str)
            or not re.fullmatch(r"(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}", row["code"])
            or row["code"] in seen
            or type(row.get("revision")) is not int
            or row["revision"] < 1
            or not isinstance(row.get("review_status"), str)
            or row["review_status"] not in STATUSES
        ):
            raise HTTPException(503, "Private pair review state is invalid.")
        if expected is not None and (
            row["code"] not in codes
            or not isinstance(row.get("note"), str)
            or len(row["note"]) > 4000
        ):
            raise HTTPException(503, "Private pair note scope is invalid.")
        seen.add(row["code"])
    fields = (
        ("code", "revision", "review_status", "note")
        if expected is not None
        else ("code", "revision", "review_status")
    )
    return payload, {row["code"]: {k: row[k] for k in fields} for row in rows}


@router.get("/{schedule_id}/pair-reviews")
def reviews(
    schedule_id: UUID,
    previous_id: UUID,
    current_id: UUID,
    status: str = "all",
    q: str = Query(default="", max_length=100),
    sort: str = "symbol",
    direction: int = 1,
    review_status: Literal["all", "unreviewed", "in_review", "reviewed"] = "all",
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=40000),
    next_code: str | None = None,
    next_review: bool = False,
    code: str | None = None,
    owner: ResearchOwner = Depends(require_research_owner),
):
    if any(
        value is not None and not re.fullmatch(r"(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}", value)
        for value in (next_code, code)
    ):
        raise HTTPException(422, "Invalid canonical review identity.")
    parent = schedules._history_parent(schedule_id, owner)
    state = {}
    lookup = {}

    def read(key, previous, current):
        payload, rows = _state(owner, schedule_id, previous_id, current_id)
        state["hash"] = payload["revision_hash"]
        lookup.update(rows)
        return {code: {**row, "note": None} for code, row in rows.items()}

    result = schedules._private_changes(
        schedule_id,
        previous_id,
        current_id,
        owner,
        parent,
        status=status,
        q=q,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
        review_lookup=read,
        review_status=review_status,
        next_review_code=(next_code or "") if next_review else next_code,
        review_code=code,
    )
    if not result["comparable"]:
        raise HTTPException(409, "Private capture pair is not comparable; no review state applied.")
    codes = [row["code"] for row in result["rows"]]
    if codes:
        _, notes = _state(owner, schedule_id, previous_id, current_id, codes, state["hash"])
        for row in result["rows"]:
            stored = lookup.get(row["code"])
            note = notes.get(row["code"])
            if stored is not None and (
                note is None
                or note["revision"] != stored["revision"]
                or note["review_status"] != stored["review_status"]
            ):
                raise HTTPException(503, "Visible review notes were not confirmed.")
            if stored is None and note is not None:
                raise HTTPException(409, "Pair review changed during loading; reload.")
            if note is not None:
                row["review"] = note
    return {**result, "review_revision_hash": state["hash"], "review_filter": review_status}


@router.patch("/{schedule_id}/pair-reviews")
def save(schedule_id: UUID, inp: ReviewIn, owner: ResearchOwner = Depends(require_research_owner)):
    parent = schedules._history_parent(schedule_id, owner)
    pair = schedules._private_changes(
        schedule_id, inp.previous_id, inp.current_id, owner, parent, review_code=inp.code, limit=1
    )
    if not pair["comparable"]:
        raise HTTPException(409, "Private capture pair is not comparable.")
    if not pair["rows"]:
        raise HTTPException(404, "Instrument is absent from this private comparison pair.")
    rows = _call(
        "rpc/research_scheduled_pair_review_save",
        {
            "p_owner": owner.id,
            "p_schedule": str(schedule_id),
            "p_previous": str(inp.previous_id),
            "p_current": str(inp.current_id),
            "p_code": inp.code,
            "p_revision": inp.revision,
            "p_note": inp.note,
            "p_status": inp.review_status,
        },
    )
    if rows == []:
        raise HTTPException(
            409, "This pair review changed. Keep your draft and reload before saving."
        )
    expected = {
        "owner_id": owner.id,
        "schedule_id": str(schedule_id),
        "previous_id": str(inp.previous_id),
        "current_id": str(inp.current_id),
        "code": inp.code,
        "revision": inp.revision + 1,
        "note": inp.note,
        "review_status": inp.review_status,
    }
    if (
        not isinstance(rows, list)
        or len(rows) != 1
        or not isinstance(rows[0], dict)
        or type(rows[0].get("revision")) is not int
        or any(rows[0].get(k) != v for k, v in expected.items())
    ):
        raise HTTPException(
            503, "Private pair review save was not confirmed. Keep your draft and reload."
        )
    return {"review": expected, "review_scope": "private_schedule_pair"}
