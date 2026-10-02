"""Off-request-path subtype cron with killable provider and whole-run budgets.

Default-off until provider/platform/lease qualification. Revisioned writes are
fenced by fixed-duration market leases; deployment qualification remains open.
"""

import contextlib
import json
import math
import multiprocessing as mp
import os
import signal
import time
import uuid

from .config import SETTINGS
from .db import Db
from .instrument_subtype_store import claim, publish, read_cache, release
from .instrument_subtypes import COHORT_CAP, SubtypeRateLimited, collect
from .moomoo import MoomooClient
from .universe_refresh import UniverseRefresher

REQUEST_SECONDS = 15
RUN_SECONDS = 300
RUN_ATTEMPTS = 100


def _yahoo_info(symbol):
    import yfinance as yf
    from yfinance.exceptions import YFRateLimitError

    try:
        return yf.Ticker(symbol).get_info()
    except YFRateLimitError:
        raise SubtypeRateLimited("Subtype provider rate limited") from None


def _provider_child(conn, symbol, fetch):
    try:
        info = fetch(symbol)
        # A general Yahoo info response is fetched, but only two bounded text
        # tokens cross the process boundary; no vendor exception text escapes.
        out = {}
        if isinstance(info, dict):
            for key in ("symbol", "quoteType"):
                value = info.get(key)
                if isinstance(value, str) and len(value) <= 128:
                    out[key] = value
        conn.send(out)
    except SubtypeRateLimited:
        conn.send({"_error": "provider_rate_limited"})
    except Exception:
        conn.send(None)
    finally:
        conn.close()


def _stop(process, group=False):
    isolated = False
    if group and process.pid is not None:
        with contextlib.suppress(ProcessLookupError):
            isolated = os.getpgid(process.pid) == process.pid
    if isolated:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    elif process.is_alive():
        process.terminate()
    process.join(1)
    if process.is_alive():
        process.kill()
        process.join(1)
    if process.is_alive():
        raise RuntimeError("Subtype child did not stop")
    process.close()


def fetch_bounded(symbol, timeout=REQUEST_SECONDS, fetch=_yahoo_info):
    if (
        not isinstance(symbol, str)
        or len(symbol) > 128
        or not symbol
        or type(timeout) not in (int, float)
        or not math.isfinite(timeout)
        or not 0 < timeout <= REQUEST_SECONDS
    ):
        raise ValueError("Invalid subtype provider budget")
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_provider_child, args=(child, symbol, fetch))
    try:
        process.start()
        child.close()
        if not parent.poll(timeout):
            raise TimeoutError("Subtype provider deadline exceeded")
        try:
            result = parent.recv()
        except EOFError:
            result = None
        if result == {"_error": "provider_rate_limited"}:
            raise SubtypeRateLimited("Subtype provider rate limited")
        if result is None:
            raise RuntimeError("Subtype provider unavailable")
        return result
    finally:
        parent.close()
        child.close()
        if process.pid is not None:
            _stop(process)


def run(db, market="US", fetch=fetch_bounded, deadline_seconds=240):
    if (
        market not in ("US", "HK")
        or type(deadline_seconds) not in (int, float)
        or not math.isfinite(deadline_seconds)
        or not 0 < deadline_seconds <= 240
    ):
        raise ValueError("Invalid subtype job scope or budget")
    started = time.monotonic()
    token = str(uuid.uuid4())
    acquired = claim(db, market, token)
    if acquired is None:
        return {
            "market": market,
            "skipped": "market_collection_already_running",
            "coverage_qualified": False,
        }
    try:
        # Read the exact published metadata, not inferred normalized labels or a
        # new provider enumeration that has not been atomically published yet.
        metadata = UniverseRefresher(
            db, MoomooClient(SETTINGS.moomoo_appkey, SETTINGS.moomoo_private_key), market
        )._stored_metadata()
        if (
            not metadata
            or len(metadata) > COHORT_CAP
            or any(
                not row.get("provider_stock_type") or not row.get("provider_classified_at")
                for row in metadata
            )
        ):
            raise ValueError("Raw published classification metadata unavailable")
        cache, revisions = read_cache(db, market)
        result = collect(
            metadata,
            cache,
            fetch,
            limit=RUN_ATTEMPTS,
            should_stop=lambda: time.monotonic() - started >= deadline_seconds,
        )
        receipt = publish(db, market, result["updates"], revisions, run_id=token)
        outcome = {
            "market": market,
            "attempted": result["attempted"],
            "eligible": result["eligible"],
            "remaining": result["remaining"],
            "saved": len(receipt["saved"]),
            "conflicts": len(receipt["conflicts"]),
            "scope": result["scope"],
            "stop_reason": result["stop_reason"],
            "coverage_qualified": False,
        }
    except BaseException:
        # Preserve the original failure; the lease expires naturally.
        with contextlib.suppress(Exception):
            release(db, market, token)
        raise
    if not release(db, market, token):
        raise RuntimeError("Subtype lease completion unconfirmed")
    return outcome


def _job_child(conn, market):
    os.setsid()  # killable POSIX group including spawned provider children
    try:
        conn.send({"status": "completed", "result": run(Db(), market)})
    except Exception:
        conn.send({"status": "failed", "reason": "collection_or_storage_unavailable"})
    finally:
        conn.close()


def main():
    if os.getenv("INSTRUMENT_SUBTYPE_COLLECTION_ENABLED") != "1":
        print(json.dumps({"status": "disabled"}), flush=True)
        return
    market = os.getenv("INSTRUMENT_SUBTYPE_MARKET", "US")
    if market not in ("US", "HK"):
        raise ValueError("Unsupported subtype market")
    ctx = mp.get_context("spawn")
    parent, child = ctx.Pipe(duplex=False)
    process = ctx.Process(target=_job_child, args=(child, market))
    try:
        process.start()
        child.close()
        if not parent.poll(RUN_SECONDS):
            raise TimeoutError("Subtype collection run deadline exceeded")
        try:
            result = parent.recv()
        except EOFError:
            result = {"status": "failed", "reason": "worker_terminated"}
        print(json.dumps(result), flush=True)
        if result.get("status") != "completed":
            raise RuntimeError("Subtype collection failed")
    finally:
        parent.close()
        child.close()
        if process.pid is not None:
            _stop(process, group=True)


if __name__ == "__main__":
    main()
