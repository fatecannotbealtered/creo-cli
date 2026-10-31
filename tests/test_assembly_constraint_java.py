"""SDK-compiled constraint adapter policy, without creating or calling CAD objects."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "service/src/com/fateforge/creocli/service"
JDK = Path(os.environ.get("JAVA_HOME", "C:/Java/jdk-25")) / "bin"
SDK = Path(
    os.environ.get(
        "CREO_OTK_JAR",
        "D:/PTC/Creo13.4/Creo 13.4.1.0/Common Files/text/java/otk.jar",
    )
)
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

HARNESS = r"""
package com.fateforge.creocli.service;
import java.util.*;
public final class ConstraintPolicyHarness {
    static int cases;
    static Map<String,Object> leaf(String name,Object value) {
        return Json.map("name",name,"value",value,"path",List.of(0,1),
            "value_state","returned_scalar","value_type","ARG_V_INTEGER");
    }
    static Map<String,Object> compound(Object... children) {
        return Json.map("compound",true,"children_read_complete",true,"children",List.of(children));
    }
    static Map<String,Object> emptyArray() {
        return Json.map("array",true,"children_read_complete",true,
            "children_state","returned_array",
            "flat_child_count",0,"children",List.of());
    }
    static Map<String,Object> ordinary(int type) {
        Map<String,Object> selected=Json.map("name","PRO_E_COMP_PLACE_INTERFACE_COMP",
            "value_kind","selection",
            "selection_read_complete",true,"selection_state","returned_null_optional","selection_count",0);
        Map<String,Object> assems=emptyArray();
        assems.put("name","PRO_E_COMP_PLACE_INTERFACE_ASSEMS");
        return Json.map("PRO_E_COMPONENT_SETS",emptyArray(),
            "PRO_E_COMPONENT_MOVEMENTS",emptyArray(),
            "PRO_E_COMPONENT_MISC_ATTR",leaf("PRO_E_COMPONENT_MISC_ATTR",0),
            "PRO_E_COMP_PLACE_INTERFACE",compound(leaf("PRO_E_COMP_PLACE_INTERFACE_TYPE",type),selected,assems));
    }
    static boolean admitted(Map<String,Object> roots,List<Object> attrs,
            List<Object> ids,int count) {
        return AssemblyConstraints.metadataSupported(roots,attrs,ids,count);
    }
    @SuppressWarnings("unchecked")
    static Map<String,Object> child(Map<String,Object> roots,String name) {
        Map<String,Object> placement=(Map<String,Object>)roots.get("PRO_E_COMP_PLACE_INTERFACE");
        for(Object raw:(List<?>)placement.get("children")) {
            Map<String,Object> item=(Map<String,Object>)raw;
            if(name.equals(item.get("name")))return item;
        }
        throw new AssertionError("missing fixture");
    }
    static void check(boolean value) {
        cases++; if (!value) throw new AssertionError("case " + cases);
    }
    static void refused(String code,Runnable action) {
        try { action.run(); throw new AssertionError("expected " + code); }
        catch(Failures.Refusal expected) { check(code.equals(expected.code)); }
    }
    static Map<String,Object> plane(double x) {
        return Json.map("origin",List.of(x,0,0),"normal",List.of(1,0,0),
            "frame",Json.map("origin",List.of(x,0,0),"x_axis",List.of(0,1,0),
                "y_axis",List.of(0,0,1),"z_axis",List.of(1,0,0)));
    }
    static Map<String,Object> auxiliaryReference() {
        return Json.map("model","root.asm","item_id",2,"item_type","ITEM_SURFACE",
            "component_path",List.of(),"path_present",true,"path_root_model","root.asm",
            "path_root_source","ComponentPath.GetRoot","path_leaf_model",null,
            "path_leaf_source","not_read_for_empty_path","reference_owner_model","root.asm",
            "reference_owner_source","DatumFeature.WFeature.GetSolid","plane",plane(0));
    }
    static Map<String,Object> nativeConstraint(Map<String,Object> ref,Object value) {
        return Json.map("type","align","native_type","ASM_CONSTRAINT_ALIGN_OFF",
            "assembly_reference",ref,"offset",value);
    }
    public static void main(String[] args) {
        List<Object> attrs=List.of(leaf("PRO_E_COMPONENT_CONSTR_ATTR",0));
        List<Object> ids=List.of(leaf("PRO_E_COMPONENT_CONSTR_SET_ID",-1));
        check(admitted(ordinary(-1),attrs,ids,1));
        check(admitted(ordinary(Ptc.PRO_ASM_INTFC_NONE),attrs,ids,1));
        check(!admitted(ordinary(1),attrs,ids,1));
        check(!admitted(ordinary(-1),List.of(leaf("PRO_E_COMPONENT_CONSTR_ATTR",32)),ids,1));
        check(!admitted(ordinary(-1),attrs,List.of(leaf("PRO_E_COMPONENT_CONSTR_SET_ID",0)),1));
        check(!admitted(ordinary(-1),attrs,List.of(),1));
        check(!admitted(ordinary(-1),List.of(),ids,1));
        check(!admitted(ordinary(-1),attrs,ids,3));
        Map<String,Object> altered=ordinary(-1);
        altered.remove("PRO_E_COMPONENT_SETS");
        check(!admitted(altered,attrs,ids,1));
        altered=ordinary(-1);
        altered.put("PRO_E_COMPONENT_SETS",compound(leaf("PRO_E_COMPONENT_SET_TYPE",0)));
        check(!admitted(altered,attrs,ids,1));
        altered=ordinary(-1);
        altered.put("PRO_E_COMPONENT_MISC_ATTR",leaf("PRO_E_COMPONENT_MISC_ATTR",32));
        check(!admitted(altered,attrs,ids,1));
        altered=ordinary(-1);
        altered.put("PRO_E_COMPONENT_MOVEMENTS",compound(leaf("PRO_E_COMPONENT_MOVEMENT_VALUE",4)));
        check(!admitted(altered,attrs,ids,1));
        altered=ordinary(-1);
        child(altered,"PRO_E_COMP_PLACE_INTERFACE_COMP").put("selection_count",1);
        check(!admitted(altered,attrs,ids,1));
        altered=ordinary(-1);
        child(altered,"PRO_E_COMP_PLACE_INTERFACE_COMP").remove("selection_read_complete");
        check(!admitted(altered,attrs,ids,1));
        altered=ordinary(-1);
        child(altered,"PRO_E_COMP_PLACE_INTERFACE_COMP").put("selection_state","getter_failed");
        check(!admitted(altered,attrs,ids,1));
        altered=ordinary(-1);
        child(altered,"PRO_E_COMP_PLACE_INTERFACE_ASSEMS").remove("children_read_complete");
        check(!admitted(altered,attrs,ids,1));
        altered=ordinary(-1);
        child(altered,"PRO_E_COMP_PLACE_INTERFACE_ASSEMS").put("flat_child_count",1);
        check(!admitted(altered,attrs,ids,1));
        altered=ordinary(-1);
        child(altered,"PRO_E_COMP_PLACE_INTERFACE_ASSEMS").put("children",List.of(leaf("unexpected",0)));
        check(!admitted(altered,attrs,ids,1));
        altered=ordinary(-1);
        child(altered,"PRO_E_COMP_PLACE_INTERFACE_TYPE").put("value_state","getter_failed");
        check(!admitted(altered,attrs,ids,1));
        check(!admitted(ordinary(-2),attrs,ids,1));
        altered=ordinary(-1); altered.put("unknown_root",leaf("unknown",0));
        check(!admitted(altered,attrs,ids,1));
        check(AssemblyConstraints.same(Json.map("id",17,"pose",List.of(1.25,2.0)),
            Json.parse("{\"id\":17,\"pose\":[1.25,2]}")));
        check(!AssemblyConstraints.same(Json.map("offset",1.0000000000001),Json.map("offset",1.0)));
        check(!AssemblyConstraints.same(Json.map("missing",null),Json.map()));
        check(!AssemblyConstraints.same(List.of(7,8),List.of(8,7)));
        Map<String,Object> diagnostic=Failures.error(new Failures.Stage("constraint_metadata_read",
            new Failures.Refusal("E_VERIFY_INCOMPLETE","required scalar returned null"),
            Json.map("element_name","PRO_E_COMPONENT_CONSTR_ATTR","indexed_path",List.of(4,2),
                "getter","Element.GetValue(metadata)","result_category","returned_null_required_scalar")));
        check("E_VERIFY_INCOMPLETE".equals(diagnostic.get("code")));
        check(diagnostic.containsKey("assembly_constraints") && !diagnostic.containsKey("sketch"));
        check(Ptc.PRO_ASM_INTFC_NONE==0);
        check(AssemblyConstraints.referencePathAdmitted(true,"owner.asm","pin.prt",false,
            17,false,List.of(),null,null,"pin.prt"));
        check(AssemblyConstraints.referencePathAdmitted(true,"owner.asm","pin.prt",false,
            17,true,List.of(17),"owner.asm","pin.prt","pin.prt"));
        check(!AssemblyConstraints.referencePathAdmitted(true,"owner.asm","pin.prt",false,
            17,true,List.of(17),"foreign.asm","pin.prt","pin.prt"));
        check(!AssemblyConstraints.referencePathAdmitted(true,"owner.asm","pin.prt",false,
            17,true,List.of(17),"owner.asm","wrong.prt","pin.prt"));
        check(!AssemblyConstraints.referencePathAdmitted(true,"owner.asm","pin.prt",false,
            17,true,List.of(18),"owner.asm","pin.prt","pin.prt"));
        check(!AssemblyConstraints.referencePathAdmitted(true,"owner.asm","pin.prt",false,
            17,false,List.of(17),null,null,"pin.prt"));
        check(!AssemblyConstraints.referencePathAdmitted(true,"owner.asm","pin.prt",false,
            17,true,List.of(),"owner.asm",null,"pin.prt"));
        check(AssemblyConstraints.referencePathAdmitted(true,"owner.asm","rigid.asm",true,
            17,true,List.of(),"rigid.asm",null,"rigid.asm"));
        check(!AssemblyConstraints.referencePathAdmitted(true,"owner.asm","pin.prt",false,
            17,true,List.of(),"pin.prt",null,"pin.prt"));
        check(!AssemblyConstraints.referencePathAdmitted(true,"owner.asm","pin.prt",false,
            17,true,List.of(17),"owner.asm",null,"pin.prt"));
        check(!AssemblyConstraints.referencePathAdmitted(true,"owner.asm","pin.prt",false,
            17,true,List.of(17,19),"owner.asm","pin.prt","pin.prt"));
        check(!AssemblyConstraints.referencePathAdmitted(false,"owner.asm","pin.prt",false,
            17,false,List.of(),null,null,"owner.asm"));
        check(AssemblyConstraints.referencePathAdmitted(false,"owner.asm","pin.prt",false,
            17,true,List.of(),"owner.asm",null,"owner.asm"));
        check(!AssemblyConstraints.referencePathAdmitted(false,"owner.asm","pin.prt",false,
            17,true,List.of(),"foreign.asm",null,"owner.asm"));
        check(AssemblyConstraints.referencePathAdmitted(false,"owner.asm","pin.prt",false,
            17,true,List.of(18),"owner.asm","pin.prt","pin.prt"));
        check(!AssemblyConstraints.referencePathAdmitted(false,"owner.asm","pin.prt",false,
            17,true,List.of(17),"owner.asm","pin.prt","pin.prt"));
        check(!AssemblyConstraints.referencePathAdmitted(false,"owner.asm","pin.prt",false,
            17,true,List.of(18),"foreign.asm","pin.prt","pin.prt"));
        check(!AssemblyConstraints.referencePathAdmitted(false,"owner.asm","pin.prt",false,
            17,true,List.of(18),"owner.asm","wrong.prt","pin.prt"));
        check(Service.instanceIdForReadback()==null);
        Map<String,Object> oldData=Json.map("constraints",List.of(
            Json.map("user_data",""),Json.map("user_data",null),Json.map("user_data","")));
        String unchanged=Json.write(oldData);
        check(AssemblyConstraints.retainedUserData(oldData,3).equals(Arrays.asList("",null,"")));
        check(unchanged.equals(Json.write(oldData)));
        check(AssemblyConstraints.retainedUserData(Json.map("constraints",List.of(
            Json.map("user_data",null),Json.map("user_data",null),Json.map("user_data",null))),3)
            .equals(Arrays.asList(null,null,null)));
        check(AssemblyConstraints.retainedUserData(Json.map("constraints",List.of(
            Json.map("user_data",""),Json.map("user_data",""),Json.map("user_data",""))),3)
            .equals(List.of("","","")));
        refused("E_UNSUPPORTED",()->AssemblyConstraints.retainedUserData(oldData,4));
        refused("E_VERIFY_INCOMPLETE",()->AssemblyConstraints.retainedUserData(
            Json.map("constraints",List.of(Json.map(),Json.map("user_data",null),
                Json.map("user_data",null))),3));
        refused("E_VERIFY_INCOMPLETE",()->AssemblyConstraints.retainedUserData(
            Json.map("constraints",List.of(Json.map("user_data",false),Json.map("user_data",null),
                Json.map("user_data",null))),3));
        refused("E_UNSUPPORTED",()->AssemblyConstraints.retainedUserData(
            Json.map("constraints",List.of(Json.map("user_data","opaque"),
                Json.map("user_data",null),Json.map("user_data",null))),3));
        refused("E_VERIFY_INCOMPLETE",()->AssemblyConstraints.retainedUserData(Json.map(),3));
        refused("E_VERIFY_INCOMPLETE",()->AssemblyConstraints.retainedUserData(
            Json.map("constraints",List.of("malformed",Json.map("user_data",null),
                Json.map("user_data",null))),3));
        check(AssemblyConstraints.PROFILE.equals("direct-planar-constraints-v2"));
        check(AssemblyConstraints.CAPABILITY_VERSION==2);
        Map<String,Object> auxRef=auxiliaryReference();
        check(AssemblyConstraints.uniqueAuxiliaryConstraint(
            List.of(nativeConstraint(auxRef,39.5)),auxRef,39.5)==0);
        check(AssemblyConstraints.uniqueAuxiliaryConstraint(List.of(
            nativeConstraint(auxRef,39.5),nativeConstraint(auxRef,39.5)),auxRef,39.5)==-1);
        Map<String,Object> foreignRef=auxiliaryReference();
        foreignRef.put("path_root_model","foreign.asm");
        check(AssemblyConstraints.uniqueAuxiliaryConstraint(
            List.of(nativeConstraint(auxRef,39.5)),foreignRef,39.5)==-1);
        check(AssemblyConstraints.uniqueAuxiliaryConstraint(
            List.of(nativeConstraint(auxRef,-29)),auxRef,-29)==0);
        check(AssemblyConstraints.uniqueAuxiliaryConstraint(
            List.of(nativeConstraint(auxRef,-29)),auxRef,29)==-1);
        check(AssemblyConstraints.uniqueAuxiliaryConstraint(
            List.of(nativeConstraint(auxRef,null)),auxRef,0)==0);
        Map<String,Object> missingOffset=nativeConstraint(auxRef,0);
        missingOffset.remove("offset");
        check(AssemblyConstraints.uniqueAuxiliaryConstraint(List.of(missingOffset),auxRef,0)==-1);
        Map<String,Object> missingRoot=auxiliaryReference(); missingRoot.remove("path_root_model");
        check(AssemblyConstraints.uniqueAuxiliaryConstraint(
            List.of(nativeConstraint(auxRef,0)),missingRoot,0)==-1);
        Map<String,Object> wrongKind=nativeConstraint(auxRef,0);
        wrongKind.put("native_type","ASM_CONSTRAINT_FIX");
        check(AssemblyConstraints.uniqueAuxiliaryConstraint(List.of(wrongKind),auxRef,0)==-1);
        check(AssemblyConstraints.auxiliaryPlaneEquation(plane(39.5),auxRef,39.5,0,null));
        check(!AssemblyConstraints.auxiliaryPlaneEquation(plane(39.5),auxRef,39.6,0,null));
        check(AssemblyConstraints.auxiliaryPlaneEquation(plane(-29),auxRef,-29,0,null));
        check(!AssemblyConstraints.auxiliaryPlaneEquation(plane(-29),auxRef,29,0,null));
        Map<String,Object> flipped=Json.map("origin",List.of(39.5,0,0),
            "normal",List.of(-1,0,0),"frame",Json.map("origin",List.of(39.5,0,0),
                "x_axis",List.of(0,1,0),"y_axis",List.of(0,0,-1),"z_axis",List.of(-1,0,0)));
        check(AssemblyConstraints.auxiliaryPlaneEquation(flipped,auxRef,39.5,1,null));
        check(!AssemblyConstraints.auxiliaryPlaneEquation(flipped,auxRef,39.5,0,null));
        check(!AssemblyConstraints.auxiliaryPlaneEquation(flipped,auxRef,39.5,2,null));
        Map<String,Object> translated=Json.map("origin",List.of(10,0,0),
            "x_axis",List.of(1,0,0),"y_axis",List.of(0,1,0),"z_axis",List.of(0,0,1));
        check(AssemblyConstraints.auxiliaryPlaneEquation(plane(15),auxRef,5,0,translated));
        Map<String,Object> rotated=Json.map("origin",List.of(10,20,0),
            "x_axis",List.of(0,1,0),"y_axis",List.of(-1,0,0),"z_axis",List.of(0,0,1));
        Map<String,Object> turnedPlane=Json.map("origin",List.of(10,25,0),
            "normal",List.of(0,1,0),"frame",Json.map("origin",List.of(10,25,0),
                "x_axis",List.of(-1,0,0),"y_axis",List.of(0,0,1),"z_axis",List.of(0,1,0)));
        check(AssemblyConstraints.auxiliaryPlaneEquation(turnedPlane,auxRef,5,0,rotated));
        check(!AssemblyConstraints.auxiliaryPlaneEquation(plane(0),auxRef,Double.NaN,0,null));
        Map<String,Object> noFrame=plane(0); noFrame.remove("frame");
        check(!AssemblyConstraints.auxiliaryPlaneEquation(noFrame,auxRef,0,0,null));
        Map<String,Object> leftHanded=Json.map("origin",List.of(0,0,0),
            "normal",List.of(1,0,0),"frame",Json.map("origin",List.of(0,0,0),
                "x_axis",List.of(0,0,1),"y_axis",List.of(0,1,0),"z_axis",List.of(1,0,0)));
        check(!AssemblyConstraints.auxiliaryPlaneEquation(leftHanded,auxRef,0,0,null));
        Map<String,Object> wrongOrigin=plane(0); wrongOrigin.put("origin",List.of(1,0,0));
        check(!AssemblyConstraints.auxiliaryPlaneEquation(wrongOrigin,auxRef,0,0,null));
        Map<String,Object> scaled=plane(0); scaled.put("normal",List.of(2,0,0));
        check(!AssemblyConstraints.auxiliaryPlaneEquation(scaled,auxRef,0,0,null));
        try {
            AssemblyConstraints.state(Json.map("model","never-opened.asm"));
            throw new AssertionError("unstarted generation must reject before any CAD call");
        } catch(Failures.Refusal expected) {
            check("E_VERIFY_INCOMPLETE".equals(expected.code));
        } catch(Exception unexpected) { throw new AssertionError(unexpected); }
        check(Service.instanceIdForReadback()==null);
        System.out.println(Json.write(Json.map("passed_cases",cases,"CAD_calls",0,"SDK_objects",0)));
    }
}
"""


@unittest.skipUnless(
    (JDK / "javac.exe").is_file() and (JDK / "java.exe").is_file() and SDK.is_file(),
    "requires declared JDK and installed licensed Creo SDK; never a CAD runtime test",
)
class AssemblyConstraintJavaPolicyTests(unittest.TestCase):
    def test_actual_sdk_compilation_and_metadata_rejections(self):
        with tempfile.TemporaryDirectory(prefix="creo-constraint-policy-") as temp:
            scratch = Path(temp)
            harness = scratch / "ConstraintPolicyHarness.java"
            harness.write_text(HARNESS, encoding="utf-8")
            classes = scratch / "classes"
            compile_result = subprocess.run(
                [
                    str(JDK / "javac.exe"),
                    "--release",
                    "17",
                    "-encoding",
                    "UTF-8",
                    "-cp",
                    str(SDK),
                    "-d",
                    str(classes),
                    *map(str, sorted(SOURCE.glob("*.java"))),
                    str(harness),
                ],
                capture_output=True,
                timeout=60,
                creationflags=FLAGS,
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                compile_result.stderr.decode("utf-8", "replace"),
            )
            result = subprocess.run(
                [
                    str(JDK / "java.exe"),
                    "-cp",
                    os.pathsep.join((str(classes), str(SDK))),
                    "com.fateforge.creocli.service.ConstraintPolicyHarness",
                ],
                capture_output=True,
                timeout=15,
                creationflags=FLAGS,
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
            self.assertEqual(
                json.loads(result.stdout),
                {"passed_cases": 84, "CAD_calls": 0, "SDK_objects": 0},
            )

    def test_used_public_element_ids_match_same_version_c_headers(self):
        header = SDK.parents[2] / "protoolkit/includes/ProElemId.h"
        if not header.is_file():
            self.skipTest("same-install C header unavailable")
        source = (SOURCE / "AssemblyConstraints.java").read_text(encoding="utf-8")
        used = set(re.findall(r"wfcElemIds\.(PRO_E_\w+)", source))
        header_text = header.read_text(encoding="utf-8")
        constants = subprocess.run(
            [
                str(JDK / "javap.exe"),
                "-constants",
                "-classpath",
                str(SDK),
                "com.ptc.wfc.wfcElemIds.wfcElemIds",
            ],
            capture_output=True,
            timeout=15,
            creationflags=FLAGS,
        )
        self.assertEqual(constants.returncode, 0)
        java_values = dict(
            re.findall(r"public static final int (PRO_E_\w+) = (\d+);", constants.stdout.decode())
        )
        self.assertGreaterEqual(len(used), 10)
        for name in used:
            with self.subTest(name=name):
                match = re.search(rf"#define\s+{re.escape(name)}\s+(\d+)", header_text)
                self.assertIsNotNone(match)
                self.assertEqual(java_values.get(name), match.group(1))
