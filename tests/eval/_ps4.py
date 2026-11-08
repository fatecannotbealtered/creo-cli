"""What the power strip questions share: the parts in Creo, reading them back, and the right builds.

The questions take the requirement text of the four-way power strip from creo-cli's design: the top
housing PS4-TOP, its switch cap PS4-KEY, and a change order on the housing. top-start/ and key-start/
hold empty parts made from Creo's metric part template with the parameters PART_NO and DESCRIPTION;
top-built/ holds the housing as creo-cli builds it from the text: four positions 62 mm apart, the
parameters POSITIONS and PITCH that relations read, and WALL, the shell's thickness. Creo holds one
model of a name at a time, so every question that opens a part closes it again in `after`.
"""
import json
import math
import re

from _disc import says_saved

DEFAULT_NAME = re.compile(r"^[dp][0-9]+$", re.IGNORECASE)


def path(run, name):
    return str(run.documents / name)


def open_part(run, name):
    """Open a part; doc open runs as a long job, so wait until the job ends."""
    reply = run.tool("doc", "open", "--doc", path(run, name))
    job = ((reply.get("data") or {}).get("result") or {}).get("job")
    if reply.get("ok") and job:
        done = run.tool("job", "get", "--job", job["id"], "--wait", "120s")
        reply = {"ok": bool((done.get("data") or {}).get("ok")), "error": done.get("data")}
    if not reply.get("ok"):
        raise RuntimeError(f"{name} did not open in Creo: {reply.get('error')}")


def close_part(run, name):
    """Close a part when it is open; unsaved changes are discarded, which is dangerous and two-step."""
    wanted = path(run, name).lower().replace("/", "\\")
    listed = (run.tool("doc", "list").get("data") or {}).get("items") or []
    if not any(str(d.get("path", "")).lower().replace("/", "\\") == wanted for d in listed):
        return
    reply = run.tool("doc", "close", "--doc", path(run, name), "--discard", "--dangerous")
    token = (reply.get("error") or {}).get("details", {}).get("confirm_token")
    if token:
        reply = run.tool("doc", "close", "--doc", path(run, name), "--discard", "--confirm", token, "--dangerous")
    if not reply.get("ok"):
        raise RuntimeError(f"{name} did not close in Creo: {reply.get('error')}")


def result(reply):
    data = reply.get("data") or {}
    return data.get("result", data) if isinstance(data, dict) else {}


def items(run, *args):
    """Every item of a list command, over all its pages."""
    out = []
    while True:
        data = run.tool(*args, "--limit", "100", "--offset", str(len(out))).get("data") or {}
        page = data.get("items") or []
        out += page
        if not data.get("has_more") or not page:
            return out


def summary(run, name):
    return result(run.tool("model", "get", "--doc", path(run, name)))


def extents(model):
    """The bounding box's size along x, y and z."""
    box = model.get("bounding_box_mm") or {}
    lo, hi = box.get("min"), box.get("max")
    return [hi[i] - lo[i] for i in range(3)] if lo and hi else [0, 0, 0]


def close_to(value, expected, tolerance=0.01):
    return isinstance(value, (int, float)) and abs(value - expected) <= tolerance


def same_sizes(model, expected):
    """Whether the bounding box has these sizes. The box is Creo's outline, which around rounds on drafted walls
    was measured up to 0.06 mm larger than the part."""
    return all(close_to(a, b, 0.1) for a, b in zip(sorted(extents(model)), sorted(expected)))


def parameters(run, name):
    return {p.get("id"): p.get("value") for p in items(run, "parameter", "list", "--doc", path(run, name))}


def dimensions(run, name):
    return items(run, "dimension", "list", "--doc", path(run, name))


def named(params, dims, value):
    """Whether a parameter, or a dimension with a name of its own, holds the value."""
    if any(close_to(v, value, 1e-6) for k, v in params.items() if isinstance(v, (int, float)) and not isinstance(v, bool)):
        return True
    return any(close_to(d.get("value_mm", d.get("value")), value, 1e-6) and not DEFAULT_NAME.match(str(d.get("id"))) for d in dims)


def surfaces(run, name):
    """Every face with all its fields: a cylinder's axis_origin_mm is not among the default ones."""
    return items(run, "geometry", "list", "--doc", path(run, name), "--kind", "surface", "--fields", "all")


