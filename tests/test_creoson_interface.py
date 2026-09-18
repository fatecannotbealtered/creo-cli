"""Check the operation catalog against CREOSON's own published interface.

contract/creoson-interface.json is derived from the jsonSpecs shipped in the
CREOSON 3.0.2 release (see scripts/gen_creoson_interface.py). The catalog narrows
that surface on purpose, but it must never invent a field name, drop a required
one, or promise a response key the upstream function does not return.

Every deviation below is listed explicitly with the reason. That is the point: a
new operation cannot quietly disagree with the published contract, and a real
deviation has to be argued for in this file rather than discovered on live Creo.
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from creo_cli.creoson_catalog import BY_PATH  # noqa: E402

INDEX = json.load(io.open(ROOT / "contract" / "creoson-interface.json", encoding="utf-8"))
FUNCTIONS = INDEX["functions"]

# Request fields the engine consumes locally instead of forwarding. Each entry names
# where the transformation happens so the exemption can be re-checked.
LOCAL_TRANSFORMS = {
    ("export image", "dirname"): "joined into filename by creoson_engine.wire; "
                                 "interface.export_image publishes no dirname",
}

# Response keys creo-cli synthesizes rather than reading straight from one upstream
# reply -- composed reads and added context, not claims about the published payload.
SYNTHESIZED_RESPONSE = {
    ("file massprops", "unit_context"): "unit context attached by the massprops verifier",
    ("file units", "length_units"): "units verifier calls file.get_length_units and renames units",
    ("file units", "mass_units"): "units verifier also calls file.get_mass_units",
    ("file roundtrip", "roundtrip_verified"): "composed save/close_window/erase/open comparison",
    ("file roundtrip", "artifacts"): "composed roundtrip disk inventory",
    ("file roundtrip", "compared_sections"): "composed roundtrip comparison summary",
}


def wire_fields(op) -> set:
    """Field names the operation forwards upstream, per its own wire() contract."""
    return set(op.request_schema["properties"]) - set(op.local_keys) | set(op.defaults)


class PublishedInterface(unittest.TestCase):
    def test_index_matches_the_declared_protocol_target(self):
        self.assertEqual(INDEX["release"], "v3.0.2")
        self.assertEqual(INDEX["function_count"], len(FUNCTIONS))
        self.assertTrue(all(len(e["git_blob_sha"]) == 40 for e in FUNCTIONS.values()))

    def test_recorded_blob_identity_still_holds(self):
        # docs/UPSTREAM_SOURCES.md pins this one; if the derivation ever changes its
        # hashing rule, this catches it before any operation is graded against it.
        self.assertEqual(FUNCTIONS["file.assemble"]["git_blob_sha"],
                         "cbfcdd4510e2fe0640e07790791bb288e028f39e")

    def test_every_operation_targets_a_published_function(self):
        for path, op in sorted(BY_PATH.items()):
            with self.subTest(path=path):
                self.assertIn(f"{op.command}.{op.function}", FUNCTIONS)

    def test_no_operation_invents_a_request_field(self):
        for path, op in sorted(BY_PATH.items()):
            published = {f["name"] for f in FUNCTIONS[f"{op.command}.{op.function}"]["request"]}
            for name in sorted(wire_fields(op) - published):
                with self.subTest(path=path, field=name):
                    self.assertIn((path, name), LOCAL_TRANSFORMS,
                                  f"{path} forwards {name!r}, which {op.command}.{op.function} does not publish")

    def test_every_required_request_field_is_supplied(self):
        for path, op in sorted(BY_PATH.items()):
            entry = FUNCTIONS[f"{op.command}.{op.function}"]
            required = {f["name"] for f in entry["request"] if f.get("required")}
            supplied = wire_fields(op) | {n for (p, n) in LOCAL_TRANSFORMS if p == path}
            with self.subTest(path=path):
                self.assertFalse(required - supplied,
                                 f"{path} never supplies required {sorted(required - supplied)}")

    def test_no_operation_promises_an_unpublished_response_key(self):
        for path, op in sorted(BY_PATH.items()):
            published = {f["name"] for f in FUNCTIONS[f"{op.command}.{op.function}"]["response"]}
            for name in sorted(set(op.response_fields) - published):
                with self.subTest(path=path, field=name):
                    self.assertIn((path, name), SYNTHESIZED_RESPONSE,
                                  f"{path} declares response key {name!r} that "
                                  f"{op.command}.{op.function} does not publish")

    def test_response_field_types_match_the_published_types(self):
        # creoson_schemas.BASE_FIELDS is hand-written, and a wrong entry only shows up
        # as E_INTEGRITY at runtime when a real reply arrives. Hold each declared type
        # against the type CREOSON publishes for that field.
        from creo_cli.creoson_engine import ID_KEYS
        from creo_cli.creoson_schemas import BASE_FIELDS
        allowed = {"string": {"string"}, "boolean": {"boolean"}, "integer": {"integer"},
                   "double": {"number"}, "array:string": {"array"}, "array:integer": {"array"},
                   "object": {"object"}}
        for path, op in sorted(BY_PATH.items()):
            published = {f["name"]: f["type"] for f in FUNCTIONS[f"{op.command}.{op.function}"]["response"]}
            for name in op.response_fields:
                kind = published.get(name)
                if (path, name) in SYNTHESIZED_RESPONSE or name not in BASE_FIELDS or kind is None:
                    continue
                declared = BASE_FIELDS[name].get("type")
                declared = {declared} if isinstance(declared, str) else set(declared or ())
                if name in ID_KEYS:
                    # CLI-SPEC: every ID leaves as a string even when the upstream numbers
                    # it. That conversion is ID_KEYS in creoson_engine, so assert the
                    # rule here instead of exempting the field from the check.
                    with self.subTest(path=path, field=name, rule="ids_are_strings"):
                        self.assertEqual(declared, {"string"},
                                         f"{path} must publish id {name!r} as a string")
                    continue
                expected = allowed.get(kind.split(":")[0] if kind.startswith("object") else kind)
                if expected is None:  # "depends on data type" and nested object payloads
                    continue
                with self.subTest(path=path, field=name, published=kind):
                    self.assertTrue(declared & expected,
                                    f"{path} types {name!r} as {sorted(declared)}, "
                                    f"but {op.command}.{op.function} publishes {kind}")

    def test_exemptions_are_not_stale(self):
        # An exemption that no longer applies is a documentation lie; drop it.
        for (path, name), reason in LOCAL_TRANSFORMS.items():
            with self.subTest(exemption=f"{path}.{name}"):
                self.assertIn(path, BY_PATH, f"exemption names a removed operation: {path}")
                self.assertIn(name, BY_PATH[path].request_schema["properties"], reason)
        for (path, name), reason in SYNTHESIZED_RESPONSE.items():
            with self.subTest(exemption=f"{path}.{name}"):
                self.assertIn(path, BY_PATH, f"exemption names a removed operation: {path}")
                self.assertIn(name, BY_PATH[path].response_fields, reason)


if __name__ == "__main__":
    unittest.main()
