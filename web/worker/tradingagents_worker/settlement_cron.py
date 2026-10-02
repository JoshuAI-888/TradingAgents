"""Render cron entry: settle decisions whose horizon elapsed. Uses price_bars only."""

from tradingagents_worker.db import Db
from tradingagents_worker.settlement import settle_due

rows = settle_due(Db())
print(
    f"settled {len(rows)}: "
    + ", ".join(f"{r.get('id', '?')[:8]}={r.get('status')} a={r.get('alpha_pct')}" for r in rows)
)
