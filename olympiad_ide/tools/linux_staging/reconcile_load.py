"""Read-only reconcile the five admitted load submissions whose short polling expired."""
import gevent.monkey
gevent.monkey.patch_all()
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path
import requests
from cms.db import SessionGen,Submission
from cms.db.filecacher import FileCacher
root=Path('/var/lib/cms-ide-stage/fixture');meta=json.loads((root/'browser.json').read_text());assert meta['kind']=='disposable-linux-staging'
actors=json.loads((root/'load/credentials.json').read_text())[:5];report={'kind':'short-poll-load-reconciliation','readOnly':True,'reconciledAt':datetime.now(timezone.utc).isoformat(),'originalReportUnchanged':True,'originalFailedOperations':5,'submissions':[]}
for actor in actors:
 c=requests.Session();c.trust_env=False;c.verify=meta['certificate'];base=meta['baseUrl'];c.get(base+'/',timeout=10);assert c.post(base+'/login',data={'username':actor['username'],'password':actor['password'],'_xsrf':c.cookies.get('_xsrf')},allow_redirects=False,timeout=10).status_code==302
 ctx=c.get(base+'/ide/api/context',timeout=10).json();h={'X-Olympiad-Principal':ctx['identity']['principalId'],'X-Olympiad-Task':str(actor['taskId'])}
 with SessionGen() as db:
  candidates=db.query(Submission).filter(Submission.id.between(5,9)).all();s=next(x for x in candidates if x.participation.user.username==actor['username']);receipt=s.olympiad_ide_receipts[0]
  # One receipt exists per native submission; never infer source identity from admission alone.
  if receipt is None:raise AssertionError('Missing original receipt')
  result=s.get_result();assert result.compilation_outcome=='ok' and result.evaluation_outcome=='ok' and result.score==100 and len(result.evaluations)==4
  raw=FileCacher().get_file_content(s.files['main.%l'].digest);assert raw==actor['variables']['source'].encode()
  external=receipt.external_id
  r=c.get(base+'/ide/api/submissions/status/'+external,params={'taskId':actor['taskId']},headers=h,timeout=10);assert r.ok and r.json()['status']['status']==5 and r.json()['status']['public_score']==25 and 'score' not in r.json()['status']
  report['submissions'].append({'databaseId':s.id,'submissionId':external,'compileOutcome':result.compilation_outcome,'evaluationOutcome':result.evaluation_outcome,'fullScoreOperatorOnly':result.score,'publicScore':result.public_score,'evaluatedCases':len(result.evaluations),'sourceSha256':hashlib.sha256(raw).hexdigest(),'participantTerminalState':5})
report['status']='passed';(root/'load-reconciliation-results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
