"""Real exit scheduler with fake PTC/session adapters; no SDK, CAD or exit call."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "service/src/com/fateforge/creocli/service"
JDK = Path(os.environ.get("JAVA_HOME", "C:/Java/jdk-25")) / "bin"

STUBS = {
    "com/ptc/pfc/pfcArgument/Arguments.java": r"""
package com.ptc.pfc.pfcArgument;
public final class Arguments {
 public final java.util.List<Object> values=new java.util.ArrayList<>();
 public static Arguments create(){return new Arguments();}
 public void append(Object value){values.add(value);}
}
""",
    "com/ptc/pfc/pfcArgument/pfcArgument.java": r"""
package com.ptc.pfc.pfcArgument;
public final class pfcArgument {
 public static Object Argument_Create(String name,Object value){
  return java.util.Map.of(name,value);
 }
 public static Object CreateIntArgValue(int value){return value;}
 public static Object CreateStringArgValue(String value){return value;}
}
""",
    "com/ptc/pfc/pfcModel/Models.java": r"""
package com.ptc.pfc.pfcModel;
public final class Models {
 private final int count;
 public Models(int value){count=value;}
 public int getarraysize(){return count;}
}
""",
    "com/fateforge/creocli/service/Failures.java": r"""
package com.fateforge.creocli.service;
final class Failures {
 static final class Refusal extends RuntimeException {
  final String code;
  Refusal(String code,String message){super(message);this.code=code;}
 }
}
""",
    "com/fateforge/creocli/service/BuildIdentity.java": r"""
package com.fateforge.creocli.service;
final class BuildIdentity {static final String SOURCE_SHA256="source-locked";}
""",
    "com/fateforge/creocli/service/Creo.java": r"""
package com.fateforge.creocli.service;
final class Creo {
 static int count,reads;
 static final class Session {
  com.ptc.pfc.pfcModel.Models ListModels(){++reads;return new com.ptc.pfc.pfcModel.Models(count);}
 }
 static Session session(){return new Session();}
}
""",
    "com/fateforge/creocli/service/NativeReadTrace.java": r"""
package com.fateforge.creocli.service;
final class NativeReadTrace {
 interface Work<T>{T run() throws Exception;}
 interface Action{void run() throws Exception;}
 static String expireAfter;
 static Runnable expireHook;
 static final class Scope implements AutoCloseable {public void close(){}}
 static void check(){}
 static Scope begin(java.util.Map<String,Object> identity){return new Scope();}
 static <T>T call(String label,Work<T> action)throws Exception{
  T value=action.run();if(label.equals(expireAfter)&&expireHook!=null)expireHook.run();return value;
 }
 static void run(String label,Action action)throws Exception{
  call(label,()->{action.run();return null;});
 }
}
""",
    "com/ptc/pfc/pfcExceptions/XToolkitCommError.java": (
        "package com.ptc.pfc.pfcExceptions; "
        "public class XToolkitCommError extends RuntimeException {}"
    ),
    "com/ptc/pfc/pfcExceptions/XToolkitAppCommunicationFailure.java": (
        "package com.ptc.pfc.pfcExceptions; "
        "public class XToolkitAppCommunicationFailure extends RuntimeException {}"
    ),
    "com/ptc/pfc/pfcExceptions/XToolkitGeneralError.java": (
        "package com.ptc.pfc.pfcExceptions; "
        "public class XToolkitGeneralError extends RuntimeException {}"
    ),
    "com/fateforge/creocli/service/Service.java": r"""
