"""Private notes tied to validated immutable capture pairs, never company-wide status."""

import os
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from tradingagents_worker.db import Db

from .research_auth import ResearchOwner, require_research_owner

router = APIRouter(prefix="/api/research/pair-reviews", tags=["Private research"])
db = Db()


class PairIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition: dict
    previous_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    current_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")


class ReviewAnchor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    previous_history_key: str = Field(pattern=r"^screen_history:[a-f0-9]{16,64}:[a-f0-9]{64}$")
    current_history_key: str = Field(pattern=r"^screen_history:[a-f0-9]{16,64}:[a-f0-9]{64}$")


class ReviewIn(PairIn):
    code: str = Field(pattern=r"^(US|HK|AU|SH|SZ|SG)\.[A-Z0-9][A-Z0-9._-]{0,30}$")
    revision: int = Field(ge=0, strict=True)
    note: str = Field(max_length=4000)
    review_status: Literal["unreviewed", "in_review", "reviewed"]
    review_anchor: ReviewAnchor | None = None


def _call(method, path, **kwargs):
    try:
        return db._call(method, path, **kwargs) or []
    except (RuntimeError, OSError):
        raise HTTPException(
            503, "Pair review storage is temporarily unavailable. Your draft has not been saved."
        ) from None


def _variants_enabled():
    return all(
        os.getenv(flag) == "1"
        for flag in (
            "DUPLICATE_CAPTURE_REVIEW_SCOPES_ENABLED",
            "CAPTURE_DEFINITION_ALIASES_ENABLED",
            "CROSS_HISTORY_PAIR_REVIEWS_ENABLED",
        )
    )


def _variants(owner, key, previous, current):
    from .review_scope_variants import read_variants

    before, after = key if isinstance(key, tuple) else (key, key)
    try:
        return read_variants(db, owner.id, before, after, previous, current)
    except ValueError:
        raise HTTPException(409, "Review scope could not be qualified; keep your draft.") from None
    except (RuntimeError, OSError):
        raise HTTPException(
            503, "Original review scope discovery is unavailable; keep your draft."
        ) from None


def _anchored(row):
    before = row.get("previous_history_key", row.get("history_key"))
    after = row.get("current_history_key", row.get("history_key"))
    return {**row, "review_anchor": {"previous_history_key": before, "current_history_key": after}}


