from copy import deepcopy

import pytest
from tradingagents_api import main
from tradingagents_api.screen_capture_aliases import backfill_page

NAMESPACE = "1" * 16
KEY = "screen_history:" + NAMESPACE + ":" + "a" * 64


def record(capture_id, definition=None):
    return {
        "history_key": KEY,
        "capture_id": capture_id,
        "definition": definition
        if definition is not None
        else main.ScreenDefinition(
            filters=[{"field": "price", "max": 10, "min": None, "_label": "Price"}]
        ).model_dump(),
        "identity_present": False,
        "definition_identity": None,
    }


class Store:
    def __init__(self, rows):
        self.rows = deepcopy(rows)
        self.mapped = {}
        self.calls = []

    def _call(self, method, path, body):
        self.calls.append((path, deepcopy(body)))
        if path == "rpc/screen_capture_alias_backfill_page":
            after = (body["p_after_key"], body["p_after_id"])
            return [
                deepcopy(r)
                for r in self.rows
                if after[0] is None or (r["history_key"], r["capture_id"]) > after
            ][: body["p_limit"] + 1]
        assert path == "rpc/screen_capture_definition_alias_register"
        existing = self.mapped.get(body["p_key"])
        if existing:
            if existing["p_screen"] != body["p_screen"] or existing["p_digest"] != body["p_digest"]:
                raise RuntimeError("conflicting alias")
            return False
        self.mapped[body["p_key"]] = deepcopy(body)
        return True


def test_bounded_pages_resume_and_retries_preserve_raw_definitions():
    rows = [record(str(i).zfill(3)) for i in range(5)]
    original = deepcopy(rows)
    store = Store(rows)
    first = backfill_page(store, NAMESPACE, page_size=2, apply=True)
    assert (
        first["scanned"] == 2
        and first["inserted"] == 1
        and first["already_mapped"] == 1
        and first["has_more"]
    )
    second = backfill_page(store, NAMESPACE, cursor=first["next_cursor"], page_size=2, apply=True)
    last = backfill_page(store, NAMESPACE, cursor=second["next_cursor"], page_size=2, apply=True)
    assert second["scanned"] == 2 and last["scanned"] == 1 and not last["has_more"]
    assert last["next_cursor"]["capture_id"] == "004" and store.rows == original
    repeat = backfill_page(store, NAMESPACE, page_size=2, apply=True)
    assert repeat["inserted"] == 0 and repeat["already_mapped"] == 2
    assert store.mapped[KEY]["p_screen"]["filters"] == [{"field": "price", "max": 10}]


def test_dry_run_never_writes_and_unknown_legacy_identity_stays_unmapped():
    legacy = record("002")
    legacy["definition"] = None
    bad = record("003")
    bad.update(identity_present=True, definition_identity=None)
    store = Store([record("001"), legacy, bad])
    result = backfill_page(store, NAMESPACE, page_size=20)
    assert (
        result["scanned"] == 3
        and result["eligible"] == 1
        and result["unprovable"] == 2
        and not store.mapped
    )
    assert len(store.calls) == 1


@pytest.mark.parametrize(
    "damage", ["other_namespace", "unordered", "duplicate", "old_cursor", "oversized", "nonlist"]
)
def test_inconsistent_page_is_rejected_before_any_write(damage):
    rows = [record("001"), record("002")]
    cursor = None
    if damage == "other_namespace":
        rows[1]["history_key"] = KEY.replace(NAMESPACE, "2" * 16)
    if damage == "unordered":
        rows.reverse()
    if damage == "duplicate":
        rows[1] = deepcopy(rows[0])
    if damage == "old_cursor":
        cursor = {"history_key": KEY, "capture_id": "001"}
    if damage == "oversized":
        rows += [record("003"), record("004")]
    if damage == "nonlist":
        rows = {"rows": rows}

    class Bad(Store):
        def _call(self, method, path, body):
            assert path == "rpc/screen_capture_alias_backfill_page"
            return rows

    with pytest.raises((ValueError, RuntimeError)):
        backfill_page(Bad([]), NAMESPACE, page_size=2, cursor=cursor, apply=True)


