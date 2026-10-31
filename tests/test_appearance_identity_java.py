"""SDK-interface controlled appearance identity regression; never native CAD evidence."""

from __future__ import annotations

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
import com.ptc.pfc.pfcBase.ColorRGB;
import com.ptc.pfc.pfcModel.Model;
import com.ptc.pfc.pfcModel.ModelType;
import com.ptc.wfc.wfcDisplay.Appearance;
import com.ptc.wfc.wfcSelect.WSelection;
import com.ptc.wfc.wfcSolid.WSolid;
import com.ptc.wfc.wfcSolid.ItemAppearanceAndTextures;
import com.ptc.wfc.wfcSolid.ItemAppearanceAndTexturesSeq;

public final class AppearanceIdentityHarness {
    static final Map<String,State> states=new LinkedHashMap<>();
    static final IdentityHashMap<Model,State> byModel=new IdentityHashMap<>();
    static final List<String> passed=new ArrayList<>();
    static int factories,serial,repaints;
    static boolean failFactory,forceRename;
    static final class Assignments extends ItemAppearanceAndTexturesSeq {
        final State state;
        Assignments(State state) {super(0);this.state=state;}
        @Override public int getarraysize() {return state.appearance==null?0:1;}
        @Override public ItemAppearanceAndTextures get(int index) {
            return (ItemAppearanceAndTextures)Proxy.newProxyInstance(
                ItemAppearanceAndTextures.class.getClassLoader(),
                new Class<?>[]{ItemAppearanceAndTextures.class},(self,method,args)-> {
                    switch(method.getName()) {
                        case "GetAppearance":return state.appearance;
                        case "GetTextures":return null;
                        case "GetSelection":return state.selection;
                        case "getptr":return 0L;
                        case "xdelete":return null;
                        default:throw new UnsupportedOperationException(method.getName());
                    }
                });
        }
        @Override public void xdelete() {}
    }
    static final class App implements InvocationHandler {
        final Map<String,Object> fields=new LinkedHashMap<>();
        final Appearance proxy;
        int setCalls;
        App(double a,double d,double h,double s,double t,ColorRGB rgb,ColorRGB hrgb,
                double reflection,String name,String label,String description,String keywords) {
            fields.put("Ambient",a);fields.put("Diffuse",d);fields.put("Highlight",h);
            fields.put("Shininess",s);fields.put("Transparency",t);fields.put("RGBColor",rgb);
            fields.put("HighlightColor",hrgb);fields.put("Reflection",reflection);
            fields.put("Name",name);fields.put("Label",label);fields.put("Description",description);
            fields.put("Keywords",keywords);
            proxy=(Appearance)Proxy.newProxyInstance(Appearance.class.getClassLoader(),
                    new Class<?>[]{Appearance.class},this);
        }
        public Object invoke(Object self,Method method,Object[] args) {
            String name=method.getName();
            if (name.equals("getptr")) return 0L;
            if (name.equals("xdelete")) return null;
            if (name.equals("hashCode")) return System.identityHashCode(self);
            if (name.equals("equals")) return self==args[0];
            if (name.startsWith("Get")) return fields.get(name.substring(3));
            if (name.startsWith("Set")) {
                setCalls++;fields.put(name.substring(3),args[0]);return null;
            }
            throw new UnsupportedOperationException(name);
        }
    }
    static final class State {
        final String name,origin;
        final Model model;
        final WSelection selection;
        Appearance appearance;
        boolean modified,failAssignment;
        int assignments;
        State(String name,Appearance initial) {
            this.name=name;this.origin="D:/owned/"+name+".4";this.appearance=initial;
            model=(Model)Proxy.newProxyInstance(WSolid.class.getClassLoader(),
                    new Class<?>[]{WSolid.class},(self,method,args)-> {
                switch(method.getName()) {
                    case "GetIsModified":return modified;
                    case "GetAllAppearancesAndTextures":return new Assignments(this);
                    case "GetType":return ModelType.MDL_PART;
                    case "getptr":return 0L;
                    case "xdelete":return null;
                    case "hashCode":return System.identityHashCode(self);
                    case "equals":return self==args[0];
                    default:throw new UnsupportedOperationException(method.getName());
                }
            });
            selection=(WSelection)Proxy.newProxyInstance(WSelection.class.getClassLoader(),
                    new Class<?>[]{WSelection.class},(self,method,args)-> {
                switch(method.getName()) {
                    case "GetVisibleAppearance":return appearance;
                    case "GetSelModel":return model;
                    case "GetSelItem":return null;
                    case "SetVisibleAppearance":
                        Appearance intended=(Appearance)args[0];
                        // Controlled allocator substitute, NOT native naming semantics.
                        if (intended!=null && (intended.GetName().isEmpty() || forceRename))
                            app(intended).fields.put("Name","fixture_allocated_"+(++serial));
                        appearance=intended;modified=true;assignments++;
                        if(failAssignment) throw new IllegalStateException("after dirty");
                        return null;
                    case "getptr":return 0L;
                    case "xdelete":return null;
                    case "hashCode":return System.identityHashCode(self);
                    case "equals":return self==args[0];
                    default:throw new UnsupportedOperationException(method.getName());
                }
            });
            states.put(name,this);byModel.put(model,this);
        }
    }
    public static App app(Appearance appearance) {
        return (App)Proxy.getInvocationHandler(appearance);
    }
    public static Model model(String name) {return states.get(name).model;}
    public static WSelection selection(Model model) {return byModel.get(model).selection;}
    public static ColorRGB color(double r,double g,double b) {
        Map<String,Double> values=new HashMap<>();
        values.put("Red",r);values.put("Green",g);values.put("Blue",b);
        return (ColorRGB)Proxy.newProxyInstance(ColorRGB.class.getClassLoader(),
                new Class<?>[]{ColorRGB.class},(self,method,args)-> {
            String name=method.getName();
            if(name.equals("getptr")) return 0L;
            if(name.equals("xdelete")) return null;
            if(name.startsWith("Get")) return values.get(name.substring(3));
            if(name.equals("hashCode")) return System.identityHashCode(self);
            if(name.equals("equals")) return self==args[0];
            throw new UnsupportedOperationException(name);
        });
    }
    public static Appearance create(double a,double d,double h,double s,double t,ColorRGB rgb,
            ColorRGB hrgb,double reflection,String name,String label,
            String description,String keywords) {
        factories++;
        if(failFactory) throw new IllegalStateException("controlled constructor failure");
        return new App(a,d,h,s,t,rgb,hrgb,reflection,name,label,description,keywords).proxy;
    }
    static Appearance initial() {
        return create(.3,.7,0,.2,0,color(.125,.375,.875),color(1,1,1),0,
                "creo_cli_color","original label","description","keywords");
    }
    static Map<String,Object> request(State state,String action,boolean replace,Object value)
            throws Exception {
        return Json.map("model",state.name,"action",action,
            action.equals("set")?"rgb":"appearance",value,
            "reference_action",replace?"create_and_bind":"preserve",
            "reference_replacement_authorized",replace,
            "reference_allocation_policy","random_candidate_native_readback_v1",
            "expected_before",AppearanceOps.get(Json.map("model",state.name)),
            "expected_source_context",Json.map("model",state.name,"origin",state.origin));
    }
    static Map<String,Object> properties(Map<String,Object> row) {
        Map<String,Object> result=new LinkedHashMap<>(row);
        result.remove("rgb");result.remove("name");return result;
    }
    static void check(boolean value,String message) {
        if(!value) throw new AssertionError(message);
    }
    static void refusal(Map<String,Object> request,String code) throws Exception {
        try {AppearanceOps.set(request);throw new AssertionError("expected refusal");}
        catch(Failures.Refusal expected) {check(expected.code.equals(code),"refusal code");}
    }
    public static void main(String[] args) throws Exception {
        Appearance shared=initial();State target=new State("midframe.prt",shared);
        State other=new State("display.prt",shared);
        Map<String,Object> before=AppearanceOps.row(shared);int created=factories;
        AppearanceOps.set(request(target,"set",true,List.of(.125,.75,.5)));
        check(target.appearance!=shared && factories==created+1,"copy on write");
        check(other.appearance==shared && !other.modified,"still-used old reference");
        check(AppearanceOps.row(shared).equals(before) && app(shared).setCalls==0,"old read-only");
        check(properties(AppearanceOps.row(target.appearance)).equals(properties(before)),
                "all non-ID non-RGB properties copied");
        check(!target.appearance.GetName().equals(shared.GetName()),"allocated only after binding");
        passed.add("copy_on_write_does_not_mutate_an_old_reference_shared_by_two_sources");

        Appearance retained=target.appearance;created=factories;
        AppearanceOps.set(request(target,"set",false,List.of(.125,.75,.5)));
        check(target.appearance==retained && factories==created,"preserve same RGB no clone");
        check(app(retained).setCalls==0,"preserve never mutates current");
        passed.add("preserve_same_rgb_reapply_keeps_strict_identity_without_current_setters");

        Map<String,Object> restored=new LinkedHashMap<>(before);
        restored.put("ambient",.45);restored.put("diffuse",.8);restored.put("highlight",.1);
        restored.put("shininess",.9);restored.put("transparency",.12);restored.put("reflection",24.0);
        restored.put("label","recorded label");restored.put("description","recorded description");
        restored.put("keywords","recorded keywords");
        restored.put("highlight_rgb",List.of(.3,.7,1.0));
        AppearanceOps.set(request(target,"restore",true,restored));
        check(target.appearance!=retained,"restore creates and binds a separate reference");
        check(properties(AppearanceOps.row(target.appearance)).equals(properties(restored)),
                "full recorded display properties");
        check(!target.appearance.GetName().equals(restored.get("name")),
                "historical ID not restored");
        check(app(retained).setCalls==0 && app(shared).setCalls==0,
                "all old objects remain read-only");
        passed.add("recorded_restore_copies_all_properties_and_allocates_a_new_identifier");

        created=factories;
        AppearanceOps.set(request(target,"restore",false,null));
        check(target.appearance==null && factories==created,"native default null no factory");
        passed.add("default_restore_remains_explicit_null_assignment");
        State empty=new State("initial.prt",null);
        AppearanceOps.set(request(empty,"set",false,List.of(.1,.32,.9)));
        String firstCandidate=empty.appearance.GetName();
        check(firstCandidate.matches("cc_[0-9a-f]{24}"),"fresh bounded candidate");
        State emptyAgain=new State("initial2.prt",null);
        AppearanceOps.set(request(emptyAgain,"set",false,List.of(.12,.38,.9)));
        check(!emptyAgain.appearance.GetName().equals(firstCandidate),"distinct first allocations");
        passed.add("null_first_assignments_use_distinct_candidates_without_predicting_native_ids");

        // Controlled first-name-wins palette model, not a claim about Creo internals.
        Map<String,List<Double>> palette=new HashMap<>();
        palette.put("creo_cli_color",List.of(.12,.38,.9));
        palette.putIfAbsent("creo_cli_color",List.of(.1,.32,.9));
        check(!palette.get("creo_cli_color").equals(List.of(.1,.32,.9)),"old fixed-name collision");
        palette.clear();palette.put(emptyAgain.appearance.GetName(),List.of(.12,.38,.9));
        palette.putIfAbsent(firstCandidate,List.of(.1,.32,.9));
        check(palette.get(firstCandidate).equals(List.of(.1,.32,.9)),
                "distinct candidates avoid fixture alias");
        passed.add("controlled_same_name_reload_counterexample_is_not_a_native_cause_claim");

        State renamed=new State("renamed.prt",null);forceRename=true;
        try {AppearanceOps.set(request(renamed,"set",false,List.of(.125,.375,.875)));}
        finally {forceRename=false;}
        check(renamed.appearance.GetName().startsWith("fixture_allocated_"),"native may rename");
        passed.add("native_returned_name_remains_authoritative_when_candidate_is_renamed");

        State historical=new State("historical.prt",null);
        AppearanceOps.set(request(historical,"restore",false,restored));
        check(historical.appearance.GetName().matches("cc_[0-9a-f]{24}"),"restore fresh candidate");
        check(historical.appearance.GetLabel().equals(restored.get("label")),
                "restore label preserved");
        passed.add("null_restore_does_not_reuse_historical_identifier_or_change_label");

        State oldClient=new State("oldclient.prt",null);created=factories;
        Map<String,Object> missingPolicy=request(oldClient,"set",false,List.of(.125,.375,.875));
        missingPolicy.remove("reference_allocation_policy");refusal(missingPolicy,"E_UNSUPPORTED");
        check(factories==created && oldClient.assignments==0,"old client refused before setter");
        passed.add("allocation_requires_explicit_new_wire_policy_before_factory");

        State denied=new State("denied.prt",initial());created=factories;
        refusal(request(denied,"set",false,List.of(.125,.75,.5)),"E_UNSUPPORTED");
        Map<String,Object> unauth=request(denied,"set",true,List.of(.125,.75,.5));
        unauth.put("reference_replacement_authorized",false);refusal(unauth,"E_FORBIDDEN");
        check(factories==created && denied.assignments==0 && !denied.modified,
                "no unauthorized write");
        passed.add("existing_colour_change_requires_opt_in_before_any_factory_or_assignment");

        Map<String,Object> missing=request(denied,"set",true,List.of(.125,.75,.5));
        missing.remove("expected_before");refusal(missing,"E_VALIDATION");
        Map<String,Object> drift=request(denied,"set",true,List.of(.125,.75,.5));
        app(denied.appearance).fields.put("Label","concurrent");refusal(drift,"E_CONFLICT");
        Map<String,Object> context=request(denied,"set",true,List.of(.125,.75,.5));
        context.put("expected_source_context",Json.map("model",denied.name,"origin","D:/wrong"));
        refusal(context,"E_CONFLICT");
        check(factories==created && denied.assignments==0,"drift refused before native factory");
        passed.add("missing_or_drifted_expected_identity_properties_and_source_context_refuse");

        State numeric=new State("numeric.prt",initial());
        Map<String,Object> numericRequest=request(numeric,"set",true,List.of(.125,.75,.5));
        numericRequest=Json.object(Json.parse(Json.write(numericRequest)),"roundtrip");
        AppearanceOps.set(numericRequest);
        check(numeric.assignments==1,"0 vs 0.0 and JSON map ordering are semantic equals");
        passed.add("expected_before_compares_numeric_values_not_json_text_or_number_wrapper_types");

        State constructor=new State("constructor.prt",initial());
        Map<String,Object> constructorRequest=request(constructor,"set",true,List.of(.125,.75,.5));
        failFactory=true;
        try {AppearanceOps.set(constructorRequest);throw new AssertionError("factory failure");}
        catch(Failures.Stage stage) {
            check(stage.stage.equals("appearance_set") && constructor.assignments==0,
                    "factory is inside stage boundary");
            check(app(constructor.appearance).setCalls==0,"constructor failure no old mutation");
        } finally {failFactory=false;}
        passed.add("constructor_failure_is_stage_wrapped_without_old_object_mutation_or_rollback");

        State dirty=new State("dirty.prt",initial());Appearance old=dirty.appearance;
        Map<String,Object> dirtyRequest=request(dirty,"set",true,List.of(.125,.75,.5));
        dirty.failAssignment=true;
        try {AppearanceOps.set(dirtyRequest);throw new AssertionError("assignment failure");}
        catch(Failures.Stage stage) {
            check(stage.stage.equals("appearance_set")
                    && stage.detail.get("modified").equals(Boolean.TRUE),"dirty failure");
            check(dirty.appearance!=old && app(old).setCalls==0,"no rollback or old mutation");
            check(((Map<?,?>)stage.detail.get("before")).get("appearance")
                    .equals(AppearanceOps.row(old)),"immutable before retained");
        }
        passed.add("setter_failure_after_dirty_retains_before_and_does_not_save_rollback_or_replay");
        System.out.println(Json.write(Json.map("CAD_calls",0,"CUA_calls",0,
            "evidence_kind","controlled SDK-interface proxy regression; NOT native Creo",
            "cases",passed,"native_reference_creation_qualified",false)));
    }
}
"""

STUBS = {
    "com/ptc/pfc/pfcBase/pfcBase.java": r"""
