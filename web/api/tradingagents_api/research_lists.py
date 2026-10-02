"""Owner-scoped durable shortlists. Separate from watchlists and saved screens."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from tradingagents_worker.db import Db
from .research_auth import ResearchOwner, require_research_owner

router = APIRouter(prefix='/api/research', tags=['Private research'])
db = Db()


def _call(method, path, **kwargs):
    try:
        return db._call(method, path, **kwargs)
    except RuntimeError as exc:
        # Never return raw PostgREST records, notes or auth details in error text.
        if '-> 409:' in str(exc):
            raise HTTPException(409, 'A shortlist with this name already exists.') from None
        raise HTTPException(503, 'Research storage is temporarily unavailable.') from None


class ListIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default='', max_length=500)

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 for c in value):
            raise ValueError('Enter a visible shortlist name without control characters')
        return value


class ListEdit(BaseModel):
    revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=500)
    active: bool | None = None

    @field_validator('name')
    @classmethod
    def clean_name(cls, value):
        return ListIn.clean_name(value) if value is not None else value

    @model_validator(mode='after')
    def actual_edit(self):
        fields = self.model_fields_set - {'revision'}
        if not fields or any(getattr(self, f) is None for f in fields):
            raise ValueError('Supply at least one non-null editable field')
        return self


class ItemIn(BaseModel):
    code: str = Field(pattern=r'^(US|HK|AU|SH|SZ|SG)\.[A-Z0-9][A-Z0-9._-]{0,30}$')


class ItemEdit(BaseModel):
    revision: int = Field(ge=1)
    note: str | None = Field(default=None, max_length=4000)
    review_status: str | None = Field(default=None, pattern=r'^(unreviewed|in_review|reviewed)$')
    active: bool | None = None

    @model_validator(mode='after')
    def actual_edit(self):
        fields = self.model_fields_set - {'revision'}
        if not fields or any(getattr(self, f) is None for f in fields):
            raise ValueError('Supply at least one non-null editable field')
        return self


def _owned_list(sid: UUID, owner: ResearchOwner, *, require_active=False):
    query = {'id': f'eq.{sid}', 'owner_id': f'eq.{owner.id}', 'select': '*'}
    if require_active:
        query['active'] = 'eq.true'
    rows = _call('GET', 'research_lists', query=query) or []
    if not rows:
        raise HTTPException(404, 'Shortlist not found.')
    return rows[0]


@router.get('/session')
def session(owner: ResearchOwner = Depends(require_research_owner)):
    return {'authenticated': True, 'owner_id': owner.id}


@router.get('/lists')
def lists(include_archived: bool = False, owner: ResearchOwner = Depends(require_research_owner)):
    query = {'owner_id': f'eq.{owner.id}', 'select': '*', 'order': 'updated_at.desc,id.asc', 'limit': '500'}
    if not include_archived:
        query['active'] = 'eq.true'
    rows = _call('GET', 'research_lists', query=query) or []
    return {'lists': rows, 'possibly_truncated': len(rows) == 500}


@router.post('/lists', status_code=201)
def create(inp: ListIn, owner: ResearchOwner = Depends(require_research_owner)):
    rows = _call('POST', 'research_lists', body={**inp.model_dump(), 'owner_id': owner.id},
                 prefer='return=representation') or []
    return {'list': rows[0]}


@router.get('/lists/{sid}')
def get_list(sid: UUID, owner: ResearchOwner = Depends(require_research_owner)):
    return {'list': _owned_list(sid, owner)}


@router.patch('/lists/{sid}')
def edit(sid: UUID, inp: ListEdit, owner: ResearchOwner = Depends(require_research_owner)):
    _owned_list(sid, owner)
    rows = _call('PATCH', 'research_lists', query={'id': f'eq.{sid}', 'owner_id': f'eq.{owner.id}',
                  'revision': f'eq.{inp.revision}'}, body={**inp.model_dump(exclude={'revision'}, exclude_unset=True),
                  'revision': inp.revision + 1, 'updated_at': datetime.now(timezone.utc).isoformat()},
                  prefer='return=representation') or []
    if not rows:
        raise HTTPException(409, 'This shortlist changed. Reload before saving.')
    return {'list': rows[0]}


@router.get('/lists/{sid}/items')
def items(sid: UUID, offset: int = Query(default=0, ge=0, le=40000),
          limit: int = Query(default=100, ge=1, le=500), include_removed: bool = False,
          q: str = Query(default='', max_length=34, pattern=r'^[A-Za-z0-9._-]*$'),
          review_status: Literal['all', 'unreviewed', 'in_review', 'reviewed'] = 'all',
          after_code: str = '',
          owner: ResearchOwner = Depends(require_research_owner)):
    shortlist = _owned_list(sid, owner)
    query = {'list_id': f'eq.{sid}', 'owner_id': f'eq.{owner.id}', 'select': '*',
             'order': 'code.asc', 'limit': str(limit + 1), 'offset': str(offset)}
    if not include_removed:
        query['active'] = 'eq.true'
    if review_status != 'all':
        query['review_status'] = f'eq.{review_status}'
    if q:
        # Restricted alphabet prevents wildcard/operator injection. This searches
        # canonical ticker identities, not incomplete company-name quote caches.
        literal = q.upper().replace('_', r'\_')
        query['code'] = f'ilike.*{literal}*'
    if after_code:
        try:
            ItemIn(code=after_code)
        except ValidationError:
            raise HTTPException(422, 'Invalid canonical instrument code.') from None
        # PostgREST AND supports a second predicate on code alongside ticker search.
        query['and'] = f'(code.gt.{after_code})'
    rows = _call('GET', 'research_list_items', query=query) or []
    has_more = len(rows) > limit
    rows = _with_quotes(rows[:limit])
    return {'list': shortlist, 'items': rows, 'has_more': has_more,
            'offset': offset, 'limit': limit, 'q': q, 'review_status': review_status}


def _with_quotes(rows):
    if not rows:
        return rows
    codes = ','.join(r['code'] for r in rows)
    # Database code constraints and path validation make the in-list canonical.
    quotes = _call('GET', 'screener_quotes', query={'code': f'in.({codes})',
                   'select': 'code,row,updated_at', 'limit': str(len(rows))}) or []
    lookup = {r['code']: r for r in quotes if isinstance(r.get('row'),dict) and r['row'].get('code')==r['code']}
    return [{**r, 'quote': lookup.get(r['code'], {}).get('row'),
             'quote_cache_at': lookup.get(r['code'], {}).get('updated_at')} for r in rows]


@router.get('/lists/{sid}/items/{code}')
def item(sid: UUID, code: str, owner: ResearchOwner = Depends(require_research_owner)):
    try:
        ItemIn(code=code)
    except ValidationError:
        raise HTTPException(422, 'Invalid canonical instrument code.') from None
    _owned_list(sid, owner)
    rows = _call('GET', 'research_list_items', query={'list_id': f'eq.{sid}',
                'owner_id': f'eq.{owner.id}', 'code': f'eq.{code}', 'select': '*'}) or []
    if not rows:
        raise HTTPException(404, 'Stock review not found.')
    return {'item': _with_quotes(rows)[0]}


@router.post('/lists/{sid}/items')
def add(sid: UUID, inp: ItemIn, owner: ResearchOwner = Depends(require_research_owner)):
    _owned_list(sid, owner, require_active=True)
    # Validate canonical identity against our enumeration, not an ambiguous symbol label.
    known = _call('GET', 'screener_universe', query={'code': f'eq.{inp.code}', 'select': 'code', 'limit': '1'})
    if not known:
        raise HTTPException(422, 'This instrument is absent from the stored universe. Refresh coverage before adding it.')
    rows = _call('POST', 'rpc/research_list_add', body={'p_list': str(sid), 'p_owner': owner.id,
                                                    'p_code': inp.code}) or []
    if not rows:
        raise HTTPException(409, 'This shortlist was archived. Reload before adding.')
    return {'item': rows[0]}


@router.patch('/lists/{sid}/items/{code}')
def edit_item(sid: UUID, code: str, inp: ItemEdit, owner: ResearchOwner = Depends(require_research_owner)):
    try:
        ItemIn(code=code)  # Reject PostgREST operator/filter injection even for path IDs.
    except ValidationError:
        raise HTTPException(422, 'Invalid canonical instrument code.') from None
    _owned_list(sid, owner, require_active=True)
    rows = _call('POST', 'rpc/research_list_review', body={
        'p_list': str(sid), 'p_owner': owner.id, 'p_code': code, 'p_revision': inp.revision,
        'p_note': inp.note, 'p_status': inp.review_status, 'p_active': inp.active}) or []
    if not rows:
        raise HTTPException(409, 'This stock review changed or is unavailable. Reload before saving.')
    return {'item': rows[0]}
