"""Real Java JDI control acceptance; run manually only on approved disposable Linux.

From olympiad_ide: PYTHONPATH=backend:. python worker/tests/java_debugger_probe.py
Requires the trusted adapter installed and isolate box650 reserved for this probe.
No API/CMS credentials or unrestricted participant execution are used.
"""
import json,queue,threading,time
from worker.app.debugger import IsolatedDebugger

def main():
    source='''public class Main {
      static int add(int x, int y) {
        int z = x + y;
        return z;
      }
      public static void main(String[] args) throws Exception {
        java.util.Scanner in = new java.util.Scanner(System.in);
        int a = in.nextInt();
        int b = in.nextInt();
        int total = add(a, b);
        System.out.println(total);
        while (true) { Thread.sleep(10); }
      }
    }
    '''
    pending=queue.Queue();messages=[];condition=threading.Condition();finished={};cancel=threading.Event();sequence=0
    snapshot={'configuration':{'language':'java17','entryPoint':'entry','mainClass':'Main'},'files':[{'id':'entry','path':'Main.java','content':source}],'tests':[{'stdin':'2 3\n'}]}
    def emit(message):
     with condition:messages.append(message);condition.notify_all()
    def receive():
     result=[]
     while True:
      try:result.append(pending.get_nowait())
      except queue.Empty:return result
    def wait(predicate,start=0,timeout=20):
     deadline=time.monotonic()+timeout
     with condition:
      while time.monotonic()<deadline:
       for m in messages[start:]:
        if predicate(m):return m
       if 'error' in finished:raise AssertionError(finished['error']+' '+json.dumps(messages[-5:]))
       condition.wait(.1)
     raise AssertionError('DAP wait timed out '+json.dumps(messages[-8:]))
    def command(name,args=None):
     nonlocal sequence;sequence+=1;seq=sequence;pending.put({'seq':seq,'type':'request','command':name,'arguments':args or {}})
     result=wait(lambda m:m.get('type')=='response' and m.get('request_seq')==seq);assert result['success'],result
     return result.get('body',{})
    def run():
     try:finished['result']=IsolatedDebugger(snapshot,650,emit,cancel.is_set).run(receive)
     except Exception as e:finished['error']=repr(e)
     finally:
      with condition:condition.notify_all()
    t=threading.Thread(target=run);t.start();checks=[]
    try:
     command('initialize');wait(lambda m:m.get('event')=='initialized');command('launch')
     bp=command('setBreakpoints',{'source':{'path':'/box/Main.java'},'breakpoints':[{'line':10}]});command('configurationDone')
     stopped=wait(lambda m:m.get('event')=='stopped');assert stopped['body']['reason']=='breakpoint',stopped;thread=stopped['body']['threadId'];checks.append('real breakpoint at source line10')
     def stack():return command('stackTrace',{'threadId':thread})['stackFrames']
     frame=stack()[0];assert frame['line']==10,frame;assert frame['source']['path']=='/box/Main.java'
     ref=command('scopes',{'frameId':frame['id']})['scopes'][0]['variablesReference'];vs=command('variables',{'variablesReference':ref})['variables'];values={v['name']:v['value'] for v in vs};assert values['a']=='2' and values['b']=='3',values;assert command('evaluate',{'frameId':frame['id'],'expression':'a'})['result']=='2';checks.append('actual scoped locals a2/b3 and identifier inspection')
     def step(name):
      mark=len(messages);command(name,{'threadId':thread});wait(lambda m:m.get('event')=='stopped' and m['body']['reason']=='step',mark);return stack()[0]
     frame=step('stepIn');assert frame['name']=='Main.add' and frame['line']==3,frame;checks.append('stepInto enters actual add frame')
     frame=step('next');assert frame['line']==4,frame;ref=command('scopes',{'frameId':frame['id']})['scopes'][0]['variablesReference'];values={v['name']:v['value'] for v in command('variables',{'variablesReference':ref})['variables']};assert values['z']=='5',values;checks.append('stepOver exposes computed local z5')
     frame=step('stepOut');assert frame['name']=='Main.main',frame;checks.append('stepOut returns to caller')
     command('setBreakpoints',{'source':{'path':'/box/Main.java'},'breakpoints':[]});mark=len(messages);command('continue',{'threadId':thread});wait(lambda m:m.get('event')=='output' and m['body'].get('category')=='stdout' and '5' in m['body'].get('output',''),mark);checks.append('continue reads fixed stdin and emits actual stdout5')
     mark=len(messages);command('pause',{'threadId':thread});wait(lambda m:m.get('event')=='stopped' and m['body']['reason']=='pause',mark);assert stack();checks.append('pause suspends actual JVM')
     command('disconnect',{'terminateDebuggee':True});t.join(8);assert not t.is_alive();assert finished.get('result')=='FINISHED',finished;checks.append('disconnect terminates debuggee and adapter')
     print(json.dumps({'kind':'real-isolate-java-jdi','status':'passed','checks':checks,'boxId':650,'security':'unchanged syscall31/cgroup1GiB/64processes/fresh netns/quota sandbox'},indent=2))
    finally:
     cancel.set();t.join(5)

if __name__=="__main__":main()
