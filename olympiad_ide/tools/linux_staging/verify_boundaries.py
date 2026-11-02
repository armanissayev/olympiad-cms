"""Read-only checks of final staging process, helper, file, network and DB boundaries."""
import json,os,subprocess
from pathlib import Path
assert os.geteuid()==0
report={'kind':'linux-staging-boundaries','checks':[]}
def run(args):return subprocess.run(args,capture_output=True,text=True,timeout=10)
for account in ['cmsstage','ideapistage','cmsingressstage']:
 result=run(['runuser','-u',account,'--','/usr/local/bin/isolate','--version']);assert result.returncode!=0,(account,result.stdout)
for account in ['cmsjudgestage','ideworkerstage']:
 result=run(['runuser','-u',account,'--','/usr/local/bin/isolate','--version']);assert result.returncode==0,(account,result.stderr)
report['checks'].append('Helper4750 root:isolatestage executable only by official/custom execution accounts; CMS/native/API/ingress denied')
for path in ['/etc/cms-ide-stage/cms.conf','/etc/cms-ide-stage/judge.conf','/etc/cms-ide-stage/native.key','/etc/cms-ide-stage/runtime.key','/var/lib/cms-ide-stage/cms-cache','/var/lib/cms-ide-stage/judge-cache']:
 result=run(['runuser','-u','ideworkerstage','--','test','-r',path]);assert result.returncode!=0,path
for path in ['/etc/cms-ide-stage/cms.conf','/etc/cms-ide-stage/judge.conf','/etc/cms-ide-stage/native.key']:
 assert run(['runuser','-u','ideapistage','--','test','-r',path]).returncode!=0,path
report['checks'].append('Custom controller cannot read CMS config/key/judge cache; API cannot read CMS config/key')
judge=json.loads(Path('/etc/cms-ide-stage/judge.conf').read_text());assert not {'secret_key','olympiad_ide_signing_key_file','rankings'}&judge.keys()
for unit in ['resource','runtime','log','ranking','ingress']:
 r=run(['systemctl','show','cms-ide-stage-'+unit,'-p','NoNewPrivileges','--value']);assert r.stdout.strip()=='yes',(unit,r.stdout)
assert run(['systemctl','show','cms-ide-stage-worker','-p','PrivateNetwork','--value']).stdout.strip()=='yes'
pid=int(run(['systemctl','show','cms-ide-stage-worker','-p','MainPID','--value']).stdout)
code='import socket\nfor port in [31003,31004,31006,18888,18891,18801]:\n try:\n  s=socket.create_connection(("127.0.0.1",port),.5)\n except OSError:continue\n else:s.close();raise AssertionError("Unexpected reachable CMS/runtime listener")\n'
r=run(['nsenter','-t',str(pid),'-n','--','/usr/bin/python3','-c',code]);assert r.returncode==0,r.stderr
report['checks'].append('Custom worker network namespace cannot establish TCP to CMS RPC, CWS, native or private runtime')
# All accounts use peer auth and narrowly granted CONNECT, not CMS passwords.
cms=json.loads(Path('/etc/cms-ide-stage/cms.conf').read_text());cmsdb=cms['database'].split('@/')[1].split('?')[0]
ideenv=Path('/etc/cms-ide-stage/worker.env').read_text();idedb=next(x for x in ideenv.splitlines() if x.startswith('DATABASE_URL=')).split('@/')[1].split('?')[0]
psql=['/usr/lib/postgresql/18/bin/psql','-X','-v','ON_ERROR_STOP=1','-h','/run/cms-ide-stage-pg','-p','15432']
r=run(['runuser','-u','ideworkerstage','--',*psql,cmsdb,'-c','SELECT 1']);assert r.returncode!=0
r=run(['runuser','-u','ideworkerstage','--',*psql,idedb,'-c','SELECT 1 FROM workspaces LIMIT 1']);assert r.returncode!=0
r=run(['runuser','-u','ideworkerstage','--',*psql,idedb,'-c','SELECT 1 FROM execution_jobs LIMIT 1']);assert r.returncode==0,r.stderr
report['checks'].append('Custom worker CMS DB CONNECT denied, IDE workspace SELECT denied, execution job SELECT allowed')
report['status']='passed';Path('/var/lib/cms-ide-stage/fixture/boundary-results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
