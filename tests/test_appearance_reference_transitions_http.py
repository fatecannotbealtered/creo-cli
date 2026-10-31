"""Public CLI transition regressions over the real repository loopback HTTP fixture.

These controlled responses are not native Creo evidence. Every test uses Base's
isolated temporary workspace/history and loopback server, never a live CAD URL.
"""

import copy
import json
from pathlib import Path
from unittest.mock import patch

from tests import test_native_display_cli as display_http
from tests.fixture_presentation import appearance_properties
from tests.physical_observation_fixture import ASSIGNED, DENSITY, physical, reading
from tests.test_features import Built
from tests.test_round7_closeout import invoke


class FirstNullReferenceHTTP(Built):
    repeated_source = display_http.NativePresentationHTTP.repeated_source
    color_request = display_http.NativePresentationHTTP.color_request

    def setUp(self):
        super().setUp()
        material_list = self.world.material_list

        def complete_physical_material_list(request):
            value = material_list(request)
            if request.get("model"):
                name, model = self.world.model(request["model"])
                summary = self.world.summary(name, model)
                proof = physical(summary)
                proof["body_materials"]["value"][0]["id"] = str(summary["bodies"][0]["id"])
                # Match the native known-unset contract without inferring density
                # from the fixture's geometry fallback or filling a material value.
                proof["density"] = reading(DENSITY, None, "unknown")
                proof["assigned_density"] = reading(ASSIGNED, None, "unset")
                value["model"]["physical_observation"] = proof
            return value

        typed = patch.object(
            self.world, "material_list", side_effect=complete_physical_material_list
        )
        typed.start()
        self.addCleanup(typed.stop)

    def capture(self, label, value):
        if not hasattr(self, "transition_evidence"):
            self.transition_evidence = {}
        self.transition_evidence[label] = copy.deepcopy(value)

    def first_null_args(self):
        source, owner = self.repeated_source()
        constraints = copy.deepcopy(owner["components"])
        request = self.color_request([0.05, 0.15, 0.95])
        return (
            source,
            constraints,
            ("appearance", "set", "--model", "block.prt", "--request", request),
        )

    def test_first_null_preview_and_result_bind_actual_initial_creation(self):
        source, constraints, args = self.first_null_args()
        preview = self.cli(*args, "--dry-run")["data"]
        domain = preview["preview"]["extensions"]["creo"]
        self.capture("preview_domain", domain)
        completed = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        self.capture("completed", completed)
        result = completed["result"]
        reference = completed["receipt"]["extensions"]["creo"]["appearance_reference"]
        self.assertEqual(domain["reference_transition"], "create_initial_binding")
        self.assertEqual(domain["intent"]["reference_transition"], "create_initial_binding")
        self.assertEqual(
            domain["reference_after"]["allocation_status"], "pending_native_allocation"
        )
        self.assertIsNone(domain["reference_before"]["native_id"])
        self.assertIsNone(domain["reference_after"]["native_id"])
        self.assertEqual(len(domain["affected_occurrences"]), 2)
        self.assertEqual(result["reference_transition"], "create_initial_binding")
        self.assertEqual(result["reference_action"], "preserve")
        self.assertIsNone(result["reference_before"]["native_id"])
        self.assertTrue(result["reference_after"]["native_id"].strip())
        self.assertTrue(result["reference_after"]["whole_source_binding_observed"])
        self.assertEqual(reference["action"], "create_initial_binding")
        self.assertEqual(reference["requested_reference_action"], "preserve")
        self.assertEqual(reference["reference_transition"], result["reference_transition"])
        self.assertEqual(reference["after"], result["reference_after"])
        self.assertEqual(reference["affected_occurrences"], domain["affected_occurrences"])
        self.assertEqual(source["cosmetic_appearance"]["rgb"], [0.05, 0.15, 0.95])
        self.assertEqual(self.world.models["holdout.asm"]["components"], constraints)
        self.assertNotIn("model.save", self.world.ops())
        self.assertEqual(self.world.ops().count("appearance.set"), 1)

    def assert_invalid_created_binding_fails(self, drift):
        _, constraints, args = self.first_null_args()
        getter = self.world.appearance_get

        def corrupted_after(q):
            observed = getter(q)
            if observed["model"] == "block.prt" and observed["appearance"] is not None:
                if drift == "missing_assignment":
                    observed["assignments"] = []
                elif drift == "null_native_id":
                    observed["appearance"]["name"] = None
                    observed["assignments"][0]["appearance"]["name"] = None
                elif drift == "wrong_selection":
                    observed["selection_model"] = "other.prt"
                    observed["assignments"][0]["selection_model"] = "other.prt"
                else:
                    raise AssertionError("Unknown controlled observation drift")
            return observed

        with patch.object(self.world, "appearance_get", side_effect=corrupted_after):
            preview = self.cli(*args, "--dry-run")["data"]
            self.capture("preview_domain", preview["preview"]["extensions"]["creo"])
            code, response = invoke(self, *args, "--confirm", preview["confirm_token"])
        self.capture("confirm_exit_code", code)
        self.capture("confirm_response", response)
        self.assertNotEqual(code, 0, response)
        self.assertFalse(response["ok"])
        self.assertEqual(response["error"]["code"], "E_VERIFY_FAILED")
        receipt = response["error"]["details"]["receipt"]
        self.assertEqual(receipt["outcome"]["verification"]["status"], "failed")
        reference = receipt["extensions"]["creo"]["appearance_reference"]
        self.assertFalse(reference["after"]["whole_source_binding_observed"])
        self.assertEqual(reference["after"]["appearance"]["rgb"], [0.05, 0.15, 0.95])
        self.assertTrue(
            receipt["extensions"]["creo"]["appearance_persistence"]["model_modified"]["block.prt"]
        )
        self.assertIn(receipt["outcome"]["persistence"], ("unsaved", "unknown"))
        self.assertEqual(self.world.models["holdout.asm"]["components"], constraints)
        self.assertEqual(self.world.ops().count("appearance.set"), 1)
        self.assertNotIn("model.save", self.world.ops())
        self.assertFalse(response["error"]["details"]["automatic_retry"])
        self.assertFalse(response["error"]["details"]["rollback_performed"])

    def test_rgb_success_with_no_assignment_is_not_success(self):
        self.assert_invalid_created_binding_fails("missing_assignment")

    def test_rgb_success_with_null_native_id_is_not_success(self):
        self.assert_invalid_created_binding_fails("null_native_id")

    def test_rgb_success_with_wrong_source_selection_is_not_success(self):
        self.assert_invalid_created_binding_fails("wrong_selection")

    def test_restore_null_declares_default_and_persists_no_model_override(self):
        self.repeated_source()
        initial = self.color_request([0.05, 0.15, 0.95])
        self.gated("appearance", "set", "--model", "block.prt", "--request", initial)
        source = self.world.models["block.prt"]
        old = copy.deepcopy(source["cosmetic_appearance"])
        other = self.part("other.prt")
        other["cosmetic_appearance"] = copy.deepcopy(old)
        request = self.color_request(None, restore=True)
        args = ("appearance", "restore", "--model", "block.prt", "--request", request)
        preview = self.cli(*args, "--dry-run")["data"]
        domain = preview["preview"]["extensions"]["creo"]
        self.capture("preview_domain", domain)
        completed = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        self.capture("completed", completed)
        self.assertEqual(domain["reference_transition"], "restore_native_default")
        self.assertIsNone(domain["reference_after"]["native_id"])
        result = completed["result"]
        reference = completed["receipt"]["extensions"]["creo"]["appearance_reference"]
        self.assertEqual(result["reference_transition"], "restore_native_default")
        self.assertEqual(reference["action"], "restore_native_default")
        self.assertEqual(reference["requested_reference_action"], "preserve")
        self.assertEqual(reference["reference_transition"], "restore_native_default")
        self.assertEqual(reference["before"]["native_id"], old["name"])
        self.assertIsNone(reference["after"]["appearance"])
        self.assertEqual(reference["after"]["assignments"], [])
        self.assertEqual(reference["after"]["selection_model"], "block.prt")
        self.assertEqual(reference["after"]["source_context"]["model"], "block.prt")
        self.assertEqual(other["cosmetic_appearance"], old)
        saved = self.gated("model", "save", "--model", "block.prt")["data"]["result"]["file"]
        self.gated("model", "close", "--model", "block.prt")
        self.gated("model", "open", "--path", saved)
        reopened = self.cli("appearance", "show", "--model", "block.prt")["data"]
        self.assertIsNone(reopened["appearance"])
        self.assertEqual(reopened["assignments"], [])
        self.assertFalse(reopened["modified"])
        self.capture("explicit_save_exact_reopened", reopened)

    def test_initial_recorded_restore_requests_native_allocation_not_the_historical_id(self):
        source, owner = self.repeated_source()
        record = appearance_properties([0.25, 0.75, 0.5]) | {"name": "historical_unbound_reference"}
        other = self.part("other.prt")
        other["cosmetic_appearance"] = copy.deepcopy(record)
        other_before = copy.deepcopy(other)
        constraints_before = copy.deepcopy(owner["components"])
        request = self.color_request(record, restore=True)
        args = ("appearance", "restore", "--model", "block.prt", "--request", request)
        setter = self.world.appearance_set
        sent = []

        def native_allocation_substitute(q):
            # Controlled native allocator substitute, never a claim about Creo.
            sent.append(copy.deepcopy(q))
            result = setter(q)
            self.assertEqual(q["action"], "restore")
            self.assertIsNone(q["expected_before"]["appearance"])
            self.assertEqual(q["appearance"]["name"], "")
            source["cosmetic_appearance"]["name"] = "fixture_allocated_initial_restore_8"
            return result

        with patch.object(self.world, "appearance_set", side_effect=native_allocation_substitute):
            preview = self.cli(*args, "--dry-run")["data"]
            domain = preview["preview"]["extensions"]["creo"]
            self.capture("preview_domain", domain)
            self.assertEqual(domain["reference_transition"], "create_initial_binding")
            self.assertEqual(domain["intent"]["appearance"], record)
            self.assertEqual(
                preview["preview"]["changes"][0]["after"]["reference_transition"],
                "create_initial_binding",
            )
            completed = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        self.capture("completed", completed)
        self.capture("actual_wire_request", sent)
        self.assertEqual(len(sent), 1)
        self.assertNotIn("reference_transition", sent[0])
        self.assertEqual(sent[0]["reference_action"], "preserve")
        self.assertEqual(
            json.loads(Path(request).read_text(encoding="utf-8"))["appearance"], record
        )
        result = completed["result"]
        self.assertEqual(result["reference_transition"], "create_initial_binding")
        self.assertIsNone(result["reference_before"]["native_id"])
        self.assertEqual(
            result["reference_after"]["native_id"], "fixture_allocated_initial_restore_8"
        )
        self.assertTrue(result["reference_after"]["whole_source_binding_observed"])
        self.assertEqual(
            {key: value for key, value in result["appearance"].items() if key != "name"},
            {key: value for key, value in record.items() if key != "name"},
        )
        reference = completed["receipt"]["extensions"]["creo"]["appearance_reference"]
        self.assertEqual(reference["action"], "create_initial_binding")
        self.assertEqual(reference["requested_reference_action"], "preserve")
        self.assertEqual(reference["after"], result["reference_after"])
        self.assertEqual(other, other_before)
        self.assertEqual(owner["components"], constraints_before)
        self.assertNotIn("model.save", self.world.ops())

    def test_public_reference_describes_effective_transition_and_unchanged_requests(self):
        for action in ("set", "restore"):
            response = self.cli("reference", "--command", "appearance " + action)["data"]
            self.capture("reference_" + action, response)
            command = response["command"]
            schema = response["schemas"][command["output_schema"]]["json_schema"]
            result = schema["properties"]["result"]
            properties = result["properties"]
            self.assertEqual(
                set(properties["reference_transition"]["enum"]),
                {"create_initial_binding", "create_and_bind", "preserve", "restore_native_default"},
            )
            self.assertEqual(
                set(properties["requested_reference_action"]["enum"]),
                {"preserve", "create_and_bind"},
            )
            for field in (
                "reference_transition",
                "requested_reference_action",
                "reference_before",
                "reference_after",
            ):
                self.assertIn(field, result["required"])
            for field in ("reference_before", "reference_after"):
                binding = properties[field]
                self.assertEqual(binding["type"], "object")
                self.assertEqual(
                    set(binding["properties"]["native_id"]["type"]), {"string", "null"}
                )
                self.assertEqual(binding["properties"]["source_context"]["type"], "object")
                self.assertEqual(binding["properties"]["assignments"]["type"], "array")
                self.assertEqual(
                    binding["properties"]["whole_source_binding_observed"]["type"], "boolean"
                )
            request = command["request_schema"]
            expected = {
                "scope",
                "source_file_authorized",
                "affected_occurrences",
                "rgb" if action == "set" else "appearance",
            }
            self.assertEqual(set(request["required"]), expected)
            self.assertNotIn("reference_transition", request["properties"])
        query = self.cli("reference", "--command", "appearance show")["data"]
        self.capture("reference_show", query)
        schema = query["schemas"][query["command"]["output_schema"]]["json_schema"]
        self.assertNotIn("reference_transition", schema["required"])
        self.assertNotIn("requested_reference_action", schema["required"])
        self.assertNotIn("reference_before", schema["properties"])
        self.assertNotIn("reference_after", schema["properties"])
        self.assertEqual(self.world.ops(), [])

    def test_non_null_preserve_replacement_and_recorded_restore_keep_wire_compatibility(self):
        source, constraints, initial_args = self.first_null_args()
        initial = self.gated(*initial_args)["data"]
        recorded_blue = copy.deepcopy(source["cosmetic_appearance"])
        old_id = recorded_blue["name"]
        other = self.part("other.prt")
        other["cosmetic_appearance"] = source["cosmetic_appearance"]
        old_other = copy.deepcopy(other)

        same = self.color_request(recorded_blue["rgb"])
        preserved = self.gated("appearance", "set", "--model", "block.prt", "--request", same)[
            "data"
        ]
        preserve_ref = preserved["receipt"]["extensions"]["creo"]["appearance_reference"]
        self.assertEqual(preserve_ref["action"], "preserve")
        self.assertEqual(preserve_ref["requested_reference_action"], "preserve")
        self.assertEqual(preserve_ref["reference_transition"], "preserve")
        self.assertEqual(preserve_ref["after"]["native_id"], old_id)

        changed_rgb = [0.875, 0.125, 0.5]
        unauthorized = self.color_request(changed_rgb)
        setters = self.world.ops().count("appearance.set")
        code, refused = invoke(
            self,
            "appearance",
            "set",
            "--model",
            "block.prt",
            "--request",
            unauthorized,
            "--dry-run",
        )
        self.assertNotEqual(code, 0)
        self.assertEqual(refused["error"]["code"], "E_UNSUPPORTED")
        self.assertEqual(refused["error"]["details"]["dispatch_state"], "not_started")
        self.assertEqual(self.world.ops().count("appearance.set"), setters)

        replacement = display_http.NativePresentationHTTP.replacement_request(self, changed_rgb)
        replaced = self.gated(
            "appearance", "set", "--model", "block.prt", "--request", replacement
        )["data"]
        replaced_id = replaced["result"]["reference_after"]["native_id"]
        self.assertNotEqual(replaced_id, old_id)
        self.assertTrue(replaced["result"]["reference_after"]["whole_source_binding_observed"])
        restore = self.request(
            {
                "scope": "source_part",
                "source_file_authorized": True,
                "affected_occurrences": initial["result"]["affected_occurrences"],
                "reference_action": "create_and_bind",
                "reference_replacement_authorized": True,
                "appearance": recorded_blue,
            },
            "recorded-nonnull-restore.json",
        )
        restored = self.gated(
            "appearance", "restore", "--model", "block.prt", "--request", restore
        )["data"]
        for completed, before_id in ((replaced, old_id), (restored, replaced_id)):
            result = completed["result"]
            reference = completed["receipt"]["extensions"]["creo"]["appearance_reference"]
            self.assertEqual(result["reference_action"], "create_and_bind")
            self.assertEqual(result["reference_transition"], "create_and_bind")
            self.assertEqual(reference["action"], "create_and_bind")
            self.assertEqual(reference["requested_reference_action"], "create_and_bind")
            self.assertEqual(reference["reference_transition"], "create_and_bind")
            self.assertEqual(reference["before"]["native_id"], before_id)
            self.assertTrue(reference["after"]["native_id"].strip())
            self.assertNotEqual(reference["after"]["native_id"], before_id)
            self.assertTrue(reference["after"]["whole_source_binding_observed"])
            self.assertEqual(reference["after"], result["reference_after"])
        self.assertEqual(
            restored["result"]["reference_after"]["appearance"]["rgb"], recorded_blue["rgb"]
        )
        self.assertNotEqual(
            restored["result"]["reference_after"]["native_id"], recorded_blue["name"]
        )
        self.assertEqual(other, old_other)
        self.assertEqual(self.world.models["holdout.asm"]["components"], constraints)
        self.assertNotIn("model.save", self.world.ops())
        self.capture(
            "compatibility",
            {
                "initial": initial,
                "preserved": preserved,
                "unauthorized": refused,
                "replacement": replaced,
                "restored": restored,
                "other_unchanged": True,
                "constraints_unchanged": True,
            },
        )
