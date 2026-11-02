"""Staging-only component outages; root controls units, CMS keeps official authority."""
import gevent.monkey
gevent.monkey.patch_all()
import hashlib,json,re,socket,subprocess,time
from pathlib import Path
from uuid import uuid4
import gevent,requests
from cms import ServiceCoord
from cms.io import RemoteServiceClient

assert re.fullmatch(r'[a-f0-9]{40}',Path('/opt/cms-ide-stage/SOURCE_COMMIT').read_text().strip())
root=Path('/var/lib/cms-ide-stage/fixture');meta=json.loads((root/'browser.json').read_text());assert meta['kind']=='disposable-linux-staging'
base=meta['baseUrl'];client=requests.Session();client.trust_env=False;client.verify=meta['certificate'];client.get(base+'/',timeout=10)
assert client.post(base+'/login',data={'username':meta['username'],'password':meta['password'],'_xsrf':client.cookies.get('_xsrf')},allow_redirects=False,timeout=10).status_code==302
ctx=client.get(base+'/ide/api/context',timeout=10).json();task=next(t for t in ctx['tasks'] if t['name']=='cppsum');headers={'X-Olympiad-Principal':ctx['identity']['principalId'],'X-XSRFToken':ctx['csrfToken'],'X-Olympiad-Task':str(task['id'])}
report={'kind':'real-linux-component-outages','checks':[],'official':[]}
source='#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}\n'
def wait(fn,timeout=35):
 until=time.monotonic()+timeout
 while time.monotonic()<until:
  try:
   value=fn()
   if value:return value
  except (requests.RequestException,OSError):pass
  gevent.sleep(.2)
 raise AssertionError('Bounded staging recovery timed out')
def get(path):return client.get(base+path,headers=headers,timeout=10)
def post(path,body):return client.post(base+path,headers=headers,json=body,timeout=15)
def intent():return {'schemaVersion':1,'intentId':str(uuid4()),'taskId':task['id'],'language':'C++17 / g++','workspaceId':str(uuid4()),'snapshotId':str(uuid4()),'telemetry':None,'files':[{'filename':'main.%l','sourceFilename':'main.cpp','fileId':str(uuid4()),'content':source}]}
def admit():
 body=intent();r=post('/ide/api/submissions',body);assert r.status_code==201,(r.status_code,r.text);receipt=r.json();assert post('/ide/api/submissions',body).status_code==200;report['official'].append({'intentId':body['intentId'],'submissionId':receipt['submissionId']});return body,receipt
def judged(receipt,timeout=120):
 def done():
  r=get('/ide/api/submissions/status/'+receipt['submissionId']+'?taskId='+str(task['id']));return r.ok and r.json()['status']['status']==5
 wait(done,timeout)
def unit(name,operation):subprocess.run(['systemctl',operation,'cms-ide-stage-'+name+'.service'],check=True)
def tcp(port):
 try:
  with socket.create_connection(('127.0.0.1',port),timeout=.5):return True
 except OSError:return False
rs=RemoteServiceClient(ServiceCoord('ResourceService',0),auto_retry=.2);rs.connect();wait(lambda:rs.connected)
def stop_cms(name):
 assert rs.toggle_autorestart(service=name+',0').get(timeout=5) is False
 c=RemoteServiceClient(ServiceCoord(name,0),auto_retry=.2);c.connect();wait(lambda:c.connected)
 try:c.quit(reason='Authorized disposable Linux staging outage').get(timeout=5)
 except Exception:
  port={'EvaluationService':31004,'OlympiadIDEService':31003}[name]
  try:wait(lambda:not tcp(port),10)
  except Exception:
   start_cms(name);raise
