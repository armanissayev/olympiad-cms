from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
from datetime import timedelta
from sqlalchemy import select, func
from alembic import command
from alembic.config import Config
from app.main import create_app
from app.models import utcnow
from app.telemetry import apply_event, canonical, digest, delete_expired, lock_owner, replay_at
from app.telemetry_models import TelemetryBatch, TelemetryEvent, TelemetrySession
from conftest import APIClient
from test_persistence import document


def setup_session(api):
    wid, sid, doc = str(uuid4()), str(uuid4()), document()
    fid = next(key for key, node in doc['nodes'].items() if node['type'] == 'file')
    doc['nodes'][fid]['content'] = 'A😀Ω\nsecond\r\n'
    assert api.post('/api/v1/workspaces', json={'id': wid, 'document': doc}).status_code == 201
    nodes = {key: {'id': key, 'parentId': n['parentId'], 'name': n['name'], 'type': n['type'],
                  'content': n.get('content'), 'revision': n.get('documentRevision', 0)} for key, n in doc['nodes'].items()}
    cp = checkpoint(sid, 0, nodes)
    body = {'id': sid, 'workspaceId': wid, 'startedAt': '2026-10-20T00:00:00.000Z', 'initial': cp}
    response = api.post('/api/v1/telemetry/sessions', json=body)
    assert response.status_code == 201, response.text
    return sid, wid, fid, nodes, body


def checkpoint(sid, sequence, nodes):
    return {'id': str(uuid4()), 'sessionId': sid, 'sequence': sequence, 'workspaceRevision': 1, 'nodes': deepcopy(nodes),
            'stateHash': digest(nodes), 'createdAt': '2026-10-20T00:00:00.000Z', 'reason': 'test'}


def event(sid, wid, fid, sequence=1, before=1, text='你好', offset=3, deleted=1):
    return {'schemaVersion': 1, 'eventId': str(uuid4()), 'sessionId': sid, 'workspaceId': wid, 'fileId': fid,
        'sequence': sequence, 'clientTimestamp': '2026-10-20T00:00:00.123Z', 'monotonicOffsetMs': sequence * 10.7,
        'eventType': 'TEXT_REPLACE', 'payload': {'transactionId': str(uuid4()), 'beforeRevision': before, 'afterRevision': before + 1,
        'changes': [{'offset': offset, 'deletedLength': deleted, 'insertedText': text, 'range': {
            'startLineNumber': 1, 'startColumn': offset + 1, 'endLineNumber': 1, 'endColumn': offset + deleted + 1}}],
        'inputEventId': None, 'origin': 'editor', 'eol': '\n'}}


def batch(sid, events, checkpoints=None):
    body = {'id': str(uuid4()), 'sessionId': sid, 'events': events, 'checkpoints': checkpoints or []}
    return {**body, 'digest': digest(body)}


def send(api, body): return api.post('/api/v1/telemetry/batches', json=body)
def status(api, sid): return api.get(f'/api/v1/telemetry/sessions/{sid}/status').json()


def test_unicode_utf16_replay_checkpoint_and_pagination(api):
    sid, wid, fid, nodes, creation = setup_session(api)
    first = event(sid, wid, fid)
    expected = apply_event(nodes, first)
    assert expected[fid]['content'] == 'A😀你好\nsecond\n'
    second = event(sid, wid, fid, 2, 2, 'X', 1, 2)
    expected = apply_event(expected, second)
    assert expected[fid]['content'] == 'AX你好\nsecond\n'
    response = send(api, batch(sid, [first, second], [checkpoint(sid, 2, expected)]))
    assert response.status_code == 200, response.text
    assert status(api, sid)['integrity'] == 'Complete'
    assert status(api, sid)['lastCheckpoint'] == 2
    page = api.get(f'/api/v1/telemetry/sessions/{sid}/events?pageSize=1').json()
    assert page['events'][0]['sequence'] == 1
    assert page['events'][0]['serverTimestamp']
    assert page['nextAfter'] == 1
    assert api.get(f'/api/v1/telemetry/sessions/{sid}/events?after=1').json()['events'][0]['sequence'] == 2
    checkpoints = api.get(f'/api/v1/telemetry/sessions/{sid}/checkpoints?pageSize=1').json()
    assert checkpoints['checkpoints'][0]['sequence'] == 0
    assert api.get(f"/api/v1/telemetry/sessions/{sid}/checkpoints?after={checkpoints['nextAfter']}").json()['checkpoints'][0]['sequence'] == 2
    assert api.post('/api/v1/telemetry/sessions', json=creation).status_code == 201
    with api.app.state.session_factory() as db:
        assert replay_at(db, db.get(TelemetrySession, sid), 1) == apply_event(nodes, first)


