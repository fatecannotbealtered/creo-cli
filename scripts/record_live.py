"""Record creo-cli running against a live Creo, as CLI subprocesses.

The Creo-side service must be running (docs/SERVICE.md), and the write policy must
already be in the environment -- CREO_CLI_WORKSPACE, CREO_CLI_PERMISSION=write and
CREO_CLI_EXPERIMENTAL_NATIVE_WRITES=1, set because a person said so. The script never
sets them. Everything it creates lives in a new directory inside the workspace, and it
takes out of the session every model it put there.

  python scripts/record_live.py --output docs/evidence/live-creo.json

The record is what registry.LIVE_VERIFIED is checked against: a command counts as
verified on a live Creo only if a call in it ran that command and exited as expected.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.test import fingerprint  # noqa: E402

POLICY = {"CREO_CLI_PERMISSION": "write", "CREO_CLI_EXPERIMENTAL_NATIVE_WRITES": "1"}
HEXAGON = [[15 * math.cos(k * math.pi / 3), 15 * math.sin(k * math.pi / 3)] for k in range(6)]
SKETCH = {"plane": "FRONT", "orient_ref": "RIGHT"}
# Each CLI run in a console of its own would flash up a window when the recorder itself has
# none -- run from an agent's shell, some 800 of them.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class Stop(Exception):
    pass


class Recorder:
    """Runs the CLI, keeps every call, and stops at the first failed check."""

    def __init__(self, workspace: Path, run_dir: Path):
        self.workspace, self.run_dir = workspace, run_dir
        self.requests = run_dir / "requests"
        self.requests.mkdir()
        self.calls: list[dict] = []
        self.checks: list[dict] = []
        self.opened: list[str] = []
        self.env = {k: v for k, v in os.environ.items() if k != "CREO_CLI_TEST_TRACE"}
        # The run's receipts and tokens stay with the run, not in the user's own store.
        self.env["CREO_CLI_CONFIG_DIR"] = str(run_dir / "state")

    def sanitize(self, value):
        if isinstance(value, dict):
            return {
                k: "[confirmation token omitted]" if k == "confirm_token" else self.sanitize(v)
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [self.sanitize(v) for v in value]
        if isinstance(value, str):
            for form in (str(self.workspace), str(self.workspace).replace("\\", "/")):
                value = value.replace(form, "<workspace>")
        return value

    def run(self, *args, expect: int = 0, stdin: str | None = None):
        start = time.monotonic()
        argv = [str(a) for a in args]
        try:
            result = subprocess.run(
                [sys.executable, "-m", "creo_cli", *argv, "--compact"],
                cwd=ROOT,
                env=self.env,
                input=stdin,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=200,
                creationflags=NO_WINDOW,
            )
            output = json.loads(result.stdout)
        except (subprocess.TimeoutExpired, ValueError) as failure:
            raise Stop(f"{argv[:2]} gave no envelope: {type(failure).__name__}") from failure
        shown = list(argv)
        if "--confirm" in shown:
            shown[shown.index("--confirm") + 1] = "<confirm_token>"
        call = {
            "argv": self.sanitize(shown),
            "exit_code": result.returncode,
            "expected_exit_code": expect,
            "duration_ms": round((time.monotonic() - start) * 1000),
            "stdout": self.sanitize(output),
        }
        if stdin is not None:
            call["stdin"] = self.sanitize(json.loads(stdin))
        self.calls.append(call)
        if result.returncode != expect or result.stderr:
            raise Stop(f"{' '.join(shown)} exited {result.returncode}, expected {expect}")
        return output["data"] if output["ok"] else output["error"]

    def gate(self, *args, stdin: str | None = None):
        token = self.run(*args, "--dry-run", stdin=stdin)["confirm_token"]
        return self.run(*args, "--confirm", token, stdin=stdin)

    def check(self, name: str, passed, **detail) -> None:
        self.checks.append({"check": name, "passed": bool(passed), **detail})
        if not passed:
            raise Stop("check failed: " + name)

    def request(self, name: str, body: dict) -> Path:
        p = self.requests / (name + ".json")
        p.write_text(json.dumps(body), encoding="utf-8")
        return p

    def verified(self, name: str, data: dict) -> dict:
        checks = data["verification"]["checks"]
        self.check(
            name + "_postconditions",
            data["status"] == "completed" and all(c["passed"] for c in checks),
            checks=[c["check"] for c in checks],
        )
        return data

    def extrude(self, model: str, name: str, body: dict, via_stdin: bool = False) -> dict:
        body = {"units": "mm", "name": name} | body
        if via_stdin:
            data = self.gate(
                "feature", "extrude", "--model", model, "--request", "-", stdin=json.dumps(body)
            )
        else:
            data = self.gate(
                "feature", "extrude", "--model", model, "--request", self.request(name, body)
            )
        return self.verified(name.lower(), data)

    def create(self, name: str, *args) -> dict:
        data = self.verified("create_" + name, self.gate("part", "create", "--name", name, *args))
        self.opened.append(name + ".prt")
        return data

    def cleanup(self) -> None:
        """Take this run's models out of the session, whatever happened: drawings and
        assemblies before the parts they use."""
        order = {"drw": 0, "asm": 1, "prt": 2}
        for model in sorted(self.opened, key=lambda m: order.get(m.rsplit(".", 1)[-1], 3)):
            try:
                self.gate("model", "discard", "--model", model, "--dangerous")
            except Stop:
                pass


def close_enough(a, b, rel=1e-9) -> bool:
    return isinstance(a, (int, float)) and math.isclose(a, b, rel_tol=rel, abs_tol=1e-9)


def discover(r: Recorder) -> dict:
    reference = r.run("reference")
    r.check("reference_lists_commands", len(reference["commands"]) >= 20)
    r.run("context")
    r.run("changelog")
    doctor = r.run("doctor")
    failing = [
        c["check"]
        for c in doctor["checks"]
        if c["status"] == "fail" and c["check"] != "release_readiness"
    ]
    r.check("doctor_finds_nothing_failing", not failing, failing=failing)
    status = r.run("session", "status")
    r.check(
        "service_ready",
        status["connected"] and status["creation_api"] and status["native_sketch_available"],
        problems=[p["code"] for p in status["problems"]],
    )
    return status


def block_part(r: Recorder, part: str) -> None:
    """A part from nothing: block, pocket, hole; save, change, discard, reopen."""
    created = r.create(part, "--units", "mmns")
    r.check("part_created_in_millimetres", created["result"]["units"]["length"] == "mm")
    r.check("first_version_on_disk", (r.run_dir / f"{part}.prt.1").is_file())

    block = r.extrude(
        part,
        "BLOCK",
        {
            "depth": 10,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 40, "height": 20}},
        },
    )
    r.check(
        "block_adds_8000",
        close_enough(block["result"]["volume"]["change"], 8000),
        measured=block["result"]["volume"]["change"],
    )

    inches = r.request(
        "inches",
        {
            "units": "in",
            "depth": 1,
            "sketch": SKETCH | {"profile": {"type": "circle", "diameter": 1}},
        },
    )
    refused = r.run(
        "feature", "extrude", "--model", part, "--request", inches, "--dry-run", expect=6
    )
    r.check("inch_request_on_millimetre_part_refused", refused["code"] == "E_CONFLICT")

    pocket = r.extrude(
        part,
        "POCKET",
        {
            "depth": 5,
            "material": "remove",
            "sketch": SKETCH
            | {"profile": {"type": "rectangle", "width": 10, "height": 6, "center": [8, 2]}},
        },
        via_stdin=True,
    )
    r.check(
        "pocket_removes_300",
        close_enough(pocket["result"]["volume"]["change"], -300),
        measured=pocket["result"]["volume"]["change"],
    )

    hole = {
        "units": "mm",
        "name": "HOLE",
        "depth": 10,
        "material": "remove",
        "sketch": SKETCH | {"profile": {"type": "circle", "diameter": 6, "center": [-12, 0]}},
    }
    hole_file = r.request("HOLE", hole)
    stale = r.run("feature", "extrude", "--model", part, "--request", hole_file, "--dry-run")[
        "confirm_token"
    ]
    saved = r.verified("save", r.gate("model", "save", "--model", part))
    r.check("save_wrote_the_second_version", Path(saved["result"]["file"]).name == f"{part}.prt.2")
    replay = r.run(
        "feature", "extrude", "--model", part, "--request", hole_file, "--confirm", stale, expect=6
    )
    r.check("token_previewed_before_the_save_refused", replay["code"] == "E_CONFLICT")
    made = r.verified(
        "hole",
        r.gate("feature", "extrude", "--model", part, "--request", hole_file),
    )
    r.check(
        "hole_removes_pi_9_10",
        close_enough(made["result"]["volume"]["change"], -math.pi * 9 * 10, rel=1e-5),
        measured=made["result"]["volume"]["change"],
    )
    r.verified("save_again", r.gate("model", "save", "--model", part))

    listed = r.run("feature", "list", "--model", part)
    names = [f["name"] for f in listed["items"] if f.get("visible", True)]
    r.check("tree_as_built", names[-3:] == ["BLOCK", "POCKET", "HOLE"], visible=names)
    everything = r.run("feature", "list", "--model", part, "--include-internal")
    r.check(
        "internal_features_on_request",
        everything["total"] > listed["total"]
        and any(f.get("visible") is False for f in everything["items"]),
        total=everything["total"],
        visible=listed["total"],
    )
    shown = r.run("feature", "show", "--model", part, "--feature", "HOLE")
    values = sorted(d["value"] for d in shown["dimensions"])
    r.check(
        "hole_dimensions_read",
        any(close_enough(v, 6) for v in values) and any(close_enough(v, 10) for v in values),
        dimensions=values,
    )
    model = r.run("model", "show", "--model", part)
    full = 8000 - 300 - 90 * math.pi
    r.check(
        "saved_volume",
        close_enough(model["mass_properties"]["volume"], full, rel=1e-5),
        measured=model["mass_properties"]["volume"],
    )
    r.check("datum_planes_visible_only", model["datum_planes"] == ["RIGHT", "TOP", "FRONT"])
    r.check("nothing_pending_after_save", model["modified"] is False)

    preview = r.run(
        "feature", "delete", "--model", part, "--feature", "POCKET", "--dangerous", "--dry-run"
    )
    r.check("delete_preview_names_the_feature", "POCKET" in json.dumps(preview["preview"]))
    deleted = r.verified(
        "delete_pocket",
        r.run(
            "feature",
            "delete",
            "--model",
            part,
            "--feature",
            "POCKET",
            "--dangerous",
            "--confirm",
            preview["confirm_token"],
        ),
    )
    r.check(
        "delete_restores_the_pocket_volume",
        close_enough(deleted["result"]["volume"]["after"], full + 300, rel=1e-5),
        measured=deleted["result"]["volume"]["after"],
    )

    unsaved = r.run("model", "close", "--model", part, "--dry-run", expect=6)
    r.check("close_with_unsaved_changes_refused", unsaved["code"] == "E_CONFLICT")
    r.verified("discard", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")
    listed = r.run("model", "list")
    r.check(
        "discarded_model_left_the_session",
        part + ".prt" not in [m["model"] for m in listed["items"]],
    )

    newest = r.run_dir / f"{part}.prt.3"
    opened = r.verified("open", r.gate("model", "open", "--path", newest))
    r.opened.append(part + ".prt")
    r.check("reopened_from_the_newest_version", opened["result"]["model"] == part + ".prt")
    back = r.run("feature", "list", "--model", part)
    r.check(
        "saved_tree_survived_the_discard",
        [f["name"] for f in back["items"] if f.get("visible", True)][-3:]
        == ["BLOCK", "POCKET", "HOLE"],
    )
    r.verified("close", r.gate("model", "close", "--model", part))
    r.opened.remove(part + ".prt")


def hexagon_part(r: Recorder, part: str) -> None:
    """A polygon drawn by the native library, an ellipse by Java."""
    r.create(part, "--units", "mmns")
    made = r.extrude(
        part,
        "HEX",
        {"depth": 8, "sketch": SKETCH | {"profile": {"type": "polygon", "points": HEXAGON}}},
    )
    exact = 3 * math.sqrt(3) / 2 * 15**2 * 8
    r.check(
        "hexagon_volume",
        close_enough(made["result"]["volume"]["change"], exact),
        measured=made["result"]["volume"]["change"],
        exact=exact,
    )
    # Creo holds an ellipse as a spline: its volume is close, not exact.
    # Three features merged into one solid: each edge is listed once, however many
    # features rebuilt it.
    seen: dict = {}
    for e in geometry(r, part, kind="edge"):
        key = (tuple(sorted(e["surfaces"])), tuple(sorted([tuple(e["start"]), tuple(e["end"])])))
        seen.setdefault(key, []).append(e["ref"])
    twice = [refs for refs in seen.values() if len(refs) > 1]
    r.check("each_edge_listed_once", not twice, duplicates=twice)
    slot = r.extrude(
        part,
        "SLOT",
        {
            "depth": 8,
            "material": "remove",
            "sketch": SKETCH | {"profile": {"type": "ellipse", "x_radius": 6, "y_radius": 3}},
        },
    )
    r.check(
        "ellipse_removes_pi_18_8",
        close_enough(slot["result"]["volume"]["change"], -math.pi * 18 * 8, rel=1e-4),
        measured=slot["result"]["volume"]["change"],
    )
    r.verified("save_hexagon", r.gate("model", "save", "--model", part))
    r.verified("close_hexagon", r.gate("model", "close", "--model", part))
    r.opened.remove(part + ".prt")


def from_template(r: Recorder, part: str, template: Path) -> None:
    templates = r.run_dir / "templates"
    templates.mkdir()
    local = templates / template.name
    shutil.copyfile(template, local)
    created = r.create(part, "--template", local)
    r.check("created_from_a_workspace_template", created["result"]["units"]["length"] is not None)
    r.verified("close_from_template", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")
    shipped = template.parent / "mmns_asm_design_abs.asm"
    if shipped.is_file():
        local = templates / shipped.name
        shutil.copyfile(shipped, local)
        asm = part + "a"
        made = r.verified(
            "assembly_from_template",
            r.gate("assembly", "create", "--name", asm, "--template", local),
        )
        r.opened.append(asm + ".asm")
        r.check(
            "assembly_from_a_workspace_template",
            made["result"]["datum_planes"] == ["ASM_RIGHT", "ASM_TOP", "ASM_FRONT"],
        )
        r.verified(
            "discard_template_assembly",
            r.gate("model", "discard", "--model", asm + ".asm", "--dangerous"),
        )
        r.opened.remove(asm + ".asm")


def geometry(r: Recorder, part: str, **filters) -> list:
    args = ["geometry", "list", "--model", part, "--limit", "1000"]
    for k, v in filters.items():
        args += ["--" + k, v]
    return r.run(*args)["items"]


def request_gate(r: Recorder, command: str, part: str, name: str, body: dict) -> dict:
    return r.verified(
        name.lower(),
        r.gate("feature", command, "--model", part, "--request", r.request(name, body)),
    )


def bracket_part(r: Recorder, part: str) -> None:
    """A plate from nothing, worked the way a person details one: rounded corners, a row of
    holes, a chamfer, a thicker plate, parameters, a material, datums, a picture, exports."""
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "BASE",
        {
            "depth": 8,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 60, "height": 40}},
        },
    )
    vertical = [
        e["ref"] for e in geometry(r, part, kind="edge") if e.get("direction") == [0, 0, -1]
    ]
    r.check("four_vertical_edges_listed", len(vertical) == 4, edges=vertical)
    rounded = request_gate(
        r,
        "round",
        part,
        "CORNERS",
        {"units": "mm", "name": "CORNERS", "radius": 5, "edges": vertical},
    )
    left = {e["ref"] for e in geometry(r, part, kind="edge")}
    r.check(
        "rounded_edges_leave_the_list",
        not set(vertical) & left,
        still_listed=sorted(set(vertical) & left),
    )
    r.check(
        "round_matches_the_straight_edge_estimate",
        rounded["result"]["volume"].get("matches_request") is True,
        change=rounded["result"]["volume"]["change"],
        expected=rounded["result"]["volume"].get("expected_change"),
    )
    top = next(s for s in geometry(r, part, kind="surface") if s.get("normal") == [0, 0, 1])
    hole = request_gate(
        r,
        "hole",
        part,
        "H1",
        {
            "units": "mm",
            "name": "H1",
            "diameter": 6,
            "depth": "through_all",
            "placement": {
                "surface": top["ref"],
                "offsets": [{"from": "RIGHT", "distance": -20}, {"from": "TOP", "distance": -12}],
            },
        },
    )
    r.check(
        "through_hole_removes_pi_9_8",
        close_enough(hole["result"]["volume"]["change"], -math.pi * 9 * 8, rel=1e-5),
        change=hole["result"]["volume"]["change"],
    )
    axes = geometry(r, part, kind="axis")
    r.check(
        "hole_axis_where_placed",
        any(a.get("start", [None])[:2] == [-20, -12] for a in axes),
        axes=[a.get("start") for a in axes],
    )
    row = request_gate(
        r,
        "pattern",
        part,
        "ROW",
        {
            "units": "mm",
            "name": "ROW",
            "feature": "H1",
            "direction": {"along": "RIGHT", "spacing": 20, "count": 3},
        },
    )
    r.check(
        "pattern_adds_two_holes",
        close_enough(row["result"]["volume"]["change"], -2 * math.pi * 9 * 8, rel=1e-5),
        change=row["result"]["volume"]["change"],
    )
    straight = next(
        e for e in geometry(r, part, kind="edge") if e.get("direction") in ([1, 0, 0], [-1, 0, 0])
    )
    request_gate(
        r,
        "chamfer",
        part,
        "BREAK",
        {"units": "mm", "name": "BREAK", "distance": 1, "edges": [straight["ref"]]},
    )
    every = r.run("dimension", "list", "--model", part)["items"]
    dims = r.run("dimension", "list", "--model", part, "--feature", "BASE")["items"]
    r.check("every_dimension_of_the_part", len(every) > len(dims) > 0, every=len(every))
    depth = next(d for d in dims if close_enough(d["value"], 8))
    before = r.run("model", "show", "--model", part)["mass_properties"]["volume"]
    thicker = r.verified(
        "dimension_set",
        r.gate(
            "dimension",
            "set",
            "--model",
            part,
            "--dimension",
            depth["name"],
            "--value",
            10,
            "--units",
            "mm",
        ),
    )
    r.check(
        "thicker_plate_adds_volume",
        thicker["result"]["volume"]["change"] > 0 and thicker["result"]["dimension"]["value"] == 10,
        before=before,
        change=thicker["result"]["volume"]["change"],
    )
    bottom = next(s for s in geometry(r, part, kind="surface") if s.get("normal") == [0, 0, -1])
    top = next(s for s in geometry(r, part, kind="surface") if s.get("normal") == [0, 0, 1])
    gap = r.run("geometry", "measure", "--model", part, "--from", top["ref"], "--to", bottom["ref"])
    r.check("plate_is_now_10_thick", close_enough(gap["distance"], 10), distance=gap["distance"])
    r.verified(
        "parameter_description",
        r.gate(
            "parameter",
            "set",
            "--model",
            part,
            "--name",
            "DESCRIPTION",
            "--type",
            "string",
            "--value",
            "bracket",
        ),
    )
    r.verified(
        "parameter_created",
        r.gate(
            "parameter",
            "set",
            "--model",
            part,
            "--name",
            "PART_NO",
            "--type",
            "string",
            "--value",
            "CC-001",
            "--create",
        ),
    )
    params = {p["name"]: p["value"] for p in r.run("parameter", "list", "--model", part)["items"]}
    r.check("parameters_read_back", params.get("PART_NO") == "CC-001", parameters=params)
    for name, kind, value in (
        ("QTY", "integer", "4"),
        ("TARGET_MASS", "real", "1.25"),
        ("CRITICAL", "boolean", "true"),
    ):
        r.verified(
            "parameter_" + kind,
            r.gate(
                "parameter",
                "set",
                "--model",
                part,
                "--name",
                name,
                "--type",
                kind,
                "--value",
                value,
                "--create",
            ),
        )
    typed = {p["name"]: p for p in r.run("parameter", "list", "--model", part)["items"]}
    r.check(
        "typed_parameters_read_back",
        typed["QTY"]["type"] == "integer"
        and typed["QTY"]["value"] == 4
        and typed["TARGET_MASS"]["type"] == "real"
        and close_enough(typed["TARGET_MASS"]["value"], 1.25)
        and typed["CRITICAL"]["value"] is True,
        parameters={k: typed[k] for k in ("QTY", "TARGET_MASS", "CRITICAL")},
    )
    r.run("material", "list", "--name", "steel", "--model", part)
    steel = r.verified(
        "material_assign",
        r.gate("material", "assign", "--model", part, "--material", "Steel_low_carbon"),
    )
    after = steel["result"]["after"]["mass_properties"]
    r.check(
        "mass_is_volume_times_density",
        close_enough(after["mass"], after["volume"] * 7.85e-09, rel=1e-6),
        mass=after["mass"],
        volume=after["volume"],
    )
    plane = request_gate(
        r,
        "datum-plane",
        part,
        "MID",
        {"units": "mm", "name": "MID", "offset": {"from": "FRONT", "distance": -5}},
    )
    r.check("mid_plane_at_z_minus_5", plane["result"]["geometry"]["origin"][2] == -5)
    request_gate(r, "datum-axis", part, "ZAXIS", {"name": "ZAXIS", "through": ["RIGHT", "TOP"]})
    r.verified(
        "suppress_break", r.gate("feature", "suppress", "--model", part, "--feature", "BREAK")
    )
    r.verified("resume_break", r.gate("feature", "resume", "--model", part, "--feature", "BREAK"))
    r.verified(
        "rename_break",
        r.gate("feature", "rename", "--model", part, "--feature", "BREAK", "--name", "EDGE_BREAK"),
    )
    picture = r.run(
        "model", "render", "--model", part, "--view", "isometric", "--width", 800, "--height", 600
    )
    shot = Path(picture["file"])
    r.check(
        "render_is_a_jpeg",
        shot.is_file() and shot.read_bytes()[:2] == b"\xff\xd8",
        bytes=picture["bytes"],
    )
    for view in ("front", "top", "back", "bottom", "left", "right", "current"):
        other = r.run(
            "model", "render", "--model", part, "--view", view, "--width", 320, "--height", 240
        )
        r.check(
            f"render_{view}_is_a_jpeg",
            Path(other["file"]).read_bytes()[:2] == b"\xff\xd8" and other["view"] == view,
        )
    (r.run_dir / "exports").mkdir()
    for suffix in ("stp", "step", "igs", "iges", "stl"):
        out = r.verified(
            "export_" + suffix,
            r.gate(
                "model",
                "export",
                "--model",
                part,
                "--output",
                r.run_dir / "exports" / f"{part}.{suffix}",
            ),
        )
        r.check(
            f"export_{suffix}_on_disk",
            Path(out["result"]["file"]).is_file(),
            bytes=out["result"]["bytes"],
        )
    original = r.run("model", "show", "--model", part)["mass_properties"]["volume"]
    r.verified("save_bracket", r.gate("model", "save", "--model", part))
    r.verified("close_bracket", r.gate("model", "close", "--model", part))
    r.opened.remove(part + ".prt")
    # The STEP file back into Creo as a supplier's part would come: a new part, same solid.
    imported = r.verified(
        "import_step",
        r.gate(
            "model",
            "import",
            "--path",
            r.run_dir / "exports" / f"{part}.stp",
            "--name",
            part + "_imp",
        ),
    )
    r.opened.append(part + "_imp.prt")
    r.check(
        "imported_step_keeps_the_volume",
        close_enough(imported["result"]["mass_properties"]["volume"], original, rel=1e-6),
        imported=imported["result"]["mass_properties"]["volume"],
        original=original,
    )
    r.verified(
        "discard_imported",
        r.gate("model", "discard", "--model", part + "_imp.prt", "--dangerous"),
    )
    r.opened.remove(part + "_imp.prt")


def shaft_part(r: Recorder, part: str) -> None:
    """A stepped shaft revolved from a sketched profile about a sketched axis."""
    r.create(part, "--units", "mmns")
    body = {
        "units": "mm",
        "name": "SHAFT",
        "angle": 360,
        "axis": [[0, 0], [0, 1]],
        "sketch": SKETCH
        | {
            "profile": {
                "type": "polygon",
                "points": [[0, 0], [10, 0], [10, 20], [6, 20], [6, 40], [0, 40]],
            }
        },
    }
    made = request_gate(r, "revolve", part, "SHAFT", body)
    r.check(
        "revolve_matches_pappus",
        close_enough(made["result"]["volume"]["change"], math.pi * 2720, rel=1e-9),
        measured=made["result"]["volume"]["change"],
        exact=math.pi * 2720,
    )
    groove = request_gate(
        r,
        "revolve",
        part,
        "GROOVE",
        {
            "units": "mm",
            "name": "GROOVE",
            "angle": 360,
            "material": "remove",
            "axis": [[0, 0], [0, 1]],
            "sketch": SKETCH
            | {"profile": {"type": "polygon", "points": [[8, 8], [10, 8], [10, 12], [8, 12]]}},
        },
    )
    r.check(
        "groove_removes_an_annulus",
        close_enough(groove["result"]["volume"]["change"], -144 * math.pi, rel=1e-9),
        change=groove["result"]["volume"]["change"],
        exact=-144 * math.pi,
    )
    key = request_gate(
        r,
        "revolve",
        part,
        "KEY",
        {
            "units": "mm",
            "name": "KEY",
            "angle": 90,
            "side": "symmetric",
            "axis": [[0, 0], [0, 1]],
            "sketch": SKETCH
            | {"profile": {"type": "polygon", "points": [[6, 30], [8, 30], [8, 34], [6, 34]]}},
        },
    )
    other = request_gate(
        r,
        "revolve",
        part,
        "KEY2",
        {
            "units": "mm",
            "name": "KEY2",
            "angle": 90,
            "side": "two",
            "axis": [[0, 0], [0, 1]],
            "sketch": SKETCH
            | {"profile": {"type": "polygon", "points": [[6, 24], [8, 24], [8, 28], [6, 28]]}},
        },
    )
    r.check(
        "a_quarter_turn_the_other_way",
        close_enough(other["result"]["volume"]["change"], 28 * math.pi, rel=1e-5),
        change=other["result"]["volume"]["change"],
    )
    r.check(
        "a_quarter_turn_split_about_the_sketch",
        close_enough(key["result"]["volume"]["change"], 28 * math.pi, rel=1e-5),
        change=key["result"]["volume"]["change"],
        exact=28 * math.pi,
    )
    r.verified("discard_shaft", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def box_part(r: Recorder, part: str) -> None:
    """A box hollowed with its top removed, then mirrored whole about one of its faces."""
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "BOX",
        {
            "depth": 20,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 40, "height": 30}},
        },
    )
    top = next(s for s in geometry(r, part, kind="surface") if s.get("normal") == [0, 0, 1])
    shelled = request_gate(
        r,
        "shell",
        part,
        "HOLLOW",
        {"units": "mm", "name": "HOLLOW", "thickness": 2, "remove": [top["ref"]]},
    )
    inside = (40 - 4) * (30 - 4) * (20 - 2)
    r.check(
        "shell_removes_the_inside",
        close_enough(shelled["result"]["volume"]["change"], -inside, rel=1e-6),
        change=shelled["result"]["volume"]["change"],
        exact=-inside,
    )
    right = next(
        s
        for s in geometry(r, part, kind="surface")
        if s.get("normal") == [1, 0, 0] and s["origin"][0] == 20
    )
    mirrored = r.verified(
        "mirror",
        r.gate("feature", "mirror", "--model", part, "--plane", right["ref"], "--name", "TWIN"),
    )
    r.check(
        "mirror_doubles_the_box",
        mirrored["result"]["volume"].get("matches_request") is True,
        change=mirrored["result"]["volume"]["change"],
    )
    r.verified("discard_box", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def disc_part(r: Recorder, part: str) -> None:
    """Six bolt holes on a disc: one hole, patterned about an axis."""
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "DISC",
        {"depth": 5, "sketch": SKETCH | {"profile": {"type": "circle", "diameter": 50}}},
    )
    request_gate(r, "datum-axis", part, "CENTER", {"name": "CENTER", "through": ["RIGHT", "TOP"]})
    top = next(s for s in geometry(r, part, kind="surface") if s.get("normal") == [0, 0, 1])
    request_gate(
        r,
        "hole",
        part,
        "BOLT",
        {
            "units": "mm",
            "name": "BOLT",
            "diameter": 4,
            "depth": "through_all",
            "placement": {
                "surface": top["ref"],
                "offsets": [{"from": "RIGHT", "distance": 17}, {"from": "TOP", "distance": 0}],
            },
        },
    )
    bolts = request_gate(
        r,
        "pattern",
        part,
        "BOLTS",
        {
            "units": "mm",
            "name": "BOLTS",
            "feature": "BOLT",
            "axis": {"about": "CENTER", "angle": 60, "count": 6},
        },
    )
    r.check(
        "six_bolt_holes",
        len(bolts["result"]["members"]) == 6
        and close_enough(bolts["result"]["volume"]["change"], -5 * math.pi * 4 * 5, rel=1e-5),
        change=bolts["result"]["volume"]["change"],
    )
    r.verified("discard_disc", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def face(r: Recorder, part: str, normal: list) -> str:
    return next(s["ref"] for s in geometry(r, part, kind="surface") if s.get("normal") == normal)


def assembly_models(r: Recorder, stamp: str) -> None:
    """A plate and a pin, a pin constrained onto the plate, a second pin left clashing, found by
    the interference check and taken out again."""
    base, pin, asm = f"ab_{stamp}", f"ap_{stamp}", f"aa_{stamp}"
    r.create(base, "--units", "mmns")
    r.extrude(
        base,
        "PLATE",
        {
            "depth": 10,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 60, "height": 40}},
        },
    )
    request_gate(
        r,
        "hole",
        base,
        "SOCKET",
        {
            "units": "mm",
            "name": "SOCKET",
            "diameter": 10.5,
            "depth": "through_all",
            "placement": {
                "surface": face(r, base, [0, 0, 1]),
                "offsets": [{"from": "RIGHT", "distance": 20}, {"from": "TOP", "distance": 0}],
            },
        },
    )
    r.create(pin, "--units", "mmns")
    r.extrude(
        pin,
        "ROD",
        {"depth": 20, "sketch": SKETCH | {"profile": {"type": "circle", "diameter": 10}}},
    )
    request_gate(
        r, "datum-axis", pin, "PIN_AXIS", {"name": "PIN_AXIS", "through": ["RIGHT", "TOP"]}
    )
    created = r.verified(
        "create_assembly", r.gate("assembly", "create", "--name", asm, "--units", "mmns")
    )
    r.opened.append(asm + ".asm")
    r.check(
        "assembly_datums",
        created["result"]["datum_planes"] == ["ASM_RIGHT", "ASM_TOP", "ASM_FRONT"],
    )
    default = r.request("default", {"constraints": [{"type": "default"}]})
    placed_base = r.verified(
        "add_base",
        r.gate("assembly", "add", "--model", asm, "--component", base, "--request", default),
    )
    base_id = placed_base["result"]["component"]["id"]
    placing = {
        "constraints": [
            {
                "type": "mate",
                "assembly_ref": f"{face(r, base, [0, 0, 1])}@{base}",
                "component_ref": face(r, pin, [0, 0, -1]),
            },
            {"type": "align", "assembly_ref": "ASM_RIGHT", "component_ref": "RIGHT"},
            {"type": "align", "assembly_ref": "ASM_TOP", "component_ref": "TOP"},
        ]
    }
    placed = r.verified(
        "add_pin",
        r.gate(
            "assembly",
            "add",
            "--model",
            asm,
            "--component",
            pin,
            "--request",
            r.request("place", placing),
        ),
    )
    r.check(
        "pin_stands_on_the_plate",
        placed["result"]["component"]["position"]["origin"] == [0, 0, 20]
        and placed["result"]["component"]["underconstrained"] is False,
        position=placed["result"]["component"]["position"],
    )
    clean = r.run("assembly", "check", "--model", asm)
    r.check(
        "no_interference_when_placed",
        clean["interferences"] == [] and clean["not_fully_constrained"] == 0,
        interferences=clean["interferences"],
    )
    clash = r.verified(
        "add_clashing_pin",
        r.gate("assembly", "add", "--model", asm, "--component", pin, "--request", default),
    )
    found = r.run("assembly", "check", "--model", asm)["interferences"]
    r.check(
        "interference_found_with_its_volume",
        len(found) == 1 and close_enough(found[0]["volume"], math.pi * 25 * 10, rel=1e-6),
        interferences=found,
    )
    r.verified(
        "remove_clashing_pin",
        r.gate(
            "assembly",
            "remove",
            "--model",
            asm,
            "--component",
            clash["result"]["component"]["id"],
            "--dangerous",
        ),
    )
    r.check("clean_again", r.run("assembly", "check", "--model", asm)["interferences"] == [])
    socket = next(
        a["ref"]
        for a in geometry(r, base, kind="axis")
        if close_enough(a["start"][0], 20) and close_enough(a["start"][1], 0)
    )
    inserted = r.verified(
        "insert_pin",
        r.gate(
            "assembly",
            "add",
            "--model",
            asm,
            "--component",
            pin,
            "--request",
            r.request(
                "insert",
                {
                    "units": "mm",
                    "constraints": [
                        {
                            "type": "insert",
                            "assembly_ref": f"{socket}@{base_id}",
                            "component_ref": "PIN_AXIS",
                        },
                        {
                            "type": "mate",
                            "assembly_ref": f"{face(r, base, [0, 0, 1])}@{base_id}",
                            "component_ref": face(r, pin, [0, 0, -1]),
                            "offset": 5,
                        },
                        {"type": "align", "assembly_ref": "ASM_TOP", "component_ref": "TOP"},
                    ],
                },
            ),
        ),
    )
    where = inserted["result"]["component"]["position"]["origin"]
    r.check(
        "pin_inserted_into_the_socket",
        close_enough(where[0], 20)
        and close_enough(where[1], 0)
        and inserted["result"]["component"]["underconstrained"] is False,
        position=where,
    )
    r.check(
        "floating_pin_clears_the_plate",
        r.run("assembly", "check", "--model", asm)["interferences"] == [],
    )
    for kind, body in (
        (
            "csys",
            {
                "constraints": [
                    {
                        "type": "csys",
                        "assembly_ref": "ASM_DEF_CSYS",
                        "component_ref": "PRT_CSYS_DEF",
                    }
                ]
            },
        ),
        ("fix", {"constraints": [{"type": "fix"}]}),
    ):
        added = r.verified(
            "add_by_" + kind,
            r.gate(
                "assembly",
                "add",
                "--model",
                asm,
                "--component",
                pin,
                "--request",
                r.request(kind, body),
            ),
        )
        r.check(
            kind + "_places_it_fully",
            added["result"]["component"]["underconstrained"] is False,
            component=added["result"]["component"],
        )
        r.verified(
            "remove_" + kind,
            r.gate(
                "assembly",
                "remove",
                "--model",
                asm,
                "--component",
                added["result"]["component"]["id"],
                "--dangerous",
            ),
        )
    r.verified("save_assembly", r.gate("model", "save", "--model", f"{asm}.asm"))
    picture = r.run(
        "model",
        "render",
        "--model",
        f"{asm}.asm",
        "--view",
        "isometric",
        "--width",
        800,
        "--height",
        600,
    )
    r.check("assembly_render_is_a_jpeg", Path(picture["file"]).read_bytes()[:2] == b"\xff\xd8")
    (r.run_dir / "exports").mkdir(exist_ok=True)
    out = r.verified(
        "export_assembly",
        r.gate(
            "model",
            "export",
            "--model",
            f"{asm}.asm",
            "--output",
            r.run_dir / "exports" / f"{asm}.stp",
        ),
    )
    r.check("assembly_step_on_disk", Path(out["result"]["file"]).is_file())
    assembly_drawing(r, asm)
    for model in (f"{asm}.asm", base, pin):
        r.verified(
            "discard_" + model.replace(".", "_"),
            r.gate("model", "discard", "--model", model, "--dangerous"),
        )
        r.opened.remove(model if "." in model else model + ".prt")


def assembly_drawing(r: Recorder, asm: str) -> None:
    """The assembly drawn: Creo's parts list filled from it, moved to fit the sheet, and its
    components ballooned in the front view; the drawing discarded after."""
    made = r.verified(
        "assembly_drawing_create",
        r.gate(
            "drawing",
            "create",
            "--name",
            asm,
            "--of",
            asm + ".asm",
            "--sheet",
            "a3",
            "--views",
            "template",
        ),
    )
    r.opened.append(asm + ".drw")
    r.check("assembly_drawing_shows_the_assembly", asm + ".asm" in made["result"]["models"])
    components = r.run("model", "show", "--model", asm + ".asm")["components"]
    counts: dict = {}
    for c in components:
        counts[c["model"]] = counts.get(c["model"], 0) + 1
    listed = r.verified(
        "drawing_add_bom",
        r.gate("drawing", "add-bom", "--model", asm, "--x", 290, "--y", 120),
    )["result"]["table"]
    rows = [[str(x).upper() for x in row if x] for row in listed["cells"][1:]]
    r.check(
        "parts_list_counts_every_component",
        all(
            any(m.split(".")[0].upper() in row and str(n) in row for row in rows)
            for m, n in counts.items()
        ),
        rows=listed["cells"],
        components=counts,
    )
    width = listed["size"][0]
    moved = r.verified(
        "drawing_move_table",
        r.gate(
            "drawing",
            "move-table",
            "--model",
            asm,
            "--table",
            listed["id"],
            "--x",
            round(415 - width, 3),
            "--y",
            120,
        ),
    )["result"]["table"]
    r.check(
        "parts_list_moved_onto_the_sheet",
        moved["at"][0] + moved["size"][0] <= 420,
        at=moved["at"],
        size=moved["size"],
    )
    balloons = r.verified(
        "drawing_add_balloons",
        r.gate(
            "drawing",
            "add-balloons",
            "--model",
            asm,
            "--table",
            listed["id"],
            "--view",
            "VIEW_TEMPLATE_1",
        ),
    )
    r.check(
        "a_balloon_per_listed_component",
        balloons["result"]["balloons"]["made"] == len(counts),
        made=balloons["result"]["balloons"]["made"],
        listed=len(counts),
    )
    r.verified(
        "discard_assembly_drawing",
        r.gate("model", "discard", "--model", asm + ".drw", "--dangerous"),
    )
    r.opened.remove(asm + ".drw")


def finish_the_drawing(r: Recorder, part: str) -> None:
    """The rest of a person's detailing, on the plate's drawing: the note edited and moved, a
    dimension moved, the plate's thickness as a reference dimension, a title block, a surface
    finish symbol -- then each taken off again."""
    drawing = part + ".drw"

    def show() -> dict:
        return r.run("model", "show", "--model", drawing)

    note = next(n for n in show()["notes"] if n["text"].startswith("孔 Ø8"))
    edited = "孔 Ø8 通孔\n未注圆角 R1\n去毛刺"
    r.verified(
        "drawing_edit_note",
        r.gate(
            "drawing",
            "edit-note",
            "--model",
            part,
            "--note",
            note["id"],
            "--text",
            edited,
            "--x",
            50,
            "--y",
            35,
        ),
    )
    row = next(n for n in show()["notes"] if n["id"] == note["id"])
    r.check(
        "note_edited_and_moved",
        row["text"] == edited and row["at"] == [50, 35],
        note=row,
    )
    dimension = show()["dimensions"][0]
    r.verified(
        "drawing_move_dimension",
        r.gate(
            "drawing",
            "move-dimension",
            "--model",
            part,
            "--dimension",
            dimension["name"],
            "--x",
            150,
            "--y",
            250,
        ),
    )
    moved = next(d for d in show()["dimensions"] if d["name"] == dimension["name"])
    r.check(
        "dimension_text_where_asked",
        moved["at"] == [150, 250] and moved["value"] == dimension["value"],
        before=dimension["at"],
        after=moved["at"],
    )
    # The plate is 10 thick; no feature dimension says so on the top view. Its two long
    # edges at the back (y = 20) are 10 apart, one on each face.
    back = sorted(
        (
            e
            for e in geometry(r, part, kind="edge")
            if e.get("type") == "line"
            and e.get("direction") in ([1, 0, 0], [-1, 0, 0])
            and close_enough(e["start"][1], 20, rel=1e-9)
        ),
        key=lambda e: e["start"][2],
    )
    added = r.verified(
        "drawing_add_dimension",
        r.gate(
            "drawing",
            "add-dimension",
            "--model",
            part,
            "--view",
            "VIEW_TEMPLATE_2",
            "--from",
            back[0]["ref"],
            "--to",
            back[-1]["ref"],
            "--orientation",
            "vertical",
            "--x",
            60,
            "--y",
            262,
        ),
    )
    thickness = added["result"]["dimension"]
    r.check(
        "thickness_measured_by_creo",
        thickness["reference"] is True and close_enough(thickness["value"], 10, rel=1e-9),
        dimension=thickness,
    )
    r.verified(
        "drawing_move_reference_dimension",
        r.gate(
            "drawing",
            "move-dimension",
            "--model",
            part,
            "--dimension",
            thickness["name"],
            "--x",
            45,
            "--y",
            262,
        ),
    )
    moved = next(d for d in show()["dimensions"] if d["name"] == thickness["name"])
    r.check("reference_dimension_where_asked", moved["at"] == [45, 262], at=moved["at"])
    refused = r.run(
        "drawing",
        "hide-dimension",
        "--model",
        part,
        "--dimension",
        thickness["name"],
        "--dry-run",
        expect=6,
    )
    r.check(
        "a_drawings_own_dimension_is_removed_not_hidden",
        refused["code"] == "E_CONFLICT" and "drawing remove" in refused["details"]["fix"],
    )
    title = {
        "units": "mm",
        "at": [290, 45],
        "columns": [30, 60, 35],
        "rows": [8, 8, 8],
        "cells": [
            ["名称", "带孔平板", "比例 1:1"],
            ["材料", "Q235", "数量 1"],
            ["备注：未注公差按 GB/T 1804-m"],
        ],
        "merge": [[3, 1, 3, 3]],
    }
    narrow = r.run(
        "drawing", "add-table", "--model", part, "--request", r.request("title", title), "--dry-run"
    )["preview"]["cells_too_narrow"]
    r.check("title_block_text_fits", narrow == [], narrow=narrow)
    table = r.verified(
        "drawing_add_table",
        r.gate("drawing", "add-table", "--model", part, "--request", r.request("title", title)),
    )["result"]["table"]
    r.check(
        "title_block_reads_back",
        table["cells"][0] == title["cells"][0]
        and table["cells"][2][0] == title["cells"][2][0]
        and table["at"] == [290, 45],
        table=table,
    )
    unknown = r.run(
        "drawing",
        "add-symbol",
        "--model",
        part,
        "--symbol",
        "surffins/nothing",
        "--x",
        200,
        "--y",
        200,
        "--dry-run",
        expect=3,
    )
    r.check(
        "an_unknown_symbol_lists_the_library",
        "surffins/generic/standard" in unknown["details"]["library"],
        library=len(unknown["details"]["library"]),
    )
    symbol = r.verified(
        "drawing_add_symbol",
        r.gate(
            "drawing",
            "add-symbol",
            "--model",
            part,
            "--symbol",
            "surffins/generic/standard",
            "--x",
            120,
            "--y",
            260,
            "--value",
            "roughness_height=3.2",
        ),
    )["result"]["symbol"]
    placed = next(s for s in show()["symbols"] if s["id"] == symbol["id"])
    r.check(
        "surface_finish_reads_back",
        # Creo keeps the variable as a number and shows it in the sheet's format.
        float(str(placed["values"].get("roughness_height")).replace(",", ".")) == 3.2
        and placed["at"] == [120, 260],
        symbol=placed,
    )
    for item in (
        f"symbol:{symbol['id']}",
        f"table:{table['id']}",
        f"note:{note['id']}",
        f"dimension:{thickness['name']}",
    ):
        kind = item.split(":")[0]
        r.verified(
            "drawing_remove_" + kind,
            r.gate("drawing", "remove", "--model", part, "--item", item),
        )
    left = show()
    r.check(
        "what_the_drawing_owned_is_gone",
        symbol["id"] not in [s["id"] for s in left["symbols"]]
        and table["id"] not in [t["id"] for t in left["tables"]]
        and note["id"] not in [n["id"] for n in left["notes"]]
        and thickness["name"] not in [d["name"] for d in left["dimensions"]],
    )


def views_of_the_drawing(r: Recorder, part: str) -> None:
    """A section through the hole's axis, a detail of the hole, a view moved and taken off."""
    drawing = part + ".drw"

    def views() -> list:
        return r.run("model", "show", "--model", drawing)["views"]

    # The hole is 15 from RIGHT: a plane there cuts through its axis.
    request_gate(
        r,
        "datum-plane",
        part,
        "SEC_H1",
        {"units": "mm", "name": "SEC_H1", "offset": {"from": "RIGHT", "distance": 15}},
    )
    front = next(v for v in views() if v["name"] == "VIEW_TEMPLATE_1")
    middle_y = (front["outline"][0][1] + front["outline"][1][1]) / 2
    cut = r.verified(
        "drawing_section_view",
        r.gate(
            "drawing",
            "add-view",
            "--model",
            part,
            "--type",
            "projection",
            "--parent",
            "VIEW_TEMPLATE_1",
            "--plane",
            "SEC_H1",
            "--x",
            35,
            "--y",
            round(middle_y, 3),
        ),
    )
    section = cut["result"]["view"]["sections"]
    sections = r.run("model", "show", "--model", part)["cross_sections"]
    r.check(
        "section_cut_through_the_plane_in_the_part",
        len(section) == 1
        and any(x["name"] == section[0] and x["plane"] == "SEC_H1" for x in sections),
        view=cut["result"]["view"],
        cross_sections=sections,
    )
    hole = next(
        e
        for e in geometry(r, part, kind="edge")
        if e.get("type") == "arc" and (e.get("feature") or {}).get("name") == "H1"
    )
    detail = r.verified(
        "drawing_detail_view",
        r.gate(
            "drawing",
            "add-view",
            "--model",
            part,
            "--type",
            "detail",
            "--parent",
            "VIEW_TEMPLATE_1",
            "--center",
            hole["ref"],
            "--radius",
            7,
            "--x",
            360,
            "--y",
            60,
        ),
    )["result"]["view"]
    (x0, y0), (x1, y1) = detail["outline"]
    r.check(
        "detail_of_the_hole_twice_its_size",
        detail["type"] == "detail"
        and detail["scale"] == 2 * front["scale"]
        and close_enough(x1 - x0, 28 * front["scale"], rel=1e-6)
        and close_enough((x0 + x1) / 2, 360, rel=1e-9),
        view=detail,
    )
    moved = r.verified(
        "drawing_move_view",
        r.gate(
            "drawing", "move-view", "--model", part, "--view", detail["name"], "--x", 370, "--y", 75
        ),
    )["result"]["view"]
    (x0, y0), (x1, y1) = moved["outline"]
    r.check(
        "view_moved_where_asked",
        close_enough((x0 + x1) / 2, 370, rel=1e-9) and close_enough((y0 + y1) / 2, 75, rel=1e-9),
        outline=moved["outline"],
    )
    refused = r.run(
        "drawing",
        "remove",
        "--model",
        part,
        "--item",
        "view:VIEW_TEMPLATE_1",
        "--dry-run",
        expect=6,
    )
    r.check(
        "a_parent_view_is_not_removed",
        refused["code"] == "E_CONFLICT" and detail["name"] in refused["details"]["children"],
    )
    r.verified(
        "drawing_remove_view",
        r.gate("drawing", "remove", "--model", part, "--item", "view:" + detail["name"]),
    )
    r.check(
        "the_detail_view_is_gone",
        detail["name"] not in [v["name"] for v in views()],
    )


