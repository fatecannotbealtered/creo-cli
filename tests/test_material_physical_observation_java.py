"""SDK-interface substitutes for typed material reads, never a native CAD test."""

import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "service/src/com/fateforge/creocli/service"
JDK = Path(os.environ.get("JAVA_HOME", "C:/Java/jdk-25")) / "bin"
SDK = Path(
    os.environ.get("CREO_OTK_JAR", "D:/PTC/Creo13.4/Creo 13.4.1.0/Common Files/text/java/otk.jar")
)
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

HARNESS = r"""
package com.fateforge.creocli.service;
import java.lang.reflect.*;
import java.util.*;
import com.ptc.pfc.pfcPart.*;
import com.ptc.pfc.pfcModelItem.*;
import com.ptc.pfc.pfcSolid.*;
import com.ptc.wfc.wfcSolid.WSolidBody;

public final class MaterialPhysicalHarness {
    static String scenario;
    static int calls,currentCalls;
    static final List<String> passed = new ArrayList<>();
    static Object fail(String getter) {
        throw new IllegalStateException("untrusted-secret-text-must-not-be-emitted:" + getter);
    }
    static <T> T proxy(Class<T> type,InvocationHandler handler) {
        return type.cast(Proxy.newProxyInstance(
                type.getClassLoader(),new Class<?>[]{type},handler));
    }
    static Material material() {
        return proxy(Material.class,(self,method,args)-> {
            calls++;
            switch(method.getName()) {
            case "GetName":
                if(scenario.equals("name_error"))return fail("legacy name getter");
                return "PTC_SYSTEM_MTRL_PROPS";
            case "GetId":
                if(scenario.equals("id_error"))return fail("new identity getter");
                return 12;
            case "GetDescription":return "";
            case "GetMassDensity":
                if(scenario.equals("numeric"))return 2.7e-9;
                if(scenario.equals("nonfinite"))return Double.NaN;
                return fail("density");
            case "GetPropertyValue":
                if(scenario.equals("unset"))return null;
                if(scenario.equals("assigned"))return proxy(MaterialProperty.class,(p,m,a)-> {
                    if(m.getName().equals("GetValue"))return 2.7e-9;
                    if(m.getName().equals("GetUnits"))return null;
                    throw new UnsupportedOperationException(m.getName());
                });
                return fail("assigned property");
            default:throw new UnsupportedOperationException(method.getName());
            }
        });
    }
    static Part part() {
        Material material = material();
        WSolidBody body = proxy(WSolidBody.class,(self,method,args)-> {
            switch(method.getName()) {
            case "GetId":return 1;
            case "GetMaterial":return material;
            case "GetDensity":
                return scenario.equals("body_numeric") ? Double.valueOf(2.7e-9) : null;
            default:throw new UnsupportedOperationException(method.getName());
            }
        });
        return proxy(Part.class,(self,method,args)-> {
            calls++;
            switch(method.getName()) {
            case "GetCurrentMaterial":
                currentCalls++;
                if(scenario.equals("current_error"))return fail("current");
                return scenario.equals("current_null") ? null : material;
            case "GetIsModified":return false;
            case "ListMaterials":
                if(scenario.equals("inventory_null"))return null;
                return new com.ptc.pfc.pfcPart.Materials(0) {
                    public int getarraysize(){return 1;}
                    public Material get(int index){return material;}
                    public void xdelete(){}
                };
            case "ListItems":return new ModelItems(0) {
                public int getarraysize(){return scenario.equals("multiple_bodies") ? 2 : 1;}
                public ModelItem get(int index){return body;}
                public void xdelete(){}
            };
            default:throw new UnsupportedOperationException(method.getName());
            }
        });
    }
    @SuppressWarnings("unchecked")
    static Map<String,Object> map(Object value){return (Map<String,Object>)value;}
    static String status(Map<String,Object> value,String key){
        return String.valueOf(map(value.get(key)).get("status"));
    }
    static void require(boolean ok,String text){if(!ok)throw new AssertionError(text);}
    public static void main(String[] ignored) throws Exception {
        for(String name:List.of("numeric","assigned","unset","ambiguous_error","current_error",
                "current_null","inventory_null","nonfinite","multiple_bodies","body_numeric",
                "id_error","name_error")) {
            scenario=name;calls=0;currentCalls=0;
            if(name.equals("name_error")) {
                boolean refused=false;
                try {Materials.state(part());} catch(IllegalStateException expected) {refused=true;}
                require(refused,"legacy name read error not silently changed into null");
                require(currentCalls==1,"legacy name failure no second lookup");
                passed.add(name);continue;
            }
            Map<String,Object> value=Materials.state(part());
            Map<String,Object> observation=map(value.get("physical_observation"));
            Map<String,Object> density=map(observation.get("density"));
            Map<String,Object> property=map(observation.get("assigned_density"));
            require(observation.get("schema").equals("part_material_physical.v1"),"schema");
            if(name.equals("numeric")) {
                require(density.get("status").equals("value"),"numeric direct result");
                require(property.get("status").equals("unknown"),"unknown property retained");
            } else if(name.equals("assigned")) {
                require(property.get("status").equals("value"),"assigned result");
                require(map(property.get("value")).containsKey("units"),"null units retained");
            } else if(name.equals("unset")) {
                require(property.get("status").equals("unset"),"returned null is unset");
                require(density.get("status").equals("unknown"),"direct error not called absence");
            } else if(name.equals("ambiguous_error")) {
                require(property.get("status").equals("unknown"),"exception is unknown");
                require(property.containsKey("exception_type"),"typed error");
            } else if(name.equals("current_error")) {
                require(status(observation,"current_material").equals("unknown"),"current error");
            } else if(name.equals("current_null")) {
                require(status(observation,"current_material").equals("unset"),"current null");
            } else if(name.equals("inventory_null")) {
                require(status(observation,"loaded_materials").equals("unknown"),"null inventory");
            } else if(name.equals("nonfinite")) {
                require(density.get("status").equals("non_finite"),"nonfinite is unavailable");
            } else if(name.equals("multiple_bodies")) {
                require(status(observation,"body_materials").equals("unsupported_profile"),
                        "bounded body profile");
            } else if(name.equals("body_numeric")) {
                List<?> rows=(List<?>)map(observation.get("body_materials")).get("value");
                require(status(map(rows.get(0)),"density").equals("value"),"body numeric");
            } else if(name.equals("id_error")) {
                require(status(observation,"current_material").equals("unknown"),"new ID unknown");
                require(value.get("material").equals("PTC_SYSTEM_MTRL_PROPS"),"legacy name kept");
            }
            require(currentCalls==1,"one held current material; no second lookup");
            require(!Json.write(value).contains("untrusted-secret-text"),"no exception message");
            passed.add(name);
        }
        System.out.println(Json.write(Json.map("cases",passed,"CAD_calls",0,"CUA_calls",0,
                "native_qualification",false)));
    }
}
"""

