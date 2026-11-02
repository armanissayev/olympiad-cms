"""Disable connections only to the two newly provisioned staging databases."""
import json,subprocess,time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4
import requests
root=Path('/var/lib/cms-ide-stage/fixture');m=json.loads((root/'browser.json').read_text());assert m['kind']=='disposable-linux-staging'
c=requests.Session();c.trust_env=False;c.verify=m['certificate'];base=m['baseUrl'];c.get(base+'/',timeout=10);assert c.post(base+'/login',data={'username':m['username'],'password':m['password'],'_xsrf':c.cookies.get('_xsrf')},timeout=10,allow_redirects=False).status_code==302
ctx=c.get(base+'/ide/api/context',timeout=10).json();task=next(t for t in ctx['tasks'] if t['name']=='cppsum');h={'X-Olympiad-Principal':ctx['identity']['principalId'],'X-XSRFToken':ctx['csrfToken'],'X-Olympiad-Task':str(task['id'])}
report={'kind':'linux-staging-database-faults','checks':[]}
def sql(command):
 subprocess.run(['runuser','-u','stagepguser','--','/usr/lib/postgresql/18/bin/psql','-X','-v','ON_ERROR_STOP=1','-h','/run/cms-ide-stage-pg','-p','15432','postgres','-c',command],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
@contextmanager
def unavailable(database):
 assert database in ('cmside_linux_fortesting','ide_linux_staging')
 sql(f'ALTER DATABASE {database} ALLOW_CONNECTIONS false')
 try:
  sql("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='"+database+"' AND pid<>pg_backend_pid()")
  yield
 finally:sql(f'ALTER DATABASE {database} ALLOW_CONNECTIONS true')
def get(path):return c.get(base+path,headers=h,timeout=10)
def wait(fn,seconds=40):
 end=time.monotonic()+seconds
 while time.monotonic()<end:
  try:
   if fn():return
  except requests.RequestException:pass
  time.sleep(.3)
 raise AssertionError('Database recovery timed out')
def intent():return {'schemaVersion':1,'intentId':str(uuid4()),'taskId':task['id'],'language':'Python 3 / CPython','workspaceId':str(uuid4()),'snapshotId':str(uuid4()),'telemetry':None,'files':[{'filename':'main.%l','sourceFilename':'main.py','fileId':str(uuid4()),'content':'a,b=map(int,input().split())\nprint(a+b)\n'}]}
def post(body):return c.post(base+'/ide/api/submissions',headers=h,json=body,timeout=15)
body=intent()
with unavailable('cmside_linux_fortesting'):
 live=get('/ide/health/live');ready=get('/ide/health/ready');context=get('/ide/api/context');admission=post(body)
 assert live.status_code==200 and ready.status_code==503 and context.status_code in (500,503) and admission.status_code in (500,503)
 report['cmsDown']={'live':live.status_code,'ready':ready.status_code,'context':context.status_code,'official':admission.status_code}
wait(lambda:get('/ide/health/ready').status_code==200)
wait(lambda:get('/ide/api/context').status_code==200)
assert get('/ide/api/submissions/'+body['intentId']).status_code==404
r=post(body);assert r.status_code==201;r0=r.json();assert post(body).status_code==200
wait(lambda:get('/ide/api/submissions/status/'+r0['submissionId']+'?taskId='+str(task['id'])).json().get('status',{}).get('status')==5,150)
report['checks'].append('CMS DB outage fails closed; unadmitted intent404 then deliberate exact retry201/200 and real judging recovery')
workspace=get('/ide/api/runtime/v1/workspaces').json()[0];before=json.dumps(workspace,sort_keys=True)
with unavailable('ide_linux_staging'):
 private=requests.get('http://127.0.0.1:18801/health/ready',timeout=10);gateway=get('/ide/api/runtime/v1/workspaces');context=get('/ide/api/context');fallback=get('/')
 assert private.status_code==503 and gateway.status_code==503 and context.status_code==200 and fallback.status_code==200
 r=post(intent());assert r.status_code==201;r1=r.json()
 report['ideDown']={'runtimeReady':private.status_code,'gateway':gateway.status_code,'context':context.status_code,'cws':fallback.status_code,'official':r.status_code}
wait(lambda:get('/ide/api/runtime/v1/workspaces/'+workspace['id']).status_code==200)
assert json.dumps(get('/ide/api/runtime/v1/workspaces/'+workspace['id']).json(),sort_keys=True)==before
wait(lambda:get('/ide/api/submissions/status/'+r1['submissionId']+'?taskId='+str(task['id'])).json().get('status',{}).get('status')==5,120)
wait(lambda:get('/').status_code==200)
report['checks'].append('IDE DB outage leaves CMS native/CWS and real official judging available; original workspace survives recovery')
report['status']='passed';(root/'database-fault-results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
