-- 0011: screener enrichment (yfinance fields + computed technicals) and the
-- daily kline store the technicals are computed from. Rows are keyed by
-- (market, code); `data` holds only fields that actually resolved — a missing
-- key means "no data", never zero. Freshness: `as_of` per row (spec §5b).
create table if not exists screener_enrichment (
  market     text not null,
  code       text not null,
  data       jsonb not null default '{}'::jsonb,
  source     text not null default 'yfinance+computed',
  as_of      timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  primary key (market, code)
);

create table if not exists screener_klines (
  market text not null,
  code   text not null,
  day    date not null,
  o double precision,
  h double precision,
  l double precision,
  c double precision,
  v double precision,
  primary key (market, code, day)
);
create index if not exists screener_klines_code_idx on screener_klines (market, code, day);

-- Rotation bookkeeping for the kline backfill: which codes are fresh enough
-- to skip tonight (PostgREST can't GROUP BY max(day) cheaply at 13k codes).
create table if not exists screener_kline_state (
  market     text not null,
  code       text not null,
  last_fetch timestamptz not null default now(),
  bars       int,
  primary key (market, code)
);
