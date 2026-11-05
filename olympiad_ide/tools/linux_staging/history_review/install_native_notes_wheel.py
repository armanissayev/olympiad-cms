"""Install the verified native package, preserving installed-file rollback and CMS ownership."""
import hashlib,importlib.metadata,json,os,shlex,shutil,socket,subprocess,sys,time,zipfile
from pathlib import Path
import psutil
stage=Path('/opt/cms-ide-stage');venv=stage/'cms-venv';source=stage/'source';location=stage/'verification/file-history-notes-505c1a4b401d'
assert os.geteuid()==0 and (stage/'SOURCE_COMMIT').read_text().strip()=='84f42f02aa872b01a77c6280695f077437fa2a07'
manifest=json.loads((stage/'verification/file-history-84f42f02aa87/delta-manifest.json').read_text())
overrides={row['path']:row for row in json.loads((location/'notes-manifest.json').read_text())['files']}
for row in manifest['files']:
 if row['path'] in overrides:row['sha256']=overrides[row['path']]['sha256']
distribution=importlib.metadata.distribution('cms')
records=[]
for member in distribution.files:
 original=Path(distribution.locate_file(member)).resolve();assert original.is_relative_to(venv),str(original)
 if original.is_file():records.append((original,original.relative_to(venv)))
assert len(records)>500
backup=stage/'backups/native-wheel-before-file-history-505c1a4b401d';backup.mkdir(mode=0o700,exist_ok=False)
for original,relative in records:
 target=backup/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,target)
(backup/'installed-files.json').write_text(json.dumps([str(relative) for _,relative in records]))
wheel_dir=location/'native-wheel';wheel_dir.mkdir(exist_ok=False)
with (location/'native-wheel-build.log').open('w') as output:
 subprocess.run([str(venv/'bin/pip'),'wheel','--no-index','--no-deps','--no-build-isolation','--wheel-dir',str(wheel_dir),str(source)],stdout=output,stderr=subprocess.STDOUT,check=True)
wheels=list(wheel_dir.glob('cms-1.5.1-*.whl'));assert len(wheels)==1;wheel=wheels[0]
with zipfile.ZipFile(wheel) as archive:
 for row in manifest['files']:
  if row['path'].startswith('cms/server/admin/'):
   assert hashlib.sha256(archive.read(row['path'])).hexdigest()==row['sha256'],row['path']

def admin_pids():
 output=[]
 for process in psutil.process_iter(['pid','cmdline','username']):
  try:
   if any(Path(arg).name=='cmsAdminWebServer' for arg in process.info['cmdline'] or []):
    assert process.info['username']=='cmsstage';output.append(process.info['pid'])
  except(psutil.NoSuchProcess,psutil.AccessDenied):pass
 return output

def restart_admin():
 old=set(admin_pids());assert len(old)==1
 for attempt in range(3):
  request={'__id':'native-wheel-history-'+str(attempt),'__method':'kill_service','__data':{'service':'AdminWebServer,0'}}
  with socket.create_connection(('127.0.0.1',31001),timeout=10) as conn:
   conn.settimeout(15);conn.sendall(json.dumps(request).encode()+b'\r\n')
   with conn.makefile('rb') as stream:reply=json.loads(stream.readline(10001))
  assert reply.get('__id')==request['__id']
  error=reply.get('__error');print('ADMIN_RPC',str(error).splitlines()[0] if error else 'acknowledged',flush=True)
  if error and str(error).startswith('RPCError: Write failed.') and set(admin_pids())==old:
   time.sleep(0.5);continue
  break
 else:raise RuntimeError('Cold native RPC did not connect')
 for _ in range(40):
  fresh=admin_pids()
  response=subprocess.run(['curl','--noproxy','*','--silent','--fail','--max-time','2','http://127.0.0.1:18889/login'],capture_output=True,text=True)
  if len(fresh)==1 and fresh[0] not in old and not any(psutil.pid_exists(pid) for pid in old) and response.returncode==0:return {'old':list(old),'fresh':fresh}
  time.sleep(0.5)
 raise RuntimeError('Native Admin did not become ready')
try:
 with (location/'native-wheel-install.log').open('w') as output:
  subprocess.run([str(venv/'bin/pip'),'install','--no-index','--no-deps','--force-reinstall',str(wheel)],stdout=output,stderr=subprocess.STDOUT,check=True)
 # Import exactly as the native console script resolves packages: outside the checkout.
 probe="import cms;from cms.server.admin.handlers import HANDLERS,idehistory;assert '/site-packages/' in cms.__file__;assert any('/api/(files)' in row[0] for row in HANDLERS);print('INSTALLED_NATIVE_HISTORY_ROUTES_OK',idehistory.__file__)"
 subprocess.run(['runuser','-u','cmsstage','--','env','CMS_CONFIG=/etc/cms-ide-stage/cms.conf',str(venv/'bin/python'),'-c',probe],cwd='/',check=True)
 pids=restart_admin()
 # The guest endpoint must be registered and require login, not silently remain a 404.
 response=subprocess.run(['curl','--noproxy','*','--silent','--show-error','--max-time','5','-o','/dev/null','-w','%{http_code}','http://127.0.0.1:18889/contest/1/ide-history/api/files?userId=352&taskId=1'],capture_output=True,text=True,check=True)
 assert response.stdout=='302',response.stdout
except Exception:
 current=importlib.metadata.distribution('cms');old={relative for _,relative in records}
 for member in current.files:
  target=Path(current.locate_file(member)).resolve();assert target.is_relative_to(venv)
  if target.is_file() and target.relative_to(venv) not in old:target.unlink()
 for _,relative in records:
  target=venv/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(backup/relative,target)
 restart_admin()
 raise
(stage/'SOURCE_COMMIT').write_text('505c1a4b401da9662775efa3020621dfca344349\n')
(stage/'FILE_HISTORY_COMMIT').write_text('505c1a4b401da9662775efa3020621dfca344349\n')
report={'status':'installed-native-package','wheel':str(wheel),'wheelSha256':hashlib.sha256(wheel.read_bytes()).hexdigest(),'oldInstalledBackup':str(backup),'adminPids':pids,'guestFilesStatus':302,'dependenciesChanged':False}
(location/'native-wheel-deployment.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
