\set ON_ERROR_STOP on
begin;
\ir ../../../supabase/migrations/20261002131807_instrument_subtype_cache.sql
\ir ../../../supabase/migrations/20261002132749_instrument_subtype_leases.sql
set local role service_role;
do $$
declare a uuid:='10000000-0000-0000-0000-000000000001';b uuid:='10000000-0000-0000-0000-000000000002';x jsonb;y jsonb;
begin
 x:=public.instrument_subtype_claim('US',a);
 if x is null or (x->>'expires_at')::timestamptz-(x->>'started_at')::timestamptz<>interval '330 seconds' then raise exception 'lease acquisition failed';end if;
 if public.instrument_subtype_claim('US',a) is distinct from x then raise exception 'claim replay changed deadline';end if;
 if public.instrument_subtype_claim('US',b) is not null then raise exception 'active overlap acquired';end if;
 if public.instrument_subtype_release('US',b) then raise exception 'wrong token released';end if;
 if has_function_privilege('service_role','public.instrument_subtype_cache_save(text,text,integer,jsonb)','EXECUTE') then raise exception 'unfenced publication accessible';end if;
 if has_function_privilege('authenticated','public.instrument_subtype_claim(text,uuid)','EXECUTE')
  or has_table_privilege('anon','public.instrument_subtype_runs','SELECT')
  or has_table_privilege('service_role','public.instrument_subtype_runs','UPDATE') then raise exception 'overbroad lease permissions';end if;
 if not public.instrument_subtype_release('US',a) or not public.instrument_subtype_release('US',a) then raise exception 'release replay failed';end if;
 if public.instrument_subtype_claim('US',a) is not null or public.instrument_subtype_claim('HK',a) is not null then raise exception 'token reuse accepted';end if;
 if public.instrument_subtype_claim('US',b) is null then raise exception 'successor acquisition failed';end if;
end;$$;
reset role;
-- Force passage of the fixed lease clock solely inside this rollback fixture.
update public.instrument_subtype_runs set started_at=statement_timestamp()-interval '331 seconds',expires_at=statement_timestamp()-interval '1 second'
 where id='10000000-0000-0000-0000-000000000002';
set local role service_role;
do $$
declare stale uuid:='10000000-0000-0000-0000-000000000002';fresh uuid:='10000000-0000-0000-0000-000000000003';stamp text;
 c jsonb;r jsonb;n integer;
begin
 if public.instrument_subtype_claim('US',stale) is not null then raise exception 'expired replay resurrected';end if;
 if public.instrument_subtype_claim('US',fresh) is null then raise exception 'expired lease not recoverable';end if;
 stamp:=to_char((clock_timestamp()-interval '1 second') at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00';
 c:=jsonb_build_object('version','yfinance_info_context_v1','code','US.PLD','provider_symbol','PLD','source','yfinance',
 'fields',jsonb_build_object('quoteType','EQUITY'),
 'scope','Same-response provider info calendar and currencies; not per-metric periods or cross-provider currency attribution',
 'classification_scope','Same-response Yahoo quoteType; does not reinterpret another provider trust/fund category');
 r:=jsonb_build_object('version','instrument_subtype_cache_v1','code','US.PLD','context',c,'retrieved_at',stamp,'attempted_at',stamp,'status','success');
 begin
  perform public.instrument_subtype_save_leased('US',stale,'US.PLD',0,r);
  raise exception 'stale lease published';
 exception when object_not_in_prerequisite_state then null;end;
 select count(*) into n from public.instrument_subtype_save_leased('US',fresh,'US.PLD',0,r);
 if n<>1 then raise exception 'fresh lease publication failed';end if;
 select count(*) into n from public.instrument_subtype_save_leased('US',fresh,'US.PLD',0,r);
 if n<>1 or (select revision from public.instrument_subtype_cache where code='US.PLD')<>1 then raise exception 'leased receipt replay changed evidence';end if;
 if public.instrument_subtype_release('US',stale) then raise exception 'stale release affected successor';end if;
 if not public.instrument_subtype_release('US',fresh) then raise exception 'successor release failed';end if;
 begin
  perform public.instrument_subtype_save_leased('US',fresh,'US.PLD',0,r);
  raise exception 'released lease published';
 exception when object_not_in_prerequisite_state then null;end;
end;$$;
reset role;
rollback;
