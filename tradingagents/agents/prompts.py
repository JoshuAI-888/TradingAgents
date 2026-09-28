"""Runtime prompt overrides for the agent graph.

The portal worker registers saved prompt versions (Settings → Agent prompts)
before each run; agents resolve their stock template against this registry at
node-call time, so an edited prompt applies to the next run without rebuilding
the cached graph. Pure stdlib — importable without the framework's heavy deps.
"""
from __future__ import annotations

OVERRIDES: dict[str, str] = {}


def register(overrides: dict[str, str] | None) -> None:
    """Replace the active override set (one call per run keeps it consistent)."""
    OVERRIDES.clear()
    for key, text in (overrides or {}).items():
        if str(text or "").strip():
            OVERRIDES[str(key)] = str(text)


def resolve(key: str, default: str) -> str:
    """The saved override for `key`, or the stock template when unset."""
    return OVERRIDES.get(key) or default


def render(template: str, **values) -> str:
    """Brace-safe placeholder substitution — str.format would choke on literal
    braces inside saved prompts, and agent prompts carry JSON/markdown text."""
    for key, value in values.items():
        template = template.replace("{" + key + "}", "" if value is None else str(value))
    return template
