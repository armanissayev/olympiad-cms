"""One-time additive debug rollout on the authorized disposable staging layout.

Run as root with --expected-database copied from the reviewed staging configuration.
Never starts the worker or writes DEBUG_SANDBOX_APPROVED. No credentials are emitted.
The original executed procedure is recorded in PHASE6_ARCHITECTURE.md; this retained
parameterized consolidation has been syntax-checked, not rerun on a second host.
"""
import argparse
import datetime
import os
from pathlib import Path
import pwd
import shutil
import subprocess
import tempfile
from urllib.parse import parse_qs, urlsplit

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--expected-database', required=True)
parser.add_argument('--source', type=Path, default=Path('/opt/cms-ide-stage/source/olympiad_ide'))
parser.add_argument('--install-packages', action='store_true', help='Install official distro gdb/python3-debugpy')
args = parser.parse_args()
os.umask(0o077)
assert os.geteuid() == 0, 'Root is required for provisioning only'
root = Path('/opt/cms-ide-stage')
conf = Path('/etc/cms-ide-stage')
assert (root / 'AUTHORIZED_DISPOSABLE').is_file(), 'Missing explicit disposable-staging marker'
source = args.source.resolve()
assert source.is_relative_to(root) and (source / 'backend/alembic.ini').is_file()
assert not list((source / 'backend/migrations').rglob('._*.py')), 'Remove archive metadata before migration'
envfile = conf / 'debug.env'
unitfile = Path('/etc/systemd/system/cms-ide-stage-debug.service')
assert not envfile.exists() and not unitfile.exists(), 'One-time setup refuses existing debug configuration'


def values(path):
    info = path.stat()
    assert info.st_uid == 0 and not info.st_mode & 0o077, 'Protected root-only environment required'
    return dict(line.split('=', 1) for line in path.read_text().splitlines() if line and not line.startswith('#'))


migration = values(conf / 'migration.env')['DATABASE_URL']
parsed = urlsplit(migration.replace('postgresql+psycopg:', 'postgresql:'))
database = parsed.path.lstrip('/')
assert database == args.expected_database, 'Reviewed staging database does not match configuration'
assert database == 'ide_linux_staging' or database.startswith('ide_restore_') and database.endswith('fortesting')
query = parse_qs(parsed.query)
assert parsed.hostname is None and parsed.username == 'idemigratestage' and parsed.password is None
assert query.get('host') == ['/run/cms-ide-stage-pg'] and query.get('port') == ['15432']
worker = values(conf / 'worker.env')
assert worker.get('WORKER_SANDBOX_APPROVED') == '1', 'Review mandatory26 Run prerequisites first'
worker_url = urlsplit(worker['DATABASE_URL'].replace('postgresql+psycopg:', 'postgresql:'))
assert worker_url.password is None and worker_url.username == 'ideworkerstage' and worker_url.path == parsed.path and worker_url.query == parsed.query

if args.install_packages:
    subprocess.run(['apt-get', 'install', '-y', '--no-install-recommends', 'gdb', 'python3-debugpy'], check=True)
for binary in ('gdb', 'javac', 'java'):
    assert shutil.which(binary), 'Missing distro tool: ' + binary
assert Path('/usr/lib/python3/dist-packages/debugpy/adapter/__main__.py').is_file()
helpers = Path('/usr/local/share/olympiad-debug')
helpers.mkdir(mode=0o755, exist_ok=True)
assert helpers.stat().st_uid == 0 and not helpers.stat().st_mode & 0o022
for name in ('stdin_wrapper.py', 'python_entry.py'):
    subprocess.run(['install', '-o', 'root', '-g', 'root', '-m', '0644', str(source / 'worker/adapters' / name), str(helpers / name)], check=True)
with tempfile.TemporaryDirectory(prefix='cms-debug-jdi-') as build:
    subprocess.run([str(Path(shutil.which('javac')).resolve()), '--release', '17', '--add-modules', 'jdk.jdi', '-d', build, str(source / 'worker/adapters/OlympiadJavaDAP.java')], check=True)
    for compiled in Path(build).glob('OlympiadJavaDAP*.class'):
        subprocess.run(['install', '-o', 'root', '-g', 'root', '-m', '0644', str(compiled), str(helpers / compiled.name)], check=True)

# A new, protected directory prevents accidental replacement of an earlier backup.
backup = Path('/var/lib/cms-ide-stage/backups') / ('debug-rollout-' + datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
backup.mkdir(mode=0o700)
owner = pwd.getpwnam('stagepguser')
os.chown(backup, owner.pw_uid, owner.pw_gid)
pg = Path('/usr/lib/postgresql/18/bin')
connection = ['-h', '/run/cms-ide-stage-pg', '-p', '15432']
subprocess.run(['runuser', '-u', 'stagepguser', '--', str(pg / 'pg_dump'), *connection, '-Fc', '-f', str(backup / 'ide-before-f6.dump'), database], check=True)
for command in (['upgrade', 'f6a001'], ['check']):
    subprocess.run(['runuser', '-u', 'idemigratestage', '--', 'env', 'DATABASE_URL=' + migration, str(root / 'runtime-venv/bin/alembic'), *command], cwd=source / 'backend', check=True)
grants = '''GRANT SELECT,INSERT,UPDATE,DELETE ON debug_sessions,debug_messages,debug_workers TO ideapistage;
GRANT SELECT ON debug_sessions,debug_messages,debug_workers TO ideworkerstage;
GRANT UPDATE(status,lease_token,heartbeat,cancelled,output_bytes,last_event,error) ON debug_sessions TO ideworkerstage;
GRANT INSERT ON debug_messages TO ideworkerstage;
GRANT INSERT,UPDATE ON debug_workers TO ideworkerstage;'''
subprocess.run(['runuser', '-u', 'stagepguser', '--', str(pg / 'psql'), '-X', '-v', 'ON_ERROR_STOP=1', *connection, database, '-c', grants], check=True)

# Production code path remains the reviewed live tree, even when probing a candidate.
live = root / 'source/olympiad_ide'
with envfile.open('x') as stream:
    stream.write('DATABASE_URL=' + worker['DATABASE_URL'] + '\nWORKER_SANDBOX_APPROVED=1\nDEBUG_BOX_ID=600\nPYTHONPATH=' + str(live / 'backend') + ':' + str(live) + '\n')
envfile.chmod(0o600)
with unitfile.open('x') as stream:
    stream.write('''[Unit]
Description=Restricted real DAP debug worker (separate from official CMS judging)
After=isolate.service cms-ide-stage-postgres.service
Requires=isolate.service cms-ide-stage-postgres.service
[Service]
User=ideworkerstage
Group=ideworkerstage
WorkingDirectory=/opt/cms-ide-stage/source/olympiad_ide
EnvironmentFile=/etc/cms-ide-stage/debug.env
Environment=PATH=/usr/local/bin:/usr/bin:/bin
ExecStart=/opt/cms-ide-stage/runtime-venv/bin/python -m worker.app.debug_main
PrivateNetwork=true
ProtectHome=true
Restart=on-failure
RestartSec=5
KillMode=control-group
UMask=0077
[Install]
WantedBy=multi-user.target
''')
unitfile.chmod(0o644)
subprocess.run(['systemctl', 'daemon-reload'], check=True)
subprocess.run(['dpkg-query', '-W', '-f=${Package} ${Version}\n', 'gdb', 'python3-debugpy', 'openjdk-17-jdk-headless'], check=True)
print('DEBUG_SETUP_READY: backup=' + str(backup) + '; approval absent; worker not started/enabled')
