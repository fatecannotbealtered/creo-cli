"""SDK compile plus controlled Java/file close tests; no HTTP, CAD or native loading."""

import json
import os
import subprocess
from pathlib import Path

import pytest

# ruff: noqa: E501 - an independent, SDK-free state-machine harness
HARNESS = r"""
package com.fateforge.creocli.service;
import java.util.*;
import java.util.concurrent.atomic.*;
import java.nio.file.*;
import java.nio.*;
import java.nio.channels.*;
public final class ModelCurrentCloseHarness {
 static void yes(boolean v,String label){if(!v)throw new AssertionError(label);}
 static Map<String,Object> copy(Map<String,Object> value){return Json.object(Json.parse(Json.write(value)),"copy");}
 static final class ForceChannel extends FileChannel {
  Runnable hook;
  ForceChannel(Runnable hook){this.hook=hook;}
  public int write(ByteBuffer bytes){int n=bytes.remaining();bytes.position(bytes.limit());return n;}
  public void force(boolean metadata){if(hook!=null){Runnable run=hook;hook=null;run.run();}}
  protected void implCloseChannel(){}
  public int read(ByteBuffer b){throw new UnsupportedOperationException();}
  public long read(ByteBuffer[] b,int o,int n){throw new UnsupportedOperationException();}
  public long write(ByteBuffer[] b,int o,int n){throw new UnsupportedOperationException();}
  public long position(){throw new UnsupportedOperationException();}
  public FileChannel position(long p){throw new UnsupportedOperationException();}
  public long size(){throw new UnsupportedOperationException();}
  public FileChannel truncate(long s){throw new UnsupportedOperationException();}
  public long transferTo(long p,long c,WritableByteChannel t){throw new UnsupportedOperationException();}
  public long transferFrom(ReadableByteChannel s,long p,long c){throw new UnsupportedOperationException();}
  public int read(ByteBuffer b,long p){throw new UnsupportedOperationException();}
  public int write(ByteBuffer b,long p){throw new UnsupportedOperationException();}
  public MappedByteBuffer map(FileChannel.MapMode m,long p,long s){throw new UnsupportedOperationException();}
  public FileLock lock(long p,long s,boolean shared){throw new UnsupportedOperationException();}
  public FileLock tryLock(long p,long s,boolean shared){throw new UnsupportedOperationException();}
 }
 static ModelCurrentClose.Journal flushing(Runnable hook)throws Exception {
  var ctor=ModelCurrentClose.Journal.class.getDeclaredConstructor(FileChannel.class,Map.class);ctor.setAccessible(true);
  return ctor.newInstance(new ForceChannel(hook),Json.map("close_ticket_id","controlled"));
 }
 static class Fake implements ModelCloseLifecycle.Adapter {
  Map<String,Object> state=Json.map("completed",true,"models",new ArrayList<>(List.of(
   Json.map("model","last.prt","type","part","modified",false,"version_stamp","V1"))),
   "windows",new ArrayList<>(List.of(Json.map("id","1001","model",null),Json.map("id","1003","model","last.prt"))),
   "active_window","1003","active_model","last.prt");
  int reads,closes,queues,erases,polls,cancels,returnReads,returnStatus=-2;
  boolean ready,dirty,queueFailure,callbackFailure,readFailure,useMarker,useDispatch,returnFailure;
  Runnable returnHook;ModelCurrentClose.PrequeueRefusal forgedRefusal;
  ModelCloseLifecycle.Ticket queued;
  public Object resolve(String name)throws Throwable{return ModelCloseLifecycle.call("fake.resolve",()->name);}
  public boolean modified(Object model)throws Throwable{return ModelCloseLifecycle.call("fake.modified",()->dirty);}
  public Map<String,Object> snapshot()throws Throwable{return ModelCloseLifecycle.call("fake.snapshot",()->{
   reads++;if(readFailure)throw new IllegalStateException("controlled first getter failure");return copy(state);});}
  public void closeWindow(Object model,String target,String other){closes++;}
  public void erase(Object model)throws Throwable{ModelCloseLifecycle.call("fake.erase",()->{
   erases++;state.put("models",new ArrayList<>());return null;});}
  public void queueCurrentClose(ModelCloseLifecycle.Ticket ticket,Object model,String target,String empty)throws Throwable{
   queues++;queued=ticket;yes("1003".equals(target)&&"1001".equals(empty),"exact target and empty windows");
   if(forgedRefusal!=null)throw forgedRefusal;
   if(useDispatch)ModelCurrentClose.dispatchReturned(ticket,()->{returnReads++;if(returnHook!=null)returnHook.run();if(returnFailure)throw new IllegalStateException("controlled return transport failure");return returnStatus;});
   if(queueFailure)throw new IllegalStateException("controlled queue failure");}
  public boolean currentCloseReturned(ModelCloseLifecycle.Ticket ticket)throws Throwable{polls++;yes(ticket==queued,"same ticket");
   if(useMarker)return ModelCurrentClose.returned(ticket);
   if(callbackFailure)throw new IllegalStateException("controlled callback failure");return ready;}
  public void cancelCurrentClose(ModelCloseLifecycle.Ticket ticket){if(queued!=null)cancels++;}
  void returned(){ready=true;state.put("windows",new ArrayList<>(List.of(Json.map("id","1001","model",null))));
   state.put("active_window","1001");state.put("active_model",null);}
 }
 static class Case {
  Fake f=new Fake();AtomicLong now=new AtomicLong();AtomicReference<String> generation=new AtomicReference<>("01234567-89ab-cdef-0123-456789abcdef");
  ModelCloseLifecycle.Controller c=new ModelCloseLifecycle.Controller(f,generation::get,now::get);
  ModelCloseLifecycle.Ticket t=c.ticket(Json.map("operation","model.close","diagnostic_request_id","controlled","cli_invocation_id","controlled"),10);
  Map<String,Object> request(){return Json.map("model","last.prt","expected_session",copy(f.state));}
  void stage(){c.stage(t,request(),1);}
 }
 static ModelCurrentClose.Binding bind(Case x,Path runtime)throws Exception {
  x.t.requestSha256=ModelCurrentClose.sha256(Json.write(x.request()));
  x.t.nativeClose=ModelCurrentClose.binding(runtime,x.t,"last","1003","1001",Json.map(
   "schema_version","1.0","dispatch_contract",ModelCurrentClose.CONTRACT,"input_argument_count",10,"command",ModelCurrentClose.COMMAND,
   "priority","uiProeImmediate","registered",true,"registration_status",0,"native_pid",123,"native_creation_filetime","123456789"));
  return x.t.nativeClose;
 }
 static Map<String,Object> dispatch(ModelCurrentClose.Binding b,boolean refusal){
  Map<String,Object> row=new LinkedHashMap<>(b.expected);row.put("dispatch_contract",ModelCurrentClose.CONTRACT);
  row.put("state",refusal?"refused_before_queue":"queue_acknowledged");row.put("status",refusal?-2:0);
  row.put("queue_api_entered",!refusal);row.put("queue_acknowledged",!refusal);row.put("reason",refusal?"target_name_mismatch":"queued");
  if(refusal)row.put("dispatch_refusal_proof",b.dispatchRefusalProof);return row;
 }
 public static void main(String[] args)throws Throwable {
  List<String> cases=new ArrayList<>();
  {Case x=new Case();x.stage();yes(x.f.queues==1&&x.f.closes==0&&x.f.erases==0,"ordinary fixed path only");
   x.c.pump(1);yes(x.f.polls==0,"same tick never polls or observes");int reads=x.f.reads;
   x.c.pump(2);yes(x.f.reads==reads&&x.f.erases==0&&x.f.polls==1,"missing callback is plain-file wait only");
   x.f.returned();x.c.pump(3);yes(x.f.erases==1&&!x.t.answer.isDone(),"later callback observation precedes erase");
   x.c.pump(3);yes(!x.t.answer.isDone(),"erase same tick does not verify");x.c.pump(4);
   yes(!x.t.answer.isCompletedExceptionally()&&x.t.answer.join().get("selected_existing_window")==null,"never claims switched empty window");
   cases.add("fixed_callback_then_two_observations");}
  {Case x=new Case();x.f.state.put("active_window","1001");x.f.state.put("active_model",null);x.stage();
   yes(x.f.queues==0&&x.f.closes==1,"inactive target keeps existing path");cases.add("target_not_current");}
  {Case x=new Case();x.f.state.put("models",new ArrayList<>(List.of(Json.map("model","last.prt","type","part"),Json.map("model","other.prt","type","part"))));
   x.stage();yes(x.f.queues==0&&x.f.closes==1,"more models keep existing path");cases.add("other_model");}
  {Case x=new Case();List<Object> rows=new ArrayList<>(List.of(Json.map("id","1001","model",null),Json.map("id","1003","model","last.prt"),Json.map("id","1007","model",null)));
   x.f.state.put("windows",rows);x.stage();yes(x.f.queues==0&&x.f.closes==1,"extra window keeps existing path");cases.add("other_window");}
  {Case x=new Case();x.f.dirty=true;x.stage();yes(x.f.queues==0&&x.f.erases==0&&!x.t.started(),"dirty rejected before queue");cases.add("dirty");}
  {Case x=new Case();Map<String,Object> request=x.request();x.f.state.put("active_model","foreign.prt");x.c.stage(x.t,request,1);
   yes(x.f.queues==0&&!x.t.started(),"stale expected session rejected");cases.add("stale_before");}
  {Case x=new Case();x.stage();x.generation.set("foreign");int reads=x.f.reads;x.c.pump(2);
   yes(x.f.reads==reads&&x.f.polls==0&&x.f.erases==0&&x.f.cancels==1,"foreign generation cancelled without SDK");cases.add("foreign_generation");}
  {Case x=new Case();x.stage();x.c.stop();int reads=x.f.reads;x.c.pump(2);
   yes(x.f.reads==reads&&x.f.erases==0&&x.f.cancels==1,"service stop pure cancellation");cases.add("stop");}
  {Case x=new Case();x.f.queueFailure=true;x.stage();yes(x.c.stopped.get()!=null&&x.f.erases==0&&x.t.answer.isCompletedExceptionally(),"first queue error stops no fallback");cases.add("queue_failure");}
  {Case x=new Case();x.stage();x.f.callbackFailure=true;int reads=x.f.reads;x.c.pump(2);
   yes(x.f.reads==reads&&x.f.erases==0&&x.c.stopped.get()!=null,"callback error no SDK read or retry");cases.add("callback_failure");}
  {Case x=new Case();x.stage();x.c.pump(2);x.now.set(20_000_000);int reads=x.f.reads,polls=x.f.polls;x.c.pump(3);
   yes(x.f.reads==reads&&x.f.polls==polls&&x.f.erases==0&&x.c.stopped.get()!=null&&x.f.cancels==1,"callback missing at timeout is unknown and stopped");cases.add("missing_callback_timeout");}
  {Case x=new Case();x.stage();x.f.ready=true;x.c.pump(2);yes(x.f.erases==0&&x.c.stopped.get()!=null,"callback marker alone cannot bypass attached window");cases.add("window_still_attached");}
  {Case x=new Case();x.stage();x.f.returned();x.f.dirty=true;x.c.pump(2);yes(x.f.erases==0,"dirty after callback cannot erase");cases.add("dirty_after_callback");}
  {Case x=new Case();x.stage();x.f.returned();ModelCloseLifecycle.modelRow(x.f.state,"last.prt").put("version_stamp","V2");x.c.pump(2);
   yes(x.f.erases==0,"version after callback cannot erase");cases.add("version_after_callback");}
  {Case x=new Case();x.stage();x.f.returned();x.f.state.put("windows",List.of(Json.map("id","1008","model",null)));x.c.pump(2);
   yes(x.f.erases==0,"non-target empty identity is protected");cases.add("non_target_window_after_callback");}
  {Case x=new Case();x.f.readFailure=true;x.stage();yes(x.f.reads==1&&x.f.queues==0&&x.f.erases==0,"first getter failure does not continue");cases.add("first_getter_failure");}
  for(boolean cancel:List.of(false,true)){Case x=new Case();AtomicInteger entered=new AtomicInteger();AtomicReference<Thread> canceller=new AtomicReference<>();
   x.t.journal=flushing(()->{if(!cancel)x.now.set(20_000_000);else{
    Thread other=new Thread(()->x.c.expire(x.t,"controlled_cancel_during_force"));canceller.set(other);other.start();
    long waitUntil=System.nanoTime()+5_000_000_000L;
    while(x.t.phase.get()!=ModelCloseLifecycle.Ticket.CANCELLED&&System.nanoTime()<waitUntil)Thread.onSpinWait();
    yes(x.t.phase.get()==ModelCloseLifecycle.Ticket.CANCELLED,"concurrent cancel CAS completed during force");}});
   try(ModelCloseLifecycle.Scope scope=new ModelCloseLifecycle.Scope(x.t,x.c.guard(x.t))){
    try{ModelCloseLifecycle.call("controlled.no_sdk_after_force",()->{entered.incrementAndGet();return null;});
     throw new AssertionError("flush cancellation passed final guard");}catch(Failures.Refusal expected){}
   }
   if(canceller.get()!=null){canceller.get().join(5000);yes(!canceller.get().isAlive(),"cancellation completed after force returned");}
   yes(entered.get()==0&&!x.t.sdkEntered.get()&&x.c.stopped.get()==null,"expiry or concurrent cancel inside force must not enter first SDK or claim entered");
   cases.add(cancel?"concurrent_cancel_during_force":"deadline_during_force");}
  Path runtime=Path.of(args[0]);
  {Case x=new Case();ModelCurrentClose.Binding b=bind(x,runtime);ModelCurrentClose.writeNew(b.file("dispatch.json"),dispatch(b,false));
   x.f.useDispatch=true;x.stage();yes(x.f.returnReads==0&&x.c.stopped.get()==null&&!x.t.answer.isDone(),"ACK cannot invoke FunctionReturn transport or complete close");
   int reads=x.f.reads;x.c.pump(2);yes(x.f.reads==reads&&x.f.erases==0,"ACK still awaits real callback");cases.add("ack_never_reads_function_return");}
  {Case x=new Case();ModelCurrentClose.Binding b=bind(x,runtime);yes(!b.callbackProof.equals(b.dispatchRefusalProof),"independent proof domains");
   ModelCurrentClose.writeNew(b.file("dispatch.json"),dispatch(b,true));x.f.useDispatch=true;x.stage();
   yes(x.f.returnReads==1&&!x.t.started()&&x.t.sdkEntered.get()&&x.c.stopped.get()==null&&x.f.reads==1&&x.f.erases==0,"authenticated prequeue refusal is known no mutation without an after SDK read");
   try{x.t.answer.join();throw new AssertionError("refusal completed successfully");}catch(java.util.concurrent.CompletionException wrapped){
    Map<String,Object> error=((Service.ToolkitFailure)wrapped.getCause()).error;
    yes("E_VERIFY_INCOMPLETE".equals(error.get("code"))&&Boolean.FALSE.equals(error.get("started"))&&Boolean.TRUE.equals(error.get("sdk_read_entered")),"existing Python complete failure-observation contract retained");}
   yes(x.c.pending.get()==null&&x.f.cancels==1,"known refusal has terminal cancellation and no pending callback wait");cases.add("authenticated_prequeue_refusal_terminal");}
  for(String fault:List.of("missing","malformed","wrong_contract","foreign","wrong_proof","callback_proof_substituted","ack_leaks_refusal_proof","ack_leaks_callback_proof","entered_true_refusal","zero_status_refusal","unknown_queue","noninteger_status")){
   Case x=new Case();ModelCurrentClose.Binding b=bind(x,runtime);Map<String,Object> row=dispatch(b,true);
   if(fault.equals("wrong_contract"))row.put("dispatch_contract","model_current_close_v1");
   if(fault.equals("foreign"))row.put("request_sha256","foreign");
   if(fault.equals("wrong_proof"))row.put("dispatch_refusal_proof","0".repeat(64));
   if(fault.equals("callback_proof_substituted"))row.put("dispatch_refusal_proof",b.callbackProof);
   if(fault.equals("ack_leaks_refusal_proof")){row=dispatch(b,false);row.put("dispatch_refusal_proof",b.dispatchRefusalProof);}
   if(fault.equals("ack_leaks_callback_proof")){row=dispatch(b,false);row.put("callback_proof",b.callbackProof);}
   if(fault.equals("entered_true_refusal"))row.put("queue_api_entered",true);
   if(fault.equals("zero_status_refusal"))row.put("status",0);
   if(fault.equals("unknown_queue")){row=dispatch(b,false);row.put("state","queue_outcome_unknown");row.put("status",-1);}
   if(fault.equals("noninteger_status"))row.put("status",-2.5);
   if(fault.equals("malformed"))Files.writeString(b.file("dispatch.json"),"{");
   else if(!fault.equals("missing"))ModelCurrentClose.writeNew(b.file("dispatch.json"),row);
   x.f.useDispatch=true;x.stage();int reads=x.f.reads;x.c.pump(2);
   yes(x.f.returnReads==0&&x.f.reads==reads&&x.f.erases==0&&x.t.started()&&x.c.stopped.get()!=null&&x.f.cancels==1,"ambiguous dispatch stops and cancels without new transport, snapshot or erase: "+fault);
   cases.add("dispatch_guard_"+fault);
  }
  for(String fault:List.of("return_zero","return_other","return_throws")){Case x=new Case();ModelCurrentClose.Binding b=bind(x,runtime);
   ModelCurrentClose.writeNew(b.file("dispatch.json"),dispatch(b,true));x.f.useDispatch=true;
   if(fault.equals("return_zero"))x.f.returnStatus=0;else if(fault.equals("return_other"))x.f.returnStatus=-3;else x.f.returnFailure=true;
   x.stage();int reads=x.f.reads;x.c.pump(2);
   yes(x.f.returnReads==1&&x.t.started()&&x.f.reads==reads&&x.f.erases==0&&x.c.stopped.get()!=null,"return metadata failure remains unknown with no snapshot: "+fault);
   cases.add("function_return_"+fault);}
  {Case x=new Case();ModelCurrentClose.Binding b=bind(x,runtime);ModelCurrentClose.writeNew(b.file("dispatch.json"),dispatch(b,true));
   x.f.useDispatch=true;x.f.returnHook=()->x.now.set(20_000_000);x.stage();
   yes(x.f.returnReads==1&&x.t.started()&&x.c.stopped.get()!=null&&x.f.reads==1&&x.f.erases==0,"late return cannot reclassify timeout as known refusal");
   cases.add("late_function_return_preserves_unknown");}
  {Case x=new Case();bind(x,runtime);Case foreign=new Case();ModelCurrentClose.Binding other=bind(foreign,runtime);
   x.f.forgedRefusal=new ModelCurrentClose.PrequeueRefusal(other,-2,"target_name_mismatch");x.stage();
   yes(x.t.started()&&x.c.stopped.get()!=null&&x.f.reads==1&&x.f.erases==0,"foreign binding cannot lower mutation status");
   cases.add("foreign_prequeue_refusal_preserves_unknown");}
  {Case x=new Case();ModelCurrentClose.Binding b=bind(x,runtime);Map<String,Object> marker=new LinkedHashMap<>(b.expected);
   marker.put("callback_proof",b.dispatchRefusalProof);marker.put("normal_callback_return_ready",true);marker.put("api_called",true);marker.put("status",0);
   ModelCurrentClose.writeNew(b.file("callback-return.json"),marker);x.stage();x.f.useMarker=true;int reads=x.f.reads;x.c.pump(2);
   yes(x.f.reads==reads&&x.f.erases==0&&x.c.stopped.get()!=null,"dispatch proof cannot forge callback authority");cases.add("independent_refusal_proof_cannot_forge_callback");}
  {Case x=new Case();x.t.requestSha256=ModelCurrentClose.sha256(Json.write(x.request()));
   Map<String,Object> registration=Json.map("schema_version","1.0","dispatch_contract",ModelCurrentClose.CONTRACT,"input_argument_count",10,
    "command",ModelCurrentClose.COMMAND,"priority","uiProeImmediate","registered",true,"registration_status",0,
    "native_pid",123,"native_creation_filetime","123456789");
   x.t.nativeClose=ModelCurrentClose.binding(runtime,x.t,"last","1003","1001",registration);
   yes(!ModelCurrentClose.returned(x.t),"missing durable callback marker is not success");
   Map<String,Object> marker=new LinkedHashMap<>(x.t.nativeClose.expected);marker.put("normal_callback_return_ready",true);marker.put("api_called",true);marker.put("status",0);
   ModelCurrentClose.writeNew(x.t.nativeClose.file("callback-return.json"),marker);
   try{ModelCurrentClose.returned(x.t);throw new AssertionError("public-field forged marker accepted");}catch(Failures.Refusal expected){}
   x.stage();x.f.useMarker=true;int reads=x.f.reads;x.c.pump(2);
   yes(x.f.reads==reads&&x.f.erases==0&&x.c.stopped.get()!=null,"forged marker cannot trigger subsequent SDK");
   Files.delete(x.t.nativeClose.file("callback-return.json"));marker.put("callback_proof",x.t.nativeClose.callbackProof);
   ModelCurrentClose.writeNew(x.t.nativeClose.file("callback-return.json"),marker);yes(ModelCurrentClose.returned(x.t),"authenticated callback marker is only stage gate");
   ModelCurrentClose.cancel(x.t);yes(Files.isRegularFile(x.t.nativeClose.file("cancelled.json")),"durable cancel");ModelCurrentClose.cancel(x.t);
   Files.delete(x.t.nativeClose.file("callback-return.json"));marker.put("service_instance_id","foreign");ModelCurrentClose.writeNew(x.t.nativeClose.file("callback-return.json"),marker);
   try{ModelCurrentClose.returned(x.t);throw new AssertionError("foreign witness accepted");}catch(Failures.Refusal expected){}
   cases.add("durable_marker_binding_and_cancel");}
  {Case x=new Case();Map<String,Object> identity=Json.map("close_ticket_id",x.t.closeId,"model","last.prt","request_sha256","controlled");
   Path journal=runtime.resolve("controlled.java.jsonl");x.t.journal=ModelCurrentClose.Journal.create(journal,identity);
   try(ModelCloseLifecycle.Scope scope=new ModelCloseLifecycle.Scope(x.t,()->{})){
    ModelCloseLifecycle.call("controlled.sdk",()->{yes(Files.readString(journal).contains("call_begin"),"begin flushed before SDK");return null;});}
   x.t.journal.event("normal_callback_return_observed","later_timer_tick",null);x.t.journal.close();
   String log=Files.readString(journal);yes(log.contains("call_begin")&&log.contains("call_end")&&log.contains("normal_callback_return_observed"),"default close journal independent of disabled native diagnostics");
   try{ModelCurrentClose.Journal.create(journal,identity);throw new AssertionError("journal overwrite accepted");}catch(java.nio.file.FileAlreadyExistsException expected){}
   cases.add("durable_begin_end_without_global_diagnostic");}
  System.out.println(Json.write(Json.map("cases",cases,"CAD_calls",0,"HTTP_calls",0,"native_qualification",false)));
 }
}
"""


