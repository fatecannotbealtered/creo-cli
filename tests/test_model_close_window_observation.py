"""Controlled close-window observations and deferred lifecycle; never Native evidence."""

import json
import os
import subprocess

# ruff: noqa: E501 - embedded independent Java state-machine harness
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from creo_cli import driver, model_management
from creo_cli.core import Error
from tests.test_model_close_budget_reuse import (
    CLOSE,
    after_state_fault,
)
from tests.test_model_close_budget_reuse import (
    close_case as close_case,
)
from tests.test_model_close_budget_reuse import (
    close_verifier as close_verifier,
)


@pytest.mark.parametrize("variant", ("removed", "added_empty", "reassigned_to_target_id"))
def test_complete_failed_window_a_is_retained_and_never_replaced(close_verifier, variant):
    c = close_verifier
    if variant == "removed":
        c.after["windows"] = []
    elif variant == "added_empty":
        c.after["windows"].append({"id": "extra", "model": None})
    else:
        c.after["windows"] = [{"id": "close.drw", "model": "source.prt"}]
    result, verification = c.p.verify(c.client, {"model": "close.drw", "erased": True})
    checks = {row["check"]: row for row in verification["checks"]}
    assert checks["other_window_identities_unchanged"]["passed"] is False
    assert checks["other_window_identities_unchanged"]["differences"]
    expected = deepcopy(c.after)
    expected["windows"].sort(key=lambda row: row["id"])
    assert result["after"] == expected
    assert verification["observations"][0]["state"] == result["after"]
    assert c.p.verified_observation is None
    settled = c.p._settled_observation(c.p, c.client)
    assert settled == result["after"]
    assert c.p.observe(c.client) == result["after"]
    assert c.client.op.call_count == 2  # plan before + one complete A, never a B


def test_same_ids_and_complete_empty_base_pass_without_weakening_window_conditions():
    old = {
        "windows": [
            {"id": "1001", "model": "phone_demo.asm"},
            {"id": "1007", "model": "battery.prt"},
        ],
        "active_model": "phone_demo.asm",
        "active_window": "1001",
    }
    after = {
        "windows": [{"id": "1001", "model": None}, {"id": "1007", "model": "battery.prt"}],
        "active_model": "battery.prt",
        "active_window": "1007",
    }
    checks = model_management.window_checks(old, after, "phone_demo.asm")
    assert len(checks) == 3
    assert all(row["passed"] for row in checks)
    diagnostic = model_management.window_diagnostics(old, after, "phone_demo.asm")
    assert diagnostic["differences"] == []
    assert diagnostic["target_window_residuals"] == [{"id": "1001", "model": None}]


@pytest.mark.parametrize("field", ("arguments", "request", "binding", "preview", "before"))
def test_post_verify_intent_mutation_cannot_consume_a_or_dispatch_b(close_verifier, field):
    c = close_verifier
    c.p.verify(c.client, {"model": "close.drw", "erased": True})
    getattr(c.p, field)["controlled_tamper"] = True
    assert c.p._verified_observation_guard(c.p, c.client) is False
    assert c.p._settled_observation(c.p, c.client) is None
    with pytest.raises(Error) as caught:
        c.p.observe(c.client)
    assert caught.value.code == "E_VERIFY_INCOMPLETE"
    assert c.client.op.call_count == 2


def test_after_alias_mutation_cannot_substitute_observation(close_verifier):
    c = close_verifier
    result, _ = c.p.verify(c.client, {"model": "close.drw", "erased": True})
    result["after"]["models"][0]["modified"] = True
    assert c.p._verified_observation_guard(c.p, c.client) is False
    assert c.p._settled_observation(c.p, c.client) is None
    with pytest.raises(Error):
        c.p.observe(c.client)
    assert c.client.op.call_count == 2


def test_other_plan_and_client_cannot_consume_a(close_verifier):
    c = close_verifier
    c.p.verify(c.client, {"model": "close.drw", "erased": True})
    foreign = SimpleNamespace(op=c.client.op, require_capability=c.client.require_capability)
    assert c.p._settled_observation(deepcopy(c.p), c.client) is None
    assert c.p._settled_observation(c.p, foreign) is None
    with pytest.raises(Error) as refused:
        driver._effect_observation(c.p, foreign)
    assert refused.value.code == "E_VERIFY_INCOMPLETE"
    with pytest.raises(Error):
        c.p.observe(foreign)
    assert c.client.op.call_count == 2


