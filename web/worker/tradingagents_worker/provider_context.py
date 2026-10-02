"""Same-response Yahoo context, never a per-metric period or another feed's currency."""
from datetime import datetime, timezone
import math
import re
from .yf_enrich import to_yahoo_symbol

VERSION='yfinance_info_context_v1'
SCOPE='Same-response provider info calendar and currencies; not per-metric periods or cross-provider currency attribution'
KEYS=('currency','financialCurrency','lastFiscalYearEnd','mostRecentQuarter')


def info_context(info,code,now=None):
    if not isinstance(info,dict) or not isinstance(code,str):return None
    symbol=to_yahoo_symbol(code,code.split('.',1)[0])
    if not symbol or info.get('symbol')!=symbol:return None
    now=now or datetime.now(timezone.utc)
    fields={}
    for key in KEYS:
        value=info.get(key)
        if key in ('currency','financialCurrency'):
            if isinstance(value,str) and re.fullmatch(r'[A-Z]{3}',value):fields[key]=value
        else:
            try:
                if type(value) not in (int,float) or not math.isfinite(value) or value!=int(value) or not 0<value<=now.timestamp():continue
                fields[key]={'provider_unix_seconds':int(value),'date':datetime.fromtimestamp(value,timezone.utc).date().isoformat()}
            except (OverflowError,ValueError,OSError):continue
    return {'version':VERSION,'code':code,'provider_symbol':symbol,'source':'yfinance','fields':fields,'scope':SCOPE}


def validated_context(context,code,cache_at=None,now=None):
    if not isinstance(context,dict) or context.get('code')!=code or context.get('version')!=VERSION or context.get('source')!='yfinance':return None
    fields=context.get('fields')
    if not isinstance(fields,dict) or set(fields)-set(KEYS):return None
    info={'symbol':context.get('provider_symbol')}
    for key,value in fields.items():info[key]=value.get('provider_unix_seconds') if isinstance(value,dict) else value
    expected=info_context(info,code,now)
    if expected!=context:return None
    if cache_at is not None:
        try:
            current=now or datetime.now(timezone.utc);stamp=datetime.fromisoformat(str(cache_at).replace('Z','+00:00'))
            if stamp.tzinfo is None or not 0<=(current-stamp).total_seconds()<=7*86400:return None
        except (ValueError,TypeError):return None
    return expected
