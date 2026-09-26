"""OpenRouter model catalog for the portal's model pickers.

Fetches https://openrouter.ai/api/v1/models (public, no key needed for listing),
attaches a curated intelligence tier (manually updatable — edit INTELLIGENCE_TIERS),
computes an estimated cost per analysis using the observed run token mix
(~1.8M input / 140k output), and sorts: recommended (best value) first.
"""
from __future__ import annotations

import json
import time

from .net import urlopen

MODELS_URL = "https://openrouter.ai/api/v1/models"

# Typical run token mix (see MEMORY 2026-09-27 cost model): 1.8M in / 140k out.
EST_IN_TOKENS = 1_800_000
EST_OUT_TOKENS = 140_000

# Manually-updatable intelligence tiers (0–100, higher = smarter). Substring match,
# first hit wins; anything unmatched defaults to 50. Edit this table to re-rank.
INTELLIGENCE_TIERS: list[tuple[str, int]] = [
    ("gpt-6-astra", 100),          # flagship reasoning
    ("gpt-6-sol-pro", 96),
    ("gpt-6-sol", 94),
    ("claude-opus-5.5", 93),
    ("gemini-3.8-pro", 92),
    ("grok-4.6", 90),
    ("gpt-6-luna-pro", 88),
    ("gpt-6-luna", 84),
    ("glm-5.3-prime", 82),
    ("deepseek-v4-pro", 80),
    ("glm-5.3-flashx", 76),
    ("deepseek-v4.1", 75),
    ("claude-sonnet", 74),
    ("glm-5.3", 74),
    ("gemini-3.8-flash", 72),
    ("glm-5.3-flash", 70),
    ("deepseek-v4-flash", 68),
    ("minimax-m", 66),
    ("kimi-k3", 66),
    ("mistral-large", 62),
    ("llama-", 48),
]
DEFAULT_TIER = 50

# Hand-picked best-value pairs surfaced at the top of the dropdowns.
RECOMMENDED = ["z-ai/glm-5.3-flash", "deepseek/deepseek-v4.1-flash", "openai/gpt-6-luna"]


def _tier(model_id: str) -> int:
    low = model_id.lower()
    # longest pattern wins so "glm-5.3-flash" is not shadowed by "glm-5.3"
    for pat, t in sorted(INTELLIGENCE_TIERS, key=lambda x: -len(x[0])):
        if pat in low:
            return t
    return DEFAULT_TIER


def _est_run_cost(pricing: dict) -> float:
    pin = float(pricing.get("prompt", 0) or 0)
    pout = float(pricing.get("completion", 0) or 0)
    return pin * EST_IN_TOKENS + pout * EST_OUT_TOKENS


def _fmt(m: dict) -> dict:
    pricing = m.get("pricing") or {}
    pin = float(pricing.get("prompt", 0) or 0) * 1e6
    pout = float(pricing.get("completion", 0) or 0) * 1e6
    est = _est_run_cost(pricing)
    tier = _tier(m["id"])
    # floor at $0.02/1M blended so free models don't divide by ~zero
    cost_index = max((pin * 0.9 + pout * 0.1) / 2, 0.02)
    return {
        "id": m["id"],
        "name": m.get("name", m["id"]),
        "in_per_m": round(pin, 2),
        "out_per_m": round(pout, 2),
        "est_per_run": round(est, 2),
        "context_k": round((m.get("context_length") or 0) / 1000),
        "tier": tier,
        "value_score": round(tier / cost_index, 1),
        "free": pin == 0 and pout == 0,
    }


def build_catalog(raw: list[dict]) -> dict:
    """Pure transform: OpenRouter raw → sorted, cost-annotated, recommended-pinned."""
    models = [_fmt(m) for m in raw if not any(t in m["id"] for t in (":batch", ":floor")) and not m["id"].startswith("~")]
    models.sort(key=lambda x: (-x["value_score"], x["est_per_run"], x["id"]))
    rest, pinned = list(models), []
    for mid in RECOMMENDED:
        for m in rest:
            if m["id"] == mid:
                m["recommended"] = True
                rest.remove(m)
                pinned.append(m)
                break
    models = pinned + rest
    return {"models": models, "count": len(models), "fetched_at": time.time(),
            "sorted_by": "recommended (intelligence per $) first · curated picks pinned top",
            "est_run_basis": f"{EST_IN_TOKENS/1e6:.1f}M in / {EST_OUT_TOKENS/1e3:.0f}k out"}


def fetch_models(timeout: int = 20) -> dict:
    """Live catalog fetch → build_catalog. Raises on network failure."""
    with urlopen(MODELS_URL, timeout=timeout) as r:
        raw = json.loads(r.read())["data"]
    return build_catalog(raw)


class CatalogCache:
    """TTL-wrapped catalog with manual refresh + offline fallback to last good copy."""

    def __init__(self, ttl_s: int = 3600):
        self.ttl = ttl_s
        self._at: float = 0
        self._data: dict | None = None

    def get(self, force: bool = False) -> dict:
        if not force and self._data and time.time() - self._at < self.ttl:
            return self._data
        data = fetch_models()
        self._data, self._at = data, time.time()
        return data

    def try_get(self, force: bool = False) -> tuple[dict | None, str | None]:
        try:
            return self.get(force=force), None
        except Exception as e:
            if self._data:
                return {**self._data, "stale": True}, None
            return None, str(e)[:200]


CATALOG = CatalogCache()
