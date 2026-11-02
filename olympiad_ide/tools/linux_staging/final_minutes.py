"""Run a bounded final-minute mixture and prove late receipt/new-intent semantics."""
import json,subprocess,time
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
import requests
from cms.db import Contest,OlympiadIDEReceipt,SessionGen
from cmscommon.datetime import make_datetime
root=Path('/var/lib/cms-ide-stage/fixture');folder=root/'load';meta=json.loads((root/'browser.json').read_text());target=json.loads((folder/'target.json').read_text());assert meta['kind']=='disposable-linux-staging' and target['contestName']=='ide-load-linux-staging'
# Keep the observed failed2second-poll run intact; this separate mixed run uses bounded6s+ reconciliation windows.
p=folder/'final_minutes.json';fixture=json.loads(p.read_text());prefix=fixture['steps'][:6]
def read_job(check=False):return {'method':'GET','path':'/ide/api/runtime/v1/executions/{{jobId}}','expect':[200],**({'assert':{'status':'FINISHED'}} if check else {})}
def read_score(check=False):return {'method':'GET','path':'/ide/api/submissions/status/{{submissionId}}?taskId={{taskId}}','expect':[200],**({'assert':{'status.status':5}} if check else {})}
fixture['steps']=prefix+[read_job() for _ in range(10)]+[read_job(True)]+[read_score() for _ in range(20)]+[read_score(True)];p.write_text(json.dumps(fixture))
with SessionGen() as db:
 contest=db.query(Contest).filter_by(id=1).one();assert contest.name==target['contestName'];old_stop=contest.stop;started=make_datetime();deadline=started+timedelta(seconds=120);contest.stop=deadline;db.commit()
report={'kind':'real-final-minutes','start':started.isoformat()+'Z','deadline':deadline.isoformat()+'Z','participants':10,'rateHttpPerSecond':5,'concurrency':2}
try:
 result=subprocess.run(['/opt/cms-ide-stage/cms-venv/bin/python','/opt/cms-ide-stage/source/olympiad_ide/tools/cms_load.py','--target',str(folder/'target.json'),'--credentials',str(folder/'credentials.json'),'--plan',str(folder/'final-plan.json'),'--confirm-disposable',target['targetId'],'--allow-custom-runs','--allow-official-submissions','--report',str(folder/'final-report.json')],capture_output=True,text=True)
 report['loadExitCode']=result.returncode;print(result.stdout,flush=True)
 assert result.returncode==0,'Final-minute operation failed; preserve report and reconcile receipts'
 while make_datetime()<=deadline:
  remaining=(deadline-make_datetime()).total_seconds();print('Waiting for actual deadline;',round(remaining,1),'seconds',flush=True);time.sleep(min(10,max(.2,remaining+1)))
 with SessionGen() as db:
  receipts=db.query(OlympiadIDEReceipt).filter(OlympiadIDEReceipt.received_at>=started).all()
  assert len(receipts)==10,len(receipts)
  assert all(item.received_at<=deadline for item in receipts)
  expected=next(item for item in receipts if item.submission.participation.user.username=='stage-load-001');intent_id=expected.intent_id
  report['admittedBeforeDeadline']=len(receipts);report['lastReceivedAt']=max(item.received_at for item in receipts).isoformat()+'Z'
 actor=json.loads((folder/'credentials.json').read_text())[0];c=requests.Session();c.trust_env=False;c.verify=meta['certificate'];base=meta['baseUrl'];c.get(base+'/',timeout=10)
 assert c.post(base+'/login',data={'username':actor['username'],'password':actor['password'],'_xsrf':c.cookies.get('_xsrf')},allow_redirects=False,timeout=10).status_code==302
 context=c.get(base+'/ide/api/context',timeout=10).json();headers={'X-Olympiad-Principal':context['identity']['principalId'],'X-XSRFToken':context['csrfToken']}
 receipt=c.get(base+'/ide/api/submissions/'+intent_id,headers=headers,timeout=10);assert receipt.status_code==200
 body={'schemaVersion':1,'intentId':str(uuid4()),'taskId':actor['taskId'],'language':'C++17 / g++','workspaceId':actor['variables']['workspaceId'],'snapshotId':str(uuid4()),'telemetry':None,'files':[{'filename':'main.%l','sourceFilename':'main.cpp','fileId':actor['variables']['fileId'],'content':actor['variables']['source']}]}
 late=c.post(base+'/ide/api/submissions',headers=headers,json=body,timeout=15);assert late.status_code==422,late.status_code
 report['committedReceiptAfterDeadline']=receipt.status_code;report['newLateIntent']=late.status_code;report['status']='passed'
finally:
 with SessionGen() as db:
  db.query(Contest).filter_by(id=1).one().stop=old_stop;db.commit()
 (root/'final-minutes-results.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
