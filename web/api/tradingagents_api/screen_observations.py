"""Immutable criterion identities and conservative paired-observation assessment."""
from __future__ import annotations

import math
import re
from tradingagents_worker.screener_generations import canonical_generation
from datetime import datetime


def criterion_slots(filters):
    return [(f'c{i}', c) for i, c in enumerate(filters)]


def numeric(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def capture_observation(row, filters):
    supplied = row.get('field_evidence') if isinstance(row.get('field_evidence'),dict) else {}
    produced = row.get('field_observations') if isinstance(row.get('field_observations'),dict) else {}
    observations = {}
    counts = {c.get('field'): sum(other.get('field') == c.get('field') for other in filters) for c in filters}
    for key, criterion in criterion_slots(filters):
        field = criterion.get('field')
        # A period-specific record wins. Never reuse a flat value for ambiguous windows.
        contract = supplied.get(key) or (supplied.get(field) if counts[field] == 1 else None) or {}
        contract = contract if isinstance(contract,dict) and contract.get('criterion') == criterion else {}
        contextual = any(k in criterion for k in ('days','period','term','plate_ids'))
        if not contract and not contextual and isinstance(produced.get(field),dict):
            actual = produced[field]
            if actual.get('code') != row['code'] or actual.get('field') != field or actual.get('value') != row.get(field):
                raise ValueError('Produced observation identity or value conflicts with stored row')
            contract = {**actual,'criterion':criterion}
        value = contract.get('value') if contract else (
            row.get(field) if counts[field] == 1 and not any(k in criterion for k in ('days','period','term','plate_ids')) else None)
        if isinstance(value, float) and not math.isfinite(value):
            value = None
        if contract and not any(k in criterion for k in ('days','period','term','plate_ids')) and field in row and row[field] != value:
            raise ValueError('Conflicting stored field and observation values')
        observations[key] = {'criterion': criterion, 'value': value,
            **{k: contract.get(k) for k in ('source', 'period', 'unit', 'currency', 'observed_at', 'clock',
                                           'provider_data_date','timestamp_semantics','last_trade_time')},
            'cache_at': row.get('quote_cache_at')}
    return {'code': row['code'], 'symbol': row.get('symbol'), 'name': row.get('name'),
            'instrument_type': row.get('stock_type'), 'quote_cache_at': row.get('quote_cache_at'),
            **({'generation_id': row['generation_id']} if row.get('generation_id') else {}),
            'metrics': {k: row.get(k) for k in ('price', 'pct', 'market_cap', 'pe_ttm')},
            'evidence': {c.get('field'): observations[key]['value'] for key, c in criterion_slots(filters)
                         if counts[c.get('field')] == 1}, 'criterion_observations': observations}


def validate_observation_capture(snapshot, definition):
    """Validate persisted v3 evidence before trusting membership or reading values.

    Immutability does not establish correctness. Reject malformed or mismatched
    payloads rather than silently repairing their meaning during comparison.
    """
    records = snapshot.get('observations')
    if (snapshot.get('definition') != definition or snapshot.get('observation_scope') != 'eligible_stored_universe'
            or not isinstance(records,list) or type(snapshot.get('eligible_count')) is not int
            or snapshot['eligible_count'] != len(records)):
        raise ValueError('Observation scope, count or definition is inconsistent')
    captured = datetime.fromisoformat(str(snapshot.get('at')).replace('Z','+00:00'))
    if captured.tzinfo is None:
        raise ValueError('Capture timezone missing')
    generation = snapshot.get('source_generation_id')
    if snapshot.get('source_clock') == 'generation_publication' and 'source_generation_id' not in snapshot:
        raise ValueError('Generation identity missing from publication capture')
    if 'source_generation_id' in snapshot:
        canonical_generation(generation)
        if snapshot.get('source_clock') != 'generation_publication':
            raise ValueError('Generation publication clock missing')
    slots = dict(criterion_slots(definition['filters']))
    unique_fields = {c['field'] for c in slots.values() if sum(other['field']==c['field'] for other in slots.values())==1}
    lookup = {}
    for record in records:
        if not isinstance(record,dict):
            raise ValueError('Invalid observation record')
        code = record.get('code')
        if record.get('generation_id') != generation:
            raise ValueError('Observation generation differs from its capture')
        if (not isinstance(code,str) or not re.fullmatch(r'(US|HK)\.[A-Z0-9][A-Z0-9._-]{0,30}',code)
                or not code.startswith(definition['market']+'.') or code in lookup):
            raise ValueError('Invalid or duplicated observation identity')
        if record.get('instrument_type') not in (('STOCK','ETF') if definition['etfs'] else ('STOCK',)):
            raise ValueError('Invalid eligible instrument classification')
        cache = datetime.fromisoformat(str(record.get('quote_cache_at')).replace('Z','+00:00'))
        if cache.tzinfo is None or not -300 <= (captured-cache).total_seconds() <= 86400:
            raise ValueError('Invalid eligible quote cache timestamp')
        observations = record.get('criterion_observations')
        if not isinstance(observations,dict) or observations.keys() != slots.keys():
            raise ValueError('Criterion slots are incomplete or inconsistent')
        evidence = record.get('evidence')
        if not isinstance(evidence,dict) or evidence.keys() != unique_fields or not isinstance(record.get('metrics'),dict):
            raise ValueError('Observation values are inconsistent')
        for key, criterion in slots.items():
            observation = observations[key]
            if not isinstance(observation,dict) or observation.get('criterion') != criterion or observation.get('cache_at') != record['quote_cache_at']:
                raise ValueError('Criterion identity or cache timestamp is inconsistent')
            value = observation.get('value')
            if criterion.get('currency') is not None and (not isinstance(criterion['currency'],str) or not re.fullmatch(r'[A-Z]{3}',criterion['currency']) or observation.get('unit')!='currency' or not isinstance(observation.get('currency'),str) or not re.fullmatch(r'[A-Z]{3}',observation['currency'])):
                raise ValueError('Criterion currency observation is incomplete or invalid')
            if criterion.get('values') is not None:
                valid = isinstance(value,(str,list)) and (not isinstance(value,list) or all(isinstance(v,str) for v in value))
            else:
                valid = numeric(value) or (type(value) is bool and all(bound in (None,0,1) for bound in (criterion.get('min'),criterion.get('max'))))
            if not valid or (criterion['field'] in unique_fields and evidence[criterion['field']] != value):
                raise ValueError('Criterion value is missing, nonfinite or inconsistent')
        lookup[code] = record
    return lookup


def rule_pass(value, criterion):
    if not numeric(value) or criterion.get('values') is not None:
        return None
    lo, hi = criterion.get('min'), criterion.get('max')
    if any(bound is not None and not numeric(bound) for bound in (lo,hi)) or (lo is None and hi is None):
        return None
    if lo is not None and (value < lo or (criterion.get('excl_min') and value == lo)):
        return False
    if hi is not None and (value > hi or (criterion.get('excl_max') and value == hi)):
        return False
    return True


def paired_evidence(before, after, filters, capture_times=None):
    result = []
    for key, criterion in criterion_slots(filters):
        a = (before or {}).get('criterion_observations', {}).get(key) or {}
        b = (after or {}).get('criterion_observations', {}).get(key) or {}
        prior, current = a.get('value'), b.get('value')
        reason = 'Missing observation on one side'
        comparable = numeric(prior) and numeric(current)
        if comparable:
            required = ('source', 'period', 'unit', 'clock')
            comparable = all(isinstance(a.get(k),str) and a.get(k) and a.get(k) == b.get(k) for k in required)
            comparable = comparable and a.get('criterion') == criterion == b.get('criterion')
            comparable = comparable and a.get('currency') == b.get('currency')
            comparable = comparable and a.get('clock') in ('quote_source','computed_bar_time','financial_report')
            comparable = comparable and a.get('unit') in ('ratio','multiple','percentage_points','currency','shares','count')
            if a.get('unit') == 'currency' and not a.get('currency'):
                comparable = False
            reason = 'Period, unit, currency or source contract is missing or incompatible'
            if comparable:
                try:
                    times = [datetime.fromisoformat(str(o.get('observed_at')).replace('Z', '+00:00')) for o in (a,b)]
                    comparable = all(t.tzinfo is not None for t in times) and times[0] < times[1]
                    comparable = comparable and capture_times is not None and len(capture_times)==2 and all(0 <= (captured-t).total_seconds() <= (7*86400 if a['clock']=='financial_report' else 86400) for captured,t in zip(capture_times,times))
                except (KeyError, TypeError, ValueError):
                    comparable = False
                reason = 'Observation timestamps are missing, invalid or not advancing'
        assessment = None
        if comparable:
            old, new = rule_pass(prior, criterion), rule_pass(current, criterion)
            if old is None or new is None:
                comparable = False
            else:
                assessment = 'rule_entered' if old is False and new is True else 'rule_exited' if old is True and new is False else 'rule_retained'
            reason = ('Comparable captured observations; rule result is not a causal attribution' if comparable else
                      'The criterion has no assessable numeric rule')
        result.append({'criterion_key': key, 'field': criterion.get('field'), 'criterion': criterion,
                       'previous': prior, 'current': current, 'previous_observation': a, 'current_observation': b,
                       'period': a.get('period') if a.get('period') == b.get('period') else 'Incompatible / unavailable periods',
                       'source': a.get('source') if a.get('source') == b.get('source') else 'Incompatible / unavailable sources',
                       'status': 'comparable' if comparable else 'unavailable_pair', 'assessment': assessment, 'explanation': reason})
    return result
