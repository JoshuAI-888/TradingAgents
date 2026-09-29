-- 0012: full plate membership per code (Phase B taxonomy filters). The loader
-- previously kept only the FIRST plate that enumerated a code, so concepts
-- boards were unreachable as filters. `plates` lists every plate name that
-- contains the code, primary industry first.
alter table screener_universe add column if not exists plates jsonb not null default '[]'::jsonb;
