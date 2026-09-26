-- 0002: product deltas from ARCHITECTURE_SPEC/PRODUCT_SPEC (2026-09-26)
-- Applied after 0001_init.sql. Idempotent-ish: uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.

-- ── decisions: QC + human review ─────────────────────────────────────────
alter table decisions
  add column if not exists qc_verdict text not null default 'passed'
    check (qc_verdict in ('passed','needs_review','blocked')),
  add column if not exists user_rating text check (user_rating in ('agree','disagree')),
  add column if not exists note text,
  add column if not exists evidence jsonb not null default '[]';

-- ── agent_reports: quality gate ──────────────────────────────────────────
alter table agent_reports
  add column if not exists quality_grade text check (quality_grade in ('A+','A','A-','B+','B','B-','C+','C','D','F')),
  add column if not exists quality_score smallint check (quality_score between 0 and 100),
  add column if not exists quality_notes jsonb not null default '{}';

-- ── runs: presets, provider transparency, token split ────────────────────
alter table runs
  add column if not exists depth_preset text not null default 'standard'
    check (depth_preset in ('fast','standard','deep')),
  add column if not exists effective_provider text,
  add column if not exists tokens_cached int not null default 0,
  add column if not exists tokens_uncached int not null default 0,
  add column if not exists tool_calls int not null default 0,
  add column if not exists elapsed_seconds int;

-- ── job requeue RPC (attempts < max_attempts -> pending, else failed) ────
create or replace function requeue_job(p_job uuid, p_error text) returns void
language plpgsql as $$
begin
  update jobs
     set status = case when attempts < max_attempts then 'pending' else 'failed' end,
         last_error = p_error,
         locked_by = null, locked_at = null,
         finished_at = case when attempts < max_attempts then null else now() end
   where id = p_job;
end $$;

-- ── moomoo realtime quotes (WS ingestion) ────────────────────────────────
create table if not exists quotes_realtime (
  symbol        text primary key,
  last          numeric(18,8),
  prev_close    numeric(18,8),
  bid           numeric(18,8),
  ask           numeric(18,8),
  volume        bigint,
  session       text,
  update_time   timestamptz,
  received_at   timestamptz not null default now()
);

create table if not exists quote_ticks (
  symbol      text not null,
  sequence    bigint not null,
  price       numeric(18,8) not null,
  volume      bigint,
  direction   smallint,
  ts          timestamptz,
  received_at timestamptz not null default now(),
  primary key (symbol, sequence)
);

-- ── vendor budget ledger (moomoo 30/min per path-template) ───────────────
create table if not exists vendor_budget_ledger (
  vendor       text not null,
  path_template text not null,
  window_start timestamptz not null,          -- server-minute window
  used         int not null default 0,
  limit_n      int not null default 30,
  primary key (vendor, path_template, window_start)
);

-- ── discovery candidates (Market Pulse trigger feed) ─────────────────────
create table if not exists discovery_candidates (
  id           uuid primary key default gen_random_uuid(),
  trigger_type text not null check (trigger_type in ('screen','news','earnings','macro','watchlist')),
  symbol       text,
  market       text,
  title        text not null,
  reason       text not null,
  score        int not null default 0,
  sources      jsonb not null default '[]',
  status       text not null default 'open' check (status in ('open','run_queued','dismissed','expired')),
  job_id       uuid references jobs (id),
  created_at   timestamptz not null default now(),
  unique (trigger_type, symbol, title)
);
create index if not exists discovery_open_idx on discovery_candidates (status, created_at desc);
alter table discovery_candidates enable row level security;
create policy "read candidates" on discovery_candidates for select using (true);

-- RLS for the new market tables (client read-only)
alter table quotes_realtime   enable row level security;
alter table quote_ticks       enable row level security;
create policy "read quotes" on quotes_realtime for select using (true);
create policy "read ticks"  on quote_ticks    for select using (true);
