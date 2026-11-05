"""The domain commands of creo-cli, as registrations (DCLI-029).

Each command is one dict. The runtime checks every field when the tool starts and refuses a
registration that breaks a rule, so a mistake shows up at once. A command needs:

- ``path``: ``noun verb`` in lowercase words, the noun taken from Creo Parametric's object model
- ``summary``: one line
- ``effects``: what it changes (DCLI-051); the runtime derives the confirmation and risk tiers
- ``modes``, ``target_kind``, ``flags`` (with a unit for every physical quantity), ``untrusted_fields``
- ``adapter_capabilities``: the adapter methods it calls (DCLI-260)
- ``survey_ids``: the capability IDs of docs/APPLICATION.md it provides (DREPO-061)
- ``irreversible``, ``halt``, ``tolerances``, ``default_fields``, ``related_knowledge``
- ``output_schema``, ``examples``, ``maturity`` and ``evidence``

Every command also gets a behavior matrix in tests/matrix/; its ``normal`` row is the write
sample (DVER-002, DVER-030). Run ``python scripts/spec.py generate`` after a change.

Objects inside a model are named by their target keys (DCLI-028): the document's key followed
by ``#/dimensions/<name>``, ``#/parameters/<name>`` or ``#/features/<id>``.
"""
from __future__ import annotations

from typing import Any

MODEL = "the model's default coordinate system; lengths in mm"
READ = ["read"]
WRITE = ["read", "preview", "apply", "read_back"]
EXAMPLE = "creo-cli {path} --session creo-9184-1d9a4c2e --doc D:/work/bracket.prt"

LIMIT = {"name": "--limit", "type": "integer", "summary": "At most this many items, 1 to 1000; 100 by default."}
OFFSET = {"name": "--offset", "type": "integer", "summary": "Skip this many items first."}


def _items(item: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": {
        "items": {"type": "array", "items": {"type": "object", "properties": item}},
        "total": {"type": "integer"}}}


def _read(path: str, summary: str, target_kind: str, flags: list[dict[str, Any]], output: dict[str, Any],
          survey: list[str], untrusted: list[str], example: str = "", **extra: Any) -> dict[str, Any]:
    return {
        "path": path, "summary": summary, "effects": ["observe"], "modes": ["session"],
        "target_kind": target_kind, "flags": flags, "untrusted_fields": untrusted,
        "adapter_capabilities": READ, "survey_ids": survey, "irreversible": False, "halt": False,
        "tolerances": {}, "default_fields": [], "related_knowledge": [], "output_schema": output,
        "examples": [EXAMPLE.format(path=path) + example], "maturity": "draft", "evidence": [], **extra,
    }


STR = {"type": "string"}
NUM = {"type": "number"}
INT = {"type": "integer"}
BOOL = {"type": "boolean"}

FEATURE_ITEM = {"id": INT, "number": INT, "name": STR, "type": STR, "status": STR}
DIMENSION_ITEM = {
    "name": STR, "kind": STR, "feature_id": INT, "value_mm": NUM, "value_deg": NUM,
    "driven_by_relation": BOOL, "tolerance": {"type": "object"},
}