def cylinders(faces, radius):
    return [f for f in faces if f.get("shape") == "cylinder" and close_to(f.get("radius_mm"), radius, 1e-3)]


def errors(run, name):
    """The errors of model check: ModelCHECK's and creo-cli's."""
    return result(run.tool("model", "check", "--doc", path(run, name))).get("errors")


def versions(run, name):
    """The version numbers of a part on disk: ps4_top.prt.1 is 1."""
    return sorted(int(p.name.rsplit(".", 1)[1]) for p in run.documents.glob(name + ".*") if p.name.rsplit(".", 1)[1].isdigit())


def check_saved(run, name):
    run.check(len(versions(run, name)) > 1, f"{name} was not saved: no version after the first on disk")
    run.check(says_saved(run.messages[-1]), f"the report does not say that {name} was saved")


# ------------------------------------------------------------------ the right builds


def answer(call):
    return ((call.envelope or {}).get("data") or {}).get("result") or {}


def save(agent, name):
    """What an Agent does to save a part: confirm the save, then follow its long job to the end."""
    out = agent.run("doc", "save", "--doc", name)
    done = agent.run("doc", "save", "--doc", name, "--confirm", out.details["confirm_token"])
    job = answer(done).get("job") or {}
    view = {"state": job.get("state")}
    while job.get("poll") and view.get("state") in ("queued", "running"):
        view = agent.line(job["poll"]).data or {}


def corners(diameter, name_d, name_x, name_z):
    """Four circles at the corners of the housing, mirrored from the first, all of one size."""
    return {
        "plane": "BOSS_PLANE", "x_axis": "+x", "references": ["RIGHT", "FRONT"],
        "entities": [{"id": f"b{i}", "type": "circle", "diameter_mm": diameter} for i in range(1, 5)],
        "constraints": [{"type": "symmetric", "a": "b1.center", "b": "b2.center", "about": "RIGHT"},
                        {"type": "symmetric", "a": "b3.center", "b": "b4.center", "about": "RIGHT"},
                        {"type": "symmetric", "a": "b1.center", "b": "b3.center", "about": "FRONT"},
                        {"type": "equal", "a": "b1", "b": "b2"}, {"type": "equal", "a": "b1", "b": "b3"},
                        {"type": "equal", "a": "b1", "b": "b4"}],
        "dimensions": [{"name": name_d, "measure": "b1.diameter"},
                       {"name": name_x, "from": "RIGHT", "to": "b1.center", "value_mm": 132},
                       {"name": name_z, "from": "FRONT", "to": "b1.center", "value_mm": 19.5}]}


