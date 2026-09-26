"""Model-catalog tests: value sort, cost math, recommended pinning — offline via fixture."""
from __future__ import annotations

from tradingagents_worker import openrouter as orr


def fake_raw():
    return [
        {"id": "openai/gpt-6-sol", "name": "GPT-6 Sol", "context_length": 400000,
         "pricing": {"prompt": "0.000002", "completion": "0.00001"}},
        {"id": "z-ai/glm-5.3-flash", "name": "GLM 5.3 Flash", "context_length": 200000,
         "pricing": {"prompt": "0.00000004", "completion": "0.0000005"}},
        {"id": "some/unknown-model", "name": "Unknown", "context_length": 128000,
         "pricing": {"prompt": "0.0000001", "completion": "0.0000002"}},
        {"id": "free/test", "name": "Free", "context_length": 32000,
         "pricing": {"prompt": "0", "completion": "0"}},
        {"id": "openai/gpt-6-luna", "name": "GPT-6 Luna", "context_length": 400000,
         "pricing": {"prompt": "0.0000001", "completion": "0.0000005"}},
        {"id": "openai/gpt-6-luna:batch", "name": "batch variant", "context_length": 1,
         "pricing": {"prompt": "0", "completion": "0"}},  # must be filtered out
    ]


def test_build_sorts_pins_and_filters():
    out = orr.build_catalog(fake_raw())
    ids = [m["id"] for m in out["models"]]
    assert ids[0] == "z-ai/glm-5.3-flash"                # recommended pinned #1
    assert ids[1] == "openai/gpt-6-luna"                 # recommended pinned #2 (deepseek absent from fixture)
    assert "openai/gpt-6-luna:batch" not in ids          # batch variants filtered
    recs = [m for m in out["models"] if m.get("recommended")]
    assert [m["id"] for m in recs] == ["z-ai/glm-5.3-flash", "openai/gpt-6-luna"]


def test_cost_math_matches_run_mix():
    m = {x["id"]: x for x in orr.build_catalog(fake_raw())["models"]}
    sol = m["openai/gpt-6-sol"]
    assert sol["in_per_m"] == 2.0 and sol["out_per_m"] == 10.0
    assert abs(sol["est_per_run"] - 5.0) < 0.01          # 2.0*1.8 + 10.0*0.14
    flash = m["z-ai/glm-5.3-flash"]
    assert abs(flash["est_per_run"] - 0.142) < 0.01      # 0.04*1.8 + 0.50*0.14
    assert m["free/test"]["free"] is True


def test_tier_specificity_and_default():
    m = {x["id"]: x for x in orr.build_catalog(fake_raw())["models"]}
    assert m["z-ai/glm-5.3-flash"]["tier"] == 70          # "glm-5.3-flash", not shadowed by "glm-5.3"
    assert m["openai/gpt-6-sol"]["tier"] == 94
    assert m["some/unknown-model"]["tier"] == orr.DEFAULT_TIER
    # flash must not inherit the parent-family tier
    assert m["z-ai/glm-5.3-flash"]["tier"] < 74


def test_free_models_do_not_divide_by_zero():
    m = {x["id"]: x for x in orr.build_catalog(fake_raw())["models"]}
    assert m["free/test"]["value_score"] == m["free/test"]["tier"] / 0.02


def test_cache_falls_back_to_stale_copy(monkeypatch):
    c = orr.CatalogCache(ttl_s=3600)
    monkeypatch.setattr(orr, "fetch_models", lambda timeout=20: orr.build_catalog(fake_raw()))
    first, err = c.try_get()
    assert err is None and first["count"] == 5

    def boom(timeout=20):
        raise RuntimeError("network down")
    monkeypatch.setattr(orr, "fetch_models", boom)
    second, err2 = c.try_get(force=True)
    assert err2 is None and second["stale"] is True
