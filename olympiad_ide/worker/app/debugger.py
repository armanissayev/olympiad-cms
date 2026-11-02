"""Real DAP adapter lifecycle entirely inside approved isolate boxes."""
import json,os,selectors,subprocess,time
from pathlib import Path
from .sandbox import Sandbox,SandboxUnavailable
from app.execution_service import limits_for

ADAPTERS='/usr/local/share/olympiad-debug'
DEBUG_LIMITS={'cpuSeconds':30,'wallSeconds':300,'memoryKiB':1048576,'maxProcesses':64,'outputBytes':1048576,'compileWallSeconds':30,'compileMemoryKiB':524288}

class Framer:
    def __init__(self):self.buffer=bytearray()
    def feed(self,data):
        self.buffer.extend(data);result=[]
        while True:
            pos=self.buffer.find(b'\r\n\r\n')
            if pos<0:
                if len(self.buffer)>1024:raise RuntimeError('Invalid DAP framing')
                break
            headers=self.buffer[:pos].decode('ascii').split('\r\n')
            lengths=[int(line.split(':',1)[1]) for line in headers if line.lower().startswith('content-length:')]
            if len(lengths)!=1 or not 0<lengths[0]<=65536:raise RuntimeError('DAP frame exceeds budget')
            size=lengths[0]
            if len(self.buffer)<pos+4+size:break
            value=json.loads(self.buffer[pos+4:pos+4+size]);del self.buffer[:pos+4+size]
            if not isinstance(value,dict) or value.get('type') not in ('event','response'):raise RuntimeError('Unexpected adapter message')
            result.append(value)
        return result

def encode(message):
    body=json.dumps(message,separators=(',',':'),ensure_ascii=True).encode()
    if len(body)>65536:raise RuntimeError('DAP request too large')
    return b'Content-Length: '+str(len(body)).encode()+b'\r\n\r\n'+body

class DAPInput:
    """Bounded nonblocking pipe writer; a stalled adapter cannot stall Stop."""
    def __init__(self,stream):
        self.fd=stream.fileno();self.pending=bytearray();os.set_blocking(self.fd,False)
    def enqueue(self,message):
        wire=encode(message)
        if len(self.pending)+len(wire)>65536:raise RuntimeError('DAP input queue budget exhausted')
        self.pending.extend(wire)
    def flush(self):
        if not self.pending:return
        try:count=os.write(self.fd,self.pending)
        except BlockingIOError:return
        del self.pending[:count]

def profile(snapshot):
    config=snapshot['configuration'];language=config['language'];entry=next(f['path'] for f in snapshot['files'] if f['id']==config['entryPoint'])
    if language.startswith('cpp'):
        command=['/usr/bin/g++','-std=c++17' if language=='cpp17' else '-std=c++20','-g','-O0','-fno-omit-frame-pointer',*[('/box/'+f['path']) for f in snapshot['files'] if f['path'].endswith(('.cpp','.cc','.cxx'))],'-o','/box/__debug_program']
        adapter=['/usr/bin/gdb','--quiet','--nx','--nh','--interpreter=dap','-iex','set auto-load off','-iex','set debuginfod enabled off','-iex','set exec-wrapper /usr/bin/python3 '+ADAPTERS+'/stdin_wrapper.py']
        launch={'program':'/box/__debug_program','cwd':'/box','stopAtBeginningOfMainSubprogram':False}
    elif language=='python3':
        command=None;adapter=['/usr/bin/python3','-m','debugpy.adapter'];launch={'program':ADAPTERS+'/python_entry.py','args':['/box/'+entry],'cwd':'/box','python':['/usr/bin/python3'],'console':'internalConsole','redirectOutput':True,'justMyCode':True,'subProcess':False,'stopOnEntry':False}
    elif language=='java17':
        command=[str(Path('/usr/bin/javac').resolve()),'--release','17','-g','-d','/box/__debug_build',*[('/box/'+f['path']) for f in snapshot['files'] if f['path'].endswith('.java')]]
        adapter=[str(Path('/usr/bin/java').resolve()),'--add-modules','jdk.jdi','-Xmx128m','-cp',ADAPTERS,'OlympiadJavaDAP']
        launch={'mainClass':config['mainClass'],'cwd':'/box','classPaths':['/box/__debug_build'],'stdin':'/box/__debug_stdin','javaExec':'/usr/bin/java'}
    else:raise RuntimeError('Unsupported debug language')
    return command,adapter,launch