def test_public_window_drift_keeps_a_full_and_failed_despite_hypothetical_clean_b(
    close_case, monkeypatch
):
    c = close_case
    dry = c.cli(*CLOSE, "--dry-run")["data"]

    def remove_window(data):
        data["windows"] = [row for row in data["windows"] if row["model"] != "sibling.prt"]

    state = after_state_fault(c, monkeypatch, remove_window)
    error = c.cli(*CLOSE, "--confirm", dry["confirm_token"], status=1)["error"]
    assert error["code"] == "E_VERIFY_FAILED"
    receipt = error["details"]["receipt"]
    assert receipt["outcome"]["verification"]["status"] == "failed"
    observed = receipt["snapshot_after"]["extensions"]["creo"]["observation"]
    assert "after" in observed and "window_diagnostics" in observed
    assert observed["window_diagnostics"]["differences"]
    assert not any(row["model"] == "sibling.prt" for row in observed["after"]["windows"])
    evidence = receipt["outcome"]["verification"]["extensions"]["creo"]["observations"][0]
    assert evidence["state"] == observed["after"]
    assert state["reads"] == 1
    assert c.world.ops().count("model.close") == 1


def test_public_new_lifecycle_expected_session_rejects_pre_dispatch_drift(close_case, monkeypatch):
    c = close_case
    dry = c.cli(*CLOSE, "--dry-run")["data"]
    original = c.world.management_state
    phase = {"attempts": 0}

    def changed():
        state = original()
        phase["attempts"] += 1
        # Force a source change at the synthetic service's own compare, without a setter.
        if phase["attempts"] == 2:
            state["active_model"] = "controlled-drift"
        return state

    monkeypatch.setattr(c.world, "management_state", changed)
    result = c.cli(*CLOSE, "--confirm", dry["confirm_token"], status=6)
    assert result["ok"] is False
    assert result["error"]["code"] == "E_CONFLICT"
    assert "close.drw" in c.world.models


