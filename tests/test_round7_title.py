"""Title input provenance, bounded page scope and current component capability gates."""

import copy
import json

from tests.test_capabilities import DrawnBlock


class TitleBoundary(DrawnBlock):
    def args(self, file):
        return ("drawing", "title-block", "apply", "--model", "block.drw", "--request", file)

    def test_request_content_replacement_and_deletion_refuse_before_native(self):
        path = self.request(
            {"title": "REFERENCE SAMPLE", "material": "", "drawn_by": "", "checked_by": ""},
            "title.json",
        )
        before = copy.deepcopy(self.world.models["block.drw"])
        for mode in ("content", "replace", "delete"):
            with self.subTest(mode=mode):
                path.write_text(json.dumps({"title": "REFERENCE SAMPLE"}), encoding="utf-8")
                pre = self.cli(*self.args(path), "--dry-run")["data"]
                if mode == "content":
                    path.write_text(json.dumps({"title": "EXTERNAL TITLE"}), encoding="utf-8")
                elif mode == "replace":
                    tmp = path.with_suffix(".new")
                    tmp.write_bytes(path.read_bytes())
                    tmp.replace(path)
                else:
                    path.unlink()
                error = self.cli(
                    *self.args(path),
                    "--confirm",
                    pre["confirm_token"],
                    status=3 if mode == "delete" else 6,
                )["error"]
                self.assertEqual(error["code"], "E_NOT_FOUND" if mode == "delete" else "E_CONFLICT")
                self.assertEqual(self.world.models["block.drw"], before)
        self.assertNotIn("drawing.add-table", self.world.ops())

    def test_blank_metadata_full_bounds_and_no_duplicate_confirmation(self):
        path = self.request(
            {"title": "REFERENCE SAMPLE", "material": "", "drawn_by": "", "checked_by": ""},
            "title.json",
        )
        args = self.args(path)
        pre = self.cli(*args, "--dry-run")["data"]
        out = self.cli(*args, "--confirm", pre["confirm_token"])["data"]
        self.assertEqual(out["receipt"]["outcome"]["change"], "applied")
        table = self.world.models["block.drw"]["tables"][-1]
        self.assertEqual(table["outline"], [[235, 5], [415, 37]])
        for row, col in ((1, 1), (3, 1), (3, 3)):
            self.assertFalse(table["cells"][row][col])
        self.assertEqual(table["cells"][2][0], "Number")
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertEqual(self.world.ops().count("drawing.add-table"), 1)

    def test_old_component_and_scope_change_are_not_native_writes(self):
        path = self.request({"title": "REFERENCE SAMPLE"}, "title.json")
        args = self.args(path)
        self.world.capabilities.pop("title_projection_arcs")
        self.cli(*args, "--dry-run", status=4)
        self.world.capabilities["title_projection_arcs"] = 2
        pre = self.cli(*args, "--dry-run")["data"]
        scope = self.root / "scope.json"
        grant = json.loads(scope.read_text(encoding="utf-8"))
        grant["effects"].remove("change")
        scope.write_text(json.dumps(grant), encoding="utf-8")
        self.cli(*args, "--confirm", pre["confirm_token"], status=6)
        self.assertNotIn("drawing.add-table", self.world.ops())
