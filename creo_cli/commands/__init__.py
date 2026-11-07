"""The domain commands of creo-cli, as registrations (DCLI-029).

Each command is one dict. The runtime checks every field when the tool starts and refuses a
registration that breaks a rule, so a mistake shows up at once. A command needs:

- ``path``: ``noun verb`` in lowercase words, the noun taken from Creo Parametric's object model
- ``summary``: one line
- ``effects``: what it changes (DCLI-051); the runtime derives the confirmation and risk tiers
- ``modes``, ``target_kind``, ``flags`` (with a unit for every physical quantity), ``untrusted_fields``
- ``irreversible``, ``halt``, ``tolerances``, ``default_fields``, ``related_knowledge``
- ``output_schema``, ``examples``, ``maturity`` and ``evidence``
- ``doc_kinds`` when it works on only some kinds of model, and ``long`` when it can take Creo
  more than a minute

The runtime derives the adapter capabilities from the effects (DCLI-260), and adds ``--limit``
and ``--offset`` to every list command (DCLI-026). The capabilities a command offers are marked
``provided`` in docs/APPLICATION.md (DREPO-060).

Every command also gets a behavior matrix in tests/matrix/; its ``normal`` row is the write
sample (DVER-002, DVER-030). Run ``python scripts/spec.py generate`` after a change.

Objects inside a model are named by their target keys (DCLI-028): the document's key followed
by ``#/dimensions/<name>``, ``#/parameters/<name>`` or ``#/features/<id>``.
"""
from __future__ import annotations

from typing import Any

from ..maturity import DOMAIN as MATURITY

MODEL = "the model's default coordinate system; lengths in mm"
EXAMPLE = "creo-cli {path} --session creo-9184-1d9a4c2e --doc D:/work/bracket.prt"
# Features, dimensions and geometry belong to parts and assemblies; a drawing has none of its own.
SOLID = ["part", "assembly"]


def _items(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": {
        "items": {"type": "array", "items": {"type": "object", "properties": item}},
        "total": {"type": "integer"}}}


def _read(path: str, summary: str, target_kind: str, flags: list[dict[str, Any]], output: dict[str, Any],
          untrusted: list[str], example: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "path": path, "summary": summary, "effects": ["observe"], "modes": ["session"],
        "target_kind": target_kind, "flags": flags, "untrusted_fields": untrusted,
        "irreversible": False, "halt": False,
        "tolerances": {}, "default_fields": [], "related_knowledge": [], "output_schema": output,
        "examples": [EXAMPLE.format(path=path) + example], "maturity": "draft", "evidence": [], **extra,
    }


STR = {"type": "string"}
NUM = {"type": "number"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}

FEATURE_ITEM = {"id": INT, "number": INT, "name": STR, "type": STR, "status": STR}
DIMENSION_ITEM = {
    "id": STR, "name": STR, "kind": STR, "feature_id": INT, "value_mm": NUM, "value_deg": NUM,
    "driven_by_relation": BOOL, "tolerance": {"type": "object"},
}
PARAMETER_ITEM = {
    "id": STR, "name": STR, "type": STR, "value": {}, "unit": {"type": ["string", "null"]}, "value_mm": NUM,
    "driven_by_relation": BOOL,
}

