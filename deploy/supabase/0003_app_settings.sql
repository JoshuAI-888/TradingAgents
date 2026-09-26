-- 0003: pre-auth single-user settings storage (service-role only).
-- When portal auth lands, model prefs move to user_settings (FK-bound, RLS).
create table if not exists app_settings (
  key        text primary key,
  value      jsonb not null,
  updated_at timestamptz not null default now()
);
alter table app_settings enable row level security;
-- No policies: only the worker/API service role reads or writes this table.
