#!/usr/bin/env bash
set -euo pipefail
stage_root=/opt/cms-ide-stage
# Only the reviewed staging helper/suite can unlock this exact deployment.
[ -s "$stage_root/SANDBOX_REVIEW" ] # Created only after operator reviews the real suite output.
grep -q '26 passed, 7 deselected' "$stage_root/logs/linux-worker-mandatory.log"
if grep -q WORKER_SANDBOX_APPROVED /etc/cms-ide-stage/worker.env; then echo 'Approval already recorded; inspect before rerun'; exit 1; fi
printf '%s\n' 'WORKER_SANDBOX_APPROVED=1' >> /etc/cms-ide-stage/worker.env
cd "$stage_root/source/olympiad_ide/backend"
runuser -u idemigratestage -- env DATABASE_URL='postgresql+psycopg://idemigratestage@/ide_linux_staging?host=/run/cms-ide-stage-pg&port=15432' "$stage_root/runtime-venv/bin/alembic" upgrade head > "$stage_root/logs/ide-migrate.log" 2>&1
runuser -u idemigratestage -- env DATABASE_URL='postgresql+psycopg://idemigratestage@/ide_linux_staging?host=/run/cms-ide-stage-pg&port=15432' "$stage_root/runtime-venv/bin/alembic" check >> "$stage_root/logs/ide-migrate.log" 2>&1
runuser -u stagepguser -- /usr/lib/postgresql/18/bin/psql -X -v ON_ERROR_STOP=1 -h /run/cms-ide-stage-pg -p 15432 ide_linux_staging <<'SQL'
GRANT USAGE ON SCHEMA public TO ideapistage,ideworkerstage;
GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA public TO ideapistage;
GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA public TO ideapistage;
GRANT SELECT ON execution_snapshots TO ideworkerstage;
GRANT SELECT,UPDATE ON execution_jobs TO ideworkerstage;
GRANT SELECT,INSERT ON execution_events TO ideworkerstage;
GRANT SELECT,INSERT,UPDATE ON execution_workers TO ideworkerstage;
SQL
cd "$stage_root/source"
runuser -u cmsstage -- env CMS_CONFIG=/etc/cms-ide-stage/cms.conf "$stage_root/cms-venv/bin/python" "$stage_root/incoming/fixture.py" > "$stage_root/logs/fixture-create.log" 2>&1
runuser -u cmsstage -- env CMS_CONFIG=/etc/cms-ide-stage/cms.conf "$stage_root/cms-venv/bin/cmsOlympiadIDEMigrate" --dry-run > "$stage_root/logs/cms-migrate.log" 2>&1
systemctl start cms-ide-stage-runtime.service cms-ide-stage-ranking.service cms-ide-stage-log.service
systemctl start cms-ide-stage-resource.service cms-ide-stage-worker.service
runuser -u cmsingressstage -- /usr/sbin/nginx -t -c /etc/cms-ide-stage/nginx.conf
systemctl start cms-ide-stage-ingress.service
systemctl is-active cms-ide-stage-runtime cms-ide-stage-ranking cms-ide-stage-log cms-ide-stage-resource cms-ide-stage-worker cms-ide-stage-ingress
cat "$stage_root/logs/fixture-create.log"
