"""Real PostgreSQL debug admission/transport isolation; adapter execution has separate Linux probes."""
import hashlib,json
from datetime import timedelta
from uuid import uuid4
import pytest
from fastapi.testclient import TestClient
from app.debug_models import DebugSession,DebugWorker
from app.models import utcnow
from conftest import APIClient


def fixture(api):
    wid,fid,cid,sid=map(lambda _:str(uuid4()),range(4))
    assert api.post('/api/v1/workspaces',json={'id':wid,'document':{'name':'Debug','nodes':{},'settings':{},'editorState':{}}}).status_code==201
    config={'kind':'configuration','id':cid,'name':'Debug','language':'python3','entryPoint':fid,'includedFiles':[fid],'compilerProfile':'release','mainClass':None,'defaultTestId':None}
    files=[{'id':fid,'path':'main.py','content':'a=2\nprint(a)\n'}]
    digest=hashlib.sha256(json.dumps({'files':files,'configuration':config},sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
    return {'submission':{'id':sid,'workspaceId':wid,'configuration':config,'files':files,'sourceHash':digest,'tests':[{'kind':'test','id':str(uuid4()),'name':'stdin','stdin':'','expectedStdout':None}]}}

def worker(api):
    with api.app.state.session_factory() as db:db.add(DebugWorker(id='control-plane-test-only',languages=['python3'],last_seen=utcnow()));db.commit()

def test_debug_requires_actual_worker_and_valid_capture(api):
    body=fixture(api)
    assert api.post('/api/v1/debug/sessions',json=body).status_code==503
    worker(api);body['submission']['sourceHash']='0'*64
    assert api.post('/api/v1/debug/sessions',json=body).status_code==422

def test_owner_budget_immutable_replay_and_private_tickets(api):
    worker(api);body=fixture(api);response=api.post('/api/v1/debug/sessions',json=body);assert response.status_code==201
    sid=response.json()['id'];path='/api/v1/debug/sessions/'+sid
    assert api.post('/api/v1/debug/sessions',json=body).json()['id']==sid
    other=APIClient(api.app);assert other.post('/api/v1/session').status_code==200
    assert other.get(path).status_code==404 and other.post(path+'/attach').status_code==404
    ticket=api.post(path+'/attach').json();assert len(ticket['token'])>=40
    assert 'token' not in api.get(path).text
    with api.app.state.session_factory() as db:
        row=db.get(DebugSession,sid);assert row.attach_hash==hashlib.sha256(ticket['token'].encode()).hexdigest()
    assert api.post('/api/v1/debug/sessions',json=fixture(api)).status_code==429
    assert api.post(path+'/stop').status_code==200
    assert api.post(path+'/attach').status_code==409

def test_dap_allowlist_source_binding_and_idempotent_commands(api):
    worker(api);body=fixture(api);sid=api.post('/api/v1/debug/sessions',json=body).json()['id'];path='/api/v1/debug/sessions/'+sid+'/messages'
    message={'seq':1,'type':'request','command':'setBreakpoints','arguments':{'source':{'path':'/etc/passwd'},'breakpoints':[{'line':1}]}}
    assert api.post(path,json=message).status_code==422
    message['command']='evaluate';assert api.post(path,json=message).status_code==422
    message['command']='launch';message['arguments']={'program':'/bin/sh','env':{'SECRET':'fake'}}
    assert api.post(path,json=message).status_code==200
    assert api.post(path,json=message).status_code==200
    message['command']='initialize';assert api.post(path,json=message).status_code==409
    assert api.get('/api/v1/debug/sessions/'+sid+'/events').json()['events']==[]

def test_websocket_origin_and_one_use_ticket(api,monkeypatch):
    monkeypatch.setenv('ALLOWED_ORIGINS','https://allowed.test');worker(api);sid=api.post('/api/v1/debug/sessions',json=fixture(api)).json()['id'];path='/api/v1/debug/sessions/'+sid
    token=api.post(path+'/attach').json()['token']
    with TestClient(api.app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect(path+'/dap',headers={'origin':'https://evil.test'}):pass
        with client.websocket_connect(path+'/dap',headers={'origin':'https://allowed.test'}) as ws:
            ws.send_json({'attachToken':token});assert ws.receive_json()['status']=='attached'
            ws.send_json({'seq':1,'type':'request','command':'initialize','arguments':{}})
            assert ws.receive_json()['type']=='transport'
        assert api.get(path).json()['status']=='STOPPED'
        with client.websocket_connect(path+'/dap',headers={'origin':'https://allowed.test'}) as ws:
            ws.send_json({'attachToken':token})
            with pytest.raises(Exception):ws.receive_json()

def test_session_deadline_fail_closed(api):
    worker(api);sid=api.post('/api/v1/debug/sessions',json=fixture(api)).json()['id'];path='/api/v1/debug/sessions/'+sid
    with api.app.state.session_factory() as db:row=db.get(DebugSession,sid);row.expires_at=utcnow()-timedelta(seconds=1);db.commit()
    assert api.get(path).json()['status']=='EXPIRED'
    assert api.post(path+'/attach').status_code==409


def test_expired_attach_does_not_cancel_unauthorized_session(api,monkeypatch):
    monkeypatch.setenv('ALLOWED_ORIGINS','https://allowed.test');worker(api);sid=api.post('/api/v1/debug/sessions',json=fixture(api)).json()['id'];path='/api/v1/debug/sessions/'+sid
    token=api.post(path+'/attach').json()['token']
    with api.app.state.session_factory() as db:row=db.get(DebugSession,sid);row.attach_expires=utcnow()-timedelta(seconds=1);db.commit()
    with TestClient(api.app) as client:
        with client.websocket_connect(path+'/dap',headers={'origin':'https://allowed.test'}) as ws:
            ws.send_json({'attachToken':token})
            with pytest.raises(Exception):ws.receive_json()
    assert api.get(path).json()['status']=='QUEUED'

from test_cms_identity import cms_api,call

def test_cms_debug_tickets_and_history_cannot_cross_task_or_participant(api,cms_api):
    worker(api);body=fixture(api);wid=str(uuid4())
    response=call(cms_api,'POST','/api/v1/workspaces',{'id':wid,'document':{'name':'CMS debug','nodes':{},'settings':{},'editorState':{}}});assert response.status_code==201
    body['submission']['workspaceId']=wid
    response=call(cms_api,'POST','/api/v1/debug/sessions',body);assert response.status_code==201,response.text
    path='/api/v1/debug/sessions/'+response.json()['id']
    assert call(cms_api,'GET',path,task='5').status_code==404
    assert call(cms_api,'POST',path+'/attach',task='5').status_code==404
    assert call(cms_api,'POST',path+'/attach',user='2').status_code==404
    assert call(cms_api,'POST',path+'/attach').status_code==200


def test_replayed_token_cannot_attach_while_original_socket_is_authorized(api,monkeypatch):
    monkeypatch.setenv('ALLOWED_ORIGINS','https://allowed.test');worker(api);sid=api.post('/api/v1/debug/sessions',json=fixture(api)).json()['id'];path='/api/v1/debug/sessions/'+sid
    token=api.post(path+'/attach').json()['token']
    with TestClient(api.app) as client:
        with client.websocket_connect(path+'/dap',headers={'origin':'https://allowed.test'}) as first:
            first.send_json({'attachToken':token});assert first.receive_json()['status']=='attached'
            with client.websocket_connect(path+'/dap',headers={'origin':'https://allowed.test'}) as second:
                second.send_json({'attachToken':token})
                with pytest.raises(Exception):second.receive_json()
            assert api.get(path).json()['status']=='QUEUED'
    assert api.get(path).json()['status']=='STOPPED'


@pytest.mark.parametrize('fault',['api-expiry','output-budget'])
def test_worker_final_state_survives_authoritative_expiry_and_output_failure(api,monkeypatch,fault):
    # Control-plane fault injection only: real PostgreSQL, no participant code executed here.
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2]))
    import worker.app.debug_main as controller
    worker(api);sid=api.post('/api/v1/debug/sessions',json=fixture(api)).json()['id'];token=str(uuid4());factory=api.app.state.session_factory
    with factory() as db:
        row=db.get(DebugSession,sid);row.status='RUNNING';row.lease_token=token
        if fault=='output-budget':row.output_bytes=1048576
        db.commit()
    class FaultAdapter:
        def __init__(self,*args):pass
        def run(self,receive):
            if fault=='output-budget':raise RuntimeError('output budget exhausted')
            with factory() as db:row=db.get(DebugSession,sid);row.status='EXPIRED';row.error='Authoritative timeout';db.commit()
            return 'STOPPED'
    monkeypatch.setattr(controller,'IsolatedDebugger',FaultAdapter)
    controller.run_session(factory,sid,token,600)
    with factory() as db:
        row=db.get(DebugSession,sid)
        assert row.status==('EXPIRED' if fault=='api-expiry' else 'FAILED')
        assert row.error==('Authoritative timeout' if fault=='api-expiry' else 'output budget exhausted')


