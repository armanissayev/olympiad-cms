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


FILE_TIMELINE='/api/v1/admin/telemetry/file-timeline'
FILE_REPLAY='/api/v1/admin/telemetry/file-replay'


def submitted_file_query(sid,wid,fid,nodes,sequence=2,**changes):
    from urllib.parse import urlencode
    values={'workspaceId':wid,'fileId':fid,'captureSessionId':sid,'captureSequence':sequence,
            'sha256':hashlib.sha256(nodes[fid]['content'].encode()).hexdigest(),
            'submittedAt':(utcnow()+timedelta(seconds=1)).isoformat()}
    values.update(changes)
    return urlencode(values)


def test_submitted_file_timeline_replay_authentication_query_binding_and_scope(cms_api):
    sid,wid,fid,initial,after,cp=recording(cms_api);query=submitted_file_query(sid,wid,fid,after)
    assert cms_api.get(FILE_TIMELINE+'?'+query).status_code==401
    assert call(cms_api,'GET',FILE_TIMELINE).status_code==401
    assertion=admin_token(FILE_TIMELINE,query.encode())
    assert cms_api.get(FILE_TIMELINE+'?'+query+'&intervalSeconds=10',headers={'Authorization':'Bearer '+assertion}).status_code==401
    assert cms_api.get(FILE_TIMELINE+'?'+query,headers={'Authorization':'Bearer '+assertion}).status_code==200
    assert cms_api.get(FILE_TIMELINE+'?'+query,headers={'Authorization':'Bearer '+assertion}).status_code==401
    for scope in ({'task':'5'},{'user':'2'},{'contest':'3'},{'participation':'5'}):
        assert admin_get(cms_api,FILE_TIMELINE,query,**scope).status_code==404
        assert admin_get(cms_api,FILE_REPLAY,query+'&sessionId='+sid+'&through=1',**scope).status_code==404
    assert admin_get(cms_api,FILE_TIMELINE,submitted_file_query(sid,str(uuid4()),fid,after)).status_code==404


def test_submitted_file_timeline_contains_only_relevant_intervals_and_immutable_capture(cms_api):
    sid,wid,fid,initial,after,cp=recording(cms_api)
    later=event(sid,wid,fid,3,before=2,text='AFTER_SUBMISSION',offset=0,deleted=1)
    assert call(cms_api,'POST','/api/v1/telemetry/batches',batch(sid,[later])).status_code==200
    query=submitted_file_query(sid,wid,fid,after)
    response=admin_get(cms_api,FILE_TIMELINE,query+'&intervalSeconds=5');assert response.status_code==200,response.text
    result=response.json()
    assert result['correlation']['state']=='matched'
    assert result['fileId']==fid and result['summary']['editCount']==1
    assert [point['kind'] for point in result['points']]==['initial','editing','submission']
    assert result['points'][-1]['sequence']==2
    assert result['periods'][-1]['lastOffsetMs']==2*10.7  # Later edits do not extend a submitted version's duration.
    replay=admin_get(cms_api,FILE_REPLAY,query+'&sessionId='+sid+'&through=2').json()
    assert replay['available'] and replay['content']==after[fid]['content']
    assert 'nodes' not in replay and replay['name']=='renamed.cpp'
    assert admin_get(cms_api,FILE_REPLAY,query+'&sessionId='+sid+'&through=3').status_code==422
    wrong=submitted_file_query(sid,wid,fid,after,sha256='0'*64)
    assert admin_get(cms_api,FILE_TIMELINE,wrong).json()['correlation']['state']=='mismatch'


