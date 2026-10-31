"""Compile the exact readiness recovery method with bounded SDK getter doubles."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_fixed_recovery_getters_and_inherited_process_root(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("requires the declared developer JDK")
    source = (ROOT / "service/src/com/fateforge/creocli/service/SessionOps.java").read_text(
        encoding="utf-8"
    )
    start = source.index("    static Map<String, Object> recoveryConfiguration()")
    stop = source.index("    /** Complete bounded", start)
    method = source[start:stop]
    sequence = tmp_path / "com/ptc/cipjava/stringseq.java"
    sequence.parent.mkdir(parents=True)
    sequence.write_text(
        "package com.ptc.cipjava; public class stringseq { String[] values; "
        "public stringseq(String...v){values=v;} public int getarraysize(){return values.length;}"
        "public String get(int index){return values[index];}}",
        encoding="utf-8",
    )
    harness = tmp_path / "RecoveryHarness.java"
    harness.write_text(
        "import java.util.*; public class RecoveryHarness {\n"
        + method
        + r"""
static void require(boolean ok,String why){if(!ok)throw new AssertionError(why);}
public static void main(String[] ignored){
  for(String scenario:List.of("normal","null","empty","long","multi","failed","fatal")){
    Creo.mode=scenario;Creo.calls=0;NativeReadTrace.calls=0;
    Map<String,Object> value;
    try{value=recoveryConfiguration();}
    catch(VirtualMachineError failure){
      require(scenario.equals("fatal"),"unexpected fatal");
      require(Creo.calls==1 && NativeReadTrace.calls==1,"fatal must stop before second getter");
      continue;
    }
    require(!scenario.equals("fatal"),"fatal swallowed");
    require(Creo.calls==2 && NativeReadTrace.calls==2,"exactly two fixed readiness getters");
    require(value.get("workflow_root").equals("D:/owned/runtime/wfroot"),
      "actual child environment");
    require(value.get("last_session_retrieval").equals("YES"),"preserve raw native enum");
    require(value.get("last_session_retrieval_readback").equals("observed"),"observed enum");
    require(value.get("complete").equals(scenario.equals("normal")),
      "unknown readback stays incomplete");
    if(scenario.equals("normal")){
      require(value.get("last_session_directory_path").equals("D:/owned/runtime/session-history"),
        "actual native directory");
      require(value.get("last_session_directory_path_value_count").equals(1),"one scalar path");
    }else{
      require(value.get("last_session_directory_path")==null,"missing directory not invented");
      require(!value.get("last_session_directory_path_readback").equals("observed"),
        "failed read not observed");
    }
  }
  System.out.println("PASS 7 fixed recovery getter scenarios");
}
}
class Json {
  static Map<String,Object> map(Object... args){
    Map<String,Object> value=new LinkedHashMap<>();
    for(int i=0;i<args.length;i+=2)value.put((String)args[i],args[i+1]);return value;
  }
}
class NativeReadTrace {
  static int calls;interface Call<T>{T run()throws Throwable;}
  static<T>T call(String name,Call<T> getter)throws Throwable{
    if(!name.matches("BaseSession.GetConfigOption(?:Values)?\\(last_session_(directory_path|retrieval)\\)"))
      throw new AssertionError("unexpected getter");
    calls++;return getter.run();
  }
  static void rethrowFatal(Throwable failure){
    if(failure instanceof VirtualMachineError)throw(VirtualMachineError)failure;
  }
}
class Creo {
  static String mode;static int calls;static Creo session(){return new Creo();}
  String GetConfigOption(String option){
    calls++;
    if(!option.equals("last_session_retrieval"))
      throw new AssertionError("short getter used for long path");
    return "YES";
  }
  com.ptc.cipjava.stringseq GetConfigOptionValues(String option){
    calls++;
    if(!option.equals("last_session_directory_path"))
      throw new AssertionError("wrong vector getter");
    switch(mode){
      case "normal":return new com.ptc.cipjava.stringseq("D:/owned/runtime/session-history");
      case "null":return null;case "empty":return new com.ptc.cipjava.stringseq("");
      case "long":return new com.ptc.cipjava.stringseq("x".repeat(261));
      case "multi":return new com.ptc.cipjava.stringseq("first","second");
      case "failed":throw new IllegalStateException("controlled SDK error, no native call");
      case "fatal":throw new InternalError("controlled fatal");
      default:throw new AssertionError(mode);
    }
  }
}
""",
        encoding="utf-8",
    )
    compiled = subprocess.run(
        [javac, "--release", "17", "-d", str(tmp_path), str(sequence), str(harness)],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    environment = dict(os.environ, PTC_WF_ROOT="D:/owned/runtime/wfroot")
    result = subprocess.run(
        [java, "-cp", str(tmp_path), "RecoveryHarness"],
        capture_output=True,
        text=True,
        timeout=20,
        env=environment,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == "PASS 7 fixed recovery getter scenarios"


def test_recovery_getters_are_readiness_only_not_ordinary_session_status():
    service = (ROOT / "service/src/com/fateforge/creocli/service/Service.java").read_text(
        encoding="utf-8"
    )
    session = (ROOT / "service/src/com/fateforge/creocli/service/SessionOps.java").read_text(
        encoding="utf-8"
    )
    assert (
        service.count('out.put("recovery_configuration",SessionOps.recoveryConfiguration())') == 1
    )
    status = session[session.index("    static Map<String, Object> status()") :]
    assert "recoveryConfiguration()" not in status
