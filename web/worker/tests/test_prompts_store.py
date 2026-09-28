"""Saved prompt versions: selection → overrides; engine stock-prompt seeding."""
from __future__ import annotations

import sys
from pathlib import Path

# The engine lives at the repo root; prompt_texts is stdlib-only so importing
# it here (unlike the CI root suite) needs no langchain.
ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "ta_prompt_texts", ROOT / "tradingagents" / "agents" / "prompt_texts.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
AGENT_PROMPTS = _mod.AGENT_PROMPTS

from tradingagents_worker.prompts_store import (  # noqa: E402
    active_prompt_overrides,
    active_selection,
    seed_prompt_defaults,
)


def test_selection_and_overrides_default_empty(fake_db):
    assert active_selection(fake_db) == {}
    assert active_prompt_overrides(fake_db) == {}


def test_overrides_resolve_active_versions_only(fake_db):
    fake_db.upsert("app_settings", "key", {"key": "prompts", "value": {"trader": 2}})
    for version, content in ((1, "stock"), (2, "custom v2"), (3, "v3 not active")):
        fake_db.insert("prompt_versions", {"agent_key": "trader", "version": version,
                                           "content": content}, prefer="return=minimal")
    assert active_prompt_overrides(fake_db) == {"trader": "custom v2"}


def test_blank_active_version_is_skipped(fake_db):
    fake_db.upsert("app_settings", "key", {"key": "prompts", "value": {"trader": 1}})
    fake_db.insert("prompt_versions", {"agent_key": "trader", "version": 1, "content": "  "},
                   prefer="return=minimal")
    assert active_prompt_overrides(fake_db) == {}


def test_seed_stores_engine_stock_prompts_once(fake_db):
    seed_prompt_defaults(fake_db)
    assert set(AGENT_PROMPTS) <= {r["agent_key"] for r in fake_db.select("prompt_versions", {}, "agent_key")}
    seed_prompt_defaults(fake_db)  # idempotent: no duplicate version rows
    rows = fake_db.select("prompt_versions", {}, "agent_key,version")
    assert len([r for r in rows if r["agent_key"] == "trader"]) == 1
    stock = next(r for r in rows if r["agent_key"] == "trader")
    assert stock["content"] == AGENT_PROMPTS["trader"] and stock["version"] == 1