def test_submitted_file_future_upload_or_reported_gap_never_claims_hash_match(cms_api):
    sid,wid,fid,initial,after,cp=recording(cms_api)
    query=submitted_file_query(sid,wid,fid,after,sequence=3)
    assert admin_get(cms_api,FILE_TIMELINE,query).json()['correlation']['state']=='unavailable'
    missing=admin_get(cms_api,FILE_REPLAY,query+'&sessionId='+sid+'&through=3').json()
    assert not missing['available'] and missing['content'] is None
    with cms_api.app.state.session_factory() as db:
        row=db.get(TelemetrySession,sid);row.integrity='Missing Events';row.detected_gaps=1;db.commit()
    complete_bytes=admin_get(cms_api,FILE_TIMELINE,submitted_file_query(sid,wid,fid,after)).json()
    assert complete_bytes['correlation']['state']=='unavailable'
    assert complete_bytes['correlation']['actualSha256']==hashlib.sha256(after[fid]['content'].encode()).hexdigest()
    assert complete_bytes['partial']


def test_submitted_file_separates_periods_and_cuts_older_prefix_at_first_late_upload(cms_api):
    from urllib.parse import parse_qs
    from datetime import datetime
    old,wid,fid,initial,after,cp=recording(cms_api);captured=str(uuid4())
    assert call(cms_api,'POST','/api/v1/telemetry/sessions',{'id':captured,'workspaceId':wid,
        'startedAt':'2026-10-20T01:00:00Z','initial':checkpoint(captured,0,after)}).status_code==201
    query=submitted_file_query(captured,wid,fid,after,sequence=0)
    cutoff=datetime.fromisoformat(parse_qs(query)['submittedAt'][0])
    with cms_api.app.state.session_factory() as db:
        first=db.query(TelemetryEvent).filter(TelemetryEvent.session_id==old,TelemetryEvent.sequence==1).one()
        second=db.query(TelemetryEvent).filter(TelemetryEvent.session_id==old,TelemetryEvent.sequence==2).one()
        first.server_timestamp=cutoff+timedelta(seconds=1);second.server_timestamp=cutoff-timedelta(seconds=1);db.commit()
    result=admin_get(cms_api,FILE_TIMELINE,query).json()
    assert [period['sessionId'] for period in result['periods']]==[old,captured]
    assert result['periods'][0]['through']==0 and result['partial']
    assert all(point['sequence']==0 for point in result['points'] if point['sessionId']==old)
    assert admin_get(cms_api,FILE_REPLAY,query+'&sessionId='+old+'&through=1').status_code==422
    assert admin_get(cms_api,FILE_REPLAY,query+'&sessionId='+old+'&through=0').json()['content']==initial[fid]['content']
    newest=str(uuid4())
    assert call(cms_api,'POST','/api/v1/telemetry/sessions',{'id':newest,'workspaceId':wid,
        'startedAt':'2026-10-20T02:00:00Z','initial':checkpoint(newest,0,after)}).status_code==201
    assert newest not in [period['sessionId'] for period in admin_get(cms_api,FILE_TIMELINE,query).json()['periods']]
    assert admin_get(cms_api,FILE_REPLAY,query+'&sessionId='+newest+'&through=0').status_code==404


def test_submitted_file_input_bounds_and_analysis_limits_are_explicit(cms_api,monkeypatch):
    sid,wid,fid,initial,after,cp=recording(cms_api);query=submitted_file_query(sid,wid,fid,after)
    for suffix in ('&intervalSeconds=0','&intervalSeconds=2','&intervalSeconds=31'):
        assert admin_get(cms_api,FILE_TIMELINE,query+suffix).status_code==422
    assert admin_get(cms_api,FILE_TIMELINE,submitted_file_query(sid,wid,fid,after,submittedAt='2026-11-05T00:00:00')).status_code==422
    assert admin_get(cms_api,FILE_TIMELINE,submitted_file_query(sid,wid,fid,after,sha256='not-a-hash')).status_code==422
    import app.admin_history as history
    monkeypatch.setattr(history,'MAX_HISTORY_PAYLOAD_BYTES',1)
    result=admin_get(cms_api,FILE_TIMELINE,query).json()
    assert result['partial'] and any('truncated' in notice for notice in result['notices'])
    assert result['points'][-1]['kind']=='submission'
    assert result['correlation']['state']=='matched'


