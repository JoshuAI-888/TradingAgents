-- 0009: saved agent-prompt versions (Settings → Agent prompts).
-- One row per saved version; app_settings key 'prompts' maps agent_key →
-- active version (absent = engine stock prompt). The worker seeds version 1
-- with the engine's stock text on boot and applies the active set per run.
create table if not exists prompt_versions (
  id         uuid primary key default gen_random_uuid(),
  agent_key  text not null,
  version    int  not null,
  content    text not null,
  note       text,
  created_at timestamptz not null default now(),
  unique (agent_key, version)
);

create index if not exists prompt_versions_agent on prompt_versions (agent_key, version desc);

alter table prompt_versions enable row level security;
-- No policies: API service role only (single-user Phase 0), like saved_screeners.
