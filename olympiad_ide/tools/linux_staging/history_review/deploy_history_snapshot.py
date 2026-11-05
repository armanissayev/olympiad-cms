"""Apply only the verified Admin/history delta; preserve native CMS process ownership."""
import hashlib,json,os,shutil,socket,subprocess,sys,time
from pathlib import Path
from urllib.parse import urlsplit
import psutil

assert os.geteuid()==0
stage=Path('/opt/cms-ide-stage');source=stage/'source'
location=Path(sys.argv[1]).resolve();assert location.is_relative_to(stage/'verification')
snapshot=location/'source';manifest=json.loads((location/'delta-manifest.json').read_text())
assert len(manifest['files'])==13 and len({row['path'] for row in manifest['files']})==13
assert (location/'delta-manifest.json').stat().st_uid==0 and not (location/'delta-manifest.json').stat().st_mode&0o022
for row in manifest['files']:
 path=Path(row['path']);assert not path.is_absolute() and '..' not in path.parts
 assert row['path'].startswith(('cms/server/admin/','cmstestsuite/unit_tests/server/olympiadide/','olympiad_ide/backend/app/','olympiad_ide/backend/tests/','olympiad_ide/frontend/tools/','docs/olympiad-ide/'))
 assert (snapshot/path).is_file() and not (snapshot/path).is_symlink()
commit=manifest['commit'];assert commit=='84f42f02aa872b01a77c6280695f077437fa2a07'
assert (stage/'SOURCE_COMMIT').read_text().strip()==manifest['previousApplicationCommit']
assert (stage/'AUTHORIZED_DISPOSABLE').is_file()
for name in ('native-linux.log','runtime-linux.log'):
 content=(location/'test-results'/name).read_text()
 assert ' passed' in content and ' failed' not in content and 'ERROR collecting' not in content,name
config=json.loads(Path('/etc/cms-ide-stage/cms.conf').read_text())
assert urlsplit(config['database']).path=='/cms_restore_21c7bd2d5bfortesting'
assert config['admin_listen_address']=='127.0.0.1' and config['admin_listen_port']==18889
assert config['core_services']['ResourceService'][0]==['127.0.0.1',31001]
pg=['runuser','-u','stagepguser','--','/usr/lib/postgresql/18/bin/psql','-X','-At','-h','/run/cms-ide-stage-pg','-p','15432','-d','ide_restore_d4008d5dedfortesting','-c']
query="SELECT count(*) FROM execution_jobs WHERE status IN ('QUEUED','PREPARING','COMPILING','RUNNING'); SELECT count(*) FROM debug_sessions WHERE status NOT IN ('FINISHED','STOPPED','FAILED','EXPIRED');"
assert subprocess.check_output(pg+[query],text=True).split()==['0','0'],'Execution active; defer deployment'
scripts=('cmsAdminWebServer','cmsContestWebServer','cmsOlympiadIDEService','cmsEvaluationService','cmsScoringService','cmsProxyService','cmsWorker','cmsResourceService')
def processes():
 result={}
 for process in psutil.process_iter(['pid','cmdline','username','create_time']):
  try:
   args=process.info['cmdline'] or []
   for name in scripts:
    if any(Path(arg).name==name for arg in args):
     key=name+':'+str(process.info['pid']);result[key]={'pid':process.info['pid'],'user':process.info['username'],'started':process.info['create_time'],'name':name}
  except (psutil.NoSuchProcess,psutil.AccessDenied):pass
 return result
before=processes();admins=[v for v in before.values() if v['name']=='cmsAdminWebServer'];assert len(admins)==1 and admins[0]['user']=='cmsstage'
backup=stage/'backups'/('file-history-'+commit[:12]+'-retry2');backup.mkdir(mode=0o700,parents=True,exist_ok=False)
for item in manifest['files']:
 name=item['path'];target=source/name;replacement=snapshot/name
 assert not target.is_symlink() and hashlib.sha256(replacement.read_bytes()).hexdigest()==item['sha256']
 if item['previousSha256'] is None:assert not target.exists()
 else:
  assert hashlib.sha256(target.read_bytes()).hexdigest()==item['previousSha256'],name
  saved=backup/name;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