def profile_variety(r: Recorder, stamp: str) -> None:
    """Profiles a person sketches past polygons: a plate with rounded corners, two holes and a
    slot inside it; an L bracket whose inside corner is an arc, a slot cut through it; a
    shaft revolved from an outline with a rounded shoulder -- each volume checked exactly."""
    plate = f"lq_{stamp}"
    r.create(plate, "--units", "mmns")
    made = r.extrude(
        plate,
        "PLATE",
        {
            "depth": 8,
            "sketch": SKETCH
            | {
                "profile": {
                    "type": "rectangle",
                    "width": 60,
                    "height": 40,
                    "corner_radius": 5,
                    "holes": [
                        {"type": "circle", "diameter": 6, "center": [-22, -12]},
                        {"type": "circle", "diameter": 6, "center": [22, 12]},
                        {"type": "slot", "centers": [[-8, 0], [8, 0]], "width": 6},
                    ],
                }
            },
        },
    )
    area = 60 * 40 - (4 - math.pi) * 25 - 2 * math.pi * 9 - (16 * 6 + math.pi * 9)
    r.check(
        "rounded_plate_with_holes_volume_exact",
        close_enough(made["result"]["volume"]["change"], area * 8, rel=1e-6),
        measured=made["result"]["volume"]["change"],
        expected=area * 8,
    )
    bracket = f"lu_{stamp}"
    r.create(bracket, "--units", "mmns")
    made = r.extrude(
        bracket,
        "BRACKET",
        {
            "depth": 12,
            "sketch": SKETCH
            | {
                "profile": {
                    "type": "outline",
                    "start": [0, 0],
                    "segments": [
                        {"to": [30, 0]},
                        {"to": [30, 10]},
                        {"to": [14, 10]},
                        {"to": [10, 14], "sweep": -90},
                        {"to": [10, 30]},
                        {"to": [0, 30]},
                    ],
                }
            },
        },
    )
    r.check(
        "bracket_with_a_filleted_corner_volume_exact",
        close_enough(made["result"]["volume"]["change"], (516 - 4 * math.pi) * 12, rel=1e-6),
        measured=made["result"]["volume"]["change"],
    )
    cut = r.extrude(
        bracket,
        "SLOT",
        {
            "depth": 12,
            "material": "remove",
            "sketch": SKETCH
            | {"profile": {"type": "slot", "centers": [[4, 5], [4, 24]], "width": 4}},
        },
    )
    r.check(
        "slot_cut_volume_exact",
        close_enough(cut["result"]["volume"]["change"], -(19 * 4 + 4 * math.pi) * 12, rel=1e-6),
        measured=cut["result"]["volume"]["change"],
    )
    shaft = f"lw2_{stamp}"
    r.create(shaft, "--units", "mmns")
    shoulder = {
        "type": "outline",
        "start": [0, 0],
        "segments": [
            {"to": [10, 0]},
            {"to": [10, 18]},
            {"to": [8, 20], "sweep": 90},
            {"to": [6, 20]},
            {"to": [6, 40]},
            {"to": [0, 40]},
        ],
    }
    turned = r.verified(
        "shaft_with_a_rounded_shoulder",
        r.gate(
            "feature",
            "revolve",
            "--model",
            shaft,
            "--request",
            r.request(
                "SHOULDER",
                {
                    "units": "mm",
                    "name": "SHOULDER",
                    "angle": 360,
                    "axis": [[0, 0], [0, 1]],
                    "sketch": SKETCH | {"profile": shoulder},
                },
            ),
        ),
    )
    r.check(
        "revolved_outline_volume_by_pappus",
        turned["result"]["volume"]["matches_request"],
        volume=turned["result"]["volume"],
    )