XY = {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2}
SKETCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["plane", "x_axis", "entities"],
    "properties": {
        "plane": {"type": "string", "description": "The sketch plane: a datum such as TOP, a face such as BASE/end, or surface:<id>."},
        "x_axis": {"type": "string", "enum": ["+x", "-x", "+y", "-y", "+z", "-z"],
                   "description": "The model axis the sketch's x runs along; it must lie in the plane. y is the plane's normal crossed with x."},
        "references": {"type": "array", "items": {"type": "string"},
                       "description": "Datum planes or planar faces across the sketch plane, projected to dimension and constrain to."},
        "entities": {"type": "array", "items": {"type": "object", "required": ["id", "type"], "properties": {
            "id": {"type": "string"},
            "type": {"type": "string", "enum": ["rectangle", "circle", "line", "arc", "centerline", "point"]},
            "width_mm": {"type": "number"}, "height_mm": {"type": "number"}, "corner_radius_mm": {"type": "number"},
            "center_mm": XY, "diameter_mm": {"type": "number"}, "radius_mm": {"type": "number"},
            "start_mm": XY, "end_mm": XY, "start_deg": {"type": "number"}, "end_deg": {"type": "number"}, "at_mm": XY}}},
        "constraints": {"type": "array", "items": {"type": "object", "required": ["type"], "properties": {
            "type": {"type": "string", "enum": ["symmetric", "horizontal", "vertical", "coincident", "on", "tangent", "parallel",
                                                "perpendicular", "equal"]},
            "entity": {"type": "string"}, "about": {"type": "string"}, "a": {"type": "string"}, "b": {"type": "string"},
            "point": {"type": "string"}}}},
        "dimensions": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string", "description": "The dimension's name in Creo; dimension update takes it."},
            "measure": {"type": "string", "description": "An entity's own size: body.width, body.height, body.corner_radius, hole.diameter, rim.length."},
            "from": {"type": "string"}, "to": {"type": "string"},
            "value_mm": {"type": "number", "description": "For from and to: the distance, its sign the side of from along the sketch axis."}}}},
    },
}