def test_interruption_replays_page_idempotently_without_claiming_complete():
    class Fail(Store):
        def _call(self, method, path, body):
            if path.endswith("_register") and len(self.mapped) == 1 and body["p_key"] != KEY:
                raise RuntimeError("interrupted")
            return super()._call(method, path, body)

    second = record("002")
    second["history_key"] = KEY[:-64] + "b" * 64
    store = Fail([record("001"), second])
    with pytest.raises(RuntimeError):
        backfill_page(store, NAMESPACE, apply=True)
    assert len(store.mapped) == 1
    resumed = Store(store.rows)
    resumed.mapped = deepcopy(store.mapped)
    result = backfill_page(resumed, NAMESPACE, apply=True)
    assert result["already_mapped"] == 1 and result["inserted"] == 1 and not result["has_more"]


def test_operator_checkpoint_resumes_across_runs_and_dry_run_does_not_change_it(tmp_path):
    import json

    from tradingagents_api.capture_alias_backfill import run

    store = Store([record(str(i).zfill(3)) for i in range(5)])
    path = tmp_path / "progress.json"
    first = run(store, NAMESPACE, page_size=2, max_pages=1, apply=True, checkpoint=path)
    assert not first["scan_complete"] and first["scanned"] == 2 and not first["cutover_qualified"]
    saved = path.read_bytes()
    preview = run(store, NAMESPACE, page_size=2, max_pages=10, checkpoint=path)
    assert preview["scan_complete"] and path.read_bytes() == saved
    resumed = run(store, NAMESPACE, page_size=2, max_pages=10, apply=True, checkpoint=path)
    assert resumed["scan_complete"] and resumed["scanned"] == 5
    assert json.loads(path.read_text())["cursor"]["capture_id"] == "004"
    # A late legacy import behind the cursor requires the explicit full rescan.
    store.rows.append(record("000-old"))
    store.rows.sort(key=lambda r: (r["history_key"], r["capture_id"]))
    assert run(store, NAMESPACE, apply=True, checkpoint=path)["pages"] == 0
    scan = run(store, NAMESPACE, apply=True, checkpoint=path, restart=True)
    assert scan["scanned"] == 6 and not scan["cutover_qualified"]


def test_operator_rejects_another_namespace_checkpoint_before_storage(tmp_path):
    import json

    from tradingagents_api.capture_alias_backfill import run

    store = Store([])
    path = tmp_path / "other.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "namespace": "2" * 16,
                "cursor": None,
                "scan_complete": False,
                "scanned": 0,
                "eligible": 0,
                "inserted": 0,
                "already_mapped": 0,
                "unprovable": 0,
            }
        )
    )
    with pytest.raises(ValueError):
        run(store, NAMESPACE, apply=True, checkpoint=path)
    assert not store.calls


@pytest.mark.parametrize("damage", ["cursor_scope", "count", "bool_version", "bool_count"])
def test_completed_operator_checkpoint_is_still_validated(tmp_path, damage):
    import json

    from tradingagents_api.capture_alias_backfill import run

    state = {
        "schema_version": 1,
        "namespace": NAMESPACE,
        "cursor": {"history_key": KEY, "capture_id": "001"},
        "scan_complete": True,
        "scanned": 1,
        "eligible": 1,
        "inserted": 1,
        "already_mapped": 0,
        "unprovable": 0,
    }
    if damage == "cursor_scope":
        state["cursor"]["history_key"] = KEY.replace(NAMESPACE, "2" * 16)
    if damage == "count":
        state["scanned"] = 2
    if damage == "bool_version":
        state["schema_version"] = True
    if damage == "bool_count":
        state["scanned"] = True
    path = tmp_path / "progress.json"
    path.write_text(json.dumps(state))
    store = Store([])
    with pytest.raises(ValueError):
        run(store, NAMESPACE, apply=True, checkpoint=path)
    assert not store.calls


def test_interrupted_checkpoint_replace_preserves_previous_position_and_cleans_temp(
    tmp_path, monkeypatch
):
    from tradingagents_api import capture_alias_backfill as operator

    path = tmp_path / "progress.json"
    path.write_text("previous-checkpoint")
    monkeypatch.setattr(
        operator.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("interrupted"))
    )
    with pytest.raises(OSError):
        operator.save_checkpoint(path, {"cursor": "new"})
    assert path.read_text() == "previous-checkpoint"
    assert list(tmp_path.iterdir()) == [path]
