#!/usr/bin/env bash
set -euo pipefail
stage_root=/opt/cms-ide-stage
install -d -m 0700 -o stagepguser -g stagepguser /var/lib/cms-ide-stage/postgres
[ ! -f /var/lib/cms-ide-stage/postgres/PG_VERSION ]
runuser -u stagepguser -- /usr/lib/postgresql/18/bin/initdb -D /var/lib/cms-ide-stage/postgres --auth-local=peer --auth-host=scram-sha-256 --no-locale --encoding=UTF8 > "$stage_root/logs/postgres-init.log"
cat >> /var/lib/cms-ide-stage/postgres/postgresql.conf <<'CONFIG'
listen_addresses = ''
port = 15432
unix_socket_directories = '/run/cms-ide-stage-pg'
max_connections = 80
shared_buffers = 128MB
CONFIG
cat > /etc/systemd/system/cms-ide-stage-postgres.service <<'UNIT'
[Unit]
Description=Disposable CMS IDE staging PostgreSQL
After=local-fs.target
[Service]
Type=simple
User=stagepguser
Group=stagepguser
RuntimeDirectory=cms-ide-stage-pg
RuntimeDirectoryMode=0755
ExecStart=/usr/lib/postgresql/18/bin/postgres -D /var/lib/cms-ide-stage/postgres
ExecStop=/usr/lib/postgresql/18/bin/pg_ctl -D /var/lib/cms-ide-stage/postgres -m fast -w stop
Restart=on-failure
TimeoutStopSec=30
UMask=0077
[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl start cms-ide-stage-postgres
for attempt in $(seq 1 20); do
 if runuser -u stagepguser -- /usr/lib/postgresql/18/bin/pg_isready -h /run/cms-ide-stage-pg -p 15432 >/dev/null; then break; fi
 sleep 1
done
runuser -u stagepguser -- /usr/lib/postgresql/18/bin/psql -X -v ON_ERROR_STOP=1 -h /run/cms-ide-stage-pg -p 15432 postgres <<'SQL'
CREATE ROLE cmsstage LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE idemigratestage LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE ideapistage LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE ideworkerstage LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE DATABASE cmside_linux_fortesting OWNER cmsstage;
CREATE DATABASE ide_linux_staging OWNER idemigratestage;
REVOKE ALL ON DATABASE cmside_linux_fortesting FROM PUBLIC;
REVOKE ALL ON DATABASE ide_linux_staging FROM PUBLIC;
GRANT CONNECT ON DATABASE cmside_linux_fortesting TO cmsstage;
GRANT CONNECT ON DATABASE ide_linux_staging TO idemigratestage,ideapistage,ideworkerstage;
SQL
printf '%s\n' 'STAGING_POSTGRES_READY_UNIX_SOCKET_ONLY'
