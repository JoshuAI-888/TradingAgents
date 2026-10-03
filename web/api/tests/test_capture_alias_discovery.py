from copy import deepcopy

import pytest
from tradingagents_api import main
from tradingagents_api.screen_capture_aliases import alias_capture_get, alias_history_page
from tradingagents_api.screen_definition_identity import definition_identity

NS = "1" * 16
KEY = "screen_history:" + NS + ":" + "a" * 64
ALIAS = "screen_history:" + NS + ":" + "b" * 64
DEFINITION = main.ScreenDefinition(filters=[{"field": "price", "max": 10}]).model_dump()


def metadata(code, at="2026-10-03T00:00:00Z"):
    return {
        "history_key": ALIAS,
        "id": code,
        "at": at,
        "source_at": at,
        "source_clock": "stored_universe",
        "complete": True,
        "members": 1,
        "version": 3,
        "copies": 1,
    }


class Store:
    def __init__(self, result):
        self.result = deepcopy(result)
        self.calls = []

    def _call(self, *args, **kwargs):
        self.calls.append((args, deepcopy(kwargs)))
        return deepcopy(self.result)


def test_metadata_page_is_bounded_deterministic_and_retains_original_history_key():
    store = Store([metadata("c"), metadata("b"), metadata("a")])
    rows, more = alias_history_page(store, KEY, DEFINITION, limit=2, offset=100)
    assert (
        [r["id"] for r in rows] == ["b", "c"]
        and more
        and all(r["history_key"] == ALIAS for r in rows)
    )
    body = store.calls[0][1]["body"]
    assert (
        body["p_namespace"] == NS
        and body["p_raw_key"] == KEY
        and body["p_limit"] == 2
        and body["p_offset"] == 100
    )
    assert body["p_digest"] == definition_identity(DEFINITION)["sha256"]


@pytest.mark.parametrize(
    "damage",
    ["foreign", "duplicate", "unordered", "invalid_time", "bool_count", "oversized", "nonlist"],
)
def test_bad_metadata_never_establishes_a_timeline(damage):
    rows = [metadata("b"), metadata("a")]
    if damage == "foreign":
        rows[0]["history_key"] = ALIAS.replace(NS, "2" * 16)
    if damage == "duplicate":
        rows[1] = deepcopy(rows[0])
    if damage == "unordered":
        rows.reverse()
    if damage == "invalid_time":
        rows[0]["at"] = 1
    if damage == "bool_count":
        rows[0]["copies"] = True
    if damage == "oversized":
        rows += [metadata("extra"), metadata("more")]
    if damage == "nonlist":
        rows = {"rows": rows}
    with pytest.raises(RuntimeError):
        alias_history_page(Store(rows), KEY, DEFINITION, limit=2)


def detail():
    return {
        "history_key": ALIAS,
        "id": "capture",
        "snapshot": {
            "id": "capture",
            "definition": DEFINITION,
            "definition_identity": definition_identity(DEFINITION),
        },
        "conflicting": False,
        "copies": 2,
    }


def test_exact_duplicate_detail_retains_raw_key_and_evidence():
    row = detail()
    result = alias_capture_get(Store([row]), KEY, DEFINITION, "capture")
    assert result == row and result["copies"] == 2 and result["history_key"] == ALIAS


@pytest.mark.parametrize(
    "damage",
    [
        "divergent",
        "foreign",
        "record_id",
        "payload_id",
        "definition",
        "semantic_digest",
        "bool_count",
        "bool_conflict",
        "multiple",
    ],
)
def test_unproven_detail_cannot_drive_membership_or_review(damage):
    row = detail()
    if damage == "divergent":
        row["conflicting"] = True
    if damage == "foreign":
        row["history_key"] = ALIAS.replace(NS, "2" * 16)
    if damage == "record_id":
        row["id"] = "other"
    if damage == "payload_id":
        row["snapshot"]["id"] = "other"
    if damage == "definition":
        row["snapshot"]["definition"] = {**DEFINITION, "market": "HK"}
        row["snapshot"].pop("definition_identity")
    if damage == "semantic_digest":
        row["snapshot"]["definition_identity"]["sha256"] = "0" * 64
    if damage == "bool_count":
        row["copies"] = True
    if damage == "bool_conflict":
        row["conflicting"] = 1
    rows = [row, row] if damage == "multiple" else [row]
    with pytest.raises((RuntimeError, ValueError)):
        alias_capture_get(Store(rows), KEY, DEFINITION, "capture")