COMMANDS: list[dict[str, Any]] = [
    _read(
        "feature get", "One feature: its dimensions, parents and children.",
        "feature", [{"name": "--id", "type": "string", "required": True,
                     "summary": "The feature's ID, such as 12, or its name."}],
        {"type": "object", "properties": {
            **FEATURE_ITEM, "dimensions": {"type": "array", "items": {"type": "object", "properties": DIMENSION_ITEM}},
            "parents": {"type": "array"}, "children": {"type": "array"}}},
        ["name", "parents[*].name", "children[*].name", "dimensions[*].id", "dimensions[*].name"], " --id 12", related_knowledge=["creo-localized-names"],
        doc_kinds=SOLID,
    ),
    _read(
        "model get", "A model's summary: kind, units, material, mass properties, bounding box and feature count.",
        "model", [],
        {"type": "object", "properties": {
            "name": STR, "kind": STR, "units": {"type": "object"}, "material": {"type": ["string", "null"]},
            "volume_mm3": NUM, "surface_area_mm2": NUM, "mass_kg": {"type": ["number", "null"]},
            "center_of_mass_mm": {"type": "array"},
            "bounding_box_mm": {"type": "object"}, "feature_count": INT}},
        ["name", "material", "units"], output_coordinate_system=MODEL, related_knowledge=["creo-units", "creo-materials"],
    ),
    _read(
        "feature list", "The features of a model in regeneration order: ID, number, name, type and status.",
        "feature", [], _items(FEATURE_ITEM), ["name"], related_knowledge=["creo-localized-names"],
        default_fields=["id", "name", "type", "status"], doc_kinds=SOLID,
    ),
    _read(
        "geometry list", "Faces, edges, axes, datum planes and coordinate systems with the references other commands take.",
        "geometry", [
            {"name": "--kind", "type": "string",
             "summary": "Only this kind: surface, edge, axis, datum-plane or coordinate-system."},
            {"name": "--feature", "type": "string", "summary": "Only the geometry this feature created: its ID or name."}],
        _items({"reference": STR, "kind": STR, "shape": STR, "feature_id": INT, "name": STR, "normal": {"type": "array"},
                "origin_mm": {"type": "array"}, "axis_direction": {"type": "array"}, "axis_origin_mm": {"type": "array"},
                "radius_mm": NUM, "length_mm": NUM}),
        ["reference", "name"], " --kind surface", output_coordinate_system=MODEL,
        related_knowledge=["creo-geometry-references", "creo-units"],
        default_fields=["reference", "kind", "shape", "feature_id", "normal", "origin_mm", "axis_direction", "radius_mm"],
        doc_kinds=SOLID,
    ),
    _read(
        "distance get", "The shortest distance between two geometry references, as Creo measures it.",
        "geometry", [
            {"name": "--from", "type": "string", "required": True,
             "summary": "A reference from geometry list, such as surface:41, or a datum name such as FRONT."},
            {"name": "--to", "type": "string", "required": True, "summary": "A second reference, as --from."}],
        {"type": "object", "properties": {"from": STR, "to": STR, "distance_mm": NUM}},
        [], " --from FRONT --to surface:41", related_knowledge=["creo-geometry-references", "creo-units"], doc_kinds=SOLID,
    ),
    _read(
        "dimension list", "The dimensions of a model, or of one feature: name, kind, value, tolerance and owner.",
        "dimension", [{"name": "--feature", "type": "string", "summary": "Only this feature's dimensions: its ID or name."}],
        _items(DIMENSION_ITEM), ["id", "name"], related_knowledge=["creo-relations-and-dimensions", "creo-units"],
        default_fields=["id", "kind", "value_mm", "value_deg", "driven_by_relation", "tolerance"], doc_kinds=SOLID,
    ),
    {
        "path": "dimension update",
        "summary": "Change one dimension's value or tolerance and regenerate; Creo takes back a value the model cannot regenerate with.",
        "effects": ["change"], "modes": ["session"], "target_kind": "dimension",
        "flags": [
            {"name": "--id", "type": "string", "required": True, "summary": "The dimension's name, such as d12."},
            {"name": "--length", "type": "quantity", "quantity": "length", "summary": "The new value of a linear, radius or diameter dimension."},
            {"name": "--angle", "type": "quantity", "quantity": "angle", "summary": "The new value of an angular dimension."},
            {"name": "--plus", "type": "quantity", "quantity": "length", "summary": "With --minus: the upper deviation of a plus-minus tolerance."},
            {"name": "--minus", "type": "quantity", "quantity": "length", "summary": "With --plus: the lower deviation, as a positive amount."},
            {"name": "--symmetric", "type": "quantity", "quantity": "length", "summary": "A symmetric tolerance of plus or minus this much."},
            {"name": "--upper", "type": "quantity", "quantity": "length", "summary": "With --lower: the upper limit itself."},
            {"name": "--lower", "type": "quantity", "quantity": "length", "summary": "With --upper: the lower limit itself."},
            {"name": "--fit", "type": "string", "summary": "An ISO 286 fit: capitals for a hole (H7), small letters for a shaft (g6)."},
            {"name": "--basic", "type": "boolean", "summary": "Make it a basic dimension, the exact value a geometric tolerance refers to."},
            {"name": "--nominal", "type": "boolean", "summary": "Remove its tolerance."},
        ],
        "untrusted_fields": ["id", "name"],
        "irreversible": False, "halt": False,
        "tolerances": {"value_mm": 0.000001, "value_deg": 0.000001, "plus_mm": 0.000001, "minus_mm": 0.000001,
                       "upper_mm": 0.000001, "lower_mm": 0.000001},
        "default_fields": [], "related_knowledge": ["creo-relations-and-dimensions", "creo-units"],
        "output_schema": {"type": "object", "properties": DIMENSION_ITEM}, "doc_kinds": SOLID,
        "examples": [EXAMPLE.format(path="dimension update") + " --id d12 --length 25mm",
                     EXAMPLE.format(path="dimension update") + " --id d12 --plus 0.1mm --minus 0.05mm"],
        "maturity": "draft", "evidence": [],
    },
    _read(
        "parameter list", "A model's parameters: name, type, value, unit and whether a relation drives it.",
        "parameter", [],
        _items(PARAMETER_ITEM), ["id", "name", "value", "unit"],
        related_knowledge=["creo-relations-and-dimensions", "creo-units"],
        default_fields=["id", "type", "value", "unit", "value_mm", "driven_by_relation"],
    ),
    {
        "path": "parameter update",
        "summary": "Set a parameter's value, keeping its type; a parameter with a unit takes the value with a unit.",
        "effects": ["change"], "modes": ["session"], "target_kind": "parameter",
        "flags": [
            {"name": "--id", "type": "string", "required": True, "summary": "The parameter's name."},
            {"name": "--value", "type": "string", "required": True,
             "summary": "The new value: 12, 4.5, true or text; 12.5mm for a parameter with a length unit."},
        ],
        "untrusted_fields": ["id", "name", "value", "unit"],
        "irreversible": False, "halt": False, "tolerances": {"value": 0.000001}, "default_fields": [],
        "related_knowledge": ["creo-relations-and-dimensions", "creo-units"],
        "output_schema": {"type": "object", "properties": PARAMETER_ITEM},
        "examples": [EXAMPLE.format(path="parameter update") + " --id MATERIAL_CODE --value CC-001"],
        "maturity": "draft", "evidence": [],
    },
    _read(
        "relation list", "A model's relations, one item per line, numbered as Tools > Relations shows them.",
        "relation", [], _items({"number": INT, "text": STR}),
        ["text"], related_knowledge=["creo-relations-and-dimensions"],
    ),
    _read(
        "material list", "The materials in Creo's material library and the model's own materials, with the one assigned.",
        "material", [{"name": "--query", "type": "string", "summary": "Only materials whose name contains this text."}],
        _items({"name": STR, "source": STR, "assigned": BOOL}), ["name"], related_knowledge=["creo-materials"],
        default_fields=["name", "source", "assigned"],
    ),
    _read(
        "model check", "Run Creo's ModelCHECK and creo-cli's checks on a part: failed, suppressed and unnamed features.",
        "model", [],
        {"type": "object", "properties": {
            "modelcheck": {"type": "object"}, "errors": INT, "passed": BOOL,
            "findings": {"type": "array", "items": {"type": "object", "properties": {
                "rule": STR, "object": STR, "severity": STR, "message": STR}}}}},
        ["findings[*].object", "modelcheck.report", "modelcheck.reason"], related_knowledge=["creo-localized-names"], doc_kinds=["part"],
    ),
    _read(
        "component list", "The top-level components of an assembly: model, status and position.",
        "component", [],
        _items({"id": INT, "model": STR, "kind": STR, "status": STR, "origin_mm": {"type": "array"}}),
        ["model"], output_coordinate_system="the assembly's default coordinate system; lengths in mm",
        related_knowledge=["creo-units"], default_fields=["id", "model", "kind", "status"], doc_kinds=["assembly"],
    ),
    {
        "path": "feature update",
        "summary": "Suppress, resume or rename one feature; suppressing takes the features that depend on it along.",
        "effects": ["change"], "modes": ["session"], "target_kind": "feature",
        "flags": [
            {"name": "--id", "type": "string", "required": True, "summary": "The feature's ID, such as 12, or its name."},
            {"name": "--status", "type": "string", "summary": "suppressed or active."},
            {"name": "--name", "type": "string", "summary": "A new name: a letter, then letters, digits or _, 31 at most."},
        ],
        "untrusted_fields": ["name"],
        "irreversible": False, "halt": False, "tolerances": {}, "default_fields": [], "related_knowledge": ["creo-localized-names"],
        "output_schema": {"type": "object", "properties": FEATURE_ITEM}, "doc_kinds": SOLID,
        "examples": [EXAMPLE.format(path="feature update") + " --id 12 --status suppressed"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "extrude create",
        "summary": "Extrude a sketch into one feature, adding or removing material, and regenerate; a sketch that is not fully defined is refused.",
        "effects": ["change"], "modes": ["session"], "target_kind": "feature",
        "flags": [
            {"name": "--name", "type": "string", "required": True,
             "summary": "The new feature's name: a letter, then letters, digits or _, 31 at most."},
            {"name": "--sketch", "type": "json", "required": True, "schema": SKETCH_SCHEMA,
             "summary": "The sketch: plane, x_axis, references, entities, constraints and named dimensions, inline or a file."},
            {"name": "--depth", "type": "quantity", "quantity": "length", "summary": "How far to extrude; with --symmetric, split to both sides."},
            {"name": "--depth-name", "type": "string", "summary": "A name for the depth dimension, such as BODY_HEIGHT."},
            {"name": "--through-all", "type": "boolean", "summary": "Through the whole part, for a cut."},
            {"name": "--to", "type": "string", "summary": "Up to this plane or face: a datum name, a face such as BASE/end, or surface:<id>."},
            {"name": "--symmetric", "type": "boolean", "summary": "Extrude half of --depth to each side of the sketch plane."},
            {"name": "--direction", "type": "string", "summary": "The model axis to extrude along, such as +z; the plane's normal by default."},
            {"name": "--remove", "type": "boolean", "summary": "Remove material (a cut) instead of adding it."},
        ],
        "untrusted_fields": ["name", "dimensions[*].id"],
        "irreversible": False, "halt": False, "tolerances": {"value_mm": 0.000001}, "default_fields": [],
        "related_knowledge": ["creo-sketches", "creo-geometry-references", "creo-units"],
        "output_schema": {"type": "object", "properties": {
            **FEATURE_ITEM, "dimensions": {"type": "array", "items": {"type": "object"}}, "volume_mm3": NUM,
            "volume_change_mm3": NUM, "bounding_box_mm": {"type": ["object", "null"]}, "faces": {"type": "object"}}},
        "output_coordinate_system": MODEL, "doc_kinds": ["part"],
        "examples": [EXAMPLE.format(path="extrude create") + " --name BASE --depth 22mm --sketch body.json",
                     EXAMPLE.format(path="extrude create") + " --name SOCKET_CUT --remove --through-all --sketch socket.json"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "shell create",
        "summary": "Hollow the part into one shell feature with walls of one thickness, open at the faces named; regenerate.",
        "effects": ["change"], "modes": ["session"], "target_kind": "feature",
        "flags": [
            {"name": "--name", "type": "string", "required": True, "summary": "The new feature's name, such as SHELL."},
            {"name": "--thickness", "type": "quantity", "quantity": "length", "required": True, "summary": "The wall thickness, measured inward."},
            {"name": "--thickness-name", "type": "string", "summary": "A name for the thickness dimension, such as WALL."},
            {"name": "--remove", "type": "string",
             "summary": "The faces left open, separated by ;: such as BASE/start, BASE/side[+x] or surface:41. Without it the shell is closed."},
        ],
        "untrusted_fields": ["name", "dimensions[*].id"],
        "irreversible": False, "halt": False, "tolerances": {"value_mm": 0.000001}, "default_fields": [],
        "related_knowledge": ["creo-geometry-references", "creo-units"],
        "output_schema": {"type": "object", "properties": {
            **FEATURE_ITEM, "dimensions": {"type": "array", "items": {"type": "object"}}, "volume_mm3": NUM,
            "volume_change_mm3": NUM, "bounding_box_mm": {"type": ["object", "null"]}, "faces": {"type": "object"}}},
        "output_coordinate_system": MODEL, "doc_kinds": ["part"],
        "examples": [EXAMPLE.format(path="shell create") + " --name SHELL --thickness 2mm --thickness-name WALL --remove BASE/start"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "round create",
        "summary": "Round edges to one constant radius as one feature, and regenerate.",
        "effects": ["change"], "modes": ["session"], "target_kind": "feature",
        "flags": [
            {"name": "--name", "type": "string", "required": True, "summary": "The new feature's name, such as TOP_ROUND."},
            {"name": "--radius", "type": "quantity", "quantity": "length", "required": True, "summary": "The radius."},
            {"name": "--radius-name", "type": "string", "summary": "A name for the radius dimension, such as TOP_R."},
            {"name": "--edges", "type": "string", "required": True,
             "summary": "The edges, separated by ;: edge(BASE/end, BASE/side[+x]), BASE/end:outer-edges, BASE/end:edges, SOCKET:edges or edge:57."},
        ],
        "untrusted_fields": ["name", "dimensions[*].id"],
        "irreversible": False, "halt": False, "tolerances": {"value_mm": 0.000001}, "default_fields": [],
        "related_knowledge": ["creo-geometry-references", "creo-units"],
        "output_schema": {"type": "object", "properties": {
            **FEATURE_ITEM, "dimensions": {"type": "array", "items": {"type": "object"}}, "volume_mm3": NUM,
            "volume_change_mm3": NUM, "bounding_box_mm": {"type": ["object", "null"]}, "faces": {"type": "object"}}},
        "output_coordinate_system": MODEL, "doc_kinds": ["part"],
        "examples": [EXAMPLE.format(path="round create") + " --name TOP_ROUND --radius 2mm --edges BASE/end:outer-edges"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "pattern create",
        "summary": "Repeat one feature in a row along a model axis, as one pattern feature, and regenerate.",
        "effects": ["change"], "modes": ["session"], "target_kind": "feature",
        "flags": [
            {"name": "--name", "type": "string", "required": True, "summary": "The pattern's name, such as SOCKET_ROW."},
            {"name": "--feature", "type": "string", "required": True, "summary": "The feature to repeat, by name or ID."},
            {"name": "--along", "type": "string", "required": True, "summary": "The model axis the copies step along, such as +x."},
            {"name": "--count", "type": "integer", "required": True, "summary": "How many in all, the original included; 2 or more."},
            {"name": "--spacing", "type": "quantity", "quantity": "length", "required": True, "summary": "The step from one copy to the next."},
            {"name": "--spacing-name", "type": "string", "summary": "A name for the spacing dimension, such as OUTLET_PITCH."},
        ],
        "untrusted_fields": ["name", "dimensions[*].id"],
        "irreversible": False, "halt": False, "tolerances": {"value_mm": 0.000001}, "default_fields": [],
        "related_knowledge": ["creo-geometry-references", "creo-units"],
        "output_schema": {"type": "object", "properties": {
            **FEATURE_ITEM, "count": INT, "dimensions": {"type": "array", "items": {"type": "object"}}, "volume_mm3": NUM,
            "volume_change_mm3": NUM, "bounding_box_mm": {"type": ["object", "null"]}, "faces": {"type": "object"}}},
        "output_coordinate_system": MODEL, "doc_kinds": ["part"],
        "examples": [EXAMPLE.format(path="pattern create") + " --name SOCKET_ROW --feature SOCKET_CUT --along +x --count 4 --spacing 62mm --spacing-name OUTLET_PITCH"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "plane create",
        "summary": "Create a datum plane offset from a plane or planar face, or through an axis at an angle to a plane.",
        "effects": ["change"], "modes": ["session"], "target_kind": "feature",
        "flags": [
            {"name": "--name", "type": "string", "required": True, "summary": "The new datum plane's name, such as DTM_BOSS."},
            {"name": "--from", "type": "string", "required": True, "summary": "The plane or planar face it is measured from: TOP, BASE/start or surface:41."},
            {"name": "--distance", "type": "quantity", "quantity": "length", "summary": "The distance from --from."},
            {"name": "--direction", "type": "string", "summary": "With --distance: the model axis to offset toward, such as +y; the normal of --from by default."},
            {"name": "--distance-name", "type": "string", "summary": "A name for the distance dimension."},
            {"name": "--through", "type": "string", "summary": "With --angle: the datum axis the plane passes through."},
            {"name": "--angle", "type": "quantity", "quantity": "angle", "summary": "With --through: the angle from --from."},
            {"name": "--angle-name", "type": "string", "summary": "A name for the angle dimension."},
        ],
        "untrusted_fields": ["name", "dimensions[*].id"],
        "irreversible": False, "halt": False, "tolerances": {"value_mm": 0.000001, "value_deg": 0.000001}, "default_fields": [],
        "related_knowledge": ["creo-geometry-references", "creo-units"],
        "output_schema": {"type": "object", "properties": {**FEATURE_ITEM, "dimensions": {"type": "array", "items": {"type": "object"}}}},
        "output_coordinate_system": MODEL, "doc_kinds": ["part"],
        "examples": [EXAMPLE.format(path="plane create") + " --name DTM_BOSS --from BASE/start --distance 2mm --direction +y"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "axis create",
        "summary": "Create a datum axis where two planes cross, or through the axis of a cylindrical face.",
        "effects": ["change"], "modes": ["session"], "target_kind": "feature",
        "flags": [
            {"name": "--name", "type": "string", "required": True, "summary": "The new datum axis's name, such as A_BOSS."},
            {"name": "--planes", "type": "string", "summary": "Two planes separated by ;, such as RIGHT;FRONT."},
            {"name": "--through", "type": "string", "summary": "A cylindrical face, such as BOSS/side or surface:88."},
        ],
        "untrusted_fields": ["name"],
        "irreversible": False, "halt": False, "tolerances": {}, "default_fields": [],
        "related_knowledge": ["creo-geometry-references"],
        "output_schema": {"type": "object", "properties": FEATURE_ITEM},
        "output_coordinate_system": MODEL, "doc_kinds": ["part"],
        "examples": [EXAMPLE.format(path="axis create") + " --name A_CENTER --planes RIGHT;FRONT"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "chamfer create",
        "summary": "Chamfer edges by one distance on both faces as one feature, and regenerate.",
        "effects": ["change"], "modes": ["session"], "target_kind": "feature",
        "flags": [
            {"name": "--name", "type": "string", "required": True, "summary": "The new feature's name, such as EDGE_CHAMFER."},
            {"name": "--distance", "type": "quantity", "quantity": "length", "required": True, "summary": "The leg on each face."},
            {"name": "--distance-name", "type": "string", "summary": "A name for the distance dimension."},
            {"name": "--edges", "type": "string", "required": True,
             "summary": "The edges, separated by ;: edge(BASE/end, BASE/side[+x]), BASE/end:outer-edges, SOCKET:edges or edge:57."},
        ],
        "untrusted_fields": ["name", "dimensions[*].id"],
        "irreversible": False, "halt": False, "tolerances": {"value_mm": 0.000001}, "default_fields": [],
        "related_knowledge": ["creo-geometry-references", "creo-units"],
        "output_schema": {"type": "object", "properties": {
            **FEATURE_ITEM, "dimensions": {"type": "array", "items": {"type": "object"}}, "volume_mm3": NUM,
            "volume_change_mm3": NUM, "bounding_box_mm": {"type": ["object", "null"]}, "faces": {"type": "object"}}},
        "output_coordinate_system": MODEL, "doc_kinds": ["part"],
        "examples": [EXAMPLE.format(path="chamfer create") + " --name EDGE_CHAMFER --distance 0.5mm --edges SOCKET:edges"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "draft create",
        "summary": "Draft faces by one angle about a hinge plane so that they narrow toward the pull direction, as one feature.",
        "effects": ["change"], "modes": ["session"], "target_kind": "feature",
        "flags": [
            {"name": "--name", "type": "string", "required": True, "summary": "The new feature's name, such as OUTER_DRAFT."},
            {"name": "--faces", "type": "string", "required": True, "summary": "The faces to draft, separated by ;: such as BASE/side."},
            {"name": "--hinge", "type": "string", "required": True, "summary": "The plane the faces turn about: a datum, a face such as BASE/start, or surface:<id>."},
            {"name": "--pull", "type": "string", "required": True, "summary": "The model axis the mold opens along, such as +y; the faces narrow toward it."},
            {"name": "--angle", "type": "quantity", "quantity": "angle", "required": True, "summary": "The draft angle, under 30 degrees."},
            {"name": "--angle-name", "type": "string", "summary": "A name for the angle dimension, such as DRAFT_ANGLE."},
        ],
        "untrusted_fields": ["name", "dimensions[*].id"],
        "irreversible": False, "halt": False, "tolerances": {"value_deg": 0.000001}, "default_fields": [],
        "related_knowledge": ["creo-geometry-references", "creo-units"],
        "output_schema": {"type": "object", "properties": {
            **FEATURE_ITEM, "dimensions": {"type": "array", "items": {"type": "object"}}, "volume_mm3": NUM,
            "volume_change_mm3": NUM, "bounding_box_mm": {"type": ["object", "null"]}, "faces": {"type": "object"}}},
        "output_coordinate_system": MODEL, "doc_kinds": ["part"],
        "examples": [EXAMPLE.format(path="draft create") + " --name OUTER_DRAFT --faces BASE/side --hinge BASE/start --pull +y --angle 1deg"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "parameter create",
        "summary": "Create a model parameter of a type, with its value.",
        "effects": ["change"], "modes": ["session"], "target_kind": "parameter",
        "flags": [
            {"name": "--name", "type": "string", "required": True, "summary": "The parameter's name, such as POSITIONS."},
            {"name": "--type", "type": "string", "summary": "string (the default), integer, real or boolean."},
            {"name": "--value", "type": "string", "required": True, "summary": "The value: text, 4, 2.5, true or false."},
        ],
        "untrusted_fields": ["id", "name", "value"],
        "irreversible": False, "halt": False, "tolerances": {"value": 0.000001}, "default_fields": [],
        "related_knowledge": ["creo-relations-and-dimensions"],
        "output_schema": {"type": "object", "properties": PARAMETER_ITEM},
        "examples": [EXAMPLE.format(path="parameter create") + " --name POSITIONS --type integer --value 4"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "relation update",
        "summary": "Replace a model's relations and regenerate; the old relations come back when the model does not regenerate.",
        "effects": ["change"], "modes": ["session"], "target_kind": "relation",
        "flags": [
            {"name": "--relations", "type": "json", "required": True,
             "schema": {"type": "array", "items": {"type": "string"}},
             "summary": "Every relation line, as a JSON array of strings, inline or a file; an empty array removes them all."},
        ],
        "untrusted_fields": ["items[*].text"],
        "irreversible": False, "halt": False, "tolerances": {}, "default_fields": [],
        "related_knowledge": ["creo-relations-and-dimensions"],
        "output_schema": _items({"number": INT, "text": STR}),
        "examples": [EXAMPLE.format(path="relation update") + " --relations '[\"BODY_LENGTH = POSITIONS * OUTLET_PITCH + 32\"]'"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "model update",
        "summary": "Assign a part's material from the part or Creo's material library, or change a model's common name.",
        "effects": ["change"], "modes": ["session"], "target_kind": "model",
        "flags": [
            {"name": "--material", "type": "string", "summary": "A material's name, as material list shows it, such as ABS."},
            {"name": "--common-name", "type": "string", "summary": "The model's common name."},
        ],
        "untrusted_fields": ["material", "common_name"],
        "irreversible": False, "halt": False, "tolerances": {}, "default_fields": [],
        "related_knowledge": ["creo-materials"],
        "output_schema": {"type": "object", "properties": {"material": {"type": ["string", "null"]}, "common_name": {"type": ["string", "null"]}}},
        "examples": [EXAMPLE.format(path="model update") + " --material ABS"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "feature delete",
        "summary": "Delete a feature with the features that depend on it; the preview lists them all. Nothing brings them back but closing without saving.",
        "effects": ["change"], "modes": ["session"], "target_kind": "feature",
        "flags": [{"name": "--id", "type": "string", "required": True, "summary": "The feature's ID or name."}],
        "untrusted_fields": ["deleted[*]"],
        "irreversible": True, "halt": False, "tolerances": {}, "default_fields": [],
        "related_knowledge": ["creo-localized-names"],
        "output_schema": {"type": "object", "properties": {"deleted": {"type": "array", "items": STR}}},
        "doc_kinds": SOLID,
        "examples": [EXAMPLE.format(path="feature delete") + " --id SOCKET_CUT"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "model export",
        "summary": "Write a part or assembly to STEP, IGES or STL, or a drawing to PDF; the file extension picks the format.",
        "effects": ["artifact"], "modes": ["session"], "target_kind": "file",
        "flags": [{"name": "--output", "type": "path", "required": True, "output": True,
                   "summary": "The new file: .stp or .step, .igs or .iges, .stl, or .pdf for a drawing."}],
        "untrusted_fields": [],
        "irreversible": False, "halt": False, "tolerances": {}, "default_fields": [], "related_knowledge": ["creo-save-versions"],
        "output_schema": {"type": "object", "properties": {"path": STR, "format": STR, "bytes": INT}},
        # A large assembly's STEP export takes Creo minutes, so the runtime runs it as a long job.
        "long": True,
        "examples": [EXAMPLE.format(path="model export") + " --output D:/work/out/bracket.stp"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "model render",
        "summary": "Write a JPEG image of a part or assembly as its window shows it.",
        "effects": ["artifact"], "modes": ["session"], "target_kind": "file",
        "flags": [
            {"name": "--output", "type": "path", "required": True, "output": True, "summary": "The new .jpg file."},
            {"name": "--width", "type": "integer", "summary": "Image width in pixels, 1 to 4096; 1024 by default."},
            {"name": "--height", "type": "integer", "summary": "Image height in pixels, 1 to 4096; 768 by default."},
        ],
        "untrusted_fields": [],
        "irreversible": False, "halt": False, "tolerances": {}, "default_fields": [], "related_knowledge": ["creo-display-requirements"],
        "output_schema": {"type": "object", "properties": {"path": STR, "width": INT, "height": INT, "bytes": INT}},
        "doc_kinds": SOLID,
        "examples": [EXAMPLE.format(path="model render") + " --output D:/work/out/bracket.jpg"],
        "maturity": "draft", "evidence": [],
    },
]

for _reg in COMMANDS:
    _reg.update(MATURITY.get(_reg["path"], {}))