def test_lost_ack_duplicate_batch_event_and_restart(api):
    sid, wid, fid, nodes, _ = setup_session(api)
    first = event(sid, wid, fid)
    body = batch(sid, [first])
    ack = send(api, body)
    assert ack.status_code == 200, ack.text
    restarted = APIClient(create_app(api.app.state.engine))
    restarted.cookies = api.cookies
    assert send(restarted, body).json() == ack.json()
    assert send(restarted, batch(sid, [first])).status_code == 200
    with api.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(TelemetryEvent)) == 1
    altered = deepcopy(body); altered['events'][0]['payload']['changes'][0]['insertedText'] = 'different'
    altered['digest'] = digest({k: v for k, v in altered.items() if k != 'digest'})
    assert send(api, altered).status_code == 409


def test_missing_sequence_rolls_back_entire_batch_and_does_not_ack(api):
    sid, wid, fid, _, _ = setup_session(api)
    response = send(api, batch(sid, [event(sid, wid, fid), event(sid, wid, fid, 3, 2)]))
    assert response.status_code == 409, response.text
    assert 'Missing Events' in response.text
    assert status(api, sid)['lastSequence'] == 0
    assert status(api, sid)['gaps'] == 1
    with api.app.state.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(TelemetryEvent)) == 0
        assert db.scalar(select(func.count()).select_from(TelemetryBatch)) == 0
    assert send(api, batch(sid, [event(sid, wid, fid)])).status_code == 200


def test_revision_offset_and_checkpoint_faults_are_explicit(api):
    sid, wid, fid, nodes, _ = setup_session(api)
    response = send(api, batch(sid, [event(sid, wid, fid, before=7)]))
    assert response.status_code == 409
    assert status(api, sid)['integrity'] == 'Revision Mismatch'
    bad = event(sid, wid, fid, offset=999)
    assert send(api, batch(sid, [bad])).status_code == 409
    assert status(api, sid)['integrity'] == 'Invalid Event'
    first = event(sid, wid, fid)
    wrong = checkpoint(sid, 1, nodes)
    assert send(api, batch(sid, [first], [wrong])).status_code == 409
    assert status(api, sid)['integrity'] == 'Checkpoint Mismatch'
    assert status(api, sid)['lastSequence'] == 0


def test_owner_checks_on_every_telemetry_endpoint(api):
    sid, wid, fid, _, creation = setup_session(api)
    other = APIClient(api.app)
    assert other.post('/api/v1/session').status_code == 200
    for path in ('status', 'events', 'checkpoints'):
        assert other.get(f'/api/v1/telemetry/sessions/{sid}/{path}').status_code == 404
    assert send(other, batch(sid, [event(sid, wid, fid)])).status_code == 404
    assert other.post('/api/v1/telemetry/sessions', json=creation).status_code == 404
    assert other.post(f'/api/v1/telemetry/sessions/{sid}/close', json={'completedAt': None, 'lastSequence': 0, 'integrity': 'Complete'}).status_code == 404
    assert other.post(f'/api/v1/telemetry/batches/{uuid4()}/chunks', json={'sessionId': sid, 'digest': 'a' * 64, 'index': 0, 'total': 1, 'data': '{}'}).status_code == 404


def test_chunk_staging_survives_restart_and_retries(api):
    sid, wid, fid, _, _ = setup_session(api)
    body = batch(sid, [event(sid, wid, fid, text='x' * 300_000)])
    encoded = canonical({key: value for key, value in body.items() if key != 'digest'})
    parts = [encoded[i:i + 32_000] for i in range(0, len(encoded), 32_000)]
    url = f"/api/v1/telemetry/batches/{body['id']}/chunks"
    def chunk(index): return {'sessionId': sid, 'digest': body['digest'], 'index': index, 'total': len(parts), 'data': parts[index]}
    assert api.post(url, json=chunk(0)).json()['acknowledgement'] is None
    restarted = APIClient(create_app(api.app.state.engine)); restarted.cookies = api.cookies
    for i in range(len(parts)):
        response = restarted.post(url, json=chunk(i))
        assert response.status_code == 200, response.text
    ack = response.json()['acknowledgement']
    assert ack['lastSequence'] == 1
    assert api.post(url, json=chunk(0)).json()['acknowledgement'] == ack
    assert status(api, sid)['lastSequence'] == 1


def test_multicursor_undo_redo_and_historical_checkpoint_arriving_later(api):
    sid, wid, fid, nodes, _ = setup_session(api)
    first = event(sid, wid, fid)
    first['eventType'] = 'DOCUMENT_CHANGE'
    first['payload']['changes'].append({'offset': 0, 'deletedLength': 1, 'insertedText': 'Z', 'range': {'startLineNumber': 1, 'startColumn': 1, 'endLineNumber': 1, 'endColumn': 2}})
    intermediate = apply_event(nodes, first)
    second = event(sid, wid, fid, 2, 2, 'Ω', 3, 2); second['eventType'] = 'UNDO'
    third = event(sid, wid, fid, 3, 3, '你好', 3, 1); third['eventType'] = 'REDO'
    assert send(api, batch(sid, [first, second, third])).status_code == 200
    assert send(api, batch(sid, [], [checkpoint(sid, 1, intermediate)])).status_code == 200


