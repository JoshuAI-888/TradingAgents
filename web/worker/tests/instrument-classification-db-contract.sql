\set ON_ERROR_STOP on
begin;
set local role service_role;
do $$
declare token uuid:=gen_random_uuid();stamp text;classification jsonb;payload jsonb;receipt jsonb;
begin
 perform public.screener_refresh_begin('HK',token);
 stamp:=to_char(clock_timestamp() at time zone 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00';
 classification:=jsonb_build_object('version','instrument_classification_v1','code','HK.00700','provider_type','ETF','provider_at',stamp,
  'provider_source','moomoo_basicinfo','provider_clock','retrieval','stock_type','STOCK','reason','qualified_trust_fund_subtype',
  'subtype_context',jsonb_build_object('version','yfinance_info_context_v1','code','HK.00700','provider_symbol','0700.HK','source','yfinance',
   'fields',jsonb_build_object('quoteType','EQUITY'),'scope','Same-response provider info calendar and currencies; not per-metric periods or cross-provider currency attribution',
   'classification_scope','Same-response Yahoo quoteType; does not reinterpret another provider trust/fund category'),'subtype_at',stamp);
 payload:=jsonb_build_array(jsonb_build_object('code','HK.00700','quote_cache_at',replace(stamp,' ','T'),
  'row',jsonb_build_object('code','HK.00700','stock_type','STOCK','instrument_classification',classification),
  'metadata',jsonb_build_object('code','HK.00700','market','HK','stock_type','STOCK','plates','[]'::jsonb,'provider_stock_type','ETF','provider_classified_at',stamp,'instrument_classification',classification)));
 receipt:=public.screener_refresh_publish('HK',token,'["HK.00700"]'::jsonb,payload,'{}'::jsonb,false);
 assert receipt->>'row_count'='1';
 assert (select metadata->'instrument_classification' from public.screener_generation_rows where generation_id=token)=classification;
 assert (select row->'instrument_classification' from public.screener_generation_rows where generation_id=token)=classification;
 assert (select stock_type from public.screener_universe where market='HK' and code='HK.00700')='STOCK';
 begin
  update public.screener_generation_rows set row=jsonb_set(row,'{stock_type}','"ETF"') where generation_id=token;
  raise exception 'immutable classification was editable';
 exception when insufficient_privilege or sqlstate '55000' then null;
 end;
end $$;
reset role;
rollback;
