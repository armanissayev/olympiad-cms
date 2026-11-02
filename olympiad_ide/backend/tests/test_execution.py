from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import uuid4
import pytest
from sqlalchemy import func, select
from app.execution_models import ExecutionJob, ExecutionSnapshot
from app.execution_schema import ExecutionSubmit, JobResult
from app.execution_service import claim, compare, emit, expire_leases, fenced_job, finish, transition
from app.models import utcnow
from app.service import APIError
from app.telemetry import digest
from conftest import APIClient
from test_persistence import document


def submission(api, language='cpp20', tests=1):
    workspace_id, doc = str(uuid4()), document()
    assert api.post('/api/v1/workspaces', json={'id': workspace_id, 'document': doc}).status_code == 201
    file_id = next(key for key, node in doc['nodes'].items() if node['type'] == 'file')
    suffix = 'py' if language == 'python3' else 'java' if language == 'java17' else 'cpp'
    config = {'kind': 'configuration', 'id': str(uuid4()), 'name': 'Test configuration', 'language': language, 'entryPoint': file_id,
        'includedFiles': [file_id], 'compilerProfile': 'release', 'mainClass': 'Main' if language == 'java17' else None, 'defaultTestId': None}
    files = [{'id': file_id, 'path': f'src/Main.{suffix}', 'content': 'unsynchronized source\n'}]
    body = {'id': str(uuid4()), 'workspaceId': workspace_id, 'configuration': config, 'files': files,
        'sourceHash': digest({'files': sorted(files, key=lambda f: f['id']), 'configuration': config}),
        'tests': [{'kind': 'test', 'id': str(uuid4()), 'name': f'Test {i}', 'stdin': '2 3\n', 'expectedStdout': '5\n'} for i in range(tests)]}
    return body


def send(api, body): return api.post('/api/v1/executions', json=body)


def test_snapshot_is_immutable_live_source_and_submission_is_idempotent(api):
    body = submission(api)
    result = send(api, body)
    assert result.status_code == 201, result.text
    assert result.json()['status'] == 'QUEUED'
    assert send(api, body).json() == result.json()
    workspace = api.get(f"/api/v1/workspaces/{body['workspaceId']}").json()
    assert workspace['revision'] == 1
    assert next(n for n in workspace['document']['nodes'].values() if n['type'] == 'file')['content'] != body['files'][0]['content']
    with api.app.state.session_factory() as db:
        snapshot = db.get(ExecutionSnapshot, result.json()['snapshotId'])
        assert snapshot.files == body['files']
        assert db.scalar(select(func.count()).select_from(ExecutionJob)) == 1
    changed = deepcopy(body); changed['tests'][0]['stdin'] = 'changed'
    assert send(api, changed).status_code == 409


@pytest.mark.parametrize('language', ['cpp17', 'cpp20', 'python3', 'java17'])
def test_all_allowlisted_language_manifests_are_admitted(api, language):
    body = submission(api, language)
    assert send(api, body).status_code == 201


@pytest.mark.parametrize('path', ['../escape.cpp', '/etc/passwd', 'src/../../x.cpp', 'a\\b.cpp', '__ide_build/main.cpp', 'a//b.cpp'])
def test_manifest_path_traversal_and_reserved_paths_are_rejected(api, path):
    body = submission(api); body['files'][0]['path'] = path
    assert send(api, body).status_code == 422


def test_hash_unknown_flags_entry_and_oversized_tests_rejected(api):
    body = submission(api)
    bad = deepcopy(body); bad['sourceHash'] = '0' * 64
    assert send(api, bad).status_code == 422
    bad = deepcopy(body); bad['configuration']['compilerProfile'] = '-fplugin=/evil.so'
    assert send(api, bad).status_code == 422
    bad = deepcopy(body); bad['configuration']['entryPoint'] = str(uuid4())
    assert send(api, bad).status_code == 422
    bad = deepcopy(body); bad['tests'][0]['stdin'] = 'x' * 262145
    assert send(api, bad).status_code == 422


