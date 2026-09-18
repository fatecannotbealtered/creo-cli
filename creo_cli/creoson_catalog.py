"""Audited CREOSON allowlist: request schemas, safe wire defaults and readback rules.

Only entries in this table are exposed. No arbitrary command/function passthrough.
API field names are based on published CREOSON/Creopyson interfaces; see SOURCES.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .core import Error, number

SOURCES = {
    "file": ("Zepmanbc/creopyson", "creopyson/file.py", "228f71eb3fcb3a34764c4dc145686b79fffdf9b8"),
    "parameter": ("Zepmanbc/creopyson", "creopyson/parameter.py", "cba1c8decb1c851bcea14f224b601baef4f93023"),
    "dimension": ("Zepmanbc/creopyson", "creopyson/dimension.py", "91e4c616f23edeab574bb270510be245137c9009"),
    "feature": ("Zepmanbc/creopyson", "creopyson/feature.py", "fb2d7892d0c192bf68b700512e48ec886e3ca6e3"),
    "interface": ("Zepmanbc/creopyson", "creopyson/interface.py", "997640a896b69c0482dc0a3a1ef285a747d353c1"),
    "view": ("Zepmanbc/creopyson", "creopyson/view.py", "ebdae69b795ef042f67da9f601781fa9b2b33e20"),
    "drawing": ("Zepmanbc/creopyson", "creopyson/drawing.py", "e0ad14a5f1c5da6b261efc16efb8181432c4bf68"),
    "bom": ("Zepmanbc/creopyson", "creopyson/bom.py", "611209b7f6695bdce8f3d08bdaa4096d3bbdef54"),
    "creo": ("Zepmanbc/creopyson", "creopyson/creo.py", "678c83bdcafd67c5a838959c9080a20989c29d80"),
    "connection": ("Zepmanbc/creopyson", "creopyson/connection.py", "cc1bd8ebf59f3139d1906fda9e159e16bd78c109"),
}


def obj(properties: dict, required: tuple | None = None) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(properties if required is None else required), "additionalProperties": False}


def text(*, enum: tuple = (), pattern: str | None = None, maximum: int = 256) -> dict:
    result: dict = {"type": "string", "minLength": 1, "maxLength": maximum}
    if enum:
        result["enum"] = list(enum)
    if pattern:
        result["pattern"] = pattern
    return result


NAME = text(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,79}$")
MODEL = text(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,79}\.(?:prt|asm|drw)$")
PART = text(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,79}\.prt$")
ASM = text(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,79}\.asm$")
DRAWING = text(pattern=r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,79}\.drw$")
NUM = {"type": "number", "minimum": -1e9, "maximum": 1e9}
POS = {"type": "number", "exclusiveMinimum": 0, "maximum": 1e9}
BOOL = {"type": "boolean"}
SHEET = {"type": "integer", "minimum": 1, "maximum": 10000}
PATH = text(maximum=2048)
POINT = obj({"x": NUM, "y": NUM, "z": NUM}, ("x", "y"))
VECTOR = obj({"x": NUM, "y": NUM, "z": NUM})
LENGTH = text(enum=("mm", "cm", "m", "in", "ft"))
F = {"file": MODEL}
D = {"drawing": DRAWING}
PARAM_VALUE = {"type": ["string", "number", "boolean"], "maxLength": 4000}
CONSTRAINT = obj({"type": text(enum=("csys", "fix")), "asmref": NAME, "compref": NAME}, ("type",))


@dataclass(frozen=True)
class Operation:
    path: str
    command: str
    function: str
    description: str
    request_schema: dict
    response_fields: tuple
    example: dict
    write: bool = False
    target_keys: tuple = ("file",)
    defaults: dict = field(default_factory=dict)
    local_keys: tuple = ()
    verifier: str = "observation"
    list_key: str | None = None
    effect: str = "read"
    dangerous: bool = False
    version_required: bool = False
    interaction_risks: tuple = ()

    def source(self) -> dict:
        repo, path, sha = SOURCES[self.command]
        return {"repository": repo, "path": path, "git_blob_sha": sha,
                "protocol_target": "CREOSON 3.0.2", "source_kind": "published_source_snapshot", "live_verified": False}

    def validate(self, request: Any) -> dict:
        validate(request, self.request_schema)
        q = dict(request)
        if self.path == "parameter set":
            kind, value = q["type"], q["value"]
            matches = {"STRING": type(value) is str, "DOUBLE": number(value),
                       "INTEGER": type(value) is int and -(2**31) <= value < 2**31,
                       "BOOL": type(value) is bool}
            if not matches[kind]:
                raise Error("E_VALIDATION", "parameter value does not match its explicit type")
        if self.path == "assembly assemble":
            constraints = q["constraints"]
            if len(constraints) != 1:
                raise Error("E_UNSUPPORTED", "this adapter supports exactly one coordinate-system or fixed constraint")
            c = constraints[0]
            if c["type"] == "csys":
                if set(c) != {"type", "asmref", "compref"} or "transform" in q:
                    raise Error("E_VALIDATION", "csys constraint needs explicit asmref/compref and no transform")
            elif set(c) != {"type"} or "transform" not in q:
                raise Error("E_VALIDATION", "fixed assembly needs an explicit transform and no implicit selection")
        if self.path == "drawing project-view":
            p = q["point"]
            if (p.get("x", 0) == 0) == (p.get("y", 0) == 0):
                raise Error("E_VALIDATION", "projection offset must have exactly one nonzero x or y coordinate")
        if self.path.startswith("export "):
            import re
            suffix = {"export step": r"\.(?:stp|step)$", "export iges": r"\.(?:igs|iges)$",
                      "export dxf": r"\.dxf$", "export pdf": r"\.pdf$", "export image": r"\.(?:jpg|jpeg)$"}[self.path]
            if not re.search(suffix, q["filename"], re.I) or any(x in q["filename"] for x in ("/", "\\", ":", "..", "*", "?")):
                raise Error("E_VALIDATION", "export filename must be a basename with the matching extension")
        return q

    def wire(self, request: dict) -> dict:
        return self.defaults | {k: v for k, v in request.items() if k not in self.local_keys}


def validate(value: Any, schema: dict, path: str = "request", depth: int = 0) -> None:
    """Strict input subset shared with workflow manifests; reject unknown fields."""
    import re
    if depth > 24:
        raise Error("E_VALIDATION", "request nesting limit exceeded")
    kinds = schema.get("type", [])
    kinds = [kinds] if isinstance(kinds, str) else kinds
    matches = {"object": type(value) is dict, "array": type(value) is list,
               "string": type(value) is str, "integer": type(value) is int,
               "number": number(value), "boolean": type(value) is bool, "null": value is None}
    if kinds and not any(matches[k] for k in kinds):
        raise Error("E_VALIDATION", "wrong request value type", {"path": path})
    if "enum" in schema and value not in schema["enum"]:
        raise Error("E_VALIDATION", "unsupported request value", {"path": path, "allowed": schema["enum"]})
    if isinstance(value, dict):
        props = schema.get("properties", {})
        if set(value) - set(props) or set(schema.get("required", [])) - set(value):
            raise Error("E_VALIDATION", "request has missing or unknown fields",
                        {"path": path, "unknown": sorted(set(value) - set(props)),
                         "missing": sorted(set(schema.get("required", [])) - set(value))})
        for k, v in value.items():
            validate(v, props[k], path + "." + k, depth + 1)
    elif isinstance(value, list):
        if not schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 1000):
            raise Error("E_VALIDATION", "request list size out of range", {"path": path})
        for v in value:
            validate(v, schema.get("items", {}), path + "[]", depth + 1)
    elif isinstance(value, str):
        if (not schema.get("minLength", 0) <= len(value) <= schema.get("maxLength", 4000)
                or (schema.get("pattern") and not re.fullmatch(schema["pattern"], value))
                or "\x00" in value):
            raise Error("E_VALIDATION", "invalid request string", {"path": path})
    elif number(value):
        if (("minimum" in schema and value < schema["minimum"])
                or ("maximum" in schema and value > schema["maximum"])
                or ("exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"])):
            raise Error("E_VALIDATION", "request number out of range", {"path": path})


OPS: list[Operation] = []


def add(path, command, function, description, props, response, example, **kw):
    required = kw.pop("required", None)
    OPS.append(Operation(path, command, function, description, obj(props, required), tuple(response), example, **kw))


# Reads are named, bounded observations; no wildcard model targets or UI selection.
add("file list", "file", "list", "List currently loaded models", {}, ("files",), {}, target_keys=(), list_key="files")
add("file active", "file", "get_active", "Read the active model without switching windows", {}, ("file", "dirname"), {}, target_keys=())
add("file info", "file", "get_fileinfo", "Read explicit model file information", F, ("file", "dirname", "revision"), {"file": "bracket.prt"})
add("file units", "file", "get_length_units", "Read length and mass units without conversion", F, ("length_units", "mass_units"), {"file": "bracket.prt"}, verifier="units")
add("file massprops", "file", "massprops", "Read model mass properties and unit context; density validity is not assumed", F,
    ("volume", "mass", "density", "surface_area", "ctr_grav", "coord_sys_inertia", "coord_sys_inertia_tensor", "ctr_grav_inertia_tensor", "unit_context"), {"file": "bracket.prt"}, verifier="massprops")
add("file relations", "file", "relations_get", "Read relations without evaluating them in the CLI", F, ("relations",), {"file": "bracket.prt"}, list_key="relations")
add("file instances", "file", "list_instances", "List family-table instances, not create them", F, ("generic", "dirname", "files"), {"file": "bracket.prt"}, list_key="files")
add("parameter list", "parameter", "list", "Read typed model parameters", F | {"name": NAME}, ("paramlist",), {"file": "bracket.prt"}, required=("file",), defaults={"encoded": False}, list_key="paramlist")
add("dimension list", "dimension", "list_detail", "Read dimension values, types and drawing context without selecting", F | {"name": NAME}, ("dimlist",), {"file": "bracket.prt"}, required=("file",), defaults={"encoded": False, "select": False}, list_key="dimlist")
add("feature list", "feature", "list", "Read reported visible feature identities/statuses, including unnamed features", F, ("featlist",), {"file": "bracket.prt"}, defaults={"paths": True, "inc_unnamed": True}, list_key="featlist")
add("material list", "file", "list_materials", "Read materials already loaded on a part", {"file": PART}, ("materials",), {"file": "bracket.prt"}, list_key="materials")
add("material current", "file", "get_cur_material", "Read the part's assigned material", {"file": PART}, ("material",), {"file": "bracket.prt"})
add("view list", "view", "list", "List named model orientations", F, ("viewlist",), {"file": "bracket.prt"}, list_key="viewlist")
add("assembly tree", "bom", "get_paths", "Read component hierarchy; upstream omits inactive/unregenerated components", {"file": ASM}, ("file", "generic", "children", "has_simprep"), {"file": "device.asm"}, defaults={"paths": True, "get_transforms": True, "skeletons": True})
add("assembly transform", "file", "get_transform", "Read a specific component occurrence transform", {"asm": ASM, "path": {"type": "array", "items": text(pattern=r"^[0-9]{1,10}$"), "minItems": 1, "maxItems": 32}}, ("origin", "x_axis", "y_axis", "z_axis", "x_rot", "y_rot", "z_rot"), {"asm": "device.asm", "path": ["39"]}, target_keys=("asm",))

# Session-model operations. Every one goes through preview/confirm, local policy and journal.
W = {"write": True, "effect": "memory"}
add("file open", "file", "open", "Open one explicit working-copy model; never replaces an already-loaded name", F | {"dirname": PATH}, ("files", "dirname", "revision"), {"file": "bracket.prt", "dirname": "."}, defaults={"display": True, "activate": True, "new_window": False, "regen_force": False}, verifier="open", **W)
add("file display", "file", "display", "Display and activate a specific loaded model", F, (), {"file": "bracket.prt"}, defaults={"activate": True}, verifier="active", **W)
add("file regenerate", "file", "regenerate", "Regenerate once and read feature statuses; not a full design check", F, (), {"file": "bracket.prt"}, defaults={"display": False}, verifier="regenerate", version_required=True, **W)
add("file close-window", "file", "close_window", "Close only the model window; does not erase or claim to save", F, (), {"file": "bracket.prt"}, verifier="acknowledgement", effect="ui", write=True)
add("file save", "file", "save", "Save a named working-copy model with pre-save byte backup and artifact inventory", F, (), {"file": "bracket.prt"}, verifier="save", effect="disk", write=True)
add("file backup", "file", "backup", "Back up a model and dependencies into a new workspace directory", F | {"target_dir": PATH}, (), {"file": "bracket.prt", "target_dir": "backup_bracket"}, verifier="backup", effect="disk", write=True)
add("parameter set", "parameter", "set", "Set or explicitly create one typed parameter and read it back", F | {"name": NAME, "type": text(enum=("STRING", "DOUBLE", "INTEGER", "BOOL")), "value": PARAM_VALUE, "create": BOOL}, (), {"file": "bracket.prt", "name": "PART_NO", "type": "STRING", "value": "BRK-001", "create": False}, local_keys=("create",), defaults={"encoded": False}, verifier="parameter", **W)
add("dimension set", "dimension", "set", "Set an existing dimension with explicit length units and readback", F | {"name": NAME, "value": POS, "expected_length_units": LENGTH}, (), {"file": "bracket.prt", "name": "d1", "value": 45, "expected_length_units": "mm"}, local_keys=("expected_length_units",), defaults={"encoded": False}, verifier="dimension", **W)
add("feature suppress", "feature", "suppress", "Suppress exactly one named feature; never clip or include children", F | {"name": NAME}, (), {"file": "bracket.prt", "name": "HOLE_1"}, defaults={"clip": False, "with_children": False}, verifier="suppress", version_required=True, **W)
add("feature resume", "feature", "resume", "Resume exactly one named feature", F | {"name": NAME}, (), {"file": "bracket.prt", "name": "HOLE_1"}, defaults={"with_children": False}, verifier="resume", version_required=True, **W)
add("feature rename", "feature", "rename", "Rename one explicitly named feature and read it back", F | {"name": NAME, "new_name": NAME}, (), {"file": "bracket.prt", "name": "HOLE_1", "new_name": "MOUNT_HOLE"}, verifier="feature_name", **W)
add("material assign", "file", "set_cur_material", "Assign a material already present in a part; never assumes a density", {"file": PART, "material": NAME}, ("files",), {"file": "bracket.prt", "material": "ALUMINUM"}, verifier="material", **W)
add("view activate", "view", "activate", "Apply an existing named model orientation", F | {"name": NAME}, (), {"file": "bracket.prt", "name": "FRONT"}, verifier="acknowledgement", effect="ui", write=True)
add("view save", "view", "save", "Save the current orientation as a new named view", F | {"name": NAME}, (), {"file": "bracket.prt", "name": "REVIEW"}, verifier="view", **W)
add("assembly assemble", "file", "assemble", "Assemble one loaded part using explicit csys or fixed placement; never prompts", {"file": PART, "into_asm": ASM, "constraints": {"type": "array", "items": CONSTRAINT, "minItems": 1, "maxItems": 1}, "transform": obj({"origin": VECTOR, "x_rot": NUM}, ("origin",)), "expected_length_units": LENGTH}, ("files", "dirname", "revision", "featureid"), {"file": "bracket.prt", "into_asm": "device.asm", "constraints": [{"type": "csys", "asmref": "ASM_DEF_CSYS", "compref": "PRT_CSYS_DEF"}], "expected_length_units": "mm"}, required=("file", "into_asm", "constraints", "expected_length_units"), target_keys=("file", "into_asm"), defaults={"package_assembly": True, "walk_children": False, "assemble_to_root": True, "suppress": False}, local_keys=("expected_length_units",), verifier="assemble", version_required=True, **W)

# Drawing template + explicit views. Coordinates are in drawing units, never silently in mm.
add("drawing create", "drawing", "create", "Create a named drawing from a local drawing template", {"template": PATH, "model": MODEL, "drawing": DRAWING, "scale": POS}, ("drawing",), {"template": "templates/a4.drw", "model": "bracket.prt", "drawing": "bracket.drw", "scale": 1}, target_keys=("model", "drawing"), defaults={"display": True, "activate": True, "new_window": False}, verifier="drawing_create", interaction_risks=("upstream_may_open_modal_error_dialog", "client_timeout_does_not_cancel_creo"), **W)
add("drawing add-model", "drawing", "add_model", "Add a loaded model to a named drawing", D | {"model": MODEL}, (), {"drawing": "bracket.drw", "model": "bracket.prt"}, target_keys=("drawing", "model"), verifier="drawing_models", **W)
add("drawing add-sheet", "drawing", "add_sheet", "Append one sheet to a named drawing", D, (), {"drawing": "bracket.drw"}, target_keys=("drawing",), defaults={"position": 0}, verifier="drawing_sheets", **W)
add("drawing create-view", "drawing", "create_gen_view", "Create an explicit general view in drawing units", D | {"model": MODEL, "model_view": NAME, "view": NAME, "sheet": SHEET, "point": POINT, "scale": POS, "coordinate_units": text(enum=("drawing_units",))}, (), {"drawing": "bracket.drw", "model": "bracket.prt", "model_view": "FRONT", "view": "FRONT_MAIN", "sheet": 1, "point": {"x": 100, "y": 100}, "scale": 1, "coordinate_units": "drawing_units"}, target_keys=("drawing", "model"), local_keys=("coordinate_units",), defaults={"exploded": False}, verifier="drawing_views", **W)
add("drawing project-view", "drawing", "create_proj_view", "Create one aligned projected view with an explicit parent and offset", D | {"parent_view": NAME, "view": NAME, "sheet": SHEET, "point": POINT, "coordinate_units": text(enum=("drawing_units",))}, (), {"drawing": "bracket.drw", "parent_view": "FRONT_MAIN", "view": "RIGHT_PROJECTED", "sheet": 1, "point": {"x": 100, "y": 0}, "coordinate_units": "drawing_units"}, target_keys=("drawing",), local_keys=("coordinate_units",), defaults={"exploded": False}, verifier="drawing_views", **W)
add("drawing regenerate", "drawing", "regenerate", "Regenerate a named drawing; does not certify dimensions or tolerances", D, (), {"drawing": "bracket.drw"}, target_keys=("drawing",), verifier="acknowledgement", **W)

for label, kind, ext in (("step", "STEP", "step"), ("iges", "IGES", "igs"), ("dxf", "DXF", "dxf")):
    add("export " + label, "interface", "export_file", "Export " + kind + " into a new explicit file, then verify bytes and header",
        F | {"filename": NAME | {"pattern": r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,120}$"}, "dirname": PATH},
        ("filename", "dirname"), {"file": "bracket.prt", "filename": "bracket." + ext, "dirname": "exports"},
        defaults={"type": kind, **({"geom_flags": "solids"} if kind in ("STEP", "IGES") else {})},
        verifier="export", effect="disk", write=True)
add("export pdf", "interface", "export_pdf", "Export a named model/drawing to PDF with explicit all-sheet policy", F | {"filename": text(maximum=128), "dirname": PATH}, ("filename", "dirname"), {"file": "bracket.drw", "filename": "bracket.pdf", "dirname": "exports"}, defaults={"sheet_range": "all", "use_drawing_settings": True}, verifier="export", effect="disk", write=True)
add("export image", "interface", "export_image", "Export a JPEG review image; validates file bytes, not visual correctness", F | {"filename": text(maximum=128), "dirname": PATH, "dpi": {"type": "integer", "enum": [100, 200, 300, 400, 500, 600]}}, ("filename", "dirname"), {"file": "bracket.prt", "filename": "bracket.jpg", "dirname": "exports", "dpi": 200}, defaults={"type": "JPEG", "depth": 24}, verifier="export", effect="disk", write=True)

add("drawing models", "drawing", "list_models", "Read models contained in a named drawing", D, ("files",), {"drawing": "bracket.drw"}, target_keys=("drawing",), list_key="files")
add("drawing sheets", "drawing", "get_num_sheets", "Read the sheet count", D, ("num_sheets",), {"drawing": "bracket.drw"}, target_keys=("drawing",))
add("drawing views", "drawing", "list_view_details", "Read view names, sheets, positions and referenced models", D, ("views",), {"drawing": "bracket.drw"}, target_keys=("drawing",), list_key="views")
add("file roundtrip", "file", "save", "Save, close, erase only one isolated part, reopen and compare observed design data", {"file": PART},
    ("roundtrip_verified", "artifacts", "compared_sections"), {"file": "bracket.prt"}, verifier="roundtrip", effect="disk_and_memory", write=True)
BY_PATH = {op.path: op for op in OPS}
