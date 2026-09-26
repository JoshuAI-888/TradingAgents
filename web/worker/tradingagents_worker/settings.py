"""Model-pair settings: app_settings (DB) → env → config defaults, in that order.

Stored under key 'models' as {"quick": id, "deep": id, "provider": ...}.
"""
from __future__ import annotations

from .config import SETTINGS
from .db import Db

KEY = "models"


def get_model_pair(db: Db | None = None) -> dict:
    """Resolve the active model pair: DB row wins over env defaults."""
    provider, quick, deep = SETTINGS.llm_provider, SETTINGS.quick_model, SETTINGS.deep_model
    try:
        if db is not None:
            rows = db.select("app_settings", {"key": f"eq.{KEY}"}, "value")
            if rows:
                v = rows[0]["value"] or {}
                provider = v.get("provider", provider)
                quick = v.get("quick", quick)
                deep = v.get("deep", deep)
    except Exception:
        pass  # settings are an optimization; never block a run on them
    return {"provider": provider, "quick": quick, "deep": deep}


def save_model_pair(db: Db, provider: str, quick: str, deep: str) -> dict:
    value = {"provider": provider, "quick": quick, "deep": deep}
    db.upsert("app_settings", "key", {"key": KEY, "value": value})
    return value
