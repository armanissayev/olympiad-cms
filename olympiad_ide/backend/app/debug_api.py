"""Ownership checked DAP transport. No browser-supplied adapter commands/configuration."""
import asyncio,hashlib,json,os,secrets,time
import anyio
from datetime import timedelta
from uuid import UUID,uuid4
from fastapi import Depends,Query,WebSocket,WebSocketDisconnect
from pydantic import Field
from sqlalchemy import select,func,text
from .debug_models import DebugSession,DebugMessage,DebugWorker
from .models import utcnow,DevelopmentIdentity
from .service import APIError,owned_workspace
from .execution_schema import Strict,ExecutionSubmit

TERMINAL={'FINISHED','STOPPED','FAILED','EXPIRED'}
COMMANDS={'initialize','launch','setBreakpoints','configurationDone','threads','stackTrace','scopes','variables','continue','pause','next','stepIn','stepOut','disconnect'}

class DebugCreate(Strict):
    submission: ExecutionSubmit

class DAPMessage(Strict):
    seq:int=Field(ge=1,le=100000000,strict=True)
    type:str
    command:str
    arguments:dict=Field(default_factory=dict)

def owned(db,sid,owner,lock=False):
    q=select(DebugSession).where(DebugSession.id==str(sid),DebugSession.owner_id==owner)
    if lock:q=q.with_for_update()
    row=db.scalar(q)
    if not row:raise APIError(404,'debug_unavailable','Debug session unavailable')
    if row.status not in TERMINAL and (row.expires_at<=utcnow() or row.heartbeat and row.heartbeat<utcnow()-timedelta(seconds=15)):
        row.cancelled=True;row.status='EXPIRED';row.error='Debug session timed out; start a new session from its immutable source.'
    return row

def view(row):return {'id':row.id,'workspaceId':row.workspace_id,'status':row.status,'expiresAt':row.expires_at.isoformat(),'error':row.error,'sourceHash':row.snapshot['sourceHash'],'files':[{'id':f['id'],'path':f['path']} for f in row.snapshot['files']]}

def validate_message(row,body):
    if body.type!='request' or body.command not in COMMANDS:raise APIError(422,'dap_command_denied','Only breakpoint/control/inspection requests are permitted')
    a=body.arguments;c=body.command
    if len(json.dumps(a))>16384:raise APIError(413,'dap_too_large','Debugger message too large')
    if c in ('initialize','launch','configurationDone','disconnect','threads'):a={}
    elif c=='setBreakpoints':
        source=a.get('source',{});path=source.get('path','') if isinstance(source,dict) else ''
        if path not in ['/box/'+f['path'] for f in row.snapshot['files']]:raise APIError(422,'debug_source_denied','Breakpoints must reference captured workspace files')
        points=a.get('breakpoints',[])
        if not isinstance(points,list) or len(points)>100 or any(not isinstance(p,dict) or type(p.get('line'))!=int or not 1<=p['line']<=1000000 for p in points):raise APIError(422,'invalid_breakpoints','Invalid source breakpoints')
        a={'source':{'path':path},'breakpoints':[{'line':p['line']} for p in points]}
    else:
        key={'stackTrace':'threadId','scopes':'frameId','variables':'variablesReference'}.get(c,'threadId')
        if type(a.get(key))!=int or not 0<=a[key]<=2**53:raise APIError(422,'invalid_debug_reference','Invalid debugger reference')
        a={key:a[key]}
        if c=='variables':a['count']=100
    return {'seq':body.seq,'type':'request','command':c,'arguments':a}

