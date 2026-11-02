"""Direct x86_64 syscall-denial probes through the unchanged secure Sandbox adapter."""
import json,platform
from pathlib import Path
assert Path("/opt/cms-ide-stage/AUTHORIZED_DISPOSABLE").is_file()
from worker.app.sandbox import Sandbox
from app.execution_service import limits_for
assert platform.machine()=='x86_64'
program='''import ctypes,errno,fcntl,json,socket
from pathlib import Path
lib=ctypes.CDLL(None,use_errno=True)
result={}
for name,number,args in [('keyctl',250,(2,0,0,0,0)),('io_uring_setup',425,(0,0))]:
 ctypes.set_errno(0);value=lib.syscall(number,*args);result[name]={'return':value,'errno':ctypes.get_errno()};assert value==-1 and result[name]['errno']==errno.ENOSYS
try:socket.socket(socket.AF_VSOCK,socket.SOCK_STREAM)
except OSError as e:result['AF_VSOCK']=e.errno;assert e.errno==errno.EAFNOSUPPORT
else:raise AssertionError('vsock unexpectedly allowed')
with open('/box/probe-file','w') as f:
 for name,op,wanted in [('flock',lambda:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB),errno.ENOSYS),('fcntl_lock',lambda:fcntl.lockf(f,fcntl.LOCK_EX|fcntl.LOCK_NB),errno.EPERM)]:
  try:op()
  except OSError as e:result[name]=e.errno;assert e.errno==wanted
  else:raise AssertionError(name+' unexpectedly allowed')
print(json.dumps(result,sort_keys=True))
'''
with Sandbox(450).opened() as sandbox:
 sandbox.write('probe.py',program.encode());result=sandbox.run(['/usr/bin/python3','/box/probe.py'],'',limits_for('python3'),lambda:False,lambda *_:None)
assert result['status']=='FINISHED',result
report={'kind':'real-linux-syscall-filter','helperFlags':'--syscalls=31','architecture':platform.machine(),'result':json.loads(result['stdout']),'status':'passed','cpuTime':result['cpuTime'],'wallTime':result['wallTime'],'peakMemoryKiB':result['peakMemoryKiB']}
print(json.dumps(report,indent=2))
