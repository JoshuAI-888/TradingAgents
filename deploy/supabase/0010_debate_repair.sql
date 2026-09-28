-- 0010: transcript repair — the pre-fix pipeline stored debate rows with all
-- word spacing stripped. The worker's repair pass restores spacing via the
-- digest LLM and rewrites `content`; the untouched original is kept here so
-- stored outputs are never silently rewritten (audit integrity).
alter table debate_messages add column if not exists content_original text;