def test_current_close_state_machine_and_file_binding(tmp_path):
    root = Path(__file__).resolve().parents[1]
    java = Path("C:/Java/jdk-25/bin")
    sdk = Path("D:/PTC/Creo13.4/Creo 13.4.1.0/Common Files/text/java/otk.jar")
    if not (java / "javac.exe").is_file() or not sdk.is_file():
        pytest.skip("requires declared SDK/JDK; no CAD is started")
    harness = tmp_path / "ModelCurrentCloseHarness.java"
    harness.write_text(HARNESS, encoding="utf-8")
    compiled = subprocess.run(
        [
            str(java / "javac.exe"),
            "--release",
            "17",
            "-encoding",
            "UTF-8",
            "-cp",
            str(sdk),
            "-d",
            str(tmp_path / "classes"),
            *map(str, sorted((root / "service/src").rglob("*.java"))),
            str(harness),
        ],
        capture_output=True,
        timeout=90,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert compiled.returncode == 0, compiled.stderr.decode("utf-8", "replace")
    run = subprocess.run(
        [
            str(java / "java.exe"),
            "-cp",
            os.pathsep.join((str(tmp_path / "classes"), str(sdk))),
            "com.fateforge.creocli.service.ModelCurrentCloseHarness",
            str(tmp_path),
        ],
        capture_output=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert run.returncode == 0, run.stderr.decode("utf-8", "replace")
    evidence = json.loads(run.stdout)
    assert len(evidence["cases"]) == 40
    assert evidence["CAD_calls"] == evidence["HTTP_calls"] == 0
    assert evidence["native_qualification"] is False
