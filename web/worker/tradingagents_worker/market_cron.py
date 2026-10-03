"""Route the existing screener cron services to their US or HK session.

Universe schedule: 0 1-8,13-21 * * 1-5. Enrichment: 45 8,21 * * 1-5.
Use an explicit market for manual recovery outside those UTC windows.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone


def scheduled_market(kind: str, now: datetime) -> str:
    if now.tzinfo is None:
        raise ValueError("Cron routing requires an aware time")
    utc = now.astimezone(timezone.utc)
    hours = {"universe": ((1, 8), (13, 21)), "enrich": ((8, 8), (21, 21))}
    if kind not in hours or utc.weekday() >= 5:
        raise ValueError("Outside configured screener schedule")
    hk, us = hours[kind]
    if hk[0] <= utc.hour <= hk[1]:
        return "HK"
    if us[0] <= utc.hour <= us[1]:
        return "US"
    raise ValueError("Outside configured screener schedule")


def main(argv: list[str] | None = None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("universe", "enrich"))
    parser.add_argument("--market", choices=("US", "HK"))
    args = parser.parse_args(argv)
    market = args.market or scheduled_market(args.kind, datetime.now(timezone.utc))
    if args.kind == "universe":
        from .universe_refresh import main as refresh
    else:
        from .enrich_nightly import main as refresh
    refresh(market)


if __name__ == "__main__":
    main()