package com.ptc.pfc.pfcBase;
public final class pfcBase {
    public static ColorRGB ColorRGB_Create(double r,double g,double b) {
        return com.fateforge.creocli.service.AppearanceIdentityHarness.color(r,g,b);
    }
}
""",
    "com/ptc/pfc/pfcSelect/pfcSelect.java": r"""
package com.ptc.pfc.pfcSelect;
import com.ptc.pfc.pfcModel.Model;
public final class pfcSelect {
    public static Selection CreateModelSelection(Model model) {
        return com.fateforge.creocli.service.AppearanceIdentityHarness.selection(model);
    }
}
""",
    "com/ptc/wfc/wfcDisplay/wfcDisplay.java": r"""
package com.ptc.wfc.wfcDisplay;
import com.ptc.pfc.pfcBase.ColorRGB;
public final class wfcDisplay {
    public static Appearance Appearance_Create(double a,double d,double h,double s,double t,
            ColorRGB rgb,ColorRGB hrgb,double reflection,String name,String label,
            String description,String keywords) {
        return com.fateforge.creocli.service.AppearanceIdentityHarness.create(
            a,d,h,s,t,rgb,hrgb,reflection,name,label,description,keywords);
    }
}
""",
    "com/fateforge/creocli/service/Creo.java": r"""