def test_ownership_on_execution_snapshot_resources_stream_and_cancel(api):
    body = submission(api); result = send(api, body).json()
    other = APIClient(api.app); assert other.post('/api/v1/session').status_code == 200
    assert send(other, body).status_code == 404
    for path in (f"/executions/{result['id']}", f"/executions/{result['id']}/events", f"/executions/{result['id']}/events?stream=true", f"/workspaces/{body['workspaceId']}/executions", f"/workspaces/{body['workspaceId']}/execution-resources"):
        assert other.get('/api/v1' + path).status_code == 404
    assert other.post(f"/api/v1/executions/{result['id']}/cancel").status_code == 404


def test_resource_cas_duplicate_receipts_and_tombstones(api):
    body = submission(api)
    url = f"/api/v1/workspaces/{body['workspaceId']}/execution-resources"
    mutation = {'operationId': str(uuid4()), 'baseRevision': 0, 'value': body['tests'][0], 'deleted': False}
    first = api.post(url, json=mutation)
    assert first.status_code == 200, first.text
    assert first.json()['revision'] == 1
    assert api.post(url, json=mutation).json() == first.json()
    stale = deepcopy(mutation); stale['operationId'] = str(uuid4()); stale['value']['stdin'] = 'offline edit'
    response = api.post(url, json=stale)
    assert response.status_code == 409
    assert response.json()['error']['server']['value']['stdin'] == '2 3\n'
    stale['baseRevision'] = 1; stale['deleted'] = True
    assert api.post(url, json=stale).json()['revision'] == 2
    assert api.get(url).json()[0]['deleted'] is True


def test_bounded_admission_and_queued_cancellation(api):
    body = submission(api)
    for _ in range(3):
        body['id'] = str(uuid4()); assert send(api, body).status_code == 201
    body['id'] = str(uuid4()); assert send(api, body).status_code == 429
    history = api.get(f"/api/v1/workspaces/{body['workspaceId']}/executions").json()
    assert api.post(f"/api/v1/executions/{history[0]['id']}/cancel").json()['status'] == 'CANCELLED'
    assert send(api, body).status_code == 201


def test_concurrent_claims_serialize_owner_and_capacity(api):
    body = submission(api)
    for _ in range(3): body['id'] = str(uuid4()); assert send(api, body).status_code == 201
    factory = api.app.state.session_factory
    def reserve(worker):
        with factory() as db:
            job = claim(db, worker, 2); db.commit(); return job.id if job else None
    with ThreadPoolExecutor(max_workers=3) as threads:
        claimed = list(threads.map(reserve, ['a', 'b', 'c']))
    assert len([job for job in claimed if job]) == 1


def test_lease_expiry_fences_old_worker_and_never_reports_success(api):
    body = submission(api); assert send(api, body).status_code == 201
    with api.app.state.session_factory() as db:
        job = claim(db, 'worker', 1); token = job.lease_token; job.lease_expiration = utcnow() - timedelta(seconds=1); db.commit()
    with api.app.state.session_factory() as db:
        expire_leases(db); db.commit()
        job = db.get(ExecutionJob, body['id'])
        assert job.status == 'INFRASTRUCTURE_ERROR'
        assert 'unresolved' in job.result['error']
        with pytest.raises(APIError): fenced_job(db, body['id'], token)