def tolerance_the_drawing(r: Recorder, part: str) -> None:
    """Datums on the plate's bottom and left faces; the hole located by a position tolerance
    under its size, the top flat by a frame led to it, a parallelism free in a view; some
    taken off again."""
    drawing = part + ".drw"

    def shown() -> dict:
        return r.run("model", "show", "--model", drawing)

    faces = geometry(r, part, kind="surface")
    bottom = next(f["ref"] for f in faces if f.get("normal") == [0, -1, 0])
    left = next(f["ref"] for f in faces if f.get("normal") == [-1, 0, 0])
    for label, face_ref in (("A", bottom), ("B", left)):
        r.verified(
            "drawing_datum_" + label.lower(),
            r.gate(
                "drawing",
                "add-datum",
                "--model",
                part,
                "--label",
                label,
                "--view",
                "VIEW_TEMPLATE_1",
                "--on",
                face_ref,
            ),
        )
    r.check(
        "datums_on_their_faces",
        [(d["label"], d["on"]) for d in shown()["datums"]] == [("A", bottom), ("B", left)],
        datums=shown()["datums"],
    )
    hole = next(
        d["name"]
        for d in shown()["dimensions"]
        if d.get("type") == "diameter" and (d.get("feature") or {}).get("name") == "H1"
    )
    frame = r.verified(
        "drawing_position_tolerance",
        r.gate(
            "drawing",
            "add-gtol",
            "--model",
            part,
            "--type",
            "position",
            "--value",
            "0.1",
            "--diameter",
            "--material",
            "mmc",
            "--datums",
            "A,B",
            "--dimension",
            hole,
        ),
    )["result"]["gtol"]
    r.check(
        "position_frame_kept_with_the_part",
        frame["model"] == part + ".prt"
        and frame["value"].endswith("Ⓜ")
        and frame["datums"] == ["A", "B"],
        frame=frame,
    )
    top = next(
        e["ref"]
        for e in geometry(r, part, kind="edge")
        if e.get("direction") in ([1, 0, 0], [-1, 0, 0])
        and close_enough(e["start"][1], 20, rel=1e-9)
        and close_enough(e["start"][2], 0, rel=1e-9)
    )
    r.verified(
        "drawing_flatness_tolerance",
        r.gate(
            "drawing",
            "add-gtol",
            "--model",
            part,
            "--type",
            "flatness",
            "--value",
            "0.05",
            "--view",
            "VIEW_TEMPLATE_2",
            "--on",
            top,
            "--x",
            160,
            "--y",
            250,
        ),
    )
    r.verified(
        "drawing_parallelism_tolerance",
        r.gate(
            "drawing",
            "add-gtol",
            "--model",
            part,
            "--type",
            "parallelism",
            "--value",
            "0.02",
            "--datums",
            "A",
            "--view",
            "VIEW_TEMPLATE_1",
            "--x",
            255,
            "--y",
            190,
        ),
    )
    frames = shown()["gtols"]
    r.check(
        "three_frames_read_back",
        sorted(g["type"] for g in frames) == ["flatness", "parallelism", "position"],
        frames=frames,
    )
    parallel = next(g for g in frames if g["type"] == "parallelism")
    for item in (
        f"gtol:{frame['id']}@{frame['model']}",
        f"gtol:{parallel['id']}",
        "datum:B",
    ):
        r.verified(
            "drawing_remove_" + item.split(":")[0] + "_" + item.split(":")[1].split("@")[0],
            r.gate("drawing", "remove", "--model", part, "--item", item),
        )
    left_over = shown()
    r.check(
        "frames_and_datum_taken_off",
        [g["type"] for g in left_over["gtols"]] == ["flatness"]
        and [d["label"] for d in left_over["datums"]] == ["A"],
        gtols=left_over["gtols"],
        datums=left_over["datums"],
    )