package com.fateforge.creocli.service;
import com.ptc.pfc.pfcModel.Model;
final class Creo {
    static Object session() {return null;}
    static Model part(Object ignored,String name) {return AppearanceIdentityHarness.model(name);}
    static String fileName(Model model) {return AppearanceIdentityHarness.byModel.get(model).name;}
    static Boolean modified(Model model) {
        return AppearanceIdentityHarness.byModel.get(model).modified;
    }
    static String origin(Model model) {return AppearanceIdentityHarness.byModel.get(model).origin;}
    static String typeName(com.ptc.pfc.pfcModel.ModelType type) {return "part";}
    static String enumName(Object value) {return String.valueOf(value);}
    static void repaint(Object ignored) {AppearanceIdentityHarness.repaints++;}
}
""",
    "com/fateforge/creocli/service/Failures.java": r"""
package com.fateforge.creocli.service;
import java.util.Map;
final class Failures {
    static final class Refusal extends RuntimeException {
        final String code;
        Refusal(String code,String message) {super(message);this.code=code;}
    }
    static final class Stage extends Exception {
        final String stage;final Map<String,Object> detail;
        Stage(String stage,Throwable cause,Map<String,Object> detail) {
            super(cause);this.stage=stage;this.detail=detail;
        }
    }
}
""",
}


@pytest.mark.skipif(
    not ((JDK / "javac.exe").is_file() and (JDK / "java.exe").is_file() and SDK.is_file()),
    reason="requires declared installed SDK/JDK; this controlled harness never calls CAD",
)
def test_copy_on_write_reference_contract_and_pre_mutator_guards(tmp_path):
    harness = tmp_path / "com/fateforge/creocli/service/AppearanceIdentityHarness.java"
    harness.parent.mkdir(parents=True)
    harness.write_text(HARNESS, encoding="utf-8")
    files = [harness]
    for relative, source in STUBS.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        files.append(path)
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
            str(SOURCE / "AppearanceOps.java"),
            str(SOURCE / "Json.java"),
            *map(str, files),
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
            "com.fateforge.creocli.service.AppearanceIdentityHarness",
        ],
        capture_output=True,
        timeout=20,
        creationflags=FLAGS,
    )
    assert executed.returncode == 0, executed.stderr.decode("utf-8", "replace")
    result = json.loads(executed.stdout)
    assert len(result["cases"]) == 14
    assert result["CAD_calls"] == result["CUA_calls"] == 0
    assert result["native_reference_creation_qualified"] is False
