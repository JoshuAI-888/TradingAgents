"""Saved agent-prompt versions (Settings → Agent prompts).

prompt_versions holds every saved version (seeded with the engine's stock
text); app_settings key 'prompts' maps agent_key → active version, absent =
stock prompt. The worker applies the active set to the engine's prompt
registry before each run; the API serves the store to the Settings page.
"""

from __future__ import annotations

from .db import Db

SETTING_KEY = "prompts"


def _load_agent_prompts() -> dict[str, str] | None:
    """The engine's stock prompts. Normal package import in deployed envs;
    direct file load as fallback — prompt_texts.py is stdlib-only, and dev/test
    venvs (web/.venv) often lack the engine's heavy deps (langgraph) that the
    agents package __init__ pulls in."""
    try:
        from tradingagents.agents.prompt_texts import AGENT_PROMPTS

        return AGENT_PROMPTS
    except Exception:
        pass
    try:
        import importlib.util
        from pathlib import Path

        candidate = (
            Path(__file__).resolve().parents[3] / "tradingagents" / "agents" / "prompt_texts.py"
        )
        spec = importlib.util.spec_from_file_location("ta_prompt_texts", candidate)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.AGENT_PROMPTS
    except Exception:
        return None


def active_selection(db: Db) -> dict[str, int]:
    rows = db.select("app_settings", {"key": f"eq.{SETTING_KEY}"}, "value")
    value = (rows[0].get("value") or {}) if rows else {}
    return {str(k): int(v) for k, v in value.items()}


def active_prompt_overrides(db: Db) -> dict[str, str]:
    """agent_key → prompt text for every agent with an active saved version."""
    out: dict[str, str] = {}
    try:
        sel = active_selection(db)
        for agent_key, version in sel.items():
            rows = db.select(
                "prompt_versions",
                {"agent_key": f"eq.{agent_key}", "version": f"eq.{version}"},
                "content",
            )
            if rows and (rows[0].get("content") or "").strip():
                out[agent_key] = rows[0]["content"]
    except Exception as e:
        print(f"prompt overrides (non-fatal): {e}", flush=True)
    return out


def seed_prompt_defaults(db: Db) -> None:
    """One-time per agent: store the engine's stock prompts as version 1 so the
    Settings page can show them (the API process has no engine installed).
    Skips agents that already have any saved version; a missing engine
    (stub-only deployment) or table skips seeding entirely."""
    agent_prompts = _load_agent_prompts()
    if not agent_prompts:
        return
    try:
        existing = {r["agent_key"] for r in db.select("prompt_versions", {}, "agent_key")}
    except Exception:
        return  # table not migrated yet
    for agent_key, text in agent_prompts.items():
        if agent_key in existing:
            continue
        try:
            db.insert(
                "prompt_versions",
                {
                    "agent_key": agent_key,
                    "version": 1,
                    "content": text,
                    "note": "engine stock prompt",
                },
                prefer="return=minimal",
            )
        except Exception as e:
            print(f"prompt seed {agent_key} (non-fatal): {e}", flush=True)
