"""ISOLATED LOCAL DATABASE ONLY: v3 JSON evidence survives immutable storage.

No production connection options are accepted. Fixtures roll back in one
transaction and do not disable immutability. This tests storage fidelity, not
live market coverage or provider provenance.
Run with PYTHONPATH=web/api python web/api/tests/observation-db-contract.py.
"""
import json
import subprocess
from datetime import datetime,timezone,timedelta

from tradingagents_api.screen_observations import capture_observation,validate_observation_capture

PSQL=['/opt/homebrew/opt/postgresql@16/bin/psql','-h','/private/tmp/tradingagent-research-pg',
      '-p','55439','-d','postgres','-v','ON_ERROR_STOP=1','-qAt']
definition={'market':'US','src':'moo','etfs':False,'watchlist_only':False,'preset':None,
            'filters':[{'field':'price','max':5},{'field':'volume','days':30,'min':0},
                       {'field':'volume','days':60,'min':0}]}
records=[]
for side,days,values in [('before',1,[6,3]),('after',0,[4,7])]:
    captured=datetime.now(timezone.utc)-timedelta(days=days)
    observations=[]
    for code,price in zip(['US.BRK.B','US.A'],values):
        row={'code':code,'symbol':code[3:],'stock_type':'STOCK','price':price,
             'quote_cache_at':captured.isoformat(),'field_evidence':{}}
        for i,(criterion,value) in enumerate(zip(definition['filters'],[price,30,60])):
            row['field_evidence'][f'c{i}']={'criterion':criterion,'value':value,'source':'synthetic_fixture',
                'period':'point_in_time' if i==0 else f'{criterion["days"]}-day average',
                'unit':'currency' if i==0 else 'shares','currency':'USD' if i==0 else None,
                'clock':'quote_source' if i==0 else 'computed_bar_time',
                'observed_at':(captured-timedelta(minutes=1)).isoformat()}
        observations.append(capture_observation(row,definition['filters']))
    snapshot={'id':'native-observations-'+side,'version':3,'at':captured.isoformat(),
              'complete':True,'definition':definition,'source_clock':'stored_universe',
              'source_at':captured.isoformat(),'observation_scope':'eligible_stored_universe',
              'eligible_count':2,'observations':observations,
              'members':[r for r in observations if r['evidence']['price']<=5]}
    validate_observation_capture(snapshot,definition)
    records.append({'id':snapshot['id'],'snapshot':snapshot})
payload=json.dumps(records,allow_nan=False)
# Fixed fixture data; dollar delimiters never contain untrusted text.
assert '$observation$' not in payload
key='screen_history:'+'e'*16+':'+'f'*64
query=f"""begin;
set local role service_role;
do $test$ declare records jsonb := $observation${payload}$observation$::jsonb; r jsonb;
begin
 assert public.screen_capture_append('{key}',records)=2;
 assert public.screen_capture_append('{key}',records)=0;
 for r in select value from jsonb_array_elements(records) loop
  assert (select snapshot from public.screen_captures where history_key='{key}' and id=r->>'id')=r->'snapshot';
  assert (select version=3 and members=1 from public.screen_captures where history_key='{key}' and id=r->>'id');
 end loop;
end $test$;
rollback;
"""
subprocess.run(PSQL,input=query,text=True,check=True)
print('v3 observation storage passed: nonmembers, share class, independent windows and typed provenance round-trip unchanged; exact replay idempotent; fixtures rolled back')