def install_debug_routes(app,db_session,identity):
    @app.get('/api/v1/debug/capacity')
    def capacity(owner=Depends(identity),db=Depends(db_session)):
        rows=list(db.scalars(select(DebugWorker).where(DebugWorker.last_seen>utcnow()-timedelta(seconds=15))))
        return {'workers':len(rows),'languages':sorted({v for r in rows for v in r.languages})}
    @app.post('/api/v1/debug/sessions',status_code=201)
    def create(body:DebugCreate,owner=Depends(identity),db=Depends(db_session)):
        s=body.submission;owned_workspace(db,str(s.workspaceId),owner.id)
        db.scalar(select(DevelopmentIdentity).where(DevelopmentIdentity.id==owner.id).with_for_update())
        prior=db.get(DebugSession,str(s.id))
        data=s.model_dump(mode='json')
        if any(any(part.startswith('__debug_') for part in f['path'].split('/')) for f in data['files']):raise APIError(422,'debug_reserved_path','Debug artifact paths are reserved')
        try:
            for f in data['files']:f['content'].encode('utf-8')
        except UnicodeError:raise APIError(422,'invalid_source_encoding','Debug source must contain valid UTF-8')
        canonical={'files':sorted(data['files'],key=lambda f:f['id']),'configuration':data['configuration']}
        expected=hashlib.sha256(json.dumps(canonical,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()
        if expected!=s.sourceHash:raise APIError(422,'source_hash_mismatch','Captured source hash mismatch')
        if prior:
            if prior.owner_id!=owner.id or prior.snapshot!=data:raise APIError(409,'debug_intent_reused','Debug session identifier already used')
            return view(prior)
        db.execute(text('SELECT pg_advisory_xact_lock(70406001)'))
        if db.scalar(select(func.count()).select_from(DebugSession).where(DebugSession.created_at>utcnow()-timedelta(hours=1),DebugSession.owner_id==owner.id))>=20:raise APIError(429,'debug_hourly_quota','Hourly debug session limit reached')
        if db.scalar(select(func.count()).select_from(DebugSession).where(DebugSession.status.notin_(TERMINAL),DebugSession.expires_at>utcnow()))>=32:raise APIError(503,'debug_queue_full','Debug worker queue is full')
        workers=list(db.scalars(select(DebugWorker).where(DebugWorker.last_seen>utcnow()-timedelta(seconds=15))))
        if not any(s.configuration.language in w.languages for w in workers):raise APIError(503,'debug_worker_unavailable','No approved isolated debug worker supports this language')
        active=list(db.scalars(select(DebugSession).where(DebugSession.owner_id==owner.id,DebugSession.status.notin_(TERMINAL))))
        for row in active:owned(db,row.id,owner.id)
        if any(row.status not in TERMINAL for row in active):raise APIError(429,'debug_capacity','Stop the current debug session first')
        row=DebugSession(id=str(s.id),owner_id=owner.id,workspace_id=str(s.workspaceId),snapshot=data,status='QUEUED',expires_at=utcnow()+timedelta(seconds=300))
        db.add(row);db.commit();return view(row)
    @app.get('/api/v1/debug/sessions/{sid}')
    def get(sid:UUID,owner=Depends(identity),db=Depends(db_session)):
        row=owned(db,sid,owner.id);db.commit();return view(row)
    @app.post('/api/v1/debug/sessions/{sid}/stop')
    def stop(sid:UUID,owner=Depends(identity),db=Depends(db_session)):
        row=owned(db,sid,owner.id,True);row.cancelled=True
        if row.status=='QUEUED':row.status='STOPPED'
        db.commit();return view(row)
    @app.post('/api/v1/debug/sessions/{sid}/messages')
    def message(sid:UUID,body:DAPMessage,owner=Depends(identity),db=Depends(db_session)):
        row=owned(db,sid,owner.id,True)
        if row.status in TERMINAL:raise APIError(409,'debug_finished','Debug session has ended')
        payload=validate_message(row,body)
        old=db.scalar(select(DebugMessage).where(DebugMessage.session_id==row.id,DebugMessage.direction=='in',DebugMessage.sequence==body.seq))
        if old:
            if old.payload!=payload:raise APIError(409,'dap_sequence_reused','Message sequence already used')
            return {'accepted':body.seq}
        count=db.scalar(select(func.count()).select_from(DebugMessage).where(DebugMessage.session_id==row.id,DebugMessage.direction=='in'))
        if count>=1000:raise APIError(429,'debug_budget','Debug command budget exhausted')
        db.add(DebugMessage(id=str(uuid4()),session_id=row.id,direction='in',sequence=body.seq,payload=payload));db.commit();return {'accepted':body.seq}
    @app.get('/api/v1/debug/sessions/{sid}/events')
    def events(sid:UUID,after:int=Query(0,ge=0),owner=Depends(identity),db=Depends(db_session)):
        row=owned(db,sid,owner.id);rows=list(db.scalars(select(DebugMessage).where(DebugMessage.session_id==row.id,DebugMessage.direction=='out',DebugMessage.sequence>after).order_by(DebugMessage.sequence).limit(100)))
        result={'session':view(row),'events':[{'sequence':m.sequence,'message':m.payload} for m in rows],'nextAfter':rows[-1].sequence if rows else after};db.commit();return result

    @app.post('/api/v1/debug/sessions/{sid}/attach')
    def attach(sid:UUID,owner=Depends(identity),db=Depends(db_session)):
        row=owned(db,sid,owner.id,True)
        if row.status in TERMINAL:raise APIError(409,'debug_finished','Debug session has ended')
        token=secrets.token_urlsafe(32);row.attach_hash=hashlib.sha256(token.encode()).hexdigest();row.attach_expires=utcnow()+timedelta(seconds=30);db.commit()
        return {'token':token,'expiresIn':30}

    @app.websocket('/api/v1/debug/sessions/{sid}/dap')
    async def dap(ws:WebSocket,sid:UUID):
        origins=os.getenv('ALLOWED_ORIGINS','http://localhost:5173').split(',')
        if ws.headers.get('origin') not in origins or ws.url.query:
            await ws.close(code=1008);return
        await ws.accept();owner_id=None;cursor=0;authorized_until=0;rate=[]
        async def authorize(token):
            nonlocal owner_id,authorized_until
            if not isinstance(token,str) or len(token)>128:raise ValueError('Invalid attach token')
            def consume():
                with app.state.session_factory() as db:
                    row=db.scalar(select(DebugSession).where(DebugSession.id==str(sid)).with_for_update())
                    if not row or row.status in TERMINAL or row.expires_at<=utcnow() or not row.attach_expires or row.attach_expires<=utcnow() or not secrets.compare_digest(row.attach_hash or '',hashlib.sha256(token.encode()).hexdigest()):raise ValueError('Expired attach token')
                    if owner_id and row.owner_id!=owner_id:raise ValueError('Owner changed')
                    row.attach_hash=None;row.attach_expires=None;who=row.owner_id;db.commit();return who
            owner_id=await asyncio.to_thread(consume);authorized_until=time.monotonic()+30
        try:
            initial=await asyncio.wait_for(ws.receive_text(),5)
            if len(initial)>1024:raise ValueError('Invalid attach')
            payload=json.loads(initial)
            if not isinstance(payload,dict):raise ValueError('Invalid attach frame')
            await authorize(payload.get('attachToken'))
            await ws.send_json({'type':'transport','status':'attached'})
            while time.monotonic()<authorized_until:
                try:
                    raw=await asyncio.wait_for(ws.receive_text(),.15)
                except asyncio.TimeoutError:raw=None
                if raw:
                    if len(raw)>32768:raise ValueError('Message too large')
                    payload=json.loads(raw)
                    if 'attachToken' in payload:await authorize(payload['attachToken'])
                    else:
                        now=time.monotonic();rate=[t for t in rate if now-t<1]
                        if len(rate)>=20:raise ValueError('Debugger command rate exceeded')
                        rate.append(now);body=DAPMessage.model_validate(payload)
                        def enqueue():
                            with app.state.session_factory() as db:
                                row=owned(db,sid,owner_id,True)
                                if row.status in TERMINAL:raise ValueError('Session finished')
                                checked=validate_message(row,body)
                                old=db.scalar(select(DebugMessage).where(DebugMessage.session_id==str(sid),DebugMessage.direction=='in',DebugMessage.sequence==body.seq))
                                if old:
                                    if old.payload!=checked:raise ValueError('Sequence reused')
                                else:
                                    count=db.scalar(select(func.count()).select_from(DebugMessage).where(DebugMessage.session_id==str(sid),DebugMessage.direction=='in'))
                                    if count>=1000:raise ValueError('Debug command budget exhausted')
                                    db.add(DebugMessage(id=str(uuid4()),session_id=str(sid),direction='in',sequence=body.seq,payload=checked))
                                db.commit()
                        await asyncio.to_thread(enqueue)
                def collect():
                    with app.state.session_factory() as db:
                        row=owned(db,sid,owner_id);items=list(db.scalars(select(DebugMessage).where(DebugMessage.session_id==str(sid),DebugMessage.direction=='out',DebugMessage.sequence>cursor).order_by(DebugMessage.sequence).limit(100)))
                        result=view(row),[(m.sequence,m.payload) for m in items];db.commit();return result
                state,items=await asyncio.to_thread(collect)
                for seq,payload in items:await ws.send_json(payload);cursor=seq
                await ws.send_json({'type':'transport','session':state})
                if state['status'] in TERMINAL:return
            await ws.close(code=1008,reason='CMS authorization expired')
        except (ValueError,APIError,WebSocketDisconnect,asyncio.TimeoutError):
            try:await ws.close(code=1008,reason='Debug transport closed; verify CMS authentication')
            except RuntimeError:pass
        finally:
            if owner_id:
                def cancel_disconnected():
                    with app.state.session_factory() as db:
                        row=db.scalar(select(DebugSession).where(DebugSession.id==str(sid),DebugSession.owner_id==owner_id).with_for_update())
                        if row and row.status not in TERMINAL:
                            row.cancelled=True
                            if row.status=='QUEUED':row.status='STOPPED'
                        db.commit()
                # ASGI shutdown/client cancellation must not abandon an in-flight commit.
                # Shield both AnyIO cancellation scopes and direct asyncio Task.cancel().
                try:
                    with anyio.CancelScope(shield=True):
                        cleanup=asyncio.create_task(asyncio.to_thread(cancel_disconnected));interrupted=False
                        try:
                            while True:
                                try:await asyncio.shield(cleanup);break
                                except asyncio.CancelledError:
                                    if cleanup.cancelled():raise
                                    interrupted=True
                        finally:
                            if interrupted:raise asyncio.CancelledError
                except Exception:pass # Worker independently expires the fixed deadline/lease.
