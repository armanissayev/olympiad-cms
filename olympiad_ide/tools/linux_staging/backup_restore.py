"""Quiesce this staging deployment, restore to new DBs, prove app recovery, retain originals."""
import hashlib,json,os,pwd,subprocess,time
from pathlib import Path
import requests
root=Path('/var/lib/cms-ide-stage/fixture');meta=json.loads((root/'browser.json').read_text());assert meta['kind']=='disposable-linux-staging'
base=meta['baseUrl'];c=requests.Session();c.trust_env=False;c.verify=meta['certificate'];c.get(base+'/',timeout=10);assert c.post(base+'/login',data={'username':meta['username'],'password':meta['password'],'_xsrf':c.cookies.get('_xsrf')},timeout=10,allow_redirects=False).status_code==302
context=c.get(base+'/ide/api/context',timeout=10).json();task=next(t for t in context['tasks'] if t['name']=='cppsum');headers={'X-Olympiad-Principal':context['identity']['principalId'],'X-XSRFToken':context['csrfToken'],'X-Olympiad-Task':str(task['id'])}
def get(path):return c.get(base+path,headers=headers,timeout=15)
def fingerprints():
 workspaces=get('/ide/api/runtime/v1/workspaces').json();result={}
 for item in workspaces:
  response=get('/ide/api/runtime/v1/workspaces/'+item['id']);assert response.ok
  result[item['id']]=hashlib.sha256(json.dumps(response.json(),sort_keys=True).encode()).hexdigest()
 return result
before=fingerprints();assert before
receipts=json.loads((root/'core-results.json').read_text())['submissions'];old_receipts={item['intentId']:get('/ide/api/submissions/'+item['intentId']).json() for item in receipts}
conf=Path('/etc/cms-ide-stage');names=['cms.conf','judge.conf','runtime.env','worker.env','migration.env'];saved={name:(conf/name).read_text() for name in names}
services=['resource','judge','runtime','worker','ranking'];changed=False;passed=False
report={'kind':'linux-staging-application-restore','checks':[]}
def unit(operation,*names):subprocess.run(['systemctl',operation,*['cms-ide-stage-'+name+'.service' for name in names]],check=True)
try:
 unit('stop',*services)
 backup=Path('/var/lib/cms-ide-stage/backups');backup.mkdir(mode=0o700,exist_ok=True);u=pwd.getpwnam('stagepguser');os.chown(backup,u.pw_uid,u.pw_gid)
 subprocess.run(['tar','-czf',str(backup/'protected-config-and-ranking.tar.gz'),'-C','/','etc/cms-ide-stage','var/lib/cms-ide-stage/ranking-data'],check=True);(backup/'protected-config-and-ranking.tar.gz').chmod(0o600)
 result=subprocess.run(['runuser','-u','stagepguser','--','/opt/cms-ide-stage/cms-venv/bin/python','/opt/cms-ide-stage/incoming/restore.py'],capture_output=True,text=True);print(result.stdout,flush=True);assert result.returncode==0,'Restore comparison failed; protected diagnostics retained'
 restore=json.loads(Path((backup/'latest-report-path').read_text().strip()).read_text());assert restore['status']=='passed'
 target={item['source']:item['target'] for item in restore['databases']};cms_target=target['cmside_linux_fortesting'];ide_target=target['ide_linux_staging']
 for database,roles in [(cms_target,'cmsstage'),(ide_target,'idemigratestage,ideapistage,ideworkerstage')]:
  assert database.replace('_','').isalnum()
  subprocess.run(['runuser','-u','stagepguser','--','/usr/lib/postgresql/18/bin/psql','-X','-v','ON_ERROR_STOP=1','-h','/run/cms-ide-stage-pg','-p','15432','postgres','-c',f'REVOKE ALL ON DATABASE {database} FROM PUBLIC; GRANT CONNECT ON DATABASE {database} TO {roles};'],check=True,stdout=subprocess.DEVNULL)
 for name in ['cms.conf','judge.conf']:
  data=json.loads(saved[name]);assert '/cmside_linux_fortesting?' in data['database'];data['database']=data['database'].replace('/cmside_linux_fortesting?','/'+cms_target+'?');(conf/name).write_text(json.dumps(data,indent=2)+'\n')
 for name in ['runtime.env','worker.env','migration.env']:
  assert '/ide_linux_staging?' in saved[name];(conf/name).write_text(saved[name].replace('/ide_linux_staging?','/'+ide_target+'?'))
 changed=True;unit('start',*services)
 until=time.monotonic()+45
 while time.monotonic()<until:
  try:
   if get('/ide/health/ready').status_code==200 and get('/ide/api/runtime/v1/workspaces').status_code==200:break
  except requests.RequestException:pass
  time.sleep(.5)
 assert get('/ide/health/ready').status_code==200
 assert fingerprints()==before
 for item in receipts:
  response=get('/ide/api/submissions/'+item['intentId']);assert response.ok and response.json()==old_receipts[item['intentId']]
  feedback=get('/ide/api/submissions/status/'+item['submissionId']+'?taskId='+str(item['taskId']));assert feedback.ok and feedback.json()['status']['status']==5
 assert get('/').status_code==200
 report.update(status='passed',restoredDatabases=target,workspaceFingerprintsCompared=len(before),committedReceiptsCompared=len(receipts),originalDatabasesRetained=True,sourceDataPrinted=False,restoreReport=restore)
 report['checks']=['quiesced application writers','new empty PostgreSQL destinations','all table rows/schema/sequences/large objects compared','same participant session and workspace UUIDs recover through native gateway','same committed receipts and actual judged feedback recover','ordinary CWS available after restored application restart']
 (root/'restore-application-results.json').write_text(json.dumps(report,indent=2)+'\n');passed=True
 print(json.dumps({k:v for k,v in report.items() if k!='restoreReport'},indent=2))
finally:
 if not passed:
  for name,value in saved.items():(conf/name).write_text(value)
  unit('start',*services)
