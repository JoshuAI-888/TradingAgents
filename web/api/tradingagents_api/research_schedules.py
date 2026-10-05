"""Owner-private capture configuration. Runtime stays gated until private dispatch exists."""

import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from tradingagents_worker.capture_schedule import CaptureCadence
from tradingagents_worker.db import Db

from .research_auth import ResearchOwner, require_research_owner

router = APIRouter(prefix="/api/research/capture-schedules", tags=["Private research"])
db = Db()


class CadenceIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    timezone: str = Field(min_length=1, max_length=80)
    hour: int = Field(ge=0, le=23)
    minute: int = Field(ge=0, le=59)
    weekdays: list[int] = Field(default_factory=lambda: [0, 1, 2, 3, 4], min_length=1, max_length=7)

    @model_validator(mode="after")
    def valid_calendar(self):
        CaptureCadence(self.timezone, self.hour, self.minute, tuple(self.weekdays))
        self.weekdays = sorted(self.weekdays)
        return self


class ScheduleIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    definition: dict
    name: str = Field(min_length=1, max_length=80)
    cadence: CadenceIn
    enabled: bool = False

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if not value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("Enter a visible schedule name")
        return value.strip()


class ScheduleEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    revision: int = Field(ge=1)
    name: str | None = None
    cadence: CadenceIn | None = None
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def clean_name(cls, value):
        if value is None:
            return value
        if len(value) > 80:
            raise ValueError("Name exceeds 80 characters")
        return ScheduleIn.clean_name(value)

    @model_validator(mode="after")
    def edits(self):
        keys = self.model_fields_set - {"revision"}
        if not keys or any(getattr(self, key) is None for key in keys):
            raise ValueError("Supply a non-null schedule edit")
        return self


def _call(method, path, **kwargs):
    try:
        rows = db._call(method, path, **kwargs)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise RuntimeError("Invalid storage response")
        return rows
    except (RuntimeError, OSError):
        raise HTTPException(
            503, "Private schedule storage is temporarily unavailable. No change was confirmed."
        ) from None


def _owned(rows, owner):
    if any(row.get("owner_id") != owner.id for row in rows):
        raise HTTPException(
            503, "Private schedule storage returned an invalid scope. No change was confirmed."
        )
    return rows


def _definition(raw):
    from .main import PRESET_SCREENERS, ScreenDefinition, _capture_criteria

    if not isinstance(raw, dict) or set(raw) - set(ScreenDefinition.model_fields):
        raise HTTPException(422, "Invalid screen definition fields.")
    try:
        spec = ScreenDefinition.model_validate(raw, strict=True)
        if spec.watchlist_only:
            raise ValueError("Shared watchlist scope is unsupported")
        preset = (
            next((p for p in PRESET_SCREENERS if p["key"] == spec.preset), None)
            if spec.preset
            else None
        )
        if spec.preset and preset is None:
            raise ValueError("Unknown preset")
        spec = _capture_criteria(spec)
        if len(spec.filters) > 60 or any(
            not isinstance(f.get("field"), str) or not 1 <= len(f["field"]) <= 64
            for f in spec.filters
        ):
            raise ValueError("Invalid criteria")
        body = {"schema_version": 1, "screen": spec.model_dump(), "preset_definition": preset}
        encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(encoded.encode()) > 32768:
            raise ValueError("Definition is too large")
    except (ValueError, TypeError):
        raise HTTPException(422, "Invalid or unsupported capture definition.") from None
    return body, hashlib.sha256(encoded.encode()).hexdigest()


def build_schedule_capture(definition, digest, capture_id):
    """Validate a pinned private definition, then build evidence without publishing.

    A changed preset catalog must not silently change an existing schedule. The
    dispatcher/publisher remains responsible for lease and revision fencing.
    """
    from .main import ScreenDefinition, build_screen_capture

    try:
        if (
            not isinstance(definition, dict)
            or type(definition.get("schema_version")) is not int
            or definition["schema_version"] != 1
        ):
            raise ValueError("Invalid definition version")
        current, current_hash = _definition(definition.get("screen"))
        if current != definition or current_hash != digest:
            raise ValueError("Definition or preset changed")
    except (ValueError, TypeError, HTTPException):
        raise HTTPException(
            409,
            "Scheduled screen definition is invalid or its original preset has changed. No capture was published.",
        ) from None
    return build_screen_capture(
        ScreenDefinition.model_validate(current["screen"], strict=True), capture_id
    )