def test_file_review_budget_prioritizes_actual_capture_before_older_sessions(cms_api,monkeypatch):
    old,wid,fid,initial,after,cp=recording(cms_api);captured=str(uuid4())
    assert call(cms_api,'POST','/api/v1/telemetry/sessions',{'id':captured,'workspaceId':wid,
        'startedAt':'2026-10-20T01:00:00Z','initial':checkpoint(captured,0,after)}).status_code==201
    actual=event(captured,wid,fid,1,before=2,text='CAPTURE',offset=0,deleted=1)
    final=apply_event(after,actual)
    assert call(cms_api,'POST','/api/v1/telemetry/batches',batch(captured,[actual])).status_code==200
    import app.admin_history as history
    monkeypatch.setattr(history,'MAX_HISTORY_EVENTS',1)
    result=admin_get(cms_api,FILE_TIMELINE,submitted_file_query(captured,wid,fid,final,sequence=1)).json()
    assert result['partial'] and result['correlation']['state']=='matched'
    captured_edits=[point for point in result['points'] if point['sessionId']==captured and point['kind']=='editing']
    assert len(captured_edits)==1 and captured_edits[0]['inserted']==7
    assert result['points'][-1]['kind']=='submission'


def test_file_replay_never_returns_other_workspace_source_and_detects_missing_prefix(cms_api):
    sid,wid,fid,initial,after,cp=recording(cms_api)
    other_fid=str(uuid4())
    other={**event(sid,wid,other_fid,3),'eventType':'FILE_CREATED','payload':{'node':{
        'id':other_fid,'parentId':None,'name':'other-private.cpp','type':'file',
        'content':'OTHER-FILE-PRIVATE-SOURCE','revision':1}}}
    assert call(cms_api,'POST','/api/v1/telemetry/batches',batch(sid,[other])).status_code==200
    query=submitted_file_query(sid,wid,fid,after,sequence=3)
    response=admin_get(cms_api,FILE_REPLAY,query+'&sessionId='+sid+'&through=3')
    result=response.json();assert 'OTHER-FILE-PRIVATE-SOURCE' not in response.text
    assert set(result)=={'fileId','content','name','sequence','requestedSequence','available','sha256','session','notices'}
    assert result['fileId']==fid and 'nodes' not in result
    with cms_api.app.state.session_factory() as db:
        db.execute(delete(TelemetryEvent).where(TelemetryEvent.session_id==sid,TelemetryEvent.sequence==1));db.commit()
    result=admin_get(cms_api,FILE_TIMELINE,query).json()
    assert result['partial'] and result['correlation']['state']=='unavailable'
    assert any('missing stored events' in notice for notice in result['notices'])


def test_malformed_stored_checkpoint_objects_are_disclosed_without_500(cms_api):
    sid,wid,fid,initial,after,cp=recording(cms_api)
    with cms_api.app.state.session_factory() as db:
        latest=db.get(TelemetryCheckpoint,cp['id']);latest.document_state=[];latest.envelope=[];db.commit()
    result=admin_get(cms_api,FILE_TIMELINE,submitted_file_query(sid,wid,fid,after))
    assert result.status_code==200,result.text
    assert result.json()['correlation']['state']=='unavailable'
    with cms_api.app.state.session_factory() as db:
        original=db.query(TelemetryCheckpoint).filter(TelemetryCheckpoint.session_id==sid,TelemetryCheckpoint.sequence==0).one()
        original.document_state=[];original.envelope=None;db.commit()
    result=admin_get(cms_api,FILE_REPLAY,submitted_file_query(sid,wid,fid,after)+'&sessionId='+sid+'&through=2')
    assert result.status_code==200,result.text
    assert not result.json()['available'] and result.json()['content'] is None
    assert any('No verified uploaded checkpoint' in notice for notice in result.json()['notices'])
