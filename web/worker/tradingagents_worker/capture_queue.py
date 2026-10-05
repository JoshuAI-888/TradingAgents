"""Private capture lease transport. No public jobs, payload logging or publication."""

import json
import re
from uuid import UUID

from .capture_dispatch import instant

ERRORS = {
    "provider_unavailable",
    "incomplete_data",
    "storage_unconfirmed",
    "worker_interrupted",
    "definition_changed",
}


def identity(value):
    if not isinstance(value, str):
        raise ValueError("Invalid capture identity")
    return str(UUID(value))


class CaptureQueue:
    def __init__(self, db, worker_id):
        self.db = db
        self.worker_id = identity(worker_id)

    def _row(self, rows, claimed=None, running=True):
        if rows == []:
            return None
        try:
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
                raise ValueError("Invalid rows")
            row = rows[0]
            for key in ("id", "schedule_id", "owner_id"):
                identity(row[key])
            if (
                type(row["schedule_revision"]) is not int
                or row["schedule_revision"] < 1
                or type(row["attempts"]) is not int
                or not 1 <= row["attempts"] <= 3
            ):
                raise ValueError("Invalid revision/attempt")
            instant(row["due_at"])
            instant(row["updated_at"])
            if claimed and any(
                row.get(k) != claimed.get(k)
                for k in (
                    "id",
                    "schedule_id",
                    "owner_id",
                    "schedule_revision",
                    "attempts",
                    "due_at",
                )
            ):
                raise ValueError("Changed lease identity")
            if running:
                if row["status"] != "running" or row["worker_id"] != self.worker_id:
                    raise ValueError("Invalid lease holder")
                identity(row["lease_token"])
                if claimed and row["lease_token"] != claimed["lease_token"]:
                    raise ValueError("Changed lease token")
                start = instant(row["attempt_started_at"])
                end = instant(row["lease_until"])
                if (
                    not instant(row["updated_at"]) < end
                    or not 0 < (end - start).total_seconds() <= 1200
                ):
                    raise ValueError("Invalid lease time")
            elif row["status"] not in ("pending", "failed") or any(
                row.get(k) is not None for k in ("worker_id", "lease_token", "lease_until")
            ):
                raise ValueError("Invalid failure state")
            return row
        except (ValueError, KeyError, TypeError, OverflowError):
            raise RuntimeError("Private capture queue response was not confirmed") from None

    def claim(self):
        return self._row(
            self.db._call("POST", "rpc/research_capture_claim", body={"p_worker": self.worker_id})
        )

    def _credentials(self, claimed):
        self._row([claimed])
        return {
            "p_occurrence": claimed["id"],
            "p_worker": self.worker_id,
            "p_token": claimed["lease_token"],
        }

    def renew(self, claimed):
        body = self._credentials(claimed)
        return self._row(self.db._call("POST", "rpc/research_capture_renew", body=body), claimed)

    def fail(self, claimed, error, retryable):
        if not isinstance(error, str) or error not in ERRORS or type(retryable) is not bool:
            raise ValueError("Use a safe capture failure code and explicit retry choice")
        body = {**self._credentials(claimed), "p_error": error, "p_retryable": retryable}
        row = self._row(
            self.db._call("POST", "rpc/research_capture_fail", body=body), claimed, running=False
        )
        if row is not None and (
            row.get("error_code") != error
            or row["status"] != ("pending" if retryable and claimed["attempts"] < 3 else "failed")
        ):
            raise RuntimeError("Private capture failure state was not confirmed")
        return row

    def publish(self, claimed, snapshot, definition, digest):
        """Publish builder-validated evidence; confirm exact immutable identity.

        This transport guard does not replace criterion validation by the
        capture builder or database lease/revision checks.
        """
        body = self._credentials(claimed)
        if (
            not isinstance(digest, str)
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or not isinstance(definition, dict)
        ):
            raise ValueError("Invalid pinned capture definition")
        if (
            not isinstance(snapshot, dict)
            or snapshot.get("id") != claimed["id"]
            or snapshot.get("complete") is not True
            or snapshot.get("definition") != definition.get("screen")
        ):
            raise ValueError("Incomplete or incompatible capture")
        if len(json.dumps(snapshot, allow_nan=False).encode()) > 33554432:
            raise ValueError("Capture exceeds publication limit")
        rows = self.db._call(
            "POST", "rpc/research_capture_publish", body={**body, "p_snapshot": snapshot}
        )
        if rows == []:
            return None
        try:
            if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
                raise ValueError("Invalid publication response")
            row = rows[0]
            if (
                any(
                    row.get(k) != claimed[k]
                    for k in ("id", "owner_id", "schedule_id", "schedule_revision")
                )
                or type(row.get("schedule_revision")) is not int
            ):
                raise ValueError("Changed publication identity")
            if (
                row.get("snapshot") != snapshot
                or row.get("definition_hash") != digest
                or row.get("publish_token") != claimed["lease_token"]
                or row.get("publish_worker") != self.worker_id
            ):
                raise ValueError("Unconfirmed publication content")
            instant(row["published_at"])
        except (ValueError, TypeError, KeyError):
            raise RuntimeError(
                "Private capture publication was not confirmed; retry the same payload"
            ) from None
        return row