def _save(owner, definition, digest, revision, name, cadence, enabled):
    # Infrastructure opt-in is separate from qualified user-facing automation.
    if enabled:
        raise HTTPException(
            409,
            "Scheduled captures are not enabled yet. Private runtime qualification and history workflows are incomplete.",
        )
    next_due = None
    result = _call(
        "POST",
        "rpc/research_capture_schedule_save",
        body={
            "p_owner": owner.id,
            "p_hash": digest,
            "p_revision": revision,
            "p_definition": definition,
            "p_name": name,
            "p_cadence": cadence.model_dump(),
            "p_enabled": enabled,
            "p_next": next_due,
        },
    )
    if not result:
        raise HTTPException(
            409,
            "Schedule changed or already exists. Reload the current revision; your changes were not saved.",
        )
    _owned(result, owner)
    if (
        len(result) != 1
        or result[0].get("definition_hash") != digest
        or result[0].get("definition") != definition
        or result[0].get("revision") != revision + 1
    ):
        raise HTTPException(
            503, "Private schedule save could not be confirmed. Reload before retrying."
        )
    return {"schedule": result[0], "runtime_available": False}


@router.get("")
def schedules(
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    definition: str | None = None,
    owner: ResearchOwner = Depends(require_research_owner),
):
    query = {
        "owner_id": f"eq.{owner.id}",
        "select": "*",
        "order": "created_at.asc,id.asc",
        "offset": str(offset),
        "limit": str(limit + 1),
    }
    if definition is not None:
        try:
            raw = json.loads(definition)
        except ValueError:
            raise HTTPException(422, "Invalid screen definition JSON.") from None
        _, digest = _definition(raw)
        query["definition_hash"] = "eq." + digest
    rows = _owned(_call("GET", "research_capture_schedules", query=query), owner)
    return {
        "schedules": rows[:limit],
        "has_more": len(rows) > limit,
        "offset": offset,
        "runtime_available": False,
    }


@router.post("")
def create(inp: ScheduleIn, owner: ResearchOwner = Depends(require_research_owner)):
    definition, digest = _definition(inp.definition)
    return _save(owner, definition, digest, 0, inp.name, inp.cadence, inp.enabled)


@router.patch("/{schedule_id}")
def edit(
    schedule_id: UUID, inp: ScheduleEdit, owner: ResearchOwner = Depends(require_research_owner)
):
    rows = _owned(
        _call(
            "GET",
            "research_capture_schedules",
            query={
                "id": f"eq.{schedule_id}",
                "owner_id": f"eq.{owner.id}",
                "select": "*",
                "limit": "1",
            },
        ),
        owner,
    )
    if not rows:
        raise HTTPException(404, "Capture schedule not found.")
    row = rows[0]
    try:
        if len(rows) != 1 or row.get("id") != str(schedule_id):
            raise ValueError("Invalid stored identity")
        cadence = inp.cadence or CadenceIn.model_validate(row["cadence"])
        if (
            not isinstance(row.get("definition"), dict)
            or not isinstance(row.get("definition_hash"), str)
            or not isinstance(row.get("name"), str)
            or type(row.get("enabled")) is not bool
        ):
            raise ValueError("Invalid stored schedule")
    except (ValueError, TypeError, KeyError):
        raise HTTPException(
            503, "Private schedule configuration is invalid. No change was confirmed."
        ) from None
    return _save(
        owner,
        row["definition"],
        row["definition_hash"],
        inp.revision,
        inp.name if inp.name is not None else row["name"],
        cadence,
        inp.enabled if inp.enabled is not None else row["enabled"],
    )


