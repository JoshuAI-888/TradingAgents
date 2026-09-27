-- 0006: post-run digest — structured evidence register, scenario/sensitivity
-- table, news classification and per-agent QC grades rendered by the dossier.
-- One row per run (upsert target); service key only, like app_settings.
create table if not exists run_digest (
  run_id     uuid primary key references runs (id) on delete cascade,
  digest     jsonb not null,
  model      text,
  created_at timestamptz not null default now()
);

alter table run_digest enable row level security;
