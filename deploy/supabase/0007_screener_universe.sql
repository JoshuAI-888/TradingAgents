-- 0007: full-market screener universe + quotes (loaded by the worker's
-- universe_refresh job; the API reads these instead of calling moomoo live).
create table if not exists screener_universe (
  market     text not null,
  code       text not null,
  name       text,
  plate      text,
  updated_at timestamptz not null default now(),
  primary key (market, code)
);

create table if not exists screener_quotes (
  code       text primary key,
  market     text not null,
  row        jsonb not null,          -- the normalized screener row (see api _snapshot_to_row)
  updated_at timestamptz not null default now()
);

create index if not exists screener_quotes_market on screener_quotes (market);
create index if not exists screener_universe_market on screener_universe (market);

alter table screener_universe enable row level security;
alter table screener_quotes  enable row level security;
-- No policies: worker/API service role only, like app_settings.

-- the universe loader runs as a queued job; widen the job_type domain
alter table jobs drop constraint jobs_job_type_check;
alter table jobs add constraint jobs_job_type_check
  check (job_type in ('analysis','settlement','backtest','digest','maintenance','universe_refresh'));