def relations_part(r: Recorder, stamp: str) -> None:
    """A block whose depth a relation keeps a quarter of its width: the width changed, the
    depth follows, the volume says so; the driven depth refused a value of its own."""
    part = f"lrr_{stamp}"
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "BLOCK",
        {
            "depth": 10,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 40, "height": 20}},
        },
    )
    dims = r.run("dimension", "list", "--model", part, "--feature", "BLOCK")["items"]
    width = next(d["name"] for d in dims if close_enough(d["value"], 40))
    # The depth, not the sketch's offset of 10 from the reference: in_sketch tells them apart.
    depth = next(
        d["name"] for d in dims if close_enough(d["value"], 10) and d["in_sketch"] is False
    )
    rules = {"relations": ["/* as deep as a quarter of its width", f"{depth} = {width} / 4"]}
    set_ = r.verified(
        "relation_set",
        r.gate("relation", "set", "--model", part, "--request", r.request("relations", rules)),
    )
    r.check(
        "relations_read_back",
        r.run("relation", "list", "--model", part)["relations"] == rules["relations"],
        relations=set_["result"]["relations"],
    )
    refused = r.run(
        "dimension",
        "set",
        "--model",
        part,
        "--dimension",
        depth,
        "--value",
        12,
        "--units",
        "mm",
        "--dry-run",
        expect=6,
    )
    r.check("a_driven_dimension_refuses_a_value", refused["code"] == "E_CONFLICT")
    grown = r.verified(
        "width_changed",
        r.gate(
            "dimension",
            "set",
            "--model",
            part,
            "--dimension",
            width,
            "--value",
            48,
            "--units",
            "mm",
        ),
    )
    r.check(
        "depth_follows_the_width",
        close_enough(grown["result"]["volume"]["after"], 48 * 20 * 12, rel=1e-9),
        volume=grown["result"]["volume"],
    )
    cleared = r.verified(
        "relations_cleared",
        r.gate(
            "relation",
            "set",
            "--model",
            part,
            "--request",
            r.request("no_relations", {"relations": []}),
        ),
    )
    r.check("relations_gone", cleared["result"]["relations"] == [])
    r.verified("discard_relations_part", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def drawing_models(r: Recorder, stamp: str, template: Path | None = None) -> None:
    """A plate with a hole, drawn on A3 from Creo's template, an isometric view added, its
    dimensions shown, exported as PDF and saved."""
    part = f"dp_{stamp}"
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "PLATE",
        {
            "depth": 10,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 60, "height": 40}},
        },
    )
    request_gate(
        r,
        "hole",
        part,
        "H1",
        {
            "units": "mm",
            "name": "H1",
            "diameter": 8,
            "depth": "through_all",
            "placement": {
                "surface": face(r, part, [0, 0, 1]),
                "offsets": [{"from": "RIGHT", "distance": 15}, {"from": "TOP", "distance": 5}],
            },
        },
    )
    made = r.verified(
        "drawing_create",
        r.gate(
            "drawing",
            "create",
            "--name",
            part,
            "--of",
            part,
            "--sheet",
            "a3",
            "--views",
            "template",
        ),
    )
    r.opened.append(part + ".drw")
    r.check(
        "standard_sheet_letters_in_creo_font",
        str(made["result"].get("lettering")).lower() in ("font", "font.ndx"),
        lettering=made["result"].get("lettering"),
    )
    chosen = made["result"].get("scale_chosen") or {}
    r.check(
        "sheet_at_a_preferred_scale",
        chosen.get("label") in ("1:1", "2:1", "5:1", "1:2", "1:5", "10:1", "1:10")
        and all(v["scale"] == chosen.get("scale") for v in made["result"]["views"]),
        scale=chosen,
    )
    views = made["result"]["views"]
    r.check(
        "template_views_on_the_sheet",
        len(views) >= 3
        and all(0 <= v["outline"][0][0] and v["outline"][1][0] <= 420 for v in views),
        views=[[v["name"], v["outline"]] for v in views],
    )
    iso = r.verified(
        "drawing_isometric",
        r.gate(
            "drawing",
            "add-view",
            "--model",
            part,
            "--type",
            "general",
            "--orientation",
            "isometric",
            "--x",
            330,
            "--y",
            220,
            "--scale",
            1,
        ),
    )
    r.check("isometric_view_added", len(iso["result"]["views"]) == len(views) + 1)
    parent = views[0]
    middle = (parent["outline"][0][0] + parent["outline"][1][0]) / 2
    below = r.verified(
        "drawing_projection",
        r.gate(
            "drawing",
            "add-view",
            "--model",
            part,
            "--type",
            "projection",
            "--parent",
            parent["name"],
            "--x",
            round(middle, 3),
            "--y",
            40,
        ),
    )
    known = {v["name"] for v in iso["result"]["views"]}
    added = [v for v in below["result"]["views"] if v["name"] not in known]
    for (x, y), orientation in zip(
        ((180, 60), (230, 60), (180, 110), (230, 110), (180, 160), (230, 160)),
        ("front", "back", "top", "bottom", "left", "right"),
        strict=True,
    ):
        placed = r.verified(
            "drawing_view_" + orientation,
            r.gate(
                "drawing",
                "add-view",
                "--model",
                part,
                "--type",
                "general",
                "--orientation",
                orientation,
                "--x",
                x,
                "--y",
                y,
                "--scale",
                0.5,
            ),
        )
        # A 60 x 40 x 10 plate at half scale: 30 x 20 from the front or back, 30 x 5 from
        # the top or bottom, 5 x 20 from the side.
        view = placed["result"]["views"][-1]
        (x0, y0), (x1, y1) = view["outline"]
        size = {"front": (30, 20), "back": (30, 20), "top": (30, 5), "bottom": (30, 5)}.get(
            orientation, (5, 20)
        )
        r.check(
            f"general_view_{orientation}_shows_that_side",
            view["scale"] == 0.5
            and close_enough(x1 - x0, size[0], rel=1e-6)
            and close_enough(y1 - y0, size[1], rel=1e-6),
            view=view,
        )
    r.check(
        "projection_lines_up_under_its_parent",
        len(added) == 1
        and abs((added[0]["outline"][0][0] + added[0]["outline"][1][0]) / 2 - middle) < 0.5,
        view=added,
        parent_middle=middle,
    )
    noted = r.verified("drawing_annotate", r.gate("drawing", "annotate", "--model", part))
    r.check(
        "dimensions_shown_on_the_drawing",
        noted["result"]["annotated"]["shown"] >= 6,
        shown=noted["result"]["annotated"]["shown"],
        by_view=noted["result"]["annotated"]["by_view"],
    )
    left = r.run("model", "show", "--model", part + ".drw")["dimensions"]
    r.check(
        "no_dimension_of_zero_shown",
        all(abs(d.get("value") or 0) > 1e-9 for d in left)
        and isinstance(noted["result"]["annotated"].get("zeros_taken_off"), list),
        zeros=noted["result"]["annotated"].get("zeros_taken_off"),
    )
    pdf = r.verified(
        "drawing_pdf",
        r.gate(
            "model",
            "export",
            "--model",
            part + ".drw",
            "--output",
            r.run_dir / "exports" / f"{part}.pdf",
        ),
    )
    r.check("pdf_on_disk", Path(pdf["result"]["file"]).read_bytes()[:5] == b"%PDF-")
    r.verified("save_drawing", r.gate("model", "save", "--model", part + ".drw"))
    shown = r.run("model", "show", "--model", part + ".drw")
    r.check(
        "dimensions_read_back_from_the_drawing",
        shown["dimensions_shown"] == noted["result"]["annotated"]["shown"],
        shown=shown["dimensions_shown"],
    )
    # Detailing as an engineer does: a dimension taken off, then only the hole's, notes.
    rows = r.run("model", "show", "--model", part + ".drw")["dimensions"]
    doomed = next(d for d in rows if (d.get("feature") or {}).get("name") == "PLATE")
    r.verified(
        "drawing_hide_dimension",
        r.gate("drawing", "hide-dimension", "--model", part, "--dimension", doomed["name"]),
    )
    left = r.run("model", "show", "--model", part + ".drw")["dimensions"]
    r.check(
        "dimension_taken_off_the_drawing",
        doomed["name"] not in [d["name"] for d in left] and len(left) == len(rows) - 1,
        taken_off=doomed["name"],
        shown=len(left),
    )
    only = r.verified(
        "drawing_annotate_the_hole_only",
        r.gate("drawing", "annotate", "--model", part, "--feature", "H1"),
    )
    rows = r.run("model", "show", "--model", part + ".drw")["dimensions"]
    r.check(
        "only_the_holes_dimensions_shown",
        rows and {(d.get("feature") or {}).get("name") for d in rows} == {"H1"},
        shown=[[d["name"], d["value"], (d.get("feature") or {}).get("name")] for d in rows],
        taken_off=len(only["result"]["annotated"]["taken_off"]),
    )
    r.verified("drawing_annotate_all_again", r.gate("drawing", "annotate", "--model", part))
    rows = r.run("model", "show", "--model", part + ".drw")["dimensions"]
    r.check(
        "erased_dimensions_stay_off",
        {(d.get("feature") or {}).get("name") for d in rows} == {"H1"},
        shown=[[d["name"], (d.get("feature") or {}).get("name")] for d in rows],
    )
    note = "孔 Ø8 通孔\n未注圆角 R1"
    r.verified(
        "drawing_add_note",
        r.gate("drawing", "add-note", "--model", part, "--text", note, "--x", 40, "--y", 30),
    )
    notes = r.run("model", "show", "--model", part + ".drw")["notes"]
    r.check(
        "note_on_the_sheet_reads_back",
        any(n["text"] == note.replace("\\n", "\n") for n in notes),
        notes=[n["text"] for n in notes],
    )
    finish_the_drawing(r, part)
    views_of_the_drawing(r, part)
    tolerance_the_drawing(r, part)
    for sheet in ("a0", "a1", "a2", "a4", "a", "b", "c", "d", "e", "f"):
        sized = f"{part}_{sheet}"
        made = r.verified(
            "drawing_on_" + sheet,
            r.gate("drawing", "create", "--name", sized, "--of", part, "--sheet", sheet),
        )
        r.opened.append(sized + ".drw")
        first = sheet.startswith("a") and sheet != "a"
        r.check(
            f"sheet_{sheet}_laid_out_by_its_projection",
            made["result"]["sheets"][0].get("size") == sheet
            and made["result"]["projection"] == ("first_angle" if first else "third_angle")
            and made["result"]["views_laid_out"]
            == ["FRONT", "LEFT" if first else "RIGHT", "TOP", "ISOMETRIC"],
            sheets=made["result"]["sheets"],
            projection=made["result"]["projection"],
            views=made["result"]["views_laid_out"],
        )
        r.verified(
            "discard_" + sized, r.gate("model", "discard", "--model", sized + ".drw", "--dangerous")
        )
        r.opened.remove(sized + ".drw")
    own = template.parent / "a4_drawing.drw" if template else None
    if own and own.is_file():
        shutil.copyfile(own, r.run_dir / "house_a4.drw")
        mine = f"{part}_own"
        made = r.verified(
            "drawing_from_own_template",
            r.gate(
                "drawing",
                "create",
                "--name",
                mine,
                "--of",
                part,
                "--template",
                r.run_dir / "house_a4.drw",
            ),
        )
        r.opened.append(mine + ".drw")
        r.check("own_template_lays_out_views", len(made["result"]["views"]) >= 1)
        r.verified(
            "discard_own_drawing",
            r.gate("model", "discard", "--model", mine + ".drw", "--dangerous"),
        )
        r.opened.remove(mine + ".drw")
    for model in (part + ".drw", part):
        r.verified(
            "close_" + model.replace(".", "_"),
            r.gate("model", "discard", "--model", model, "--dangerous"),
        )
        r.opened.remove(model if "." in model else model + ".prt")