def test_payload_validation_and_event_batch_limits(api, monkeypatch):
    sid, wid, fid, _, _ = setup_session(api)
    bad = event(sid, wid, fid); bad['payload']['password'] = 'not allowed'
    assert send(api, batch(sid, [bad])).status_code == 422
    bad = event(sid, wid, fid); bad['eventType'] = 'MADE_UP'
    assert send(api, batch(sid, [bad])).status_code == 422
    bad = event(sid, wid, fid); bad['clientTimestamp'] = 123
    assert send(api, batch(sid, [bad])).status_code == 422
    bad = event(sid, wid, fid); bad['clientTimestamp'] = '2026-10-20T00:00:00'
    assert send(api, batch(sid, [bad])).status_code == 422
    assert api.get(f'/api/v1/telemetry/sessions/{sid}/events?pageSize=501').status_code == 422
    monkeypatch.setenv('TELEMETRY_MAX_EVENT_BYTES', '10')
    assert send(api, batch(sid, [event(sid, wid, fid)])).status_code == 409
    assert status(api, sid)['lastSequence'] == 0


def test_retention_cascade_and_interrupted_close(api, monkeypatch):
    monkeypatch.setenv('TELEMETRY_RETENTION_DAYS', '3')
    sid, wid, fid, _, _ = setup_session(api)
    assert send(api, batch(sid, [event(sid, wid, fid)])).status_code == 200
    assert api.post(f'/api/v1/telemetry/sessions/{sid}/close', json={'completedAt': None, 'lastSequence': 2, 'integrity': 'Complete'}).status_code == 409
    assert api.post(f'/api/v1/telemetry/sessions/{sid}/close', json={'completedAt': None, 'lastSequence': 1, 'integrity': 'Recording Interrupted'}).status_code == 200
    assert status(api, sid)['integrity'] == 'Recording Interrupted'
    with api.app.state.session_factory() as db:
        assert delete_expired(db, utcnow() + timedelta(days=4)) == 1
        assert db.scalar(select(func.count()).select_from(TelemetryEvent)) == 0
        assert db.scalar(select(func.count()).select_from(TelemetryBatch)) == 0
    assert api.get(f'/api/v1/telemetry/sessions/{sid}/status').status_code == 404
    assert api.get(f'/api/v1/workspaces/{wid}').status_code == 200


def test_phase2_data_survives_migration(api):
    command.downgrade(Config('alembic.ini'), '9773627aa90c')
    wid, doc = str(uuid4()), document()
    assert api.post('/api/v1/workspaces', json={'id': wid, 'document': doc}).status_code == 201
    before = api.get(f'/api/v1/workspaces/{wid}').json()
    command.upgrade(Config('alembic.ini'), 'head')
    assert api.get(f'/api/v1/workspaces/{wid}').json() == before


def test_cursor_moved_is_navigation_not_a_structural_move(api):
    sid, wid, fid, _, _ = setup_session(api)
    navigation = event(sid, wid, fid)
    navigation['eventType'] = 'CURSOR_MOVED'
    navigation['payload'] = {'paneId': 'primary', 'lineNumber': 1, 'column': 3, 'source': 'keyboard'}
    assert send(api, batch(sid, [navigation])).status_code == 200
    assert status(api, sid)['integrity'] == 'Complete'


def test_lone_utf16_surrogate_is_preserved_in_replay_and_reads(api):
    import json
    sid, wid, fid, _, _ = setup_session(api)
    body = batch(sid, [event(sid, wid, fid, text='\ud800')])
    response = api.post('/api/v1/telemetry/batches', content=json.dumps(body, ensure_ascii=True), headers={'content-type': 'application/json'})
    assert response.status_code == 200, response.text
    read = api.get(f'/api/v1/telemetry/sessions/{sid}/events').json()
    assert read['events'][0]['payload']['changes'][0]['insertedText'] == '\ud800'


def test_telemetry_quota_lock_does_not_block_phase2_owner_foreign_keys(api):
    sid, wid, _, _, _ = setup_session(api)
    workspace = api.get(f'/api/v1/workspaces/{wid}').json()
    owner_id = api.post('/api/v1/session').json()['identityId']
    with api.app.state.session_factory() as db, ThreadPoolExecutor(max_workers=1) as executor:
        lock_owner(db, owner_id)
        operation = {'workspaceId': wid, 'operationId': str(uuid4()), 'baseRevision': workspace['revision'], 'document': workspace['document']}
        future = executor.submit(api.post, '/api/v1/sync/batches', json={'operations': [operation]})
        try:
            response = future.result(timeout=3)
            assert response.status_code == 200, response.text
        finally:
            db.rollback()  # Always release before waiting for executor cleanup, even on a failed assertion.


def test_existing_telemetry_session_cannot_be_replayed_under_another_workspace(api):
    sid, _, _, _, creation = setup_session(api)
    other = str(uuid4())
    assert api.post('/api/v1/workspaces', json={'id': other, 'document': document()}).status_code == 201
    changed = deepcopy(creation)
    changed['workspaceId'] = other
    assert api.post('/api/v1/telemetry/sessions', json=changed).status_code == 409
    assert api.post('/api/v1/telemetry/sessions', json=creation).json()['id'] == sid