package com.fateforge.creocli.service;
final class Service {
 static final class ToolkitFailure extends Exception {
  final java.util.Map<String,Object> error;ToolkitFailure(java.util.Map<String,Object>e){error=e;}
 }
 static String generation="01234567-89ab-cdef-0123-456789abcdef";
 static java.nio.file.Path runtime;
 static boolean queued;
 static final int MAX_JOBS_PER_TICK=4;
 static long PUMP_TICK;
 static int refused,otherPumps;
 static java.util.Queue<Runnable> QUEUE=new java.util.concurrent.ConcurrentLinkedQueue<>();
 static Library library=new Library();
 static String instanceIdForReadback(){return generation;}
 static java.nio.file.Path stateDirectory(){return runtime;}
 static boolean ownedExitOtherWorkQueued(){return queued;}
 static Library loadedSketchLibrary(){return library;}
 static void refuseStoppedQueue(){++refused;Runnable job=QUEUE.poll();if(job!=null)job.run();}
 static void log(String ignored){}
 static String describe(Throwable failure){return failure.getClass().getName();}
 static void triggerDrain(){drain();}
 /*ACTUAL_DRAIN*/
 static final class Library {
  int calls;
  Runnable hook;
  com.ptc.pfc.pfcArgument.Arguments ExecuteFunction(
      String name,com.ptc.pfc.pfcArgument.Arguments arguments){
   if(!"creo_cli_session_exit".equals(name)||arguments.values.size()!=8
       ||!arguments.values.contains(java.util.Map.of("dispatch_contract","queued_native_command_v1")))
    throw new AssertionError("fixed C function and exact argument count required");
   ++calls;if(hook!=null)hook.run();return new com.ptc.pfc.pfcArgument.Arguments();
  }
 }
}
final class ModelCloseLifecycle {
 static boolean pump(long tick){++Service.otherPumps;return false;}
 static boolean blocksQueue(){return false;}
}
final class ContextActivation {
 static boolean pump(long tick){++Service.otherPumps;return false;}
 static boolean blocksQueue(){return false;}
 static boolean hasStopped(){return false;}
}
""",
}

HARNESS = r"""
package com.fateforge.creocli.service;
import java.util.*;
import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import java.lang.reflect.*;
import java.util.concurrent.atomic.AtomicReference;
public final class OwnedExitHarness {
 static final List<String> passed=new ArrayList<>();
 static int serial;
 static Path root;
 static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
 static AtomicReference<Object> pending()throws Exception{
  Field f=OwnedSessionExit.class.getDeclaredField("PENDING");f.setAccessible(true);
  return (AtomicReference<Object>)f.get(null);
 }
 static void reset(String name)throws Exception{
  pending().set(null);Creo.count=0;Creo.reads=0;Service.queued=false;
  for(String key:List.of("READER_STOP","ACTIVE_READ")) {
   Field field=OwnedSessionExit.class.getDeclaredField(key);field.setAccessible(true);
   ((AtomicReference<?>)field.get(null)).set(null);
  }
  NativeReadTrace.expireAfter=null;NativeReadTrace.expireHook=null;
  Service.QUEUE.clear();Service.refused=0;Service.otherPumps=0;
  Service.generation="01234567-89ab-cdef-0123-456789abcdef";
  Service.library=new Service.Library();Service.runtime=root.resolve(name);
  Files.createDirectory(Service.runtime);
 }
 static Map<String,Object> request()throws Exception{
  String op=String.format("%032x",++serial);
  Map<String,Object> r=Json.map("operation_id",op,"service_instance_id",Service.generation,
   "source_sha256",BuildIdentity.SOURCE_SHA256,"runtime_directory",Service.runtime.toString(),
   "expected_pid",1234,"expected_creation_filetime","123456789","ttl_ms",20000,
   "deadline_epoch_ms",Long.toString(System.currentTimeMillis()+15000),"deadline_tick_ms","30000");
  r=Json.object(Json.parse(Json.write(r)),"actual HTTP numeric representation");
  Map<String,Object> intent=new LinkedHashMap<>(r);intent.put("entrypoint","ProEngineerEnd");
  Files.writeString(file(r,"intent"),Json.write(intent));registration(r,true);return r;
 }
 static void registration(Map<String,Object> r,boolean registered)throws Exception {
  Files.writeString(Service.runtime.resolve("native-owned-exit-dispatch.json"),Json.write(Json.map(
   "schema_version","1.0","dispatch_contract","queued_native_command_v1",
   "command","CreoCliOwnedExitDeferred","priority","uiProeImmediate",
   "registered",registered,"registration_status",registered?0:-1,"native_pid",1234,
   "native_creation_filetime","123456789")));
 }
 static Path file(Map<String,Object> r,String kind){
  return Service.runtime.resolve("owned-exit-"+r.get("operation_id")+"."+kind+".json");
 }
 static void prepare(Map<String,Object> r)throws Exception{
  OwnedSessionExit.prepare(r,Json.map("test","identity"));
 }
 static void refused(Map<String,Object> r)throws Exception{
  boolean refused=false;try{prepare(r);}catch(Failures.Refusal expected){refused=true;}
  check(refused,"request must refuse");
  check(!OwnedSessionExit.blocksQueue(),"refusal left ticket");
 }
 static void expire()throws Exception{
  Object ticket=pending().get();Field f=ticket.getClass().getDeclaredField("deadline");
  f.setAccessible(true);f.setLong(ticket,System.nanoTime()-1);
 }
 static void entered(Map<String,Object> r,boolean matching)throws Exception{
  Files.writeString(file(r,"entered"),Json.write(Json.map("status","native_entered",
   "operation_id",r.get("operation_id"),"service_instance_id",r.get("service_instance_id"),
   "entrypoint","ProEngineerEnd","native_pid",matching?1234:9999,
   "native_creation_filetime",r.get("expected_creation_filetime"),"empty_models",true,
   "raw_java_empty_checked",true,"native_known_types_empty",true,"native_type_count",11,
   "dispatch_contract","queued_native_command_v1","dispatch_context","registered_native_command")));
 }
 static void success(String name){passed.add(name);}
 public static void main(String[]args)throws Exception{
  root=Path.of(args[0]);
  reset("registration-missing");Map<String,Object> r=request();
  Files.delete(Service.runtime.resolve("native-owned-exit-dispatch.json"));refused(r);
  check(Creo.reads==0&&Service.library.calls==0,"missing registration entered SDK");
  success("missing registration refuses without losing other DLL availability");
  reset("registration-failed");r=request();registration(r,false);refused(r);
  check(Creo.reads==0&&Service.library.calls==0,"failed registration entered SDK");
  success("failed native command registration refuses before SDK");
  reset("registration-foreign");r=request();
  Path mode=Service.runtime.resolve("native-owned-exit-dispatch.json");
  Map<String,Object> wrongRegistration=Json.object(Json.parse(Files.readString(mode)),"mode");
  wrongRegistration.put("native_pid",9999);Files.writeString(mode,Json.write(wrongRegistration));refused(r);
  check(Creo.reads==0&&Service.library.calls==0,"foreign native registration entered SDK");
  success("foreign native registration cannot claim availability");
  reset("raw-model");r=request();Creo.count=1;refused(r);
  check(Creo.reads==1,"raw nonempty read missing");
  success("raw model including hidden section refuses");
  reset("no-native");r=request();Service.library=null;refused(r);
  success("native backend missing refuses");
  reset("queued");r=request();Service.queued=true;refused(r);
  check(Creo.reads==0,"queued work entered SDK");success("other pending RPC refuses before SDK");
  reset("gen");r=request();
  r.put("service_instance_id","ffffffff-ffff-ffff-ffff-ffffffffffff");
  refused(r);check(Creo.reads==0,"wrong generation read");
  success("wrong generation refuses");
  reset("runtime");r=request();r.put("runtime_directory",root.toString());refused(r);
  success("wrong runtime refuses");
  reset("intent");r=request();Map<String,Object> bad=new LinkedHashMap<>(r);
  bad.put("expected_pid",9999);
  bad.put("entrypoint","ProEngineerEnd");
  Files.writeString(file(r,"intent"),Json.write(bad));refused(r);
  success("durable intent mismatch refuses");
  reset("no-arm");r=request();prepare(r);int read=Creo.reads;
  check(OwnedSessionExit.pump(),"prepared pump must block queue");
  check(Service.library.calls==0&&Creo.reads==read,"HTTP response not armed but SDK ran");
  check(!OwnedSessionExit.normalStop(),"prepared phase must not prove normal stop");
  success("before HTTP arm pump has zero dispatch");
  reset("single");r=request();prepare(r);OwnedSessionExit.arm((String)r.get("operation_id"));
  OwnedSessionExit.pump();OwnedSessionExit.pump();
  check(Service.library.calls==1,"repeat pump reentered exit API");
  check(OwnedSessionExit.nativeCommandQueued(),"queue acknowledgement lost pending phase");
  check(!Files.exists(file(r,"returned"))&&!Files.exists(file(r,"entered")),
   "queue acknowledgement invented native entry or return");
  check(!OwnedSessionExit.normalStop(),"returned phase may not invent service stop");
  success("armed later pump invokes fixed API once");
  reset("return-immediately");r=request();prepare(r);OwnedSessionExit.arm((String)r.get("operation_id"));
  Service.QUEUE.add(()->{throw new AssertionError("work ran after native command scheduled");});
  Service.triggerDrain();int afterQueueReads=Creo.reads;Service.triggerDrain();
  check(Service.library.calls==1&&Creo.reads==afterQueueReads&&Service.refused==0
    &&Service.otherPumps==0&&Service.QUEUE.size()==1,
    "drain did not return after queue acknowledgement");
  success("actual drain returns without any job or SDK work after native queue");
  reset("return-after-native-error");r=request();prepare(r);
  Service.library.hook=()->{throw new com.ptc.pfc.pfcExceptions.XToolkitGeneralError();};
  OwnedSessionExit.arm((String)r.get("operation_id"));
  Service.QUEUE.add(()->{throw new AssertionError("work ran after native dispatch attempt");});
  Service.triggerDrain();
  check(Service.refused==0&&Service.otherPumps==0&&Service.QUEUE.size()==1,
   "drain continued after an uncertain native dispatch attempt");
  success("native dispatch error also returns without later queued work");
  reset("cancel");r=request();prepare(r);OwnedSessionExit.cancel((String)r.get("operation_id"),"controlled");
  read=Creo.reads;OwnedSessionExit.arm((String)r.get("operation_id"));OwnedSessionExit.pump();
  check(Service.library.calls==0&&Creo.reads==read,"cancelled ticket entered SDK");
  success("cancelled ticket never dispatches");
  reset("expire");r=request();prepare(r);expire();read=Creo.reads;
  OwnedSessionExit.arm((String)r.get("operation_id"));OwnedSessionExit.pump();
  check(Service.library.calls==0&&Creo.reads==read,"expired response entered SDK");
  success("expired response never arms");
  reset("expire-after-arm");r=request();prepare(r);
  OwnedSessionExit.arm((String)r.get("operation_id"));expire();read=Creo.reads;
  OwnedSessionExit.pump();
  check(Service.library.calls==0&&Creo.reads==read,"expired armed ticket entered SDK");
  success("expiry after arm stops before SDK");
  reset("generation-after-arm");r=request();prepare(r);
  OwnedSessionExit.arm((String)r.get("operation_id"));read=Creo.reads;
  Service.generation="ffffffff-ffff-ffff-ffff-ffffffffffff";OwnedSessionExit.pump();
  check(Service.library.calls==0&&Creo.reads==read,"changed generation entered SDK");
  success("generation changed after arm stops before SDK");
  reset("model-appeared");r=request();prepare(r);OwnedSessionExit.arm((String)r.get("operation_id"));
  Creo.count=1;OwnedSessionExit.pump();check(Service.library.calls==0,"new model did not refuse");
  success("model appearing before dispatch refuses");
  reset("stop");r=request();prepare(r);Map<String,Object> matched=r;
  boolean[] stopped={false};Service.library.hook=()->{try{entered(matched,true);
   stopped[0]=OwnedSessionExit.normalStop();}catch(Exception e){throw new RuntimeException(e);}};
  OwnedSessionExit.arm((String)r.get("operation_id"));OwnedSessionExit.pump();
  check(stopped[0],"matching invoking witness did not permit stop observation");
  Map<String,Object> stop=Json.object(Json.parse(Files.readString(file(r,"stop"))),"stop");
  StringBuilder hash=new StringBuilder();
  for(byte b:java.security.MessageDigest.getInstance("SHA-256")
   .digest(Files.readAllBytes(file(r,"entered"))))hash.append(String.format("%02x",b));
  check(hash.toString().equals(stop.get("entered_sha256")),
   "stop hash differs from actual entered bytes");
  success("invoking stop correlates exact entered hash");
  reset("wrong-entered");r=request();prepare(r);Map<String,Object> wrong=r;
  stopped[0]=true;Service.library.hook=()->{try{entered(wrong,false);
   stopped[0]=OwnedSessionExit.normalStop();}catch(Exception e){throw new RuntimeException(e);}};
  OwnedSessionExit.arm((String)r.get("operation_id"));OwnedSessionExit.pump();
  check(!stopped[0]&&!Files.exists(file(r,"stop")),"wrong entered native PID was accepted");
  success("wrong entered identity cannot prove normal stop");
  reset("old-inline-entry");r=request();prepare(r);Map<String,Object> oldEntry=r;
  Service.library.hook=()->{
   try{entered(oldEntry,true);Path p=file(oldEntry,"entered");
    Map<String,Object> old=Json.object(Json.parse(Files.readString(p)),"old inline entry");
    old.remove("dispatch_contract");old.remove("dispatch_context");Files.writeString(p,Json.write(old));
   }catch(Exception e){throw new RuntimeException(e);}};
  OwnedSessionExit.arm((String)r.get("operation_id"));OwnedSessionExit.pump();
  check(!OwnedSessionExit.normalStop()&&!Files.exists(file(r,"stop")),
   "old inline entry accepted as deferred native context");
  success("old inline witness cannot prove new native dispatch context");
  for(String boundary:List.of("pfcGlobal.GetProESession(owned-exit)","Arguments.create(owned-exit)",
   "CreateIntArgValue(owned-exit)","Argument_Create(owned-exit)","Arguments.append(owned-exit)")) {
   reset("late-"+serial);r=request();prepare(r);OwnedSessionExit.arm((String)r.get("operation_id"));
   int readsBefore=Creo.reads;NativeReadTrace.expireAfter=boundary;
   NativeReadTrace.expireHook=()->{
    try{expire();}catch(Exception e){throw new RuntimeException(e);}
   };
   OwnedSessionExit.pump();
   check(Service.library.calls==0,"SDK boundary expiry reached exit function: "+boundary);
   if(boundary.startsWith("pfcGlobal"))
    check(Creo.reads==readsBefore,"ListModels continued after session getter expiry");
   success("deadline stops next SDK at "+boundary);
  }
  reset("known-native-failure");r=request();prepare(r);Map<String,Object> failed=r;
  Service.library.hook=()->{
   try{entered(failed,true);}catch(Exception e){throw new RuntimeException(e);}
   throw new com.ptc.pfc.pfcExceptions.XToolkitGeneralError();};
  OwnedSessionExit.arm((String)r.get("operation_id"));OwnedSessionExit.pump();
  check(Files.exists(file(r,"failed"))&&!Files.exists(file(r,"unavailable")),
   "known native failure became communication missing");
  OwnedSessionExit.normalStop();
  check(Files.exists(file(r,"failed")),"later stop erased sticky known failure");
  check(!Files.exists(file(r,"stop")),"known failure minted later normal stop proof");
  Files.delete(file(r,"failed"));
  check(!OwnedSessionExit.normalStop()&&!Files.exists(file(r,"stop")),
   "lost failure file removed in-memory sticky veto");
  success("known native error remains sticky failed despite entered and later stop");
  reset("communication-missing");r=request();prepare(r);Map<String,Object> missing=r;
  Service.library.hook=()->{
   try{entered(missing,true);}catch(Exception e){throw new RuntimeException(e);}
   throw new com.ptc.pfc.pfcExceptions.XToolkitCommError();};
  OwnedSessionExit.arm((String)r.get("operation_id"));OwnedSessionExit.pump();
  check(Files.exists(file(r,"unavailable"))&&!Files.exists(file(r,"failed")),
   "explicit communication type not distinguished");
  success("only explicit SDK communication type may retain unavailable");
  reset("read-pure-withdraw");r=request();
  r.put("read_deadline_epoch_ms",Long.toString(System.currentTimeMillis()+20000));
  Map<String,Object> rid=Json.map("diagnostic_request_id","owned-read-1");
  try(OwnedSessionExit.ReadScope scope=OwnedSessionExit.readScope("session.exit-state",r,rid)) {
   OwnedSessionExit.readerTimedOut(rid);
   boolean denied=false;try{OwnedSessionExit.state(r);}catch(Failures.Refusal e){denied=true;}
   check(denied&&Creo.reads==0,"pure reader cancellation dispatched SDK");
  }
  check(!OwnedSessionExit.blocksQueue(),"pure cancellation falsely stopped generation");
  success("pure reader withdrawal is not SDK stop");
  reset("read-entered-timeout");r=request();
  r.put("read_deadline_epoch_ms",Long.toString(System.currentTimeMillis()+20000));
  rid=Json.map("diagnostic_request_id","owned-read-2");Map<String,Object> originalRead=rid;
  try(OwnedSessionExit.ReadScope scope=OwnedSessionExit.readScope("session.exit-state",r,rid)) {
   NativeReadTrace.expireAfter="pfcGlobal.GetProESession(owned-exit)";
   NativeReadTrace.expireHook=()->OwnedSessionExit.readerTimedOut(originalRead);
   boolean denied=false;try{OwnedSessionExit.state(r);}catch(Failures.Refusal e){denied=true;}
   check(denied&&Creo.reads==0,"ListModels continued after entered session getter timeout");
   check(OwnedSessionExit.readerInFlight(),"inflight reader lost cleanup safety gate");
  }
  check(OwnedSessionExit.blocksQueue(),"entered reader timeout did not sticky stop");
  success("SDK-entered preflight timeout blocks all later SDK without diagnostics");
  System.out.println(Json.write(Json.map("passed",passed,"count",passed.size(),"CAD",0)));
 }
}
"""


@pytest.mark.skipif(not (JDK / "javac.exe").is_file(), reason="requires local JDK")
def test_owned_exit_java_scheduler(tmp_path):
    src = tmp_path / "src"
    files = []
    for name, content in STUBS.items():
        if "/*ACTUAL_DRAIN*/" in content:
            source = (SERVICE / "Service.java").read_text(encoding="utf-8")
            start = source.index("    private static void drain() {")
            cursor = source.index("{", start)
            depth = 1
            end = cursor + 1
            while depth:
                if source[end] == "{":
                    depth += 1
                elif source[end] == "}":
                    depth -= 1
                end += 1
            content = content.replace("/*ACTUAL_DRAIN*/", source[start:end])
        path = src / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        files.append(str(path))
    for name in ["Json.java", "OwnedSessionExit.java"]:
        path = src / "com/fateforge/creocli/service" / name
        path.write_bytes((SERVICE / name).read_bytes())
        files.append(str(path))
    harness = src / "com/fateforge/creocli/service/OwnedExitHarness.java"
    harness.write_text(HARNESS, encoding="utf-8")
    files.append(str(harness))
    classes = tmp_path / "classes"
    compiled = subprocess.run(
        [
            str(JDK / "javac.exe"),
            "--release",
            "17",
            "-encoding",
            "UTF-8",
            "-d",
            str(classes),
            *files,
        ],
        capture_output=True,
        timeout=45,
    )
    assert compiled.returncode == 0, compiled.stderr.decode("utf-8", errors="replace")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    result = subprocess.run(
        [
            str(JDK / "java.exe"),
            "-cp",
            str(classes),
            "com.fateforge.creocli.service.OwnedExitHarness",
            str(runtime),
        ],
        capture_output=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    data = json.loads(result.stdout)
    assert data["count"] == 30
    assert data["CAD"] == 0
