"""workflow run: several writes, one preview, one confirmation, one receipt per step."""

from __future__ import annotations

from tests.test_commands import RECT, Base, domain_preview


def steps(*items):
    return {"steps": [{"command": c, "args": a} for c, a in items]}


class Workflow(Base):
    def test_edits_an_existing_part_in_one_confirmation(self):
        self.part()
        self.gated("feature", "extrude", "--model", "block", "--request", self.request(RECT))
        dims = self.cli("dimension", "list", "--model", "block")["data"]["items"]
        width = next(d["id"] for d in dims if d["value"] == 40)
        body = steps(
            (
                "parameter set",
                {"model": "block", "name": "DESCRIPTION", "type": "string", "value": "block"},
            ),
            ("dimension set", {"model": "block", "dimension": width, "value": 48, "units": "mm"}),
            ("model regenerate", {"model": "block"}),
            ("model save", {"model": "block"}),
        )
        args = ("workflow", "run", "--request", self.request(body))
        preview = self.cli(*args, "--dry-run")["data"]
        self.assertEqual(
            domain_preview(preview["preview"])["first_step"]["command"], "parameter set"
        )
        result = self.cli(*args, "--confirm", preview["confirm_token"])["data"]
        self.assertEqual(result["workflow"]["summary"]["completed"], 4)
        self.assertEqual(result["receipt"]["outcome"]["persistence"], "saved")
        self.assertEqual(
            self.cli("geometry", "mass-properties", "--model", "block")["data"]["data"]["volume"],
            9600,
        )

    def test_later_known_type_conflict_is_found_before_first_write(self):
        self.part()
        body = steps(
            (
                "parameter set",
                {"model": "block", "name": "DESCRIPTION", "type": "string", "value": "changed"},
            ),
            (
                "parameter set",
                {"model": "block", "name": "DESCRIPTION", "type": "integer", "value": "1"},
            ),
        )
        self.cli("workflow", "run", "--request", self.request(body), "--dry-run", status=6)
        self.assertFalse(any(op == "parameter.set" for op, _ in self.world.events))

    def test_steps_are_checked_before_anything_runs(self):
        for body, code, status in (
            (steps(("feature delete", {"model": "block", "feature": "X"})), "E_VALIDATION", 2),
            (steps(("workflow run", {"request": {}})), "E_VALIDATION", 2),
            (steps(("model list", {})), "E_VALIDATION", 2),
            (steps(("model save", {"model": "block", "nope": 1})), "E_VALIDATION", 2),
            (steps(("model save", {})), "E_VALIDATION", 2),
            (
                steps(
                    (
                        "dimension set",
                        {"model": "block", "dimension": "d1", "value": "x", "units": "mm"},
                    )
                ),
                "E_VALIDATION",
                2,
            ),
            (steps(("part create", {"name": "a", "units": "furlongs"})), "E_VALIDATION", 2),
            ({"steps": []}, "E_VALIDATION", 2),
        ):
            with self.subTest(body=body):
                self.assertEqual(
                    self.cli(
                        "workflow",
                        "run",
                        "--request",
                        self.request(body),
                        "--dry-run",
                        status=status,
                    )["error"]["code"],
                    code,
                )
        self.assertEqual(self.world.models, {})

    def test_a_changed_first_target_invalidates_the_token(self):
        self.world.part("block.prt")
        self.world.write_version(self.ws, "block.prt", self.world.models["block.prt"])
        body = steps(("model regenerate", {"model": "block"}))
        dry = self.cli("workflow", "run", "--request", self.request(body), "--dry-run")["data"]
        self.world.models["block.prt"]["modified"] = True
        self.assertEqual(
            self.cli(
                "workflow",
                "run",
                "--request",
                self.request(body),
                "--confirm",
                dry["confirm_token"],
                status=6,
            )["error"]["code"],
            "E_CONFLICT",
        )

    def test_object_creation_and_open_close_are_explicitly_unsupported(self):
        for body in (
            steps(("part create", {"name": "block", "units": "mmns"})),
            steps(("model open", {"path": "block.prt.1"})),
        ):
            with self.subTest(body=body):
                error = self.cli(
                    "workflow", "run", "--request", self.request(body), "--dry-run", status=2
                )["error"]
                self.assertEqual(error["code"], "E_UNSUPPORTED")
        self.assertEqual(self.world.models, {})
