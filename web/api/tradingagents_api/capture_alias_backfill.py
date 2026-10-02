"""Bounded operator backfill. Dry-run by default; never enables alias rollout.

PYTHONPATH=web/api:web/worker python -m tradingagents_api.capture_alias_backfill
Use --apply --checkpoint PATH to persist progress. After old writers drain,
--restart performs the required full rescan; scan completion is not cutover.
"""

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from .screen_capture_aliases import backfill_page

COUNTERS = ("scanned", "eligible", "inserted", "already_mapped", "unprovable")


def save_checkpoint(path, state):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".capture-alias-", delete=False
        ) as file:
            temporary = file.name
            json.dump(state, file, sort_keys=True)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def run(db, namespace, *, page_size=20, max_pages=10, apply=False, checkpoint=None, restart=False):
    if (
        type(max_pages) is not int
        or not 1 <= max_pages <= 1000
        or type(page_size) is not int
        or not 1 <= page_size <= 100
        or type(apply) is not bool
        or type(restart) is not bool
        or restart
        and not apply
        or not isinstance(namespace, str)
        or not re.fullmatch(r"[a-f0-9]{16,64}", namespace)
    ):
        raise ValueError("Invalid bounded backfill run")
    state = {
        "schema_version": 1,
        "namespace": namespace,
        "cursor": None,
        "scan_complete": False,
        **dict.fromkeys(COUNTERS, 0),
    }
    if checkpoint and Path(checkpoint).exists() and not restart:
        loaded = json.loads(Path(checkpoint).read_text())
        if (
            not isinstance(loaded, dict)
            or set(loaded) != set(state)
            or type(loaded["schema_version"]) is not int
            or loaded["schema_version"] != 1
            or loaded["namespace"] != namespace
            or type(loaded["scan_complete"]) is not bool
            or any(type(loaded[k]) is not int or loaded[k] < 0 for k in COUNTERS)
        ):
            raise ValueError("Checkpoint is invalid or belongs to another namespace")
        cursor = loaded["cursor"]
        if (
            loaded["scanned"] != loaded["eligible"] + loaded["unprovable"]
            or loaded["inserted"] + loaded["already_mapped"] != loaded["eligible"]
            or (loaded["scanned"] > 0 and cursor is None)
            or (
                cursor is not None
                and (
                    not isinstance(cursor, dict)
                    or set(cursor) != {"history_key", "capture_id"}
                    or not isinstance(cursor["history_key"], str)
                    or not re.fullmatch(
                        r"screen_history:" + namespace + r":[a-f0-9]{64}", cursor["history_key"]
                    )
                    or not isinstance(cursor["capture_id"], str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", cursor["capture_id"])
                )
            )
        ):
            raise ValueError("Checkpoint cursor or counts are inconsistent")
        state = loaded
    pages = 0
    while pages < max_pages and not state["scan_complete"]:
        result = backfill_page(
            db, namespace, cursor=state["cursor"], page_size=page_size, apply=apply
        )
        for key in COUNTERS:
            state[key] += result[key]
        state["cursor"] = result["next_cursor"] or state["cursor"]
        state["scan_complete"] = not result["has_more"]
        pages += 1
        # A partially failed page produces no new checkpoint; retry replays its
        # earlier confirmed registrations safely through the idempotent RPC.
        if apply and checkpoint:
            save_checkpoint(checkpoint, state)
    return {
        "scope": "deployment_shared_manual",
        "apply": apply,
        "pages": pages,
        "scan_complete": state["scan_complete"],
        **{k: state[k] for k in COUNTERS},
        "cutover_qualified": False,
    }


def main():
    parser = argparse.ArgumentParser(
        description="Dry-run or backfill manual capture definition aliases; does not enable discovery."
    )
    parser.add_argument("--page-size", type=int, default=20)
    parser.add_argument("--max-pages", type=int, default=10)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--checkpoint")
    parser.add_argument("--restart", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.checkpoint:
        parser.error("--apply requires a durable --checkpoint path")
    from .main import _screener_owner, db

    namespace = hashlib.sha256(_screener_owner().encode()).hexdigest()[:16]
    try:
        result = run(
            db,
            namespace,
            page_size=args.page_size,
            max_pages=args.max_pages,
            apply=args.apply,
            checkpoint=args.checkpoint,
            restart=args.restart,
        )
    except (ValueError, RuntimeError, OSError):
        # Do not print definitions, provider evidence, connection details or raw
        # storage exceptions. The prior checkpoint remains the retry position.
        raise SystemExit(
            "Capture alias backfill interrupted; retry from the prior checkpoint."
        ) from None
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
