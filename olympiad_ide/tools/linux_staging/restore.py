"""One-shot Linux staging PostgreSQL restore rehearsal; requires quiesced task-owned sources."""
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile
import time
from uuid import NAMESPACE_URL, uuid4, uuid5
import psycopg2
from psycopg2 import sql

os.umask(0o077)
HOST, PORT, USER = '/run/cms-ide-stage-pg', 15432, 'stagepguser'
SOURCES = ('cmside_linux_fortesting', 'ide_linux_staging')
BIN = Path('/usr/lib/postgresql/18/bin')
ROOT = Path(tempfile.mkdtemp(prefix='restore-', dir='/var/lib/cms-ide-stage/backups'))
ENV = {k:v for k,v in os.environ.items() if not k.startswith('PG')}
EMPTY_PASSFILE=ROOT/'empty.pgpass'
EMPTY_PASSFILE.write_text(''); EMPTY_PASSFILE.chmod(0o600)
ENV.update(PGPASSFILE=str(EMPTY_PASSFILE), PGSERVICEFILE=str(EMPTY_PASSFILE), PGCONNECT_TIMEOUT='3')
BASE = ['-h', HOST, '-p', str(PORT), '-U', USER, '--no-password']


def connect(database, readonly=True):
    assert database in SOURCES or re.fullmatch(r'(?:cms|ide)_restore_[a-f0-9]{10}fortesting', database)
    conn = psycopg2.connect(host=HOST, port=PORT, user=USER, dbname=database, connect_timeout=3, passfile=str(EMPTY_PASSFILE))
    conn.set_session(isolation_level='REPEATABLE READ', readonly=readonly, autocommit=False)
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE 'UTC'")
        cur.execute("SELECT current_setting('unix_socket_directories'),current_setting('port')::int,current_database()")
        assert cur.fetchone() == (HOST, PORT, database)
    return conn


