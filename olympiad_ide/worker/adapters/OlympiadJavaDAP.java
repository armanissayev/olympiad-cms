// SPDX-License-Identifier: AGPL-3.0-or-later
// Self-contained JDK17 JDI/DAP bridge. Run only inside the approved debug sandbox.
import com.sun.jdi.*;
import com.sun.jdi.connect.*;
import com.sun.jdi.event.*;
import com.sun.jdi.request.*;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.atomic.*;

public final class OlympiadJavaDAP {
    static final int MAX_MESSAGE=65536, MAX_CHILDREN=100;
    final InputStream input=System.in;
    final OutputStream output=System.out;
    final Object state=new Object(), wire=new Object();
    final AtomicInteger sequence=new AtomicInteger(1), ids=new AtomicInteger(1);
    final AtomicBoolean terminated=new AtomicBoolean();
    volatile VirtualMachine vm;
    volatile Process process;
    volatile boolean configured, closing, stopOnEntry;
    String mainClass;
    final Map<Integer,ThreadReference> threads=new LinkedHashMap<>();
    final Map<Long,Integer> threadIds=new HashMap<>();
    final Map<Integer,StackFrame> frames=new HashMap<>();
    final Map<Integer,Object> values=new HashMap<>();
    final Map<String,List<Map<String,Object>>> breakpoints=new LinkedHashMap<>();
    final List<Path> sources=new ArrayList<>();
    ThreadReference stoppedThread;

