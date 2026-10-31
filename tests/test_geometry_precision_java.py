"""SDK-compiled Java accessor/JSON precision regression; no CAD calls or native proof."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from creo_cli import presentation

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "service/src/com/fateforge/creocli/service"
JDK = Path(os.environ.get("JAVA_HOME", "C:/Java/jdk-25")) / "bin"
SDK = Path(
    os.environ.get("CREO_OTK_JAR", "D:/PTC/Creo13.4/Creo 13.4.1.0/Common Files/text/java/otk.jar")
)
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

HARNESS = r"""
package com.fateforge.creocli.service;
import java.util.*;
import com.ptc.pfc.pfcBase.Point3D;
import com.ptc.pfc.pfcBase.Vector3D;
public final class GeometryPrecisionHarness {
    // Local accessors only: never call SDK create(), session, transport or CAD.
    static final class LocalPoint extends Point3D {
        final double[] values;
        LocalPoint(double... values) { super(0); this.values=values; }
        @Override public double get(int i) { return values[i]; }
        @Override public void xdelete() {}
    }
    static final class LocalVector extends Vector3D {
        final double[] values;
        LocalVector(double... values) { super(0); this.values=values; }
        @Override public double get(int i) { return values[i]; }
        @Override public void xdelete() {}
    }
    static Map<String,Object> example(String name,double base,double distance,double[] direction)
            throws Throwable {
        LocalVector vector=new LocalVector(direction);
        double exploded=base+direction[2]*distance;
        List<Object> point=Geometry.point(new LocalPoint(0,0,exploded));
        List<Object> observed=Geometry.vector(vector);
        double reconstructed=((Number)point.get(2)).doubleValue()
                -((Number)observed.get(2)).doubleValue()*distance;
        double oldReconstructed=Geometry.round(exploded)-Geometry.round(direction[2])*distance;
        return Json.map("name",name,"base",base,"distance",distance,
                "direction",observed,"direction_native_binary64",Geometry.vectorBinary64(vector),
                "exploded",point,"reconstructed",reconstructed,
                "old_9_decimal_reconstructed",oldReconstructed);
    }
    public static void main(String[] args) throws Throwable {
        List<Object> exact=Geometry.point(
                new LocalPoint(1e-12,1.2345678901234567,Math.nextUp(2.0)));
        List<Object> scale=Geometry.vector(new LocalVector(1.0000000000000002,1e-12,0));
        Map<String,Object> output=Json.map("CAD_calls",0,
                "evidence_kind","offline synthetic accessor regression; not native CAD",
                "precision",Geometry.precision(),"exact_point",exact,"unrenormalized_vector",scale,
                "examples",List.of(
                    example("archived_phone_diagonal",3.2,33.46640106136302,
                        new double[]{-.5976143046671968,-.35856858280031806,.7171371656006361}),
                    example("independent_equal_axes",.25,123.456789012345,
                        new double[]{1/Math.sqrt(3),1/Math.sqrt(3),1/Math.sqrt(3)})));
        System.out.println(Json.write(output));
    }
}
"""


@unittest.skipUnless(
    (JDK / "javac.exe").is_file() and (JDK / "java.exe").is_file() and SDK.is_file(),
    "requires declared JDK and installed licensed Creo SDK; never a CAD runtime test",
)
class GeometryNativePrecision(unittest.TestCase):
    def test_native_accessor_values_survive_json_and_original_diagonal_tolerance(self):
        with tempfile.TemporaryDirectory(prefix="creo-geometry-precision-") as temp:
            scratch = Path(temp)
            harness = scratch / "GeometryPrecisionHarness.java"
            harness.write_text(HARNESS, encoding="utf-8")
            classes = scratch / "classes"
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
                    str(classes),
                    *map(str, sorted(SOURCE.glob("*.java"))),
                    str(harness),
                ],
                capture_output=True,
                timeout=90,
                creationflags=FLAGS,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr.decode("utf-8", "replace"))
            executed = subprocess.run(
                [
                    str(JDK / "java.exe"),
                    "-cp",
                    os.pathsep.join((str(classes), str(SDK))),
                    "com.fateforge.creocli.service.GeometryPrecisionHarness",
                ],
                capture_output=True,
                timeout=15,
                creationflags=FLAGS,
            )
            self.assertEqual(executed.returncode, 0, executed.stderr.decode("utf-8", "replace"))
            data = json.loads(executed.stdout)
        self.assertEqual(data["CAD_calls"], 0)
        self.assertEqual(data["exact_point"], [1e-12, 1.2345678901234567, 2.0000000000000004])
        self.assertEqual(data["unrenormalized_vector"], [1.0000000000000002, 1e-12, 0])
        self.assertFalse(data["precision"]["display_formatting_used_for_verification"])
        for case in data["examples"]:
            with self.subTest(name=case["name"]):
                self.assertFalse(
                    presentation.equivalent(case["base"], case["old_9_decimal_reconstructed"])
                )
                self.assertTrue(presentation.equivalent(case["base"], case["reconstructed"]))
                self.assertEqual(
                    [float.fromhex(value) for value in case["direction_native_binary64"]],
                    case["direction"],
                )
