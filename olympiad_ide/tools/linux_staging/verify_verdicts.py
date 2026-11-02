"""Exercise actual official CMS failure verdicts without copying restricted judge data."""
import gevent.monkey
gevent.monkey.patch_all()
import hashlib,json,time
from pathlib import Path
from uuid import uuid4
import requests
from cms.db import OlympiadIDEReceipt,SessionGen
root=Path('/var/lib/cms-ide-stage/fixture');meta=json.loads((root/'browser.json').read_text());assert meta['kind']=='disposable-linux-staging'
c=requests.Session();c.trust_env=False;c.verify=meta['certificate'];base=meta['baseUrl'];c.get(base+'/',timeout=10);assert c.post(base+'/login',data={'username':meta['username'],'password':meta['password'],'_xsrf':c.cookies.get('_xsrf')},allow_redirects=False,timeout=10).status_code==302
ctx=c.get(base+'/ide/api/context',timeout=10).json();task=next(t for t in ctx['tasks'] if t['name']=='cppsum');headers={'X-Olympiad-Principal':ctx['identity']['principalId'],'X-XSRFToken':ctx['csrfToken']}
cases=[('compilation_error','C++17 / g++','main.cpp','int main( { syntax error\n',2),('wrong_answer','C++17 / g++','main.cpp','#include <iostream>\nint main(){std::cout<<0<<"\\n";}\n',5),('runtime_error','Python 3 / CPython','main.py','raise RuntimeError("disposable staging fixture")\n',5),('time_limit','Python 3 / CPython','main.py','while True: pass\n',5)]
report={'kind':'real-linux-official-failure-verdicts','cases':[]}
for label,language,filename,source,terminal in cases:
 body={'schemaVersion':1,'intentId':str(uuid4()),'taskId':task['id'],'language':language,'workspaceId':str(uuid4()),'snapshotId':str(uuid4()),'telemetry':None,'files':[{'filename':'main.%l','sourceFilename':filename,'fileId':str(uuid4()),'content':source}]}
 r=c.post(base+'/ide/api/submissions',headers=headers,json=body,timeout=15);assert r.status_code==201,r.status_code;receipt=r.json()
 deadline=time.monotonic()+100
 while time.monotonic()<deadline:
  r=c.get(base+'/ide/api/submissions/status/'+receipt['submissionId'],params={'taskId':task['id']},headers=headers,timeout=10);assert r.ok;status=r.json()['status']
  if status['status'] in (2,5):break
  time.sleep(.3)
 assert status['status']==terminal,(label,status['status'])
 assert 'score' not in status
 assert not any(value in json.dumps(status) for value in ['1234567 7654321','8888888','-3999983','10000000000'])
 with SessionGen() as db:
  record=db.query(OlympiadIDEReceipt).filter_by(intent_id=body['intentId']).one();result=record.submission.get_result()
  if terminal==2:
   assert result.compilation_outcome=='fail' and 'error:' in status['compilation']['stderr']
  else:
   assert result.compilation_outcome=='ok' and result.evaluation_outcome=='ok' and result.score==0 and result.public_score==0 and len(result.evaluations)==4
   assert all(float(ev.outcome)==0 for ev in result.evaluations)
  if label=='runtime_error':assert all('signal' in str(ev.text).lower() or 'nonzero' in str(ev.text).lower() or 'exit' in str(ev.text).lower() for ev in result.evaluations)
  if label=='time_limit':assert all('time' in str(ev.text).lower() for ev in result.evaluations)
  report['cases'].append({'fixture':label,'language':language,'submissionId':receipt['submissionId'],'sourceSha256':hashlib.sha256(source.encode()).hexdigest(),'participantTerminalState':status['status'],'compilation':result.compilation_outcome,'evaluation':result.evaluation_outcome,'fullScoreOperatorOnly':result.score,'publicScore':result.public_score,'evaluatedCases':len(result.evaluations),'restrictedDataAbsent':True,'compilerDiagnosticVisible':bool(status.get('compilation',{}).get('stderr'))})
 print('Verified real official verdict',label,flush=True)
report['status']='passed';(root/'verdict-results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
