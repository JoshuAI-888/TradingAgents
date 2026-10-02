-- Add presentation state without changing existing saved criteria or preset definitions.
alter table public.saved_screeners add column if not exists settings jsonb not null default '{}'::jsonb;
-- Chart history and derived factors are maintained by the service-role API/worker.
-- These tables previously inherited public write grants. No browser client uses them.
alter table public.screener_enrichment enable row level security;
alter table public.screener_klines enable row level security;
alter table public.screener_kline_state enable row level security;
revoke all on public.screener_enrichment, public.screener_klines, public.screener_kline_state from anon, authenticated;
