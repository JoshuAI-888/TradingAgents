"""Exact private pair downloads; fully assemble and fence before serving a file."""

import contextlib
import os
import tempfile
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import research_schedules as schedules
from .export_values import csv_cell, finite, xml_text
from .research_auth import ResearchOwner, require_research_owner
from .scheduled_reviews import _state

router = APIRouter(prefix="/api/research/capture-schedules", tags=["Private research"])
HEADERS = [
    "definition_json",
    "definition_hash",
    "schedule_id",
    "previous_id",
    "current_id",
    "previous_at",
    "current_at",
    "previous_source_at",
    "current_source_at",
    "code",
    "symbol",
    "name",
    "status",
    "reason",
    "previous_metrics",
    "current_metrics",
    "previous_observation",
    "current_observation",
    "criterion_evidence",
    "previous_source_clock",
    "current_source_clock",
    "capture_scope",
    "observation_scope",
    "previous_eligible_observations",
    "current_eligible_observations",
    "previous_generation_id",
    "current_generation_id",
    "export_scope",
    "query_json",
    "review_scope",
    "review_revision_hash",
    "review_revision",
    "review_status",
    "private_note",
    "market_cap_sort_json",
    "criterion_sorts_json",
    "previous_definition_json",
    "current_definition_json",
    "previous_definition_identity",
    "current_definition_identity",
    "previous_history_key",
    "current_history_key",
    "review_history_key",
    "previous_instrument_classification",
    "current_instrument_classification",
]
NUMERIC = {"previous_eligible_observations", "current_eligible_observations", "review_revision"}


class ExportIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    previous_id: UUID
    current_id: UUID
    review_revision_hash: str = Field(pattern=r"^[a-f0-9]{64}$", strict=True)
    status: Literal["all", "new", "exited"] = "all"
    q: str = Field(default="", max_length=100, strict=True)
    sort: str = Field(default="symbol", max_length=100, strict=True)
    direction: int = Field(default=1, ge=1, le=2, strict=True)
    review_status: Literal["all", "unreviewed", "in_review", "reviewed"] = "all"
    scope: Literal["all_filtered", "selected"] = "all_filtered"
    codes: list[str] = Field(default_factory=list, max_length=40000)
    format: Literal["csv", "excel"] = "csv"

    @model_validator(mode="after")
    def selection(self):
        import re

        if (
            self.scope == "selected"
            and not self.codes
            or self.scope == "all_filtered"
            and self.codes
        ):
            raise ValueError("Choose a consistent export scope")
        if len(set(self.codes)) != len(self.codes) or any(
            not re.fullmatch(r"(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}", code) for code in self.codes
        ):
            raise ValueError("Invalid selected identities")
        return self


def _delete(path):
    with contextlib.suppress(FileNotFoundError):
        os.unlink(path)


class PrivateFileResponse(FileResponse):
    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            _delete(self.path)


def _values(pair, row, inp, notes):
    from .main import ScreenDefinition, _change_evidence, paired_evidence

    before = row.get("previous")
    after = row.get("current")
    evidence = (
        paired_evidence(
            before,
            after,
            pair["definition"]["filters"],
            [
                datetime.fromisoformat(pair[key].replace("Z", "+00:00"))
                for key in ("previous_at", "current_at")
            ],
        )
        if pair["observation_coverage"]["scope"] == "eligible_stored_universe"
        else _change_evidence(before, after, ScreenDefinition.model_validate(pair["definition"]))
    )
    reason = row["reason"]
    if row["status"] != "unchanged" and any(e.get("status") == "comparable" for e in evidence):
        reason = "Membership changed; comparable captured rule results are available. This does not establish a sole cause."
    review = notes.get(row["code"], {"revision": 0, "review_status": "unreviewed", "note": ""})
    query = {
        key: getattr(inp, key) for key in ("status", "q", "sort", "direction", "review_status")
    }
    return [
        pair["definition"],
        pair["definition_hash"],
        pair["schedule_id"],
        pair["previous_id"],
        pair["current_id"],
        pair["previous_at"],
        pair["current_at"],
        pair["previous_source_at"],
        pair["current_source_at"],
        row["code"],
        row.get("symbol"),
        row.get("name"),
        row["status"],
        reason,
        (before or {}).get("metrics"),
        (after or {}).get("metrics"),
        before,
        after,
        evidence,
        pair["previous_source_clock"],
        pair["current_source_clock"],
        pair["scope"],
        pair["observation_coverage"]["scope"],
        pair["observation_coverage"].get("previous"),
        pair["observation_coverage"].get("current"),
        pair.get("previous_generation_id"),
        pair.get("current_generation_id"),
        inp.scope,
        query,
        "private_schedule_pair",
        inp.review_revision_hash,
        review["revision"],
        review["review_status"],
        review["note"],
        pair.get("market_cap_sort"),
        pair.get("criterion_sorts"),
        pair.get("previous_definition"),
        pair.get("current_definition"),
        pair.get("previous_definition_identity"),
        pair.get("current_definition_identity"),
        pair.get("previous_history_key"),
        pair.get("current_history_key"),
        pair.get("review_history_key"),
        (before or {}).get("instrument_classification"),
        (after or {}).get("instrument_classification"),
    ]


