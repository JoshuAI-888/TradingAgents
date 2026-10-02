"""ISOLATED LOCAL DATABASE ONLY: prove archive and membership are serialized.
Run after research-db-bootstrap.sql. Uses the dedicated test Unix socket only.
"""
import subprocess
import time

PSQL=['/opt/homebrew/opt/postgresql@16/bin/psql','-h','/private/tmp/tradingagent-research-pg','-p','55439','-d','postgres','-v','ON_ERROR_STOP=1','-qAt']
OWNER='00000000-0000-4000-8000-000000000001'
LIST='00000000-0000-4000-8000-000000000003'
def sql(query):return subprocess.check_output(PSQL+['-c',query],text=True).strip()
sql(f"insert into public.research_lists(id,owner_id,name) values ('{LIST}','{OWNER}','Concurrency fixture'); select public.research_list_add('{LIST}','{OWNER}','US.BRK.B');")
archive=add=None
try:
    archive=subprocess.Popen(PSQL+['-c',f"set application_name='research-archive-contract'; begin; update public.research_lists set active=false where id='{LIST}'; select 'locked'; select pg_sleep(3); commit;"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    locked=False
    for _ in range(30):
        if sql("select count(*) from pg_stat_activity where application_name='research-archive-contract' and wait_event='PgSleep'")=='1':locked=True;break
        time.sleep(.05)
    assert locked,'Archive transaction did not reach its held-lock state' 
    add=subprocess.Popen(PSQL+['-c',f"set application_name='research-add-contract'; set role service_role; select count(*) from public.research_list_add('{LIST}','{OWNER}','US.MSFT');"],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    waited=False
    for _ in range(30):
        if sql("select count(*) from pg_stat_activity where application_name='research-add-contract' and wait_event_type='Lock'")=='1':waited=True;break
        time.sleep(.05)
    assert waited,'Concurrent add did not wait on archive lock'
    out,err=add.communicate(timeout=10);assert add.returncode==0,err;assert out.strip()=='0',out
    _,err=archive.communicate(timeout=10);assert archive.returncode==0,err
    assert sql(f"select count(*) from public.research_list_items where list_id='{LIST}' and code='US.MSFT'")=='0'
    print('archive/add concurrency contract passed: blocked on parent lock, no post-archive member inserted')
finally:
    for process in (add,archive):
        if process and process.poll() is None:process.terminate();process.wait(timeout=5)
    sql(f"delete from public.research_list_items where list_id='{LIST}'; delete from public.research_lists where id='{LIST}';")
