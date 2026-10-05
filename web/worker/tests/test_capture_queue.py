from copy import deepcopy

import pytest
from tradingagents_worker.capture_queue import CaptureQueue

WORKER = "00000000-0000-4000-8000-000000000040"


def lease():
    return {
        "id": "00000000-0000-4000-8000-000000000031",
        "schedule_id": "00000000-0000-4000-8000-000000000030",
        "owner_id": "00000000-0000-4000-8000-000000000001",
        "schedule_revision": 1,
        "attempts": 1,
        "worker_id": WORKER,
        "lease_token": "00000000-0000-4000-8000-000000000050",
        "status": "running",
        "due_at": "2026-10-02T16:00:00Z",
        "updated_at": "2026-10-02T16:01:00Z",
        "attempt_started_at": "2026-10-02T16:01:00Z",
        "lease_until": "2026-10-02T16:03:00Z",
    }


class Store:
    def __init__(self, row):
        self.rows = [row]
        self.calls = []

    def _call(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return deepcopy(self.rows)


def test_private_claim_renew_and_failure_confirmation():
    db = Store(lease())
    queue = CaptureQueue(db, WORKER)
    claimed = queue.claim()
    assert claimed == lease()
    assert queue.renew(claimed) == claimed
    db.rows = [
        {
            **claimed,
            "status": "pending",
            "error_code": "provider_unavailable",
            "lease_token": None,
            "worker_id": None,
            "lease_until": None,
        }
    ]
    assert queue.fail(claimed, "provider_unavailable", True)["status"] == "pending"
    assert [args[1] for args, _ in db.calls] == [
        "rpc/research_capture_claim",
        "rpc/research_capture_renew",
        "rpc/research_capture_fail",
    ]
    assert db.calls[-1][1]["body"]["p_token"] == claimed["lease_token"]


def test_fenced_or_empty_queue_is_not_success():
    db = Store(lease())
    db.rows = []
    queue = CaptureQueue(db, WORKER)
    assert (
        queue.claim() is None
        and queue.renew(lease()) is None
        and queue.fail(lease(), "incomplete_data", True) is None
    )


@pytest.mark.parametrize(
    "key,value",
    [
        ("attempts", True),
        ("schedule_revision", True),
        ("owner_id", "bad"),
        ("worker_id", "other"),
        ("lease_token", None),
        ("status", "succeeded"),
        ("lease_until", "2026-10-02T16:01:00Z"),
        ("lease_until", "2026-10-02T16:30:00Z"),
    ],
)
def test_bad_claim_confirmation_fails_closed(key, value):
    row = lease()
    row[key] = value
    with pytest.raises(RuntimeError):
        CaptureQueue(Store(row), WORKER).claim()


def test_stale_token_or_identity_in_renewal_response_is_unconfirmed():
    row = lease()
    row["lease_token"] = "00000000-0000-4000-8000-000000000099"
    with pytest.raises(RuntimeError):
        CaptureQueue(Store(row), WORKER).renew(lease())


@pytest.mark.parametrize(
    "error,retryable",
    [("raw private details", True), ("incomplete_data", 1), ("incomplete_data", None)],
)
def test_invalid_failure_never_reaches_transport(error, retryable):
    db = Store(lease())
    with pytest.raises(ValueError):
        CaptureQueue(db, WORKER).fail(lease(), error, retryable)
    assert not db.calls


def test_failure_does_not_confirm_unexpected_retry():
    row = lease()
    row.update(
        status="pending",
        worker_id=None,
        lease_token=None,
        lease_until=None,
        error_code="definition_changed",
    )
    with pytest.raises(RuntimeError):
        CaptureQueue(Store(row), WORKER).fail(lease(), "definition_changed", False)


def publication():
    claimed = lease()
    definition = {"screen": {"market": "US"}}
    digest = "a" * 64
    snapshot = {
        "id": claimed["id"],
        "complete": True,
        "definition": definition["screen"],
        "members": [],
    }
    row = {k: claimed[k] for k in ("id", "owner_id", "schedule_id", "schedule_revision")}
    row.update(
        snapshot=deepcopy(snapshot),
        definition_hash=digest,
        publish_token=claimed["lease_token"],
        publish_worker=WORKER,
        published_at="2026-10-02T16:02:00Z",
    )
    return claimed, definition, digest, snapshot, row


def test_publication_confirms_exact_payload_and_fenced_reply():
    claimed, definition, digest, snapshot, row = publication()
    db = Store(row)
    queue = CaptureQueue(db, WORKER)
    assert queue.publish(claimed, snapshot, definition, digest) == row
    assert db.calls[0][0][1] == "rpc/research_capture_publish"
    db.rows = []
    assert queue.publish(claimed, snapshot, definition, digest) is None


@pytest.mark.parametrize(
    "key,value",
    [
        ("owner_id", "other"),
        ("schedule_revision", True),
        ("definition_hash", "b" * 64),
        ("publish_token", "other"),
        ("publish_worker", "other"),
        ("snapshot", {}),
        ("published_at", "invalid"),
    ],
)
def test_invalid_publication_confirmation_fails_closed(key, value):
    claimed, definition, digest, snapshot, row = publication()
    row[key] = value
    with pytest.raises(RuntimeError):
        CaptureQueue(Store(row), WORKER).publish(claimed, snapshot, definition, digest)


@pytest.mark.parametrize("damage", ["identity", "complete", "definition", "nonfinite"])
def test_invalid_payload_never_reaches_publication(damage):
    claimed, definition, digest, snapshot, row = publication()
    db = Store(row)
    if damage == "identity":
        snapshot["id"] = "other"
    elif damage == "complete":
        snapshot["complete"] = 1
    elif damage == "definition":
        snapshot["definition"] = {"market": "HK"}
    else:
        snapshot["invalid"] = float("nan")
    with pytest.raises(ValueError):
        CaptureQueue(db, WORKER).publish(claimed, snapshot, definition, digest)
    assert not db.calls
