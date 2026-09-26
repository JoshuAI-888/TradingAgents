-- ============================================================================
-- TradingAgents product schema — Supabase Postgres (migration 0001)
--
-- Domains:
--   1. Identity & configuration     4. Ingest telemetry
--   2. Instrument master            5. Orchestration (queue, runs, backtests)
--   3. Market data (PIT-correct)    6. Inference outputs (reports, decisions,
--                                      settlements, memory, embeddings, reports)
--
-- Conventions:
--   * uuid PKs (gen_random_uuid), timestamptz everywhere, snake_case.
--   * Enums as text + CHECK constraints (easier to evolve than PG enums).
--   * Point-in-time correctness: every time-varying fact carries the date it
--     is true FOR (as_of/bar_date/period_end) and, where the source revises
--     history, the vintage date it became KNOWN (filed_at/vintage_date).
--   * Tenancy: user-scoped tables have user_id and RLS enabled; the worker
--     uses the service role (bypasses RLS). Market-data tables are read-only
--     to clients and written only by the worker.
-- ============================================================================

create extension if not exists pgcrypto;
create extension if not exists vector;      -- pgvector: similarity retrieval

-- ---------------------------------------------------------------------------
-- Helpers
-- ---------------------------------------------------------------------------

create or replace function set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

-- enqueue_job: single insert point for the queue
create or replace function enqueue_job(
  p_job_type text, p_user_id uuid, p_payload jsonb,
  p_priority int default 100
) returns uuid language sql as $$
  insert into jobs (job_type, user_id, payload, priority)
  values (p_job_type, p_user_id, p_payload, p_priority)
  returning id;
$$;

-- claim_job: concurrent-safe dequeue (FOR UPDATE SKIP LOCKED)
create or replace function claim_job(p_worker text, p_types text[] default null)
returns jobs language plpgsql as $$
declare j jobs;
begin
  select * into j from jobs
   where status = 'pending'
     and (p_types is null or job_type = any (p_types))
   order by priority desc, created_at
   for update skip locked limit 1;
  if found then
    update jobs
       set status = 'running', locked_by = p_worker, locked_at = now(),
           attempts = attempts + 1, started_at = coalesce(started_at, now())
     where id = j.id
    returning * into j;
  end if;
  return j;
end $$;

-- ---------------------------------------------------------------------------
-- 1. IDENTITY & CONFIGURATION
-- ---------------------------------------------------------------------------

