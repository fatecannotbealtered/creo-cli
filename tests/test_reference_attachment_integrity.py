"""Native auto-sense contract, independently arranged at the public CLI boundary."""

from unittest.mock import patch

from tests.test_capabilities import DrawnBlock


class ReferenceAttachmentIntegrity(DrawnBlock):
    def words(self, explicit=False):
        a, b = (e["ref"] for e in self.edges([1, 0, 0])[:2])
        args = [
            "drawing",
            "dimension",
            "add",
            "--model",
            "block.drw",
            "--view",
            self.shown()["views"][0]["name"],
            "--from",
            a,
            "--to",
            b,
            "--x",
            170,
            "--y",
            232,
        ]
        if explicit:
            args += ["--from-sense", "auto", "--to-sense", "auto"]
        return args

    def native_contract(self, fault=None):
        original = self.world.op

        def reply(op, request):
            result = original(op, request)
            if op == "drawing.add-dimension":
                row = self.world.models["block.drw"]["own_dims"][-1]
                # Arrange the observed native reader contract, not the CLI's expected value.
                for item in row["attachments"]:
                    if item["sense"] == "none":
                        item["sense"] = "auto"
                if fault == "ref":
                    row["attachments"][0]["ref"] = "edge:99999"
                elif fault == "model":
                    row["attachments"][0]["model"] = "unrelated.prt"
                elif fault == "sense":
                    row["attachments"][0]["sense"] = "midpoint"
                elif fault == "incomplete":
                    row["attachments"].pop()
                elif fault == "unassociated":
                    row["associative"] = False
            return result

        return patch.object(self.world, "op", side_effect=reply)

    def success(self, explicit):
        with self.native_contract():
            result = self.gated(*self.words(explicit))["data"]
        self.checks_pass(result)
        checks = {c["check"]: c for c in result["verification"]["checks"]}
        self.assertTrue(checks["associative_geometry_attachments"]["passed"])
        self.assertEqual(self.world.ops().count("drawing.add-dimension"), 1)

    def refused_result(self, fault, explicit=False):
        with self.native_contract(fault):
            error = self.gated(*self.words(explicit), status=1)["error"]
        self.assertEqual(error["code"], "E_VERIFY_FAILED")
        self.assertEqual(self.world.ops().count("drawing.add-dimension"), 1)
        self.assertEqual(len(self.world.models["block.drw"]["own_dims"]), 1)
        self.cli("model", "save", "--model", "block.drw", "--dry-run", status=6)

    def test_explicit_auto_matches_native_auto_not_fictional_none(self):
        self.success(True)

    def test_default_auto_still_requires_independent_attachments(self):
        self.success(False)

    def test_explicit_point_senses_are_preserved(self):
        words = self.words(True)
        words[-3], words[-1] = "end1", "end2"
        with self.native_contract():
            out = self.gated(*words)["data"]
        self.checks_pass(out)
        self.assertEqual(
            [a["sense"] for a in out["result"]["dimension"]["attachments"]], ["end1", "end2"]
        )

    def test_default_wrong_reference_is_not_accepted(self):
        self.refused_result("ref")

    def test_default_wrong_model_is_not_accepted(self):
        self.refused_result("model")

    def test_default_wrong_sense_is_not_accepted(self):
        self.refused_result("sense")

    def test_incomplete_attachments_are_not_accepted(self):
        self.refused_result("incomplete", True)

    def test_unassociated_dimension_is_not_accepted(self):
        self.refused_result("unassociated", True)

    def test_workflow_leaf_uses_the_same_auto_attachment_check(self):
        words = self.words(True)
        args = {words[i][2:]: words[i + 1] for i in range(3, len(words), 2)}
        args.update(x=170, y=232)
        request = self.request(
            {"steps": [{"id": "reference", "command": "drawing dimension add", "args": args}]}
        )
        with self.native_contract():
            out = self.gated("workflow", "run", "--request", request)["data"]
        self.assertEqual(out["workflow"]["summary"]["completed"], 1)
        self.assertEqual(self.world.ops().count("drawing.add-dimension"), 1)
