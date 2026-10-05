from copy import deepcopy
from threading import Event

import pytest
from test_capture_queue import WORKER, lease as lease, publication
from tradingagents_worker.capture_executor import CaptureExecutor, PermanentCaptureError


class Store:
    def __init__(self):
        self.calls = []
        self.claimed, self.definition, self.digest, self.snapshot, self.published = publication()
        self.schedule = {
            "id": self.claimed["schedule_id"],
            "owner_id": self.claimed["owner_id"],
            "revision": 1,
            "enabled": True,
            "definition": self.definition,
            "definition_hash": self.digest,
        }
        self.renew_fenced = False
        self.publish_errors = 0
        self.failures = []

    def _call(self, method, path, body=None, query=None):
        self.calls.append((method, path, deepcopy(body), query))
        if path == "rpc/research_capture_claim":
            return [deepcopy(self.claimed)]
        if path == "research_capture_schedules":
            return [deepcopy(self.schedule)]
        if path == "rpc/research_capture_renew":
            return [] if self.renew_fenced else [deepcopy(self.claimed)]
        if path == "rpc/research_capture_publish":
            if self.publish_errors:
                self.publish_errors -= 1
                raise OSError("private details")
            return [deepcopy(self.published)]
        if path == "rpc/research_capture_fail":
            self.failures.append(body)
            return [
                {
                    **self.claimed,
                    "status": "pending" if body["p_retryable"] else "failed",
                    "worker_id": None,
                    "lease_token": None,
                    "lease_until": None,
                    "error_code": body["p_error"],
                }
            ]
        raise AssertionError(path)


def executor(db, builder=None):
    return CaptureExecutor(db, WORKER, builder or (lambda s, i: deepcopy(db.snapshot)))


def test_connected_private_read_build_renew_publish():
    db = Store()
    built = []

    def build(s, i):
        built.append((s, i))
        return deepcopy(db.snapshot)

    result = executor(db, build).execute_one()
    assert result == {"state": "succeeded", "occurrence_id": db.claimed["id"]}
    assert len(built) == 1 and built[0][1] == db.claimed["id"]
    query = next(q for _, p, _, q in db.calls if p == "research_capture_schedules")
    assert query["owner_id"] == "eq." + db.claimed["owner_id"]
    assert not db.failures


def test_lost_response_retries_exact_payload_without_rebuilding():
    db = Store()
    db.publish_errors = 1
    built = []

    def build(s, i):
        built.append(i)
        return deepcopy(db.snapshot)

    assert executor(db, build).execute_one()["state"] == "succeeded"
    requests = [body for _, p, body, _ in db.calls if p == "rpc/research_capture_publish"]
    assert len(requests) == 2 and requests[0] == requests[1] and len(built) == 1


def test_unconfirmed_publication_never_marked_failed_or_rebuilt():
    db = Store()
    db.publish_errors = 2
    result = executor(db).execute_one()
    assert (
        result["state"] == "unconfirmed"
        and not db.failures
        and "private details" not in str(result)
    )


@pytest.mark.parametrize("change", [{"enabled": False}, {"revision": 2}])
def test_changed_schedule_stops_before_provider(change):
    db = Store()
    db.schedule.update(change)

    def forbidden(*a):
        pytest.fail("Obsolete schedule reached builder")

    assert executor(db, forbidden).execute_one()["state"] == "obsolete"
    assert not any(p == "rpc/research_capture_publish" for _, p, _, _ in db.calls)


def test_permanent_definition_failure_and_transient_data_failure():
    for error, expected in [
        (PermanentCaptureError("private"), False),
        (RuntimeError("provider details"), True),
    ]:
        db = Store()

        def broken(*a, error=error):
            raise error

        result = executor(db, broken).execute_one()
        assert (
            result["state"] == ("pending" if expected else "failed")
            and db.failures[0]["p_retryable"] == expected
        )
        assert not any(p == "rpc/research_capture_publish" for _, p, _, _ in db.calls)


def test_lease_loss_after_build_prevents_publication():
    db = Store()

    def build(s, i):
        db.renew_fenced = True
        return deepcopy(db.snapshot)

    assert executor(db, build).execute_one()["state"] == "obsolete"
    assert not any(p == "rpc/research_capture_publish" for _, p, _, _ in db.calls)


def test_shutdown_before_claim_and_during_build():
    db = Store()
    stop = Event()
    stop.set()
    assert executor(db).execute_one(stop)["state"] == "stopped" and not db.calls
    stop.clear()

    def build(s, i):
        stop.set()
        return deepcopy(db.snapshot)

    assert executor(db, build).execute_one(stop)["state"] == "pending"
    assert db.failures[0]["p_error"] == "worker_interrupted"


def test_wrong_owner_response_is_unconfirmed_not_provider_work():
    db = Store()
    db.schedule["owner_id"] = "other"

    def forbidden(*a):
        pytest.fail("Wrong scope reached builder")

    assert executor(db, forbidden).execute_one()["state"] == "pending"
    assert db.failures[0]["p_error"] == "storage_unconfirmed"


def test_background_lease_loss_while_builder_is_waiting_stops_publication():
    db = Store()
    renewed = Event()
    original = db._call
    count = 0

    def call(method, path, **kwargs):
        nonlocal count
        if path == "rpc/research_capture_renew":
            count += 1
            if count == 2:
                db.renew_fenced = True
                renewed.set()
                return []
        return original(method, path, **kwargs)

    db._call = call

    def waiting(s, i):
        assert renewed.wait(3), "Background renewal did not execute"
        return deepcopy(db.snapshot)

    result = CaptureExecutor(db, WORKER, waiting, renew_seconds=1).execute_one()
    assert result["state"] == "obsolete" and count >= 2
    assert not any(p == "rpc/research_capture_publish" for _, p, _, _ in db.calls)