def _lookup(owner, state=None):
    def read(key, previous, current):
        if _variants_enabled():
            discovered = _variants(owner, key, previous, current)
            if discovered["alias_qualified"]:
                import hashlib
                import json

                if state is not None:
                    state["review_revision_hash"] = hashlib.sha256(
                        json.dumps(
                            discovered["variants"], sort_keys=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest()
                    state["review_scope_conflicts"] = len(discovered["ambiguous_codes"])
                return {
                    code: _anchored(rows[0])
                    if len(rows) == 1
                    else {
                        "code": code,
                        "revision": 0,
                        "note": "",
                        "review_status": "scope_conflict",
                        "scope_conflict": True,
                        "review_variants": [_anchored(row) for row in rows],
                    }
                    for code, rows in discovered["variants"].items()
                }
        body = {"p_owner": owner.id, "p_previous": previous, "p_current": current}
        if isinstance(key, tuple):
            body.update(p_previous_key=key[0], p_current_key=key[1])
            rpc = "research_cross_history_pair_review_read"
        else:
            body["p_key"] = key
            rpc = "research_pair_review_read"
        payload = _call("POST", "rpc/" + rpc, body=body)
        rows = payload.get("reviews") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise HTTPException(
                503, "Pair review state was not confirmed; no partial review returned."
            )
        if len(rows) > 40000:
            raise HTTPException(
                409, "Review state exceeds supported scope; no partial review returned."
            )
        if state is not None:
            import hashlib
            import json

            state["review_revision_hash"] = hashlib.sha256(
                json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
        return {row["code"]: row for row in rows}

    return read


def _pair(definition, previous, current, **kwargs):
    import json

    from .main import _screen_changes

    result = _screen_changes(json.dumps(definition), previous, current, **kwargs)
    if not result["comparable"]:
        raise HTTPException(409, "This pair is not comparable; no review state applied.")
    return result


@router.get("")
def reviews(
    definition: str,
    previous_id: str,
    current_id: str,
    status: str = "all",
    q: str = "",
    sort: str = "symbol",
    direction: int = 1,
    review_status: Literal["all", "unreviewed", "in_review", "reviewed", "scope_conflict"] = "all",
    limit: int = 100,
    offset: int = 0,
    history_offset: int = 0,
    next_code: str | None = None,
    code: str | None = None,
    next_review: bool = False,
    owner: ResearchOwner = Depends(require_research_owner),
):
    import json

    try:
        pair = PairIn(
            definition=json.loads(definition), previous_id=previous_id, current_id=current_id
        )
    except ValueError:
        raise HTTPException(422, "Invalid capture pair.") from None
    for canonical in (next_code, code):
        if canonical is None:
            continue
        from .research_lists import ItemIn

        try:
            ItemIn(code=canonical)
        except ValueError:
            raise HTTPException(422, "Invalid canonical review code.") from None
    state = {}
    result = _pair(
        pair.definition,
        pair.previous_id,
        pair.current_id,
        status=status,
        q=q,
        sort=sort,
        direction=direction,
        limit=limit,
        offset=offset,
        history_offset=history_offset,
        review_lookup=_lookup(owner, state),
        review_status=review_status,
        next_review_code=(next_code or "") if next_review else next_code,
        review_code=code,
    )
    return {
        **result,
        **state,
        "review_scope": "private_capture_pair"
        if result.get("review_history_key", True)
        or result.get("review_contract") == "cross_history"
        else "unavailable",
        "owner_id": owner.id,
        "review_filter": review_status,
    }


@router.patch("")
def save(inp: ReviewIn, owner: ResearchOwner = Depends(require_research_owner)):
    from .main import ScreenDefinition, _snapshot_key

    pair = _pair(inp.definition, inp.previous_id, inp.current_id, review_code=inp.code, limit=1)
    if not pair["rows"]:
        raise HTTPException(404, "Instrument is absent from this comparison pair.")
    key = pair.get(
        "review_history_key", _snapshot_key(ScreenDefinition.model_validate(inp.definition))
    )
    if pair.get("review_contract") == "cross_history":
        key = (pair["previous_history_key"], pair["current_history_key"])
    if key is None:
        raise HTTPException(
            409,
            "Private review for cross-history captures is pending. Existing notes retain their original scope.",
        )
    if _variants_enabled():
        discovered = _variants(owner, key, inp.previous_id, inp.current_id)
        if discovered["alias_qualified"]:
            variants = discovered["variants"].get(inp.code, [])
            selected = None
            if inp.review_anchor is not None:
                wanted = inp.review_anchor.model_dump()
                selected = next(
                    (row for row in variants if _anchored(row)["review_anchor"] == wanted), None
                )
                if selected is None:
                    raise HTTPException(
                        409,
                        "This original review scope is no longer available; keep your draft and reload.",
                    )
            elif len(variants) == 1:
                selected = variants[0]
            elif len(variants) > 1:
                raise HTTPException(
                    409,
                    "Several original reviews exist. Choose the original review scope before saving; all notes remain unchanged.",
                )
            if selected is not None:
                before, after = selected["previous_history_key"], selected["current_history_key"]
                key = before if before == after else (before, after)
        elif inp.review_anchor is not None:
            raise HTTPException(409, "Original review scope is unqualified; keep your draft.")
    elif inp.review_anchor is not None:
        raise HTTPException(409, "Original review scope selection is unavailable; keep your draft.")
    body = {
        "p_owner": owner.id,
        "p_previous": inp.previous_id,
        "p_current": inp.current_id,
        "p_code": inp.code,
        "p_revision": inp.revision,
        "p_note": inp.note,
        "p_status": inp.review_status,
    }
    if isinstance(key, tuple):
        body.update(p_previous_key=key[0], p_current_key=key[1])
        rpc = "research_cross_history_pair_review_save"
    else:
        body["p_key"] = key
        rpc = "research_pair_review_save"
    rows = _call("POST", "rpc/" + rpc, body=body)
    if not rows:
        raise HTTPException(
            409,
            "This pair review changed or is unavailable. Keep your draft and reload before saving.",
        )
    return {
        "review": _anchored(rows[0]) if _variants_enabled() else rows[0],
        "review_scope": "private_capture_pair",
    }
