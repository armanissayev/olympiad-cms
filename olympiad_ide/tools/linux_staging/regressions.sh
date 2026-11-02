#!/usr/bin/env bash
# Linux regressions against new, test-owned DB/schema and separate writable fixture paths.
set -euo pipefail
stage_root=/opt/cms-ide-stage
[ "$(id -u)" -eq 0 ]
[ -f "$stage_root/AUTHORIZED_DISPOSABLE" ]
# Generate a standalone destructive unit DB, never reuse the acceptance contest.
runuser -u stagepguser -- /usr/lib/postgresql/18/bin/createdb -h /run/cms-ide-stage-pg -p 15432 --owner=cmsstage cmside_linux_unitfortesting
install -d -o cmsstage -g cmsstage -m 0700 /var/lib/cms-ide-stage/unit-run /var/lib/cms-ide-stage/unit-state
python=/opt/cms-ide-stage/cms-venv/bin/python
"$python" - <<'PY'
import json,os,pwd
from pathlib import Path
config=json.loads(Path('/etc/cms-ide-stage/cms.conf').read_text())
config['database']='postgresql+psycopg2://cmsstage@/cmside_linux_unitfortesting?host=/run/cms-ide-stage-pg&port=15432'
config['olympiad_ide_listen_address']=['127.0.0.1'];config['olympiad_ide_listen_port']=[8891];config['olympiad_ide_runtime_url']='http://127.0.0.1:8801'
# Unit contracts expect original default coordinates plus a second CWS/Worker shard.
sample=json.loads(Path('/opt/cms-ide-stage/source/config/cms.conf.sample').read_text())
config['olympiad_ide_enabled']=False
config['core_services']={name:[['127.0.0.1',33000+index*20+shard] for shard in range(len(coordinates))] for index,(name,coordinates) in enumerate(sample['core_services'].items())}
config['other_services']={'TestFileCacher':[['127.0.0.1',34501]]}
owner=pwd.getpwnam('cmsstage')
for key in ['temp_dir','log_dir','cache_dir','data_dir','run_dir']:
 path=Path('/var/lib/cms-ide-stage/unit-state')/key;path.mkdir(mode=0o700);os.chown(path,owner.pw_uid,owner.pw_gid);config[key]=str(path)
path=Path('/etc/cms-ide-stage/unit.conf');assert not path.exists();path.write_text(json.dumps(config));os.chown(path,owner.pw_uid,owner.pw_gid);path.chmod(0o600)
PY
cd /var/lib/cms-ide-stage/unit-run
runuser -u cmsstage -- env CMS_CONFIG=/etc/cms-ide-stage/unit.conf PYTHONPATH="$stage_root/source" "$python" -m pytest "$stage_root/source/cmstestsuite/unit_tests" -q --tb=short > "$stage_root/logs/cms-linux-unit.log" 2>&1
cd "$stage_root/source/olympiad_ide/backend"
runuser -u idemigratestage -- env TEST_DATABASE_URL='postgresql+psycopg://idemigratestage@/ide_linux_staging?host=/run/cms-ide-stage-pg&port=15432' "$stage_root/runtime-venv/bin/python" -m pytest -q --tb=short > "$stage_root/logs/backend-linux-tests.log" 2>&1
cd "$stage_root/source/olympiad_ide/frontend"
npm ci > "$stage_root/logs/frontend-check.log" 2>&1
npm run typecheck >> "$stage_root/logs/frontend-check.log" 2>&1
npm run lint >> "$stage_root/logs/frontend-check.log" 2>&1
npm test >> "$stage_root/logs/frontend-check.log" 2>&1
npm run build >> "$stage_root/logs/frontend-check.log" 2>&1
