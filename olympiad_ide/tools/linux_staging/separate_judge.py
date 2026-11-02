"""Restrict helper execution and let a second native ResourceService own the CMS judge."""
import json,os,pwd,subprocess
from pathlib import Path
assert os.geteuid()==0
conf=Path('/etc/cms-ide-stage');cms=json.loads((conf/'cms.conf').read_text())
assert '/cmside_linux_fortesting?' in cms['database']
assert cms['core_services']['Worker']==[['127.0.0.1',31006]]
def run(*args):subprocess.run(args,check=True)
run('systemctl','stop','cms-ide-stage-resource','cms-ide-stage-worker')
try:
 try:pwd.getpwnam('cmsjudgestage')
 except KeyError:run('useradd','--system','--no-create-home','--shell','/usr/sbin/nologin','cmsjudgestage')
 result=subprocess.run(['getent','group','isolatestage'],capture_output=True)
 if result.returncode:run('groupadd','--system','isolatestage')
 for user in ['ideworkerstage','cmsjudgestage']:run('usermod','-a','-G','isolatestage',user)
 run('chown','root:isolatestage','/usr/local/bin/isolate');run('chmod','4750','/usr/local/bin/isolate')
 cms['core_services']['ResourceService'].append(['127.0.0.2',31101]);cms['core_services']['Worker']=[['127.0.0.2',31006]]
 (conf/'cms.conf').write_text(json.dumps(cms,indent=2)+'\n')
 judge={key:cms[key] for key in ['core_services','other_services','database','use_cgroups','keep_sandbox','submit_local_copy']}
 judge['cmsuser']='cmsjudgestage';judge['olympiad_ide_enabled']=False
 for key,suffix in [('temp_dir','tmp'),('log_dir','log'),('cache_dir','cache'),('data_dir','data'),('run_dir','run')]:
  path=Path('/var/lib/cms-ide-stage/judge-'+suffix);path.mkdir(mode=0o700);owner=pwd.getpwnam('cmsjudgestage');os.chown(path,owner.pw_uid,owner.pw_gid);judge[key]=str(path)
 path=conf/'judge.conf';path.write_text(json.dumps(judge,indent=2)+'\n');os.chown(path,owner.pw_uid,owner.pw_gid);path.chmod(0o600)
 pg=Path('/var/lib/cms-ide-stage/postgres')
 with (pg/'pg_ident.conf').open('a') as file:file.write('\ncms_stage_judge cmsstage cmsstage\ncms_stage_judge cmsjudgestage cmsstage\n')
 path=pg/'pg_hba.conf';path.write_text('local all cmsstage peer map=cms_stage_judge\n'+path.read_text())
 run('runuser','-u','stagepguser','--','/usr/lib/postgresql/18/bin/pg_ctl','-D',str(pg),'reload')
 unit=Path('/etc/systemd/system/cms-ide-stage-resource.service');unit.write_text(unit.read_text().replace('UMask=0077','NoNewPrivileges=true\nUMask=0077'))
 for name in ['log','ranking','ingress']:
  unit=Path('/etc/systemd/system/cms-ide-stage-'+name+'.service');text=unit.read_text()
  if 'NoNewPrivileges=' not in text:unit.write_text(text.replace('UMask=0077','NoNewPrivileges=true\nUMask=0077'))
 unit=Path('/etc/systemd/system/cms-ide-stage-judge.service');unit.write_text('''[Unit]
Description=Disposable CMS judging ResourceService and its owned Worker (no web helper access)
After=cms-ide-stage-postgres.service cms-ide-stage-log.service isolate.service
Requires=cms-ide-stage-postgres.service cms-ide-stage-log.service isolate.service
[Service]
User=cmsjudgestage
Group=cmsjudgestage
WorkingDirectory=/opt/cms-ide-stage/source
Environment=CMS_CONFIG=/etc/cms-ide-stage/judge.conf
Environment=PATH=/opt/cms-ide-stage/cms-venv/bin:/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/cms-ide-stage/cms-venv/bin/cmsResourceService 1 -a 1
Restart=on-failure
RestartSec=5
KillMode=control-group
TimeoutStopSec=30
UMask=0077
''')
 run('systemctl','daemon-reload')
finally:
 run('systemctl','start','cms-ide-stage-judge','cms-ide-stage-resource','cms-ide-stage-worker')
print('JUDGING_RESOURCE_SERVICE_1_OWNS_WORKER_NO_WEB_HELPER_ACCESS')