class IsolatedDebugger:
    def __init__(self,snapshot,box_id,emit,cancelled):self.snapshot=snapshot;self.box_id=box_id;self.emit=emit;self.cancelled=cancelled;self.process=None;self.launch_seen=False;self.initialized=False
    def run(self,receive):
        compile_command,adapter,launch=profile(self.snapshot)
        with Sandbox(self.box_id).opened() as box:
            for f in self.snapshot['files']:box.write(f['path'],f['content'].encode())
            box.write('__debug_stdin',self.snapshot['tests'][0]['stdin'].encode())
            (box.box/'__debug_build').mkdir(exist_ok=True)
            if compile_command:
                result=box.run(compile_command,'',DEBUG_LIMITS,self.cancelled,lambda stream,text:self.emit({'type':'event','event':'output','body':{'category':'stderr','output':text}}),compilation=True)
                if result['status']!='FINISHED':raise RuntimeError('Debug compilation failed: '+result['stderr'][:1000])
            args=[*box.prefix,'--silent','--syscalls=31',f'--meta={box.control/"debug.meta"}','--chdir=/box','--time=30','--wall-time=300','--cg-mem=1048576','--processes=64','--open-files=128','--core=0','--fsize=1024','--env=PATH=/usr/bin:/bin','--env=HOME=/box','--env=LANG=C.UTF-8','--env=TMPDIR=/box','--env=PYTHONPATH=/usr/lib/python3/dist-packages','--run','--',*adapter]
            if Path('/etc/java-17-openjdk').is_dir():args.insert(len(box.prefix),'--dir=etc/java-17-openjdk=/etc/java-17-openjdk')
            self.process=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={'PATH':'/usr/bin:/bin'},start_new_session=True)
            p=self.process;input_pipe=DAPInput(p.stdin);selector=selectors.DefaultSelector();selector.register(p.stdout,selectors.EVENT_READ,'dap');selector.register(p.stderr,selectors.EVENT_READ,'stderr');framer=Framer();deadline=time.monotonic()+300;total=0;terminated=False
            try:
                while p.poll() is None and not self.cancelled() and time.monotonic()<deadline:
                    for message in receive():
                        # The API validates all controls; the trusted worker alone sets launch settings.
                        message=dict(message);command=message['command']
                        if command=='initialize':
                            if self.initialized:raise RuntimeError('Duplicate initialize')
                            self.initialized=True;message['arguments']={'clientID':'olympiad','adapterID':'olympiad','linesStartAt1':True,'columnsStartAt1':True,'pathFormat':'path','supportsRunInTerminalRequest':False}
                        elif command=='launch':
                            if self.launch_seen:raise RuntimeError('Duplicate launch')
                            self.launch_seen=True;message['arguments']=launch
                        input_pipe.enqueue(message)
                    input_pipe.flush()
                    for key,_ in selector.select(.05):
                        data=os.read(key.fileobj.fileno(),8192)
                        if not data:selector.unregister(key.fileobj);continue
                        total+=len(data)
                        if total>1048576:raise RuntimeError('Debugger output budget exhausted')
                        if key.data=='stderr':self.emit({'type':'event','event':'output','body':{'category':'stderr','output':data.decode(errors='replace')}})
                        else:
                            for message in framer.feed(data):
                                self.emit(message)
                                if message.get('event')=='terminated':terminated=True
                    if terminated:return 'FINISHED'
                if self.cancelled():return 'STOPPED'
                if time.monotonic()>=deadline:return 'EXPIRED'
                raise RuntimeError('Isolated adapter exited unexpectedly')
            finally:
                selector.close()
                if p.poll() is None:p.terminate()
                try:p.wait(timeout=3)
                except subprocess.TimeoutExpired:p.kill();p.wait(timeout=2)
                for file in [p.stdin,p.stdout,p.stderr]:file.close()
