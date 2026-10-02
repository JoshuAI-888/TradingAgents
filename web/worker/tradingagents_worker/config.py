"""Worker configuration from environment. No secrets are logged, ever."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field


def _bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).lower() in ("1", "true", "yes")


@dataclass
class Settings:
    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    # Service-role key: worker only. Never exposed to the portal.
    supabase_service_key: str = field(default_factory=lambda: os.getenv("SUPABASE_SERVICE_KEY", ""))
    # Worker-owned shared secret for API→worker-triggered actions (crons).
    cron_secret: str = field(default_factory=lambda: os.getenv("CRON_SECRET", ""))

    # LLM (one provider key required for real runs; stub mode needs none)
    llm_provider: str = field(
        default_factory=lambda: os.getenv(
            "TRADINGAGENTS_PROVIDER", "openrouter" if os.getenv("OPENROUTER_API_KEY") else "openai"
        )
    )
    quick_model: str = field(
        default_factory=lambda: os.getenv(
            "TRADINGAGENTS_QUICK_MODEL",
            # Cheap-mode-first (product decision): GLM-5.3-flash ≈ $0.14/run vs ≈ $4.98 GPT-6.
            # OpenRouter accepts any model ID; gpt-6-sol/luna are the premium upgrade.
            "z-ai/glm-5.3-flash" if os.getenv("OPENROUTER_API_KEY") else "gpt-6-luna",
        )
    )
    deep_model: str = field(
        default_factory=lambda: os.getenv(
            "TRADINGAGENTS_DEEP_MODEL",
            "z-ai/glm-5.3-flash" if os.getenv("OPENROUTER_API_KEY") else "gpt-6-sol",
        )
    )

    # Behavior
    stub_mode: bool = field(default_factory=lambda: _bool("WORKER_STUB_MODE", "1"))
    poll_interval_s: float = field(
        default_factory=lambda: float(os.getenv("WORKER_POLL_INTERVAL", "3"))
    )
    max_concurrent: int = field(
        default_factory=lambda: int(os.getenv("WORKER_MAX_CONCURRENT", "1"))
    )
    cancel_poll_s: float = field(
        default_factory=lambda: float(os.getenv("WORKER_CANCEL_POLL", "5"))
    )

    # Data vendors
    moomoo_appkey: str = field(default_factory=lambda: os.getenv("MOOMOO_APPKEY", ""))
    moomoo_private_key: str = field(default_factory=lambda: os.getenv("MOOMOO_PRIVATE_KEY", ""))
    fred_api_key: str = field(default_factory=lambda: os.getenv("FRED_API_KEY", ""))
    fmp_api_key: str = field(default_factory=lambda: os.getenv("FMP_API_KEY", ""))

    # Paths. Web services mount /tmp paths explicitly (render.yaml); Render
    # CRON jobs have no disk and /data is not writable there, so an unset env
    # falls back to a writable temp dir — the hard-coded /data default used to
    # crash every discovery cron run at import (PermissionError, exit 1).
    cache_dir: str = field(default_factory=lambda: _path("TRADINGAGENTS_CACHE_DIR", "/data/cache"))
    results_dir: str = field(
        default_factory=lambda: _path("TRADINGAGENTS_RESULTS_DIR", "/data/results")
    )

    def missing_critical(self) -> list[str]:
        need = []
        if not self.supabase_url:
            need.append("SUPABASE_URL")
        if not self.supabase_service_key:
            need.append("SUPABASE_SERVICE_KEY")
        if not self.stub_mode and not (
            os.getenv("OPENAI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("DEEPSEEK_API_KEY")
            or os.getenv("ZHIPU_API_KEY")
            or os.getenv("OPENROUTER_API_KEY")
        ):
            need.append("one LLM API key (OPENROUTER_API_KEY or equivalent)")
        return need


def _path(env_key: str, disk_path: str) -> str:
    """Explicit env wins; otherwise use the disk path when writable, else /tmp."""
    env = os.getenv(env_key)
    if env:
        return env
    try:
        os.makedirs(disk_path, exist_ok=True)
        return disk_path
    except OSError:
        fallback = os.path.join(
            tempfile.gettempdir(), "tradingagents", disk_path.strip("/").replace("/", "-")
        )
        os.makedirs(fallback, exist_ok=True)
        return fallback


SETTINGS = Settings()
