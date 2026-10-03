"""Private capture execution with renewable leases and exact publication retries."""

from threading import Event, Thread

from .capture_queue import CaptureQueue


class PermanentCaptureError(ValueError):
    pass


class CaptureExecutor:
    def __init__(self, db, worker_id, builder, renew_seconds=30):
        if type(renew_seconds) is not int or not 1 <= renew_seconds <= 60:
            raise ValueError("Invalid renewal interval")
        self.db = db
        self.queue = CaptureQueue(db, worker_id)
        self.builder = builder
        self.renew_seconds = renew_seconds

    def _schedule(self, claimed):
        rows = self.db._call(
            "GET",
            "research_capture_schedules",
            query={
                "id": "eq." + claimed["schedule_id"],
                "owner_id": "eq." + claimed["owner_id"],
                "select": "*",
                "limit": "1",
            },
        )
        if rows == []:
            return None
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise RuntimeError("Unconfirmed private schedule read")
        row = rows[0]
        if row.get("owner_id") != claimed["owner_id"] or row.get("id") != claimed["schedule_id"]:
            raise RuntimeError("Unconfirmed private schedule scope")
        if (
            row.get("enabled") is not True
            or type(row.get("revision")) is not int
            or row["revision"] != claimed["schedule_revision"]
        ):
            return None
        return row

    def execute_one(self, stop=None):
        stop = stop or Event()
        if stop.is_set():
            return {"state": "stopped"}
        claimed = self.queue.claim()
        if claimed is None:
            return {"state": "idle"}
        result = {"occurrence_id": claimed["id"]}
        done = Event()
        lost = Event()
        thread = None

        def renew():
            while not done.wait(self.renew_seconds):
                try:
                    if self.queue.renew(claimed) is None:
                        lost.set()
                        return
                except (RuntimeError, OSError, ValueError):
                    lost.set()
                    return

        def failure(code, retryable):
            try:
                row = self.queue.fail(claimed, code, retryable)
                return {**result, "state": row["status"] if row else "obsolete", "error_code": code}
            except (RuntimeError, OSError, ValueError):
                return {**result, "state": "unconfirmed", "error_code": "storage_unconfirmed"}

        try:
            schedule = self._schedule(claimed)
            if schedule is None:
                return {**result, "state": "obsolete"}
            if stop.is_set():
                return failure("worker_interrupted", True)
            if self.queue.renew(claimed) is None:
                return {**result, "state": "obsolete"}
            thread = Thread(target=renew, daemon=True, name="private-capture-lease")
            thread.start()
            try:
                snapshot = self.builder(schedule, claimed["id"])
            except PermanentCaptureError:
                return failure("definition_changed", False)
            except Exception as exc:
                # Only safe categories leave this boundary; no exception payloads.
                code = (
                    "incomplete_data"
                    if getattr(exc, "status_code", None) in (400, 409, 422)
                    else "provider_unavailable"
                )
                return failure(code, True)
            if lost.is_set():
                return {**result, "state": "obsolete"}
            if stop.is_set():
                return failure("worker_interrupted", True)
            if self.queue.renew(claimed) is None:
                return {**result, "state": "obsolete"}
            # A transport timeout may follow commit. Retry the exact immutable payload,
            # never fetch a second observation under the same occurrence ID.
            for attempt in range(2):
                try:
                    published = self.queue.publish(
                        claimed, snapshot, schedule["definition"], schedule["definition_hash"]
                    )
                    return {**result, "state": "succeeded" if published else "obsolete"}
                except (RuntimeError, OSError):
                    if attempt == 1:
                        return {
                            **result,
                            "state": "unconfirmed",
                            "error_code": "storage_unconfirmed",
                        }
                except (ValueError, TypeError):
                    return failure("incomplete_data", False)
        except (RuntimeError, OSError, ValueError, KeyError):
            return failure("storage_unconfirmed", True)
        finally:
            done.set()
            if thread is not None:
                thread.join(timeout=35)
