"""Execute the actual Service queue methods with controlled lifecycle states, no CAD."""

import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "service/src/com/fateforge/creocli/service"
JDK = Path("C:/Java/jdk-25/bin")


def method(text, signature):
    begin = text.index(signature)
    opening = text.index("{", begin)
    depth = 1
    end = opening + 1
    while depth:
        depth += (text[end] == "{") - (text[end] == "}")
        end += 1
    return text[begin:end]


@pytest.mark.skipif(not (JDK / "javac.exe").exists(), reason="local JDK required")
def test_actual_service_queue_yields_and_only_rejects_while_blocked(tmp_path):
    actual = (JAVA / "Service.java").read_text(encoding="utf-8")
    methods = "\n".join(
        method(actual, signature)
        for signature in (
            "private static void drain()",
            "private static void refuseStoppedQueue()",
            "private static void requireContextQueueAvailable()",
        )
    )
    harness = r"""
package com.fateforge.creocli.service;
import java.util.*;
import java.util.concurrent.*;
public final class QueueHarness {
 static final Queue<Runnable> QUEUE=new ConcurrentLinkedQueue<>();
 static final int MAX_JOBS_PER_TICK=8;
 static long PUMP_TICK;
 static int sdk,rejected;
 static final class ToolkitFailure extends Exception {ToolkitFailure(Map<String,Object>x){}}
 static final class Failures {static final class Refusal extends RuntimeException {
  String code="E_UNAVAILABLE";Refusal(){super("stopped");}}}
 static class Lifecycle {
  boolean blocked,stopped,finish;
  boolean pulse(){if(finish){finish=false;blocked=false;return true;}return blocked;}
 }
 static final Lifecycle close=new Lifecycle(),ctx=new Lifecycle(),exit=new Lifecycle();
 static final class ModelCloseLifecycle {
  static boolean pump(long t){return close.pulse();}
  static boolean blocksQueue(){return close.blocked;}
  static void healthy(){if(close.stopped)throw new Failures.Refusal();}
  static Map<String,Object>status(){return Map.of();}
 }
 static final class ContextActivation {
  static boolean pump(long t){return ctx.pulse();}
  static boolean blocksQueue(){return ctx.blocked;}
  static boolean hasStopped(){return ctx.stopped;}
  static void healthy(){if(ctx.stopped)throw new Failures.Refusal();}
  static Map<String,Object>status(){return Map.of();}
 }
 static final class OwnedSessionExit {
  static boolean pump(){return exit.pulse();}
  static boolean blocksQueue(){return exit.blocked;}
  // None of these seven cases enters a native exit command. A pending pump
  // must therefore still reject queued work through the real Service method.
  static boolean invocationStarted(){return false;}
  static Map<String,Object>status(){return Map.of();}
 }
 static void log(String s){}
 static String describe(Throwable t){return t.getClass().getName();}
 /*ACTUAL_METHODS*/
 static void queue(){QUEUE.add(()->{try{requireContextQueueAvailable();sdk++;}
  catch(ToolkitFailure denied){rejected++;}});}
 static void reset(){QUEUE.clear();sdk=0;rejected=0;
  for(Lifecycle l:List.of(close,ctx,exit)){l.blocked=false;l.stopped=false;l.finish=false;}}
 static void check(boolean b,String message){if(!b)throw new AssertionError(message);}
 public static void main(String[]args){
  reset();close.blocked=true;close.finish=true;queue();drain();
  check(sdk==0&&QUEUE.size()==1,"close success tick executed queued SDK");drain();
  check(sdk==1,"next free tick did not execute queued work");
  reset();close.blocked=true;queue();drain();
  check(sdk==0&&rejected==1,"pending close allowed SDK");
  reset();close.blocked=true;close.stopped=true;queue();drain();
  check(sdk==0&&rejected==1,"stopped close allowed SDK");
  reset();ctx.blocked=true;ctx.finish=true;queue();drain();
  check(sdk==0&&QUEUE.size()==1,"context success tick executed queued SDK");
  reset();ctx.blocked=true;ctx.stopped=true;queue();drain();
  check(sdk==0&&rejected==1,"stopped context allowed SDK");
  reset();exit.blocked=true;queue();drain();
  check(sdk==0&&rejected==1,"pending exit allowed SDK");
  reset();queue();refuseStoppedQueue();
  check(sdk==0&&QUEUE.size()==1,"unblocked refusal helper dispatched SDK");
  System.out.println("{\"cases\":7,\"SDK\":0,\"CAD\":0,\"checks\":["+
    "\"close_yield_then_next_tick\",\"pending_close_rejected\",\"stopped_close_rejected\","+
    "\"context_yield\",\"stopped_context_rejected\",\"pending_exit_rejected\","+
    "\"unblocked_refusal_does_not_dispatch\"]}");
 }
}
""".replace("/*ACTUAL_METHODS*/", methods)
    source = tmp_path / "com/fateforge/creocli/service"
    source.mkdir(parents=True)
    (source / "QueueHarness.java").write_text(harness, encoding="utf-8")
    (source / "Json.java").write_bytes((JAVA / "Json.java").read_bytes())
    classes = tmp_path / "classes"
    built = subprocess.run(
        [
            str(JDK / "javac.exe"),
            "--release",
            "17",
            "-encoding",
            "UTF-8",
            "-d",
            str(classes),
            *map(str, source.glob("*.java")),
        ],
        capture_output=True,
    )
    assert built.returncode == 0, built.stderr.decode("utf-8", errors="replace")
    result = subprocess.run(
        [str(JDK / "java.exe"), "-cp", str(classes), "com.fateforge.creocli.service.QueueHarness"],
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    outcome = json.loads(result.stdout)
    assert outcome["cases"] == len(outcome["checks"]) == 7
    assert outcome["SDK"] == outcome["CAD"] == 0
    print(result.stdout.decode("utf-8").strip())
