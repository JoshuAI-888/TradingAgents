"""TTL cache choke point in front of all vendor calls (BSTester pattern).

quotes 5m · news 1h · OHLCV 1d · fundamentals 7d. Keys = sha1(method+args).
Disk-backed under the mounted cache dir; process-local dict fast path.
"""

from __future__ import annotations

import hashlib
import json
import os
import pickle
import time


class TtlCache:
    DEFAULTS = {"quotes": 300, "news": 3600, "ohlcv": 86400, "fundamentals": 604800, "other": 600}

    def __init__(self, root: str = "/data/cache/ttl"):
        self.root = root
        os.makedirs(root, exist_ok=True)
        self._mem: dict[str, tuple[float, bytes]] = {}

    def key(self, category: str, *parts) -> str:
        return hashlib.sha1(
            json.dumps([category, *parts], sort_keys=True, default=str).encode()
        ).hexdigest()

    def get(self, category: str, k: str):
        ttl = self.DEFAULTS.get(category, 600)
        hit = self._mem.get(k)
        now = time.time()
        if hit and now - hit[0] < ttl:
            return pickle.loads(hit[1])
        path = os.path.join(self.root, f"{k}.pkl")
        if os.path.exists(path) and now - os.path.getmtime(path) < ttl:
            with open(path, "rb") as f:
                val = pickle.load(f)
            self._mem[k] = (os.path.getmtime(path), pickle.dumps(val))
            return val
        return None

    def put(self, category: str, k: str, val):
        blob = pickle.dumps(val)
        self._mem[k] = (time.time(), blob)
        tmp = os.path.join(self.root, f".{k}.tmp")
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, os.path.join(self.root, f"{k}.pkl"))

    def wrap(self, category: str, *parts):
        """Decorator-style helper: cache.get_or_put."""
        k = self.key(category, *parts)
        hit = self.get(category, k)
        if hit is not None:
            return hit, True
        return None, False
