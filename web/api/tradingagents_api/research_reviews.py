"""Private notes tied to validated immutable capture pairs, never company-wide status."""
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,Field,ConfigDict
from tradingagents_worker.db import Db
from .research_auth import ResearchOwner,require_research_owner
router=APIRouter(prefix='/api/research/pair-reviews',tags=['Private research'])
db=Db()

class PairIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    definition:dict
    previous_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')
    current_id:str=Field(pattern=r'^[A-Za-z0-9_-]{1,100}$')

class ReviewIn(PairIn):
    code:str=Field(pattern=r'^(US|HK|AU|SH|SZ|SG)\.[A-Z0-9][A-Z0-9._-]{0,30}$')
    revision:int=Field(ge=0)
    note:str=Field(max_length=4000)
    review_status:Literal['unreviewed','in_review','reviewed']

def _call(method,path,**kwargs):
    try:return db._call(method,path,**kwargs) or []
    except (RuntimeError,OSError):raise HTTPException(503,'Pair review storage is temporarily unavailable. Your draft has not been saved.') from None

def _lookup(owner):
    def read(key,previous,current):
        payload=_call('POST','rpc/research_pair_review_read',body={'p_owner':owner.id,'p_key':key,
            'p_previous':previous,'p_current':current})
        rows=payload.get('reviews') if isinstance(payload,dict) else None
        if not isinstance(rows,list):
            raise HTTPException(503,'Pair review state was not confirmed; no partial review returned.')
        if len(rows)>40000:
            raise HTTPException(409,'Review state exceeds supported scope; no partial review returned.')
        return {row['code']:row for row in rows}
    return read

def _pair(definition,previous,current,**kwargs):
    from .main import _screen_changes
    import json
    result=_screen_changes(json.dumps(definition),previous,current,**kwargs)
    if not result['comparable']:raise HTTPException(409,'This pair is not comparable; no review state applied.')
    return result

@router.get('')
def reviews(definition:str,previous_id:str,current_id:str,status:str='all',q:str='',sort:str='symbol',direction:int=1,
            review_status:Literal['all','unreviewed','in_review','reviewed']='all',limit:int=100,offset:int=0,
            owner:ResearchOwner=Depends(require_research_owner)):
    import json
    try:pair=PairIn(definition=json.loads(definition),previous_id=previous_id,current_id=current_id)
    except ValueError:raise HTTPException(422,'Invalid capture pair.') from None
    result=_pair(pair.definition,pair.previous_id,pair.current_id,status=status,q=q,sort=sort,direction=direction,
                 limit=limit,offset=offset,review_lookup=_lookup(owner),review_status=review_status)
    return {**result,'review_scope':'private_capture_pair','owner_id':owner.id,'review_filter':review_status}

@router.patch('')
def save(inp:ReviewIn,owner:ResearchOwner=Depends(require_research_owner)):
    from .main import ScreenDefinition,_snapshot_key
    pair=_pair(inp.definition,inp.previous_id,inp.current_id,review_code=inp.code,limit=1)
    if not pair['rows']:raise HTTPException(404,'Instrument is absent from this comparison pair.')
    key=_snapshot_key(ScreenDefinition.model_validate(inp.definition))
    rows=_call('POST','rpc/research_pair_review_save',body={'p_owner':owner.id,'p_key':key,'p_previous':inp.previous_id,
        'p_current':inp.current_id,'p_code':inp.code,'p_revision':inp.revision,'p_note':inp.note,'p_status':inp.review_status})
    if not rows:raise HTTPException(409,'This pair review changed or is unavailable. Keep your draft and reload before saving.')
    return {'review':rows[0],'review_scope':'private_capture_pair'}