def test_state_machine_result_validation_cancellation_race_and_ordered_sse(api):
    body = submission(api); assert send(api, body).status_code == 201
    with api.app.state.session_factory() as db:
        job = db.get(ExecutionJob, body['id'])
        with pytest.raises(APIError): transition(db, job, 'RUNNING')
        job = claim(db, 'worker', 1); token = job.lease_token; transition(db, job, 'COMPILING'); transition(db, job, 'RUNNING')
        with pytest.raises(APIError): finish(db, job, JobResult(status='FINISHED', compilationOutput='', toolchainVersion='test fixture', cases=[]).model_dump(mode='json'))
        emit(db, job, 'OUTPUT', stream='stdout', text='fixture output for control-plane test only'); db.commit()
    api.post(f"/api/v1/executions/{body['id']}/cancel")
    with api.app.state.session_factory() as db:
        job = fenced_job(db, body['id'], token)
        finish(db, job, JobResult(status='CANCELLED', compilationOutput='', toolchainVersion='unavailable', cases=[]).model_dump(mode='json')); db.commit()
    response = api.get(f"/api/v1/executions/{body['id']}/events?stream=true&after=2")
    assert response.status_code == 200
    assert 'id: 3' in response.text and 'id: 2\n' not in response.text
    assert 'CANCELLED' in response.text


@pytest.mark.parametrize('actual,expected,status', [('', '', 'Accepted'), ('a\r\n', 'a\n', 'Accepted'), ('5 \n', '5\n', 'Wrong Answer'), ('\n', '', 'Wrong Answer'), ('anything', None, 'Not Compared')])
def test_exact_custom_comparison_policy(actual, expected, status):
    assert compare('FINISHED', actual, expected) == status


@pytest.mark.parametrize('status', ['TIME_LIMIT_EXCEEDED', 'MEMORY_LIMIT_EXCEEDED', 'CANCELLED'])
def test_signalled_case_events_keep_nullable_exit_code(api, status):
    from app.execution_schema import CaseResult, JobEvent
    body = submission(api, 'python3'); assert send(api, body).status_code == 201
    case = CaseResult(testId=body['tests'][0]['id'], name='Signalled process', status=status,
        stdout='', stderr='', verdict='Not Executed', exitCode=None)
    with api.app.state.session_factory() as db:
        job = claim(db, 'contract-test', 1)
        transition(db, job, 'RUNNING')
        emit(db, job, 'CASE_RESULT', case=case)
        db.commit()
    response = api.get(f"/api/v1/executions/{body['id']}/events")
    assert response.status_code == 200, response.text
    event = next(e for e in response.json()['events'] if e['eventType'] == 'CASE_RESULT')
    assert 'exitCode' in event['case'] and event['case']['exitCode'] is None
    # Previously persisted events omitted nulls; they must remain readable.
    del event['case']['exitCode']
    assert JobEvent.model_validate(event).case.exitCode is None


def test_run_all_one_snapshot_and_output_result_metadata(api):
    body = submission(api, tests=3); response = send(api, body)
    assert response.status_code == 201
    assert len(response.json()['tests']) == 3
    with api.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionSnapshot)) == 1
        job = claim(db, 'worker', 1); transition(db, job, 'RUNNING')
        cases = [{'testId': t['id'], 'name': t['name'], 'status': 'FINISHED', 'stdout': '5\n', 'stderr': '', 'expectedStdout': None, 'verdict': 'Not Compared', 'exitCode': 0, 'cpuTime': None, 'wallTime': None, 'peakMemoryKiB': None} for t in body['tests']]
        finish(db, job, JobResult(status='FINISHED', compilationOutput='', toolchainVersion='explicit control-plane fixture, not a measured compiler', cases=cases).model_dump(mode='json')); db.commit()
    result = api.get(f"/api/v1/executions/{body['id']}").json()
    assert all(case['verdict'] == 'Accepted' for case in result['result']['cases'])
    assert all(case['peakMemoryKiB'] is None for case in result['result']['cases'])


def test_cms_worker_outage_blocks_new_runs_but_retains_committed_job_receipt(api):
    body = submission(api)
    api.app.state.auth_mode = 'cms'
    response = send(api, body)
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'worker_unavailable'
    with api.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(ExecutionJob)) == 0
        assert db.scalar(select(func.count()).select_from(ExecutionSnapshot)) == 0
    api.app.state.auth_mode = 'development'
    admitted = send(api, body).json()
    api.app.state.auth_mode = 'cms'
    assert send(api, body).json() == admitted
