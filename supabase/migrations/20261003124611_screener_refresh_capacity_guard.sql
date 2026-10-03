-- Admission guard, not retention or a hard quota: an admitted in-flight refresh
-- can grow these relations beyond the threshold before the next preflight.
-- Includes indexes and TOAST. Never deletes historical or staged evidence.
begin;
create or replace function public.screener_refresh_capacity(p_market text)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  relation_bytes jsonb;
  used_bytes bigint;
  limit_bytes constant bigint := 524288000; -- 500 MiB, fixed server-side
begin
  if p_market is null or p_market not in ('US','HK') then
    raise exception 'Invalid screener capacity market' using errcode = '22023';
  end if;
  relation_bytes := pg_catalog.jsonb_build_object(
    'generation_rows',pg_catalog.pg_total_relation_size('public.screener_generation_rows'::pg_catalog.regclass),
    'staged_rows',pg_catalog.pg_total_relation_size('public.screener_refresh_staged_rows'::pg_catalog.regclass),
    'generations',pg_catalog.pg_total_relation_size('public.screener_generations'::pg_catalog.regclass));
  used_bytes := (relation_bytes->>'generation_rows')::bigint
    + (relation_bytes->>'staged_rows')::bigint + (relation_bytes->>'generations')::bigint;
  if used_bytes is null or used_bytes < 0 then
    raise exception 'Invalid screener capacity measurement' using errcode = '55000';
  end if;
  return pg_catalog.jsonb_build_object('version','screener_capacity_v1','market',p_market,
    'used_bytes',used_bytes,'limit_bytes',limit_bytes,'relation_bytes',relation_bytes,
    'allowed',used_bytes < limit_bytes);
end;
$$;
revoke all on function public.screener_refresh_capacity(text) from public,anon,authenticated;
grant execute on function public.screener_refresh_capacity(text) to service_role;
commit;
