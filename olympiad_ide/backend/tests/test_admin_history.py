"""CMS admin-only, cross-device uploaded history and truthful checkpoint replay."""
import hashlib
import json
import time
from copy import deepcopy
from datetime import timedelta
from app.models import utcnow
from uuid import uuid4

import jwt
from sqlalchemy import delete

from app.cms_identity import principal_id
from app.main import create_app
from app.telemetry import apply_event
from app.telemetry_models import TelemetryCheckpoint, TelemetryEvent, TelemetrySession
from conftest import APIClient
from test_cms_identity import cms_api, call, token, KEY, INSTALLATION
from test_persistence import document
from test_telemetry import batch, checkpoint, event

BASE = '/api/v1/admin/telemetry/sessions'


def admin_token(path=BASE, query=b'', method='GET', user='1', contest='2', participation='3', task='4', **updates):
    now = int(time.time())
    claims = {'iss': INSTALLATION, 'aud': 'olympiad-ide-admin-history', 'scope': 'admin-history', 'sub': '99',
              'targetUser': user, 'contest': contest, 'participation': participation, 'task': task,
              'principal': principal_id(INSTALLATION, user, contest, participation), 'iat': now, 'nbf': now, 'exp': now + 30,
              'jti': str(uuid4()), 'method': method, 'path': path, 'query_sha256': hashlib.sha256(query).hexdigest(),
              'body_sha256': hashlib.sha256(b'').hexdigest()}
    claims.update(updates)
    return jwt.encode(claims, KEY, algorithm='HS256')


def admin_get(client, path=BASE, query='', **scope):
    return client.get(path + ('?' + query if query else ''), headers={'Authorization': 'Bearer ' + admin_token(path, query.encode(), **scope)})


def recording(client):
    wid, sid, doc = str(uuid4()), str(uuid4()), document()
    fid = next(key for key, node in doc['nodes'].items() if node['type'] == 'file')
    doc['nodes'][fid]['content'] = 'A😀Ω\nsecond\r\n'
    assert call(client, 'POST', '/api/v1/workspaces', {'id': wid, 'document': doc}).status_code == 201
    nodes = {key: {'id': key, 'parentId': n['parentId'], 'name': n['name'], 'type': n['type'],
                  'content': n.get('content'), 'revision': n.get('documentRevision', 0)} for key,n in doc['nodes'].items()}
    initial = checkpoint(sid,0,nodes)
    response=call(client,'POST','/api/v1/telemetry/sessions',{'id':sid,'workspaceId':wid,'startedAt':'2026-10-20T00:00:00.000Z','initial':initial})
    assert response.status_code==201,response.text
    first=event(sid,wid,fid); after=apply_event(nodes,first)
    second={**event(sid,wid,fid,2), 'eventType':'FILE_RENAMED','payload':{'name':'renamed.cpp'}}
    after=apply_event(after,second); cp=checkpoint(sid,2,after)
    response=call(client,'POST','/api/v1/telemetry/batches',batch(sid,[first,second],[cp]));assert response.status_code==200,response.text
    return sid,wid,fid,nodes,after,cp


def test_admin_history_requires_separate_cms_scope_and_rejects_spoofing(cms_api):
    sid,*_=recording(cms_api)
    assert cms_api.get(BASE,headers={'X-Role':'admin','X-Olympiad-Admin':'99'}).status_code==401
    assert cms_api.get(BASE,headers={'Authorization':'Bearer '+token(path=BASE,method='GET')}).status_code==401
    for path in ('events','checkpoints'):
        assert call(cms_api,'GET',f'/api/v1/telemetry/sessions/{sid}/{path}').status_code==403
    assert call(cms_api,'GET',f'/api/v1/telemetry/sessions/{sid}/status').status_code==200
    assert admin_get(cms_api).json()['sessions'][0]['id']==sid
    assertion=admin_token();headers={'Authorization':'Bearer '+assertion}
    assert cms_api.get(BASE,headers=headers).status_code==200
    assert cms_api.get(BASE,headers=headers).status_code==401
    assert cms_api.get('/api/v1/workspaces',headers={'Authorization':'Bearer '+admin_token('/api/v1/workspaces')}).status_code==401
    assert cms_api.post(BASE,headers={'Authorization':'Bearer '+admin_token(method='POST')}).status_code==401


def test_admin_history_reads_only_signed_installation_participant_contest_task(cms_api):
    sid,*_=recording(cms_api)
    for scope in ({'user':'2'},{'task':'5'},{'contest':'3'},{'participation':'5'}):
        assert admin_get(cms_api,**scope).json()['sessions']==[]
        assert admin_get(cms_api,f'{BASE}/{sid}/replay',**scope).status_code==404
    assert admin_get(cms_api,query='pageSize=201').status_code==422
    signed=admin_token(query=b'pageSize=1')
    assert cms_api.get(BASE+'?pageSize=2',headers={'Authorization':'Bearer '+signed}).status_code==401
    assert admin_get(cms_api,exp=int(time.time())-60).status_code==401
    assert admin_get(cms_api,principal=str(uuid4())).status_code==401


