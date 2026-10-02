"""Cloud snapshot provenance, without inventing currency or fiscal periods.

Moomoo cloud update_time is Unix milliseconds. This is a provider snapshot
update clock, not a last-trade timestamp, cache timestamp or SDK-local string.
"""
from datetime import datetime,timezone
import math
import re

CURRENCY_FIELDS = frozenset({'price','chg','open','high','low','high52','low52',
    'market_cap','float_cap','turnover','eps','div_ttm','target_price','op_ebt'})


def field_currency(row,field):
    """Supplied field currency with identity/value/unit checks; never infer it.

    This validates attribution for display/export, not fiscal/session or peer
    comparability. Trading currency on a company record cannot qualify EPS,
    capitalization or another provider's financial value.
    """
    if field not in CURRENCY_FIELDS:return None
    code,value=row.get('code'),row.get(field)
    observations=row.get('field_observations')
    observation=observations.get(field) if isinstance(observations,dict) else None
    if not isinstance(code,str) or not re.fullmatch(r'(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}',code):return None
    def finite(number):
        try:return type(number) in (int,float) and math.isfinite(number)
        except OverflowError:return False
    if not finite(value) or not isinstance(observation,dict):return None
    observed=observation.get('value');currency=observation.get('currency')
    if (observation.get('code')!=code or observation.get('field')!=field or observation.get('unit')!='currency'
            or not finite(observed) or observed!=value
            or not isinstance(currency,str) or not re.fullmatch(r'[A-Z]{3}',currency)):return None
    return currency


def cloud_snapshot_time(value):
    if isinstance(value,bool) or not isinstance(value,(str,int,float)):
        return None
    try:
        milliseconds=float(value)
        # Reject second-based/local/ambiguous times. Never guess a timezone.
        if not math.isfinite(milliseconds) or not 946684800000 <= milliseconds <= datetime.now(timezone.utc).timestamp()*1000+300000:
            return None
        return datetime.fromtimestamp(milliseconds/1000,timezone.utc).isoformat()
    except (ValueError,OverflowError,OSError):
        return None


def snapshot_observations(snapshot,row):
    code=row.get('code')
    stamp=cloud_snapshot_time(snapshot.get('update_time'))
    if not isinstance(code,str) or not re.fullmatch(r'(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}',code):
        return {}
    # The current cloud snapshot response omits currency. Keep it absent rather
    # than deriving it from a market prefix. Listing-currency qualification is
    # a separate provider/reference-data contract.
    units={'price':'currency','chg':'currency','open':'currency','high':'currency','low':'currency',
           'market_cap':'currency','float_cap':'currency','turnover':'currency','shares':'shares',
           'volume':'shares','pct':'percentage_points','turnover_rate':'percentage_points',
           'volume_ratio':'ratio','pe':'multiple','pe_ttm':'multiple','pb':'multiple',
           'div_yield':'percentage_points','div_ttm':'currency','eps':'currency',
           'amplitude':'percentage_points','bid_ask_ratio':'percentage_points',
           'high52':'currency','low52':'currency'}
    # Session and fiscal denominator/report periods are not supplied by the
    # quote header. Preserve data_date separately; it does not prove either.
    point_fields={'price','market_cap','float_cap','shares'}
    result={}
    for field,unit in units.items():
        value=row.get(field)
        if type(value) not in (int,float) or not math.isfinite(value):continue
        result[field]={'code':code,'field':field,'value':value,'source':'moomoo_cloud_snapshot',
            'period':'point_in_time' if field in point_fields else None,'unit':unit,'currency':None,
            'observed_at':stamp,'clock':'quote_source' if stamp else None,
            'provider_data_date':snapshot.get('data_date'),
            'timestamp_semantics':'provider_snapshot_update','last_trade_time':None}
    return result
