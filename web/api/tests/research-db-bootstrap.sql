-- ISOLATED TEST DATABASE ONLY. Never run against a Supabase project.
create role anon;
create role authenticated;
create role service_role bypassrls;
create schema auth;
create table auth.users(id uuid primary key);
create table auth.sessions(id uuid primary key, user_id uuid not null references auth.users, not_after timestamptz);
create function auth.uid() returns uuid language sql stable as $$
  select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid;
$$;
insert into auth.users values ('00000000-0000-4000-8000-000000000001'),('00000000-0000-4000-8000-000000000002');
insert into auth.sessions values ('00000000-0000-4000-8000-000000000004','00000000-0000-4000-8000-000000000001',null);
\ir ../../../supabase/migrations/20261002034627_private_research_lists.sql
