"""Manual real GDB/debugpy prerequisite: from olympiad_ide, PYTHONPATH=backend:. python worker/tests/debugger_language_probe.py cpp20|python3.
Uses reserved isolate610/611. No service approval flag is enabled or bypassed.
"""
import json,sys,time
from collections import deque
from worker.app.debugger import IsolatedDebugger
assert len(sys.argv)==2 and sys.argv[1] in ('cpp20','python3'), 'Select cpp20 or python3'
language=sys.argv[1];source={'cpp20':'#include <iostream>\nint inc(int v){return v+1;}\nint main(){\n int a;std::cin>>a;\n int b=inc(a);\n std::cout<<b<<"\\n";\n return 0;\n}\n','python3':'def inc(v):\n return v+1\na=int(input())\nb=inc(a)\nprint(b)\n'}[language];entry='main.cpp' if language=='cpp20' else 'main.py';line=5 if language=='cpp20' else 4
snapshot={'files':[{'id':'file','path':entry,'content':source}],'configuration':{'language':language,'entryPoint':'file'},'tests':[{'stdin':'2\n'}]};queue=deque();seq=0;messages=[];stage=0;stops=[];variable_seen=False;deadline=time.monotonic()+50;threadid=1

def send(command,arguments={}):
 global seq
 seq+=1;queue.append({'type':'request','seq':seq,'command':command,'arguments':arguments})

def emit(m):
 global stage,variable_seen,threadid
 messages.append(m)
 if m.get('event')=='initialized':send('setBreakpoints',{'source':{'path':'/box/'+entry},'breakpoints':[{'line':line}]});send('configurationDone')
 if m.get('event')=='stopped':
  threadid=m['body']['threadId'];stops.append(m['body']);send('stackTrace',{'threadId':threadid})
 if m.get('type')=='response' and not m.get('success'):raise RuntimeError('DAPfailure:'+json.dumps(m))
 if m.get('command')=='stackTrace' and m.get('type')=='response':
  frames=m.get('body',{}).get('stackFrames',[])
  if frames:send('scopes',{'frameId':frames[0]['id']})
 if m.get('command')=='scopes' and m.get('type')=='response':
  scopes=m.get('body',{}).get('scopes',[])
  if scopes:send('variables',{'variablesReference':scopes[0]['variablesReference']})
 if m.get('command')=='variables' and m.get('type')=='response':
  if any(v['name']=='a' and v['value']=='2' for v in m.get('body',{}).get('variables',[])):variable_seen=True
  cmd=['stepIn','stepOut','next','continue'][min(stage,3)];stage+=1;send(cmd,{'threadId':threadid})

def receive():
 result=list(queue);queue.clear();return result
send('initialize');send('launch')
try:
 status=IsolatedDebugger(snapshot,610 if language=='cpp20' else 611,emit,lambda:time.monotonic()>deadline).run(receive)
 assert variable_seen,(status,stops)
 assert len(stops)>=3,(status,stops)
 assert status=='FINISHED',status
 print(json.dumps({'language':language,'status':status,'stops':stops,'actualVariableA2':variable_seen,'steps':stage,'output':[m.get('body') for m in messages if m.get('event')=='output']},indent=2))
except Exception:
 print(json.dumps(messages,indent=2));raise