    static Map<String,Object> obj(Object... pairs) {
        Map<String,Object> result=new LinkedHashMap<>();
        for(int i=0;i<pairs.length;i+=2) result.put((String)pairs[i],pairs[i+1]);
        return result;
    }
    @SuppressWarnings("unchecked") static Map<String,Object> map(Object value) {
        if(!(value instanceof Map)) throw new IllegalArgumentException("Expected object");
        return (Map<String,Object>)value;
    }
    static String text(Map<String,Object> object,String key,String fallback) {
        Object value=object.get(key); return value instanceof String?(String)value:fallback;
    }
    static int number(Map<String,Object> object,String key,int fallback) {
        Object value=object.get(key);return value instanceof Number?((Number)value).intValue():fallback;
    }
    static String brief(String text,int limit) { return text.length()<=limit?text:text.substring(0,limit)+"…"; }
    static boolean appendBounded(List<Object> list,Object value) {
        list.add(value);
        if(Json.encode(list).getBytes(StandardCharsets.UTF_8).length>MAX_MESSAGE-4096){list.remove(list.size()-1);return false;}
        return true;
    }
    void send(Map<String,Object> message) {
        synchronized(wire) {
            message.put("seq",sequence.getAndIncrement());
            byte[] bytes=Json.encode(message).getBytes(StandardCharsets.UTF_8);
            if(bytes.length>MAX_MESSAGE) throw new IllegalArgumentException("DAP response exceeds bound");
            try { output.write(("Content-Length: "+bytes.length+"\r\n\r\n").getBytes(StandardCharsets.US_ASCII));output.write(bytes);output.flush(); }
            catch(IOException error) { closing=true; }
        }
    }
    void event(String name,Map<String,Object> body) { send(obj("type","event","event",name,"body",body)); }
    void response(Map<String,Object> request,Map<String,Object> body) {
        send(obj("type","response","request_seq",request.get("seq"),"command",request.get("command"),"success",true,"body",body));
    }
    Map<String,Object> read() throws IOException {
        ByteArrayOutputStream header=new ByteArrayOutputStream();int last=0;
        while(true) {
            int b=input.read();if(b<0){if(header.size()==0)return null;throw new EOFException("Truncated header");}
            header.write(b);last=((last<<8)|(b&255));
            if(last==0x0d0a0d0a)break;
            if(header.size()>8192)throw new IOException("Oversized DAP header");
        }
        int length=-1;
        for(String line:header.toString(StandardCharsets.US_ASCII).split("\r\n")) {
            if(line.toLowerCase(Locale.ROOT).startsWith("content-length:")) {
                if(length!=-1)throw new IOException("Duplicate Content-Length");
                try {length=Integer.parseInt(line.substring(line.indexOf(':')+1).trim());}
                catch(NumberFormatException error){throw new IOException("Invalid Content-Length");}
            }
        }
        if(length<0||length>MAX_MESSAGE)throw new IOException("Invalid DAP frame bound");
        byte[] bytes=input.readNBytes(length);if(bytes.length!=length)throw new EOFException("Truncated DAP frame");
        return map(new Json(new String(bytes,StandardCharsets.UTF_8)).parse());
    }
    void needVM(){if(vm==null)throw new IllegalStateException("Launch a Java debug session first");}
    ThreadReference thread(int id) {
        ThreadReference value=threads.get(id);if(value==null)throw new IllegalArgumentException("Unknown thread");return value;
    }
    int threadId(ThreadReference thread) {
        long unique=thread.uniqueID();Integer id=threadIds.get(unique);
        if(id==null){id=ids.getAndIncrement();threadIds.put(unique,id);threads.put(id,thread);}return id;
    }
    int valueId(Object value) {int id=ids.getAndIncrement();values.put(id,value);return id;}
    void clearStopped() {frames.clear();values.clear();stoppedThread=null;}
    Path sourcePath(String raw) throws IOException {
        if(raw==null)throw new IllegalArgumentException("Source path required");
        Path path=Path.of(raw).toAbsolutePath().normalize();
        if(!sources.contains(path))throw new IllegalArgumentException("Source is outside the immutable Java snapshot");
        return path;
    }
    Path locationSource(Location location) {
        try {
            // Never attach a JDK/platform frame to a participant file with the
            // same basename. Only the launched application's class loader is
            // backed by the immutable compiled snapshot.
            ClassLoaderReference loader=location.declaringType().classLoader();
            if(loader==null||!loader.referenceType().name().equals("jdk.internal.loader.ClassLoaders$AppClassLoader"))return null;
            String relative=location.sourcePath().replace('\\','/');
            for(Path source:sources)if(source.toString().endsWith("/"+relative))return source;
            List<Path> matching=new ArrayList<>();
            for(Path source:sources)if(source.getFileName().toString().equals(location.sourceName()))matching.add(source);
            return matching.size()==1?matching.get(0):null;
        }catch(AbsentInformationException error){return null;}
    }
    void installBreakpoints(ReferenceType type) {
        for(var entry:breakpoints.entrySet())for(var breakpoint:entry.getValue()) {
            int line=number(breakpoint,"line",0);
            try {
                for(Location location:type.locationsOfLine(line)) {
                    Path source=locationSource(location);if(source==null||!source.toString().equals(entry.getKey()))continue;
                    BreakpointRequest request=vm.eventRequestManager().createBreakpointRequest(location);
                    request.setSuspendPolicy(EventRequest.SUSPEND_ALL);request.putProperty("id",breakpoint.get("id"));request.enable();
                    if(!Boolean.TRUE.equals(breakpoint.get("verified"))) {
                        breakpoint.put("verified",true);
                        event("breakpoint",obj("reason","changed","breakpoint",obj("id",breakpoint.get("id"),"verified",true,"line",line)));
                    }
                }
            }catch(AbsentInformationException|ClassNotPreparedException ignored) { /* No executable location for this line. */ }
        }
    }
    Map<String,Object> setBreakpoints(Map<String,Object> args) throws Exception {
        needVM();Path path=sourcePath(text(map(args.get("source")),"path",null));
        List<EventRequest> remove=new ArrayList<>();
        for(BreakpointRequest existing:vm.eventRequestManager().breakpointRequests()) {
            Path source=locationSource(existing.location());if(path.equals(source))remove.add(existing);
        }
        vm.eventRequestManager().deleteEventRequests(remove);
        List<Map<String,Object>> requested=new ArrayList<>();
        Object raw=args.get("breakpoints");
        if(raw instanceof List)for(Object item:(List<?>)raw) {
            if(requested.size()>=MAX_CHILDREN)throw new IllegalArgumentException("Too many breakpoints");
            Map<String,Object> candidate=map(item);int line=number(candidate,"line",0);
            if(line<1)throw new IllegalArgumentException("Invalid breakpoint line");
            if(candidate.containsKey("condition")||candidate.containsKey("hitCondition")||candidate.containsKey("logMessage"))throw new IllegalArgumentException("Only source-line breakpoints are supported");
            requested.add(obj("id",ids.getAndIncrement(),"verified",false,"line",line));
        }
        breakpoints.put(path.toString(),requested);
        // Rebuild existing line requests once, avoiding duplicates across other sources.
        List<BreakpointRequest> old=new ArrayList<>(vm.eventRequestManager().breakpointRequests());
        for(BreakpointRequest bp:old)if(bp.getProperty("id")!=null)vm.eventRequestManager().deleteEventRequest(bp);
        for(ReferenceType type:vm.allClasses())installBreakpoints(type);
        return obj("breakpoints",requested);
    }
    void startLaunch(Map<String,Object> args) throws Exception {
        if(vm!=null)throw new IllegalStateException("Only one Java debuggee per adapter");
        if(!"/box".equals(text(args,"cwd","/box")))throw new IllegalArgumentException("Java cwd must be /box");
        if(!"/usr/bin/java".equals(text(args,"javaExec","/usr/bin/java")))throw new IllegalArgumentException("Java toolchain is fixed");
        if(!"/box/__debug_stdin".equals(text(args,"stdin","/box/__debug_stdin")))throw new IllegalArgumentException("Stdin must be the immutable debug input");
        Object classPaths=args.get("classPaths");
        if(!(classPaths instanceof List)||!classPaths.equals(List.of("/box/__debug_build")))throw new IllegalArgumentException("Java classpath is fixed");
        mainClass=text(args,"mainClass","");if(!mainClass.matches("(?:[A-Za-z_$][A-Za-z0-9_$]*\\.)*[A-Za-z_$][A-Za-z0-9_$]*"))throw new IllegalArgumentException("Invalid main class");
        stopOnEntry=Boolean.TRUE.equals(args.get("stopOnEntry"));
        try(var walk=Files.walk(Path.of("/box"),128)) {
            walk.filter(p->Files.isRegularFile(p,LinkOption.NOFOLLOW_LINKS)&&p.toString().endsWith(".java")).limit(MAX_CHILDREN+1).forEach(p->sources.add(p.toAbsolutePath().normalize()));
        }
        if(sources.isEmpty()||sources.size()>MAX_CHILDREN)throw new IllegalArgumentException("Invalid Java source snapshot");
        LaunchingConnector connector=Bootstrap.virtualMachineManager().defaultConnector();
        Map<String,Connector.Argument> launch=connector.defaultArguments();
        launch.get("home").setValue(System.getProperty("java.home"));launch.get("main").setValue(mainClass);
        launch.get("options").setValue("-Xmx128m -XX:MaxMetaspaceSize=96m -XX:ReservedCodeCacheSize=32m -XX:+UseSerialGC -cp /box/__debug_build");
        launch.get("suspend").setValue("true");
        vm=connector.launch(launch);process=vm.process();
        ClassPrepareRequest prepare=vm.eventRequestManager().createClassPrepareRequest();
        for(String exclude:List.of("java.*","javax.*","jdk.*","sun.*","com.sun.*"))prepare.addClassExclusionFilter(exclude);
        prepare.setSuspendPolicy(EventRequest.SUSPEND_ALL);prepare.enable();
        pump(process.getInputStream(),"stdout");pump(process.getErrorStream(),"stderr");
        daemon("java-debug-input",()->{
            try(OutputStream stdin=process.getOutputStream()) {
                Path file=Path.of("/box/__debug_stdin");if(Files.size(file)>1_000_000)throw new IOException("Oversized stdin");
                stdin.write(Files.readAllBytes(file));
            }catch(IOException error){event("output",obj("category","stderr","output","Java stdin: "+brief(error.getMessage(),256)+"\n"));}
        });
        daemon("java-jdi-events",this::events);
        daemon("java-debug-exit",()->{
            try {int code=process.waitFor();if(terminated.compareAndSet(false,true)){event("exited",obj("exitCode",code));event("terminated",obj());}}
            catch(InterruptedException error){Thread.currentThread().interrupt();}
        });
    }
    static void daemon(String name,Runnable runnable){Thread t=new Thread(runnable,name);t.setDaemon(true);t.start();}
    void pump(InputStream stream,String category) {
        daemon("java-debug-"+category,()->{
            try(Reader reader=new InputStreamReader(stream,StandardCharsets.UTF_8)) {
                char[] chars=new char[2048];int n;while((n=reader.read(chars))!=-1)event("output",obj("category",category,"output",new String(chars,0,n)));
            }catch(IOException ignored){}
        });
    }
    void events() {
        try {
            while(!closing) {
                EventSet set=vm.eventQueue().remove();boolean keepSuspended=false;
                synchronized(state) {
                    for(Event event:set) {
                        if(event instanceof ClassPrepareEvent prepared) {
                            installBreakpoints(prepared.referenceType());
                            if(stopOnEntry&&prepared.referenceType().name().equals(mainClass)) {
                                for(Method method:prepared.referenceType().methodsByName("main")) {
                                    if(method.isStatic()&&method.signature().equals("([Ljava/lang/String;)V")) {
                                        BreakpointRequest entry=vm.eventRequestManager().createBreakpointRequest(method.location());entry.putProperty("entry",true);entry.setSuspendPolicy(EventRequest.SUSPEND_ALL);entry.enable();break;
                                    }
                                }
                                stopOnEntry=false;
                            }
                        } else if(event instanceof BreakpointEvent hit) {
                            stoppedThread=hit.thread();keepSuspended=true;
                            boolean entry=Boolean.TRUE.equals(hit.request().getProperty("entry"));
                            if(entry)vm.eventRequestManager().deleteEventRequest(hit.request());
                            event("stopped",obj("reason",entry?"entry":"breakpoint","threadId",threadId(hit.thread()),"allThreadsStopped",true));
                        } else if(event instanceof StepEvent stepped) {
                            vm.eventRequestManager().deleteEventRequest(stepped.request());stoppedThread=stepped.thread();keepSuspended=true;
                            event("stopped",obj("reason","step","threadId",threadId(stepped.thread()),"allThreadsStopped",true));
                        } else if(event instanceof VMStartEvent) {
                            // configurationDone alone releases the VMStart suspension.
                            // Resuming this stale event after configurationDone could
                            // accidentally release a newer class-prepare suspension.
                            keepSuspended=true;
                        }
                    }
                    if(!keepSuspended)set.resume();
                }
            }
        }catch(VMDisconnectedException ignored){}
        catch(InterruptedException error){Thread.currentThread().interrupt();}
        catch(Exception error){event("output",obj("category","stderr","output","JDI event error: "+brief(error.toString(),512)+"\n"));shutdown();}
    }
    Map<String,Object> stackTrace(Map<String,Object> args) throws Exception {
        ThreadReference thread=thread(number(args,"threadId",0));
        if(!thread.isSuspended())throw new IllegalStateException("Thread is not stopped");
        int total=thread.frameCount(),start=Math.max(0,number(args,"startFrame",0));
        int count=Math.min(MAX_CHILDREN,Math.min(Math.max(0,total-start),Math.max(1,number(args,"levels",MAX_CHILDREN))));
        List<Object> result=new ArrayList<>();
        for(StackFrame frame:thread.frames(start,count)) {
            int id=ids.getAndIncrement();frames.put(id,frame);Location location=frame.location();Path source=locationSource(location);
            Map<String,Object> entry=obj("id",id,"name",brief(location.declaringType().name()+"."+location.method().name(),512),"line",Math.max(1,location.lineNumber()),"column",1);
            if(source!=null)entry.put("source",obj("name",source.getFileName().toString(),"path",source.toString()));
            if(!appendBounded(result,entry))break;
        }
        return obj("stackFrames",result,"totalFrames",total);
    }
    Map<String,Object> variable(String name,Value value) {
        int reference=0;String display,type="null";
        if(value==null)display="null";
        else {
            type=value.type().name();
            if(value instanceof StringReference string)display=Json.encode(brief(string.value(),4096));
            else if(value instanceof ArrayReference array){display=type+"["+array.length()+"]";reference=valueId(array);}
            else if(value instanceof ObjectReference object){display=type+"@"+Long.toHexString(object.uniqueID());reference=valueId(object);}
            else display=value.toString();
        }
        Map<String,Object> result=obj("name",brief(name,256),"value",brief(display,4096),"type",brief(type,512),"variablesReference",reference);
        if(value instanceof ArrayReference array)result.put("indexedVariables",array.length());
        return result;
    }
    Map<String,Object> variables(Map<String,Object> args) throws Exception {
        Object reference=values.get(number(args,"variablesReference",0));if(reference==null)throw new IllegalArgumentException("Expired variables reference; request a new stopped stack");
        List<Object> children=new ArrayList<>();
        if(reference instanceof StackFrame frame) {
            ObjectReference self=frame.thisObject();if(self!=null)appendBounded(children,variable("this",self));
            try {
                List<LocalVariable> locals=frame.visibleVariables();
                for(LocalVariable local:locals){if(children.size()>=MAX_CHILDREN)break;if(!appendBounded(children,variable(local.name(),frame.getValue(local))))break;}
            }catch(AbsentInformationException ignored){}
        }else if(reference instanceof ArrayReference array) {
            int start=Math.max(0,number(args,"start",0));int count=Math.min(MAX_CHILDREN,Math.min(Math.max(0,array.length()-start),Math.max(0,number(args,"count",MAX_CHILDREN))));
            List<Value> contents=array.getValues(start,count);for(int i=0;i<contents.size();i++){if(!appendBounded(children,variable("["+(start+i)+"]",contents.get(i))))break;}
        }else if(reference instanceof ObjectReference object) {
            for(Field field:object.referenceType().allFields()){if(field.isStatic())continue;if(children.size()>=MAX_CHILDREN)break;if(!appendBounded(children,variable(field.name(),object.getValue(field))))break;}
        }
        return obj("variables",children);
    }
    Map<String,Object> evaluate(Map<String,Object> args) throws Exception {
        StackFrame frame=frames.get(number(args,"frameId",0));if(frame==null)throw new IllegalArgumentException("A current stopped frame is required");
        String expression=text(args,"expression","");if(!expression.matches("[A-Za-z_$][A-Za-z0-9_$]*(?:\\.[A-Za-z_$][A-Za-z0-9_$]*)*"))throw new IllegalArgumentException("Java inspection supports local variables and field paths only");
        String[] path=expression.split("\\.");Value value;
        if(path[0].equals("this"))value=frame.thisObject();
        else {LocalVariable local=frame.visibleVariableByName(path[0]);if(local==null)throw new IllegalArgumentException("Local variable not in scope");value=frame.getValue(local);}
        for(int i=1;i<path.length;i++) {
            if(!(value instanceof ObjectReference object))throw new IllegalArgumentException("Field path does not refer to an object");
            Field field=object.referenceType().fieldByName(path[i]);if(field==null||field.isStatic())throw new IllegalArgumentException("Instance field not found");value=object.getValue(field);
        }
        Map<String,Object> result=variable(expression,value);result.put("result",result.remove("value"));result.remove("name");return result;
    }
    Map<String,Object> resume(String command,Map<String,Object> args) {
        needVM();ThreadReference thread=thread(number(args,"threadId",stoppedThread==null?0:threadId(stoppedThread)));
        for(StepRequest request:new ArrayList<>(vm.eventRequestManager().stepRequests()))vm.eventRequestManager().deleteEventRequest(request);
        if(!command.equals("continue")) {
            int depth=command.equals("next")?StepRequest.STEP_OVER:command.equals("stepIn")?StepRequest.STEP_INTO:StepRequest.STEP_OUT;
            StepRequest step=vm.eventRequestManager().createStepRequest(thread,StepRequest.STEP_LINE,depth);step.addCountFilter(1);
            for(String exclude:List.of("java.*","javax.*","jdk.*","sun.*","com.sun.*"))step.addClassExclusionFilter(exclude);
            step.setSuspendPolicy(EventRequest.SUSPEND_ALL);step.enable();
        }
        int id=threadId(thread);clearStopped();vm.resume();event("continued",obj("threadId",id,"allThreadsContinued",true));return command.equals("continue")?obj("allThreadsContinued",true):obj();
    }
    void shutdown() {
        closing=true;
        try {if(vm!=null)vm.exit(0);}catch(VMDisconnectedException ignored){}
        if(process!=null) {
            try {if(!process.waitFor(1,java.util.concurrent.TimeUnit.SECONDS)){process.destroyForcibly();process.waitFor(1,java.util.concurrent.TimeUnit.SECONDS);}}
            catch(InterruptedException error){Thread.currentThread().interrupt();}
            if(!process.isAlive()&&terminated.compareAndSet(false,true)){event("exited",obj("exitCode",process.exitValue()));event("terminated",obj());}
        }
    }
    Map<String,Object> dispatch(String command,Map<String,Object> args) throws Exception {
        switch(command) {
            case "initialize":return obj("supportsConfigurationDoneRequest",true,"supportsTerminateRequest",true,"supportsEvaluateForHovers",true,"supportsConditionalBreakpoints",false,"exceptionBreakpointFilters",List.of());
            case "launch":startLaunch(args);return obj();
            case "setBreakpoints":return setBreakpoints(args);
            case "setExceptionBreakpoints":if(args.get("filters") instanceof List<?> filters&&!filters.isEmpty())throw new IllegalArgumentException("Exception filters are unsupported");return obj();
            case "configurationDone":needVM();if(configured)throw new IllegalStateException("Configuration already completed");configured=true;clearStopped();vm.resume();return obj();
            case "threads":needVM();List<Object> found=new ArrayList<>();for(ThreadReference thread:vm.allThreads()){if(found.size()>=MAX_CHILDREN)break;if(!appendBounded(found,obj("id",threadId(thread),"name",brief(thread.name(),256))))break;}return obj("threads",found);
            case "stackTrace":needVM();return stackTrace(args);
            case "scopes":StackFrame frame=frames.get(number(args,"frameId",0));if(frame==null)throw new IllegalArgumentException("Expired stack frame");return obj("scopes",List.of(obj("name","Locals","presentationHint","locals","variablesReference",valueId(frame),"expensive",false)));
            case "variables":needVM();return variables(args);
            case "evaluate":needVM();return evaluate(args);
            case "continue":case "next":case "stepIn":case "stepOut":return resume(command,args);
            case "pause":needVM();if(!configured)throw new IllegalStateException("Complete configuration first");if(stoppedThread!=null&&stoppedThread.isSuspended())return obj();vm.suspend();ThreadReference selected=threads.get(number(args,"threadId",0));if(selected==null)for(ThreadReference thread:vm.allThreads())if(thread.name().equals("main")){selected=thread;break;}if(selected==null)throw new IllegalStateException("No live thread to pause");stoppedThread=selected;event("stopped",obj("reason","pause","threadId",threadId(selected),"allThreadsStopped",true));return obj();
            case "disconnect":case "terminate":return obj();
            default:throw new IllegalArgumentException("Unsupported Java DAP command: "+command);
        }
    }
    void run() throws Exception {
        try {
            while(!closing) {
                Map<String,Object> request=read();if(request==null)break;
                if(!"request".equals(request.get("type")))continue;
                String command=text(request,"command","");
                try {
                    synchronized(state){Map<String,Object> body=dispatch(command,request.get("arguments") instanceof Map?map(request.get("arguments")):obj());response(request,body);if(command.equals("initialize"))event("initialized",obj());if(command.equals("disconnect")||command.equals("terminate"))shutdown();}
                }catch(Exception error) {
                    send(obj("type","response","request_seq",request.get("seq"),"command",command,"success",false,"message",brief(error.getClass().getSimpleName()+": "+String.valueOf(error.getMessage()),1024)));
                }
            }
        }finally{shutdown();}
    }
    public static void main(String[] args) {
        try {new OlympiadJavaDAP().run();}
        catch(Exception error){System.err.println("Java DAP: "+brief(error.toString(),1024));System.exit(1);}
    }