(backup/'delta-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
(backup/'SOURCE_COMMIT').write_bytes((stage/'SOURCE_COMMIT').read_bytes())

def restart_admin():
 old_pids={value['pid'] for value in processes().values() if value['name']=='cmsAdminWebServer'}
 assert len(old_pids)==1
 for attempt in range(3):
  request={'__id':'file-history-deploy-'+str(attempt),'__method':'kill_service','__data':{'service':'AdminWebServer,0'}}
  with socket.create_connection(('127.0.0.1',31001),timeout=10) as connection:
   connection.settimeout(15);connection.sendall(json.dumps(request).encode()+b'\r\n')
   with connection.makefile('rb') as stream:data=stream.readline(10001)
   if not data.endswith(b'\r\n') or len(data)>10000:raise RuntimeError('Unexpected supervisor response')
   reply=json.loads(data)
   assert reply.get('__id')==request['__id']
  (backup/('admin-rpc-'+str(attempt)+'.json')).write_text(json.dumps(reply,indent=2))
  error=reply.get('__error')
  print('ADMIN_RESTART_RPC',json.dumps({'attempt':attempt,'error':str(error).splitlines()[0] if error else None}),flush=True)
  if error is None:return old_pids
  # Do not issue another quit if the first call already shut down Admin and lost its reply.
  current={value['pid'] for value in processes().values() if value['name']=='cmsAdminWebServer'}
  if (str(error).startswith('RPCError: Write failed.') and current==old_pids
      and all(psutil.pid_exists(pid) and psutil.Process(pid).status()!=psutil.STATUS_ZOMBIE for pid in old_pids)):
   time.sleep(0.5)
   continue
  health(old_pids)
  print('ADMIN_RESTART_CONFIRMED_BY_FRESH_PID_AND_HEALTH',flush=True)
  return old_pids
 raise RuntimeError('Native Admin RPC connection did not become ready')

def health(old_admin_pids):
 for attempt in range(30):
  runtime=subprocess.run(['curl','--noproxy','*','--silent','--fail','--max-time','3','http://127.0.0.1:18801/health/ready'],capture_output=True,text=True)
  admin=subprocess.run(['curl','--noproxy','*','--silent','--fail','--max-time','3','http://127.0.0.1:18889/login'],capture_output=True,text=True)
  active_admins=[value for value in processes().values() if value['name']=='cmsAdminWebServer']
  fresh=len(active_admins)==1 and active_admins[0]['user']=='cmsstage' and active_admins[0]['pid'] not in old_admin_pids and all(not psutil.pid_exists(pid) for pid in old_admin_pids)
  if fresh and runtime.returncode==0 and admin.returncode==0 and '<title>Admin</title>' in admin.stdout:return
  time.sleep(1)
 raise RuntimeError('Admin/runtime readiness failed')
try:
 for item in manifest['files']:
  target=source/item['path'];target.parent.mkdir(parents=True,exist_ok=True)
  temporary=target.with_name(target.name+'.history-deploy')
  assert not temporary.exists();temporary.write_bytes((snapshot/item['path']).read_bytes());temporary.chmod(0o644);temporary.replace(target)
 subprocess.run(['systemctl','restart','cms-ide-stage-runtime'],check=True)
 old_pids=restart_admin();health(old_pids)
 after=processes()
 assert all(after.get(key)==value for key,value in before.items() if value['name']!='cmsAdminWebServer'),'Unexpected native process replacement'
 fresh=[v for v in after.values() if v['name']=='cmsAdminWebServer'];assert len(fresh)==1 and fresh[0]['pid']!=admins[0]['pid'] and fresh[0]['user']=='cmsstage'
 (stage/'SOURCE_COMMIT').write_text(commit+'\n')
 (stage/'FILE_HISTORY_COMMIT').write_text(commit+'\n')
except Exception:
 for item in manifest['files']:
  target=source/item['path']
  if item['previousSha256'] is None:target.unlink(missing_ok=True)
  else:shutil.copy2(backup/item['path'],target)
 (stage/'SOURCE_COMMIT').write_bytes((backup/'SOURCE_COMMIT').read_bytes())
 subprocess.run(['systemctl','restart','cms-ide-stage-runtime'],check=True)
 old_pids=restart_admin();health(old_pids)
 raise
report={'status':'deployed','commit':commit,'backup':str(backup),'runtimeRestarted':True,'adminRestartedBy':'native ResourceService.kill_service(AdminWebServer,0)','otherNativeProcessesUnchanged':True,'before':before,'after':after,'databaseMigration':False}
(location/'deployment.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({key:value for key,value in report.items() if key not in ('before','after')}))
