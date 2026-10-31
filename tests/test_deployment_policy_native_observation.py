"""Compile the production policy method with SDK-free bounded getter doubles."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "service/src/com/fateforge/creocli/service/SessionOps.java"


def test_two_known_policy_getters_preserve_raw_classification_and_fatal_stop(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("requires the declared developer JDK")
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index("    static Map<String, Object> deploymentPolicy()")
    stop = source.index("    /** Fixed recovery", start)
    method = source[start:stop]
    exception = tmp_path / "com/ptc/pfc/pfcExceptions/XToolkitNotFound.java"
    exception.parent.mkdir(parents=True)
    exception.write_text(
        "package com.ptc.pfc.pfcExceptions; public class XToolkitNotFound "
        "extends RuntimeException {}",
        encoding="utf-8",
    )
    harness = tmp_path / "Harness.java"
    harness.write_text(
        "import java.util.*; public class Harness {\n"
        + method
        + r"""
static void require(boolean ok,String reason){if(!ok)throw new AssertionError(reason);}
@SuppressWarnings("unchecked")
public static void main(String[] ignored){
  for(String scenario:List.of("null","empty","notfound","unknown","space","long",
      "other","normal","fatal")){
    Creo.mode=scenario;Creo.calls=0;NativeReadTrace.calls=0;
    Map<String,Object> result;
    try {result=deploymentPolicy();}
    catch(VirtualMachineError fatal){
      require(scenario.equals("fatal"),"unexpected fatal");
      require(Creo.calls==1 && NativeReadTrace.calls==1,"fatal must stop before another getter");
      continue;
    }
    require(!scenario.equals("fatal"),"fatal was swallowed");
    require(Creo.calls==2 && NativeReadTrace.calls==2,"exactly two existing traced getters");
    Map<String,Object> signed=(Map<String,Object>)result.get("signed_observation");
    Map<String,Object> unsigned=(Map<String,Object>)result.get("unsigned_observation");
    require(unsigned.get("status").equals("recognized"),"unsigned observation");
    require(unsigned.get("raw").equals("always"),"unsigned raw");
    require(result.get("unsigned_apps").equals("always"),"unsigned normalized");
    require(signed.containsKey("raw"),"null raw must be explicit");
    String status=(String)signed.get("status");
    switch(scenario){
      case "null":require(status.equals("unsupported_null")&&signed.get("raw")==null,"null");break;
      case "empty":require(status.equals("unsupported_empty")&&
        signed.get("raw").equals(""),"empty");break;
      case "notfound":require(status.equals("unsupported_not_found")&&
        signed.get("exception_category").equals("XToolkitNotFound"),"typed not found");break;
      case "unknown":require(status.equals("unrecognized")&&
        signed.get("raw").equals("unexpected"),"unknown");break;
      case "space":require(status.equals("unrecognized")&&
        signed.get("raw").equals(" "),"space not empty");break;
      case "long":require(status.equals("unrecognized")&&((String)signed.get("raw")).length()==64&&
        signed.get("raw_truncated").equals(true),"bounded raw");break;
      case "other":require(status.equals("read_failed")&&
        signed.get("exception_category").equals("other_failure"),"other failure");break;
      case "normal":require(status.equals("recognized")&&signed.get("raw").equals(" Always ")&&
        result.get("signed_apps").equals("always"),"recognized preserves raw");break;
      default:throw new AssertionError("unexpected fixture");
    }
    require(result.get("complete").equals(scenario.equals("normal")),"generic complete preserved");
  }
  System.out.println("PASS 9 bounded getter scenarios");
}
}
class Json {
  static Map<String,Object> map(Object...args){
    Map<String,Object> result=new LinkedHashMap<>();
    for(int i=0;i<args.length;i+=2)result.put((String)args[i],args[i+1]);return result;
  }
}
class NativeReadTrace {
  static int calls;interface Call<T>{T run()throws Throwable;}
  static<T>T call(String name,Call<T> getter)throws Throwable{
    if(!name.matches("BaseSession.GetConfigOption\\(open_protk_(signed|unsigned)_apps\\)"))
      throw new AssertionError("unexpected native getter");
    calls++;return getter.run();
  }
  static void rethrowFatal(Throwable error){
    if(error instanceof VirtualMachineError)throw (VirtualMachineError)error;
  }
}
class Creo {
  static String mode;static int calls;static Creo session(){return new Creo();}
  String GetConfigOption(String option){
    calls++;if(option.equals("open_protk_unsigned_apps"))return "always";
    switch(mode){
      case "null":return null;case "empty":return "";
      case "notfound":throw new com.ptc.pfc.pfcExceptions.XToolkitNotFound();
      case "other":throw new IllegalStateException("controlled failure, never printed");
      case "unknown":return "unexpected";case "space":return " ";
      case "long":return "x".repeat(128);case "normal":return " Always ";
      case "fatal":throw new InternalError("controlled fatal");
      default:throw new AssertionError("fixture mode");
    }
  }
}
""",
        encoding="utf-8",
    )
    compiled = subprocess.run(
        [javac, "--release", "17", "-d", str(tmp_path), str(exception), str(harness)],
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert compiled.returncode == 0, compiled.stdout + compiled.stderr
    executed = subprocess.run(
        [java, "-cp", str(tmp_path), "Harness"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert executed.returncode == 0, executed.stdout + executed.stderr
    assert executed.stdout.strip() == "PASS 9 bounded getter scenarios"