    // Strict bounded JSON codec: no reflection, class loading, external library or executable input.
    static final class Json {
        final String s;int i;
        Json(String s){this.s=s;}
        Object parse(){Object value=value(0);space();if(i!=s.length())throw new IllegalArgumentException("Trailing JSON");return value;}
        void space(){while(i<s.length()&&Character.isWhitespace(s.charAt(i)))i++;}
        char take(){if(i>=s.length())throw new IllegalArgumentException("Truncated JSON");return s.charAt(i++);}
        Object value(int depth) {
            if(depth>48)throw new IllegalArgumentException("JSON nesting limit");space();char c=take();
            if(c=='"')return string();
            if(c=='{') {Map<String,Object> m=new LinkedHashMap<>();space();if(i<s.length()&&s.charAt(i)=='}'){i++;return m;}while(true){space();if(take()!='"')throw new IllegalArgumentException("Object key required");String key=string();space();if(take()!=':')throw new IllegalArgumentException("Colon required");if(m.containsKey(key))throw new IllegalArgumentException("Duplicate JSON key");m.put(key,value(depth+1));space();char end=take();if(end=='}')return m;if(end!=',')throw new IllegalArgumentException("Comma required");}}
            if(c=='[') {List<Object> a=new ArrayList<>();space();if(i<s.length()&&s.charAt(i)==']'){i++;return a;}while(true){a.add(value(depth+1));space();char end=take();if(end==']')return a;if(end!=',')throw new IllegalArgumentException("Comma required");}}
            if(c=='t'&&s.startsWith("rue",i)){i+=3;return true;}if(c=='f'&&s.startsWith("alse",i)){i+=4;return false;}if(c=='n'&&s.startsWith("ull",i)){i+=3;return null;}
            int start=i-1;while(i<s.length()&&"0123456789+-.eE".indexOf(s.charAt(i))>=0)i++;
            String number=s.substring(start,i);if(!number.matches("-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?"))throw new IllegalArgumentException("Invalid JSON value");
            if(number.indexOf('.')>=0||number.indexOf('e')>=0||number.indexOf('E')>=0)return Double.valueOf(number);return Long.valueOf(number);
        }
        String string() {
            StringBuilder result=new StringBuilder();while(true){char c=take();if(c=='"')return result.toString();if(c<32)throw new IllegalArgumentException("Control character in JSON");if(c!='\\'){result.append(c);continue;}char escape=take();switch(escape){case '"':case '\\':case '/':result.append(escape);break;case 'b':result.append('\b');break;case 'f':result.append('\f');break;case 'n':result.append('\n');break;case 'r':result.append('\r');break;case 't':result.append('\t');break;case 'u':if(i+4>s.length())throw new IllegalArgumentException("Truncated Unicode");result.append((char)Integer.parseInt(s.substring(i,i+4),16));i+=4;break;default:throw new IllegalArgumentException("Invalid escape");}}
        }
        static String encode(Object value) {
            if(value==null)return "null";if(value instanceof Number||value instanceof Boolean)return value.toString();
            if(value instanceof String text){StringBuilder out=new StringBuilder("\"");for(int n=0;n<text.length();n++){char c=text.charAt(n);switch(c){case '"':out.append("\\\"");break;case '\\':out.append("\\\\");break;case '\n':out.append("\\n");break;case '\r':out.append("\\r");break;case '\t':out.append("\\t");break;default:if(c<32||Character.isSurrogate(c))out.append(String.format("\\u%04x",(int)c));else out.append(c);}}return out.append('"').toString();}
            if(value instanceof Map<?,?> map){List<String> pairs=new ArrayList<>();for(var e:map.entrySet())pairs.add(encode(e.getKey().toString())+":"+encode(e.getValue()));return "{"+String.join(",",pairs)+"}";}
            if(value instanceof Iterable<?> list){List<String> items=new ArrayList<>();for(Object item:list)items.add(encode(item));return "["+String.join(",",items)+"]";}
            throw new IllegalArgumentException("Unsupported JSON value");
        }
    }
}
