# SPDX-License-Identifier: AGPL-3.0-or-later

"""Opt-in real-process native IDE/CWS/ResourceService control-plane smoke.

Run in the CMS environment against a NEW disposable database ending fortesting.
This intentionally does not start CMS judging or IDE sandbox workers. A private
IDE runtime, separately supervised, must already be ready. The test owns only
its LogService/ResourceService process groups and a test-local HTTPS ingress.
"""
import gevent.monkey
gevent.monkey.patch_all()  # noqa

import argparse
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

import gevent
from gevent.pywsgi import WSGIServer
import psutil
import requests

try:
    from .olympiadide_smoke_safety import database_unavailable, validate_outage_urls
except ImportError:
    from olympiadide_smoke_safety import database_unavailable, validate_outage_urls


def wait_for(predicate, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            value = predicate()
            if value:
                return value
        except (requests.RequestException, ConnectionError, OSError):
            pass
        gevent.sleep(0.2)
    raise AssertionError('Timed out waiting for a smoke-test condition')



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--bin-dir', required=True)
    parser.add_argument('--report', required=True)
    parser.add_argument('--tls-port', type=int, default=18443)
    parser.add_argument('--check-database-outages', action='store_true', help='Temporarily disable ONLY the two separate disposable fixture databases, then verify failure and recovery')
    parser.add_argument('--runtime-database-url-file', help='Private file containing the separate disposable runtime database URL; required for database outage checks')
    parser.add_argument('--check-runtime-outage', action='store_true', help='During handoff, wait for .runtime-down marker then verify runtime503 with CMS submission/fallback success')
    parser.add_argument('--browser-handoff-file', help='Write private disposable credentials here and wait for a .done marker (at most 10 minutes)')
    args = parser.parse_args()
    if args.check_runtime_outage and not args.browser_handoff_file:
        parser.error('--check-runtime-outage requires --browser-handoff-file')
    if args.check_database_outages != bool(args.runtime_database_url_file):
        parser.error('--check-database-outages and --runtime-database-url-file must be provided together')
    os.environ['CMS_CONFIG'] = str(Path(args.config).resolve())
    from cms import ServiceCoord, config
    from cms.db import Contest, Dataset, OlympiadIDEReceipt, Participation, SessionGen, Submission, Task, User, engine, init_db
    from cms.db.filecacher import DBBackend
    from cms.io import RemoteServiceClient
    from cmscommon.crypto import build_password
    from cmscommon.datetime import make_datetime

    outage_urls = validate_outage_urls(engine.url, Path(args.runtime_database_url_file).read_text().strip()) if args.check_database_outages else None
    if not engine.url.database.endswith('fortesting'):
        raise ValueError('Smoke database must be explicitly disposable and end with fortesting')
    allowed = {'LogService', 'ResourceService', 'ContestWebServer', 'OlympiadIDEService'}
    if set(coord.name for coord in config.async_config.core_services) != allowed:
        raise ValueError('Smoke core_services must contain ONLY LogService, ResourceService, ContestWebServer and OlympiadIDEService')
    if any(address.ip != '127.0.0.1' for address in config.async_config.core_services.values()):
        raise ValueError('Smoke services must all bind IPv4 loopback')
    if engine.table_names():
        raise ValueError("Smoke requires a new empty database; do not reuse a previous run")
    init_db()
    with SessionGen() as db:
        if db.query(Contest).count():
            raise ValueError('Refusing to reuse a populated smoke database')
        now = make_datetime()
        contest = Contest(name='ide-smoke', description='Disposable native IDE smoke', start=now-timedelta(minutes=5), stop=now+timedelta(hours=1),
                          languages=['C++17 / g++', 'Python 3 / CPython'], allow_password_authentication=True)
        password = secrets.token_urlsafe(24)
        user = User(username='ide-smoke-user', password=build_password(password), first_name='Native', last_name='Smoke')
        participation = Participation(contest=contest, user=user)
        task = Task(contest=contest, name='sum', title='Disposable Batch', submission_format=['main.%l'])
        dataset = Dataset(task=task, description='active', task_type='Batch', task_type_parameters=['alone', ['', ''], 'diff'],
                          score_type='Sum', score_type_parameters=100, time_limit=1.0, memory_limit=64 * 1024 * 1024)
        task.active_dataset = dataset
        db.add_all([contest, user, participation, task, dataset])
        db.commit()
        contest_id, task_id, participation_id = contest.id, task.id, participation.id

    report = {'kind': 'native-control-plane-smoke', 'cmsContestId': contest_id, 'checks': [],
              'realJudging': 'not run; no CMS Worker', 'realCustomExecution': 'not run; no approved Linux isolate worker'}
    directory = Path(tempfile.mkdtemp(prefix='cms-ide-smoke-'))
    report['artifacts'] = str(directory)
    cert, key = directory/'localhost.crt', directory/'localhost.key'
    subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', str(key), '-out', str(cert),
                    '-subj', '/CN=localhost', '-days', '1', '-addext', 'subjectAltName=DNS:localhost,IP:127.0.0.1'],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    key.chmod(0o600)
    env = dict(os.environ, PATH=str(Path(args.bin_dir).resolve())+os.pathsep+os.environ.get('PATH',''))
    processes, logs, rpc = [], [], None
    tls = None

    def start(name, *extra):
        log = (directory/(name+'.log')).open('wb')
        logs.append(log)
        proc = subprocess.Popen([str(Path(args.bin_dir)/name), *map(str, extra)], env=env,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        processes.append(proc)
        return proc

    def http_ok(url):
        with requests.Session() as client:
            client.trust_env = False
            return client.get(url, timeout=2).status_code == 200

    native = 'http://127.0.0.1:%d' % config.olympiad_ide_listen_port[0]
    cws = 'http://127.0.0.1:%d' % config.contest_listen_port[0]

    def ingress(environ, start_response):
        selected_shard = 1 if environ.get('HTTP_X_SMOKE_SHARD') == '1' and len(config.olympiad_ide_listen_port) > 1 else 0
        selected_native = 'http://127.0.0.1:%d' % config.olympiad_ide_listen_port[selected_shard]
        target = selected_native if environ['PATH_INFO'].startswith('/ide') else cws
        target += environ['PATH_INFO']
        if environ.get('QUERY_STRING'):
            target += '?'+environ['QUERY_STRING']
        size = int(environ.get('CONTENT_LENGTH') or 0)
        body = environ['wsgi.input'].read(size)
        headers = {name[5:].replace('_','-'): value for name,value in environ.items() if name.startswith('HTTP_') and name not in ('HTTP_HOST','HTTP_CONNECTION','HTTP_TRANSFER_ENCODING','HTTP_X_FORWARDED_FOR','HTTP_X_FORWARDED_PROTO','HTTP_X_SMOKE_SHARD')}
        headers.update({'X-Forwarded-For': environ['REMOTE_ADDR'], 'X-Forwarded-Proto': 'https', 'Host': environ.get('HTTP_HOST','localhost')})
        if environ.get('CONTENT_TYPE'):
            headers['Content-Type'] = environ['CONTENT_TYPE']
        with requests.Session() as client:
            client.trust_env = False
            response = client.request(environ['REQUEST_METHOD'], target, headers=headers, data=body, timeout=15, allow_redirects=False)
            output = []
            for name in response.raw.headers:
                if name.lower() not in ('connection','transfer-encoding','content-encoding','content-length'):
                    output.extend((name,value) for value in response.raw.headers.getlist(name))
            output.append(('Content-Length', str(len(response.content))))
            start_response('%d %s' % (response.status_code,response.reason), output)
            return [response.content]

    def native_pid(shard=0):
        found = []
        for proc in psutil.process_iter(['pid','cmdline']):
            try:
                command = proc.info['cmdline'] or []
                launcher = str(Path(args.bin_dir)/'cmsOlympiadIDEService')
                if launcher in command and command[command.index(launcher)+1:command.index(launcher)+2] == [str(shard)]:
                    found.append(proc.pid)
            except (psutil.NoSuchProcess,psutil.AccessDenied):
                pass
        if len(found) > 1:
            raise AssertionError('Duplicate native service processes')
        return found[0] if found else None

    try:
        start('cmsLogService', 0)
        start('cmsResourceService', 0, '-a', contest_id)
        wait_for(lambda: http_ok(native+'/ide/health/ready'))
        wait_for(lambda: http_ok(cws+'/'))
        first_pid = wait_for(native_pid)
        shard_pids={0:first_pid}
        for shard,port in enumerate(config.olympiad_ide_listen_port[1:],start=1):
            wait_for(lambda: http_ok('http://127.0.0.1:%d/ide/health/ready' % port))
            shard_pids[shard]=wait_for(lambda: native_pid(shard))
        assert len(set(shard_pids.values()))==len(shard_pids)
        report['shards']=len(shard_pids)
        report['checks'].append('ResourceService launched native IDE and CWS; HTTP readiness and singleton process recognition')
        rpc = RemoteServiceClient(ServiceCoord('ResourceService',0), auto_retry=0.2)
        rpc.connect()
        wait_for(lambda: rpc.connected)
        def resource_status():
            samples = rpc.get_resources().get(timeout=5)
            return samples[-1][1]['services'].get('OlympiadIDEService,0',{}).get('running') if samples else False
        wait_for(resource_status)
        report['checks'].append('ResourceService RPC reports native service running')
        tls = WSGIServer(('127.0.0.1',args.tls_port), ingress, certfile=str(cert), keyfile=str(key), log=None)
        tls.start()
        base = 'https://localhost:%d' % args.tls_port
        client = requests.Session()
        client.trust_env = False
        client.verify = str(cert)
        assert client.get(base+'/',timeout=10).status_code == 200
        csrf = client.cookies.get('_xsrf')
        assert csrf
        response = client.post(base+'/login', data={'username':'ide-smoke-user','password':password,'_xsrf':csrf}, timeout=10, allow_redirects=False)
        assert response.status_code == 302, response.text[:200]
        response = client.get(base+'/ide/api/context',timeout=10)
        assert response.status_code == 200, response.text[:200]
        context = response.json()
        assert context['identity']['participationId'] == str(participation_id)
        assert context['tasks'][0]['id'] == task_id
        report['checks'].append('CWS password login cookie authenticates native context through TLS; participant/task scope matches')
        assert client.get(base+'/ide/',timeout=10).status_code == 200
        headers = {'X-XSRFToken':context['csrfToken'],'X-Olympiad-Principal':context['identity']['principalId'],'X-Olympiad-Task':str(task_id)}
        runtime = base+'/ide/api/runtime/v1'
        response = client.post(runtime+'/session',headers=headers,timeout=10)
        assert response.status_code == 200,response.text[:200]
        assert response.json()['identityId'] == context['identity']['principalId']
        workspace_id,file_id = str(uuid4()),str(uuid4())
        source = 'int main() { return 0; }\n'
        document = {'name':'CMS smoke','settings':{},'editorState':{},'nodes':{file_id:{'id':file_id,'type':'file','parentId':None,'name':'main.cpp','content':source,'language':'cpp','documentRevision':1,'createdAt':make_datetime().isoformat()+'Z','updatedAt':make_datetime().isoformat()+'Z'}}}
        response = client.post(runtime+'/workspaces',headers=headers,json={'id':workspace_id,'document':document},timeout=10)
        assert response.status_code == 201,response.text[:200]
        response = client.get(runtime+'/workspaces/'+workspace_id,headers=headers,timeout=10)
        assert response.status_code == 200,response.text[:200]
        assert response.json()['document']['nodes'][file_id]['content'] == source
        wrong = dict(headers, **{'X-Olympiad-Principal':str(uuid4())})
        assert client.get(runtime+'/workspaces/'+workspace_id,headers=wrong,timeout=10).status_code == 409
        report['checks'].append('Authenticated private-runtime session/workspace write-read; account-switch scope rejected')
        receipts = []
        for language,filename,content in [('C++17 / g++','main.cpp',source),('Python 3 / CPython','main.py','print("Unicode Ω")\n')]:
            intent={'schemaVersion':1,'intentId':str(uuid4()),'taskId':task_id,'language':language,'workspaceId':workspace_id,'snapshotId':str(uuid4()),'telemetry':None,
                    'files':[{'filename':'main.%l','sourceFilename':filename,'fileId':file_id,'content':content}]}
            response=client.post(base+'/ide/api/submissions',headers=headers,json=intent,timeout=15)
            assert response.status_code == 201,response.text[:200]
            receipt=response.json()
            assert receipt['state']=='admitted'
            replay=client.post(base+'/ide/api/submissions',headers=headers,json=intent,timeout=15)
            assert replay.status_code==200 and replay.json()['submissionId']==receipt['submissionId'],replay.text[:200]
            if len(shard_pids)>1:
                cross=client.post(base+'/ide/api/submissions',headers=dict(headers,**{'X-Smoke-Shard':'1'}),json=intent,timeout=15)
                assert cross.status_code==200 and cross.json()['submissionId']==receipt['submissionId'],cross.text[:200]
            intent['files'][0]['content']+='changed'
            assert client.post(base+'/ide/api/submissions',headers=headers,json=intent,timeout=15).status_code==409
            receipts.append(receipt)
            with SessionGen() as db:
                record=db.query(OlympiadIDEReceipt).filter_by(intent_id=receipt['intentId']).one()
                assert record.submission.participation_id==participation_id
                assert len(record.submission.files)==1
                digest=record.submission.files['main.%l'].digest
                with DBBackend().get_file(digest) as stream:
                    assert stream.read()==content.encode('utf-8')
            response=client.get(base+'/ide/api/submissions/status/'+receipt['submissionId'],params={'taskId':task_id},headers=headers,timeout=10)
            assert response.status_code==200,response.text[:200]
        history=client.get(base+'/ide/api/submissions',params={'taskId':task_id},headers=headers,timeout=10)
        assert history.status_code==200 and history.json()['total']==2,history.text[:200]
        assert client.get(base+'/tasks/sum/submissions',timeout=10).status_code==200
        report['checks'].append('C++/Python official admission, immutable retries, changed-content rejection, exact CMS file bytes, native pending feedback/history and CWS visibility')
        try:
            rpc.kill_service(service='OlympiadIDEService,0').get(timeout=5)
        except Exception:
            pass  # Existing CMS quit may close the RPC socket before acknowledgement.
        wait_for(lambda: native_pid() not in (None,first_pid))
        wait_for(lambda: http_ok(native+'/ide/health/ready'))
        for receipt in receipts:
            response=client.get(base+'/ide/api/submissions/'+receipt['intentId'],headers=headers,timeout=10)
            assert response.status_code==200 and response.json()['submissionId']==receipt['submissionId']
        for shard,pid in shard_pids.items():
            if shard:
                assert native_pid(shard)==pid
        report['checks'].append('ResourceService restart produces new singleton PID and reconciles durable receipts; other shards remain unchanged')
        if len(shard_pids)>1:
            report['checks'].append('Distinct native HTTP/RPC shards start through ResourceService and return one receipt for cross-shard retries')
        with SessionGen() as db:
            db.query(Contest).filter_by(id=contest_id).one().stop=make_datetime()-timedelta(seconds=1)
            db.commit()
            assert db.query(Submission).count()==2
        for receipt in receipts:
            assert client.get(base+'/ide/api/submissions/'+receipt['intentId'],headers=headers,timeout=10).status_code==200
        report['checks'].append('Committed receipts remain accessible after contest deadline; duplicate intents consumed no extra submissions')
        assert client.post(base+'/logout',data={'_xsrf':context['csrfToken']},timeout=10,allow_redirects=False).status_code==302
        assert client.get(base+'/ide/api/context',timeout=10).status_code==401
        report['checks'].append('CWS logout revokes native browser access without development-cookie fallback')
        assert rpc.toggle_autorestart(service='OlympiadIDEService,0').get(timeout=5) is False
        try:
            rpc.kill_service(service='OlympiadIDEService,0').get(timeout=5)
        except Exception:
            pass
        wait_for(lambda: native_pid() is None)
        gevent.sleep(6)
        assert native_pid() is None
        assert client.get(base+'/',timeout=10).status_code==200
        report['checks'].append('Intentional stop is respected across restart interval; ordinary CWS fallback remains available')
        if args.browser_handoff_file or args.check_database_outages:
            with SessionGen() as db:
                db.query(Contest).filter_by(id=contest_id).one().stop=make_datetime()+timedelta(hours=1)
                db.commit()
            assert rpc.toggle_autorestart(service='OlympiadIDEService,0').get(timeout=5) is True
            wait_for(lambda: http_ok(native+'/ide/health/ready'))
        if args.check_database_outages:
            assert client.get(base+'/',timeout=10).status_code==200
            csrf=client.cookies.get('_xsrf')
            assert client.post(base+'/login',data={'username':'ide-smoke-user','password':password,'_xsrf':csrf},timeout=10,allow_redirects=False).status_code==302
            current=client.get(base+'/ide/api/context',timeout=10).json()
            outage_headers={'X-XSRFToken':current['csrfToken'],'X-Olympiad-Principal':current['identity']['principalId'],'X-Olympiad-Task':str(task_id)}
            def new_intent():
                return {'schemaVersion':1,'intentId':str(uuid4()),'taskId':task_id,'language':'C++17 / g++',
                        'workspaceId':str(uuid4()),'snapshotId':str(uuid4()),'telemetry':None,
                        'files':[{'filename':'main.%l','sourceFilename':'main.cpp','fileId':str(uuid4()),'content':'int main() { return 0; }\n'}]}
            pending_intent=new_intent()
            engine.dispose()
            with database_unavailable(outage_urls[0]):
                live=client.get(base+'/ide/health/live',timeout=10)
                ready=client.get(base+'/ide/health/ready',timeout=10)
                unavailable_context=client.get(base+'/ide/api/context',timeout=10)
                unavailable_admission=client.post(base+'/ide/api/submissions',headers=outage_headers,json=pending_intent,timeout=15)
                assert live.status_code==200 and ready.status_code==503
                assert unavailable_context.status_code in (500,503),unavailable_context.status_code
                assert unavailable_admission.status_code in (500,503),unavailable_admission.status_code
                report['cmsDatabaseOutage']={'live':live.status_code,'ready':ready.status_code,'context':unavailable_context.status_code,'official':unavailable_admission.status_code}
            engine.dispose()
            wait_for(lambda: http_ok(native+'/ide/health/ready'))
            assert client.get(base+'/ide/api/context',timeout=10).status_code==200
            for receipt in receipts:
                reconciled=client.get(base+'/ide/api/submissions/'+receipt['intentId'],headers=outage_headers,timeout=10)
                assert reconciled.status_code==200 and reconciled.json()['submissionId']==receipt['submissionId']
            assert client.get(base+'/ide/api/submissions/'+pending_intent['intentId'],headers=outage_headers,timeout=10).status_code==404
            admitted=client.post(base+'/ide/api/submissions',headers=outage_headers,json=pending_intent,timeout=15)
            assert admitted.status_code==201,admitted.text[:200]
            replay=client.post(base+'/ide/api/submissions',headers=outage_headers,json=pending_intent,timeout=15)
            assert replay.status_code==200 and replay.json()['submissionId']==admitted.json()['submissionId']
            # Upstream CMS does not pre-ping its SQLAlchemy pool. Record the
            # first stale-connection failure and require recovery before the
            # independent runtime-database fault, rather than conflating them.
            cws_recovery_statuses=[]
            def cws_recovered():
                status=client.get(base+'/tasks/sum/submissions',timeout=10).status_code
                cws_recovery_statuses.append(status)
                return status==200
            wait_for(cws_recovered,timeout=10)
            report['cmsDatabaseRecovery']={'cwsStatuses':cws_recovery_statuses,'failedIntentRetry':admitted.status_code,'sameIntentReplay':replay.status_code}
            report['checks'].append('Actual CMS database outage keeps liveness200, readiness503 and denies context/admission; recovery reconciles receipts and admits failed intent exactly once')
            runtime_origin=config.olympiad_ide_runtime_url.rstrip('/')
            with requests.Session() as internal:
                internal.trust_env=False
                with database_unavailable(outage_urls[1]):
                    ready=internal.get(runtime_origin+'/health/ready',timeout=10)
                    live=internal.get(runtime_origin+'/health/live',timeout=10)
                    unavailable_workspace=client.get(runtime+'/workspaces/'+workspace_id,headers=outage_headers,timeout=10)
                    assert ready.status_code==503 and live.status_code==200
                    assert unavailable_workspace.status_code==503,unavailable_workspace.text[:200]
                    assert client.get(base+'/ide/health/ready',timeout=10).status_code==200
                    assert client.get(base+'/ide/api/context',timeout=10).status_code==200
                    independent=client.post(base+'/ide/api/submissions',headers=outage_headers,json=new_intent(),timeout=15)
                    assert independent.status_code==201,independent.text[:200]
                    assert client.get(base+'/tasks/sum/submissions',timeout=10).status_code==200
                    report['runtimeDatabaseOutage']={'live':live.status_code,'ready':ready.status_code,'gateway':unavailable_workspace.status_code,'official':independent.status_code}
                wait_for(lambda: http_ok(runtime_origin+'/health/ready'))
            recovered=client.get(runtime+'/workspaces/'+workspace_id,headers=outage_headers,timeout=10)
            assert recovered.status_code==200,recovered.text[:200]
            assert recovered.json()['document']['nodes'][file_id]['content']==source
            with SessionGen() as db:
                assert db.query(Submission).count()==4
                assert db.query(OlympiadIDEReceipt).count()==4
            report['checks'].append('Actual IDE database outage returns runtime readiness/gateway503 while CMS readiness/context/CWS and official201 work; recovery preserves exact workspace and receipt bytes')
        report['status']='passed'
        if args.browser_handoff_file:
            handoff=Path(args.browser_handoff_file)
            handoff.write_text(json.dumps({'baseUrl':base,'username':'ide-smoke-user','password':password,'certificate':str(cert),
                                         'contestId':contest_id,'taskId':task_id,'contestName':'ide-smoke','installationId':config.olympiad_ide_installation_id,'config':args.config,'artifacts':str(directory)}))
            handoff.chmod(0o600)
            print('BROWSER_HANDOFF_READY '+str(handoff),flush=True)
            deadline=time.monotonic()+600
            outage_checked=False
            while time.monotonic()<deadline and not Path(str(handoff)+'.done').exists():
                if args.check_runtime_outage and not outage_checked and Path(str(handoff)+'.runtime-down').exists():
                    assert client.get(base+'/',timeout=10).status_code==200
                    csrf=client.cookies.get('_xsrf')
                    assert client.post(base+'/login',data={'username':'ide-smoke-user','password':password,'_xsrf':csrf},timeout=10,allow_redirects=False).status_code==302
                    current=client.get(base+'/ide/api/context',timeout=10)
                    assert current.status_code==200,current.text[:200]
                    current=current.json()
                    outage_headers={'X-XSRFToken':current['csrfToken'],'X-Olympiad-Principal':current['identity']['principalId'],'X-Olympiad-Task':str(task_id)}
                    unavailable=client.get(base+'/ide/api/runtime/v1/workspaces',headers=outage_headers,timeout=10)
                    assert unavailable.status_code==503,unavailable.text[:200]
                    new_intent={'schemaVersion':1,'intentId':str(uuid4()),'taskId':task_id,'language':'C++17 / g++',
                                'workspaceId':str(uuid4()),'snapshotId':str(uuid4()),'telemetry':None,
                                'files':[{'filename':'main.%l','sourceFilename':'main.cpp','fileId':str(uuid4()),'content':'int main() { return 0; }\n'}]}
                    admitted=client.post(base+'/ide/api/submissions',headers=outage_headers,json=new_intent,timeout=15)
                    assert admitted.status_code==201,admitted.text[:200]
                    assert admitted.json()['state']=='admitted'
                    assert client.get(base+'/tasks/sum/submissions',timeout=10).status_code==200
                    report['checks'].append('Actual private-runtime outage returns503 while native CMS context, official admission and CWS fallback remain available')
                    Path(str(handoff)+'.runtime-checked').write_text(json.dumps({'status':'passed','runtimeStatus':503,'officialStatus':201,'submissionId':admitted.json()['submissionId']}))
                    outage_checked=True
                gevent.sleep(0.5)
            if args.check_runtime_outage:
                assert outage_checked,'Runtime outage verification was requested but no completed .runtime-down check occurred'
    except Exception as error:
        report['status']='failed'
        report['error']=str(error)[:500]
        raise
    finally:
        if tls is not None:
            tls.stop()
        if rpc is not None:
            rpc.disconnect()
        for proc in reversed(processes):
            try:
                os.killpg(proc.pid,signal.SIGTERM)
            except ProcessLookupError:
                pass
        for proc in processes:
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid,signal.SIGKILL)
                proc.wait(timeout=3)
        for log in logs:
            log.close()
        report['cleanup']='Owned CMS process groups and test HTTPS listener stopped; disposable database retained for inspection.'
        Path(args.report).write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':
    main()
