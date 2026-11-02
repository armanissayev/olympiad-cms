"""Debug-specific protocol and actual isolation prerequisites; no approval bypass."""
import json,os,platform,time
from collections import deque
from pathlib import Path
import pytest
from worker.app.debugger import Framer,IsolatedDebugger,DEBUG_LIMITS,DAPInput,encode
from worker.app.sandbox import Sandbox


def test_debug_frames_are_incremental_and_bounded():
    frame=Framer();value=json.dumps({'type':'event','event':'stopped'}).encode();wire=b'Content-Length: '+str(len(value)).encode()+b'\r\n\r\n'+value
    assert frame.feed(wire[:10])==[]
    assert frame.feed(wire[10:])==[{'type':'event','event':'stopped'}]

def test_debug_frames_reject_reverse_requests_and_oversize():
    with pytest.raises(RuntimeError):Framer().feed(b'Content-Length: 65537\r\n\r\n')
    message=json.dumps({'type':'request','command':'runInTerminal'}).encode()
    with pytest.raises(RuntimeError):Framer().feed(b'Content-Length: '+str(len(message)).encode()+b'\r\n\r\n'+message)

@pytest.fixture
def debug_linux():
    if os.getenv('RUN_LINUX_DEBUG_TESTS')!='1':pytest.skip('Explicit dedicated Linux debug prerequisite run required')
    assert platform.system()=='Linux' and platform.machine()=='x86_64'
    Sandbox(620)

def snapshot(source):return {'configuration':{'language':'python3','entryPoint':'file'},'files':[{'id':'file','path':'main.py','content':source}],'tests':[{'stdin':''}]}

def adapter_run(source,box=620,cancel_after=20):
    pending=deque([{'seq':1,'type':'request','command':'initialize','arguments':{}},{'seq':2,'type':'request','command':'launch','arguments':{}}]);events=[];started=time.monotonic()
    def emit(message):
        events.append(message)
        if message.get('event')=='initialized':pending.append({'seq':3,'type':'request','command':'configurationDone','arguments':{}})
    def receive():result=list(pending);pending.clear();return result
    result=IsolatedDebugger(snapshot(source),box,emit,lambda:time.monotonic()-started>cancel_after).run(receive)
    return result,''.join(m.get('body',{}).get('output','') for m in events if m.get('event')=='output')

def test_real_debug_credentials_network_and_syscalls(debug_linux,monkeypatch):
    monkeypatch.setenv('IDE_SECRET_CANARY','do-not-inherit')
    source="""import os,socket,ctypes,errno
assert 'IDE_SECRET_CANARY' not in os.environ
for p in ['/etc/cms-ide-stage/native.key','/etc/cms-ide-stage/runtime.key','/run/cms-ide-stage-pg','/var/lib/cms-ide-stage/judge-cache']:
 assert not os.path.exists(p),p
try:socket.create_connection(('1.1.1.1',53),timeout=.2)
except OSError:pass
else:raise AssertionError('External networking allowed')
lib=ctypes.CDLL(None,use_errno=True)
assert lib.syscall(250,2,0,0,0,0)==-1 and ctypes.get_errno()==errno.ENOSYS
try:socket.socket(socket.AF_VSOCK,socket.SOCK_STREAM)
except OSError as e:assert e.errno==errno.EAFNOSUPPORT
else:raise AssertionError('VSOCK allowed')
print('debug-security-ok')
"""
    status,output=adapter_run(source);assert status=='FINISHED' and 'debug-security-ok' in output

def test_real_debug_cancellation_cleans_box(debug_linux):
    status,_=adapter_run('while True: pass',621,2)
    assert status=='STOPPED'
    assert not Path('/var/lib/cms-ide-stage/boxes/621').exists()

def test_real_debug_output_budget_cleans_box(debug_linux):
    with pytest.raises(RuntimeError,match='budget|frame'):adapter_run('print("x"*1200000)',622)
    assert not Path('/var/lib/cms-ide-stage/boxes/622').exists()

def test_real_debug_quota_with_debug_process_limits(debug_linux):
    source="""import errno
try:
 for i in range(128):
  with open('/box/data'+str(i),'wb') as f:f.write(b'x'*1048576)
except OSError as e:
 assert e.errno==errno.EDQUOT
 print('quota-ok')
else:raise AssertionError('Quota absent')
"""
    with Sandbox(623).opened() as box:
        box.write('main.py',source.encode());result=box.run(['/usr/bin/python3','/box/main.py'],'',DEBUG_LIMITS,lambda:False,lambda *_:None)
        assert result['status']=='FINISHED' and 'quota-ok' in result['stdout'],result

def test_real_debug_memory_is_cgroup_bounded(debug_linux):
    with Sandbox(624).opened() as box:
        box.write('main.py',b'x=bytearray(2147483648)')
        result=box.run(['/usr/bin/python3','/box/main.py'],'',DEBUG_LIMITS,lambda:False,lambda *_:None)
        assert result['status']=='MEMORY_LIMIT_EXCEEDED',result

def test_real_debug_neighbor_files_hidden(debug_linux):
    with Sandbox(625).opened() as other:
        other.write('secret.txt',b'neighbor-secret')
        source='from pathlib import Path\nassert not Path('+repr(str(other.box/'secret.txt'))+').exists()\nprint("neighbor-hidden")'
        with Sandbox(626).opened() as box:
            box.write('main.py',source.encode());result=box.run(['/usr/bin/python3','/box/main.py'],'',DEBUG_LIMITS,lambda:False,lambda *_:None)
            assert result['status']=='FINISHED' and 'neighbor-hidden' in result['stdout'],result


def test_input_backpressure_is_nonblocking_and_resumes_after_drain():
    read,write=os.pipe();os.set_blocking(read,False)
    with os.fdopen(write,'wb',buffering=0) as stream:
        channel=DAPInput(stream)
        try:
            while True:os.write(write,b'x'*4096)
        except BlockingIOError:pass
        message={'seq':1,'type':'request','command':'pause','arguments':{'threadId':1}}
        channel.enqueue(message);started=time.monotonic();channel.flush()
        assert time.monotonic()-started<.1 and channel.pending
        while True:
            try:os.read(read,65536)
            except BlockingIOError:break
        channel.flush();assert not channel.pending and os.read(read,65536)==encode(message)
    os.close(read)

def test_pending_input_has_an_aggregate_limit_even_if_adapter_never_reads():
    read,write=os.pipe()
    with os.fdopen(write,'wb',buffering=0) as stream:
        channel=DAPInput(stream);message={'seq':1,'type':'request','command':'launch','arguments':{'padding':'x'*32000}}
        channel.enqueue(message);channel.enqueue(message)
        with pytest.raises(RuntimeError,match='input queue budget'):channel.enqueue(message)
    os.close(read)