def test_authenticated_handler_cancellation_waits_for_durable_cleanup(api,monkeypatch):
    # Block real DB cleanup long enough to cancel its awaiting ASGI handler.
    # The handler must finish that commit before its cancellation scope exits.
    import anyio,asyncio,threading
    from contextlib import contextmanager
    from fastapi import WebSocketDisconnect
    from types import SimpleNamespace
    from uuid import UUID
    monkeypatch.setenv('ALLOWED_ORIGINS','https://allowed.test');worker(api)
    sid=api.post('/api/v1/debug/sessions',json=fixture(api)).json()['id'];path='/api/v1/debug/sessions/'+sid
    token=api.post(path+'/attach').json()['token']
    endpoint=next(route.endpoint for route in api.app.routes if getattr(route,'path',None)=='/api/v1/debug/sessions/{sid}/dap')
    factory=api.app.state.session_factory;entered=threading.Event();release=threading.Event();committed=threading.Event();calls=0
    @contextmanager
    def delayed_factory():
        nonlocal calls
        calls+=1;cleanup=calls==2
        if cleanup:entered.set();assert release.wait(2)
        with factory() as db:yield db
        if cleanup:committed.set()
    monkeypatch.setattr(api.app.state,'session_factory',delayed_factory)
    async def cancelled_handler():
        class Socket:
            headers={'origin':'https://allowed.test'};url=SimpleNamespace(query='')
            initial=True
            async def accept(self):pass
            async def close(self,**kwargs):pass
            async def send_json(self,payload):pass
            async def receive_text(self):
                if self.initial:self.initial=False;return json.dumps({'attachToken':token})
                raise WebSocketDisconnect()
        task=asyncio.create_task(endpoint(Socket(),UUID(sid)))
        assert await anyio.to_thread.run_sync(entered.wait,1)
        threading.Timer(.2,release.set).start();task.cancel()
        try:await task
        except asyncio.CancelledError:pass
        assert committed.is_set(),'ASGI cancellation abandoned authenticated session cleanup'
    try:
        anyio.run(cancelled_handler)
    finally:
        release.set();committed.wait(2)
    with factory() as db:
        row=db.get(DebugSession,sid)
        assert row.status=='STOPPED' and row.cancelled is True
