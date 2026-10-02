-- ISOLATED TEST DATABASE ONLY: minimal existing production table contracts.
-- Roles anon/authenticated/service_role must already exist in the test cluster.
create table public.app_settings(key text primary key,value jsonb not null,updated_at timestamptz not null default now());
create table public.screener_universe(market text not null,code text not null,name text,plate text,
  plates jsonb not null default '[]',stock_type text,exchange text,updated_at timestamptz not null default now(),
  primary key(market,code));
create table public.screener_quotes(code text primary key,market text not null,row jsonb not null,
  updated_at timestamptz not null default now());
alter table public.app_settings enable row level security;
alter table public.screener_universe enable row level security;
alter table public.screener_quotes enable row level security;
revoke all on public.app_settings,public.screener_universe,public.screener_quotes from public,anon,authenticated;
grant select,insert,update on public.app_settings,public.screener_universe,public.screener_quotes to service_role;
\ir ../../../supabase/migrations/20261002060206_screener_generation_publication.sql