def test_server_history_uses_uploaded_initial_and_nearest_verified_checkpoint(cms_api):
    sid,wid,fid,initial,after,cp=recording(cms_api)
    zero=admin_get(cms_api,f'{BASE}/{sid}/replay').json();assert zero['nodes']==initial and zero['sequence']==0
    one=admin_get(cms_api,f'{BASE}/{sid}/replay',query='through=1').json()
    assert one['available'] and one['nodes'][fid]['content']=='A😀你好\nsecond\n'
    two=admin_get(cms_api,f'{BASE}/{sid}/replay',query='through=2').json()
    assert two['available'] and two['checkpointSequence']==2 and two['nodes']==after
    two['nodes'][fid]['content']='mutated by reader'
    assert admin_get(cms_api,f'{BASE}/{sid}/replay',query='through=2').json()['nodes']==after
    # A fresh administrator browser/session reads the stored record, not IndexedDB.
    fresh=APIClient(cms_api.app)
    assert admin_get(fresh,f'{BASE}/{sid}/replay',query='through=2').json()['nodes']==after
    partial=admin_get(cms_api,f'{BASE}/{sid}/replay',query='through=3').json()
    assert partial['sequence']==2 and 'not been uploaded' in ' '.join(partial['notices'])


def test_server_history_never_fabricates_missing_or_corrupt_events(cms_api):
    sid,wid,fid,initial,after,cp=recording(cms_api)
    with cms_api.app.state.session_factory() as db:
        db.execute(delete(TelemetryEvent).where(TelemetryEvent.session_id==sid,TelemetryEvent.sequence==1));db.commit()
    missing=admin_get(cms_api,f'{BASE}/{sid}/replay',query='through=1').json()
    assert not missing['available'] and missing['sequence']==0 and missing['nodes']==initial
    assert 'Missing event 1' in ' '.join(missing['notices'])
    later=admin_get(cms_api,f'{BASE}/{sid}/replay',query='through=2').json()
    assert later['nodes']==after and 'Earlier events are missing' in ' '.join(later['notices'])
    with cms_api.app.state.session_factory() as db:
        row=db.get(TelemetryCheckpoint,cp['id']);row.state_hash='0'*64;db.commit()
    corrupt=admin_get(cms_api,f'{BASE}/{sid}/replay',query='through=2').json()
    assert not corrupt['available'] and corrupt['sequence']==0 and corrupt['nodes']==initial
    assert 'Rejected inconsistent checkpoint' in ' '.join(corrupt['notices'])


def test_development_identity_cannot_access_admin_history(api):
    assert api.get(BASE).status_code==403


def test_reported_gaps_clear_active_identity_until_recorded_navigation(cms_api):
    sid,wid,fid,initial,after,cp=recording(cms_api)
    active={**event(sid,wid,fid,3),'eventType':'ACTIVE_FILE_CHANGED','payload':{'paneId':str(uuid4()),'previousFileId':None}}
    assert call(cms_api,'POST','/api/v1/telemetry/batches',batch(sid,[active])).status_code==200
    with cms_api.app.state.session_factory() as db:
        row=db.get(TelemetrySession,sid);row.detected_gaps=1;row.integrity='Missing Events';db.commit()
    before=admin_get(cms_api,f'{BASE}/{sid}/replay',query='through=2').json()
    assert before['activeFileId'] is None
    fresh=admin_get(cms_api,f'{BASE}/{sid}/replay',query='through=3').json()
    assert fresh['activeFileId']==fid and fresh['nodes']==after


def test_corrupt_later_source_event_never_mislabels_partial_nodes_as_checkpoint(cms_api):
    sid,wid,fid,initial,after,cp=recording(cms_api)
    third={**event(sid,wid,fid,3),'eventType':'FILE_RENAMED','payload':{'name':'third.cpp'}}
    fourth={**event(sid,wid,fid,4),'eventType':'FILE_RENAMED','payload':{'name':'fourth.cpp'}}
    assert call(cms_api,'POST','/api/v1/telemetry/batches',batch(sid,[third,fourth])).status_code==200
    with cms_api.app.state.session_factory() as db:
        row=db.get(TelemetryEvent,fourth['eventId']);bad=deepcopy(row.envelope);bad['fileId']=str(uuid4());row.envelope=bad;db.commit()
    result=admin_get(cms_api,f'{BASE}/{sid}/replay',query='through=4').json()
    assert not result['available'] and result['sequence']==2 and result['nodes']==after
    assert 'Cannot verify event 4' in ' '.join(result['notices'])


def test_expired_recordings_are_not_exposed_or_deleted_by_review(cms_api):
    sid,*_=recording(cms_api)
    with cms_api.app.state.session_factory() as db:
        row=db.get(TelemetrySession,sid);row.expires_at=utcnow()-timedelta(seconds=1);db.commit()
    assert admin_get(cms_api).json()['sessions']==[]
    assert admin_get(cms_api,f'{BASE}/{sid}/replay').status_code==404
    with cms_api.app.state.session_factory() as db:assert db.get(TelemetrySession,sid) is not None
