import hashlib,importlib.metadata,json,subprocess
from pathlib import Path
import psutil
stage=Path('/opt/cms-ide-stage');core=stage/'verification/file-history-84f42f02aa87';notes=stage/'verification/file-history-notes-505c1a4b401d'
commit=(stage/'SOURCE_COMMIT').read_text().strip();assert commit=='505c1a4b401da9662775efa3020621dfca344349'
manifest=json.loads((core/'delta-manifest.json').read_text());updates={r['path']:r for r in json.loads((notes/'notes-manifest.json').read_text())['files']}
for row in manifest['files']:
 if row['path'] in updates:row['sha256']=updates[row['path']]['sha256']
for row in manifest['files']:assert hashlib.sha256((stage/'source'/row['path']).read_bytes()).hexdigest()==row['sha256'],row['path']
distribution=importlib.metadata.distribution('cms');native={}
for row in manifest['files']:
 if row['path'].startswith('cms/server/admin/'):
  actual=Path(distribution.locate_file(row['path']));sha=hashlib.sha256(actual.read_bytes()).hexdigest();assert sha==row['sha256'];native[row['path']]=sha
before=json.loads((core/'deployment.json').read_text())['before']
for key,value in before.items():
 if value['name']=='cmsAdminWebServer':continue
 p=psutil.Process(value['pid']);assert p.create_time()==value['started'] and p.username()==value['user'],key
units={}
for name in ('postgres','log','resource','judge','runtime','worker','debug','ranking','ingress'):
 unit='cms-ide-stage-'+name+'.service'
 lines=subprocess.check_output(['systemctl','show',unit,'-p','ActiveState','-p','UnitFileState','-p','MainPID'],text=True).splitlines();data=dict(line.split('=',1) for line in lines)
 assert data['ActiveState']=='active' and data['UnitFileState']=='enabled',unit;units[unit]=data
for name in ('worker','debug'):
 assert subprocess.check_output(['systemctl','show','cms-ide-stage-'+name,'-p','PrivateNetwork','--value'],text=True).strip()=='yes'
for name in ('cms-venv','runtime-venv'):subprocess.run([str(stage/name/'bin/pip'),'check'],check=True,capture_output=True)
cert=subprocess.check_output(['openssl','x509','-in','/etc/cms-ide-stage/public.crt','-noout','-dates','-checkip','54.206.171.67'],text=True)
assert subprocess.check_output(['systemctl','is-active','cms-ide-stage-acme-renew.timer'],text=True).strip()=='active'
tmux=subprocess.check_output(['runuser','-u','ubuntu','--','tmux','list-sessions'],text=True).strip()
public={}
for path in ('/','/ide/health/ready','/admin/login'):
 result=subprocess.run(['curl','--noproxy','*','--silent','--show-error','--max-time','15','-o','/dev/null','-w','%{http_code}','https://54.206.171.67'+path],capture_output=True,text=True,check=True);assert result.stdout=='200';public[path]=200
report={'status':'passed','applicationCommit':commit,'coreLinuxVerifiedCommit':'84f42f02aa872b01a77c6280695f077437fa2a07','nativePackageLocation':str(distribution.locate_file('cms')),'installedNativeFileHashes':native,'allSourceDeltaHashesMatched':True,'otherNativeProcessesUnchanged':True,'units':units,'executionWorkersPrivateNetwork':True,'separateEnvironmentPipChecks':'passed','certificate':cert,'renewalTimer':'active','tmux':tmux,'publicHttpsStatuses':public,'nativeWheel':json.loads((notes/'native-wheel-deployment.json').read_text()),'coreDeployment':json.loads((core/'deployment.json').read_text())}
print(json.dumps(report,indent=2))
