"""Small, ordered membership reads from the authoritative published cohort."""

import re

from .screener_generations import GenerationError, canonical_generation


def current_codes(db, market):
    settings = db.select("app_settings", {"key": f"eq.universe_state_{market}"}, "value")
    state = settings[0].get("value") or {} if settings else {}
    generation = state.get("generation_id")
    if not generation:
        return []  # Historical compatibility membership is never refresh admission.
    canonical_generation(generation)
    headers = db.select("screener_generations", {"id": f"eq.{generation}"}, "market,row_count")
    rows = db.select_all(
        "screener_generation_rows",
        {"generation_id": f"eq.{generation}", "order": "code.asc"},
        "code,stock_type:metadata->>stock_type",
        cap=20001,
    )
    if (
        len(headers) != 1
        or headers[0].get("market") != market
        or headers[0].get("row_count") != len(rows)
    ):
        raise GenerationError("Current enrichment cohort is incomplete")
    codes = [r.get("code") for r in rows]
    if len(set(codes)) != len(codes) or any(
        not isinstance(c, str) or not re.fullmatch(market + r"\.[A-Z0-9][A-Z0-9._-]{0,30}", c)
        for c in codes
    ):
        raise GenerationError("Invalid current enrichment identity")
    return [r["code"] for r in rows if r.get("stock_type") == "STOCK"]