def sketch_variants(r: Recorder, stamp: str) -> None:
    """Every extrude and sketch option on one part: symmetric, one side and the other, an
    orientation of one's own, a plane of one's own with its references; a datum plane at an
    angle, datum axes along an edge and a cylinder, a pattern run backwards."""
    part = f"lv_{stamp}"
    r.create(part, "--units", "mmns")
    base = r.extrude(
        part,
        "BASE",
        {
            "depth": 10,
            "side": "symmetric",
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 40, "height": 20}},
        },
    )
    r.check(
        "symmetric_block_adds_8000",
        close_enough(base["result"]["volume"]["change"], 8000),
        change=base["result"]["volume"]["change"],
    )
    box = r.run("model", "show", "--model", part)["bbox"]
    r.check(
        "symmetric_about_the_sketch_plane",
        close_enough(box[0][2], -5) and close_enough(box[1][2], 5),
        bbox=box,
    )
    boss = SKETCH | {"profile": {"type": "circle", "diameter": 10}}
    down = r.extrude(part, "DOWN", {"depth": 8, "sketch": boss})
    r.check(
        "side_one_adds_below_the_block",
        close_enough(down["result"]["volume"]["change"], 75 * math.pi, rel=1e-5),
        change=down["result"]["volume"]["change"],
    )
    up = r.extrude(part, "UP", {"depth": 8, "side": "two", "sketch": boss})
    r.check(
        "side_two_adds_above_it",
        close_enough(up["result"]["volume"]["change"], 75 * math.pi, rel=1e-5),
        change=up["result"]["volume"]["change"],
    )
    slot = r.extrude(
        part,
        "SLOT",
        {
            "depth": 2,
            "material": "remove",
            "sketch": {
                "plane": "FRONT",
                "orient_ref": "TOP",
                "orient": "up",
                "profile": {"type": "rectangle", "width": 30, "height": 4},
            },
        },
    )
    r.check(
        "orientation_of_ones_own_keeps_the_slot_inside",
        close_enough(slot["result"]["volume"]["change"], -240),
        change=slot["result"]["volume"]["change"],
    )
    for name, body, removed in (
        (
            "SLOT_DOWN",
            {
                "depth": 2,
                "sketch": {
                    "plane": "FRONT",
                    "orient_ref": "TOP",
                    "orient": "down",
                    "profile": {"type": "rectangle", "width": 30, "height": 4, "center": [0, 6]},
                },
            },
            240,
        ),
        (
            "SLOT_LEFT",
            {
                "depth": 1,
                "side": "two",
                "sketch": {
                    "plane": "FRONT",
                    "orient_ref": "RIGHT",
                    "orient": "left",
                    "profile": {"type": "rectangle", "width": 20, "height": 2},
                },
            },
            40,
        ),
    ):
        cut = r.extrude(part, name, body | {"material": "remove"})
        r.check(
            name.lower() + "_oriented_and_inside",
            close_enough(cut["result"]["volume"]["change"], -removed),
            change=cut["result"]["volume"]["change"],
        )
    side = request_gate(
        r,
        "datum-plane",
        part,
        "SIDE",
        {"units": "mm", "name": "SIDE", "offset": {"from": "RIGHT", "distance": 20}},
    )
    r.check("side_plane_at_x_20", close_enough(side["result"]["geometry"]["origin"][0], 20))
    peg = r.extrude(
        part,
        "PEG",
        {
            "depth": 10,
            "side": "symmetric",
            "material": "remove",
            "sketch": {
                "plane": "SIDE",
                "orient_ref": "TOP",
                "orient": "up",
                "references": ["TOP", "FRONT"],
                "profile": {"type": "circle", "diameter": 4},
            },
        },
    )
    r.check(
        "a_plane_of_ones_own_with_its_references",
        close_enough(peg["result"]["volume"]["change"], -20 * math.pi, rel=1e-5),
        change=peg["result"]["volume"]["change"],
    )
    request_gate(r, "datum-axis", part, "ZAXIS", {"name": "ZAXIS", "through": ["RIGHT", "TOP"]})
    tilt = request_gate(
        r,
        "datum-plane",
        part,
        "TILT",
        {
            "units": "mm",
            "name": "TILT",
            "angle": {"through": "ZAXIS", "from": "TOP", "degrees": 30},
        },
    )
    normal = tilt["result"]["geometry"]["normal"]
    r.check(
        "plane_turned_30_degrees_about_the_axis",
        abs(normal[2]) < 1e-9 and close_enough(abs(normal[1]), math.cos(math.radians(30))),
        normal=normal,
    )
    edge = next(
        e for e in geometry(r, part, kind="edge") if e.get("direction") in ([1, 0, 0], [-1, 0, 0])
    )
    along = request_gate(
        r, "datum-axis", part, "ALONG", {"name": "ALONG", "through": [edge["ref"]]}
    )
    direction = along["result"]["geometry"]["direction"]
    r.check("axis_along_the_edge", close_enough(abs(direction[0]), 1), direction=direction)
    cylinder = next(
        s
        for s in geometry(r, part, kind="surface")
        if s.get("type") == "cylinder" and abs(s["axis"]["direction"][2]) > 0.99
    )
    core = request_gate(
        r, "datum-axis", part, "CORE", {"name": "CORE", "through": [cylinder["ref"]]}
    )
    direction = core["result"]["geometry"]["direction"]
    r.check("axis_of_the_cylinder", close_enough(abs(direction[2]), 1), direction=direction)
    planes = [g["ref"] for g in geometry(r, part, kind="datum_plane")]
    systems = [g["ref"] for g in geometry(r, part, kind="csys")]
    cylinders = geometry(r, part, type="cylinder")
    owned = geometry(r, part, feature="UP")
    r.check(
        "geometry_list_filters",
        {"SIDE", "TILT"} <= set(planes)
        and systems == ["PRT_CSYS_DEF"]
        and cylinders
        and all(c.get("type") == "cylinder" for c in cylinders)
        and owned
        and all((g.get("feature") or {}).get("name") == "UP" for g in owned),
        planes=planes,
        systems=systems,
        cylinders=len(cylinders),
        owned=len(owned),
    )
    top = next(
        s["ref"]
        for s in geometry(r, part, kind="surface")
        if s.get("normal") == [0, 0, 1] and close_enough(s["origin"][2], 5)
    )
    request_gate(
        r,
        "hole",
        part,
        "PIT",
        {
            "units": "mm",
            "name": "PIT",
            "diameter": 2,
            "depth": 3,
            "placement": {
                "surface": top,
                "offsets": [{"from": "RIGHT", "distance": 12}, {"from": "TOP", "distance": 0}],
            },
        },
    )
    back = request_gate(
        r,
        "pattern",
        part,
        "BACK",
        {
            "units": "mm",
            "name": "BACK",
            "feature": "PIT",
            "direction": {"along": "RIGHT", "spacing": -8, "count": 2},
        },
    )
    axes = [a.get("start", [None, None])[:2] for a in geometry(r, part, kind="axis")]
    r.check(
        "negative_spacing_patterns_backwards",
        close_enough(back["result"]["volume"]["change"], -3 * math.pi, rel=1e-5)
        and any(close_enough(a[0], 4) and close_enough(a[1], 0) for a in axes if a[0] is not None),
        change=back["result"]["volume"]["change"],
        axes=axes,
    )
    island = r.extrude(
        part,
        "ISLAND",
        {
            "depth": 4,
            "body": "new",
            "sketch": SKETCH
            | {"profile": {"type": "rectangle", "width": 6, "height": 6, "center": [40, 0]}},
        },
    )
    r.check(
        "a_new_body_beside_the_first",
        close_enough(island["result"]["volume"]["change"], 144),
        change=island["result"]["volume"]["change"],
    )
    bodies = r.run("model", "show", "--model", part)["bodies"]
    r.check("the_part_holds_two_bodies", len(bodies) == 2, bodies=bodies)
    r.verified("discard_variants", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def revolved_ring(r: Recorder, stamp: str) -> None:
    """A ring revolved about a datum axis of the part, not one drawn in the sketch."""
    part = f"lr_{stamp}"
    r.create(part, "--units", "mmns")
    request_gate(r, "datum-axis", part, "ZAXIS", {"name": "ZAXIS", "through": ["RIGHT", "TOP"]})
    ring = request_gate(
        r,
        "revolve",
        part,
        "RING",
        {
            "units": "mm",
            "name": "RING",
            "angle": 360,
            "axis": "ZAXIS",
            "sketch": {
                "plane": "RIGHT",
                "orient_ref": "TOP",
                "orient": "up",
                "profile": {"type": "circle", "diameter": 4, "center": [10, 10]},
            },
        },
    )
    torus = 2 * math.pi * 10 * math.pi * 2**2
    r.check(
        "revolve_about_an_axis_of_the_part",
        close_enough(ring["result"]["volume"]["change"], torus, rel=1e-5),
        change=ring["result"]["volume"]["change"],
        exact=torus,
    )
    # An ellipse is drawn by Java, not the native library: the same axis, the other path.
    oval = request_gate(
        r,
        "revolve",
        part,
        "OVAL",
        {
            "units": "mm",
            "name": "OVAL",
            "angle": 360,
            "axis": "ZAXIS",
            "body": "new",
            "sketch": {
                "plane": "RIGHT",
                "orient_ref": "TOP",
                "orient": "up",
                "profile": {"type": "ellipse", "x_radius": 3, "y_radius": 2, "center": [30, 30]},
            },
        },
    )
    exact = 2 * math.pi * 30 * math.pi * 3 * 2
    r.check(
        "java_drawn_profile_about_the_same_axis",
        close_enough(oval["result"]["volume"]["change"], exact, rel=1e-4),
        change=oval["result"]["volume"]["change"],
        exact=exact,
    )
    bodies = r.run("model", "show", "--model", part)["bodies"]
    r.check("revolved_into_a_body_of_its_own", len(bodies) == 2, bodies=bodies)
    r.verified("discard_ring", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")

    # A straight edge of the part as the axis: a ring turned about the top edge of a block.
    part = f"le_{stamp}"
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "BLOCK",
        {
            "depth": 5,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 10, "height": 10}},
        },
    )
    edge = next(
        e["ref"]
        for e in geometry(r, part, kind="edge")
        if e.get("direction") in ([1, 0, 0], [-1, 0, 0])
        and close_enough(e["start"][1], 5)
        and close_enough(e["start"][2], 0)
    )
    hoop = request_gate(
        r,
        "revolve",
        part,
        "HOOP",
        {
            "units": "mm",
            "name": "HOOP",
            "angle": 360,
            "axis": edge,
            "sketch": SKETCH | {"profile": {"type": "circle", "diameter": 4, "center": [0, 25]}},
        },
    )
    exact = 2 * math.pi * 20 * math.pi * 2**2
    r.check(
        "revolve_about_a_straight_edge",
        close_enough(hoop["result"]["volume"]["change"], exact, rel=1e-5),
        change=hoop["result"]["volume"]["change"],
        exact=exact,
    )
    r.verified("discard_hoop", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def outside_shell(r: Recorder, stamp: str) -> None:
    """A box whose walls grow outwards from its faces, its top left open."""
    part = f"lo_{stamp}"
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "BOX",
        {
            "depth": 20,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 40, "height": 30}},
        },
    )
    skin = request_gate(
        r,
        "shell",
        part,
        "SKIN",
        {
            "units": "mm",
            "name": "SKIN",
            "thickness": 2,
            "side": "outside",
            "remove": [face(r, part, [0, 0, 1])],
        },
    )
    walls = 44 * 34 * 22 - 40 * 30 * 20
    r.check(
        "outside_walls_around_the_old_solid",
        close_enough(skin["result"]["volume"]["after"], walls, rel=1e-6),
        after=skin["result"]["volume"]["after"],
        exact=walls,
    )
    r.verified("discard_skin", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")
    part = f"lc_{stamp}"
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "BOX",
        {
            "depth": 20,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 40, "height": 30}},
        },
    )
    closed = request_gate(
        r, "shell", part, "CLOSED", {"units": "mm", "name": "CLOSED", "thickness": 2}
    )
    inside = 36 * 26 * 16
    r.check(
        "closed_shell_hollows_the_inside",
        close_enough(closed["result"]["volume"]["change"], -inside, rel=1e-6),
        change=closed["result"]["volume"]["change"],
        exact=-inside,
    )
    r.verified("discard_closed", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def draft_part(r: Recorder, stamp: str) -> None:
    """A molded block: its walls drafted 3 degrees about its base, a pocket's walls about the
    top, each volume the frustum's to the cubic millimetre; the draft angle then edited."""
    part = f"lf_{stamp}"
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "BLOCK",
        {
            "depth": 10,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 40, "height": 20}},
        },
    )
    r.extrude(
        part,
        "POCKET",
        {
            "depth": 4,
            "material": "remove",
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 20, "height": 10}},
        },
    )
    faces = geometry(r, part, kind="surface")
    walls = [f["ref"] for f in faces if f["feature"]["name"] == "BLOCK" and f["normal"][2] == 0]
    base = next(f["ref"] for f in faces if f.get("normal") == [0, 0, -1])
    body = {"name": "WALL_DRAFT", "surfaces": walls, "hinge": base, "angle": 3}
    preview = r.run(
        "feature", "draft", "--model", part, "--request", r.request("WALL_DRAFT", body), "--dry-run"
    )["preview"]
    r.check(
        "the_pull_is_out_of_the_base",
        preview["pull"]["direction"] == [0, 0, -1],
        pull=preview["pull"],
    )
    drafted = request_gate(r, "draft", part, "WALL_DRAFT", body)

    def narrowing(angle: float, width: float, height: float, depth: float) -> float:
        # A rectangle whose sides move in by tan(angle) per unit of depth, integrated.
        k = 2 * math.tan(math.radians(angle))
        return -(width + height) * k * depth**2 / 2 + k**2 * depth**3 / 3

    expected = narrowing(3, 40, 20, 10)
    r.check(
        "walls_narrow_the_block_away_from_its_base",
        close_enough(drafted["result"]["volume"]["change"], expected, rel=1e-6),
        change=drafted["result"]["volume"]["change"],
        exact=expected,
    )
    pocket = [f["ref"] for f in faces if f["feature"]["name"] == "POCKET" and f["normal"][2] == 0]
    opened = request_gate(
        r,
        "draft",
        part,
        "POCKET_DRAFT",
        {
            "name": "POCKET_DRAFT",
            "surfaces": pocket,
            "hinge": "FRONT",
            "flip_pull": True,
            "angle": 3,
        },
    )
    expected = -narrowing(3, 20, 10, 4)
    r.check(
        "pocket_walls_open_it_toward_the_top",
        close_enough(opened["result"]["volume"]["change"], expected, rel=1e-6),
        change=opened["result"]["volume"]["change"],
        exact=expected,
    )
    dims = r.run("dimension", "list", "--model", part, "--feature", "WALL_DRAFT")["items"]
    angle = next(d for d in dims if close_enough(d["value"], 3))
    r.check(
        "the_draft_angle_is_a_dimension",
        angle["units"] in ("deg", "degree", "degrees"),
        dimension=angle,
    )
    steeper = r.verified(
        "draft_angle_changed",
        r.gate(
            "dimension",
            "set",
            "--model",
            part,
            "--dimension",
            angle["name"],
            "--value",
            5,
            "--units",
            "deg",
        ),
    )
    expected = narrowing(5, 40, 20, 10) - narrowing(3, 40, 20, 10)
    r.check(
        "a_steeper_draft_narrows_it_further",
        close_enough(steeper["result"]["volume"]["change"], expected, rel=1e-6),
        change=steeper["result"]["volume"]["change"],
        exact=expected,
    )
    r.verified("discard_draft_part", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def rib_part(r: Recorder, stamp: str) -> None:
    """An L bracket stiffened by gussets: one filled toward the inside corner on whichever side
    Creo can close, one on a datum plane of its own, thickened to one side; each exactly the
    triangle times its thickness."""
    part = f"lg_{stamp}"
    r.create(part, "--units", "mmns")
    outline = {
        "type": "outline",
        "start": [0, 0],
        "segments": [
            {"to": [60, 0]},
            {"to": [60, 8]},
            {"to": [8, 8]},
            {"to": [8, 50]},
            {"to": [0, 50]},
        ],
    }
    r.extrude(
        part, "BRACKET", {"depth": 30, "side": "symmetric", "sketch": SKETCH | {"profile": outline}}
    )
    triangle = (40 - 8) * (50 - 8) / 2
    gusset = request_gate(
        r,
        "rib",
        part,
        "GUSSET",
        {
            "units": "mm",
            "name": "GUSSET",
            "thickness": 4,
            "sketch": SKETCH | {"points": [[50, 8], [8, 40]]},
        },
    )
    r.check(
        "gusset_fills_the_inside_corner",
        close_enough(gusset["result"]["volume"]["change"], triangle * 4, rel=1e-9)
        and gusset["result"]["fill"] == "left"
        and gusset["result"]["fill_tried"] == ["right"],
        change=gusset["result"]["volume"]["change"],
        exact=triangle * 4,
        fill=gusset["result"]["fill"],
        tried_first=gusset["result"]["fill_tried"],
    )
    request_gate(
        r,
        "datum-plane",
        part,
        "RIB_PLANE",
        {"units": "mm", "name": "RIB_PLANE", "offset": {"from": "FRONT", "distance": 10}},
    )
    side = request_gate(
        r,
        "rib",
        part,
        "SIDE_GUSSET",
        {
            "units": "mm",
            "name": "SIDE_GUSSET",
            "thickness": 3,
            "side": "one",
            "fill": "right",
            "sketch": {
                "plane": "RIB_PLANE",
                "orient_ref": "RIGHT",
                "references": ["RIGHT", "TOP"],
                "points": [[8, 40], [50, 8]],
            },
        },
    )
    faces = geometry(r, part, kind="surface", feature="SIDE_GUSSET")
    depths = sorted({round(z, 9) for f in faces for z in (f["bbox"][0][2], f["bbox"][1][2])})
    r.check(
        "one_sided_gusset_against_the_plane_normal",
        close_enough(side["result"]["volume"]["change"], triangle * 3, rel=1e-9)
        and depths == [7, 10],
        change=side["result"]["volume"]["change"],
        exact=triangle * 3,
        z=depths,
    )
    dims = r.run("dimension", "list", "--model", part, "--feature", "GUSSET")["items"]
    r.check(
        "the_rib_thickness_is_a_dimension",
        any(close_enough(d["value"], 4) and not d.get("in_sketch") for d in dims),
        dimensions=[[d["name"], d["value"], d.get("in_sketch")] for d in dims],
    )
    r.verified("discard_rib_part", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def tolerance_part(r: Recorder, stamp: str) -> None:
    """A pin made to a drawing's tolerances: refused an ISO fit while ANSI, put in ISO/DIN with
    the medium general class, its diameter g6 and its length toleranced in numbers, a drawing
    that shows them, and a length made basic and then plain again."""
    part = f"lz_{stamp}"
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "PIN",
        {"depth": 40, "sketch": SKETCH | {"profile": {"type": "circle", "diameter": 20}}},
    )
    dims = r.run("dimension", "list", "--model", part, "--feature", "PIN")["items"]
    diameter = next(d for d in dims if d["type"] == "diameter")
    length = next(d for d in dims if close_enough(d["value"], 40))
    r.check("a_new_dimension_has_no_tolerance", diameter["tolerance"] == {"type": "nominal"})
    refused = r.run(
        "dimension",
        "tolerance",
        "--model",
        part,
        "--dimension",
        diameter["name"],
        "--fit",
        "g6",
        "--dry-run",
        expect=6,
    )
    r.check(
        "a_fit_needs_the_iso_standard",
        refused["code"] == "E_CONFLICT" and "set-tolerance-standard" in refused["details"]["fix"],
    )
    iso = r.verified(
        "iso_standard",
        r.gate(
            "model",
            "set-tolerance-standard",
            "--model",
            part,
            "--standard",
            "iso",
            "--class",
            "medium",
        ),
    )
    r.check(
        "iso_medium_read_back",
        (iso["result"]["standard"], iso["result"]["class"]) == ("iso", "medium")
        and iso["result"]["standard_before"] == "ansi",
        result=iso["result"],
    )
    fit = r.verified(
        "diameter_g6",
        r.gate(
            "dimension",
            "tolerance",
            "--model",
            part,
            "--dimension",
            diameter["name"],
            "--fit",
            "g6",
        ),
    )
    read = fit["result"]["dimension"]["tolerance"]
    r.check(
        "g6_limits_from_creo_tables",
        read["fit"] == "g6"
        and close_enough(read["upper"], 19.993, rel=1e-12)
        and close_enough(read["lower"], 19.98, rel=1e-12),
        tolerance=read,
    )
    shown = r.verified(
        "length_plus_minus",
        r.gate(
            "dimension",
            "tolerance",
            "--model",
            part,
            "--dimension",
            length["name"],
            "--plus",
            0.021,
            "--minus",
            0,
            "--units",
            "mm",
        ),
    )
    r.check(
        "three_places_shown_for_a_three_place_tolerance",
        shown["result"]["tolerance_decimals"] == 3,
        places=shown["result"]["tolerance_decimals"],
    )
    drawing = r.verified(
        "tolerance_drawing",
        r.gate("drawing", "create", "--name", part, "--of", part, "--sheet", "a3"),
    )
    r.opened.append(part + ".drw")
    r.verified("tolerance_annotate", r.gate("drawing", "annotate", "--model", part))
    rows = {d["name"]: d for d in r.run("model", "show", "--model", part + ".drw")["dimensions"]}
    r.check(
        "the_drawing_carries_the_tolerances",
        rows[diameter["name"]]["tolerance"]["fit"] == "g6"
        and rows[length["name"]]["tolerance"]["type"] == "plus_minus",
        views=len(drawing["result"]["views"]),
    )
    r.verified(
        "length_basic",
        r.gate("dimension", "tolerance", "--model", part, "--dimension", length["name"], "--basic"),
    )
    r.verified(
        "length_nominal",
        r.gate(
            "dimension", "tolerance", "--model", part, "--dimension", length["name"], "--nominal"
        ),
    )
    r.verified(
        "discard_tolerance_drawing",
        r.gate("model", "discard", "--model", part + ".drw", "--dangerous"),
    )
    r.opened.remove(part + ".drw")
    r.verified("discard_tolerance_part", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def fastener_holes(r: Recorder, stamp: str) -> None:
    """The holes screws need, in a 20 mm plate: tapped M8 blind and M6 through, a counterbored
    clearance for an M6 head and a countersink by hand -- each volume the drilled shape's."""
    part = f"lm_{stamp}"
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "PLATE",
        {
            "depth": 20,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 80, "height": 40}},
        },
    )
    top = face(r, part, [0, 0, 1])

    def place(x):
        return {
            "surface": top,
            "offsets": [{"from": "RIGHT", "distance": x}, {"from": "TOP", "distance": 10}],
        }

    for name, body, exact in (
        (
            "TAP_M8",
            {"thread": {"size": "M8x1.25", "depth": 12}, "depth": 16},
            math.pi * 3.4**2 * 16 + math.pi * 3.4**2 * (3.4 / math.tan(math.radians(59))) / 3,
        ),
        ("TAP_M6", {"thread": {"size": "M6x1"}, "depth": "through_all"}, math.pi * 2.5**2 * 20),
        (
            "CBORE_M6",
            {
                # M6 as a person names it: the coarse thread, the chart's M6x1.
                "clearance": {"size": "M6", "fit": "medium"},
                "counterbore": True,
                "depth": "through_all",
            },
            math.pi * 3.3**2 * 14 + math.pi * 5.6**2 * 6,
        ),
        (
            "CSINK",
            {"diameter": 4.5, "countersink": {"diameter": 9, "angle": 90}, "depth": 10},
            math.pi * 2.25**2 * 10
            + math.pi * 2.25**2 * (2.25 / math.tan(math.radians(59))) / 3
            + math.pi * 2.25 / 3 * (4.5**2 + 4.5 * 2.25 + 2.25**2)
            - math.pi * 2.25**2 * 2.25,
        ),
    ):
        x = {"TAP_M8": -30, "TAP_M6": -10, "CBORE_M6": 10, "CSINK": 30}[name]
        made = request_gate(
            r, "hole", part, name, {"units": "mm", "name": name, **body, "placement": place(x)}
        )
        r.check(
            f"{name.lower()}_removes_its_drilled_shape",
            # Measured: a drill point's cone comes back within 2e-6 of the formula, not 1e-9.
            close_enough(made["result"]["volume"]["change"], -exact, rel=1e-5),
            change=made["result"]["volume"]["change"],
            exact=-exact,
            drill=made["result"].get("drill_diameter"),
        )
    refused = r.run(
        "feature",
        "hole",
        "--model",
        part,
        "--request",
        r.request(
            "NO_SUCH",
            {
                "units": "mm",
                "thread": {"size": "M6x9"},
                "depth": "through_all",
                "placement": place(0),
            },
        ),
        "--dry-run",
        expect=2,
    )
    r.check("a_size_the_chart_lacks_is_refused", refused["code"] == "E_VALIDATION")
    r.verified("discard_fastener_holes", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def threaded_shaft(r: Recorder, stamp: str) -> None:
    """A shaft threaded M10 at one end and tapped M10 at the other: the thread at its minor
    diameter on the shaft and its major one in the bore, each to its depth, nothing removed."""
    part = f"ln_{stamp}"
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "SHAFT",
        {"depth": 40, "sketch": SKETCH | {"profile": {"type": "circle", "diameter": 10}}},
    )
    faces = geometry(r, part, kind="surface")
    shaft = next(f["ref"] for f in faces if f.get("type") == "cylinder")
    end = face(r, part, [0, 0, 1])
    far = face(r, part, [0, 0, -1])
    request_gate(
        r,
        "hole",
        part,
        "TAP_DRILL",
        {
            "units": "mm",
            "name": "TAP_DRILL",
            "diameter": 8.5,
            "depth": 12,
            "placement": {
                "surface": far,
                "offsets": [{"from": "RIGHT", "distance": 0}, {"from": "TOP", "distance": 0}],
            },
        },
    )
    bore = next(
        f["ref"]
        for f in geometry(r, part, kind="surface")
        if f.get("type") == "cylinder" and close_enough(f.get("radius") or 0, 4.25)
    )
    outside = request_gate(
        r,
        "thread",
        part,
        "END_THREAD",
        {
            "units": "mm",
            "name": "END_THREAD",
            "surface": shaft,
            "start": end,
            "size": "M10x1.5",
            "depth": 15,
        },
    )
    r.check(
        "the_shaft_thread_at_its_minor_diameter",
        outside["result"]["external"] is True
        and close_enough(outside["result"]["diameter"], 10 - 1.082532 * 1.5, rel=1e-9),
        diameter=outside["result"]["diameter"],
    )
    texts = [
        d.get("text")
        for d in r.run("dimension", "list", "--model", part, "--feature", "END_THREAD")["items"]
    ]
    r.check(
        "the_thread_called_out_as_the_chart_names_it",
        outside["result"]["callout"] == "M10x1.5" and any(t and "M10x1.5" in t for t in texts),
        callout=outside["result"]["callout"],
        texts=texts,
    )
    inside = request_gate(
        r,
        "thread",
        part,
        "TAPPED",
        {
            "units": "mm",
            "name": "TAPPED",
            "surface": bore,
            "start": far,
            "size": "M10x1.5",
            "depth": 10,
        },
    )
    r.check(
        "the_bore_thread_at_its_major_diameter",
        inside["result"]["external"] is False and close_enough(inside["result"]["diameter"], 10.0),
        diameter=inside["result"]["diameter"],
    )
    r.verified("discard_threaded_shaft", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def grid_and_bodies(r: Recorder, stamp: str) -> None:
    """A plate's holes in a grid of two rows of four; the preview saying where the plate
    goes before it is built; a second body, with the part's faces still listed; the part
    saved, closed and opened again by its name alone."""
    part = f"lj_{stamp}"
    r.create(part, "--units", "mmns")
    plate = {
        "units": "mm",
        "name": "PLATE",
        "depth": 10,
        "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 80, "height": 40}},
    }
    preview = r.run(
        "feature", "extrude", "--model", part, "--request", r.request("PLATE", plate), "--dry-run"
    )["preview"]
    r.check(
        "the_preview_says_where_the_plate_goes",
        preview["model_box"] == [[-40, -20, -10], [40, 20, 0]]
        and preview["extrudes_toward"] == [0, 0, -1],
        box=preview["model_box"],
        frame=preview["sketch"]["frame"],
    )
    r.extrude(part, "PLATE", plate)
    top = face(r, part, [0, 0, 1])
    request_gate(
        r,
        "hole",
        part,
        "H1",
        {
            "units": "mm",
            "name": "H1",
            "diameter": 6,
            "depth": "through_all",
            "placement": {
                "surface": top,
                "offsets": [{"from": "RIGHT", "distance": 30}, {"from": "TOP", "distance": 12}],
            },
        },
    )
    grid = request_gate(
        r,
        "pattern",
        part,
        "GRID",
        {
            "units": "mm",
            "name": "GRID",
            "feature": "H1",
            "direction": {"along": "RIGHT", "spacing": -20, "count": 4},
            "direction2": {"along": "TOP", "spacing": -24, "count": 2},
        },
    )
    after = r.run("model", "show", "--model", part)["mass_properties"]["volume"]
    exact = 80 * 40 * 10 - 8 * math.pi * 3**2 * 10
    r.check(
        "eight_holes_in_the_grid",
        len(grid["result"]["members"]) == 8 and close_enough(after, exact, rel=1e-6),
        volume=after,
        exact=exact,
    )
    r.extrude(
        part,
        "LUG",
        {
            "depth": 5,
            "body": "new",
            "sketch": SKETCH | {"profile": {"type": "circle", "diameter": 10, "center": [60, 0]}},
        },
    )
    faces = geometry(r, part, kind="surface")
    r.check(
        "a_part_of_two_bodies_lists_its_faces",
        any(f["feature"]["name"] == "LUG" for f in faces)
        and any(f["feature"]["name"] == "PLATE" for f in faces),
        faces=len(faces),
    )
    kinds = {m["type"] for m in r.run("model", "list")["items"]}
    r.check(
        "only_models_a_person_opened_are_listed",
        kinds <= {"part", "assembly", "drawing"},
        kinds=sorted(kinds),
    )
    r.verified("save_grid", r.gate("model", "save", "--model", part))
    r.verified("close_grid", r.gate("model", "close", "--model", part))
    r.opened.remove(part + ".prt")
    r.verified("open_by_name", r.gate("model", "open", "--path", str(r.run_dir / (part + ".prt"))))
    r.opened.append(part + ".prt")
    r.verified("discard_grid", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def face_sketches(r: Recorder, stamp: str) -> None:
    """Sketches on the faces of a block, as a person clicks a face: a boss on the top and a
    slot cut into a side, each in the box its preview said, to the cubic millimetre."""
    part = f"lfs_{stamp}"
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "BLOCK",
        {
            "depth": 10,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 40, "height": 20}},
        },
    )
    top = face(r, part, [0, 0, 1])
    side = face(r, part, [1, 0, 0])
    for name, body, box, volume in (
        (
            "BOSS",
            {
                "depth": 5,
                "side": "two",
                "sketch": {
                    "plane": top,
                    "orient_ref": "RIGHT",
                    "profile": {"type": "circle", "diameter": 10, "center": [5, 0]},
                },
            },
            [[0, -5, 0], [10, 5, 5]],
            math.pi * 25 * 5,
        ),
        (
            "SLOT",
            {
                "depth": 3,
                "material": "remove",
                "sketch": {
                    "plane": side,
                    "orient_ref": "FRONT",
                    "orient": "up",
                    "profile": {"type": "rectangle", "width": 8, "height": 4, "center": [0, -5]},
                },
            },
            [[17, -4, -7], [20, 4, -3]],
            -96.0,
        ),
    ):
        request = {"units": "mm", "name": name, **body}
        preview = r.run(
            "feature",
            "extrude",
            "--model",
            part,
            "--request",
            r.request(name, request),
            "--dry-run",
        )["preview"]
        made = r.extrude(part, name, body)
        faces = geometry(r, part, kind="surface", feature=name)
        # Creo's box of a cylinder is a little loose; a flat-sided cut's is exact.
        lo = [min(f["bbox"][0][k] for f in faces) for k in range(3)]
        hi = [max(f["bbox"][1][k] for f in faces) for k in range(3)]
        r.check(
            f"{name.lower()}_where_the_preview_said",
            preview["model_box"] == box
            and all(abs(a - b) <= 0.05 for a, b in zip(lo + hi, box[0] + box[1], strict=True))
            and close_enough(made["result"]["volume"]["change"], volume, rel=1e-9),
            preview=preview["model_box"],
            actual=[lo, hi],
            change=made["result"]["volume"]["change"],
        )
    r.verified("discard_face_sketches", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def swept_parts(r: Recorder, stamp: str) -> None:
    """Sweeps as a person makes them: a pipe bent through a quarter turn, a bar along a bend
    with its section off to one side, a groove swept along the top of a block -- each where
    its preview said, to Pappus' volume: exactly for a flat-sided section, to Creo's 1e-3
    for a round one."""
    pipe = f"lsw_{stamp}"
    r.create(pipe, "--units", "mmns")
    body = {
        "units": "mm",
        "name": "PIPE",
        "path": SKETCH
        | {
            "start": [0, 0],
            "segments": [{"to": [0, 40]}, {"to": [20, 60], "sweep": -90}, {"to": [60, 60]}],
        },
        "section": {"type": "circle", "diameter": 10},
    }
    preview = r.run(
        "feature", "sweep", "--model", pipe, "--request", r.request("PIPE", body), "--dry-run"
    )["preview"]
    made = request_gate(r, "sweep", pipe, "PIPE", body)
    exact = math.pi * 25 * (80 + 10 * math.pi)
    r.check(
        "pipe_as_previewed",
        preview["path"]["starts_at"] == [0, 0, 0]
        and preview["path"]["ends_at"] == [60, 60, 0]
        and preview["section"]["frame"]["x"] == [-1, 0, 0]
        and preview["section"]["frame"]["y"] == [0, 0, 1]
        and made["result"]["path"]["name"] == "PIPE_PATH"
        and made["result"]["path"]["creo_runs_from"] == "end"
        and made["result"]["path"]["dimension_plan"] == "kept"
        and any(
            d["measures"].startswith("radius of the arc")
            for d in made["result"]["path"]["dimensions"]
        )
        and close_enough(made["result"]["volume"]["change"], exact, rel=2e-3),
        path=made["result"]["path"],
        change=made["result"]["volume"]["change"],
        pappus=exact,
    )
    r.verified("discard_pipe", r.gate("model", "discard", "--model", pipe, "--dangerous"))
    r.opened.remove(pipe + ".prt")

    bar = f"lsb_{stamp}"
    r.create(bar, "--units", "mmns")
    body = {
        "units": "mm",
        "name": "BAR",
        "path": SKETCH
        | {
            "start": [0, 0],
            "segments": [{"to": [0, 20]}, {"to": [20, 40], "sweep": -90}, {"to": [40, 40]}],
        },
        "section": {"type": "rectangle", "width": 2, "height": 3, "center": [4, 1]},
    }
    made = request_gate(r, "sweep", bar, "BAR", body)
    # Left of a path that turns right, the section travels the outside of the bend: its
    # centroid 4 out, a quarter turn.
    exact = 6 * (40 + 10 * math.pi + 4 * math.pi / 2)
    faces = geometry(r, bar, kind="surface", feature="BAR")
    lo = [min(f["bbox"][0][k] for f in faces) for k in range(3)]
    hi = [max(f["bbox"][1][k] for f in faces) for k in range(3)]
    box = [[-5, 0, -0.5], [40, 45, 2.5]]
    r.check(
        "bar_off_to_the_left_exactly",
        close_enough(made["result"]["volume"]["change"], exact, rel=1e-9)
        and all(abs(a - b) <= 0.05 for a, b in zip(lo + hi, box[0] + box[1], strict=True)),
        change=made["result"]["volume"]["change"],
        pappus=exact,
        box=[lo, hi],
        expected_box=box,
    )
    r.verified("discard_bar", r.gate("model", "discard", "--model", bar, "--dangerous"))
    r.opened.remove(bar + ".prt")

    block = f"lsg_{stamp}"
    r.create(block, "--units", "mmns")
    r.extrude(
        block,
        "BLOCK",
        {
            "depth": 20,
            "side": "two",
            "sketch": {
                "plane": "TOP",
                "orient_ref": "RIGHT",
                "profile": {"type": "rectangle", "width": 100, "height": 60},
            },
        },
    )
    top = face(r, block, [0, 1, 0])
    body = {
        "units": "mm",
        "name": "GROOVE",
        "material": "remove",
        "path": {
            "plane": top,
            "orient_ref": "RIGHT",
            "start": [-40, -10],
            "segments": [{"to": [0, -10]}, {"to": [20, 10], "sweep": 90}, {"to": [20, 25]}],
        },
        "section": {"type": "circle", "diameter": 6},
    }
    preview = r.run(
        "feature", "sweep", "--model", block, "--request", r.request("GROOVE", body), "--dry-run"
    )["preview"]
    made = request_gate(r, "sweep", block, "GROOVE", body)
    # Centred on the top face, half the circle is in the block: half its area along the path.
    removed = math.pi * 9 / 2 * (55 + 10 * math.pi)
    r.check(
        "groove_half_in_the_block",
        preview["path"]["starts_at"] == [-40, 20, 10]
        and made["result"]["feature"]["type"] == "FEATTYPE_CUT"
        and made["result"]["path"]["creo_runs_from"] == "start"
        and close_enough(made["result"]["volume"]["change"], -removed, rel=2e-3),
        starts_at=preview["path"]["starts_at"],
        change=made["result"]["volume"]["change"],
        half_the_circle=-removed,
    )
    r.verified("discard_groove", r.gate("model", "discard", "--model", block, "--dangerous"))
    r.opened.remove(block + ".prt")


def family_parts(r: Recorder, stamp: str) -> None:
    """A pin made in three sizes by a family table: two instances, one longer, one thinner and
    longer without its head, each made and read back to its volume exactly; the thin one
    opened from its generic as File > Open asks which, exported, and put in the generic's
    place on a plate by the same constraints, then moved up out of it in an exploded state
    and drawn so; the other removed."""
    part = f"lfm_{stamp}"
    (r.run_dir / "exports").mkdir(exist_ok=True)
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "SHANK",
        {"depth": 20, "sketch": SKETCH | {"profile": {"type": "circle", "diameter": 8}}},
    )
    r.extrude(
        part,
        "HEAD",
        {
            "depth": 4,
            "side": "two",
            "sketch": SKETCH | {"profile": {"type": "circle", "diameter": 12}},
        },
    )
    r.verified(
        "pin_description",
        r.gate(
            "parameter",
            "set",
            "--model",
            part,
            "--name",
            "DESCRIPTION",
            "--type",
            "string",
            "--value",
            "PIN 8x20",
            "--create",
        ),
    )
    dims = r.run("dimension", "list", "--model", part, "--feature", "SHANK")["items"]
    depth = next(d["name"] for d in dims if d.get("type") == "linear" and d["value"] == 20)
    diameter = next(d["name"] for d in dims if d.get("type") == "diameter" and d["value"] == 8)
    body = {
        "units": "mm",
        "instances": [
            {
                "name": "PIN_8X30",
                "values": {f"dimension:{depth}": 30, "parameter:DESCRIPTION": "PIN 8x30"},
            },
            {
                "name": "PIN_6X40",
                "values": {
                    f"dimension:{depth}": 40,
                    f"dimension:{diameter}": 6,
                    "feature:HEAD": False,
                    "parameter:DESCRIPTION": "PIN 6x40",
                },
            },
        ],
    }
    made = r.verified(
        "pin_family",
        r.gate("family", "set", "--model", part, "--request", r.request("PIN_FAMILY", body)),
    )
    volumes = {c["name"]: c["volume"] for c in made["result"]["checked"]}
    head = math.pi * 36 * 4
    r.check(
        "instances_to_their_volumes",
        close_enough(volumes.get("PIN_8X30"), math.pi * 16 * 30 + head, rel=1e-6)
        and close_enough(volumes.get("PIN_6X40"), math.pi * 9 * 40, rel=1e-6)
        and sorted(made["result"]["columns_added"])
        == sorted(
            [f"dimension:{depth}", f"dimension:{diameter}", "feature:HEAD", "parameter:DESCRIPTION"]
        ),
        volumes=volumes,
        columns_added=made["result"]["columns_added"],
    )
    shown = r.run("family", "show", "--model", part)
    r.check(
        "table_as_set",
        [i["name"] for i in shown["instances"]] == ["PIN_8X30", "PIN_6X40"]
        and len(shown["columns"]) == 4
        and shown["generic"] is None,
        instances=[i["name"] for i in shown["instances"]],
    )
    r.verified("save_pin", r.gate("model", "save", "--model", part))
    opened = r.verified(
        "open_pin_6x40",
        r.gate(
            "model", "open", "--path", str(r.run_dir / (part + ".prt")), "--instance", "PIN_6X40"
        ),
    )
    r.opened.append("pin_6x40.prt")
    r.check(
        "instance_from_its_generic",
        opened["result"]["family"]["generic"] == part + ".prt"
        and close_enough(opened["result"]["mass_properties"]["volume"], math.pi * 9 * 40, rel=1e-6),
        family=opened["result"]["family"],
        volume=opened["result"]["mass_properties"]["volume"],
    )
    exported = r.verified(
        "export_pin_6x40",
        r.gate(
            "model",
            "export",
            "--model",
            "pin_6x40",
            "--output",
            r.run_dir / "exports" / "pin_6x40.stp",
        ),
    )
    r.check(
        "instance_exported",
        Path(exported["result"]["file"]).is_file(),
        file=exported["result"]["file"],
    )
    # The generic on a plate, then the thin long one in its place by the same constraints.
    plate, rig = f"lfp_{stamp}", f"lfa_{stamp}"
    r.create(plate, "--units", "mmns")
    r.extrude(
        plate,
        "PLATE",
        {
            "depth": 10,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 60, "height": 40}},
        },
    )
    r.verified("create_rig", r.gate("assembly", "create", "--name", rig, "--units", "mmns"))
    r.opened.append(rig + ".asm")
    r.verified(
        "rig_plate",
        r.gate(
            "assembly",
            "add",
            "--model",
            rig,
            "--component",
            plate,
            "--request",
            r.request("rig_default", {"constraints": [{"type": "default"}]}),
        ),
    )
    shank_end = next(
        f["ref"]
        for f in geometry(r, part, kind="surface", feature="SHANK")
        if f.get("normal") == [0, 0, -1]
    )
    stood = r.verified(
        "rig_pin",
        r.gate(
            "assembly",
            "add",
            "--model",
            rig,
            "--component",
            part,
            "--request",
            r.request(
                "rig_place",
                {
                    "constraints": [
                        {
                            "type": "mate",
                            "assembly_ref": f"{face(r, plate, [0, 0, 1])}@{plate}",
                            "component_ref": shank_end,
                        },
                        {"type": "align", "assembly_ref": "ASM_RIGHT", "component_ref": "RIGHT"},
                        {"type": "align", "assembly_ref": "ASM_TOP", "component_ref": "TOP"},
                    ]
                },
            ),
        ),
    )
    pin_id = stood["result"]["component"]["id"]
    swapped = r.verified(
        "replace_with_pin_6x40",
        r.gate("assembly", "replace", "--model", rig, "--component", pin_id, "--with", "pin_6x40"),
    )
    change = math.pi * 9 * 40 - (math.pi * 16 * 20 + head)
    r.check(
        "pin_6x40_where_the_generic_stood",
        stood["result"]["component"]["position"]["origin"] == [0, 0, 20]
        and swapped["result"]["component"]["position"]["origin"] == [0, 0, 40]
        and swapped["result"]["replaced"] == part + ".prt"
        and close_enough(swapped["result"]["volume"]["change"], change, rel=1e-6),
        position=swapped["result"]["component"]["position"],
        change=swapped["result"]["volume"]["change"],
        exact=change,
    )
    # The pin moved up out of the plate, and drawn so beside the assembled side view.
    r.verified(
        "explode_rig",
        r.gate(
            "assembly",
            "explode",
            "--model",
            rig,
            "--request",
            r.request(
                "APART",
                {
                    "units": "mm",
                    "name": "APART",
                    "moves": [{"components": [pin_id], "direction": [0, 0, 1], "distance": 50}],
                },
            ),
        ),
    )
    for model, described in ((plate, "合页底板"), ("pin_6x40", "销 6x40")):
        r.verified(
            "describe_" + model,
            r.gate("model", "set-common-name", "--model", model, "--name", described),
        )
    drawn = r.verified(
        "rig_drawing",
        r.gate(
            "drawing",
            "create",
            "--name",
            rig,
            "--of",
            rig + ".asm",
            "--sheet",
            "a3",
            "--views",
            "template",
            "--scale",
            "1:1",
        ),
    )
    r.check(
        "rig_drawn_at_the_planned_scale",
        (drawn["result"].get("scale_chosen") or {}).get("label") == "1:1",
        scale=drawn["result"].get("scale_chosen"),
    )
    r.opened.append(rig + ".drw")
    sides = {}
    for view, x, flags in (("SIDE", 100, ()), ("APART", 300, ("--exploded",))):
        added = r.verified(
            "rig_view_" + view.lower(),
            r.gate(
                "drawing",
                "add-view",
                "--model",
                rig,
                "--type",
                "general",
                "--orientation",
                "right",
                "--x",
                x,
                "--y",
                120,
                "--name",
                view,
                "--scale",
                1,
                *flags,
            ),
        )
        box = added["result"]["view"]["outline"]
        sides[view] = box[1][0] - box[0][0]
        off = next(
            o for o in added["verification"]["observations"] if o["observation"] == "off_the_sheet"
        )
        r.check(f"rig_view_{view.lower()}_on_the_sheet", off["off"] is False, off=off)
    r.check(
        "exploded_view_apart_by_the_move",
        abs(sides["APART"] - sides["SIDE"] - 50) <= 0.5,
        widths=sides,
    )
    listed = r.verified(
        "rig_parts_list", r.gate("drawing", "add-bom", "--model", rig, "--x", 198, "--y", 80)
    )["result"]["table"]
    described = {row[1]: row[3] for row in listed["cells"][1:]}
    r.check(
        "parts_list_describes_by_common_name",
        described.get(plate.upper()) == "合页底板" and described.get("PIN_6X40") == "销 6x40",
        described=described,
    )
    r.verified(
        "discard_rig_drawing", r.gate("model", "discard", "--model", rig + ".drw", "--dangerous")
    )
    r.opened.remove(rig + ".drw")
    r.verified("discard_rig", r.gate("model", "discard", "--model", rig + ".asm", "--dangerous"))
    r.opened.remove(rig + ".asm")
    r.verified("discard_plate", r.gate("model", "discard", "--model", plate, "--dangerous"))
    r.opened.remove(plate + ".prt")
    r.verified(
        "remove_pin_8x30",
        r.gate("family", "remove", "--model", part, "--instance", "PIN_8X30", "--dangerous"),
    )
    r.verified("discard_pin_6x40", r.gate("model", "discard", "--model", "pin_6x40", "--dangerous"))
    r.opened.remove("pin_6x40.prt")
    r.verified("discard_pin", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def drafted_sketches(r: Recorder, stamp: str) -> None:
    """A stepped shaft whose sketch is dimensioned as a drafter would: each journal by its
    diameter, each shoulder by its distance from the end. Setting one shoulder moves that
    shoulder alone -- auto-dimensioning alone held the two 30-long journals to one length --
    and a rectangle set wider stays centred."""
    part = f"lds_{stamp}"
    r.create(part, "--units", "mmns")
    half = {
        "type": "outline",
        "start": [0, 0],
        "segments": [
            {"to": [0, 10]},
            {"to": [30, 10]},
            {"to": [30, 12.5]},
            {"to": [80, 12.5]},
            {"to": [80, 10]},
            {"to": [109, 10]},
            {"to": [110, 9]},
            {"to": [110, 0]},
        ],
    }
    body = {
        "units": "mm",
        "name": "BODY",
        "angle": 360,
        "axis": [[0, 0], [1, 0]],
        "sketch": SKETCH | {"profile": half},
    }
    made = request_gate(r, "revolve", part, "BODY", body)["result"]
    dims = made["sketch_dimensions"]
    said = {d["measures"]: d for d in dims}
    journal = said.get("diameter of the edge from (0, 10) to (30, 10), across the axis")
    shoulder = said.get("distance from RIGHT to the edge from (30, 10) to (30, 12.5)")
    r.check(
        "sketch_dimensioned_as_drafted",
        made["dimension_plan"] == "kept"
        and all(d["by"] == "cli" for d in dims)
        and journal is not None
        and journal["value"] == 20
        and shoulder is not None
        and shoulder["value"] == 30
        and not made["held_together"],
        dimensions=[[d["name"], d["value"], d["measures"]] for d in dims],
    )
    listed = r.run("dimension", "list", "--model", part, "--feature", "BODY")["items"]
    read = {d["name"]: d.get("measures") for d in listed}
    r.check(
        "dimension_list_says_what_each_measures",
        read.get(shoulder["name"]) == shoulder["measures"]
        and read.get(journal["name"]) == journal["measures"],
        read=read,
    )
    moved = r.verified(
        "shoulder_moved",
        r.gate(
            "dimension",
            "set",
            "--model",
            part,
            "--dimension",
            shoulder["name"],
            "--value",
            35,
            "--units",
            "mm",
        ),
    )
    alone = -math.pi * (12.5**2 - 10**2) * 5
    r.check(
        "one_shoulder_moves_alone",
        close_enough(moved["result"]["volume"]["change"], alone, rel=1e-6),
        change=moved["result"]["volume"]["change"],
        expected=alone,
    )
    wider = r.verified(
        "journal_widened",
        r.gate(
            "dimension",
            "set",
            "--model",
            part,
            "--dimension",
            journal["name"],
            "--value",
            22,
            "--units",
            "mm",
        ),
    )
    grown = math.pi * (11**2 - 10**2) * 35
    r.check(
        "one_journal_grows_alone",
        close_enough(wider["result"]["volume"]["change"], grown, rel=1e-6),
        change=wider["result"]["volume"]["change"],
        expected=grown,
    )
    r.verified("discard_drafted_shaft", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")

    plate = f"ldr_{stamp}"
    r.create(plate, "--units", "mmns")
    block = r.extrude(
        plate,
        "PLATE",
        {
            "depth": 10,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 40, "height": 20}},
        },
    )["result"]
    width = next(
        d
        for d in block["sketch_dimensions"]
        if d["measures"] == "width of the rectangle centred at (0, 0)"
    )
    r.verified(
        "plate_widened",
        r.gate(
            "dimension",
            "set",
            "--model",
            plate,
            "--dimension",
            width["name"],
            "--value",
            48,
            "--units",
            "mm",
        ),
    )
    sides = sorted(
        s["origin"][0]
        for s in geometry(r, plate, kind="surface")
        if s.get("normal") in ([1, 0, 0], [-1, 0, 0])
    )
    r.check(
        "a_rectangle_widens_about_its_centre",
        len(sides) == 2 and close_enough(sides[0], -24) and close_enough(sides[1], 24),
        sides=sides,
    )
    r.verified("discard_drafted_plate", r.gate("model", "discard", "--model", plate, "--dangerous"))
    r.opened.remove(plate + ".prt")


