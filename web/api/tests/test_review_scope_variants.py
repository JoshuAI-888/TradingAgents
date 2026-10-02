import pytest
from tradingagents_api.review_scope_variants import read_variants

OWNER = "00000000-0000-4000-8000-000000000001"
K1 = "screen_history:" + "7" * 16 + ":" + "a" * 64
K2 = "screen_history:" + "7" * 16 + ":" + "b" * 64


def row(previous=K1, current=K1, code="US.A", revision=2, note="Original note"):
    return {
        "owner_id": OWNER,
        "previous_history_key": previous,
        "current_history_key": current,
        "previous_id": "before",
        "current_id": "after",
        "code": code,
        "note": note,
        "review_status": "reviewed",
        "revision": revision,
        "updated_at": "2026-10-02T00:00:00Z",
        "review_contract": "same_history" if previous == current else "cross_history",
    }


class Db:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def _call(self, method, path, body=None):
        self.calls.append((method, path, body))
        return self.payload


def test_preserves_original_anchors_revisions_and_multiple_private_variants():
    original = [
        row(),
        row(K1, K2, revision=1, note="Separate note"),
        row(K2, K2, "US.B", revision=4),
    ]
    db = Db({"alias_qualified": True, "reviews": original})
    result = read_variants(db, OWNER, K2, K2, "before", "after")
    assert result["ambiguous_codes"] == ["US.A"]
    assert result["variants"]["US.A"] == original[:2]
    assert result["variants"]["US.B"][0]["revision"] == 4
    assert db.calls[0][2]["p_owner"] == OWNER and db.calls[0][2]["p_previous_key"] == K2
    result["variants"]["US.A"][0]["note"] = "Changed locally"
    assert original[0]["note"] == "Original note"


@pytest.mark.parametrize(
    "change",
    [
        {"owner_id": "00000000-0000-4000-8000-000000000002"},
        {"previous_id": "other"},
        {"previous_history_key": "screen_history:" + "8" * 16 + ":" + "a" * 64},
        {"revision": True},
        {"revision": 0},
        {"review_contract": "cross_history"},
        {"note": None},
        {"review_status": "inferred"},
        {"updated_at": "2026-10-02T00:00:00"},
    ],
)
def test_invalid_or_cross_owner_variants_fail_closed(change):
    db = Db({"alias_qualified": True, "reviews": [{**row(), **change}]})
    with pytest.raises(RuntimeError):
        read_variants(db, OWNER, K2, K2, "before", "after")


def test_bounds_duplicates_order_and_unqualified_payload():
    for rows in [[row(), row()], [row(K2, K2), row()], [row()] * 40001]:
        with pytest.raises((RuntimeError, ValueError)):
            read_variants(
                Db({"alias_qualified": True, "reviews": rows}), OWNER, K1, K1, "before", "after"
            )
    assert read_variants(
        Db({"alias_qualified": False, "reviews": []}), OWNER, K1, K1, "before", "after"
    ) == {"alias_qualified": False, "variants": {}, "ambiguous_codes": []}
    with pytest.raises(RuntimeError):
        read_variants(
            Db({"alias_qualified": False, "reviews": [row()]}), OWNER, K1, K1, "before", "after"
        )


def test_scope_invalid_before_any_storage_read():
    db = Db({"alias_qualified": True, "reviews": []})
    with pytest.raises(ValueError):
        read_variants(
            db, OWNER, K1, "screen_history:" + "8" * 16 + ":" + "b" * 64, "before", "after"
        )
    with pytest.raises(ValueError):
        read_variants(db, OWNER, K1, K1, "before", "before")
    assert db.calls == []
