"""Controlled deferred native-command state machine. No CAD, CUA or business CLI."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "service/src"
JDK = Path(os.environ.get("JAVA_HOME", "C:/Java/jdk-25")) / "bin"
SDK = Path(
    os.environ.get("CREO_OTK_JAR", "D:/PTC/Creo13.4/Creo 13.4.1.0/Common Files/text/java/otk.jar")
)
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

HARNESS = r"""
package com.fateforge.creocli.service;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.*;

public final class ContextActivationHarness {
    static final List<String> cases=new ArrayList<>();
    static void check(boolean value,String why) {if(!value)throw new AssertionError(why);}
    static final class ModelState {
        final String name,type;
        String origin,version="V1";
        int relation;
        ModelState(String name,int relation) {
            this.name=name;this.type=name.endsWith(".asm") ? "assembly" : "part";
            this.origin="D:/owned/"+name+".3";this.relation=relation;
        }
        Map<String,Object> identity() {
            return Json.map("model",name,"type",type,"origin",origin,
                    "version_stamp",version,"relation_id",relation);
        }
    }
    static final class Fake implements ContextActivation.Adapter {
        final Map<String,ModelState> models=new LinkedHashMap<>();
        Runnable callback,identityHook,observeHook,resolveHook,dispatchHook;
        RuntimeException activationFailure;
        String current,owner,pending;
        String wrongCurrentType;
        int register,resolve,resolveSecondGetter,dispatchSessionReads,identities,activeReads,
            macros,mutations,observations;
        boolean failRegister,wrongWindow;
        Fake() {
            models.put("a.prt",new ModelState("a.prt",11));
            models.put("b.asm",new ModelState("b.asm",12));
            current="a.prt";owner=current;
        }
        public void register(Runnable callback) {
            register++;
            if(failRegister)throw new IllegalStateException("controlled registration failure");
            this.callback=callback;
        }
        public Object resolve(String name) {
            ContextActivation.beforeNativeCall();resolve++;
            if(resolveHook!=null) {Runnable once=resolveHook;resolveHook=null;once.run();}
            ContextActivation.beforeNativeCall();resolveSecondGetter++;
            ModelState model=models.get(name);
            if(model==null)throw new Failures.Refusal("E_NOT_FOUND","target absent");
            return model;
        }
        public Map<String,Object> identity(Object target) {
            ContextActivation.beforeNativeCall();identities++;
            if(identityHook!=null) {Runnable once=identityHook;identityHook=null;once.run();}
            return ((ModelState)target).identity();
        }
        public boolean active(Object target) {
            ContextActivation.beforeNativeCall();activeReads++;
            String name=((ModelState)target).name;
            return name.equals(current) && name.equals(owner);
        }
        public void dispatch() {
            ContextActivation.beforeNativeCall();dispatchSessionReads++;
            if(dispatchHook!=null) {Runnable once=dispatchHook;dispatchHook=null;once.run();}
            ContextActivation.beforeNativeCall();macros++;
        }
        public void activate(Object target,Runnable guard) {
            guard.run();
            if(activationFailure!=null)throw activationFailure;
            mutations++;
            pending=((ModelState)target).name;
            guard.run(); // stand in for the distinct SDK setters, not CAD execution
        }
        public Map<String,Object> observe(Object target) {
            ContextActivation.beforeNativeCall();observations++;
            if(observeHook!=null) {Runnable once=observeHook;observeHook=null;once.run();}
            ContextActivation.beforeNativeCall();
            ModelState model=(ModelState)target;
            String currentType=current==null ? null : models.get(current).type;
            if(wrongCurrentType!=null)currentType=wrongCurrentType;
            String ownerType=owner==null ? null : models.get(owner).type;
            boolean complete=current!=null && current.equals(owner) && Objects.equals(
                currentType,ownerType);
            return Json.map("target_identity",model.identity(),"target_active",complete &&
                model.name.equals(current),
                    "context_complete",complete,"current_model",current,"current_model_type",
                        currentType,
                    "window_model",owner,"window_model_type",ownerType,
                    "window","1002","active_window",wrongWindow ? "1001" : "1002");
        }
        void releaseToCreo() {current=pending;owner=pending;pending=null;}
    }
    static final class Scenario {
        final Fake f=new Fake();
        final long[] now={1L};
        final String[] generation={"owned-generation"};
        final ContextActivation.Controller c;
        Scenario() {this(false);}
        Scenario(boolean fail) {
            f.failRegister=fail;
            c=new ContextActivation.Controller(f,()->generation[0],()->now[0]);
            c.initialize();
        }
        ContextActivation.Ticket ticket() {return c.ticket(Json.map("operation",
            "display.activate","cli_invocation_id","this-invocation"),1000);}
        Map<String,Object> request(String name) {return Json.map("model",name,"expected_target",
            new LinkedHashMap<>(f.models.get(name).identity()));}
        void stage(ContextActivation.Ticket t,Map<String,Object> r,long tick) {c.stage(t,r,tick);}
        Map<String,Object> success(ContextActivation.Ticket t) {return t.answer.join();}
    }
    static Map<String,Object> error(ContextActivation.Ticket ticket) {
        try {ticket.answer.join();throw new AssertionError("unexpected success");}
        catch(CompletionException wrapped) {return ((Service.ToolkitFailure)wrapped.getCause())
            .error;}
    }
    static void done(String name) {cases.add(name);}
    public static void main(String[] args) {
        Scenario s=new Scenario();
        ContextActivation.Ticket first=s.ticket();
        s.stage(first,s.request("b.asm"),10);
        check(s.f.macros==1 && !first.answer.isDone() && s.c.blocksQueue(),
            "deferred stage must block SDK queue");
        check(s.c.pump(10) && s.f.observations==0,"same staging tick cannot verify");
        s.f.callback.run();
        check(s.f.mutations==1 && !first.answer.isDone(),"callback return is not success");
        check(s.c.pump(10) && s.f.observations==0,"same callback tick cannot verify");
        s.f.releaseToCreo();s.c.pump(11);
        Map<String,Object> result=s.success(first);
        check(Boolean.TRUE.equals(result.get("activation_performed")) && Boolean.TRUE.equals(
            result.get("verified_after_return_to_creo")),"later proof required");
        check(result.get("activation_dispatch").equals(ContextActivation.DISPATCH),
            "fixed dispatcher provenance");
        check(((Number)result.get("verified_tick")).longValue()>((Number)result.get(
            "callback_tick")).longValue(),"strict tick boundary");
        check(!s.c.blocksQueue(),"terminal success releases queue");
        s.f.callback.run();check(s.f.mutations==1,"consumed callback cannot repeat");
        done("real_return_boundary_and_once_consumption");

        ContextActivation.Ticket back=s.ticket();s.stage(back,s.request("a.prt"),12);
        s.f.callback.run();s.f.releaseToCreo();s.c.pump(13);
        check(Boolean.TRUE.equals(s.success(back).get("activation_performed")) &&
            s.f.current.equals("a.prt"),"second different model");
        done("two_distinct_model_switches");

        s.f.models.clear();s.f.current=null;s.f.owner=null;
        s.f.models.put("a.prt",new ModelState("a.prt",999));
        ContextActivation.Ticket reopened=s.ticket();s.stage(reopened,s.request("a.prt"),14);
        s.f.callback.run();s.f.releaseToCreo();s.c.pump(15);
        check(Boolean.TRUE.equals(s.success(reopened).get("activation_performed")),
            "null-current exact reopened identity can activate");
        done("closed_all_then_new_typed_identity_null_current");

        Scenario noOp=new Scenario();ContextActivation.Ticket n=noOp.ticket();
        noOp.stage(n,Json.map("model","a.prt"),1);
        check(Boolean.FALSE.equals(noOp.success(n).get("activation_performed")) &&
            noOp.f.macros==0,"old already-active compatibility");
        done("already_active_noop_without_new_request_fields");

        for(String key:List.of("model","type","origin","version_stamp","relation_id")) {
            Scenario drift=new Scenario();Map<String,Object> request=drift.request("b.asm");
            Map<String,Object> expected=Json.object(request.get("expected_target"),"expected");
            if(key.equals("relation_id"))expected.put(key,99.0);
            else if(key.equals("model"))expected.put(key,"other.asm");
            else if(key.equals("type"))expected.put(key,"part");
            else expected.put(key,"changed");
            ContextActivation.Ticket t=drift.ticket();drift.stage(t,request,1);
            check(t.answer.isDone() && drift.f.macros==0 && drift.f.mutations==0,
                "identity must reject before dispatch: "+key);
            check(Boolean.FALSE.equals(error(t).get("started")),"pre-macro mismatch not started");
        }
        done("all_five_identity_field_mismatches_refuse_before_dispatch");

        Scenario missing=new Scenario();ContextActivation.Ticket missingTicket=missing.ticket();
        missing.stage(missingTicket,Json.map("model","b.asm"),1);
        check(error(missingTicket).get("code").equals("E_VALIDATION") && missing.f.macros==0,
            "missing bound target");
        Scenario wrongKeys=new Scenario();Map<String,Object> wrong=wrongKeys.request("b.asm");
        Json.object(wrong.get("expected_target"),"expected").put("extra","not allowed");
        ContextActivation.Ticket w=wrongKeys.ticket();wrongKeys.stage(w,wrong,1);
        check(error(w).get("code").equals("E_VALIDATION"),
            "unexpected fields cannot change contract");
        done("missing_or_ambiguous_identity_refused");

        Scenario between=new Scenario();ContextActivation.Ticket b=between.ticket();
            between.stage(b,between.request("b.asm"),1);
        between.f.models.get("b.asm").version="V2";between.f.callback.run();
        check(error(b).get("code").equals("E_CONFLICT") && between.f.mutations==0,
            "callback rebinds identity before mutation");
        between.f.callback.run();check(between.f.mutations==0,"failed callback not replayed");
        done("callback_version_drift_blocks_mutation_and_replay");

        for(String fault:List.of("window","type","owner","current","source")) {
            Scenario bad=new Scenario();ContextActivation.Ticket t=bad.ticket();bad.stage(t,
                bad.request("b.asm"),1);
            bad.f.callback.run();bad.f.releaseToCreo();
            if(fault.equals("window"))bad.f.wrongWindow=true;
            if(fault.equals("type"))bad.f.wrongCurrentType="part";
            if(fault.equals("owner"))bad.f.owner="a.prt";
            if(fault.equals("current"))bad.f.current=null;
            if(fault.equals("source"))bad.f.models.get("b.asm").origin="D:/other/b.asm.3";
            bad.c.pump(2);
            check(t.answer.isCompletedExceptionally(),
                "wrong independent context cannot pass: "+fault);
            check(Boolean.TRUE.equals(error(t).get("started")),"known dispatch remains started");
        }
        done("independent_window_type_owner_current_and_source_rejections");

        Scenario queued=new Scenario();ContextActivation.Ticket q=queued.ticket();
            queued.c.expire(q,"controlled queue expiry");
        queued.stage(q,queued.request("b.asm"),1);
        check(queued.f.resolve==0 && queued.f.macros==0 && queued.c.stopped.get()==null,
            "queued withdrawal has no SDK call or instance stop");
        check(Boolean.FALSE.equals(error(q).get("started")),"withdrawn is not started");
        done("queue_withdrawal_before_any_sdk_call");

        Scenario late=new Scenario();ContextActivation.Ticket l=late.ticket();late.stage(l,
            late.request("b.asm"),1);
        late.now[0]=l.deadline;late.f.callback.run();late.f.callback.run();late.c.pump(2);
        check(late.f.mutations==0 && late.f.observations==0 && late.c.stopped.get()!=null,
            "late callback must remain SDK-free and sticky stopped");
        check(Boolean.TRUE.equals(error(l).get("started")),
            "RunMacro already entered means started unknown");
        done("expired_dispatched_callback_cannot_execute_late");

        Scenario midStage=new Scenario();ContextActivation.Ticket m=midStage.ticket();
        midStage.f.identityHook=()->midStage.c.expire(m,"controlled timeout in getter");
        midStage.stage(m,midStage.request("b.asm"),1);
        check(midStage.f.activeReads==0 && midStage.f.macros==0 && midStage.c.stopped.get()
            !=null,"no next SDK getter after in-flight expiry");
        done("expiry_during_binding_stops_next_getter");

        Scenario resolveExpiry=new Scenario();ContextActivation.Ticket re=resolveExpiry.ticket();
        resolveExpiry.f.resolveHook=()->resolveExpiry.c.expire(re,
            "controlled timeout after session getter");
        resolveExpiry.stage(re,resolveExpiry.request("b.asm"),1);
        check(resolveExpiry.f.resolveSecondGetter==0 && resolveExpiry.f.identities==0 &&
            resolveExpiry.f.macros==0,"resolver must not scan or call second getter after expiry");
        done("expiry_between_resolver_sdk_getters");

        Scenario dispatchExpiry=new Scenario();ContextActivation.Ticket de=dispatchExpiry.ticket();
        dispatchExpiry.f.dispatchHook=()->dispatchExpiry.c.expire(de,
            "controlled timeout after dispatch session getter");
        dispatchExpiry.stage(de,dispatchExpiry.request("b.asm"),1);
        check(dispatchExpiry.f.dispatchSessionReads==1 && dispatchExpiry.f.macros==0 &&
            dispatchExpiry.c.stopped.get()!=null,
                "RunMacro cannot enter after session getter timeout");
        done("expiry_before_runmacro_after_session_getter");

        Scenario proxy=new Scenario();ContextActivation.Ticket proxyTicket=proxy.ticket();
        AtomicInteger proxyDetails=new AtomicInteger();
        proxy.f.activationFailure=new RuntimeException() {
            @Override public String getMessage() {proxyDetails.incrementAndGet();throw new
                AssertionError("native-like proxy detail getter");}
            @Override public String toString() {proxyDetails.incrementAndGet();throw new
                AssertionError("native-like proxy toString");}
        };
        proxy.stage(proxyTicket,proxy.request("b.asm"),1);proxy.f.callback.run();
        check(error(proxyTicket).get("code").equals("E_CREO") && proxyDetails.get()==0,
            "failure reduction must not inspect a native-like proxy");
        done("native_proxy_failure_reduction_has_no_detail_getters");

        Scenario verifyExpiry=new Scenario();ContextActivation.Ticket v=verifyExpiry.ticket();
        verifyExpiry.stage(v,verifyExpiry.request("b.asm"),1);verifyExpiry.f.callback.run();
            verifyExpiry.f.releaseToCreo();
        verifyExpiry.f.observeHook=()->verifyExpiry.now[0]=v.deadline;
        verifyExpiry.c.pump(2);
        check(v.answer.isCompletedExceptionally() && verifyExpiry.c.stopped.get()!=null,
            "observation boundary deadline stop");
        done("expiry_during_later_proof_does_not_become_success");

        Scenario changedGeneration=new Scenario();ContextActivation.Ticket
            g=changedGeneration.ticket();
        changedGeneration.stage(g,changedGeneration.request("b.asm"),1);
            changedGeneration.generation[0]="other-generation";
        changedGeneration.f.callback.run();check(changedGeneration.f.mutations==0 &&
            changedGeneration.c.stopped.get()!=null,"generation mismatch blocks callback");
        done("generation_change_refuses_stale_callback");

        Scenario stop=new Scenario();ContextActivation.Ticket stopped=stop.ticket();stop.stage(
            stopped,stop.request("b.asm"),1);
        stop.c.stop();stop.f.callback.run();check(stop.f.mutations==0 && !stop.c.ready(),
            "service stop cancels pending typed activation");
        done("service_stop_retains_started_unknown_and_blocks_late_action");

        Scenario registration=new Scenario(true);ContextActivation.Ticket r=registration.ticket()
            ;registration.stage(r,registration.request("b.asm"),1);
        check(!registration.c.ready() && error(r).get("code").equals("E_UNSUPPORTED") &&
            registration.f.macros==0,"registration failure not advertised");
        done("registration_failure_has_no_capability_or_macro");

        Scenario overflow=new Scenario();overflow.now[0]=Long.MAX_VALUE-99;
        ContextActivation.Ticket overflowTicket=overflow.ticket();overflow.stage(overflowTicket,
            overflow.request("b.asm"),1);
        check(!overflowTicket.answer.isDone(),"nanoTime wrap does not expire a fresh request");
        overflow.c.expire(overflowTicket,"controlled cleanup");
        done("monotonic_deadline_wrap");

        check(ContextActivation.MACRO.equals("~ Command `creo_cli_context_activate`;"),
            "only fixed owned command string");
        done("fixed_owned_macro_contains_no_request_values");
        System.out.println(Json.write(Json.map("cases",cases,"CAD_calls",0,"CUA_calls",0,
                "native_context_qualified",false,"sdk_interface_harness",true)));
    }
}
"""


@pytest.mark.skipif(
    not ((JDK / "javac.exe").is_file() and (JDK / "java.exe").is_file() and SDK.is_file()),
    reason="requires declared installed SDK/JDK; controlled harness never calls CAD",
)
def test_deferred_context_state_machine_and_real_sdk_compilation(tmp_path):
    harness = tmp_path / "ContextActivationHarness.java"
    harness.write_text(HARNESS, encoding="utf-8")
    compiled = subprocess.run(
        [
            str(JDK / "javac.exe"),
            "--release",
            "17",
            "-encoding",
            "UTF-8",
            "-cp",
            str(SDK),
            "-d",
            str(tmp_path / "classes"),
            *map(str, sorted(SOURCE.rglob("*.java"))),
            str(harness),
        ],
        capture_output=True,
        timeout=90,
        creationflags=FLAGS,
    )
    assert compiled.returncode == 0, compiled.stderr.decode("utf-8", "replace")
    executed = subprocess.run(
        [
            str(JDK / "java.exe"),
            "-cp",
            os.pathsep.join((str(tmp_path / "classes"), str(SDK))),
            "com.fateforge.creocli.service.ContextActivationHarness",
        ],
        capture_output=True,
        timeout=30,
        creationflags=FLAGS,
    )
    assert executed.returncode == 0, executed.stderr.decode("utf-8", "replace")
    result = json.loads(executed.stdout)
    assert len(result["cases"]) == 20
    assert result["CAD_calls"] == result["CUA_calls"] == 0
    assert result["native_context_qualified"] is False


def test_http_integration_yields_before_queue_continues_and_uses_one_fixed_dispatcher():
    service = (SOURCE / "com/fateforge/creocli/service/Service.java").read_text(encoding="utf-8")
    context = (SOURCE / "com/fateforge/creocli/service/ContextActivation.java").read_text(
        encoding="utf-8"
    )
    assert '"display.activate".equals(op)' in service
    assert "if (ContextActivation.pump(tick)) {" in service
    assert (
        "if (ContextActivation.blocksQueue() || OwnedSessionExit.blocksQueue() || "
        "ModelCloseLifecycle.blocksQueue()) {" in service
    )
    assert "if(ContextActivation.hasStopped())refuseStoppedQueue();" in service
    assert "activateOnToolkitThread(request,wait,identity)" in service
    assert "ticket.answer.get(waitMillis,TimeUnit.MILLISECONDS)" in service
    assert "NativeReadTrace.requestUnreturned(ticket.identity,error)" in context
    assert "UICreateMaxPriorityCommand(COMMAND,listener)" in context
    assert ".RunMacro(MACRO)" in context
    assert "Session.GetModelFromFileName(context resolve)" in context
    assert "return Creo.model(" not in context
    assert "Service.ToolkitFailure.of(failure).error" not in context
    assert "ExecuteMacro(" not in context