JAVA_HARNESS = r"""
package com.fateforge.creocli.service;
import java.util.*;
import java.util.concurrent.atomic.*;
public final class ModelCloseHarness {
 static void yes(boolean v,String s){if(!v)throw new AssertionError(s);}
 static Map<String,Object> copyDto(Map<String,Object> m){return Json.object(Json.parse(Json.write(m)),"copy");}
 static class Fake implements ModelCloseLifecycle.Adapter {
  Map<String,Object> state=Json.map("completed",true,"models",new ArrayList<>(List.of(
   Json.map("model","a.asm","modified",false,"version_stamp","A1"),
   Json.map("model","b.prt","modified",false,"version_stamp","B1"))),
   "windows",new ArrayList<>(List.of(Json.map("id","1001","model","a.asm"),Json.map("id","1007","model","b.prt"))),
   "active_window","1001","active_model","a.asm");
  int reads,resolves,modifiedReads,closes,erases;String selected;
  Runnable readHook,resolveHook,modifiedHook,eraseHook;boolean dirty,leaveTargetVisible;
  public Object resolve(String n)throws Throwable{return ModelCloseLifecycle.call("fake.resolve",()->{
   resolves++;if(resolveHook!=null)resolveHook.run();return n;});}
  public Map<String,Object> snapshot()throws Throwable{return ModelCloseLifecycle.call("fake.snapshot",()->{reads++;
   if(readHook!=null){Runnable hook=readHook;readHook=null;hook.run();}
   ModelCloseLifecycle.boundary();return copyDto(state);});}
  public boolean modified(Object m)throws Throwable{return ModelCloseLifecycle.call("fake.modified",()->{
   modifiedReads++;if(modifiedHook!=null)modifiedHook.run();return dirty;});}
  public void closeWindow(Object m,String target,String other)throws Throwable{ModelCloseLifecycle.call("fake.close",()->{closes++;selected=other;return null;});}
  public void erase(Object m)throws Throwable{ModelCloseLifecycle.call("fake.erase",()->{erases++;
   ModelCloseLifecycle.rows(state,"models").removeIf(row->m.equals(row.get("model")));
   List<Object> models=new ArrayList<>();for(Map<String,Object> row:ModelCloseLifecycle.rows(state,"models"))if(!m.equals(row.get("model")))models.add(row);
   state.put("models",models);
   if(eraseHook!=null)eraseHook.run();return null;});}
  void returned(){if(!leaveTargetVisible){for(Map<String,Object> row:ModelCloseLifecycle.rows(state,"windows"))if("a.asm".equals(row.get("model")))row.put("model",null);}
   state.put("active_window","1007");state.put("active_model","b.prt");}
 }
 static class Case {
  Fake f=new Fake();AtomicLong now=new AtomicLong(0);AtomicReference<String> generation=new AtomicReference<>("own-generation");
  ModelCloseLifecycle.Controller c=new ModelCloseLifecycle.Controller(f,generation::get,now::get);
  ModelCloseLifecycle.Ticket t=c.ticket(Json.map("operation","model.close","cli_invocation_id","controlled"),10);
  Map<String,Object> request(){return Json.map("model","a.asm","expected_session",copyDto(f.state));}
  void stage(){c.stage(t,request(),1);}
 }
 public static void main(String[]args){List<String> cases=new ArrayList<>();
  {Case x=new Case();x.stage();yes(x.f.closes==1 && x.f.erases==0 && !x.t.answer.isDone(),"must yield before erase");
   yes("1007".equals(x.f.selected),"only existing other selected");x.c.pump(1);yes(x.f.erases==0,"same tick cannot erase");
   x.f.returned();x.c.pump(2);yes(x.f.erases==1 && !x.t.answer.isDone(),"erase needs later independent read");
   x.c.pump(3);yes(x.t.answer.isDone()&&!x.t.answer.isCompletedExceptionally(),"complete after independent third tick");
   yes(((Number)x.t.answer.join().get("verification_tick")).intValue()==3,"actual tick retained");cases.add("three_phases");}
  {Case x=new Case();Map<String,Object> request=x.request();x.f.state.put("active_model","b.prt");x.c.stage(x.t,request,1);
   yes(x.f.closes==0&&x.f.erases==0&&!x.t.started(),"stale before is pre-mutation");cases.add("stale_expected_session");}
  {Case x=new Case();x.f.dirty=true;x.stage();yes(!x.t.started()&&x.f.closes==0,"dirty refuse");cases.add("dirty_refuse");}
  {Case x=new Case();x.now.set(20_000_000);x.stage();yes(x.f.reads==0&&x.f.closes==0,"expired stage no SDK");cases.add("expired_before_stage");}
  {Case x=new Case();x.stage();x.now.set(20_000_000);int n=x.f.reads;x.c.pump(2);yes(x.f.reads==n&&x.f.erases==0&&x.c.stopped.get()!=null,"late work cannot enter SDK");cases.add("late_return");}
  {Case x=new Case();x.stage();x.f.leaveTargetVisible=true;x.f.returned();x.c.pump(2);yes(x.f.erases==0&&x.t.answer.isCompletedExceptionally(),"still attached never erase");cases.add("window_not_closed");}
  {Case x=new Case();x.stage();x.f.returned();ModelCloseLifecycle.rows(x.f.state,"windows").get(1).put("id","changed");x.c.pump(2);
   yes(x.f.erases==0&&x.c.stopped.get()!=null,"non-target window change never erase");cases.add("other_window_change");}
  {Case x=new Case();x.stage();x.f.returned();ModelCloseLifecycle.modelRow(x.f.state,"a.asm").put("version_stamp","A2");x.c.pump(2);
   yes(x.f.erases==0,"target version changed never erase");cases.add("target_identity_change");}
  {Case x=new Case();x.stage();x.f.returned();x.c.pump(2);ModelCloseLifecycle.modelRow(x.f.state,"b.prt").put("modified",true);x.c.pump(3);
   yes(x.t.answer.isCompletedExceptionally(),"changed sibling not passed after erase");cases.add("after_erase_collateral");}
  {Case x=new Case();x.stage();x.generation.set("other-generation");int n=x.f.reads;x.c.pump(2);yes(x.f.reads==n&&x.f.erases==0,"new generation no SDK");cases.add("generation_change");}
  {Case x=new Case();x.stage();x.c.stop();int n=x.f.reads;x.c.pump(2);yes(x.f.reads==n&&x.f.erases==0,"stop no SDK");cases.add("stop_pending");}
  for(String stage:List.of("snapshot","resolve","modified")){Case x=new Case();Runnable late=()->x.now.set(20_000_000);
   if(stage.equals("snapshot"))x.f.readHook=late;else if(stage.equals("resolve"))x.f.resolveHook=late;else x.f.modifiedHook=late;
   x.stage();yes(x.f.closes==0&&!x.t.started()&&x.t.sdkEntered.get()&&x.c.pending.get()==null&&x.c.stopped.get()!=null,"entered getter expiry stops without claiming mutation");
   int n=x.f.reads+x.f.resolves+x.f.modifiedReads;ModelCloseLifecycle.Ticket other=x.c.ticket(Json.map("operation","later"),10);
   x.c.stage(other,x.request(),2);x.c.pump(3);yes(x.f.reads+x.f.resolves+x.f.modifiedReads==n&&x.f.closes==0&&x.f.erases==0,"expired getter blocks subsequent ticket SDK");
   cases.add("getter_deadline_"+stage);}
  {Case x=new Case();x.c.expire(x.t,"controlled_queue_expiry");yes(x.c.stopped.get()==null&&!x.t.sdkEntered.get()&&!x.t.started()&&x.f.reads==0,"pure queued expiry does not stop or claim SDK");
   ModelCloseLifecycle.Ticket next=x.c.ticket(Json.map("operation","later"),10);x.c.stage(next,x.request(),1);yes(x.f.closes==1,"queued withdrawal permits a fresh operation");cases.add("queued_withdrawal");}
  {Case x=new Case();x.stage();x.f.returned();x.f.eraseHook=()->x.now.set(20_000_000);x.c.pump(2);int n=x.f.reads;x.c.pump(3);
   yes(x.f.erases==1&&x.f.reads==n&&x.t.answer.isCompletedExceptionally(),"erase return after deadline unknown not extra SDK");cases.add("erase_deadline");}
  {Case x=new Case();x.f.state.put("windows",new ArrayList<>(List.of(Json.map("id","1007","model","b.prt"))));
   x.f.state.put("active_window","1007");x.f.state.put("active_model","b.prt");x.stage();yes(x.f.closes==0&&x.f.erases==1&&!x.t.answer.isDone(),"no-window erase still independent later read");x.c.pump(2);yes(!x.t.answer.isCompletedExceptionally(),"no-window success");cases.add("no_window");}
  yes(ModelCloseLifecycle.equivalent(Json.map("a",0),Json.map("a",0.0)),"JSON integer semantics");
  try {Case x=new Case();java.nio.file.Path dir=java.nio.file.Files.createTempDirectory("close-getter-expiry-");
   java.nio.file.Path log=java.nio.file.Files.createFile(dir.resolve("native.log"));AtomicInteger expiredEvents=new AtomicInteger();
   NativeReadTrace.initialize(dir,Json.map("service_instance_id","controlled-generation"),List.of(log),(path,bytes)->{
    if(new String(bytes,java.nio.charset.StandardCharsets.UTF_8).contains("request_wait_expired_while_started"))expiredEvents.incrementAndGet();});
   x.f.readHook=()->{x.now.set(20_000_000);x.c.expire(x.t,"controlled_http_wait_during_getter");};x.stage();
   yes(!x.t.started()&&x.t.sdkEntered.get()&&x.c.stopped.get()!=null,"HTTP wait during getter stops independently of mutation");
   Map<String,Object> evidence=NativeReadTrace.stopEvidence();yes(Boolean.TRUE.equals(evidence.get("stopped"))&&evidence.get("unreturned_request")!=null&&expiredEvents.get()==1,"controlled sink receives the unreturned SDK request once");
   int n=x.f.reads;Case other=new Case();other.stage();yes(other.f.reads==0&&x.f.reads==n,"global native diagnostic refuses other SDK after unfinished getter");cases.add("http_expiry_inside_getter_trace");
  }catch(Exception failure){throw new AssertionError(failure);}
  System.out.println(Json.write(Json.map("cases",cases,"CAD_calls",0,"CUA_calls",0,"native_qualification",false)));
 }
}
"""


def test_deferred_close_state_machine_and_complete_sdk_compile(tmp_path):
    root = Path(__file__).resolve().parents[1]
    java = Path("C:/Java/jdk-25/bin")
    sdk = Path("D:/PTC/Creo13.4/Creo 13.4.1.0/Common Files/text/java/otk.jar")
    if not (java / "javac.exe").is_file() or not sdk.is_file():
        pytest.skip("requires declared SDK/JDK; controlled only")
    harness = tmp_path / "ModelCloseHarness.java"
    harness.write_text(JAVA_HARNESS, encoding="utf-8")
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
    tested = subprocess.run(
        [
            str(java / "java.exe"),
            "-cp",
            os.pathsep.join((str(tmp_path / "classes"), str(sdk))),
            "com.fateforge.creocli.service.ModelCloseHarness",
        ],
        capture_output=True,
        timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    assert tested.returncode == 0, tested.stderr.decode("utf-8", "replace")
    evidence = json.loads(tested.stdout)
    assert len(evidence["cases"]) == 18
    assert evidence["CAD_calls"] == evidence["CUA_calls"] == 0