def command(name, args, report):
    full = [str(BIN/name)] + BASE + args
    started = time.monotonic()
    completed = subprocess.run(full, env=ENV, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
    (ROOT/(name+'-'+str(len(report['commands']))+'.stderr')).write_bytes(completed.stderr)
    report['commands'].append({'command':shlex.join(full), 'exitCode':completed.returncode, 'seconds':round(time.monotonic()-started,3)})
    if completed.returncode:
        raise RuntimeError(name+' failed; protected local diagnostic file retained')


def rows(cur, query, params=None):
    cur.execute(query, params)
    return cur.fetchall()


def inventory(conn):
    with conn.cursor() as cur:
        tables = [row[0] for row in rows(cur,"SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")]
        counts, fingerprints = {}, {}
        for table in tables:
            cur.execute(sql.SQL('SELECT row_to_json(t)::text FROM public.{} AS t ORDER BY row_to_json(t)::text COLLATE "C"').format(sql.Identifier(table)))
            digest, count = hashlib.sha256(), 0
            for batch in iter(lambda:cur.fetchmany(1000), []):
                for row in batch:
                    raw = row[0].encode('utf-8')
                    digest.update(len(raw).to_bytes(8,'big')); digest.update(raw)
                    count += 1
            counts[table], fingerprints[table] = count, digest.hexdigest()
        schema = {}
        schema['columns'] = rows(cur,"SELECT table_name,column_name,ordinal_position,data_type,udt_name,is_nullable,column_default,character_maximum_length,numeric_precision FROM information_schema.columns WHERE table_schema='public' ORDER BY table_name,ordinal_position")
        schema['constraints'] = rows(cur,"SELECT c.relname, k.conname, k.contype, pg_get_constraintdef(k.oid) FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname,k.conname")
        schema['indexes'] = rows(cur,"SELECT tablename,indexname,indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY tablename,indexname")
        sequences = [row[0] for row in rows(cur,"SELECT sequencename FROM pg_sequences WHERE schemaname='public' ORDER BY sequencename")]
        schema['sequences'] = []
        for sequence in sequences:
            values = rows(cur,sql.SQL('SELECT last_value,is_called FROM public.{}').format(sql.Identifier(sequence)))
            schema['sequences'].append((sequence,values))
        large_objects = {}
        for oid, in rows(cur,'SELECT oid FROM pg_largeobject_metadata ORDER BY oid'):
            raw = bytes(rows(cur,'SELECT lo_get(%s)',(oid,))[0][0])
            large_objects[oid] = (len(raw),hashlib.sha256(raw).hexdigest())
        version = rows(cur,'SELECT version_num FROM alembic_version ORDER BY version_num') if 'alembic_version' in tables else None
    return {'counts':counts,'fingerprints':fingerprints,'schema':schema,'largeObjects':large_objects,'version':version}


def cms_sources(conn):
    with conn.cursor() as cur:
        result = {}
        for receipt_id, manifest, submission_id in rows(cur,'SELECT id,source_manifest,submission_id FROM olympiad_ide_receipts ORDER BY id'):
            file_rows = rows(cur,'SELECT f.filename,f.digest,o.loid FROM files f JOIN fsobjects o ON o.digest=f.digest WHERE f.submission_id=%s ORDER BY f.filename',(submission_id,))
            assert len(file_rows) == len(manifest)
            for filename, digest, oid in file_rows:
                raw = bytes(rows(cur,'SELECT lo_get(%s)',(oid,))[0][0])
                expected = next(item for item in manifest if item['filename']==filename)
                assert hashlib.sha1(raw).hexdigest() == digest
                assert hashlib.sha256(raw).hexdigest() == expected['sha256'] and len(raw) == expected['size']
                result[(receipt_id,submission_id,filename)] = raw
        assert result, 'CMS source must contain actual receipts/source'
        return result


def ide_mappings(conn):
    with conn.cursor() as cur:
        principals = rows(cur,'SELECT id,installation_id,user_id,contest_id,participation_id FROM cms_principals ORDER BY id')
        for principal, installation, user, contest, participation in principals:
            expected = str(uuid5(NAMESPACE_URL,json.dumps([installation,str(user),str(contest),str(participation)],separators=(',',':'),ensure_ascii=True)))
            assert principal == expected
        mappings = rows(cur,'SELECT b.workspace_id,b.principal_id,b.task_id,w.owner_id,w.revision FROM cms_workspace_bindings b LEFT JOIN workspaces w ON w.id=b.workspace_id ORDER BY b.workspace_id')
        for workspace, principal, task, owner, revision in mappings:
            assert owner is None or principal == owner
            assert task.isdigit() and int(task)>0
        assert principals and mappings, 'IDE source must contain native identity/workspace bindings'
        return principals,mappings


report = {'kind':'linux-staging-postgresql-restore-rehearsal','host':HOST,'port':PORT,'status':'running','directory':str(ROOT),'databases':[],
          'postgresTools':'18.6 Ubuntu','crossDatabaseAtomicity':False,'sourceDataPrinted':False,'productionReadinessClaim':False}
try:
    for source in SOURCES:
        target = ('cms' if source.startswith('cms') else 'ide')+'_restore_'+uuid4().hex[:10]+'fortesting'
        item = {'source':source,'target':target,'commands':[]}
        report['databases'].append(item)
        source_conn = connect(source)
        try:
            with source_conn.cursor() as cur:
                assert not rows(cur,'SELECT 1 FROM pg_database WHERE datname=%s',(target,))
                snapshot = rows(cur,'SELECT pg_export_snapshot()')[0][0]
            before = inventory(source_conn)
            source_check = cms_sources(source_conn) if source.startswith('cms') else ide_mappings(source_conn)
            command('createdb',['--maintenance-db='+source,'--template=template0','--owner='+('cmsstage' if source.startswith('cms') else 'idemigratestage'),target],item)
            dump = ROOT/(source+'.dump')
            command('pg_dump',['--format=custom','--snapshot='+snapshot,'--file='+str(dump),source],item)
            dump.chmod(0o600)
            with connect(target) as empty:
                with empty.cursor() as cur:
                    assert rows(cur,"SELECT count(*) FROM pg_tables WHERE schemaname='public'")[0][0] == 0
                    assert rows(cur,'SELECT count(*) FROM pg_largeobject_metadata')[0][0] == 0
            command('pg_restore',['--exit-on-error','--single-transaction','--dbname='+target,str(dump)],item)
            restored_conn=connect(target)
            try:
                after = inventory(restored_conn)
                assert before == after, 'Restored table rows, schemas, sequence state or large objects differ'
                restored_check = cms_sources(restored_conn) if source.startswith('cms') else ide_mappings(restored_conn)
                assert source_check == restored_check, 'Exact source bytes or native mapping differs'
                item.update(status='passed',tableCounts=after['counts'],tablesCompared=len(after['counts']),
                    allRowFingerprintsEqual=True,columnsConstraintsIndexesSequencesEqual=True,
                    largeObjectsCompared=len(after['largeObjects']),largeObjectBytesEqual=True,
                    alembicVersions=[row[0] for row in after['version']] if after['version'] is not None else None,
                    cmsModelDumpVersion=45 if source.startswith('cms') else None,
                    cmsDatabaseVersionTable=False if source.startswith('cms') else None,
                    exactCMSFileBytesCompared=len(restored_check) if source.startswith('cms') else None,
                    principalMappingsCompared=len(restored_check[0]) if source=='ide_linux_staging' else None,
                    workspaceTaskMappingsCompared=len(restored_check[1]) if source=='ide_linux_staging' else None,
                    dumpBytes=dump.stat().st_size,dumpMode=oct(dump.stat().st_mode & 0o777),
                    dumpSHA256=hashlib.sha256(dump.read_bytes()).hexdigest())
            finally:
                restored_conn.rollback(); restored_conn.close()
        finally:
            source_conn.rollback(); source_conn.close()
    report['status']='passed'
    Path('/var/lib/cms-ide-stage/backups/latest-report-path').write_text(str(ROOT/'report.json')+'\n')
except Exception as error:
    report['status']='failed'; report['errorType']=type(error).__name__
    raise
finally:
    (ROOT/'report.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps({'status':report['status'],'report':str(ROOT/'report.json'),
                      'databases':[{'source':item['source'],'target':item['target'],'status':item.get('status','incomplete')} for item in report['databases']]}))