# The first read with untrusted fields takes --id: the conformance suite checks the marking of
# untrusted fields on the first such read, with a field on the object it names.
COMMANDS: list[dict[str, Any]] = [
    _read(
        "feature get", "One feature: its dimensions, parents and children.",
        "feature", [{"name": "--id", "type": "string", "required": True,
                     "summary": "The feature's ID, such as 12, or its name."}],
        {"type": "object", "properties": {
            **FEATURE_ITEM, "dimensions": {"type": "array", "items": {"type": "object", "properties": DIMENSION_ITEM}},
            "parents": {"type": "array"}, "children": {"type": "array"}}},
        ["CAP-011"], ["name", "parents[*].name", "children[*].name"], " --id 12", related_knowledge=["creo-localized-names"],
    ),
    _read(
        "model get", "A model's summary: kind, units, material, mass properties, bounding box and feature count.",
        "model", [],
        {"type": "object", "properties": {
            "name": STR, "kind": STR, "units": {"type": "object"}, "material": {"type": ["string", "null"]},
            "volume_mm3": NUM, "surface_area_mm2": NUM, "mass_kg": {"type": ["number", "null"]},
            "density_kg_per_mm3": {"type": ["number", "null"]}, "center_of_mass_mm": {"type": "array"},
            "bounding_box_mm": {"type": "object"}, "feature_count": INT}},
        ["CAP-001"], ["name", "material"], output_coordinate_system=MODEL, related_knowledge=["creo-units", "creo-materials"],
    ),
    _read(
        "feature list", "The features of a model in regeneration order: ID, number, name, type and status.",
        "feature", [LIMIT, OFFSET], _items(FEATURE_ITEM), ["CAP-010"], ["name"], related_knowledge=["creo-localized-names"],
    ),
    _read(
        "geometry list", "Faces, edges, axes, datum planes and coordinate systems with the references other commands take.",
        "geometry", [
            {"name": "--kind", "type": "string",
             "summary": "Only this kind: surface, edge, axis, datum-plane or coordinate-system."},
            {"name": "--feature", "type": "string", "summary": "Only the geometry this feature created: its ID or name."},
            LIMIT, OFFSET],
        _items({"reference": STR, "kind": STR, "shape": STR, "feature_id": INT, "name": STR}),
        ["CAP-030"], ["name"], " --kind surface", output_coordinate_system=MODEL, related_knowledge=["creo-geometry-references", "creo-units"],
    ),
    _read(
        "distance get", "The shortest distance between two geometry references, as Creo measures it.",
        "geometry", [
            {"name": "--from", "type": "string", "required": True,
             "summary": "A reference from geometry list, such as surface:41, or a datum name such as FRONT."},
            {"name": "--to", "type": "string", "required": True, "summary": "A second reference, as --from."}],
        {"type": "object", "properties": {"from": STR, "to": STR, "distance_mm": NUM}},
        ["CAP-031"], [], " --from FRONT --to surface:41", related_knowledge=["creo-geometry-references", "creo-units"],
    ),
    _read(
        "dimension list", "The dimensions of a model, or of one feature: name, kind, value, tolerance and owner.",
        "dimension", [{"name": "--feature", "type": "string", "summary": "Only this feature's dimensions: its ID or name."},
                      LIMIT, OFFSET],
        _items(DIMENSION_ITEM), ["CAP-032"], [], related_knowledge=["creo-relations-and-dimensions", "creo-units"],
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
        "untrusted_fields": [], "adapter_capabilities": WRITE, "survey_ids": ["CAP-033", "CAP-034"],
        "irreversible": False, "halt": False,
        "tolerances": {"value_mm": 0.000001, "value_deg": 0.000001, "plus_mm": 0.000001, "minus_mm": 0.000001,
                       "upper_mm": 0.000001, "lower_mm": 0.000001},
        "default_fields": [], "related_knowledge": ["creo-relations-and-dimensions", "creo-units"],
        "output_schema": {"type": "object", "properties": DIMENSION_ITEM},
        "examples": [EXAMPLE.format(path="dimension update") + " --id d12 --length 25mm",
                     EXAMPLE.format(path="dimension update") + " --id d12 --plus 0.1mm --minus 0.05mm"],
        "maturity": "draft", "evidence": [],
    },
    _read(
        "parameter list", "A model's parameters: name, type, value, unit and whether a relation drives it.",
        "parameter", [LIMIT, OFFSET],
        _items({"name": STR, "type": STR, "value": {}, "unit": {"type": ["string", "null"]}, "driven_by_relation": BOOL}),
        ["CAP-035"], ["name", "value"], related_knowledge=["creo-relations-and-dimensions"],
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
        "untrusted_fields": ["name", "value"], "adapter_capabilities": WRITE, "survey_ids": ["CAP-035"],
        "irreversible": False, "halt": False, "tolerances": {"value": 0.000001}, "default_fields": [],
        "related_knowledge": ["creo-relations-and-dimensions", "creo-units"],
        "output_schema": {"type": "object", "properties": {"name": STR, "type": STR, "value": {}, "unit": {"type": ["string", "null"]}}},
        "examples": [EXAMPLE.format(path="parameter update") + " --id MATERIAL_CODE --value CC-001"],
        "maturity": "draft", "evidence": [],
    },
    _read(
        "relation list", "A model's relations, one per line, as Tools > Relations shows them.",
        "relation", [], {"type": "object", "properties": {"lines": {"type": "array", "items": STR}}},
        ["CAP-036"], ["lines[*]"], related_knowledge=["creo-relations-and-dimensions"],
    ),
    _read(
        "material list", "The materials in Creo's material library and the model's own materials, with the one assigned.",
        "material", [{"name": "--query", "type": "string", "summary": "Only materials whose name contains this text."},
                     LIMIT, OFFSET],
        _items({"name": STR, "source": STR, "assigned": BOOL}), ["CAP-040"], ["name"], related_knowledge=["creo-materials"],
    ),
    _read(
        "component list", "The top-level components of an assembly: model, status and position.",
        "component", [LIMIT, OFFSET],
        _items({"id": INT, "model": STR, "kind": STR, "status": STR, "origin_mm": {"type": "array"}}),
        ["CAP-050"], ["model"], output_coordinate_system="the assembly's default coordinate system; lengths in mm", related_knowledge=["creo-units"],
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
        "untrusted_fields": ["name"], "adapter_capabilities": WRITE, "survey_ids": ["CAP-012"],
        "irreversible": False, "halt": False, "tolerances": {}, "default_fields": [], "related_knowledge": ["creo-localized-names"],
        "output_schema": {"type": "object", "properties": FEATURE_ITEM},
        "examples": [EXAMPLE.format(path="feature update") + " --id 12 --status suppressed"],
        "maturity": "draft", "evidence": [],
    },
    {
        "path": "model export",
        "summary": "Write a part or assembly to STEP, IGES or STL, or a drawing to PDF; the file extension picks the format.",
        "effects": ["artifact"], "modes": ["session"], "target_kind": "file",
        "flags": [{"name": "--output", "type": "path", "required": True, "output": True,
                   "summary": "The new file: .stp or .step, .igs or .iges, .stl, or .pdf for a drawing."}],
        "untrusted_fields": [], "adapter_capabilities": WRITE, "survey_ids": ["CAP-003"],
        "irreversible": False, "halt": False, "tolerances": {}, "default_fields": [], "related_knowledge": ["creo-save-versions"],
        "output_schema": {"type": "object", "properties": {"path": STR, "format": STR, "bytes": INT}},
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
        "untrusted_fields": [], "adapter_capabilities": WRITE, "survey_ids": ["CAP-004"],
        "irreversible": False, "halt": False, "tolerances": {}, "default_fields": [], "related_knowledge": ["creo-display-requirements"],
        "output_schema": {"type": "object", "properties": {"path": STR, "width": INT, "height": INT, "bytes": INT}},
        "examples": [EXAMPLE.format(path="model render") + " --output D:/work/out/bracket.jpg"],
        "maturity": "draft", "evidence": [],
    },
]
