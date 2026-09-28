-- 0008: user-saved screeners (the "Save Screener" feature) — a named, editable
-- filter set over the screener (market + universe mode + filters + sort).
create table if not exists saved_screeners (
  id             uuid primary key default gen_random_uuid(),
  user_id        text not null,
  name           text not null,
  description    text,
  market         text not null default 'US',
  watchlist_only boolean not null default false,
  filters        jsonb not null default '[]',   -- [{field,min,max,needs?}]
  sort           text not null default 'market_cap',
  direction      int not null default 2,        -- 1 asc / 2 desc (moomoo enum)
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists saved_screeners_user on saved_screeners (user_id, updated_at desc);

alter table saved_screeners enable row level security;
-- No policies: API service role only (single-user Phase 0), like screener_universe.