# Private scheduled history never falls back to deployment-shared manual history.
def _history_parent(schedule_id, owner):
    rows = _owned(
        _call(
            "GET",
            "research_capture_schedules",
            query={
                "id": f"eq.{schedule_id}",
                "owner_id": f"eq.{owner.id}",
                "select": "*",
                "limit": "1",
            },
        ),
        owner,
    )
    if not rows:
        raise HTTPException(404, "Capture schedule not found.")
    row = rows[0]
    try:
        definition = row["definition"]
        if (
            len(rows) != 1
            or row["id"] != str(schedule_id)
            or type(row.get("revision")) is not int
            or row["revision"] < 1
            or not isinstance(definition, dict)
            or type(definition.get("schema_version")) is not int
            or definition["schema_version"] != 1
        ):
            raise ValueError("Invalid definition")
        digest = hashlib.sha256(
            json.dumps(definition, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        if digest != row["definition_hash"]:
            raise ValueError("Changed definition")
        from .main import ScreenDefinition

        spec = ScreenDefinition.model_validate(definition["screen"], strict=True)
        if spec.model_dump() != definition["screen"] or spec.watchlist_only:
            raise ValueError("Invalid stored screen")
    except (ValueError, TypeError, KeyError):
        raise HTTPException(503, "Private history definition could not be verified.") from None
    return row


def _history_rows(rows, parent, owner):
    from datetime import datetime

    _owned(rows, owner)
    try:
        ids = set()
        for row in rows:
            cid = str(UUID(row["id"]))
            if (
                cid != row["id"]
                or cid in ids
                or row["schedule_id"] != parent["id"]
                or row["definition_hash"] != parent["definition_hash"]
                or type(row["schedule_revision"]) is not int
                or not 1 <= row["schedule_revision"] <= parent["revision"]
            ):
                raise ValueError("Invalid history identity")
            stamp = datetime.fromisoformat(row["published_at"].replace("Z", "+00:00"))
            if stamp.tzinfo is None or stamp.utcoffset() is None:
                raise ValueError("Missing publication timezone")
            ids.add(cid)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(503, "Private history scope could not be verified.") from None
    return rows


_CAPTURE_ERRORS = {
    "provider_unavailable",
    "incomplete_data",
    "storage_unconfirmed",
    "worker_interrupted",
    "definition_changed",
    "lease_exhausted",
    "schedule_changed",
}


@router.get("/{schedule_id}/status")
def capture_status(schedule_id: UUID, owner: ResearchOwner = Depends(require_research_owner)):
    from datetime import datetime, timezone

    parent = _history_parent(schedule_id, owner)
    columns = "id,schedule_id,owner_id,schedule_revision,due_at,status,attempts,retry_at,updated_at,error_code,lease_until"
    rows = _owned(
        _call(
            "GET",
            "research_capture_occurrences",
            query={
                "schedule_id": f"eq.{schedule_id}",
                "owner_id": f"eq.{owner.id}",
                "select": columns,
                "order": "due_at.desc,id.desc",
                "limit": "1",
            },
        ),
        owner,
    )
    latest = None
    try:
        if len(rows) > 1:
            raise ValueError("Invalid status count")
        if rows:
            row = rows[0]
            if (
                str(UUID(row["id"])) != row["id"]
                or row["schedule_id"] != parent["id"]
                or type(row["schedule_revision"]) is not int
                or not 1 <= row["schedule_revision"] <= parent["revision"]
            ):
                raise ValueError("Invalid occurrence identity")
            if (
                row["status"] not in ("pending", "running", "succeeded", "failed", "cancelled")
                or type(row["attempts"]) is not int
                or not 0 <= row["attempts"] <= 3
                or row.get("error_code") is not None
                and row["error_code"] not in _CAPTURE_ERRORS
            ):
                raise ValueError("Invalid occurrence state")
            for field in ("due_at", "retry_at", "updated_at"):
                stamp = datetime.fromisoformat(row[field].replace("Z", "+00:00"))
                if stamp.tzinfo is None or stamp.utcoffset() is None:
                    raise ValueError("Missing timezone")
            display = row["status"]
            if display == "running":
                lease = datetime.fromisoformat(row["lease_until"].replace("Z", "+00:00"))
                if lease.tzinfo is None or lease.utcoffset() is None or row["attempts"] == 0:
                    raise ValueError("Invalid running state")
                if lease <= datetime.now(timezone.utc):
                    display = "awaiting_recovery"
            latest = {
                k: row[k]
                for k in (
                    "id",
                    "schedule_revision",
                    "due_at",
                    "status",
                    "attempts",
                    "retry_at",
                    "updated_at",
                    "error_code",
                )
            }
            latest.update(
                display_status=display,
                current_revision=row["schedule_revision"] == parent["revision"],
            )
    except (ValueError, TypeError, KeyError, AttributeError):
        raise HTTPException(503, "Private capture status could not be verified.") from None
    captures = _history_rows(
        _call(
            "GET",
            "research_private_captures",
            query={
                "schedule_id": f"eq.{schedule_id}",
                "owner_id": f"eq.{owner.id}",
                "definition_hash": "eq." + parent["definition_hash"],
                "select": "id,schedule_id,owner_id,schedule_revision,definition_hash,published_at",
                "order": "published_at.desc,id.desc",
                "limit": "1",
            },
        ),
        parent,
        owner,
    )
    if len(captures) > 1:
        raise HTTPException(503, "Private capture status could not be verified.")
    return {
        "scope": "authenticated_owner",
        "schedule_id": str(schedule_id),
        "schedule_revision": parent["revision"],
        "runtime_available": False,
        "latest_occurrence": latest,
        "last_success": {k: captures[0][k] for k in ("id", "schedule_revision", "published_at")}
        if captures
        else None,
    }


@router.get("/{schedule_id}/captures")
def capture_history(
    schedule_id: UUID,
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    owner: ResearchOwner = Depends(require_research_owner),
):
    parent = _history_parent(schedule_id, owner)
    columns = "id,schedule_id,owner_id,schedule_revision,definition_hash,published_at"
    rows = _history_rows(
        _call(
            "GET",
            "research_private_captures",
            query={
                "schedule_id": f"eq.{schedule_id}",
                "owner_id": f"eq.{owner.id}",
                "definition_hash": "eq." + parent["definition_hash"],
                "select": columns,
                "order": "published_at.desc,id.desc",
                "limit": str(limit + 1),
                "offset": str(offset),
            },
        ),
        parent,
        owner,
    )
    return {
        "captures": [
            {k: row[k] for k in ("id", "schedule_revision", "definition_hash", "published_at")}
            for row in rows[:limit]
        ],
        "has_more": len(rows) > limit,
        "offset": offset,
        "scope": "authenticated_owner",
        "schedule_id": str(schedule_id),
    }


@router.get("/{schedule_id}/captures/{capture_id}")
def capture_detail(
    schedule_id: UUID, capture_id: UUID, owner: ResearchOwner = Depends(require_research_owner)
):
    parent = _history_parent(schedule_id, owner)
    return _capture_detail_for_parent(schedule_id, capture_id, owner, parent)


def _capture_detail_for_parent(schedule_id, capture_id, owner, parent):
    columns = "id,schedule_id,owner_id,schedule_revision,definition_hash,published_at,snapshot"
    rows = _history_rows(
        _call(
            "GET",
            "research_private_captures",
            query={
                "id": f"eq.{capture_id}",
                "schedule_id": f"eq.{schedule_id}",
                "owner_id": f"eq.{owner.id}",
                "definition_hash": "eq." + parent["definition_hash"],
                "select": columns,
                "limit": "1",
            },
        ),
        parent,
        owner,
    )
    if not rows:
        raise HTTPException(404, "Private capture not found.")
    try:
        import re
        from datetime import datetime

        from .main import (
            _apply_filters,
            _criterion_filter_row,
            criterion_slots,
            validate_observation_capture,
        )

        row = rows[0]
        snapshot = row["snapshot"]
        spec = parent["definition"]["screen"]
        if (
            len(rows) != 1
            or row["id"] != str(capture_id)
            or not isinstance(snapshot, dict)
            or snapshot.get("id") != str(capture_id)
            or snapshot.get("complete") is not True
            or snapshot.get("definition") != spec
            or type(snapshot.get("version")) is not int
            or snapshot["version"] not in (2, 3)
        ):
            raise ValueError("Invalid snapshot")
        captured = datetime.fromisoformat(snapshot["at"].replace("Z", "+00:00"))
        source = datetime.fromisoformat(snapshot["source_at"].replace("Z", "+00:00"))
        if (
            captured.tzinfo is None
            or source.tzinfo is None
            or not -300 <= (captured - source).total_seconds() <= 86400
        ):
            raise ValueError("Invalid source time")
        members = snapshot["members"]
        if (
            not isinstance(members, list)
            or len(members) > 20000
            or any(
                not isinstance(r, dict)
                or not isinstance(r.get("code"), str)
                or not re.fullmatch(spec["market"] + r"\.[A-Z0-9][A-Z0-9._-]{0,30}", r["code"])
                for r in members
            )
        ):
            raise ValueError("Invalid member identity")
        codes = {r["code"] for r in members}
        if len(codes) != len(members):
            raise ValueError("Duplicate members")
        if snapshot["version"] == 3:
            if (
                spec["preset"]
                or snapshot.get("source_clock") not in ("stored_universe", "generation_publication")
                or not isinstance(snapshot.get("observations"), list)
                or len(snapshot["observations"]) > 20000
            ):
                raise ValueError("Invalid stored observation scope")
            lookup = validate_observation_capture(snapshot, spec)
            if any(lookup.get(r["code"]) != r for r in members):
                raise ValueError("Member evidence changed")
            qualifying = {
                code
                for code, record in lookup.items()
                if all(
                    _apply_filters(
                        [_criterion_filter_row(code, c, record["criterion_observations"][slot])],
                        [c],
                    )[0]
                    for slot, c in criterion_slots(spec["filters"])
                )
            }
            if qualifying != codes:
                raise ValueError("Membership disagrees with eligible evidence")
        elif not spec["preset"] or snapshot.get("source_clock") != "provider_retrieval":
            raise ValueError("Invalid provider contract")
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise HTTPException(
            409, "Private capture evidence is invalid. No changes can be inferred."
        ) from None
    return {
        "snapshot": snapshot,
        "schedule_id": str(schedule_id),
        "schedule_revision": row["schedule_revision"],
        "definition_hash": row["definition_hash"],
        "published_at": row["published_at"],
        "scope": "authenticated_owner",
        "evidence_scope": "eligible_stored_universe"
        if snapshot["version"] == 3
        else "provider_members_only",
    }


@router.get("/{schedule_id}/changes")
def capture_changes(
    schedule_id: UUID,
    previous_id: UUID,
    current_id: UUID,
    status: str = "all",
    q: str = Query(default="", max_length=100),
    sort: str = Query(default="symbol", max_length=100),
    direction: int = Query(default=1, ge=1, le=2),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=40000),
    owner: ResearchOwner = Depends(require_research_owner),
):

    parent = _history_parent(schedule_id, owner)
    return _private_changes(
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
    )


def _private_changes(schedule_id, previous_id, current_id, owner, parent, **options):
    from .main import ScreenDefinition, _compare_screen_captures, _snapshot_meta

    previous = _capture_detail_for_parent(schedule_id, previous_id, owner, parent)["snapshot"]
    current = _capture_detail_for_parent(schedule_id, current_id, owner, parent)["snapshot"]
    metadata = {
        "history": [_snapshot_meta(previous), _snapshot_meta(current)],
        "history_has_more": False,
        "history_offset": 0,
        "history_limit": 2,
        "history_scope": "selected_pair",
        "retained_limit": None,
        "scope": "authenticated_owner",
    }
    result = _compare_screen_captures(
        ScreenDefinition.model_validate(parent["definition"]["screen"], strict=True),
        previous,
        current,
        metadata,
        "private_capture_schedule:" + str(schedule_id),
        **options,
    )
    # Full new/exited payloads would defeat paginated private reads. Counts retain
    # complete pair scope; rows contain only the requested comparison page.
    result.pop("added", None)
    result.pop("exited", None)
    return {
        **result,
        "schedule_id": str(schedule_id),
        "definition_hash": parent["definition_hash"],
        "review_scope": "private_schedule_pair" if options.get("review_lookup") else "unavailable",
    }
