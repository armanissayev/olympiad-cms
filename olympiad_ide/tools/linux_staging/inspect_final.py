"""Sanitized final versions and supervisor ownership; no environment/config secrets."""
import hashlib,ipaddress,json,os,platform,subprocess
from datetime import datetime,timezone
from pathlib import Path
import psutil
root=Path('/opt/cms-ide-stage');report={'kind':'linux-staging-final-environment','time':datetime.now(timezone.utc).isoformat()}
def output(args):return subprocess.check_output(args,text=True).strip()
report['os']=output(['/usr/bin/lsb_release','-ds']);report['kernel']=platform.release();report['architecture']=platform.machine();report['logicalCpus']=os.cpu_count();report['memoryBytes']=psutil.virtual_memory().total;report['diskRoot']=dict(zip(['total','used','free'],__import__('shutil').disk_usage('/')))
report['cmsSourceCommit']=(root/'SOURCE_COMMIT').read_text().strip();report['cmsBaseTag']='CMSv1.5.1';report['cmsBaseCommit']='7c9fec8aa1a25ec93d624aebf815804dd93df9db'
for name in ['cms','runtime']:
 binary=str(root/(name+'-venv')/'bin/python');code='import sys,json,importlib.metadata as m;print(json.dumps({"python":sys.version.split()[0],"packages":{n:m.version(n) for n in '+repr(['SQLAlchemy','gevent','tornado','pytest','psutil'] if name=='cms' else ['SQLAlchemy','fastapi','uvicorn','pytest','alembic'])+'}}))';report[name]=json.loads(output([binary,'-c',code]))
report['toolchains']={'gpp':output(['/usr/bin/g++','--version']).splitlines()[0],'python3':output(['/usr/bin/python3','--version']),'javac':output(['/usr/bin/javac','-version']),'node':output(['/usr/bin/node','--version']),'nginx':subprocess.run(['/usr/sbin/nginx','-v'],capture_output=True,text=True).stderr.strip(),'postgres':output(['/usr/lib/postgresql/18/bin/postgres','--version'])}
report['isolate']={'commit':output(['git','-C',str(root/'isolate-source'),'rev-parse','HEAD']),'version':output(['/usr/local/bin/isolate','--version']),'helperSha256':hashlib.sha256(Path('/usr/local/bin/isolate').read_bytes()).hexdigest(),'helperMode':oct(Path('/usr/local/bin/isolate').stat().st_mode&0o7777),'cgroupControllers':Path('/sys/fs/cgroup/cgroup.controllers').read_text().strip(),'keeper':output(['systemctl','show','isolate.service','-p','Delegate','-p','ControlGroup','-p','ActiveState']),'mount':output(['findmnt','-no','FSTYPE,OPTIONS','/var/lib/cms-ide-stage/boxes']),'swapEntries':len(Path('/proc/swaps').read_text().splitlines())-1}
report['installedDatabaseModuleSha256']=hashlib.sha256((root/'cms-venv/lib/python3.12/site-packages/cms/db/__init__.py').read_bytes()).hexdigest();report['sourceDatabaseModuleSha256']=hashlib.sha256((root/'source/cms/db/__init__.py').read_bytes()).hexdigest();assert report['installedDatabaseModuleSha256']==report['sourceDatabaseModuleSha256']
report['services']={}
for name in ['postgres','runtime','log','resource','judge','ranking','worker','ingress']:
 unit='cms-ide-stage-'+name+'.service';values=output(['systemctl','show',unit,'-p','User','-p','ActiveState','-p','MainPID','-p','NoNewPrivileges','-p','PrivateNetwork']);info=dict(line.split('=',1) for line in values.splitlines());assert info['ActiveState']=='active';pid=int(info['MainPID']);info['children']=[{'pid':p.pid,'ppid':p.ppid(),'user':p.username(),'command':[Path(s).name if '/' in s else s for s in p.cmdline()]} for p in psutil.Process(pid).children(recursive=True)];report['services'][unit]=info
report['listeners']=output(['ss','-lnt'])
public_ports=[]
for row in report['listeners'].splitlines()[1:]:
 host,port=row.split()[3].rsplit(':',1);host=host.strip('[]').split('%',1)[0]
 if not ipaddress.ip_address(host).is_loopback:public_ports.append(int(port))
assert set(public_ports)<=set([22]),public_ports
report['publicApplicationListeners']=False;report['publicPorts']=sorted(set(public_ports));report['loadGeneratorTopology']='same-host loopback TLS; max12 concurrent HTTP actors; separately tested remote Chromium via SSH tunnel'
Path('/var/lib/cms-ide-stage/fixture/environment-results.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