def build_top(agent, relations=True):
    """The housing as creo-cli builds it: length along x, height along y, positions centered on RIGHT."""
    doc = ["--doc", "ps4_top.prt"]
    agent.run("parameter", "update", *doc, "--id", "PART_NO", "--value", "PS4-TOP")
    agent.run("parameter", "update", *doc, "--id", "DESCRIPTION", "--value", "四位排插上壳")
    agent.run("model", "update", *doc, "--material", "ABS")
    agent.run("extrude", "create", *doc, "--name", "BASE", "--depth", "22mm", "--depth-name", "BODY_HEIGHT", "--direction", "+y",
              "--sketch", json.dumps({
                  "plane": "TOP", "x_axis": "+x", "references": ["RIGHT", "FRONT"],
                  "entities": [{"id": "body", "type": "rectangle", "width_mm": 280, "height_mm": 55, "corner_radius_mm": 8}],
                  "constraints": [{"type": "symmetric", "entity": "body", "about": "RIGHT"},
                                  {"type": "symmetric", "entity": "body", "about": "FRONT"}],
                  "dimensions": [{"name": "BODY_LENGTH", "measure": "body.width"}, {"name": "BODY_WIDTH", "measure": "body.height"},
                                 {"name": "CORNER_R", "measure": "body.corner_radius"}]}))
    agent.run("draft", "create", *doc, "--name", "OUTER_DRAFT", "--faces", "BASE/side", "--hinge", "BASE/start", "--pull", "+y",
              "--angle", "1deg", "--angle-name", "DRAFT_ANGLE")
    agent.run("round", "create", *doc, "--name", "TOP_ROUND", "--radius", "2mm", "--edges", "BASE/end:outer-edges")
    agent.run("shell", "create", *doc, "--name", "SHELL", "--thickness", "2mm", "--thickness-name", "WALL", "--remove", "BASE/start")
    counts = {}
    # Each position is one pitch wide: a socket, a 5 mm gap and a switch, centered; the first is at x = -93.
    for name, size, offset, row, pitch in (("SOCKET", (36, 36, 3), -9.0, "SOCKET_ROW", "OUTLET_PITCH"),
                                           ("SWITCH", (13, 19, 0), 20.5, "SWITCH_ROW", "SWITCH_PITCH")):
        shape = {"id": "o", "type": "rectangle", "width_mm": size[0], "height_mm": size[1]}
        dims = [{"measure": "o.width"}, {"measure": "o.height"}]
        if size[2]:
            shape["corner_radius_mm"] = size[2]
            dims.append({"measure": "o.corner_radius"})
        agent.run("extrude", "create", *doc, "--name", name + "_CUT", "--remove", "--through-all", "--direction", "-y",
                  "--sketch", json.dumps({
                      "plane": "BASE/end", "x_axis": "+x", "references": ["RIGHT", "FRONT"], "entities": [shape],
                      "constraints": [{"type": "symmetric", "entity": "o", "about": "FRONT"}],
                      "dimensions": dims + [{"name": name + "_X", "from": "RIGHT", "to": "o.center", "value_mm": -93 + offset}]}))
        made = answer(agent.run("pattern", "create", *doc, "--name", row, "--feature", name + "_CUT", "--along", "+x",
                                "--count", "4", "--spacing", "62mm", "--spacing-name", pitch))
        counts[row] = next(d["id"] for d in made.get("dimensions", []) if d.get("value") == 4)
    agent.run("plane", "create", *doc, "--name", "RIB_PLANE", "--from", "RIGHT", "--distance", "62mm", "--direction", "-x",
              "--distance-name", "RIB_X")
    agent.run("extrude", "create", *doc, "--name", "RIB", "--symmetric", "--depth", "1.2mm",
              "--sketch", json.dumps({
                  "plane": "RIB_PLANE", "x_axis": "+y", "references": ["TOP", "FRONT"],
                  "entities": [{"id": "rib", "type": "rectangle", "width_mm": 16, "height_mm": 52}],
                  "constraints": [{"type": "symmetric", "entity": "rib", "about": "FRONT"}],
                  "dimensions": [{"name": "RIB_H", "measure": "rib.width"}, {"measure": "rib.height"},
                                 {"name": "RIB_Y", "from": "TOP", "to": "rib.center", "value_mm": 13}]}))
    made = answer(agent.run("pattern", "create", *doc, "--name", "RIB_ROW", "--feature", "RIB", "--along", "+x", "--count", "3",
                            "--spacing", "62mm", "--spacing-name", "RIB_PITCH"))
    counts["RIB_ROW"] = next(d["id"] for d in made.get("dimensions", []) if d.get("value") == 3)
    agent.run("plane", "create", *doc, "--name", "BOSS_PLANE", "--from", "TOP", "--distance", "2mm", "--direction", "+y")
    top = (agent.run("geometry", "list", *doc, "--feature", "SHELL", "--facing", "-y").data or {}).get("items") or [{}]
    agent.run("extrude", "create", *doc, "--name", "BOSS", "--direction", "+y", "--to", str(top[0].get("reference")),
              "--sketch", json.dumps(corners(6, "BOSS_D", "BOSS_X", "BOSS_Z")))
    agent.run("extrude", "create", *doc, "--name", "SCREW_HOLE", "--remove", "--direction", "+y", "--depth", "12mm",
              "--sketch", json.dumps(corners(2.5, "HOLE_D", "HOLE_X", "HOLE_Z")))
    if relations:
        agent.run("parameter", "create", *doc, "--name", "POSITIONS", "--type", "integer", "--value", "4")
        agent.run("parameter", "create", *doc, "--name", "PITCH", "--type", "real", "--value", "62")
        agent.run("relation", "update", *doc, "--relations", json.dumps([
            "BODY_LENGTH = POSITIONS * PITCH + 2 * 16", "OUTLET_PITCH = PITCH", "SWITCH_PITCH = PITCH", "RIB_PITCH = PITCH",
            f"{counts['SOCKET_ROW']} = POSITIONS", f"{counts['SWITCH_ROW']} = POSITIONS", f"{counts['RIB_ROW']} = POSITIONS - 1",
            "SOCKET_X = (POSITIONS - 1) / 2 * PITCH + 9", "SWITCH_X = (POSITIONS - 1) / 2 * PITCH - 20.5",
            "RIB_X = (POSITIONS / 2 - 1) * PITCH", "RIB_Y = BODY_HEIGHT - WALL - 15 + RIB_H / 2",
            "BOSS_X = BODY_LENGTH / 2 - 8", "BOSS_Z = BODY_WIDTH / 2 - 8", "HOLE_X = BOSS_X", "HOLE_Z = BOSS_Z"]))
    agent.run("model", "check", *doc)
    save(agent, "ps4_top.prt")


