"""Render cron entry: Market Pulse discovery sweep (screens/news/calendar/watchlist).

Also triggers a nightly watchlist sweep job at 02:00 UTC weekdays via job queue.
"""

import os

from tradingagents_worker.config import SETTINGS
from tradingagents_worker.db import Db
from tradingagents_worker.discovery import sweep
from tradingagents_worker.moomoo import Budget, MoomooClient
from tradingagents_worker.ttl_cache import TtlCache

db = Db()
mm = None
if SETTINGS.moomoo_appkey and SETTINGS.moomoo_private_key:
    try:
        offset = MoomooClient.server_clock_offset_ms()
        mm = MoomooClient(
            SETTINGS.moomoo_appkey,
            SETTINGS.moomoo_private_key,
            Budget(limit=30),
            clock_offset_ms=offset,
        )
    except Exception as e:
        print(f"moomoo client unavailable: {type(e).__name__}")  # never print key material
else:
    print("moomoo keys not set — discovery runs with watchlist candidates only")

cache = TtlCache(root=os.path.join(SETTINGS.cache_dir, "ttl"))
cands = sweep(db, mm, cache, watchlist=["NVDA", "MSFT", "0700.HK", "CSL.AX"])
print(f"discovery: {len(cands)} new candidates stored")
