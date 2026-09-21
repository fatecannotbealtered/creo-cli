"""Hold the OTK Java index to the library it was derived from.

Creating geometry means naming element ids and feature types exactly. There are
5433 of the former, no live Creo to catch a typo against, and a wrong id fails at
feature-commit time with a diagnostic that does not name the mistake. So the index
is checked here the same way the CREOSON one is: shape, provenance, and the specific
constants the modelling commands will be built on.

The index is derived from a jar on the build machine, so these tests never read the
installation -- they read contract/otk-interface.json, which is committed.
"""
from __future__ import annotations

import io
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX_PATH = ROOT / "contract" / "otk-interface.json"
INDEX = json.load(io.open(INDEX_PATH, encoding="utf-8")) if INDEX_PATH.is_file() else None

# The vocabulary the first modelling commands depend on. Values are the library's,
# recorded here so a Creo upgrade that renumbers them fails loudly instead of
# silently building the wrong feature.
FEATURE_TYPES = {"FEATTYPE_HOLE": 1, "FEATTYPE_ROUND": 3, "FEATTYPE_CHAMFER": 4,
                 "FEATTYPE_CUT": 6, "FEATTYPE_PROTRUSION": 7, "FEATTYPE_RIB": 10,
                 "FEATTYPE_DATUM_PLANE": 13, "FEATTYPE_DATUM_AXIS": 16,
                 "FEATTYPE_SHELL": 18, "FEATTYPE_CURVE": 39, "FEATTYPE_COORD_SYS": 68}
ELEMENT_IDS = {"PRO_E_EXT_DEPTH": 3, "PRO_E_FEATURE_TYPE": 387, "PRO_E_FEATURE_FORM": 388,
               "PRO_E_STD_SECTION": 447, "PRO_E_SKETCHER": 458, "PRO_E_STD_MATRLSIDE": 499,
               "PRO_E_STD_FEATURE_NAME": 1964, "PRO_E_REMOVE_MATERIAL": 2023}


@unittest.skipIf(INDEX is None, "contract/otk-interface.json has not been generated")
class ObjectToolkitIndex(unittest.TestCase):
    def test_provenance_identifies_exactly_one_library(self):
        self.assertEqual(INDEX["library"], "Creo Object TOOLKIT Java")
        self.assertEqual(len(INDEX["jar_sha256"]), 64)
        self.assertGreater(INDEX["jar_size_bytes"], 0)

    def test_the_licensed_extension_is_present_and_is_the_larger_half(self):
        # wfc is the namespace J-Link does not ship; it carries the element-tree API
        # that makes feature creation possible. If a future jar lost it, every
        # modelling command would be built on sand, so assert the shape directly.
        counts = INDEX["namespace_class_counts"]
        self.assertIn("wfc", counts)
        self.assertIn("pfc", counts)
        self.assertGreater(counts["wfc"], counts["pfc"],
                           "wfc should dominate; a pfc-only jar is J-Link, which cannot create features")

    def test_feature_types_resolve_to_their_recorded_values(self):
        values = INDEX["feature_types"]["values"]
        for name, expected in FEATURE_TYPES.items():
            with self.subTest(feature_type=name):
                self.assertIn(name, values, "modelling depends on this feature type")
                self.assertEqual(values[name], expected)

    def test_element_ids_resolve_to_their_recorded_values(self):
        values = INDEX["element_ids"]["values"]
        for name, expected in ELEMENT_IDS.items():
            with self.subTest(element=name):
                self.assertIn(name, values)
                self.assertEqual(values[name], expected)

    def test_constant_names_carry_no_typesafe_enum_underscore(self):
        # PTC declares each enum value twice, `int _FEATTYPE_HOLE` beside the typed
        # `FeatureType FEATTYPE_HOLE`. The index records the logical name, so a lookup
        # never has to know that convention.
        for section in ("element_ids", "feature_types"):
            leading = [n for n in INDEX[section]["values"] if n.startswith("_")]
            with self.subTest(section=section):
                self.assertFalse(leading, f"unnormalized names leaked in: {leading[:5]}")

    def test_the_creation_path_classes_expose_what_building_a_tree_needs(self):
        api = INDEX["creation_api"]
        element = " ".join(api["com.ptc.wfc.wfcElementTree.Element"])
        for method in ("SetId", "SetValue", "SetLevel"):
            with self.subTest(method=method):
                self.assertIn(method, element, "an element tree is built from id/value/level")
        tree = " ".join(api["com.ptc.wfc.wfcElementTree.ElementTree"])
        self.assertIn("ListTreeElements", tree)

    def test_counts_match_the_recorded_values(self):
        for section in ("element_ids", "feature_types"):
            with self.subTest(section=section):
                self.assertEqual(INDEX[section]["count"], len(INDEX[section]["values"]))


if __name__ == "__main__":
    unittest.main()
