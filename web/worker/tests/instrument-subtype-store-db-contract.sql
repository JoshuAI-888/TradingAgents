\set ON_ERROR_STOP on
begin;
\ir ../../../supabase/migrations/20261002131807_instrument_subtype_cache.sql
set local role service_role;
do $$
declare a text:=to_char((clock_timestamp()-interval '20 seconds') at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00';
 b text:=to_char((clock_timestamp()-interval '10 seconds') at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00';
 c jsonb; r jsonb; f jsonb; n integer;
begin
 c:=jsonb_build_object('version','yfinance_info_context_v1','code','US.PLD','provider_symbol','PLD','source','yfinance',
 'fields',jsonb_build_object('quoteType','EQUITY'),
 'scope','Same-response provider info calendar and currencies; not per-metric periods or cross-provider currency attribution',
 'classification_scope','Same-response Yahoo quoteType; does not reinterpret another provider trust/fund category');
 r:=jsonb_build_object('version','instrument_subtype_cache_v1','code','US.PLD','context',c,'retrieved_at',a,'attempted_at',a,'status','success');
 select count(*) into n from public.instrument_subtype_cache_save('US','US.PLD',0,r);
 if n<>1 then raise exception 'initial publication failed';end if;
 select count(*) into n from public.instrument_subtype_cache_save('US','US.PLD',0,r);
 if n<>1 or (select revision from public.instrument_subtype_cache where code='US.PLD')<>1 then raise exception 'exact replay failed';end if;
 f:=r||jsonb_build_object('attempted_at',b,'status','unavailable');
 select count(*) into n from public.instrument_subtype_cache_save('US','US.PLD',1,f);
 if n<>1 or (select record->>'retrieved_at' from public.instrument_subtype_cache where code='US.PLD')<>a then raise exception 'failed retrieval lost original evidence';end if;
 select count(*) into n from public.instrument_subtype_cache_save('US','US.PLD',1,f);
 if n<>1 then raise exception 'update replay failed';end if;
 select count(*) into n from public.instrument_subtype_cache_save('US','US.PLD',1,r);
 if n<>0 then raise exception 'stale revision replaced newer evidence';end if;
 begin
  perform public.instrument_subtype_cache_save('US','US.PLD',2,r);
  raise exception 'older clock accepted';
 exception when invalid_parameter_value then null;end;
 begin
  perform public.instrument_subtype_cache_save('US','US.BAD',0,r||jsonb_build_object('code','US.BAD'));
  raise exception 'wrong provider symbol accepted';
 exception when invalid_parameter_value then null;end;
 if has_table_privilege('anon','public.instrument_subtype_cache','SELECT')
  or has_table_privilege('authenticated','public.instrument_subtype_cache','UPDATE')
  or has_function_privilege('authenticated','public.instrument_subtype_cache_save(text,text,integer,jsonb)','EXECUTE')
  or has_table_privilege('service_role','public.instrument_subtype_cache','DELETE') then raise exception 'overbroad grant';end if;
 if not (select relrowsecurity from pg_class where oid='public.instrument_subtype_cache'::regclass) then raise exception 'RLS disabled';end if;
end;$$;
reset role;
rollback;
