-- Staged JSON is TOAST-compressed. Account for stored copies and index/update
-- overhead while retaining at least one complete uncompressed payload budget.
-- Live US input: 98.3 MB JSON / 19.4 MB stored; the previous 3x JSON estimate
-- rejected publication even at 235 MB database size.
begin;
do $patch$
declare definition text; old_check text;
begin
  definition := pg_get_functiondef('public.screener_refresh_publish_staged(text,uuid,jsonb,jsonb,boolean)'::regprocedure);
  old_check := 'coalesce((select sum(pg_catalog.octet_length(payload::text))::bigint*3 from public.screener_refresh_staged_rows where run_id=p_run),0)+16777216';
  if position(old_check in definition)=0 then
    raise exception 'Unknown staged publication projection layout';
  end if;
  definition := replace(definition,old_check,
    'coalesce((select greatest(sum(pg_catalog.octet_length(payload::text))::bigint,sum(pg_catalog.pg_column_size(payload))::bigint*6) from public.screener_refresh_staged_rows where run_id=p_run),0)+16777216');
  execute definition;
end; $patch$;
commit;
