package com.fateforge.creocli.service;

import com.ptc.pfc.pfcArgument.Arguments;
import com.ptc.pfc.pfcArgument.pfcArgument;
import com.sun.nio.file.ExtendedOpenOption;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/** One fixed ordinary native current-close command. No activation, exit or generic macro. */
final class ModelCurrentClose {
    static final String CONTRACT="model_current_close_v2";
    static final String COMMAND="CreoCliModelCurrentCloseDeferred";
    static final String FUNCTION="creo_cli_model_current_close";
    private ModelCurrentClose() { }

    static String sha256(String value) throws Exception {
        return java.util.HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                .digest(value.getBytes(StandardCharsets.UTF_8)));
    }
    static Path directRuntime(Path path) throws IOException {
        path=path.toAbsolutePath().normalize();
        if(!Files.isDirectory(path,LinkOption.NOFOLLOW_LINKS))throw new IOException("close runtime is not a direct directory");
        for(Path parent=path;parent!=null;parent=parent.getParent())
            if(Files.isSymbolicLink(parent)||!parent.toRealPath().equals(parent.toAbsolutePath().normalize()))
                throw new IOException("close runtime redirects are refused");
        return path;
    }
    static Map<String,Object> read(Path path) throws Exception {
        if(!Files.isRegularFile(path,LinkOption.NOFOLLOW_LINKS)||Files.isSymbolicLink(path)
                ||Files.size(path)>16_384)throw new IOException("bounded direct close witness required");
        return Json.object(Json.parse(Files.readString(path,StandardCharsets.UTF_8)),"native close witness");
    }
    static void writeNew(Path path,Map<String,Object> value) throws Exception {
        try(FileChannel channel=FileChannel.open(path,StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,
                LinkOption.NOFOLLOW_LINKS,ExtendedOpenOption.NOSHARE_WRITE,ExtendedOpenOption.NOSHARE_DELETE)){
            ByteBuffer bytes=StandardCharsets.UTF_8.encode(Json.write(value)+"\n");
            while(bytes.hasRemaining())channel.write(bytes);
            channel.force(true);
        }
    }
    static final class Binding {
        final Path runtime;
        final Map<String,Object> expected;
        final String callbackProof;
        final String dispatchRefusalProof;
        Binding(Path runtime,Map<String,Object> expected){
            this.runtime=runtime;this.expected=Map.copyOf(expected);
            java.security.SecureRandom random=new java.security.SecureRandom();
            byte[] secret=new byte[32];random.nextBytes(secret);
            callbackProof=java.util.HexFormat.of().formatHex(secret);
            String refusal;
            do{random.nextBytes(secret);refusal=java.util.HexFormat.of().formatHex(secret);}
            while(refusal.equals(callbackProof));
            dispatchRefusalProof=refusal;
        }
        Path file(String suffix){return runtime.resolve("model-close-"+expected.get("close_ticket_id")+"."+suffix);}
    }
    /** Always on for model-close, independently of optional native-read diagnostics. */
    static final class Journal implements AutoCloseable {
        final FileChannel channel;
        final Map<String,Object> identity;
        long sequence;
        private Journal(FileChannel channel,Map<String,Object> identity){this.channel=channel;this.identity=identity;}
        static Journal open(ModelCloseLifecycle.Ticket ticket,Map<String,Object> request) throws Exception {
            Path runtime=directRuntime(Service.stateDirectory());
            Map<String,Object> identity=Json.map("close_ticket_id",ticket.closeId,
                    "service_instance_id",ticket.generation,"service_source_sha256",BuildIdentity.SOURCE_SHA256,
                    "request_sha256",ticket.requestSha256,"model",Json.string(request,"model"),
                    "operation","model.close","diagnostic_request_id",ticket.identity.get("diagnostic_request_id"),
                    "cli_invocation_id",ticket.identity.get("cli_invocation_id"));
            Map<String,Object> expected=Json.object(request.get("expected_session"),"expected_session");
            identity.put("expected_target",ModelCloseLifecycle.modelRow(expected,Json.string(request,"model")));
            identity.put("expected_windows",ModelCloseLifecycle.rows(expected,"windows"));
            return create(runtime.resolve("model-close-"+ticket.closeId+".java.jsonl"),identity);
        }
        static Journal create(Path path,Map<String,Object> identity) throws Exception {
            directRuntime(path.getParent());
            FileChannel channel=FileChannel.open(path,
                    StandardOpenOption.CREATE_NEW,StandardOpenOption.WRITE,LinkOption.NOFOLLOW_LINKS,
                    ExtendedOpenOption.NOSHARE_WRITE,ExtendedOpenOption.NOSHARE_DELETE);
            Journal journal=new Journal(channel,identity);
            try{journal.event("lifecycle_begin","stage",null);return journal;}
            catch(Throwable failure){channel.close();throw failure;}
        }
        synchronized void event(String event,String call,String cause) throws IOException {
            Map<String,Object> row=new LinkedHashMap<>(identity);
            row.put("sequence",++sequence);row.put("time",Instant.now().toString());
            row.put("event",event);row.put("call",call);if(cause!=null)row.put("cause_type",cause);
            ByteBuffer bytes=StandardCharsets.UTF_8.encode(Json.write(row)+"\n");
            while(bytes.hasRemaining())channel.write(bytes);
            channel.force(true); // A begin must be durable before its SDK call is entered.
        }
        public synchronized void close() throws IOException {channel.close();}
    }
    static Binding binding(Path runtime,ModelCloseLifecycle.Ticket ticket,String model,String target,String empty,
                           Map<String,Object> registration) throws Exception {
        if(!"1.0".equals(registration.get("schema_version"))
                ||!CONTRACT.equals(registration.get("dispatch_contract"))
                ||!numberEquals(registration.get("input_argument_count"),10)
                ||!COMMAND.equals(registration.get("command"))
                ||!"uiProeImmediate".equals(registration.get("priority"))
                ||!Boolean.TRUE.equals(registration.get("registered"))
                ||!numberEquals(registration.get("registration_status"),0)
                ||!(registration.get("native_pid") instanceof Number)
                ||((Number)registration.get("native_pid")).longValue()<1
                ||!(registration.get("native_creation_filetime") instanceof String)
                ||!((String)registration.get("native_creation_filetime")).matches("[1-9][0-9]{0,19}"))
            throw new Failures.Refusal("E_UNAVAILABLE","fixed ordinary native current-close registration unavailable");
        return new Binding(runtime,Json.map("close_ticket_id",ticket.closeId,"service_instance_id",ticket.generation,
                "request_sha256",ticket.requestSha256,"target_window",Integer.parseInt(target),
                "empty_window",Integer.parseInt(empty),"model",model,
                "native_pid",registration.get("native_pid"),
                "native_creation_filetime",registration.get("native_creation_filetime")));
    }
    static boolean numberEquals(Object value,long expected){
        return value instanceof Number && ((Number)value).doubleValue()==expected;
    }
    static void queue(ModelCloseLifecycle.Ticket ticket,String model,String target,String empty) throws Throwable {
        ModelCloseLifecycle.boundary();
        Path runtime=directRuntime(Service.stateDirectory());
        if(!model.matches("[a-z0-9_]{1,80}\\.prt"))
            throw new Failures.Refusal("E_UNSUPPORTED","fixed current-close requires one ordinary part name");
        var library=Service.loadedSketchLibrary();
        if(library==null)throw new Failures.Refusal("E_UNAVAILABLE","fixed current-close DLL unavailable");
        ticket.nativeClose=binding(runtime,ticket,model.substring(0,model.length()-4),target,empty,
                read(runtime.resolve("native-model-close-dispatch.json")));
        Arguments in=ModelCloseLifecycle.call("close.Arguments.create",Arguments::create);
        integer(in,"target_window",Integer.parseInt(target));integer(in,"empty_window",Integer.parseInt(empty));
        for(String key:java.util.List.of("model","close_ticket_id","service_instance_id","request_sha256"))
            string(in,key,(String)ticket.nativeClose.expected.get(key));
        string(in,"runtime_directory",runtime.toString());
        string(in,"callback_proof",ticket.nativeClose.callbackProof);
        long remaining=(ticket.deadline-System.nanoTime())/1_000_000L;
        if(remaining<1)throw new Failures.Refusal("E_UNAVAILABLE","current-close expired before native dispatch");
        integer(in,"ttl_ms",(int)Math.min(30_000L,remaining));
        string(in,"dispatch_refusal_proof",ticket.nativeClose.dispatchRefusalProof);
        var returned=ModelCloseLifecycle.call("close.Dll.ExecuteFunction(queue fixed current-close)",()->library.ExecuteFunction(FUNCTION,in));
        if(returned==null)throw new Failures.Refusal("E_VERIFY_INCOMPLETE","native current-close function result absent");
        dispatchReturned(ticket,returned::GetFunctionReturn);
        // On ACK this inspected plain files only; return to Creo before another SDK call.
    }
    static void integer(Arguments arguments,String key,int value) throws Throwable {
        var arg=ModelCloseLifecycle.call("close.CreateIntArgValue",()->pfcArgument.CreateIntArgValue(value));
        var item=ModelCloseLifecycle.call("close.Argument_Create",()->pfcArgument.Argument_Create(key,arg));
        ModelCloseLifecycle.call("close.Arguments.append",()->{arguments.append(item);return null;});
    }
    static void string(Arguments arguments,String key,String value) throws Throwable {
        var arg=ModelCloseLifecycle.call("close.CreateStringArgValue",()->pfcArgument.CreateStringArgValue(value));
        var item=ModelCloseLifecycle.call("close.Argument_Create",()->pfcArgument.Argument_Create(key,arg));
        ModelCloseLifecycle.call("close.Arguments.append",()->{arguments.append(item);return null;});
    }
    /** Only this authenticated C path proves that the queue API was never entered. */
    static final class PrequeueRefusal extends RuntimeException {
        final Binding binding;
        final int status;
        final String reason;
        PrequeueRefusal(Binding binding,int status,String reason){
            super("native current-close refused before queue entry: "+reason);
            this.binding=binding;this.status=status;this.reason=reason;
        }
    }
    static boolean proofEquals(String expected,Object actual){
        return actual instanceof String && ((String)actual).matches("[a-f0-9]{64}")
                && MessageDigest.isEqual(expected.getBytes(StandardCharsets.US_ASCII),
                        ((String)actual).getBytes(StandardCharsets.US_ASCII));
    }
    static void requireBinding(Binding binding,Map<String,Object> value){
        for(String key:binding.expected.keySet())
            if(!ModelCloseLifecycle.equivalent(binding.expected.get(key),value.get(key)))
                throw new Failures.Refusal("E_VERIFY_INCOMPLETE","native close witness identity differs: "+key);
    }
    /** A FunctionReturn getter is a new CIP transport. Never enter it on ACK/unknown. */
    static void dispatchReturned(ModelCloseLifecycle.Ticket ticket,ModelCloseLifecycle.Read<Integer> returnCode)throws Throwable {
        ModelCloseLifecycle.boundary();
        Binding binding=ticket.nativeClose;
        if(binding==null)throw new Failures.Refusal("E_VERIFY_INCOMPLETE","native close dispatch binding absent");
        Map<String,Object> dispatch=read(binding.file("dispatch.json"));
        requireBinding(binding,dispatch);
        if(!CONTRACT.equals(dispatch.get("dispatch_contract")) || dispatch.containsKey("callback_proof"))
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE","native close dispatch contract differs or exposes callback proof");
        Object raw=dispatch.get("status");
        if(!(raw instanceof Number) || ((Number)raw).doubleValue()!=((Number)raw).intValue())
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE","native close dispatch status is not an integer");
        int status=((Number)raw).intValue();
        if("queue_acknowledged".equals(dispatch.get("state")) && status==0
                && Boolean.TRUE.equals(dispatch.get("queue_api_entered"))
                && Boolean.TRUE.equals(dispatch.get("queue_acknowledged"))
                && !dispatch.containsKey("dispatch_refusal_proof"))return;
        if(!"refused_before_queue".equals(dispatch.get("state")) || status==0
                || !Boolean.FALSE.equals(dispatch.get("queue_api_entered"))
                || !Boolean.FALSE.equals(dispatch.get("queue_acknowledged"))
                || !proofEquals(binding.dispatchRefusalProof,dispatch.get("dispatch_refusal_proof")))
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE","native close queue outcome is unknown or refusal proof differs");
        Object reason=dispatch.get("reason");
        if(!(reason instanceof String)||!((String)reason).matches("[a-z0-9_]{1,64}"))
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE","native close refusal reason absent");
        // C's independent proof admits this transport only because ProMacroLoad was not entered.
        int actual=ModelCloseLifecycle.call("close.FunctionReturn.GetFunctionReturn(prequeue refusal only)",returnCode);
        if(actual!=status || actual==0)
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE","native close refusal and function return contradict");
        throw new PrequeueRefusal(binding,status,(String)reason);
    }
    static boolean returned(ModelCloseLifecycle.Ticket ticket) throws Exception {
        Binding binding=ticket.nativeClose;
        if(binding==null)throw new Failures.Refusal("E_VERIFY_INCOMPLETE","native close binding absent");
        Path marker=binding.file("callback-return.json");
        if(!Files.exists(marker,LinkOption.NOFOLLOW_LINKS))return false;
        Map<String,Object> value=read(marker);
        if(!proofEquals(binding.callbackProof,value.get("callback_proof")))
            throw new Failures.Refusal("E_VERIFY_INCOMPLETE","native close callback proof absent or different");
        requireBinding(binding,value);
        if(!Boolean.TRUE.equals(value.get("normal_callback_return_ready"))
                ||!Boolean.TRUE.equals(value.get("api_called"))||!numberEquals(value.get("status"),0))
            throw new Failures.Refusal("E_CREO","native current-close callback did not report a successful call; preserve original operation");
        return true;
    }
    static void cancel(ModelCloseLifecycle.Ticket ticket) throws Exception {
        Binding binding=ticket.nativeClose;if(binding==null)return;
        Path path=binding.file("cancelled.json");
        if(!Files.exists(path,LinkOption.NOFOLLOW_LINKS)){
            Map<String,Object> value=new LinkedHashMap<>(binding.expected);value.put("cancelled",true);
            writeNew(path,value);
        }
    }
}
