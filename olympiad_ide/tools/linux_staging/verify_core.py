"""Real native admission -> CMS judging -> participant/CWS/Admin/ranking checks."""
import gevent.monkey
gevent.monkey.patch_all()
import hashlib,json,time
from pathlib import Path
from uuid import uuid4
import requests
from cms.db import OlympiadIDEReceipt,SessionGen,Submission,SubmissionResult
from cms.db.filecacher import FileCacher

ROOT=Path('/var/lib/cms-ide-stage/fixture')
m=json.loads((ROOT/'browser.json').read_text())
assert m['kind']=='disposable-linux-staging' and m['contestId']==1
base=m['baseUrl'];cert=m['certificate']
def client():
 c=requests.Session();c.trust_env=False;c.verify=cert;return c
c=client();c.get(base+'/',timeout=10)
r=c.post(base+'/login',data={'username':m['username'],'password':m['password'],'_xsrf':c.cookies.get('_xsrf')},timeout=10,allow_redirects=False);assert r.status_code==302,r.status_code
ctx=c.get(base+'/ide/api/context',timeout=10).json();assert ctx['identity']['installationId']==m['installationId']
headers={'X-XSRFToken':ctx['csrfToken'],'X-Olympiad-Principal':ctx['identity']['principalId']}
programs=[('cppsum','C++17 / g++','main.cpp','#include <iostream>\nint main(){long long a,b;std::cin>>a>>b;std::cout<<a+b<<"\\n";}\n'),('pysum','Python 3 / CPython','main.py','a,b=map(int,input().split())\nprint(a+b)\n')]
report={'kind':'real-linux-native-judging','checks':[],'submissions':[],'sourceCommit':'7f6517fa12d6e6555382f5f2c4fbeb1f6e03dd01'}
for name,language,filename,source in programs:
 task=next(t for t in ctx['tasks'] if t['name']==name)
 body={'schemaVersion':1,'intentId':str(uuid4()),'taskId':task['id'],'language':language,'workspaceId':str(uuid4()),'snapshotId':str(uuid4()),'telemetry':None,'files':[{'filename':'main.%l','sourceFilename':filename,'fileId':str(uuid4()),'content':source}]}
 response=c.post(base+'/ide/api/submissions',json=body,headers=headers,timeout=15);assert response.status_code==201,(response.status_code,response.text)
 receipt=response.json();assert receipt['files'][0]['sha256']==hashlib.sha256(source.encode()).hexdigest()
 print('Actual native admission',name,receipt['submissionId'],flush=True)
 deadline=time.monotonic()+120;observed=[]
 while time.monotonic()<deadline:
  response=c.get(base+'/ide/api/submissions/status/'+receipt['submissionId'],params={'taskId':task['id']},headers=headers,timeout=10);assert response.ok,response.status_code
  status=response.json()['status']
  if status['status'] not in observed:observed.append(status['status']);print('CMS judging state',name,status['status'],flush=True)
  if status['status'] in (2,5):break
  time.sleep(.3)
 assert status['status']==5,status
 assert status['public_score']==25,status
 assert 'score' not in status,status
 with SessionGen() as db:
  record=db.query(OlympiadIDEReceipt).filter_by(intent_id=body['intentId']).one();submission=record.submission;result=submission.get_result()
  assert result.compilation_outcome=='ok' and result.evaluation_outcome=='ok'
  assert result.score==100 and result.public_score==25
  assert len(result.evaluations)==4 and all(float(ev.outcome)==1 for ev in result.evaluations)
  assert all(ev.execution_time is not None and ev.execution_memory is not None for ev in result.evaluations)
  actual=FileCacher().get_file_content(submission.files['main.%l'].digest);assert actual==source.encode()
  sid=submission.id;ordinal=db.query(Submission).filter(Submission.participation_id==submission.participation_id,Submission.task_id==task['id'],Submission.id<=sid).count()
  detail={'databaseId':sid,'intentId':body['intentId'],'submissionId':receipt['submissionId'],'task':name,'taskId':task['id'],'language':language,'sourceSha256':hashlib.sha256(actual).hexdigest(),'compileOutcome':result.compilation_outcome,'evaluationOutcome':result.evaluation_outcome,'fullScoreOperatorOnly':result.score,'publicScore':result.public_score,'evaluatedCases':len(result.evaluations),'statesObserved':observed,'ordinal':ordinal}
 report['submissions'].append(detail)
 assert c.post(base+'/ide/api/submissions',json=body,headers=headers,timeout=10).status_code==200
 assert c.get(base+'/tasks/'+name+'/submissions',timeout=10).status_code==200
 report['checks'].append(name+': native exact bytes, real compilation/evaluation100, public25/full hidden, CWS visibility, duplicate200')
admin=client();admin.get(m['adminUrl']+'/login',timeout=10)
r=admin.post(m['adminUrl']+'/login',data={'username':m['adminUsername'],'password':m['adminPassword'],'_xsrf':admin.cookies.get('_xsrf')},allow_redirects=False,timeout=10);assert r.status_code==302,r.status_code
for record in report['submissions']:
 r=admin.get(m['adminUrl']+'/submission/'+str(record['databaseId']),timeout=15);assert r.status_code==200,r.status_code
 assert '100' in r.text
report['checks'].append('Authenticated Admin submission pages show real results')
deadline=time.monotonic()+20
while time.monotonic()<deadline:
 rank=client().get(m['rankingUrl']+'/submissions/',timeout=10)
 if rank.ok and len(rank.json())>=2:break
 time.sleep(.5)
assert rank.ok and len(rank.json())>=2,(rank.status_code,rank.text[:200])
subchanges=client().get(m['rankingUrl']+'/subchanges/',timeout=10);assert subchanges.ok
report['ranking']={'submissions':len(rank.json()),'subchanges':len(subchanges.json()),'scores':client().get(m['rankingUrl']+'/scores',timeout=10).json()}
assert report['ranking']['subchanges']>=2
report['checks'].append('ProxyService published actual submission/score changes to configured RankingWebServer')
report['status']='passed';(ROOT/'core-results.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