@router.post("/{schedule_id}/pair-export")
def export(
    schedule_id: UUID,
    inp: ExportIn,
    authorization: str = Header(default=""),
    owner: ResearchOwner = Depends(require_research_owner),
):
    parent = schedules._history_parent(schedule_id, owner)
    state = {}

    def read(key, previous, current):
        payload, rows = _state(owner, schedule_id, inp.previous_id, inp.current_id)
        if payload["revision_hash"] != inp.review_revision_hash:
            raise HTTPException(
                409, "Review revisions changed since this view. Reload before exporting."
            )
        state["lookup"] = rows
        return {code: {**row, "note": None} for code, row in rows.items()}

    pair = schedules._private_changes(
        schedule_id,
        inp.previous_id,
        inp.current_id,
        owner,
        parent,
        status=inp.status,
        q=inp.q,
        sort=inp.sort,
        direction=inp.direction,
        review_lookup=read,
        review_status=inp.review_status,
        limit=40000,
        max_limit=40000,
        include_evidence=False,
    )
    if not pair["comparable"] or len(pair["rows"]) != pair["matched"]:
        raise HTTPException(409, "Private pair export is incomplete or incompatible.")
    selected = set(inp.codes)
    rows = [row for row in pair["rows"] if inp.scope != "selected" or row["code"] in selected]
    if inp.scope == "selected" and {row["code"] for row in rows} != selected:
        raise HTTPException(
            409, "Selected identities no longer match this filtered pair. Reload before exporting."
        )
    path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            prefix="private-pair-",
            suffix=".csv" if inp.format == "csv" else ".xls",
            delete=False,
        ) as output:
            path = output.name
            if inp.format == "csv":
                output.write("\ufeff" + ",".join(map(csv_cell, HEADERS)) + "\r\n")
            else:
                output.write(
                    '<?xml version="1.0"?><Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet" xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"><Worksheet ss:Name="Private comparison"><Table><Row>'
                    + "".join(
                        '<Cell><Data ss:Type="String">' + xml_text(h) + "</Data></Cell>"
                        for h in HEADERS
                    )
                    + "</Row>"
                )
            pair.update(schedule_id=str(schedule_id), definition_hash=parent["definition_hash"])
            for start in range(0, len(rows), 500):
                batch = rows[start : start + 500]
                codes = [row["code"] for row in batch]
                _, notes = _state(
                    owner,
                    schedule_id,
                    inp.previous_id,
                    inp.current_id,
                    codes,
                    inp.review_revision_hash,
                )
                for row in batch:
                    stored = state["lookup"].get(row["code"])
                    note = notes.get(row["code"])
                    if (
                        stored
                        and (
                            not note
                            or note["revision"] != stored["revision"]
                            or note["review_status"] != stored["review_status"]
                        )
                        or not stored
                        and note
                    ):
                        raise HTTPException(
                            409,
                            "Review note state changed during export. Retry from the current view.",
                        )
                    values = _values(pair, row, inp, notes)
                    if inp.format == "csv":
                        output.write(",".join(map(csv_cell, values)) + "\r\n")
                    else:
                        output.write(
                            "<Row>"
                            + "".join(
                                '<Cell><Data ss:Type="'
                                + ("Number" if h in NUMERIC and finite(v) else "String")
                                + '">'
                                + xml_text(v)
                                + "</Data></Cell>"
                                for h, v in zip(HEADERS, values, strict=False)
                            )
                            + "</Row>"
                        )
                if output.tell() > 268435456:
                    raise HTTPException(
                        409,
                        "Export exceeds the 256 MiB download limit. Narrow the filter or selection.",
                    )
            if inp.format == "excel":
                output.write("</Table></Worksheet></Workbook>")
        _state(owner, schedule_id, inp.previous_id, inp.current_id, [], inp.review_revision_hash)
        if require_research_owner(authorization).id != owner.id:
            raise HTTPException(401, "Research account changed; no private file returned.")
        filename = (
            "private_comparison_"
            + str(inp.previous_id)
            + "_"
            + str(inp.current_id)
            + ("_selected" if inp.scope == "selected" else "")
            + (".csv" if inp.format == "csv" else ".xls")
        )
        return PrivateFileResponse(
            path,
            media_type="text/csv" if inp.format == "csv" else "application/vnd.ms-excel",
            filename=filename,
        )
    except BaseException:
        if path is not None:
            _delete(path)
        raise
