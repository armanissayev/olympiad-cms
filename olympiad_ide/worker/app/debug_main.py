"""Dedicated debug controller: bounded DB protocol, no HTTP/CMS keys or host execution."""
import json,logging,os,socket,threading,time
from datetime import timedelta
from uuid import uuid4
from sqlalchemy import select
from app.database import make_engine,session_factory
from app.debug_models import DebugSession,DebugMessage,DebugWorker
from app.models import utcnow
from .debugger import IsolatedDebugger
from .sandbox import Sandbox,SandboxUnavailable

log=logging.getLogger('olympiad.debug')

def run_session(factory,sid,token,box_id):
    cursor=0;halted=threading.Event();done=threading.Event()
    def heartbeat():
        while not done.wait(1):
            try:
                with factory() as db:
                    row=db.get(DebugSession,sid)
                    if row.lease_token!=token or row.cancelled or row.expires_at<=utcnow():halted.set();return
                    row.heartbeat=utcnow();db.commit()
            except Exception:halted.set();return
    def emit(message):
        with factory() as db:
            row=db.scalar(select(DebugSession).where(DebugSession.id==sid).with_for_update())
            if row.lease_token!=token:raise RuntimeError('Debug lease fenced')
            size=len(json.dumps(message).encode());row.output_bytes+=size
            if row.output_bytes>1048576 or row.last_event>=5000:raise RuntimeError('Debug output budget exhausted')
            row.last_event+=1;db.add(DebugMessage(id=str(uuid4()),session_id=sid,direction='out',sequence=row.last_event,payload=message));db.commit()
    def receive():
        nonlocal cursor
        with factory() as db:
            rows=list(db.scalars(select(DebugMessage).where(DebugMessage.session_id==sid,DebugMessage.direction=='in',DebugMessage.sequence>cursor).order_by(DebugMessage.sequence).limit(20)))
            if rows:cursor=rows[-1].sequence
            return [row.payload for row in rows]
    thread=threading.Thread(target=heartbeat,daemon=True);thread.start();status='FAILED';error=None
    try:
        with factory() as db:snapshot=db.get(DebugSession,sid).snapshot
        status=IsolatedDebugger(snapshot,box_id,emit,halted.is_set).run(receive)
    except Exception as e:
        error=str(e)[:1000];log.error(json.dumps({'debugSession':sid,'errorType':type(e).__name__}))
        try:emit({'type':'event','event':'output','body':{'category':'stderr','output':error+'\n'}})
        except Exception:pass # Output/lease failure must not prevent durable terminal state.
    finally:done.set();thread.join(timeout=2)
    with factory() as db:
        row=db.get(DebugSession,sid)
        if row.lease_token==token:
            if row.status not in {'FINISHED','STOPPED','FAILED','EXPIRED'}:row.status=status;row.error=error
            row.heartbeat=utcnow();db.commit()

def main():
    logging.basicConfig(level=logging.INFO);box_id=int(os.getenv('DEBUG_BOX_ID','600'));Sandbox(box_id)
    if os.getenv('WORKER_SANDBOX_APPROVED')!='1' or os.getenv('DEBUG_SANDBOX_APPROVED')!='1':raise SandboxUnavailable('Complete and review real debug-language/security prerequisites before approval')
    for tool in ['/usr/bin/gdb','/usr/bin/javac','/usr/lib/python3/dist-packages/debugpy/adapter/__main__.py','/usr/local/share/olympiad-debug/OlympiadJavaDAP.class']:
        if not os.path.isfile(tool):raise SandboxUnavailable('Debug tool unavailable: '+tool)
    with Sandbox(box_id).opened() as box:
        result=box.run(['/usr/bin/true'],'',{'cpuSeconds':2,'wallSeconds':5,'memoryKiB':65536,'maxProcesses':1,'outputBytes':10000,'compileWallSeconds':5,'compileMemoryKiB':65536},lambda:False,lambda *_:None)
        if result['status']!='FINISHED':raise SandboxUnavailable('Debug sandbox probe failed')
    factory=session_factory(make_engine());wid=socket.gethostname()+'-'+str(uuid4());active=None
    while True:
        with factory() as db:
            row=db.get(DebugWorker,wid)
            if not row:row=DebugWorker(id=wid,languages=['cpp17','cpp20','python3','java17']);db.add(row)
            row.last_seen=utcnow();db.commit()
        if active and active.is_alive():time.sleep(.5);continue
        with factory() as db:
            row=db.scalar(select(DebugSession).where(DebugSession.status=='QUEUED',DebugSession.cancelled.is_(False),DebugSession.expires_at>utcnow()).order_by(DebugSession.created_at).with_for_update(skip_locked=True).limit(1))
            if row:
                row.status='RUNNING';row.lease_token=str(uuid4());row.heartbeat=utcnow();sid,token=row.id,row.lease_token;db.commit();active=threading.Thread(target=run_session,args=(factory,sid,token,box_id),daemon=True);active.start()
        time.sleep(.2)

if __name__=='__main__':main()
