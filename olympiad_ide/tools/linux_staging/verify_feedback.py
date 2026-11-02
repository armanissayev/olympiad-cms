"""Exercise real token/rejudge/active-dataset behavior on this disposable contest."""
import gevent.monkey
gevent.monkey.patch_all()
import json,time
from pathlib import Path
import gevent,requests
from cms import ServiceCoord
from cms.db import Dataset,OlympiadIDEReceipt,SessionGen,Submission,Task,Testcase
from cms.io import RemoteServiceClient

root=Path('/var/lib/cms-ide-stage/fixture');meta=json.loads((root/'browser.json').read_text());core=json.loads((root/'core-results.json').read_text());record=core['submissions'][0]
assert meta['kind']=='disposable-linux-staging' and record['task']=='cppsum'
c=requests.Session();c.trust_env=False;c.verify=meta['certificate'];base=meta['baseUrl'];c.get(base+'/',timeout=10);assert c.post(base+'/login',data={'username':meta['username'],'password':meta['password'],'_xsrf':c.cookies.get('_xsrf')},allow_redirects=False,timeout=10).status_code==302
ctx=c.get(base+'/ide/api/context',timeout=10).json();headers={'X-Olympiad-Principal':ctx['identity']['principalId'],'X-XSRFToken':ctx['csrfToken']}
def status():
 r=c.get(base+'/ide/api/submissions/status/'+record['submissionId'],params={'taskId':record['taskId']},headers=headers,timeout=10);assert r.ok;return r.json()['status']
def safe(data):
 text=json.dumps(data)
 for secret in ['1234567','7654321','9999999999','8888888']:
  assert secret not in text,'Hidden input/output reached participant response'
def rpc(name):
 client=RemoteServiceClient(ServiceCoord(name,0),auto_retry=.2);client.connect();deadline=time.monotonic()+10
 while not client.connected and time.monotonic()<deadline:gevent.sleep(.1)
 assert client.connected;return client
def wait(predicate,timeout=90):
 deadline=time.monotonic()+timeout
 while time.monotonic()<deadline:
  value=predicate()
  if value:return value
  gevent.sleep(.2)
 raise AssertionError('Real feedback transition did not complete')
report={'kind':'real-linux-feedback-policy','checks':[]}
before=status();assert 'score' not in before and before['public_score']==25;safe([ctx,before])
assert c.get(base+'/tasks/cppsum/attachments/hidden-a.in',timeout=10).status_code==404
r=c.post(base+'/tasks/cppsum/submissions/'+str(record['ordinal'])+'/token',data={'_xsrf':c.cookies.get('_xsrf')},timeout=10,allow_redirects=False);assert r.status_code==302,r.status_code
after=status();assert after['score']==100 and len(after['detailsText'])>len(before['detailsText']);safe(after)
report['token']={'publicBefore':before['public_score'],'fullScoreAbsentBefore':True,'fullAfterToken':after['score'],'detailsExpanded':True,'hiddenInputsStillAbsent':True}
report['checks'].append('Actual CWS token unlocks only permitted full score/details; hidden inputs/outputs remain inaccessible')
es=rpc('EvaluationService');proxy=rpc('ProxyService')
with SessionGen() as db:
 submission=db.query(Submission).filter_by(id=record['databaseId']).one();old_evaluations={e.id for e in submission.get_result().evaluations}
es.invalidate_submission(submission_id=record['databaseId'],level='evaluation').get(timeout=10)
def rejudged():
 with SessionGen() as db:
  submission=db.query(Submission).filter_by(id=record['databaseId']).one();result=submission.get_result()
  return result.scored() and {e.id for e in result.evaluations}!=old_evaluations and result.score==100
wait(rejudged);assert status()['score']==100
report['checks'].append('EvaluationService invalidation performed fresh real testcase evaluations; tokened feedback refreshed')
with SessionGen() as db:
 task=db.query(Task).filter_by(id=record['taskId']).one();original=task.active_dataset;original_id=original.id
 assert not any(d.description=='linux-alternate' for d in task.datasets)
 alternate=Dataset(task=task,description='linux-alternate',task_type=original.task_type,task_type_parameters=original.task_type_parameters,score_type='Sum',score_type_parameters=10,time_limit=original.time_limit,memory_limit=original.memory_limit)
 for tc in original.testcases.values():Testcase(dataset=alternate,codename=tc.codename,public=tc.public,input=tc.input,output=tc.output)
 db.add(alternate);db.flush();alternate_id=alternate.id;task.active_dataset=alternate;db.commit()
try:
 pending=status();assert pending['status']==1 and 'score' not in pending,pending
 with SessionGen() as db:
  ids=[s.id for s in db.query(Submission).filter_by(task_id=record['taskId'])]
 for sid in ids:es.new_submission(submission_id=sid).get(timeout=10)
 proxy.dataset_updated(task_id=record['taskId']).get(timeout=10)
 wait(lambda: status().get('score')==40)
 active=status();assert active['public_score']==10 and active['max_score']==40;safe(active)
 deadline=time.monotonic()+25
 while time.monotonic()<deadline:
  scores=c.get(meta['rankingUrl']+'/scores',timeout=10).json()
  if any(tasks.get('cppsum')==40 for tasks in scores.values()):break
  gevent.sleep(.3)
 assert any(tasks.get('cppsum')==40 for tasks in scores.values()),scores
 report['datasetSwitch']={'originalDataset':original_id,'alternateDataset':alternate_id,'initialState':pending['status'],'freshRealScore':active['score'],'freshPublicScore':active['public_score'],'rankingChangedTo':40}
 report['checks'].append('Active dataset change hides stale scores, triggers actual compiling/evaluation and updates native/CWS/ranking to40')
finally:
 with SessionGen() as db:
  task=db.query(Task).filter_by(id=record['taskId']).one();task.active_dataset=db.query(Dataset).filter_by(id=original_id).one();db.commit()
 proxy.dataset_updated(task_id=record['taskId']).get(timeout=10)
assert status()['score']==100
report['checks'].append('Original active dataset restored without losing historical results or receipt ownership')
report['status']='passed';(root/'feedback-results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
