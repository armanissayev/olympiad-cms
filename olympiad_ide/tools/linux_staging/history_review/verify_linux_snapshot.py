"""Run both complete suites in a read-only source snapshot and isolated databases."""
import json,os,pwd,subprocess,sys
from pathlib import Path
from urllib.parse import parse_qs,urlsplit

assert os.geteuid()==0
stage=Path('/opt/cms-ide-stage')
source=Path(sys.argv[1]).resolve()
assert source.is_relative_to(stage/'verification') and source.is_dir()
assert (stage/'AUTHORIZED_DISPOSABLE').is_file()
unit_path=Path('/etc/cms-ide-stage/cms-unit.conf')
assert unit_path.is_file() and not unit_path.is_symlink()
assert pwd.getpwuid(unit_path.stat().st_uid).pw_name=='cmsstage' and unit_path.stat().st_mode&0o777==0o600
unit=json.loads(unit_path.read_text());live=json.loads(Path('/etc/cms-ide-stage/cms.conf').read_text())
u=urlsplit(unit['database'])
assert u.path=='/cmside_linux_unitfortesting' and u.username=='cmsstage' and not u.hostname
assert parse_qs(u.query)=={'host':['/run/cms-ide-stage-pg'],'port':['15432']}
assert unit['database']!=live['database'] and unit['olympiad_ide_enabled'] is False
for key in ('temp_dir','log_dir','cache_dir','data_dir','run_dir'):
 assert Path(unit[key]).is_relative_to('/var/lib/cms-ide-stage/unit-state') and Path(unit[key]).is_dir()
pg=['runuser','-u','stagepguser','--','/usr/lib/postgresql/18/bin/psql','-X','-At','-h','/run/cms-ide-stage-pg','-p','15432','postgres','-c']
for database,owner in [('cmside_linux_unitfortesting','cmsstage'),('ide_linux_staging','idemigratestage')]:
 actual=subprocess.check_output(pg+["SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='"+database+"'"],text=True).strip()
 assert actual==owner
active=dict(line.split('=',1) for line in Path('/etc/cms-ide-stage/migration.env').read_text().splitlines() if line and not line.startswith('#'))['DATABASE_URL']
assert urlsplit(active.replace('postgresql+psycopg:','postgresql:')).path!='/ide_linux_staging'
common=['runuser','-u','cmsstage','--','env','CMS_CONFIG='+str(unit_path),'PYTHONPATH='+str(source),str(stage/'cms-venv/bin/python')]
subprocess.run(common+['-c',"from cms.db import engine; from cms import config; import cms; assert engine.url.database=='cmside_linux_unitfortesting'; assert engine.url.username=='cmsstage'; assert not config.olympiad_ide_enabled; print('NATIVE_PREFLIGHT_OK',cms.__file__)"],cwd='/var/lib/cms-ide-stage/unit-run',check=True)
logs=source.parent/'test-results';logs.mkdir(exist_ok=True)
with (logs/'native-linux.log').open('w') as output:
 result=subprocess.run(common+['-m','pytest',str(source/'cmstestsuite/unit_tests'),'-q','--tb=short','-p','no:cacheprovider'],cwd='/var/lib/cms-ide-stage/unit-run',stdout=output,stderr=subprocess.STDOUT)
print('NATIVE_EXIT',result.returncode,flush=True)
if result.returncode:sys.exit(result.returncode)
with (logs/'runtime-linux.log').open('w') as output:
 result=subprocess.run(['runuser','-u','idemigratestage','--','env','TEST_DATABASE_URL=postgresql+psycopg://idemigratestage@/ide_linux_staging?host=/run/cms-ide-stage-pg&port=15432',str(stage/'runtime-venv/bin/python'),'-m','pytest','-o','addopts=','-ra','--tb=short','-p','no:cacheprovider'],cwd=source/'olympiad_ide/backend',stdout=output,stderr=subprocess.STDOUT)
print('RUNTIME_EXIT',result.returncode,flush=True)
sys.exit(result.returncode)
