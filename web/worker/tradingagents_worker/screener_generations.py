"""Read one immutable classified quote cohort, failing closed on corruption.

Shared by worker and API; this does not qualify exchange/provider coverage.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from datetime import datetime

GENERATION_CAP = 20000


class GenerationError(ValueError):
    pass


def aware_time(value):
    if not isinstance(value, str):
        raise GenerationError("Missing generation timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("naive timestamp")
        return parsed
    except (ValueError, OverflowError) as error:
        raise GenerationError("Invalid generation timestamp") from error


def canonical_generation(value):
    try:
        if not isinstance(value, str) or str(uuid.UUID(value)) != value:
            raise ValueError("noncanonical UUID")
    except (ValueError, AttributeError) as error:
        raise GenerationError("Invalid generation identity") from error
    return value


def read_generation(db, market, generation_id):
    canonical_generation(generation_id)
    headers = db.select("screener_generations", {"id": "eq." + generation_id}, "*")
    if len(headers) != 1:
        raise GenerationError("Published generation header is missing or ambiguous")
    header = headers[0]
    count = header.get("row_count")
    if (
        header.get("id") != generation_id
        or header.get("market") != market
        or isinstance(count, bool)
        or not isinstance(count, int)
        or not 1 <= count <= GENERATION_CAP
    ):
        raise GenerationError("Invalid published generation header")
    started, published = (
        aware_time(header.get("started_at")),
        aware_time(header.get("published_at")),
    )
    if published < started:
        raise GenerationError("Published generation clock precedes its run")
    records = db.select_all(
        "screener_generation_rows",
        {"generation_id": "eq." + generation_id, "order": "code.asc"},
        "*",
        cap=GENERATION_CAP + 1,
    )
    if len(records) != count:
        raise GenerationError("Published generation rows are incomplete")
    codes = []
    for item in records:
        code, row, metadata = item.get("code"), item.get("row"), item.get("metadata")
        if (
            item.get("generation_id") != generation_id
            or not isinstance(code, str)
            or not re.fullmatch(re.escape(market) + r"\.[A-Z0-9][A-Z0-9._-]{0,30}", code)
            or not isinstance(row, dict)
            or row.get("code") != code
            or not isinstance(metadata, dict)
            or metadata.get("code") != code
            or metadata.get("market") != market
            or not isinstance(metadata.get("stock_type"), str)
            or not 1 <= len(metadata["stock_type"]) <= 32
            or not isinstance(metadata.get("plates"), list)
            or any(not isinstance(p, str) for p in metadata["plates"])
        ):
            raise GenerationError("Invalid published generation row or classification")
        if any(
            metadata.get(k) is not None and not isinstance(metadata[k], str)
            for k in ("name", "plate", "exchange")
        ):
            raise GenerationError("Invalid generation company metadata")
        classification = metadata.get("instrument_classification")
        if classification is not None:
            from .instrument_classification import validate

            if (
                not validate(classification, code, item.get("quote_cache_at"))
                or row.get("instrument_classification") != classification
                or row.get("stock_type") != classification["stock_type"]
                or metadata["stock_type"] != classification["stock_type"]
            ):
                raise GenerationError("Invalid normalized instrument classification")
        if not started <= aware_time(item.get("quote_cache_at")) <= published:
            raise GenerationError("Generation quote cache receipt is outside its run")
        codes.append(code)
    fingerprint = hashlib.sha256("\n".join(sorted(codes)).encode()).hexdigest()
    if len(set(codes)) != count or fingerprint != header.get("cohort_fingerprint"):
        raise GenerationError("Generation identity cohort does not match its receipt")
    return header, records
