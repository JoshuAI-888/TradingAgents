"""Semantic metadata cannot change raw capture identity or collapse real criteria."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from tradingagents_api import main
from tradingagents_api.screen_definition_identity import (
    definition_identity,
    semantic_definition,
    validate_definition_identity,
)


def screen(filters):
    return main.ScreenDefinition(filters=filters).model_dump()


def test_ui_labels_and_null_bounds_have_same_semantic_identity_without_mutation(monkeypatch):
    monkeypatch.setenv("DEFAULT_USER_ID", "identity-test-owner")
    minimal = screen([{"field": "price", "max": 10}])
    decorated = screen([{"field": "price", "max": 10, "min": None, "_label": "Price"}])
    original = deepcopy(decorated)
    assert definition_identity(minimal) == definition_identity(decorated)
    assert decorated == original
    assert semantic_definition(decorated) == minimal
    # Raw hashes remain untouched until an owner-scoped compatibility migration.
    assert main._snapshot_key(main.ScreenDefinition.model_validate(minimal)) != main._snapshot_key(
        main.ScreenDefinition.model_validate(decorated)
    )


@pytest.mark.parametrize(
    "change",
    [
        {"max": 0},
        {"max": -1},
        {"max": True},
        {"excl_max": True},
        {"currency": "HKD"},
        {"days": 30},
        {"period": "annual"},
        {"term": 1},
        {"plate_ids": ["x"]},
        {"unknown_semantic_field": 1},
    ],
)
def test_actual_criterion_changes_keep_distinct_identities(change):
    base = {"field": "price", "max": 10}
    assert definition_identity(screen([base])) != definition_identity(screen([{**base, **change}]))


@pytest.mark.parametrize(
    "field,value",
    [
        ("market", "HK"),
        ("src", "yf"),
        ("etfs", True),
        ("watchlist_only", True),
        ("preset", "other"),
    ],
)
def test_screen_scope_changes_keep_distinct_identities(field, value):
    base = screen([{"field": "price", "max": 10}])
    other = {**base, field: value}
    assert definition_identity(base) != definition_identity(other)


def test_windows_order_and_duplicate_slots_are_not_collapsed():
    criteria = [
        {"field": "volume", "days": 30, "min": 0},
        {"field": "volume", "days": 60, "min": 0},
    ]
    assert semantic_definition(screen(criteria))["filters"] == criteria
    assert definition_identity(screen(criteria)) != definition_identity(
        screen(list(reversed(criteria)))
    )
    assert definition_identity(screen([criteria[0], criteria[0]])) != definition_identity(
        screen([criteria[0]])
    )


def test_all_original_preset_rules_keys_and_sort_definitions_are_unchanged():
    baseline = json.loads((Path(__file__).parent / "ui/presets-baseline.json").read_text())
    original = deepcopy(main.PRESET_SCREENERS)
    assert len(baseline) == 22 and baseline == main.PRESET_SCREENERS
    for preset in baseline:
        spec = main.ScreenDefinition(preset=preset["key"], filters=preset["filters"])
        effective = main._capture_criteria(spec).model_dump()
        normalized = semantic_definition(effective)
        assert normalized["preset"] == preset["key"]
        assert normalized["filters"] == preset["filters"]
        assert definition_identity(effective) == definition_identity(normalized)
    assert original == main.PRESET_SCREENERS


@pytest.mark.parametrize(
    "damage", ["digest", "version", "bool_version", "extra", "missing", "null"]
)
def test_supplied_identity_tampering_is_rejected_but_legacy_absence_is_valid(damage):
    snapshot = {"definition": screen([{"field": "price", "max": 10}])}
    validate_definition_identity(snapshot)
    snapshot["definition_identity"] = definition_identity(snapshot["definition"])
    if damage == "digest":
        snapshot["definition_identity"]["sha256"] = "0" * 64
    if damage == "version":
        snapshot["definition_identity"]["schema_version"] = 2
    if damage == "bool_version":
        snapshot["definition_identity"]["schema_version"] = True
    if damage == "extra":
        snapshot["definition_identity"]["owner_id"] = "other"
    if damage == "missing":
        snapshot["definition_identity"].pop("sha256")
    if damage == "null":
        snapshot["definition_identity"] = None
    with pytest.raises(ValueError):
        validate_definition_identity(snapshot)


@pytest.mark.parametrize(
    "filters",
    [[{"field": "price", "max": float("nan")}], [{"field": "price", "max": float("inf")}], [None]],
)
def test_nonfinite_or_malformed_definitions_cannot_get_an_identity(filters):
    with pytest.raises(ValueError):
        definition_identity(screen(filters))


@pytest.mark.parametrize("version", [2, 3])
def test_comparison_rejects_tampered_additive_identity_before_membership_inference(version):

    spec = main.ScreenDefinition()
    before = {
        "id": "before",
        "version": version,
        "at": "2026-10-01T00:00:00Z",
        "complete": True,
        "definition": spec.model_dump(),
        "members": [],
    }
    after = {
        **before,
        "id": "after",
        "at": "2026-10-02T00:00:00Z",
        "definition_identity": {"schema_version": 1, "sha256": "0" * 64},
    }
    result = main._compare_screen_captures(spec, before, after, {}, "test")
    assert not result["comparable"] and "identity is inconsistent" in result["reason"]


def test_slot_equivalence_preserves_types_order_and_unknown_nested_semantics():
    from tradingagents_api.screen_definition_identity import criteria_equivalent

    a = {"field": "price", "max": 1}
    b = {**a, "min": None, "_label": "Price"}
    assert criteria_equivalent(a, b)
    for changed in (
        {"max": True},
        {"max": 1.0},
        {"currency": "USD"},
        {"days": 30},
        {"future": {"_label": "semantic"}},
        {"values": ["B", "A"]},
    ):
        assert not criteria_equivalent(a, {**a, **changed})
    assert not criteria_equivalent(
        {"field": "x", "future": {"flag": True}}, {"field": "x", "future": {"flag": 1}}
    )


def test_decorated_preset_criteria_do_not_append_spurious_slots():
    for preset in main.PRESET_SCREENERS:
        decorated = [
            {
                **c,
                "_label": "Display label",
                **({"min": None} if "min" not in c else {}),
                **({"max": None} if "max" not in c else {}),
            }
            for c in preset["filters"]
        ]
        spec = main.ScreenDefinition(preset=preset["key"], filters=decorated)
        assert main._capture_criteria(spec).filters == preset["filters"]