def start_cms(name):assert rs.toggle_autorestart(service=name+',0').get(timeout=5) is True
runtime='/ide/api/runtime/v1/'
workspaces=get(runtime+'workspaces').json();assert workspaces;workspace=workspaces[0];workspace_id=workspace['id'];baseline=json.dumps(workspace,sort_keys=True)
fid=next(n['id'] for n in workspace['document']['nodes'].values() if n['type']=='file' and n['language']=='cpp')
configuration={'kind':'configuration','id':str(uuid4()),'name':'Staging outage recovery','language':'cpp20','entryPoint':fid,'includedFiles':[fid],'compilerProfile':'release','mainClass':None,'defaultTestId':None}
files=[{'id':fid,'path':'main.cpp','content':source}]
custom={'id':str(uuid4()),'workspaceId':workspace_id,'configuration':configuration,'files':files,'sourceHash':hashlib.sha256(json.dumps({'files':files,'configuration':configuration},sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest(),'tests':[{'kind':'test','id':str(uuid4()),'name':'Recovered real run','stdin':'2 3\n','expectedStdout':'5\n'}]}
# Missing custom capacity must not affect official judging.
unit('worker','stop')
try:
 wait(lambda:get(runtime+'execution-capacity').json()['workers']==0)
 r=post(runtime+'executions',custom);assert r.status_code==503 and r.json()['error']['code']=='worker_unavailable',r.text
 _,receipt=admit();judged(receipt);assert get('/').status_code==200
 report['checks'].append('Worker outage: real custom admission503 while official201->real judged result and CWS200')
finally:unit('worker','start')
wait(lambda:get(runtime+'execution-capacity').json()['workers']>0)
r=post(runtime+'executions',custom);assert r.status_code==201,r.text
wait(lambda:get(runtime+'executions/'+custom['id']).json()['status']=='FINISHED');assert get(runtime+'executions/'+custom['id']).json()['result']['cases'][0]['stdout']=='5\n'
# Separate ASGI runtime outage.
unit('runtime','stop')
try:
 assert get('/ide/api/context').status_code==200 and get(runtime+'workspaces').status_code==503
 _,receipt=admit();judged(receipt);assert get('/').status_code==200
 report['checks'].append('Runtime outage: gateway503 while native/CWS200 and official201->real judged result')
finally:unit('runtime','start')
wait(lambda:get(runtime+'workspaces/'+workspace_id).status_code==200)
assert json.dumps(get(runtime+'workspaces/'+workspace_id).json(),sort_keys=True)==baseline
# Commit while EvaluationService cannot receive the hint; restart uses its own sweep.
stop_cms('EvaluationService');wait(lambda:not tcp(31004))
try:
 body,receipt=admit();assert get('/ide/api/submissions/'+body['intentId']).status_code==200
 started=time.monotonic()
finally:start_cms('EvaluationService')
judged(receipt,150);report['evaluationRecoverySeconds']=round(time.monotonic()-started,3)
report['checks'].append('EvaluationService outage: durable201/retry200 and unassisted normal restart/sweep produced real judged result')
# Native service can be intentionally stopped while ordinary CWS stays usable.
stop_cms('OlympiadIDEService');wait(lambda:not tcp(18891))
try:
 gevent.sleep(6);assert not tcp(18891);assert get('/').status_code==200
 fallback=client.post(base+'/tasks/cppsum/submit',data={'language':'C++17 / g++','_xsrf':client.cookies.get('_xsrf')},files={'main.%l':('main.cpp',source.encode(),'text/plain')},allow_redirects=False,timeout=15);assert fallback.status_code==302,fallback.status_code
 report['checks'].append('Intentional native stop honored by ResourceService; ordinary CWS multipart submission302')
finally:start_cms('OlympiadIDEService')
wait(lambda:get('/ide/health/ready').status_code==200)
history=get('/ide/api/submissions?taskId='+str(task['id'])).json()['submissions'];fallback=next(item for item in history if item['intentId'] is None);assert fallback['correlation'] is None;judged(fallback);report['fallback']={'submissionId':fallback['submissionId'],'intentId':None,'correlation':None,'realJudging':'scored'}
for item in report['official']:assert get('/ide/api/submissions/'+item['intentId']).status_code==200
report['status']='passed';(root/'outage-results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