def cast_housing(r: Recorder, stamp: str) -> None:
    """A cast housing as a person models one: a block, shelled open at the bottom, its walls
    drafted for the mould, and a rib across the inside whose chain stops short of the walls
    -- carried along to the drafted faces, where Creo needs its ends."""
    part = f"lch_{stamp}"
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "BLOCK",
        {
            "depth": 40,
            "sketch": {
                "plane": "TOP",
                "orient_ref": "RIGHT",
                "profile": {"type": "rectangle", "width": 120, "height": 80},
            },
        },
    )
    upright = [
        e["ref"]
        for e in geometry(r, part, kind="edge")
        if e.get("direction") in ([0, 1, 0], [0, -1, 0])
    ]
    request_gate(
        r,
        "round",
        part,
        "CORNERS",
        {"units": "mm", "name": "CORNERS", "radius": 10, "edges": upright},
    )
    bottom = [
        f["ref"]
        for f in geometry(r, part, kind="surface")
        if f.get("type") == "plane" and f.get("normal") == [0, -1, 0]
    ]
    request_gate(
        r,
        "shell",
        part,
        "WALLS",
        {"units": "mm", "name": "WALLS", "thickness": 3, "remove": bottom},
    )
    request_gate(
        r,
        "datum-plane",
        part,
        "PARTING",
        {"units": "mm", "name": "PARTING", "offset": {"from": "TOP", "distance": -40}},
    )
    walls = [
        f["ref"]
        for f in geometry(r, part, kind="surface")
        if (
            f.get("type") == "plane"
            and f.get("normal") in ([1, 0, 0], [-1, 0, 0], [0, 0, 1], [0, 0, -1])
        )
        or (f.get("type") == "cylinder" and close_enough(f.get("radius") or 0, 10))
    ]
    request_gate(
        r,
        "draft",
        part,
        "WALL_DRAFT",
        {
            "name": "WALL_DRAFT",
            "surfaces": walls,
            "hinge": "PARTING",
            "angle": 1,
            "flip_pull": True,
        },
    )
    rib = {
        "units": "mm",
        "name": "RIB",
        "thickness": 3,
        "sketch": {"plane": "RIGHT", "orient_ref": "TOP", "points": [[-15, -37], [-15, 37]]},
    }
    preview = r.run(
        "feature", "rib", "--model", part, "--request", r.request("RIB", rib), "--dry-run"
    )["preview"]
    lean = 37 + math.tan(math.radians(1)) * 25
    carried = preview["ends_carried"]
    r.check(
        "the_rib_carried_to_the_drafted_walls",
        len(carried) == 2
        and all(close_enough(abs(c["drawn"][1]), lean, rel=1e-6) for c in carried)
        and all(close_enough(c["drawn"][0], -15, rel=1e-9) for c in carried),
        carried=carried,
        expected=lean,
    )
    made = request_gate(r, "rib", part, "RIB", rib)
    r.check(
        "the_rib_fills_to_the_top",
        made["result"]["volume"]["change"] > 0,
        change=made["result"]["volume"]["change"],
    )
    r.verified("discard_housing", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def drafted_drawing(r: Recorder, stamp: str) -> None:
    """A stepped shaft drawn as a drafter draws it: views in lines whatever the session
    shows, scales labelled 2:1, a section through the shaft showing only its cut face and
    lettered A-A, a detail ringed at the rim of its end, and no dimension of a datum or of the
    revolve's full turn on the sheet."""
    part = f"ldd_{stamp}"
    r.create(part, "--units", "mmns")
    half = {
        "type": "outline",
        "start": [0, 0],
        "segments": [
            {"to": [0, 10]},
            {"to": [30, 10]},
            {"to": [30, 12.5]},
            {"to": [80, 12.5]},
            {"to": [80, 10]},
            {"to": [109, 10]},
            {"to": [110, 9]},
            {"to": [110, 0]},
        ],
    }
    request_gate(
        r,
        "revolve",
        part,
        "BODY",
        {
            "units": "mm",
            "name": "BODY",
            "angle": 360,
            "axis": [[0, 0], [1, 0]],
            "sketch": SKETCH | {"profile": half},
        },
    )
    request_gate(
        r,
        "datum-plane",
        part,
        "CUT",
        {"units": "mm", "name": "CUT", "offset": {"from": "RIGHT", "distance": 55}},
    )
    made = r.verified(
        "drafted_drawing",
        r.gate("drawing", "create", "--name", part, "--of", part, "--sheet", "a3"),
    )
    r.opened.append(part + ".drw")
    r.check(
        "drawn_in_lines_with_ratio_scales",
        {v["display"] for v in made["result"]["views"]} == {"lines"}
        and str(made["result"]["scale_labels"]).lower() == "ratio_colon",
        views=[[v["name"], v["display"]] for v in made["result"]["views"]],
        scale_labels=made["result"]["scale_labels"],
    )
    for view in reversed([v["name"] for v in made["result"]["views"]]):
        r.verified(
            "remove_" + view.lower(),
            r.gate("drawing", "remove", "--model", part + ".drw", "--item", "view:" + view),
        )
    front = r.verified(
        "drafted_front",
        r.gate(
            "drawing",
            "add-view",
            "--model",
            part + ".drw",
            "--type",
            "general",
            "--orientation",
            "front",
            "--x",
            150,
            "--y",
            190,
            "--scale",
            2,
        ),
    )
    r.check("named_after_its_orientation", front["result"]["view"]["name"] == "FRONT")
    cut = r.verified(
        "drafted_section",
        r.gate(
            "drawing",
            "add-view",
            "--model",
            part + ".drw",
            "--type",
            "projection",
            "--parent",
            "FRONT",
            "--x",
            330,
            "--y",
            190,
            "--plane",
            "CUT",
            "--edges",
            "area",
        ),
    )
    notes = r.run("model", "show", "--model", part + ".drw")["notes"]
    r.check(
        "the_cut_face_section_is_lettered",
        cut["result"]["view"]["name"] == "SECTION_A"
        and cut["result"]["section"]["edges"] == "area"
        and any("A-A" in n["text"] or "xsec_name" in n["text"] for n in notes),
        notes=[n["text"] for n in notes],
    )
    # The edge at the rim of the end, picked by where it is.
    nearest = geometry(r, part, kind="edge", near="110,9,0")
    rim = nearest[0]["ref"]
    r.check(
        "the_rim_picked_by_where_it_is",
        nearest[0]["distance"] < 1e-6
        and nearest[0].get("type") in ("arc", "circle")
        and close_enough(nearest[0]["start"][0], 110),
        nearest=nearest[:2],
    )
    r.verified(
        "drafted_detail",
        r.gate(
            "drawing",
            "add-view",
            "--model",
            part + ".drw",
            "--type",
            "detail",
            "--parent",
            "FRONT",
            "--center",
            rim,
            "--near",
            "110,10,0",
            "--radius",
            3,
            "--x",
            330,
            "--y",
            80,
        ),
    )
    noted = r.verified("drafted_annotate", r.gate("drawing", "annotate", "--model", part + ".drw"))
    annotated = noted["result"]["annotated"]
    titled = r.verified(
        "drafted_title_block",
        r.gate(
            "drawing",
            "add-title-block",
            "--model",
            part + ".drw",
            "--language",
            "zh",
            "--request",
            r.request("title", {"number": "SH-001", "drawn_by": "Claude"}),
        ),
    )
    block = r.run("model", "show", "--model", part + ".drw")["tables"][-1]["cells"]
    r.check(
        "the_title_block_filled_from_the_part",
        block[0][:2] == ["名称", part.upper()]
        and block[0][3] == "2:1"
        and block[2][:2] == ["图号", "SH-001"]
        and block[3][:2] == ["制图", "Claude"]
        and titled["result"]["table"] is not None,
        cells=block,
    )
    stepped = annotated["diameters_on_their_steps"]
    front_box = front["result"]["view"]["outline"]
    xs = sorted(s["at"][0] for s in stepped if s["view"] == "FRONT")
    r.check(
        "diameters_over_their_steps",
        len(xs) >= 3
        and all(front_box[0][0] - 1 <= x <= front_box[1][0] + 1 for x in xs)
        and all(b - a > 5 for a, b in zip(xs, xs[1:], strict=False)),
        placed=stepped,
    )
    r.check(
        "no_datum_or_full_turn_on_the_sheet",
        len(annotated["datums_taken_off"]) == 1 and len(annotated["full_turns_taken_off"]) == 1,
        datums=annotated["datums_taken_off"],
        full_turns=annotated["full_turns_taken_off"],
    )
    r.verified(
        "discard_drafted_drawing",
        r.gate("model", "discard", "--model", part + ".drw", "--dangerous"),
    )
    r.opened.remove(part + ".drw")
    r.verified("discard_drafted_part", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def bolted_flange(r: Recorder, stamp: str) -> None:
    """A flange as a drafter would draw it: a bore on the axis needing no location, six bolt
    holes on a circle about the axis given by the circle's diameter and counted 6X, the rim
    chamfered and called out 1 X 45, every dimension on the sheet."""
    part = f"lfl_{stamp}"
    r.create(part, "--units", "mmns")
    r.extrude(
        part,
        "DISC",
        {"depth": 15, "sketch": SKETCH | {"profile": {"type": "circle", "diameter": 120}}},
    )
    face_up = next(s for s in geometry(r, part, kind="surface") if s.get("normal") == [0, 0, 1])
    r.extrude(
        part,
        "HUB",
        {
            "depth": 25,
            "sketch": {
                "plane": face_up["ref"],
                "orient_ref": "RIGHT",
                "profile": {"type": "circle", "diameter": 60},
            },
        },
    )
    request_gate(r, "datum-axis", part, "CENTER", {"name": "CENTER", "through": ["RIGHT", "TOP"]})
    ups = sorted(
        (s for s in geometry(r, part, kind="surface") if s.get("normal") == [0, 0, 1]),
        key=lambda s: s.get("area") or 0,
    )
    bore = request_gate(
        r,
        "hole",
        part,
        "BORE",
        {
            "units": "mm",
            "name": "BORE",
            "diameter": 40,
            "depth": "through_all",
            "placement": {"surface": ups[0]["ref"], "axis": "CENTER"},
        },
    )
    r.check(
        "the_bore_on_the_axis",
        bore["result"]["placement"] == "coaxial"
        and bore["result"]["drill_diameter"] == 40
        and bore["result"]["depth"] == "through_all",
        result={k: bore["result"].get(k) for k in ("placement", "drill_diameter", "depth")},
    )
    bolt = request_gate(
        r,
        "hole",
        part,
        "BOLT",
        {
            "units": "mm",
            "name": "BOLT",
            "diameter": 11,
            "depth": "through_all",
            "placement": {
                "surface": ups[-1]["ref"],
                "axis": "CENTER",
                "diameter": 90,
                "angle_from": "TOP",
            },
        },
    )
    circle = next(c for c in bolt["verification"]["checks"] if c["check"] == "on_the_bolt_circle")
    r.check(
        "the_bolt_hole_on_its_circle",
        bolt["result"]["placement"] == "bolt_circle"
        and close_enough(circle["distance_from_axis"], 45, rel=1e-6),
        distance_from_axis=circle["distance_from_axis"],
    )
    request_gate(
        r,
        "pattern",
        part,
        "BOLTS",
        {
            "units": "mm",
            "name": "BOLTS",
            "feature": "BOLT",
            "axis": {"about": "CENTER", "angle": 60, "count": 6},
        },
    )
    rim = [
        e["ref"]
        for e in geometry(r, part, kind="edge")
        if e.get("type") == "arc" and close_enough(e.get("radius"), 60)
    ]
    chamfer = request_gate(
        r, "chamfer", part, "RIM", {"units": "mm", "name": "RIM", "distance": 1, "edges": rim}
    )
    r.check(
        "the_rim_chamfered_45_x_d",
        chamfer["result"]["scheme"] == "45_x_d" and len(rim) == 4,
        edges=rim,
    )
    r.verified("save_flange", r.gate("model", "save", "--model", part))
    drawn = r.verified(
        "flange_drawing", r.gate("drawing", "create", "--name", part, "--of", part, "--sheet", "a3")
    )
    r.opened.append(part + ".drw")
    boxes = {v["name"]: v["outline"] for v in drawn["result"]["views"]}
    r.check(
        "the_flange_drawn_first_angle",
        drawn["result"]["projection"] == "first_angle"
        and set(boxes) == {"FRONT", "LEFT", "TOP", "ISOMETRIC"}
        and boxes["TOP"][1][1] < boxes["FRONT"][0][1]
        and boxes["LEFT"][0][0] > boxes["FRONT"][1][0],
        views=boxes,
    )
    noted = r.verified("flange_annotate", r.gate("drawing", "annotate", "--model", part + ".drw"))
    annotated = noted["result"]["annotated"]
    shown = r.run("model", "show", "--model", part + ".drw")["dimensions"]
    by_owner = {}
    for row in shown:
        by_owner.setdefault((row.get("feature") or {}).get("name"), []).append(row)
    bolt_dims = by_owner.get("BOLT", [])
    r.check(
        "the_bolt_holes_counted_and_their_circle_given",
        [c["prefix"] for c in annotated["counts_prefixed"]] == ["6X ⌀"]
        and any(d["value"] == 11 and d.get("prefix") == "6X ⌀" for d in bolt_dims)
        and any(d["value"] == 90 and d["type"] == "diameter" for d in bolt_dims)
        and not any(d["type"] == "linear" for d in bolt_dims),
        bolt=[[d["value"], d["type"], d.get("prefix")] for d in bolt_dims],
    )
    hub = by_owner.get("HUB", [])
    r.check(
        "the_hub_diameter_where_it_can_be_seen",
        any(d["value"] == 60 and d["view"] != "FRONT" for d in hub)
        and any(m["name"] in [d["name"] for d in hub] for m in annotated["moved_into_sight"]),
        hub=[[d["name"], d["value"], d["view"]] for d in hub],
        moved=annotated["moved_into_sight"],
    )
    r.check(
        "the_bore_needs_no_location",
        [d["type"] for d in by_owner.get("BORE", [])] == ["diameter"],
        bore=[[d["value"], d["type"]] for d in by_owner.get("BORE", [])],
    )
    r.check(
        "the_chamfer_called_out_1_x_45",
        [c["style"] for c in annotated["chamfers_called_out"]] == ["d_x_45"],
        chamfers=annotated["chamfers_called_out"],
    )
    r.check(
        "every_dimension_on_the_sheet",
        any(
            c["check"] == "dimensions_on_the_sheet" and c["passed"]
            for c in noted["verification"]["checks"]
        ),
        brought=annotated["brought_onto_the_sheet"],
    )
    r.verified(
        "discard_flange_drawing",
        r.gate("model", "discard", "--model", part + ".drw", "--dangerous"),
    )
    r.opened.remove(part + ".drw")
    r.verified("discard_flange", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def spline_profile(r: Recorder, stamp: str) -> None:
    """A plate whose top edge waves: a spline through three points closes the outline, as
    Creo's sketcher draws one, its area as the CLI models Creo's spline."""
    from creo_cli.sketch import area

    part = f"lsp_{stamp}"
    r.create(part, "--units", "mmns")
    wave = {
        "type": "outline",
        "start": [0, 0],
        "segments": [
            {"to": [60, 0]},
            {"to": [60, 20]},
            {"to": [0, 20], "through": [[45, 28], [30, 18], [15, 28]]},
        ],
    }
    body = {"units": "mm", "name": "WAVE", "depth": 10, "sketch": SKETCH | {"profile": wave}}
    preview = r.run(
        "feature", "extrude", "--model", part, "--request", r.request("WAVE", body), "--dry-run"
    )["preview"]
    made = r.extrude(part, "WAVE", {"depth": 10, "sketch": SKETCH | {"profile": wave}})
    modeled = area(wave) * 10
    r.check(
        "spline_as_creo_draws_it",
        preview["sketch"]["entities"] == 4
        and close_enough(made["result"]["volume"]["change"], modeled, rel=1e-4)
        and made["result"]["volume"]["matches_request"] is True,
        change=made["result"]["volume"]["change"],
        modeled=modeled,
    )
    r.verified("discard_wave", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def half_section(r: Recorder, stamp: str) -> None:
    """A flanged bushing turned about its axis, drawn with a half section: cut through its
    axis on one side of a plane square to the cut, whole on the other."""
    part = f"lhs_{stamp}"
    r.create(part, "--units", "mmns")
    outline = {
        "type": "outline",
        "start": [10, 0],
        "segments": [
            {"to": [35, 0]},
            {"to": [35, 8]},
            {"to": [20, 8]},
            {"to": [20, 40]},
            {"to": [10, 40]},
        ],
    }
    turned = r.verified(
        "bushing",
        r.gate(
            "feature",
            "revolve",
            "--model",
            part,
            "--request",
            r.request(
                "BUSH",
                {
                    "units": "mm",
                    "name": "BUSH",
                    "angle": 360,
                    "axis": [[0, 0], [0, 1]],
                    "sketch": SKETCH | {"profile": outline},
                },
            ),
        ),
    )
    exact = math.pi * ((35**2 - 10**2) * 8 + (20**2 - 10**2) * 32)
    r.check(
        "bushing_volume_exact",
        close_enough(turned["result"]["volume"]["change"], exact, rel=1e-9),
        change=turned["result"]["volume"]["change"],
        exact=exact,
    )
    r.verified(
        "bushing_drawing",
        r.gate(
            "drawing",
            "create",
            "--name",
            part,
            "--of",
            part,
            "--sheet",
            "a3",
            "--views",
            "template",
        ),
    )
    r.opened.append(part + ".drw")
    half = r.verified(
        "half_section_view",
        r.gate(
            "drawing",
            "add-view",
            "--model",
            part,
            "--type",
            "general",
            "--orientation",
            "front",
            "--plane",
            "FRONT",
            "--half",
            "RIGHT",
            "--x",
            300,
            "--y",
            200,
            "--name",
            "HALF",
        ),
    )
    r.check(
        "the_view_is_half_cut",
        half["result"]["view"]["section_area"] == "half"
        and half["result"]["view"]["sections"] == ["A"],
        view=half["result"]["view"],
    )
    r.verified(
        "discard_bushing_drawing",
        r.gate("model", "discard", "--model", part + ".drw", "--dangerous"),
    )
    r.opened.remove(part + ".drw")
    r.verified("discard_bushing", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")


def default_template_part(r: Recorder, stamp: str) -> None:
    """A part from Creo's own default template, in whatever unit that gives, built in that
    unit; a millimetre request is refused on it unless it is millimetres."""
    part = f"li_{stamp}"
    created = r.create(part, "--units", "session_default")
    unit = created["result"]["units"]["length"]
    r.check(
        "default_template_units_read_back", unit in ("mm", "in"), units=created["result"]["units"]
    )
    made = r.extrude(
        part,
        "BAR",
        {
            "units": unit,
            "depth": 0.5,
            "sketch": SKETCH | {"profile": {"type": "rectangle", "width": 2, "height": 1}},
        },
    )
    r.check(
        "built_in_the_part_unit",
        close_enough(made["result"]["volume"]["change"], 1.0),
        change=made["result"]["volume"]["change"],
        unit=unit,
    )
    other = "mm" if unit == "in" else "in"
    wrong = r.request(
        "wrong_unit",
        {
            "units": other,
            "depth": 1,
            "sketch": SKETCH | {"profile": {"type": "circle", "diameter": 1}},
        },
    )
    refused = r.run(
        "feature", "extrude", "--model", part, "--request", wrong, "--dry-run", expect=6
    )
    r.check("a_request_in_another_unit_refused", refused["code"] == "E_CONFLICT")
    r.verified("discard_default", r.gate("model", "discard", "--model", part, "--dangerous"))
    r.opened.remove(part + ".prt")
    inch = f"lk_{stamp}"
    named = r.create(inch, "--units", "inlbs")
    r.check("inch_part_by_name", named["result"]["units"]["length"] == "in")
    inch_asm = f"lka_{stamp}"
    made = r.verified(
        "create_inch_assembly", r.gate("assembly", "create", "--name", inch_asm, "--units", "inlbs")
    )
    r.opened.append(inch_asm + ".asm")
    r.check("inch_assembly_by_name", made["result"]["units"]["length"] == "in")
    r.verified(
        "discard_inch_assembly",
        r.gate("model", "discard", "--model", inch_asm + ".asm", "--dangerous"),
    )
    r.opened.remove(inch_asm + ".asm")
    r.verified("discard_inch", r.gate("model", "discard", "--model", inch, "--dangerous"))
    r.opened.remove(inch + ".prt")


def workflow_part(r: Recorder, stamp: str) -> None:
    """A part built, detailed and saved by one workflow: one preview, one confirmation."""
    part = f"lw_{stamp}"
    body = {
        "steps": [
            {"command": "part create", "args": {"name": part, "units": "mmns"}},
            {
                "command": "feature extrude",
                "args": {
                    "model": part,
                    "request": {
                        "units": "mm",
                        "name": "BASE",
                        "depth": 6,
                        "sketch": SKETCH
                        | {"profile": {"type": "rectangle", "width": 50, "height": 30}},
                    },
                },
            },
            {
                "command": "feature extrude",
                "args": {
                    "model": part,
                    "request": {
                        "units": "mm",
                        "name": "BORE",
                        "depth": 6,
                        "material": "remove",
                        "sketch": SKETCH | {"profile": {"type": "circle", "diameter": 10}},
                    },
                },
            },
            {
                "command": "parameter set",
                "args": {
                    "model": part,
                    "name": "DESCRIPTION",
                    "type": "string",
                    "value": "washer plate",
                },
            },
            {"command": "model save", "args": {"model": part}},
        ]
    }
    request = r.request("workflow", body)
    dry = r.run("workflow", "run", "--request", request, "--dry-run")
    r.check(
        "workflow_preview_plans_the_first_step",
        dry["preview"]["first_step"]["command"] == "part create",
    )
    done = r.run("workflow", "run", "--request", request, "--confirm", dry["confirm_token"])
    r.opened.append(part + ".prt")
    steps = done["result"]["steps"]
    r.check("workflow_ran_every_step", done["status"] == "completed" and len(steps) == 5)
    r.check(
        "workflow_volumes",
        close_enough(steps[1]["result"]["volume"]["change"], 1500 * 6)
        and close_enough(steps[2]["result"]["volume"]["change"], -math.pi * 25 * 6, rel=1e-5),
        base=steps[1]["result"]["volume"]["change"],
        bore=steps[2]["result"]["volume"]["change"],
    )
    for step in steps:
        receipt = r.run("operation", "show", "--id", step["operation_id"])["receipt"]
        if receipt["status"] != "completed":
            r.check("workflow_step_receipts_completed", False, step=step["step"])
    r.check("workflow_step_receipts_completed", True)
    r.verified("close_workflow_part", r.gate("model", "close", "--model", part))
    r.opened.remove(part + ".prt")


def record(workspace: Path, template: Path | None) -> dict:
    stamp = datetime.now().strftime("%m%d_%H%M%S")
    run_dir = workspace / f"live-{stamp}"
    run_dir.mkdir()
    r = Recorder(workspace, run_dir)
    began = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    status, error = None, None
    try:
        status = discover(r)
        r.verified("cd", r.gate("session", "cd", "--path", run_dir))
        block_part(r, f"lb_{stamp}")
        hexagon_part(r, f"lh_{stamp}")
        if template:
            from_template(r, f"lt_{stamp}", template)
        bracket_part(r, f"lp_{stamp}")
        shaft_part(r, f"ls_{stamp}")
        box_part(r, f"lx_{stamp}")
        disc_part(r, f"ld_{stamp}")
        sketch_variants(r, stamp)
        revolved_ring(r, stamp)
        outside_shell(r, stamp)
        draft_part(r, stamp)
        rib_part(r, stamp)
        tolerance_part(r, stamp)
        fastener_holes(r, stamp)
        threaded_shaft(r, stamp)
        grid_and_bodies(r, stamp)
        face_sketches(r, stamp)
        half_section(r, stamp)
        swept_parts(r, stamp)
        family_parts(r, stamp)
        spline_profile(r, stamp)
        drafted_sketches(r, stamp)
        drafted_drawing(r, stamp)
        bolted_flange(r, stamp)
        cast_housing(r, stamp)
        profile_variety(r, stamp)
        relations_part(r, stamp)
        default_template_part(r, stamp)
        assembly_models(r, stamp)
        drawing_models(r, stamp, template)
        workflow_part(r, stamp)
        files = r.run("workspace", "list", "--name", f"lb_{stamp}")["items"]
        r.check(
            "workspace_lists_the_saved_versions",
            [f["versions"] for f in files] == [[1, 2, 3]],
            files=[[f["model"], f["versions"]] for f in files],
        )
        receipts = r.run("operation", "list", "--limit", "200")["items"]
        mine = [x for x in receipts if x["at"] >= began]
        r.check(
            "every_receipt_completed",
            mine and all(x["status"] == "completed" for x in mine),
            statuses=sorted({x["status"] for x in mine}),
        )
        r.run("operation", "show", "--id", mine[0]["operation_id"])
    except Stop as stop:
        error = str(stop)
    finally:
        r.cleanup()
    return {
        "ok": error is None,
        "at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "upstream_kind": "live_creo_via_service",
        "real_creo_verified": error is None,
        "creo": {
            k: (status or {}).get(k)
            for k in ("creo_version", "creo_build", "native_sketch_available")
        },
        "cli_subprocess_count": len(r.calls),
        "checks": r.checks,
        "error": error,
        "source_fingerprint_sha256": fingerprint(),
        "calls": r.calls,
        "limitations": [
            "One machine, one Creo build; a different template, licence or configuration may "
            "behave differently.",
            "Volumes and dimensions are what Creo reports; design intent beyond them is not "
            "assessed.",
            "The parts are disposable and stay in the workspace; they are not part of this record.",
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument(
        "--creo-template",
        help="a Creo part template to copy into the workspace for part create --template; "
        "omitted, that path is not exercised",
    )
    a = p.parse_args()
    missing = [k for k, v in POLICY.items() if os.environ.get(k) != v]
    if missing or not os.environ.get("CREO_CLI_WORKSPACE"):
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": "the write policy is not in the environment; CREO_CLI_WORKSPACE, "
                    "CREO_CLI_PERMISSION=write and CREO_CLI_EXPERIMENTAL_NATIVE_WRITES=1 are "
                    "set when a person says so",
                }
            )
        )
        return 4
    doc = record(
        Path(os.environ["CREO_CLI_WORKSPACE"]).resolve(),
        Path(a.creo_template) if a.creo_template else None,
    )
    out = Path(a.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    summary = {k: doc[k] for k in ("ok", "error", "cli_subprocess_count")}
    print(json.dumps(summary | {"checks": [c["check"] for c in doc["checks"]]}, indent=2))
    return 0 if doc["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