STUBS = {
    "Creo.java": r"""
package com.fateforge.creocli.service;
import java.io.File;
import java.util.Map;
import com.ptc.pfc.pfcPart.Part;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcSession.Session;
import com.ptc.pfc.pfcSolid.Solid;
final class Creo {
    interface Call<T>{T run() throws Exception;}
    static Session session(){return null;}
    static Model part(Session session,String name){return null;}
    static File creoCommonFiles(){return new File("D:/declared");}
    static Map<String,Object> units(Solid part){return Json.map("length","mm","mass","tonne");}
    static Map<String,Object> massProperties(Solid part){
        return Json.map("mass",null,"density",null);
    }
    static String fileName(Model part){return "sample.prt";}
    static <T> T withConfig(Session session,String key,String value,String fallback,Call<T> call)
            throws Exception {
        return call.run();
    }
}
""",
    "PresentationOps.java": r"""
package com.fateforge.creocli.service;
import java.util.Map;
import com.ptc.pfc.pfcModel.Model;
final class PresentationOps {
    static Map<String,Object> targetIdentity(Model part){
        return Json.map("model","sample.prt","type","part","origin","D:/owned/sample.prt.1",
                "version_stamp","controlled","relation_id",15);
    }
    static <T> T contextRead(String source,NativeReadTrace.Call<T> call){
        try{return call.run();}catch(RuntimeException failure){throw failure;}
        catch(Throwable failure){return PresentationOps.<RuntimeException,T>raise(failure);}
    }
    @SuppressWarnings("unchecked")
    static <E extends Throwable,T>T raise(Throwable failure)throws E {throw (E)failure;}
}
""",
    "ModelOps.java": r"""
package com.fateforge.creocli.service;
final class ModelOps {
    static String expand(String value){return value;}
    static java.io.File creoCommonFiles(){return new java.io.File("D:/declared");}
}
""",
    "NativeReadTrace.java": r"""
package com.fateforge.creocli.service;
final class NativeReadTrace {
    interface Call<T>{T run()throws Throwable;}
    static void rethrowFatal(Throwable failure){}
}
""",
    "Failures.java": r"""
package com.fateforge.creocli.service;
final class Failures {
    static final class Refusal extends RuntimeException {
        Refusal(String code,String text){super(text);}
    }
}
""",
}


@pytest.mark.skipif(
    not ((JDK / "javac.exe").is_file() and (JDK / "java.exe").is_file() and SDK.is_file()),
    reason="requires declared SDK/JDK; controlled test never calls CAD",
)
def test_existing_material_state_preserves_read_outcomes_without_assigning_defaults(tmp_path):
    package = tmp_path / "com/fateforge/creocli/service"
    package.mkdir(parents=True)
    files = []
    for name, text in {"MaterialPhysicalHarness.java": HARNESS, **STUBS}.items():
        path = package / name
        path.write_text(text, encoding="utf-8")
        files.append(path)
    result = subprocess.run(
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
            str(SOURCE / "Materials.java"),
            str(SOURCE / "Json.java"),
            *map(str, files),
        ],
        capture_output=True,
        timeout=90,
        creationflags=FLAGS,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    executed = subprocess.run(
        [
            str(JDK / "java.exe"),
            "-cp",
            os.pathsep.join((str(tmp_path / "classes"), str(SDK))),
            "com.fateforge.creocli.service.MaterialPhysicalHarness",
        ],
        capture_output=True,
        timeout=20,
        creationflags=FLAGS,
    )
    assert executed.returncode == 0, executed.stderr.decode("utf-8", "replace")
    proof = json.loads(executed.stdout)
    assert len(proof["cases"]) == 12
    assert proof["CAD_calls"] == proof["CUA_calls"] == 0
    assert proof["native_qualification"] is False
