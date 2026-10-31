package com.fateforge.creocli.service;

import com.ptc.pfc.pfcArgument.Arguments;
import com.ptc.pfc.pfcArgument.pfcArgument;
import com.ptc.pfc.pfcModel.Models;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.util.Map;
import java.util.concurrent.atomic.AtomicReference;

/** Fixed native exit of one explicitly owned empty session; no generic PID operation. */
final class OwnedSessionExit {
    static final String FUNCTION="creo_cli_session_exit";
    static final String ENTRYPOINT="ProEngineerEnd";
    static final String DISPATCH_CONTRACT="queued_native_command_v1";
    private static final String DISPATCH_COMMAND="CreoCliOwnedExitDeferred";
    private static final AtomicReference<Ticket> PENDING=new AtomicReference<>();
    private static final AtomicReference<Map<String,Object>> READER_STOP=new AtomicReference<>();
    private static final AtomicReference<ReadWatch> ACTIVE_READ=new AtomicReference<>();
    private static final ThreadLocal<ReadWatch> READ=new ThreadLocal<>();
    private static final class ReadWatch {
        final Map<String,Object> identity;final long deadline;
        volatile boolean entered,cancelled;
        ReadWatch(Map<String,Object> identity,long remaining) {
            this.identity=new java.util.LinkedHashMap<>(identity);
            this.deadline=System.nanoTime()+remaining*1_000_000L;
        }
    }
    static final class ReadScope implements AutoCloseable {
        final ReadWatch watch;
        ReadScope(ReadWatch watch){this.watch=watch;}
        public void close(){if(watch!=null){READ.remove();ACTIVE_READ.compareAndSet(watch,null);}}
    }
    static ReadScope readScope(String operation,Map<String,Object> request,Map<String,Object> identity) {
        if(!operation.equals("session.exit-state")&&!operation.equals("session.exit"))return new ReadScope(null);
        String key=operation.equals("session.exit-state")?"read_deadline_epoch_ms":"deadline_epoch_ms";
        long left=Long.parseLong(Json.string(request,key))-System.currentTimeMillis();
        if(left<1||left>30000)throw new Failures.Refusal("E_UNAVAILABLE","owned-exit reader deadline invalid");
        ReadWatch watch=new ReadWatch(identity,left);
        if(!ACTIVE_READ.compareAndSet(null,watch))throw new Failures.Refusal("E_BUSY","owned-exit reader already active");
        READ.set(watch);return new ReadScope(watch);
    }
    static void readerTimedOut(Map<String,Object> identity) {
        ReadWatch watch=ACTIVE_READ.get();
        if(watch==null||identity==null||!java.util.Objects.equals(identity.get("diagnostic_request_id"),watch.identity.get("diagnostic_request_id")))return;
        watch.cancelled=true;
        if(watch.entered)READER_STOP.compareAndSet(null,Json.map("stage","owned_exit_reader_wait_expired",
                "started",true,"retryable",false,"identity",watch.identity));
    }
    private static void readerBoundary() {
        ReadWatch watch=READ.get();
        if(READER_STOP.get()!=null)throw new Failures.Refusal("E_UNAVAILABLE","owned-exit SDK reader stopped this generation");
        if(watch!=null&&(watch.cancelled||System.nanoTime()-watch.deadline>=0)) {
            if(watch.entered)READER_STOP.compareAndSet(null,Json.map("stage","owned_exit_reader_boundary_expired",
                    "started",true,"retryable",false,"identity",watch.identity));
            throw new Failures.Refusal("E_UNAVAILABLE","owned-exit reader expired; no further SDK");
        }
    }
    private static void readerEnteringSDK(){readerBoundary();ReadWatch watch=READ.get();if(watch!=null)watch.entered=true;}
    static boolean readerInFlight(){ReadWatch watch=ACTIVE_READ.get();return watch!=null&&watch.entered;}
    static Service.ToolkitFailure preflightFailure(Throwable failure) {
        ReadWatch watch=READ.get();
        if(watch!=null&&watch.entered&&(watch.cancelled||System.nanoTime()-watch.deadline>=0))
            READER_STOP.compareAndSet(null,Json.map("stage","owned_exit_reader_failed_after_deadline",
                    "started",true,"retryable",false,"identity",watch.identity));
        boolean stopped=READER_STOP.get()!=null;
        String code=failure instanceof Failures.Refusal?((Failures.Refusal)failure).code:"E_CREO";
        return new Service.ToolkitFailure(Json.map("code",stopped?"E_UNAVAILABLE":code,
                "message","owned-exit native preflight failed; preserve the original instance",
                "cause_type",failure.getClass().getName(),"reader_started",watch!=null&&watch.entered,
                "started",stopped,"mutation_started",false,"retryable",false,"reader_stop",READER_STOP.get()));
    }
    private OwnedSessionExit() { }
    private static final class Ticket {
        final Map<String,Object> request,identity;
        final long deadline;
        final Path runtime;
        volatile String phase="prepared";
        volatile boolean nativeInvocationStarted;
        volatile boolean knownFailure;
        Ticket(Map<String,Object> request,Map<String,Object> identity,Path runtime,long budget) {
            this.request=java.util.Collections.unmodifiableMap(new java.util.LinkedHashMap<>(request));
            this.identity=java.util.Collections.unmodifiableMap(new java.util.LinkedHashMap<>(identity));this.runtime=runtime;
            this.deadline=System.nanoTime()+budget*1_000_000L;
        }
        String operation() {return (String)request.get("operation_id");}
        Path file(String kind) {return runtime.resolve("owned-exit-"+operation()+"."+kind+".json");}
    }
    static boolean blocksQueue() {return PENDING.get()!=null||READER_STOP.get()!=null;}
    /** Pure Java: after C queues the fixed command, immediately leave OnTimer. */
    static boolean nativeCommandQueued() {
        Ticket t=PENDING.get();return t!=null&&"native_command_queued".equals(t.phase);
    }
    static Map<String,Object> status() {
        Ticket t=PENDING.get();
        return Json.map("pending",t!=null,"phase",t==null?null:t.phase,"entrypoint",ENTRYPOINT,
                "operation_id",t==null?null:t.operation(),"dispatch_contract",DISPATCH_CONTRACT,
                "reader_stop",READER_STOP.get(),
                "reader_in_flight",readerInFlight(),"automatic_retry",false);
    }
    private static void check(Ticket t) {
        NativeReadTrace.check();
        if(t!=PENDING.get() || !"preflight".equals(t.phase) || System.nanoTime()-t.deadline>=0
                || !Service.instanceIdForReadback().equals(t.request.get("service_instance_id")))
            throw new Failures.Refusal("E_UNAVAILABLE","owned-exit ticket expired or changed generation; no further SDK call");
    }
    private static Path runtime(Map<String,Object> request) throws Exception {
        Path path=Path.of(Json.string(request,"runtime_directory")).toAbsolutePath().normalize();
        if(!path.equals(Service.stateDirectory().toAbsolutePath().normalize()) || !Files.isDirectory(path))
            throw new Failures.Refusal("E_CONFLICT","owned-exit runtime differs from this service");
        for(Path parent=path;parent!=null;parent=parent.getParent())
            if(Files.isSymbolicLink(parent) || !parent.toRealPath().equals(parent.toAbsolutePath().normalize()))
                throw new Failures.Refusal("E_FORBIDDEN","owned-exit runtime redirects are refused");
        return path;
    }
    private static void expected(Map<String,Object> request) throws Exception {
        if(!Service.instanceIdForReadback().equals(Json.string(request,"service_instance_id"))
                || !BuildIdentity.SOURCE_SHA256.equals(Json.string(request,"source_sha256")))
            throw new Failures.Refusal("E_CONFLICT","owned-exit source or generation differs");
        if(Json.integer(request,"expected_pid")<1
                || !Json.string(request,"expected_creation_filetime").matches("[1-9][0-9]{0,19}"))
            throw new Failures.Refusal("E_VALIDATION","exact owned native process identity required");
        runtime(request);
    }
    static Map<String,Object> state(Map<String,Object> request) throws Exception {
        return state(request,()->{NativeReadTrace.check();readerBoundary();});
    }
    private static Map<String,Object> dispatchState(Map<String,Object> request) {
        Path path=Service.stateDirectory().toAbsolutePath().normalize().resolve("native-owned-exit-dispatch.json");
        try {
            byte[] raw=read(path);
            Map<String,Object> value=Json.object(Json.parse(new String(raw,StandardCharsets.UTF_8)),"native exit registration");
            boolean available="1.0".equals(value.get("schema_version"))
                    &&DISPATCH_CONTRACT.equals(value.get("dispatch_contract"))
                    &&DISPATCH_COMMAND.equals(value.get("command"))
                    &&"uiProeImmediate".equals(value.get("priority"))
                    &&Boolean.TRUE.equals(value.get("registered"))
                    &&value.get("registration_status") instanceof Number
                    &&((Number)value.get("registration_status")).doubleValue()==0
                    &&value.get("native_pid") instanceof Number
                    &&((Number)value.get("native_pid")).doubleValue()==((Number)request.get("expected_pid")).doubleValue()
                    &&request.get("expected_creation_filetime").equals(value.get("native_creation_filetime"));
            return Json.map("available",available,"contract",DISPATCH_CONTRACT,"file",path.toString(),
                    "registration",value,"source","process-private native initialization witness",
                    "qualification","registration is not execution or normal-exit proof");
        }catch(Throwable failure) {
            return Json.map("available",false,"contract",DISPATCH_CONTRACT,"file",path.toString(),
                    "cause_type",failure.getClass().getName(),"source","native registration witness unavailable",
                    "qualification","no inline or old-component fallback");
        }
    }
    private static Map<String,Object> state(Map<String,Object> request,Runnable guard) throws Exception {
        guard.run();
        expected(request);
        Map<String,Object> dispatch=dispatchState(request);
        boolean nativeAvailable=Service.loadedSketchLibrary()!=null&&Boolean.TRUE.equals(dispatch.get("available"));
        if(!nativeAvailable)return Json.map("models_complete",false,"raw_model_count",null,"raw_models",null,
                "native_exit_available",false,"native_exit_dispatch",dispatch,
                "service_instance_id",Service.instanceIdForReadback(),"source_sha256",BuildIdentity.SOURCE_SHA256,
                "source","fixed native command registration unavailable; no model getter entered");
        guard.run();
        readerEnteringSDK();
        var session=NativeReadTrace.call("pfcGlobal.GetProESession(owned-exit)",Creo::session);
        guard.run();
        readerEnteringSDK();
        Models models=NativeReadTrace.call("Session.ListModels(raw owned-exit empty inventory)",session::ListModels);
        guard.run();
        readerEnteringSDK();
        int count=models==null?0:models.getarraysize();
        guard.run();
        return Json.map("models_complete",count==0,"raw_model_count",count,
                "raw_models",count==0?java.util.List.of():null,
                "native_exit_available",true,
                "native_exit_dispatch",dispatch,
                "service_instance_id",Service.instanceIdForReadback(),"source_sha256",BuildIdentity.SOURCE_SHA256,
                "source","Session.ListModels without internal/2D filtering; loaded fixed DLL function required");
    }
    static Map<String,Object> prepare(Map<String,Object> request,Map<String,Object> identity) throws Exception {
        expected(request);
        String op=Json.string(request,"operation_id");
        if(!op.matches("[a-f0-9]{32}"))throw new Failures.Refusal("E_VALIDATION","fixed operation identifier required");
        int ttl=Json.integer(request,"ttl_ms");
        long epoch=Long.parseLong(Json.string(request,"deadline_epoch_ms"));
        long left=epoch-System.currentTimeMillis();
        if(ttl<1 || ttl>30000 || left<1 || left>ttl)
            throw new Failures.Refusal("E_VALIDATION","owned-exit deadline is expired or outside its bound");
        if(!Json.string(request,"deadline_tick_ms").matches("[1-9][0-9]{0,19}"))
            throw new Failures.Refusal("E_VALIDATION","bounded shared Windows monotonic deadline required");
        if(Service.ownedExitOtherWorkQueued())throw new Failures.Refusal("E_BUSY","other queued calls prevent owned-session exit");
        Path runtime=runtime(request);
        Map<String,Object> intent=Json.object(Json.parse(new String(read(runtime.resolve("owned-exit-"+op+".intent.json")),StandardCharsets.UTF_8)),"durable exit intent");
        if(!ENTRYPOINT.equals(intent.get("entrypoint")))throw new Failures.Refusal("E_CONFLICT","durable native entrypoint differs");
        for(String key:java.util.List.of("operation_id","service_instance_id","source_sha256","runtime_directory","expected_creation_filetime"))
            if(!java.util.Objects.equals(request.get(key),intent.get(key)))throw new Failures.Refusal("E_CONFLICT","durable owned-exit intent differs: "+key);
        if(!(intent.get("expected_pid") instanceof Number)
                || ((Number)request.get("expected_pid")).doubleValue()!=((Number)intent.get("expected_pid")).doubleValue())
            throw new Failures.Refusal("E_CONFLICT","durable owned native PID differs");
        Runnable preGuard=()-> {
            NativeReadTrace.check();
            long remaining=epoch-System.currentTimeMillis();
            if(remaining<1 || remaining>ttl)throw new Failures.Refusal("E_UNAVAILABLE","owned-exit preflight deadline elapsed");
        };
        Map<String,Object> empty=state(request,preGuard);
        if(!Boolean.TRUE.equals(empty.get("models_complete")) || !Boolean.TRUE.equals(empty.get("native_exit_available")))
            throw new Failures.Refusal("E_CONFLICT","full native backend and raw empty session required");
        left=epoch-System.currentTimeMillis();
        if(left<1 || left>ttl)throw new Failures.Refusal("E_UNAVAILABLE","owned-exit request expired during preflight");
        Ticket t=new Ticket(request,identity,runtime,left);
        if(!PENDING.compareAndSet(null,t))throw new Failures.Refusal("E_BUSY","another owned-exit ticket exists");
        return Json.map("status","request_scheduled","operation_id",op,"entrypoint",ENTRYPOINT,
                "not_completed",true,"runtime_directory",runtime.toString());
    }
    /** Called only after HttpExchange response close/flush returned successfully. */
    static void arm(String operation) {
        Ticket t=PENDING.get();
        if(t!=null) synchronized(t) {
            if(t.operation().equals(operation) && "prepared".equals(t.phase)) {
                if(System.nanoTime()-t.deadline>=0)cancel(operation,"response_completed_after_deadline");
                else t.phase="armed";
            }
        }
    }
    static void cancel(String operation,String reason) {
        Ticket t=PENDING.get();
        if(t!=null) synchronized(t) {
            if(t.operation().equals(operation) && ("prepared".equals(t.phase)||"armed".equals(t.phase)||"preflight".equals(t.phase))) {
                t.phase="cancelled";
                try {write(t.file("cancelled"),Json.map("status","cancelled_before_native","operation_id",operation,"reason",reason));}
                catch(Throwable ignored) { /* no SDK or retry */ }
            }
        }
    }
    /** Once true, ordinary queue wrappers refuse without entering any SDK getter. */
    static boolean pump() {
        Ticket t=PENDING.get();
        if(t==null)return READER_STOP.get()!=null;
        if("prepared".equals(t.phase)) {
            if(System.nanoTime()-t.deadline>=0)cancel(t.operation(),"http_response_not_completed_before_deadline");
            return true;
        }
        synchronized(t) {
            if(!"armed".equals(t.phase))return true;
            t.phase="preflight";
        }
        try(NativeReadTrace.Scope trace=NativeReadTrace.begin(t.identity)) {
            check(t);
            Map<String,Object> empty=state(t.request,()->check(t));
            check(t);
            if(!Boolean.TRUE.equals(empty.get("models_complete")))throw new Failures.Refusal("E_CONFLICT","a model appeared before native exit");
            Arguments in=NativeReadTrace.call("Arguments.create(owned-exit)",Arguments::create);
            check(t);
            integerArgument(t,in,"expected_pid",((Number)t.request.get("expected_pid")).intValue());
            integerArgument(t,in,"raw_java_model_count",0);
            for(String key:java.util.List.of("expected_creation_filetime","operation_id","service_instance_id","runtime_directory","deadline_tick_ms")) {
                check(t);
                var value=NativeReadTrace.call("CreateStringArgValue(owned-exit)",()->pfcArgument.CreateStringArgValue((String)t.request.get(key)));
                check(t);
                var argument=NativeReadTrace.call("Argument_Create(owned-exit)",()->pfcArgument.Argument_Create(key,value));
                check(t);
                NativeReadTrace.run("Arguments.append(owned-exit)",()->in.append(argument));
            }
            check(t);
            var contractValue=NativeReadTrace.call("CreateStringArgValue(owned-exit dispatch contract)",()->pfcArgument.CreateStringArgValue(DISPATCH_CONTRACT));
            check(t);
            var contractArgument=NativeReadTrace.call("Argument_Create(owned-exit dispatch contract)",()->pfcArgument.Argument_Create("dispatch_contract",contractValue));
            check(t);
            NativeReadTrace.run("Arguments.append(owned-exit dispatch contract)",()->in.append(contractArgument));
            check(t);
            var library=Service.loadedSketchLibrary();
            check(t);
            if(library==null)throw new Failures.Refusal("E_UNAVAILABLE","fixed native exit DLL unavailable");
            synchronized(t) {check(t);t.phase="invoking";t.nativeInvocationStarted=true;}
            NativeReadTrace.call("Dll.ExecuteFunction(creo_cli_session_exit/queue only)",()->library.ExecuteFunction(FUNCTION,in));
            t.phase="native_command_queued";
            // This is only queue acknowledgement. Do not inspect SDK output or write
            // a returned witness; End runs later in the registered native command.
        }catch(Throwable failure) {
            t.phase="failed";
            boolean typedCommunication=communicationFailure(failure.getClass());
            t.knownFailure=!typedCommunication;
            try {
                String enteredHash=enteredHash(t);
                boolean communication=enteredHash!=null && typedCommunication;
                if(!communication)t.knownFailure=true;
                write(t.file(communication?"unavailable":"failed"),Json.map("status",communication?"native_return_unavailable_after_entry":"exit_dispatch_failed",
                    "operation_id",t.operation(),"service_instance_id",t.request.get("service_instance_id"),
                    "entered_sha256",enteredHash,"cause_type",failure.getClass().getName(),
                    "communication_kind",communication?communicationKind(failure.getClass()):null,"automatic_retry",false));
            }
            catch(Throwable ignored) {t.knownFailure=true; /* retain unknown; never another SDK call */ }
        }
        return true;
    }
    private static void integerArgument(Ticket t,Arguments in,String key,int number) throws Exception {
        check(t);
        var value=NativeReadTrace.call("CreateIntArgValue(owned-exit)",()->pfcArgument.CreateIntArgValue(number));
        check(t);
        var argument=NativeReadTrace.call("Argument_Create(owned-exit)",()->pfcArgument.Argument_Create(key,value));
        check(t);
        NativeReadTrace.run("Arguments.append(owned-exit)",()->in.append(argument));
    }
    /** Pure Java type inspection only; no native exception detail getter or generic cause fallback. */
    static boolean communicationFailure(Class<?> type) {
        return communicationKind(type)!=null;
    }
    private static String communicationKind(Class<?> type) {
        if(type==null)return null;
        String name=type.getName();
        if(name.equals("com.ptc.pfc.pfcExceptions.XToolkitCommError")
                || name.equals("com.ptc.pfc.pfcExceptions.XToolkitAppCommunicationFailure"))return name;
        for(Class<?> implemented:type.getInterfaces()) {
            String result=communicationKind(implemented);if(result!=null)return result;
        }
        return communicationKind(type.getSuperclass());
    }
    static boolean normalStop() {
        Ticket t=PENDING.get();
        if(t==null || !t.nativeInvocationStarted || t.knownFailure)return false;
        try {
            String hash=enteredHash(t);
            if(hash==null)return false;
            if(Files.exists(t.file("returned"))) {
                if(!Files.isRegularFile(t.file("returned"),java.nio.file.LinkOption.NOFOLLOW_LINKS))return false;
                Map<String,Object> returned=Json.object(Json.parse(new String(read(t.file("returned")),StandardCharsets.UTF_8)),"native returned witness");
                if(!Boolean.TRUE.equals(returned.get("api_called"))
                        || !(returned.get("native_return_code") instanceof Number)
                        || ((Number)returned.get("native_return_code")).doubleValue()!=0)return false;
            }
            write(t.file("stop"),Json.map("status","service_stop_after_owned_native_entry",
                    "operation_id",t.operation(),"service_instance_id",t.request.get("service_instance_id"),
                    "native_pid",t.request.get("expected_pid"),"native_creation_filetime",t.request.get("expected_creation_filetime"),
                    "entered_sha256",hash,"source","Service.stop lifecycle callback, accepted only jointly with held xtop signal/exitcode0"));
        }catch(Throwable ignored) { /* missing proof is unknown, never success */ }
        return true; // a terminating session must not receive timer Stop/Destroy SDK calls
    }
    /** Cleanup safety gate only; this Java flag is never evidence that C entered ProEngineerEnd. */
    static boolean invocationStarted() {
        Ticket t=PENDING.get();return t!=null && t.nativeInvocationStarted;
    }
    private static String enteredHash(Ticket t) throws Exception {
        if(!Files.isRegularFile(t.file("entered"),java.nio.file.LinkOption.NOFOLLOW_LINKS)
                || Files.isSymbolicLink(t.file("entered")))return null;
        byte[] raw=read(t.file("entered"));
        Map<String,Object> entered=Json.object(Json.parse(new String(raw,StandardCharsets.UTF_8)),"native entered witness");
        if(!t.operation().equals(entered.get("operation_id"))
                || !t.request.get("service_instance_id").equals(entered.get("service_instance_id"))
                || !ENTRYPOINT.equals(entered.get("entrypoint"))
                || !"native_entered".equals(entered.get("status"))
                || !DISPATCH_CONTRACT.equals(entered.get("dispatch_contract"))
                || !"registered_native_command".equals(entered.get("dispatch_context"))
                || !(entered.get("native_pid") instanceof Number)
                || ((Number)entered.get("native_pid")).doubleValue()!=((Number)t.request.get("expected_pid")).doubleValue()
                || !t.request.get("expected_creation_filetime").equals(entered.get("native_creation_filetime"))
                || !Boolean.TRUE.equals(entered.get("empty_models"))
                || !Boolean.TRUE.equals(entered.get("raw_java_empty_checked"))
                || !Boolean.TRUE.equals(entered.get("native_known_types_empty")))return null;
        StringBuilder hash=new StringBuilder();
        for(byte b:MessageDigest.getInstance("SHA-256").digest(raw))hash.append(String.format("%02x",b));
        return hash.toString();
    }
    private static void write(Path path,Map<String,Object> data) throws Exception {
        byte[] bytes=(Json.write(data)+"\n").getBytes(StandardCharsets.UTF_8);
        try(FileChannel file=FileChannel.open(path,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE)) {
            ByteBuffer buffer=ByteBuffer.wrap(bytes);
            while(buffer.hasRemaining())file.write(buffer);
            file.force(true);
        }
    }
    private static byte[] read(Path path) throws Exception {
        if(!Files.isRegularFile(path,java.nio.file.LinkOption.NOFOLLOW_LINKS) || Files.isSymbolicLink(path))
            throw new java.io.IOException("owned-exit evidence is not a regular local file");
        try(var input=Files.newInputStream(path,java.nio.file.LinkOption.NOFOLLOW_LINKS)) {
            byte[] raw=input.readNBytes(16385);
            if(raw.length>16384)throw new java.io.IOException("owned-exit evidence exceeds its bound");
            return raw;
        }
    }
}
