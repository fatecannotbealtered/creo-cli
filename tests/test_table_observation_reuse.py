"""SDK-free production helper controls; no PTC objects or CAD calls."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "service/src/com/fateforge/creocli/service"
JDK = Path(os.environ["JAVA_HOME"]) / "bin" if os.environ.get("JAVA_HOME") else None
JAVAC = str(JDK / "javac.exe") if JDK and (JDK / "javac.exe").is_file() else shutil.which("javac")
JAVA = str(JDK / "java.exe") if JDK and (JDK / "java.exe").is_file() else shutil.which("java")
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class TableObservationWiringTests(unittest.TestCase):
    def test_bom_response_does_not_read_full_table_again(self):
        source = (SOURCE / "Detailing.java").read_text(encoding="utf-8")
        body = source.split("static Map<String, Object> addBom(", 1)[1].split(
            "private static int balloonNotes(", 1
        )[0]
        self.assertNotIn('out.put("table", tableRow(drawing, table))', body)
        self.assertIn("SummaryObservation.sameSummaryTable", body)


HARNESS = r"""
package com.fateforge.creocli.service;
import java.util.*;

public class SummaryObservationHarness {
    static Map<String,Object> table() {
        return Json.map("id", 7, "rows", 2, "columns", 5,
            "cells", Arrays.asList(
                Arrays.asList("ITEM NO", "PART NUMBER", "QTY", "DESCRIPTION", "NOTES"),
                Arrays.asList("1", "part", "2", "raw  double space", null)),
            "at", Arrays.asList(10.000000000000002, 90.0), "size", Arrays.asList(217.043, 15.24),
            "outline", Arrays.asList(Arrays.asList(10.000000000000002, 74.76),
                Arrays.asList(227.043, 90.0)),
            "rotation", 0.0, "segments", 1, "sheet", 1,
            "bounds_source", "Table.GetInfo(0).GetOutline; segment sheet transform",
            "from_format", false,
            "cell_references", new ArrayList<>(List.of(Json.map("row", 2, "column", 2,
                "region", 0, "model", "part.prt", "assembly", "support.asm",
                "source", "ProDwgtableCellRefmodelGet/ProDwgtableCellRegionGet"))));
    }
    static Map<String,Object> summary() {
        return Json.map("model", "instructions.drw", "type", "drawing",
            "models", List.of("support.asm"), "tables", new ArrayList<>(List.of(table())));
    }
    @SuppressWarnings("unchecked") static Map<String,Object> selected(Map<String,Object> s) {
        return (Map<String,Object>) ((List<?>)s.get("tables")).get(0);
    }
    static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }
    static void refuse(Map<String,Object> s) throws Exception {
        refuse(s, "instructions.drw");
    }
    static void refuse(Map<String,Object> s, String drawing) throws Exception {
        try { SummaryObservation.sameSummaryTable(s, drawing, 7); }
        catch (SummaryObservation.Incomplete expected) { return; }
        throw new AssertionError("incomplete or ambiguous observation accepted");
    }
    @SuppressWarnings("unchecked") public static void main(String[] args) throws Exception {
        String mode = args[0];
        Map<String,Object> s = summary();
        Map<String,Object> t = selected(s);
        switch (mode) {
        case "mixed-case":
            s.put("model", "INSTRUCTIONS.DRW");
            check(SummaryObservation.sameSummaryTable(s, "Instructions.dRw", 7) == t,
                "typed Creo identity is case-insensitive");
            break;
        case "requested-path": refuse(s, "D:/work/instructions.drw"); break;
        case "requested-bare": refuse(s, "instructions"); break;
        case "requested-version": refuse(s, "instructions.drw.1"); break;
        case "requested-part": refuse(s, "instructions.prt"); break;
        case "observed-path": s.put("model", "D:/work/instructions.drw"); refuse(s); break;
        case "observed-bare": s.put("model", "instructions"); refuse(s); break;
        case "observed-version": s.put("model", "instructions.drw.1"); refuse(s); break;
        case "observed-part": s.put("model", "instructions.prt"); refuse(s); break;
        case "observed-nontext": s.put("model", 7); refuse(s); break;
        case "observed-empty": s.put("model", ""); refuse(s); break;
        case "actual": {
            String before = Json.write(s);
            Map<String,Object> got = SummaryObservation.sameSummaryTable(s, "instructions.drw", 7);
            check(got == t, "must return the actual same-summary observation");
            check(Json.write(s).equals(before), "must not mutate the actual observation");
            check(((List<?>)((List<?>)got.get("cells")).get(1)).get(4) == null,
                "legacy optional null must remain null");
            check(((List<?>)((List<?>)got.get("cells")).get(1)).get(3).equals("raw  double space"),
                "raw text lost");
            check(Double.doubleToLongBits((Double)((List<?>)got.get("at")).get(0)) ==
                Double.doubleToLongBits(10.000000000000002), "raw coordinate rounded");
            break;
        }
        case "next-call": {
            SummaryObservation.sameSummaryTable(s, "instructions.drw", 7);
            Map<String,Object> second = summary();
            selected(second).put("rotation", 0.12345678901234567);
            check(SummaryObservation.sameSummaryTable(second, "instructions.drw", 7) ==
                selected(second), "cross-call cache");
            check(SummaryObservation.sameSummaryTable(second, "instructions.drw", 7)
                .get("rotation").equals(0.12345678901234567), "stale data");
            break;
        }
        case "optional-null":
            for (String key : List.of("at", "outline", "rotation", "bounds_source", "size"))
                t.put(key, null);
            check(SummaryObservation.sameSummaryTable(s, "instructions.drw", 7) == t,
                "optional null contract strengthened");
            break;
        case "null-summary": refuse(null); break;
        case "wrong-drawing": s.put("model", "other.drw"); refuse(s); break;
        case "missing-drawing": s.remove("model"); refuse(s); break;
        case "wrong-type": s.put("type", "part"); refuse(s); break;
        case "missing-tables": s.remove("tables"); refuse(s); break;
        case "null-tables": s.put("tables", null); refuse(s); break;
        case "no-match": t.put("id", 8); refuse(s); break;
        case "missing-id": t.remove("id"); refuse(s); break;
        case "string-id": t.put("id", "7"); refuse(s); break;
        case "duplicate-id": ((List<Object>)s.get("tables")).add(table()); refuse(s); break;
        case "non-map": ((List<Object>)s.get("tables")).add("bad"); refuse(s); break;
        case "missing-row": t.put("cells", List.of(List.of("header"))); refuse(s); break;
        case "missing-column":
            t.put("cells", List.of(List.of("header"), List.of("1"))); refuse(s); break;
        case "missing-cells": t.remove("cells"); refuse(s); break;
        case "bad-text":
            t.put("cells", List.of(List.of("a","b","c","d","e"),
                List.of("1","part",2,"d","e"))); refuse(s); break;
        case "missing-placement-field": t.remove("outline"); refuse(s); break;
        case "missing-owner": t.remove("from_format"); refuse(s); break;
        case "missing-references": t.remove("cell_references"); refuse(s); break;
        case "null-references": t.put("cell_references", null); refuse(s); break;
        case "empty-references": t.put("cell_references", List.of()); refuse(s); break;
        case "incomplete-reference":
            ((Map<String,Object>)((List<?>)t.get("cell_references")).get(0)).remove("model");
            refuse(s); break;
        case "outside-reference":
            ((Map<String,Object>)((List<?>)t.get("cell_references")).get(0)).put("column", 6);
            refuse(s); break;
        default: throw new IllegalArgumentException(mode);
        }
        System.out.println(Json.write(Json.map("case",mode,"checks",1,"native_calls",0,"PTC_objects",0)));
    }
}
"""


@unittest.skipUnless(JAVAC and JAVA, "SDK-free table controls require an available JDK")
class TableObservationHelperTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch = tempfile.TemporaryDirectory(prefix="creo-table-observation-")
        cls.classes = Path(cls.scratch.name) / "classes"
        harness = Path(cls.scratch.name) / "SummaryObservationHarness.java"
        harness.write_text(HARNESS, encoding="utf-8")
        result = subprocess.run(
            [
                JAVAC,
                "--release",
                "17",
                "-encoding",
                "UTF-8",
                "-d",
                str(cls.classes),
                str(SOURCE / "Json.java"),
                str(SOURCE / "SummaryObservation.java"),
                str(harness),
            ],
            capture_output=True,
            timeout=30,
            creationflags=FLAGS,
        )
        if result.returncode:
            cls.scratch.cleanup()
            raise AssertionError(result.stderr.decode("utf-8", "replace"))

    @classmethod
    def tearDownClass(cls):
        cls.scratch.cleanup()

    def run_case(self, mode):
        result = subprocess.run(
            [
                JAVA,
                "-cp",
                str(self.classes),
                "com.fateforge.creocli.service.SummaryObservationHarness",
                mode,
            ],
            capture_output=True,
            timeout=15,
            creationflags=FLAGS,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
        data = json.loads(result.stdout)
        self.assertEqual(data["native_calls"], 0)
        self.assertEqual(data["PTC_objects"], 0)

    def test_actual_summary_values_and_optional_nulls_are_unchanged(self):
        self.run_case("actual")
        self.run_case("optional-null")

    def test_typed_drawing_identity_allows_case_only(self):
        for case in (
            "mixed-case",
            "wrong-drawing",
            "missing-drawing",
            "wrong-type",
            "requested-path",
            "requested-bare",
            "requested-version",
            "requested-part",
            "observed-path",
            "observed-bare",
            "observed-version",
            "observed-part",
            "observed-nontext",
            "observed-empty",
        ):
            with self.subTest(case=case):
                self.run_case(case)

    def test_next_call_uses_its_own_actual_observation(self):
        self.run_case("next-call")

    def test_missing_or_wrong_drawing_is_incomplete(self):
        for case in ("null-summary", "wrong-drawing", "missing-drawing", "wrong-type"):
            with self.subTest(case=case):
                self.run_case(case)

    def test_missing_or_ambiguous_table_inventory_is_incomplete(self):
        for case in (
            "missing-tables",
            "null-tables",
            "no-match",
            "missing-id",
            "string-id",
            "duplicate-id",
            "non-map",
        ):
            with self.subTest(case=case):
                self.run_case(case)

    def test_incomplete_row_shapes_are_incomplete(self):
        for case in (
            "missing-row",
            "missing-column",
            "missing-cells",
            "bad-text",
            "missing-placement-field",
            "missing-owner",
        ):
            with self.subTest(case=case):
                self.run_case(case)

    def test_missing_or_incomplete_native_references_are_incomplete(self):
        for case in (
            "missing-references",
            "null-references",
            "empty-references",
            "incomplete-reference",
            "outside-reference",
        ):
            with self.subTest(case=case):
                self.run_case(case)
