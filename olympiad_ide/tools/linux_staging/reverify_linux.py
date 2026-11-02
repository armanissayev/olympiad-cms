"""Read-only preflight, then isolated test fixtures only. No application lifecycle changes."""
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
import json,os,pwd,subprocess,sys
root=Path('/opt/cms-ide-stage');config_path=Path('/etc/cms-ide-stage/cms-unit.conf')
assert os.geteuid()==0 and (root/'AUTHORIZED_DISPOSABLE').is_file()
assert config_path.is_file() and not config_path.is_symlink(), 'Unit config is mandatory; refuse CMS fallback'
config=json.loads(config_path.read_text());live=json.loads(Path('/etc/cms-ide-stage/cms.conf').read_text())
u=urlsplit(config['database']);assert u.path=='/cmside_linux_unitfortesting' and u.username=='cmsstage' and not u.hostname
assert config['database']!=live['database'];assert parse_qs(u.query)=={'host':['/run/cms-ide-stage-pg'],'port':['15432']}
assert pwd.getpwuid(config_path.stat().st_uid).pw_name=='cmsstage' and config_path.stat().st_mode&0o777==0o600
sample=json.loads((root/'source/config/cms.conf.sample').read_text())
expected={name:[['127.0.0.1',33000+index*20+shard] for shard in range(len(coords))] for index,(name,coords) in enumerate(sample['core_services'].items())}
assert config['core_services']==expected and config['other_services']=={'TestFileCacher':[['127.0.0.1',34501]]}
assert config['olympiad_ide_enabled'] is False
for key in ['temp_dir','log_dir','cache_dir','data_dir','run_dir']:
 p=Path(config[key]);assert p.is_relative_to('/var/lib/cms-ide-stage/unit-state') and p.is_dir()
pg=['runuser','-u','stagepguser','--','/usr/lib/postgresql/18/bin/psql','-X','-At','-h','/run/cms-ide-stage-pg','-p','15432','postgres','-c']
owner=subprocess.check_output(pg+["SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='cmside_linux_unitfortesting'"],text=True).strip();assert owner=='cmsstage'
common=['runuser','-u','cmsstage','--','env','CMS_CONFIG='+str(config_path),'PYTHONPATH='+str(root/'source'),str(root/'cms-venv/bin/python')]
subprocess.run(common+['-c',"from cms.db import engine; from cms import config; assert engine.url.database=='cmside_linux_unitfortesting'; assert engine.url.username=='cmsstage'; assert not config.olympiad_ide_enabled; print('CMS_UNIT_PREFLIGHT_OK: explicit config, exact isolated database, fixture coordinates')"],cwd='/var/lib/cms-ide-stage/unit-run',check=True)
with Path('/tmp/cms-participant-native-linux-final.log').open('w') as log:
 r=subprocess.run(common+['-m','pytest',str(root/'source/cmstestsuite/unit_tests'),'-q','--tb=short','-p','no:cacheprovider'],cwd='/var/lib/cms-ide-stage/unit-run',stdout=log,stderr=subprocess.STDOUT)
print('CMS_UNIT_EXIT',r.returncode,flush=True)
if r.returncode:sys.exit(r.returncode)
# Runtime tests create/drop only generated test_* schemas in the retained non-active IDE database.
env=dict(line.split('=',1) for line in Path('/etc/cms-ide-stage/migration.env').read_text().splitlines() if line and not line.startswith('#'))
active=urlsplit(env['DATABASE_URL'].replace('postgresql+psycopg:','postgresql:')).path
assert active!='/ide_linux_staging'
owner=subprocess.check_output(pg+["SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname='ide_linux_staging'"],text=True).strip();assert owner=='idemigratestage'
with Path('/tmp/cms-participant-runtime-linux-final.log').open('w') as log:
 r=subprocess.run(['runuser','-u','idemigratestage','--','env','TEST_DATABASE_URL=postgresql+psycopg://idemigratestage@/ide_linux_staging?host=/run/cms-ide-stage-pg&port=15432',str(root/'runtime-venv/bin/python'),'-m','pytest','-o','addopts=','-ra','--tb=short','-p','no:cacheprovider'],cwd=root/'source/olympiad_ide/backend',stdout=log,stderr=subprocess.STDOUT)
print('RUNTIME_UNIT_EXIT',r.returncode,flush=True)
sys.exit(r.returncode)