def build_key(agent, shell=True):
    """The switch cap as creo-cli builds it: the side profile on FRONT, extruded 12.6 mm across it."""
    doc = ["--doc", "ps4_key.prt"]
    agent.run("parameter", "update", *doc, "--id", "PART_NO", "--value", "PS4-KEY")
    agent.run("parameter", "update", *doc, "--id", "DESCRIPTION", "--value", "开关按钮")
    agent.run("model", "update", *doc, "--material", "PC")
    side = math.sqrt(30 ** 2 - 9.3 ** 2) - 22
    angle = math.degrees(math.acos(9.3 / 30))
    agent.run("extrude", "create", *doc, "--name", "KEY_BODY", "--symmetric", "--depth", "12.6mm", "--depth-name", "KEY_W",
              "--sketch", json.dumps({
                  "plane": "FRONT", "x_axis": "+x", "references": ["RIGHT", "TOP"],
                  "entities": [{"id": "floor", "type": "line", "start_mm": [-9.3, 0], "end_mm": [9.3, 0]},
                               {"id": "right", "type": "line", "start_mm": [9.3, 0], "end_mm": [9.3, side]},
                               {"id": "roof", "type": "arc", "center_mm": [0, -22], "radius_mm": 30, "start_deg": angle,
                                "end_deg": 180 - angle},
                               {"id": "left", "type": "line", "start_mm": [-9.3, side], "end_mm": [-9.3, 0]}],
                  "constraints": [{"type": "coincident", "a": "floor.end", "b": "right.start"},
                                  {"type": "coincident", "a": "right.end", "b": "roof.start"},
                                  {"type": "coincident", "a": "roof.end", "b": "left.start"},
                                  {"type": "coincident", "a": "left.end", "b": "floor.start"},
                                  {"type": "vertical", "entity": "right"}, {"type": "vertical", "entity": "left"},
                                  {"type": "on", "point": "floor.start", "entity": "TOP"},
                                  {"type": "symmetric", "a": "floor.start", "b": "floor.end", "about": "RIGHT"},
                                  {"type": "on", "point": "roof.center", "entity": "RIGHT"}],
                  "dimensions": [{"name": "KEY_L", "measure": "floor.length"}, {"name": "KEY_R", "measure": "roof.radius"},
                                 {"name": "ROOF_DROP", "from": "TOP", "to": "roof.center", "value_mm": -22}]}))
    if shell:
        agent.run("shell", "create", *doc, "--name", "KEY_SHELL", "--thickness", "1mm", "--remove", "KEY_BODY/side[-y]")
    agent.run("extrude", "create", *doc, "--name", "PIN", "--depth", "1.5mm", "--direction", "+z",
              "--sketch", json.dumps({
                  "plane": "KEY_BODY/end[+z]", "x_axis": "+x", "references": ["RIGHT", "TOP"],
                  "entities": [{"id": "pin", "type": "circle", "diameter_mm": 2}],
                  "constraints": [{"type": "symmetric", "entity": "pin", "about": "RIGHT"}],
                  "dimensions": [{"name": "PIN_D", "measure": "pin.diameter"},
                                 {"name": "PIN_Y", "from": "TOP", "to": "pin.center", "value_mm": 2}]}))
    agent.run("pattern", "create", *doc, "--name", "PIN_PAIR", "--feature", "PIN", "--along", "-z", "--count", "2",
              "--spacing", "14.1mm")
    agent.run("model", "check", *doc)
    save(agent, "ps4_key.prt")