create table profiles (
  id            uuid primary key references auth.users (id) on delete cascade,
  display_name  text,
  timezone      text not null default 'UTC',
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create table user_settings (
  user_id             uuid primary key references profiles (id) on delete cascade,
  llm_provider        text not null default 'openai',
  quick_model         text not null default 'gpt-6-luna',    -- upstream v0.5.1 defaults
  deep_model          text not null default 'gpt-6-sol',
  cheap_mode          boolean not null default true,     -- low-cost models by default
  max_debate_rounds   smallint not null default 1 check (max_debate_rounds between 1 and 5),
  max_risk_rounds     smallint not null default 1 check (max_risk_rounds between 1 and 5),
  risk_profile        text not null default 'balanced'
                        check (risk_profile in ('conservative','balanced','aggressive')),
  settlement_horizons smallint[] not null default '{5,30}',   -- days
  holding_period_days smallint not null default 5,  -- upstream memory/reflection window
  benchmark_default   text not null default 'SPY',
  data_vendors        jsonb not null default '{"prices":"yfinance","news":"yfinance"}',
  notification_prefs  jsonb not null default '{}',       -- channel, digest cadence
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

-- User-supplied datasource/LLM keys. Values are encrypted by the application
-- (or stored as Supabase Vault references in secret_ref); only a masked hint
-- is ever exposed to the client.
create table user_secrets (
  id            uuid primary key default gen_random_uuid(),
  user_id       uuid not null references profiles (id) on delete cascade,
  key_name      text not null check (key_name in
                  ('OPENAI_API_KEY','ANTHROPIC_API_KEY','GOOGLE_API_KEY','DEEPSEEK_API_KEY',
                   'ZHIPU_API_KEY','OPENROUTER_API_KEY','FRED_API_KEY','ALPHA_VANTAGE_API_KEY',
                   'FMP_API_KEY','EODHD_API_KEY','TYPESAFE_API_KEY','OTHER')),
  secret_ref    text not null,          -- vault reference or app-encrypted value
  masked_hint   text,                   -- e.g. 'rnd_…smc8'
  rotated_at    timestamptz,
  created_at    timestamptz not null default now(),
  unique (user_id, key_name)
);

create table watchlists (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references profiles (id) on delete cascade,
  name        text not null,
  is_default  boolean not null default false,
  created_at  timestamptz not null default now(),
  unique (user_id, name)
);

create table watchlist_items (
  id           uuid primary key default gen_random_uuid(),
  watchlist_id uuid not null references watchlists (id) on delete cascade,
  ticker_id    uuid not null references tickers (id) on delete cascade,
  cadence      text not null default 'daily' check (cadence in ('daily','weekly','manual')),
  active       boolean not null default true,
  notes        text,
  created_at   timestamptz not null default now(),
  unique (watchlist_id, ticker_id)
);

-- ---------------------------------------------------------------------------
-- 2. INSTRUMENT MASTER
-- ---------------------------------------------------------------------------

create table tickers (
  id               uuid primary key default gen_random_uuid(),
  symbol           text not null,                       -- canonical, e.g. 'NVDA'
  native_symbol    text not null,                       -- exchange-suffixed, e.g. 'NVDA', 'AAPL.L'
  exchange         text,
  mic              text,                                -- market identifier code
  name             text,
  asset_type       text not null default 'stock' check (asset_type in ('stock','etf','crypto','index')),
  currency         text not null default 'USD',
  benchmark_symbol text,                                -- auto alpha benchmark for this listing
  identity         jsonb not null default '{}',         -- deterministic anti-hallucination identity
  is_active        boolean not null default true,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  unique (native_symbol, exchange)
);
create index tickers_symbol_idx on tickers (symbol);

-- ---------------------------------------------------------------------------
-- 3. MARKET DATA  (worker-written; clients read)
-- ---------------------------------------------------------------------------

create table price_bars (
  ticker_id uuid not null references tickers (id) on delete cascade,
  bar_date  date not null,
  open      numeric(18,8) not null,
  high      numeric(18,8) not null,
  low       numeric(18,8) not null,
  close     numeric(18,8) not null,
  volume    bigint,
  source    text not null default 'yfinance'
              check (source in ('yfinance','alpha_vantage','fmp','eodhd')),
  adjusted  boolean not null default true,               -- split/div adjusted
  fetched_at timestamptz not null default now(),
  primary key (ticker_id, bar_date, source, adjusted)
);
create index price_bars_ticker_date_idx on price_bars (ticker_id, bar_date desc);

-- One JSONB doc per ticker/day: MACD, RSI, MAs, etc. — single-row AI fetch.
create table indicator_snapshots (
  ticker_id uuid not null references tickers (id) on delete cascade,
  as_of     date not null,
  payload   jsonb not null,                              -- {'macd': {...}, 'rsi': {...}}
  source    text not null default 'yfinance',
  computed_at timestamptz not null default now(),
  primary key (ticker_id, as_of, source)
);

create table corporate_actions (
  id          uuid primary key default gen_random_uuid(),
  ticker_id   uuid not null references tickers (id) on delete cascade,
  action_type text not null check (action_type in ('split','dividend')),
  ex_date     date not null,
  ratio       numeric(18,8),                            -- splits: e.g. 10.0
  amount      numeric(18,8),                            -- dividends: per-share cash
  source      text not null,
  created_at  timestamptz not null default now(),
  unique (ticker_id, action_type, ex_date, source)
);

-- Live-style profile; withheld for backtests by the framework (no vintage).
create table company_profiles (
  ticker_id  uuid primary key references tickers (id) on delete cascade,
  payload    jsonb not null,                            -- sector, industry, mcap, employees…
  as_of      timestamptz not null,
  source     text not null
);

-- Quarterly statements. filed_at enables the framework's PIT filter.
create table fundamentals (
  id             uuid primary key default gen_random_uuid(),
  ticker_id      uuid not null references tickers (id) on delete cascade,
  statement_type text not null check (statement_type in
                   ('income_statement','balance_sheet','cashflow')),
  period_end     date not null,
  filed_at       date,                                  -- point-in-time availability
  payload        jsonb not null,
  source         text not null,
  created_at     timestamptz not null default now(),
  unique (ticker_id, statement_type, period_end, source)
);
create index fundamentals_pit_idx on fundamentals (ticker_id, filed_at);

create table insider_transactions (
  id               uuid primary key default gen_random_uuid(),
  ticker_id        uuid not null references tickers (id) on delete cascade,
  transaction_date date not null,
  filed_at         date,
  insider_name     text,
  insider_role     text,
  transaction_type text,                                -- 'Buy','Sale'…
  shares           numeric(18,4),
  price            numeric(18,8),
  value_usd        numeric(20,2),
  source           text not null,
  raw              jsonb,
  created_at       timestamptz not null default now(),
  unique (ticker_id, transaction_date, insider_name, transaction_type, source)
);
create index insider_ticker_date_idx on insider_transactions (ticker_id, transaction_date desc);

create table macro_series (
  series_id  text primary key,                          -- FRED id, e.g. 'DFF'
  title      text,
  units      text,
  frequency  text,
  source     text not null default 'fred',
  meta       jsonb not null default '{}'
);

-- vintage_date = when the value became knowable (PIT fix for FRED revisions).
create table macro_observations (
  series_id   text not null references macro_series (series_id) on delete cascade,
  obs_date    date not null,
  value       numeric(20,6) not null,
  vintage_date date not null,
  primary key (series_id, obs_date, vintage_date)
);
create index macro_obs_pit_idx on macro_observations (series_id, obs_date, vintage_date);

create table news_items (
  id           uuid primary key default gen_random_uuid(),
  source       text not null check (source in ('yfinance','fmp','eodhd','alpha_vantage','other')),
  external_id  text,
  url          text,
  url_hash     text not null,                           -- sha256(normalized url)
  published_at timestamptz not null,                    -- the PIT anchor
  title        text not null,
  publisher    text,
  summary      text,
  tickers      text[] not null default '{}',            -- symbols mentioned
  sentiment    text check (sentiment in ('bullish','bearish','neutral')),
  raw          jsonb,
  ingested_at  timestamptz not null default now(),
  unique (source, url_hash)
);
create index news_published_idx on news_items (published_at desc);
create index news_tickers_idx on news_items using gin (tickers);
create index news_fts_idx on news_items
  using gin (to_tsvector('english', coalesce(title,'') || ' ' || coalesce(summary,'')));

create table social_posts (
  id            uuid primary key default gen_random_uuid(),
  source        text not null check (source in ('stocktwits','reddit')),
  symbol        text,                                   -- StockTwits symbol / subreddit ticker
  external_id   text not null,                          -- message/post id
  published_at  timestamptz not null,
  author        text,
  body          text not null,
  sentiment     text check (sentiment in ('bullish','bearish')),  -- user-labeled (StockTwits)
  raw           jsonb,
  ingested_at   timestamptz not null default now(),
  unique (source, external_id)
);
create index social_symbol_time_idx on social_posts (symbol, published_at desc);

create table prediction_market_quotes (
  id                 uuid primary key default gen_random_uuid(),
  platform           text not null default 'polymarket',
  market_slug        text not null,
  question           text,
  outcome            text,
  implied_probability numeric(6,4) not null check (implied_probability between 0 and 1),
  as_of              timestamptz not null,
  raw                jsonb,
  unique (platform, market_slug, outcome, as_of)
);

-- ---------------------------------------------------------------------------
-- 4. INGEST TELEMETRY  (reliability surface)
-- ---------------------------------------------------------------------------

create table data_fetch_log (
  id         bigserial primary key,
  ts         timestamptz not null default now(),
  vendor     text not null,             -- yfinance|alpha_vantage|fmp|eodhd|fred|reddit|stocktwits|polymarket
  category   text not null,             -- prices|indicators|fundamentals|news|social|macro|insider|prediction_markets
  symbol     text,
  params     jsonb not null default '{}',
  status     text not null check (status in ('ok','empty','rate_limited','error')),
  http_status int,
  latency_ms int,
  from_cache boolean not null default false,
  error      text,
  run_id     uuid                       -- nullable: also logs settlement/cron fetches
);
create index fetch_log_vendor_ts_idx on data_fetch_log (vendor, ts desc);
create index fetch_log_run_idx on data_fetch_log (run_id);

-- Rolling health (refresh nightly or on demand):
create materialized view vendor_health as
select vendor,
       category,
       count(*) filter (where status = 'ok')          as ok_n,
       count(*) filter (where status <> 'ok')         as bad_n,
       round(100.0 * count(*) filter (where status = 'ok') / greatest(count(*),1), 2) as success_pct,
       percentile_disc(0.5) within group (order by latency_ms) as p50_ms,
       percentile_disc(0.95) within group (order by latency_ms) as p95_ms,
       max(ts) as last_call
from data_fetch_log
where ts > now() - interval '7 days'
group by vendor, category;

-- ---------------------------------------------------------------------------
-- 5. ORCHESTRATION
-- ---------------------------------------------------------------------------

create table jobs (
  id           uuid primary key default gen_random_uuid(),
  job_type     text not null check (job_type in ('analysis','settlement','backtest','digest','maintenance')),
  user_id      uuid references profiles (id) on delete cascade,   -- null for system jobs
  status       text not null default 'pending'
                 check (status in ('pending','running','succeeded','failed','cancelled')),
  priority     int not null default 100,                -- lower = sooner
  payload      jsonb not null default '{}',             -- type-specific args
  run_id       uuid,                                    -- set when analysis starts
  attempts     int not null default 0,
  max_attempts int not null default 3,
  locked_by    text,
  locked_at    timestamptz,
  last_error   text,
  idempotency_key text unique,                          -- e.g. 'analysis:NVDA:2026-09-16'
  created_at   timestamptz not null default now(),
  started_at   timestamptz,
  finished_at  timestamptz
);
create index jobs_pending_idx on jobs (created_at)
  where status = 'pending';
create index jobs_user_idx on jobs (user_id, created_at desc);

-- Realtime-streamed progress (Supabase postgres_changes on job_id).
create table job_events (
  id      bigserial primary key,
  job_id  uuid not null references jobs (id) on delete cascade,
  seq     int not null,
  ts      timestamptz not null default now(),
  stage   text not null,      -- analyst_market|bull|bear|research_manager|trader|risk_*|portfolio_manager|tool_call|settlement
  status  text check (status in ('started','progress','done','failed')),
  message text,
  payload jsonb not null default '{}'    -- tool name/args/summary, token deltas
);
create index job_events_job_idx on job_events (job_id, seq);

-- One pipeline execution (framework propagate()).
create table runs (
  id                 uuid primary key default gen_random_uuid(),
  job_id             uuid references jobs (id),
  user_id            uuid references profiles (id) on delete cascade,
  ticker_id          uuid not null references tickers (id),
  trade_date         date not null,
  asset_type         text not null default 'stock',
  config             jsonb not null,          -- full framework config snapshot
  config_hash        text not null,           -- sha256(config): decision-stability sampling
  llm_provider       text,
  quick_model        text,
  deep_model         text,
  status             text not null default 'running'
                       check (status in ('running','succeeded','failed')),
  prompt_tokens      int not null default 0,
  completion_tokens  int not null default 0,
  cost_usd           numeric(10,4) not null default 0,
  error              text,
  framework_version  text,
  storage_bucket     text default 'run-artifacts',
  portfolio_snapshot jsonb not null default '{}',  -- PortfolioContext given to the run (v0.5.0+)
  storage_path       text,                    -- raw agent-state JSON blob (audit trail)
  storage_bytes      bigint,
  storage_sha256     text,
  started_at         timestamptz not null default now(),
  finished_at        timestamptz
);
create index runs_user_date_idx on runs (user_id, trade_date desc);
create index runs_ticker_date_idx on runs (ticker_id, trade_date desc);

create table backtests (
  id          uuid primary key default gen_random_uuid(),
  user_id     uuid not null references profiles (id) on delete cascade,
  name        text not null,
  universe    text[] not null,                 -- symbols
  start_date  date not null,
  end_date    date not null,
  config      jsonb not null,
  status      text not null default 'pending'
                check (status in ('pending','running','succeeded','failed')),
  n_total     int not null default 0,
  n_done      int not null default 0,
  created_at  timestamptz not null default now(),
  finished_at timestamptz
);

create table backtest_runs (
  backtest_id uuid not null references backtests (id) on delete cascade,
  run_id      uuid not null references runs (id),
  primary key (backtest_id, run_id)
);

-- ---------------------------------------------------------------------------
-- 6. INFERENCE OUTPUTS
-- ---------------------------------------------------------------------------

create table agent_reports (
  id               uuid primary key default gen_random_uuid(),
  run_id           uuid not null references runs (id) on delete cascade,
  stage            text not null check (stage in
                     ('analyst_market','analyst_social','analyst_news','analyst_fundamentals',
                      'research_manager','trader','portfolio_manager')),
  content_markdown text not null,
  structured       jsonb,                     -- validated schemas: SentimentReport, ResearchPlan,
                                               -- TraderProposal, PortfolioDecision
  model            text,
  created_at       timestamptz not null default now(),
  unique (run_id, stage)
);

create table debate_messages (
  id          uuid primary key default gen_random_uuid(),
  run_id      uuid not null references runs (id) on delete cascade,
  debate_type text not null check (debate_type in ('research','risk')),
  speaker     text not null check (speaker in ('bull','bear','aggressive','conservative','neutral')),
  round       int not null,
  content     text not null,
  model       text,
  created_at  timestamptz not null default now()
);
create index debate_run_idx on debate_messages (run_id, debate_type, round);

-- THE product row: one auditable recommendation.
create table decisions (
  id                uuid primary key default gen_random_uuid(),
  run_id            uuid not null unique references runs (id) on delete cascade,
  user_id           uuid not null references profiles (id) on delete cascade,
  ticker_id         uuid not null references tickers (id),
  trade_date        date not null,
  rating            text not null check (rating in
                      ('buy','overweight','hold','underweight','sell')),
  rating_rank       smallint not null check (rating_rank between 1 and 5),  -- sell=1 … buy=5
  signal            text not null check (signal in ('buy','sell','hold','review')),
  is_review         boolean not null default false,   -- unparseable → human review queue
  executive_summary text,
  thesis            text,
  price_target      numeric(18,8),
  time_horizon      text,
  entry_price       numeric(18,8),                    -- trader proposal levels
  stop_loss         numeric(18,8),
  position_size_pct numeric(6,3),
  full_decision     jsonb not null,                   -- complete PM output
  created_at        timestamptz not null default now()
);
create index decisions_user_date_idx on decisions (user_id, trade_date desc);
create index decisions_ticker_date_idx on decisions (ticker_id, trade_date desc);
create index decisions_rating_idx on decisions (rating);

-- Owned-by-us settlement ledger: what actually happened next.
create table settlements (
  id                   uuid primary key default gen_random_uuid(),
  decision_id          uuid not null references decisions (id) on delete cascade,
  horizon_days         int not null check (horizon_days > 0),  -- upstream holding_period_days is configurable
  status               text not null default 'pending'
                         check (status in ('pending','settled','failed','insufficient_data')),
  as_of_date           date,                            -- trade_date + horizon
  entry_price          numeric(18,8),                   -- close on trade_date (adjusted)
  exit_price           numeric(18,8),
  benchmark_symbol     text not null default 'SPY',
  benchmark_entry      numeric(18,8),
  benchmark_exit       numeric(18,8),
  raw_return_pct       numeric(10,4),
  benchmark_return_pct numeric(10,4),
  alpha_pct            numeric(10,4),
  max_favorable_pct    numeric(10,4),                   -- best close within window
  max_adverse_pct      numeric(10,4),                   -- worst close within window
  source               text,
  error                text,
  settled_at           timestamptz,
  unique (decision_id, horizon_days)
);
create index settlements_due_idx on settlements (status, as_of_date);

create table reflections (
  id          uuid primary key default gen_random_uuid(),
  decision_id uuid not null references decisions (id) on delete cascade,
  user_id     uuid not null references profiles (id) on delete cascade,
  ticker_id   uuid not null references tickers (id),
  lesson      text not null,          -- 2–4 sentences, from the framework Reflector
  model       text,
  created_at  timestamptz not null default now()
);

-- The memory log, promoted from markdown to a table. Past-context injection =
-- last N resolved rows for (user, ticker) with entry_date <= as_of.
create table memory_entries (
  id             uuid primary key default gen_random_uuid(),
  user_id        uuid not null references profiles (id) on delete cascade,
  ticker_id      uuid not null references tickers (id),
  decision_id    uuid references decisions (id) on delete set null,
  entry_date     date not null,             -- the decision's trade_date (PIT guard key)
  rating         text,
  raw_return_pct numeric(10,4),
  alpha_pct      numeric(10,4),
  reflection     text,
  status         text not null default 'pending' check (status in ('pending','resolved')),
  resolved_at    timestamptz,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);
create index memory_context_idx on memory_entries (user_id, ticker_id, entry_date desc);
create trigger memory_updated_at before update on memory_entries
  for each row execute function set_updated_at();

-- pgvector similarity: "past setups like this one".
create table embeddings (
  id              uuid primary key default gen_random_uuid(),
  entity_type     text not null check (entity_type in
                    ('decision','news_item','reflection','social_post')),
  entity_id       uuid not null,
  user_id         uuid references profiles (id) on delete cascade,  -- null = global corpus
  embedding_model text not null,
  content_hash    text not null,
  embedding       vector(1536) not null,    -- e.g. text-embedding-3-small
  created_at      timestamptz not null default now(),
  unique (entity_type, entity_id, embedding_model)
);
create index embeddings_hnsw_idx on embeddings
  using hnsw (embedding vector_cosine_ops);

-- Composed artifacts (digests, weekly summaries, run report bundles).
create table report_artifacts (
  id               uuid primary key default gen_random_uuid(),
  user_id          uuid not null references profiles (id) on delete cascade,
  kind             text not null check (kind in
                     ('run_report','daily_digest','weekly_summary','backtest_report')),
  run_id           uuid references runs (id) on delete set null,
  title            text not null,
  content_markdown text not null,
  storage_path     text,
  meta             jsonb not null default '{}',
  created_at       timestamptz not null default now()
);
create index artifacts_user_idx on report_artifacts (user_id, created_at desc);

-- ---------------------------------------------------------------------------
-- Row Level Security
--   * user-scoped tables: owner-only via auth.uid(); worker uses service role.
--   * market-data tables: public read, service-only write (no client policies).
--   * jobs/job_events: owner read (progress streaming), service-only write.
-- ---------------------------------------------------------------------------

alter table profiles            enable row level security;
alter table user_settings       enable row level security;
alter table user_secrets        enable row level security;
alter table watchlists          enable row level security;
alter table watchlist_items     enable row level security;
alter table runs                enable row level security;
alter table agent_reports       enable row level security;
alter table debate_messages     enable row level security;
alter table decisions           enable row level security;
alter table settlements         enable row level security;
alter table reflections         enable row level security;
alter table memory_entries      enable row level security;
alter table report_artifacts    enable row level security;
alter table backtests           enable row level security;
alter table jobs                enable row level security;
alter table job_events          enable row level security;
alter table tickers             enable row level security;
alter table price_bars          enable row level security;
alter table indicator_snapshots enable row level security;
alter table news_items          enable row level security;

create policy "own profile"    on profiles         for all    using (auth.uid() = id);
create policy "own settings"   on user_settings    for all    using (auth.uid() = user_id);
create policy "own secrets"    on user_secrets     for select using (auth.uid() = user_id);
create policy "own watchlists" on watchlists       for all    using (auth.uid() = user_id);
create policy "own wl items"   on watchlist_items  for all    using (
  exists (select 1 from watchlists w where w.id = watchlist_id and w.user_id = auth.uid()));
create policy "own runs"       on runs             for select using (auth.uid() = user_id);
create policy "own reports"    on agent_reports    for select using (
  exists (select 1 from runs r where r.id = run_id and r.user_id = auth.uid()));
create policy "own debates"    on debate_messages  for select using (
  exists (select 1 from runs r where r.id = run_id and r.user_id = auth.uid()));
create policy "own decisions"  on decisions        for select using (auth.uid() = user_id);
create policy "own settlements" on settlements     for select using (
  exists (select 1 from decisions d where d.id = decision_id and d.user_id = auth.uid()));
create policy "own reflections" on reflections     for select using (auth.uid() = user_id);
create policy "own memory"     on memory_entries   for all    using (auth.uid() = user_id);
create policy "own artifacts"  on report_artifacts for all    using (auth.uid() = user_id);
create policy "own backtests"  on backtests        for all    using (auth.uid() = user_id);
create policy "own jobs"       on jobs             for select using (auth.uid() = user_id);
create policy "own job events" on job_events       for select using (
  exists (select 1 from jobs j where j.id = job_id and (j.user_id = auth.uid() or j.user_id is null)));
create policy "read tickers"   on tickers          for select using (true);
create policy "read bars"      on price_bars       for select using (true);
create policy "read indicators" on indicator_snapshots for select using (true);
create policy "read news"      on news_items       for select using (true);

-- NOTE (client writes): profiles/settings/watchlists are written by the portal
-- via the anon key under RLS. Everything else is written exclusively by the
-- worker with the service role (bypasses RLS).

-- ---------------------------------------------------------------------------
-- Reporting views
-- ---------------------------------------------------------------------------

create view v_decision_ledger as
select d.id, d.user_id, t.symbol, t.name, d.trade_date, d.rating, d.rating_rank, d.signal,
       d.executive_summary, d.price_target, d.time_horizon,
       s.horizon_days, s.raw_return_pct, s.benchmark_return_pct, s.alpha_pct, s.status as settlement_status
from decisions d
join tickers t on t.id = d.ticker_id
left join settlements s on s.decision_id = d.id
where d.is_review = false;

create view v_equity_curve as
select user_id, trade_date, horizon_days,
       alpha_pct,
       sum(alpha_pct) over (partition by user_id, horizon_days order by trade_date) as cum_alpha_pct,
       count(*) over (partition by user_id, horizon_days) as n_decisions
from v_decision_ledger
where settlement_status = 'settled';
