"""The element-tree vocabulary the Creo-side service uses, held to PTC's own definitions.

Nothing about an element tree is checked by a compiler. An element id off by one, a
value from the wrong enumeration, a level too deep -- each builds and ships, and then
fails on a live Creo with "general error" and nothing more. This project has no
feedback loop tight enough to find those one at a time, so they are found here.

Three independent sources are involved, and the tests make them agree:

  contract/feature-trees.json   derived from the C headers in protoolkit/includes
  contract/otk-interface.json   derived from otk.jar's wfcElemIds by introspection
  service/.../Ptc.java          the constants the service actually sends to Creo

The two PTC sources disagree about sixteen element ids in Creo 13.4. Which one is
right cannot be settled offline, so the service is simply forbidden from using any of
them; the disagreement itself is pinned, so an upgrade that changes it is noticed.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TREES = json.loads((ROOT / "contract" / "feature-trees.json").read_text(encoding="utf-8"))
OTK = json.loads((ROOT / "contract" / "otk-interface.json").read_text(encoding="utf-8"))
SERVICE = ROOT / "service" / "src" / "com" / "fateforge" / "creocli" / "service"
PTC_JAVA = (SERVICE / "Ptc.java").read_text(encoding="utf-8")
MODELING_JAVA = "\n".join(p.read_text(encoding="utf-8") for p in sorted(SERVICE.glob("*.java")))

HEADER_IDS = TREES["element_ids"]["values"]
JAVA_IDS = OTK["element_ids"]["values"]
ENUM_MEMBERS = {
    member: (value, enum)
    for enum, body in TREES["enums"].items()
    for member, value in body["values"].items()
}
FEATURE_TYPES = TREES["feature_types"]["values"]
CONSTANT = re.compile(r"static final int (PRO_[A-Z0-9_]+) = (-?\d+);")
DECLARED = {name: int(value) for name, value in CONSTANT.findall(PTC_JAVA)}

# Element ids on which ProElemId.h and wfcElemIds disagree in Creo 13.4.1.0.
KNOWN_DISAGREEMENTS = {
    "PRO_E_CRN_CHMF_CORNER",
    "PRO_E_CRN_CHMF_DIM1",
    "PRO_E_CRN_CHMF_DIM2",
    "PRO_E_CRN_CHMF_DIM3",
    "PRO_E_DESIGN_CONSTR_MILL_OPT",
    "PRO_E_DESIGN_CONSTR_MILL_ORIENT_NEG_X",
    "PRO_E_DESIGN_CONSTR_MILL_ORIENT_NEG_Y",
    "PRO_E_DESIGN_CONSTR_MILL_ORIENT_NEG_Z",
    "PRO_E_DESIGN_CONSTR_MILL_ORIENT_POS_X",
    "PRO_E_DESIGN_CONSTR_MILL_ORIENT_POS_Y",
    "PRO_E_DESIGN_CONSTR_MILL_ORIENT_POS_Z",
    "PRO_E_DRAPE_SLIT_CURVES",
    "PRO_E_LATTICE_STOCH_DISTORTION",
    "PRO_E_LOOP_CRV_DOMAIN",
    "PRO_E_MOLD_INS_ROT_ARR",
    "PRO_E_MOLD_INS_ROT_SET",
}
# Names drawn in PTC's tree diagrams that are not element ids at all -- typos in the
# headers' ASCII art (PRO_E_FEAT_TYPE for PRO_E_FEATURE_TYPE and so on).
KNOWN_DIAGRAM_ERRATA = {
    "PRO_E_CORNER_SEAM_RMV_DEFAULT",
    "PRO_E_FEAT_TYPE",
    "PRO_E_MFG_CLOSED_LOOP_ARR",
    "PRO_E_MFG_ENABLE_CMM_OPT",
    "PRO_E_SMT_BBACK_FLAT_CONTOURS_ARR",
    "PRO_E_STD_FEATURE_TYPE",
    "PRO_E_VPDD_CONST_OR_VAR",
}


def disagreements() -> set[str]:
    return {k for k in set(HEADER_IDS) & set(JAVA_IDS) if HEADER_IDS[k] != JAVA_IDS[k]}


def tree_nodes(stem: str, root: str = "PRO_E_FEATURE_TREE") -> list[dict]:
    for diagram in TREES["trees"][stem]["diagrams"]:
        if diagram["root"] == root:
            return diagram["nodes"]
    raise AssertionError(f"{stem} has no diagram rooted at {root}")


def paths(nodes: list[dict]) -> set[tuple[str, ...]]:
    """Every root-to-node path in one diagram."""
    out, stack = set(), []
    for node in nodes:
        del stack[node["depth"] :]
        stack.append(node["name"])
        out.add(tuple(stack))
    return out


class IndexProvenance(unittest.TestCase):
    def test_every_header_read_is_recorded_by_digest(self):
        digests = TREES["source"]["headers_sha256"]
        self.assertIn("ProElemId.h", digests)
        self.assertIn("ProExtrude.h", digests)
        for name, digest in digests.items():
            self.assertRegex(digest, r"^[0-9a-f]{64}$", name)

    def test_the_index_is_large_enough_to_be_the_real_thing(self):
        # A parser regression that silently drops most of a header should not pass
        # as a smaller but plausible index.
        self.assertGreater(TREES["element_ids"]["count"], 5000)
        self.assertGreater(len(TREES["trees"]), 100)
        self.assertGreater(len(TREES["enums"]), 800)


class TwoPtcSourcesAgree(unittest.TestCase):
    def test_the_headers_and_the_java_library_agree_except_where_pinned(self):
        self.assertEqual(
            disagreements(),
            KNOWN_DISAGREEMENTS,
            "the set of element ids on which PTC's C headers and wfcElemIds disagree "
            "has changed; a Creo upgrade renumbered something",
        )

    def test_diagram_names_resolve_to_ids_except_the_known_errata(self):
        unresolved = {
            n["name"]
            for t in TREES["trees"].values()
            for d in t["diagrams"]
            for n in d["nodes"]
            if n["name"] not in HEADER_IDS
        }
        self.assertEqual(unresolved, KNOWN_DIAGRAM_ERRATA)


class ServiceConstants(unittest.TestCase):
    def test_constants_were_found(self):
        self.assertGreater(len(DECLARED), 30)

    def test_every_constant_is_a_ptc_name_with_ptcs_value(self):
        for name, value in DECLARED.items():
            with self.subTest(name=name):
                if name.startswith("PRO_E_"):
                    self.assertIn(name, HEADER_IDS, "not an element id in ProElemId.h")
                    self.assertEqual(value, HEADER_IDS[name])
                elif name.startswith("PRO_FEAT_"):
                    self.assertIn(name, FEATURE_TYPES, "not a feature type in ProFeatType.h")
                    self.assertEqual(value, FEATURE_TYPES[name])
                else:
                    self.assertIn(
                        name, ENUM_MEMBERS, "not a member of any enumeration in the headers"
                    )
                    self.assertEqual(
                        value, ENUM_MEMBERS[name][0], f"value in {ENUM_MEMBERS[name][1]}"
                    )

    def test_no_element_id_the_two_ptc_sources_disagree_on(self):
        used = {n for n in DECLARED if n.startswith("PRO_E_")}
        self.assertEqual(used & disagreements(), set())
        for name in used:
            with self.subTest(name=name):
                self.assertEqual(DECLARED[name], JAVA_IDS.get(name), "wfcElemIds says otherwise")

    def test_modeling_code_names_every_element_it_builds(self):
        # add(elements, <id>, ...) is the only place a tree element is created; its id
        # must be a Ptc constant, never a literal. PTC's own examples write bare
        # integers, and a bare integer is exactly what goes wrong without a sound.
        calls = re.findall(r"add\(elements,\s*([^,]+),", MODELING_JAVA)
        self.assertTrue(calls)
        for first in calls:
            with self.subTest(argument=first):
                self.assertTrue(first.strip().startswith("Ptc.PRO_E_"), first)
        self.assertNotRegex(
            MODELING_JAVA, r"Element_Create\(\s*-?\d", "an element created from a literal id"
        )


class ExtrudeShape(unittest.TestCase):
    """The shape the extrusion code builds, checked against ProExtrude.h's diagram."""

    def test_depth_nests_as_the_code_builds_it(self):
        found = paths(tree_nodes("ProExtrude"))
        self.assertIn(
            (
                "PRO_E_FEATURE_TREE",
                "PRO_E_STD_EXT_DEPTH",
                "PRO_E_EXT_DEPTH_TO",
                "PRO_E_EXT_DEPTH_TO_VALUE",
            ),
            found,
        )
        self.assertIn(
            (
                "PRO_E_FEATURE_TREE",
                "PRO_E_STD_EXT_DEPTH",
                "PRO_E_EXT_DEPTH_TO",
                "PRO_E_EXT_DEPTH_TO_TYPE",
            ),
            found,
        )

    def test_body_elements_are_part_of_the_tree(self):
        # Creo 7+ requires them for a solid; PTC's own extrusion examples predate them.
        found = paths(tree_nodes("ProExtrude"))
        self.assertIn(("PRO_E_FEATURE_TREE", "PRO_E_BODY", "PRO_E_BODY_USE"), found)
        self.assertIn(("PRO_E_FEATURE_TREE", "PRO_E_BODY", "PRO_E_BODY_SELECT"), found)

    def test_the_section_setup_nests_as_the_code_builds_it(self):
        found = paths(tree_nodes("ProStdSection", root="PRO_E_STD_SECTION"))
        for leaf in (
            "PRO_E_STD_SEC_PLANE",
            "PRO_E_STD_SEC_PLANE_VIEW_DIR",
            "PRO_E_STD_SEC_PLANE_ORIENT_DIR",
            "PRO_E_STD_SEC_PLANE_ORIENT_REF",
        ):
            self.assertIn(("PRO_E_STD_SECTION", "PRO_E_STD_SEC_SETUP_PLANE", leaf), found)
        self.assertIn(("PRO_E_STD_SECTION", "PRO_E_SKETCHER"), found)

    def test_value_types_match_how_the_code_sets_them(self):
        types = {n["name"]: n.get("value_type") for n in tree_nodes("ProExtrude")}
        self.assertEqual(types["PRO_E_EXT_DEPTH_TO_VALUE"], "PRO_VALUE_TYPE_DOUBLE")
        self.assertEqual(types["PRO_E_EXT_DEPTH_TO_TYPE"], "PRO_VALUE_TYPE_INT")
        self.assertEqual(types["PRO_E_STD_FEATURE_NAME"], "PRO_VALUE_TYPE_WSTRING")
        self.assertEqual(types["PRO_E_BODY_SELECT"], "PRO_VALUE_TYPE_SELECTION")

    def test_the_depth_enum_is_bit_flags_not_ordinals(self):
        # (1 << 18) and friends: a value table read by eye is easy to transcribe as 18.
        values = TREES["enums"]["ProExtDepthToType"]["values"]
        self.assertEqual(values["PRO_EXT_DEPTH_TO_BLIND"], 1 << 18)
        self.assertEqual(values["PRO_EXT_DEPTH_SYMMETRIC"], 1 << 28)


if __name__ == "__main__":
    unittest.main()
