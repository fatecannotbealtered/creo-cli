"""Existing direct occurrences: frozen planar constraints and independent solved poses.

The native setter never supplies its own verification. The same predicate is used by
confirmation, query, registration and retained-proof inspection. No replay or rollback.
"""

from __future__ import annotations

import math
from copy import deepcopy

from . import building, engine, machining, operations, safety
from .core import Error, digest, page, read_request
from .validation import strict, text, validate

PROFILE = "direct-planar-constraints-v2"
COMMAND = "assembly component redefine"
CAPABILITY = "assembly_constraint_redefinition"
CAPABILITY_VERSION = 2
SIDES = ("DATUM_SIDE_YELLOW", "DATUM_SIDE_RED", "DATUM_SIDE_NONE")
TOL = 1e-7  # mm and unit-vector residual; not an engineering/manufacturing tolerance.
# Public ProElemId.h values, also present in the committed feature-tree contract.
DATUM_CONSTRAINT_ARRAY = 410
DATUM_ELEMENTS = {"type": 412, "reference": 413, "offset": 414}
REFERENCE_SCHEMA = strict(
    {
        "model": text(maximum=40),
        "item_id": {"type": "integer", "minimum": 0},
        "item_type": text(enum=("ITEM_SURFACE",)),
        "component_path": {
            "type": "array",
            "items": {"type": "integer", "minimum": 0},
            "maxItems": 1,
        },
    },
    ("model", "item_id", "item_type", "component_path"),
)
CONSTRAINT_SCHEMA = strict(
    {
        "type": text(enum=("mate", "align")),
        "assembly_reference": REFERENCE_SCHEMA,
        "component_reference": REFERENCE_SCHEMA,
        "assembly_side": text(enum=SIDES),
        "component_side": text(enum=SIDES),
        "offset": {"type": "number", "minimum": -1e6, "maximum": 1e6},
    },
    (
        "type",
        "assembly_reference",
        "component_reference",
        "assembly_side",
        "component_side",
        "offset",
    ),
)
REQUEST_SCHEMA = strict(
    {
        "selection": strict(
            {
                "instance_id": text(maximum=128),
                "owner": text(maximum=40),
                "occurrence_id": text(pattern=r"^[0-9]+$", maximum=12),
                "state_revision": text(pattern=r"^[a-f0-9]{64}$", maximum=64),
            },
            ("instance_id", "owner", "occurrence_id", "state_revision"),
        ),
        "units": text(enum=("mm",)),
        "constraints": {"type": "array", "items": CONSTRAINT_SCHEMA, "minItems": 3, "maxItems": 6},
        "affected_occurrences": {
            "type": "array",
            "items": text(pattern=r"^[0-9]+$", maximum=12),
            "minItems": 1,
            "maxItems": 32,
            "uniqueItems": True,
        },
    },
    ("selection", "units", "constraints", "affected_occurrences"),
)
REQUEST_EXAMPLE = {
    "selection": {
        "instance_id": "replace_from_live_editable_query",
        "owner": "gearbox.asm",
        "occurrence_id": "41",
        "state_revision": "0" * 64,
    },
    "units": "mm",
    "affected_occurrences": ["41"],
    "constraints": [
        {
            "type": "align",
            "assembly_reference": {
                "model": "gearbox.asm",
                "item_id": item,
                "item_type": "ITEM_SURFACE",
                "component_path": [],
            },
            "component_reference": {
                "model": "pin.prt",
                "item_id": item,
                "item_type": "ITEM_SURFACE",
                "component_path": [],
            },
            "assembly_side": "DATUM_SIDE_YELLOW",
            "component_side": "DATUM_SIDE_YELLOW",
            "offset": 5 if item == 2 else 0,
        }
        for item in (2, 4, 6)
    ],
}


def validate_request(q):
    validate(q, REQUEST_SCHEMA)
    engine.model_name(q["selection"]["owner"], ("asm",), "selection.owner")
    if len(q["affected_occurrences"]) != len(set(q["affected_occurrences"])):
        raise Error("E_VALIDATION", "affected occurrence IDs must be unique")
    if any(c["component_reference"]["component_path"] != [] for c in q["constraints"]):
        raise Error("E_VALIDATION", "component reference uses the local empty path")
    if any(not math.isfinite(c["offset"]) for c in q["constraints"]):
        raise Error("E_VALIDATION", "constraint offsets must be finite")
    return deepcopy(q)


def _incomplete(message, **details):
    raise Error("E_VERIFY_INCOMPLETE", message, details)


def _vector(v):
    return (
        isinstance(v, list)
        and len(v) == 3
        and all(type(x) in (float, int) and math.isfinite(x) for x in v)
    )


def _dot(a, b):
    return sum(x * y for x, y in zip(a, b, strict=True))


def _sub(a, b):
    return [x - y for x, y in zip(a, b, strict=True)]


def _close(a, b):
    return type(a) in (float, int) and type(b) in (float, int) and abs(a - b) <= TOL


def _transform(t):
    if not isinstance(t, dict) or not all(
        _vector(t.get(k)) for k in ("origin", "x_axis", "y_axis", "z_axis")
    ):
        _incomplete("complete actual component-path transform is required")
    axes = [t[k] for k in ("x_axis", "y_axis", "z_axis")]
    if any(
        not _close(_dot(a, b), float(i == j))
        for i, a in enumerate(axes)
        for j, b in enumerate(axes)
    ):
        _incomplete("component transform is not rigid orthonormal")
    cross = [
        axes[0][1] * axes[1][2] - axes[0][2] * axes[1][1],
        axes[0][2] * axes[1][0] - axes[0][0] * axes[1][2],
        axes[0][0] * axes[1][1] - axes[0][1] * axes[1][0],
    ]
    if not _close(_dot(cross, axes[2]), 1):
        _incomplete("mirrored component transform is outside the rigid-placement scope")


def _rows(state):
    return {str(r["id"]): r for r in state["components"]}


def reference_identity(ref):
    if not isinstance(ref, dict) or any(
        k not in ref for k in ("model", "item_id", "item_type", "component_path")
    ):
        _incomplete("constraint reference identity is incomplete")
    return {k: deepcopy(ref[k]) for k in ("model", "item_id", "item_type", "component_path")}


def _plane(ref):
    p = ref.get("plane") if isinstance(ref, dict) else None
    if not isinstance(p, dict) or not _vector(p.get("origin")) or not _vector(p.get("normal")):
        _incomplete("required reference plane equation is unreadable", reference=ref)
    if not _close(_dot(p["normal"], p["normal"]), 1):
        _incomplete("reference plane normal is not a unit vector")
    return p


def _effective_side(c, key):
    """Keep raw getters; datum-side is formally inapplicable to a physical plane."""
    if key not in c or c[key] not in (None, *SIDES):
        _incomplete("datum-side getter is missing, failed or unrecognized")
    ref = c["assembly_reference" if key == "assembly_side" else "component_reference"]
    kind = _plane(ref).get("kind")
    if kind == "physical_plane":
        return "DATUM_SIDE_NONE"
    if kind != "datum_plane" or c[key] not in SIDES[:2]:
        _incomplete("datum direction is not independently known")
    return c[key]


def _offset(c):
    base = str(c.get("type", "")).removesuffix("_off")
    if (
        base not in ("mate", "align")
        or c.get("native_type")
        not in ("ASM_CONSTRAINT_" + base.upper(), "ASM_CONSTRAINT_" + base.upper() + "_OFF")
        or "offset" not in c
    ):
        _incomplete("native offset type or getter is missing or contradictory")
    value = c["offset"]
    if value is None:
        return 0  # ComponentConstraint.GetOffset explicitly defines returned null as zero.
    if type(value) not in (int, float) or not math.isfinite(value):
        _incomplete("native offset getter did not return a finite value")
    return value


def _reference_path_binding(
    state, row, ref, component_side, *, owner_source="ComponentFeat.WFeature.GetSolid"
):
    """Actual selection roots are not the catalog's constructed expected identities."""
    if (
        ref.get("reference_owner_model") != state["model"]
        or ref.get("reference_owner_source") != owner_source
        or type(ref.get("path_present")) is not bool
    ):
        _incomplete("reference lacks its independently read constraint owner/root applicability")
    present, ids = ref["path_present"], ref["component_path"]
    root, leaf = ref.get("path_root_model"), ref.get("path_leaf_model")
    if not present:
        if (
            not component_side
            or ids != []
            or root is not None
            or leaf is not None
            or ref.get("model") != row["model"]
            or ref.get("path_root_source") != "Selection.GetPath.returned_null"
            or ref.get("path_leaf_source") != "Selection.GetPath.returned_null"
        ):
            _incomplete("only a proven model-local component reference may lack a path")
        return
    if ref.get("path_root_source") != "ComponentPath.GetRoot":
        _incomplete("selection root was not independently obtained")
    if not ids:
        if leaf is not None or ref.get("path_leaf_source") != "not_read_for_empty_path":
            _incomplete("empty reference path has contradictory leaf evidence")
        expected = row["model"] if component_side else state["model"]
        if (
            root != expected
            or ref.get("model") != expected
            or component_side
            and row["model_type"] != "assembly"
        ):
            _incomplete("empty selection path belongs to a different model/root")
        return
    if (
        len(ids) != 1
        or root != state["model"]
        or leaf != ref.get("model")
        or ref.get("path_leaf_source") != "ComponentPath.GetLeaf"
    ):
        _incomplete("reference is foreign, nested or lacks its actual leaf")
    if component_side:
        if ids != [int(row["id"])] or leaf != row["model"]:
            _incomplete("component selection belongs to another occurrence")
    else:
        sibling = _rows(state).get(str(ids[0]))
        if not sibling or sibling["model"] != leaf or str(ids[0]) == str(row["id"]):
            _incomplete("assembly reference does not identify another actual direct member")


def validate_state(state):
    if (
        not isinstance(state, dict)
        or state.get("profile") != PROFILE
        or state.get("complete") is not True
    ):
        _incomplete("complete source-identified constraint state is required")
    building.check_units(state, "mm")
    if (
        not isinstance(state.get("service_instance_id"), str)
        or not state["service_instance_id"].strip()
    ):
        _incomplete("authenticated native state lacks its actual service generation")
    if not isinstance(state.get("working_directory"), str) or not state["working_directory"]:
        _incomplete("actual engineering working directory is unavailable")
    origins, provenance = state.get("model_origins"), state.get("model_origin_readback")
    if not isinstance(origins, dict) or not isinstance(provenance, dict):
        _incomplete("native engineering-origin bindings are unavailable")
    context = state.get("context") or {}
    if (
        context.get("current_model") != state.get("model")
        or context.get("window_model") != state.get("model")
        or context.get("is_exploded") is not False
        or context.get("dynamic_positioning") is not False
    ):
        raise Error(
            "E_UNSUPPORTED",
            "constraint edits require the normal owner assembly/window context",
            {"context": context},
        )
    rows = state.get("components")
    if (
        not isinstance(rows, list)
        or not 1 <= len(rows) <= 32
        or any(not isinstance(r, dict) for r in rows)
        or len({str(r.get("id")) for r in rows}) != len(rows)
    ):
        _incomplete("complete unique inventory of 1..32 direct occurrences is required")
    if state.get("failed_features") != []:
        _incomplete("assembly regeneration has failed or unreadable features")
    if any(not isinstance(r.get("model"), str) or not r["model"] for r in rows):
        _incomplete("complete typed component model identities are required")
    required_origins = {state["model"], *(r["model"] for r in rows)}
    for r in rows:
        if r.get("model_type") == "assembly":
            inner = r.get("rigid_children")
            if not isinstance(inner, list) or any(not isinstance(v, dict) for v in inner):
                _incomplete("rigid-child origin inventory is incomplete")
            required_origins.update(v.get("model") for v in inner)
    for model in required_origins:
        proof = provenance.get(model) or {}
        if (
            not isinstance(origins.get(model), str)
            or not origins[model]
            or proof.get("source") != "Model.GetOrigin"
            or proof.get("read_complete") is not True
            or proof.get("result_category") != "returned_string"
        ):
            _incomplete("supported edits require a readable declared native origin", model=model)
    for r in rows:
        ident = str(r.get("id"))
        if (
            not ident.isdigit()
            or r.get("owner") != state["model"]
            or r.get("component_path") != [int(ident)]
        ):
            _incomplete("occurrence owner or direct path is incomplete")
        if (
            r.get("status") != "FEAT_ACTIVE"
            or r.get("placed") is not True
            or r.get("packaged") is not False
            or r.get("underconstrained") is not False
        ):
            raise Error(
                "E_UNSUPPORTED",
                "only active fully constrained occurrences are admitted",
                {"occurrence": ident},
            )
        for flag in ("frozen", "bulkitem", "substitute", "flexible", "embedded", "unplaced"):
            if r.get(flag) is not False:
                raise Error(
                    "E_UNSUPPORTED",
                    "component mode is unsupported or unreadable",
                    {"occurrence": ident, "flag": flag, "value": r.get(flag)},
                )
        if r.get("model_type") not in ("part", "assembly"):
            raise Error(
                "E_UNSUPPORTED", "only ordinary parts and rigid subassemblies are supported"
            )
        if r["model_type"] == "assembly":
            inner = r.get("rigid_children")
            if (
                not isinstance(inner, list)
                or not 1 <= len(inner) <= 32
                or any(not isinstance(v, dict) for v in inner)
                or len({str(v.get("id")) for v in inner}) != len(inner)
            ):
                _incomplete("complete rigid-child occurrence inventory is required")
            for child in inner:
                if (
                    child.get("owner") != r["model"]
                    or not str(child.get("model", "")).endswith(".prt")
                    or child.get("status") != "FEAT_ACTIVE"
                    or child.get("placed") is not True
                    or any(
                        child.get(k) is not False
                        for k in (
                            "frozen",
                            "bulkitem",
                            "substitute",
                            "flexible",
                            "embedded",
                            "unplaced",
                            "packaged",
                            "underconstrained",
                        )
                    )
                    or not isinstance(child.get("placement_metadata"), dict)
                    or child["placement_metadata"].get("supported") is not True
                    or not isinstance(child.get("constraints"), list)
                    or not child["constraints"]
                ):
                    raise Error("E_UNSUPPORTED", "rigid child contains an unsupported occurrence")
                _transform(child.get("transform"))
                for c in child["constraints"]:
                    if (
                        not isinstance(c, dict)
                        or c.get("attributes")
                        not in (
                            {"raw_null_default": True, "force": None, "ignore": None},
                            {"raw_null_default": False, "force": False, "ignore": False},
                        )
                        or "user_data" not in c
                    ):
                        _incomplete("rigid-child constraint attributes are unreadable")
        _transform(r.get("component_path_transform"))
        if (
            not isinstance(r.get("placement_metadata"), dict)
            or r["placement_metadata"].get("supported") is not True
        ):
            raise Error("E_UNSUPPORTED", "complete supported placement metadata is required")
        if not isinstance(r.get("parents"), list) or not isinstance(r.get("children"), list):
            _incomplete("feature parent/child relationships are incomplete", occurrence=ident)
        constraints = r.get("constraints")
        if not isinstance(constraints, list) or not constraints or r.get("constraints_error"):
            _incomplete("constraint getter did not return a complete set", occurrence=ident)
        for c in constraints:
            if not isinstance(c, dict):
                _incomplete("constraint row is malformed")
            attrs = c.get("attributes")
            if not isinstance(attrs, dict) or not (
                attrs == {"raw_null_default": True, "force": None, "ignore": None}
                or attrs == {"raw_null_default": False, "force": False, "ignore": False}
            ):
                raise Error("E_UNSUPPORTED", "forced, ignored or unreadable constraint attributes")
            if "user_data" not in c:
                _incomplete("constraint custom-data getter was not read")
            if c.get("type") in ("mate", "align", "mate_off", "align_off"):
                _offset(c)
                for key in ("assembly_reference", "component_reference"):
                    reference_identity(c.get(key))
                    _plane(c[key])
                _effective_side(c, "assembly_side")
                _effective_side(c, "component_side")
            elif c.get("type") not in ("def_placement", "fix", "csys"):
                raise Error(
                    "E_UNSUPPORTED",
                    "existing constraint type is outside the bounded proof",
                    {"type": c.get("type"), "occurrence": ident},
                )
    catalog = state.get("reference_catalog")
    if not isinstance(catalog, list):
        _incomplete("public planar reference catalog is unavailable")
    keys = [digest(reference_identity(r)) for r in catalog]
    if len(keys) != len(set(keys)):
        _incomplete("planar reference identities are ambiguous")
    for ref in catalog:
        if _plane(ref).get("kind") not in ("datum_plane", "physical_plane"):
            _incomplete("reference plane kind is unavailable")
        classification = ref.get("classification")
        if (
            not isinstance(classification, dict)
            or type(classification.get("public_feature")) is not bool
            or classification.get("source") != "Feature.GetIsVisible"
            or ref.get("reference_usage")
            != ("editable" if classification["public_feature"] else "protection_only")
        ):
            _incomplete("reference public/internal classification was not independently read")
        if (
            ref.get("path_root_model") != state["model"]
            or ref.get("path_root_source") != "constructed_catalog_owner"
            or ref.get("path_leaf_model") != ref.get("model")
            or ref.get("path_leaf_source") != "constructed_catalog_model"
        ):
            _incomplete("catalog model/root construction provenance is incomplete")
    for row in rows:
        for c in row["constraints"]:
            if c["type"] not in ("mate", "align", "mate_off", "align_off"):
                continue
            for side, local in (("assembly_reference", False), ("component_reference", True)):
                observed = c[side]
                _reference_path_binding(state, row, observed, local)
                bound = _lookup(state, observed, row, local)
                if observed["plane"] != bound["plane"]:
                    _incomplete("constraint plane disagrees with its independent catalog binding")
    _construction_bindings(state)


def influence(state, target_id, *, planned=False):
    """Constraint paths plus actual feature dependency graph, never all-pose exemption."""
    if not planned:
        validate_state(state)
    rows = _rows(state)
    target = str(target_id)
    if target not in rows:
        raise Error("E_NOT_FOUND", "selected occurrence is absent")
    graph = {i: set() for i in rows}
    for ident, row in rows.items():
        for c in row["constraints"]:
            a, own = c.get("assembly_reference"), c.get("component_reference")
            if c["type"] in ("def_placement", "fix"):
                continue
            if not isinstance(a, dict) or not isinstance(own, dict):
                _incomplete("constraint references are incomplete", occurrence=ident)
            if (
                own.get("component_path") not in ([], [int(ident)])
                or own.get("model") != row["model"]
            ):
                raise Error(
                    "E_UNSUPPORTED", "component reference is not local to the selected definition"
                )
            path = a.get("component_path")
            if path == [] and a.get("model") == state["model"]:
                continue
            if (
                not isinstance(path, list)
                or len(path) != 1
                or str(path[0]) not in rows
                or a.get("model") != rows[str(path[0])]["model"]
                or str(path[0]) == ident
            ):
                raise Error(
                    "E_UNSUPPORTED", "assembly reference is foreign, nested or self-referential"
                )
            graph[str(path[0])].add(ident)
    # Feature edges can reveal more dependencies than constraint selections.
    for ident, row in rows.items():
        graph[ident].update(str(c) for c in row["children"] if str(c) in rows)
    visiting, visited = set(), set()

    def walk(ident):
        if ident in visiting:
            raise Error("E_UNSUPPORTED", "cyclic placement dependencies are unsupported")
        if ident in visited:
            return
        visiting.add(ident)
        for child in graph[ident]:
            walk(child)
        visiting.remove(ident)
        visited.add(ident)

    for ident in rows:
        walk(ident)
    affected, todo = set(), [target]
    while todo:
        ident = todo.pop()
        if ident not in affected:
            affected.add(ident)
            todo.extend(graph[ident])
    for ident in affected:
        extra = [str(c) for c in rows[ident]["children"] if str(c) not in rows]
        if extra:
            raise Error(
                "E_UNSUPPORTED",
                "target has non-component downstream features",
                {"occurrence": ident, "children": extra},
            )
    return sorted(affected)


def _choose(state, selector):
    hits = [
        r
        for r in state["components"]
        if str(r["id"]) == str(selector)
        or r["model"].casefold().removesuffix(".prt").removesuffix(".asm")
        == str(selector).casefold().removesuffix(".prt").removesuffix(".asm")
    ]
    if len(hits) != 1:
        raise Error(
            "E_NOT_FOUND" if not hits else "E_CONFLICT",
            "selector must identify one direct occurrence; "
            "repeated model names require its returned ID",
            {"matched_ids": [str(r["id"]) for r in hits]},
        )
    return hits[0]


def native_state(client, name):
    admission = client.require_capability(CAPABILITY, CAPABILITY_VERSION) or client.health()
    state = client.op("assembly.constraint-state", {"model": name})
    if state.get("model") != name:
        _incomplete("native constraint state belongs to another owner")
    validate_state(state)
    if state["service_instance_id"] != admission.get("service_instance_id"):
        raise Error(
            "E_CONFLICT",
            "service generation changed during the constraint observation",
            {"dispatch_state": "not_started", "automatic_retry": False},
        )
    return state


def _selection(client, state, row):
    return {
        "instance_id": state["service_instance_id"],
        "owner": state["model"],
        "occurrence_id": str(row["id"]),
        "state_revision": digest(state),
    }


def _copy_constraint(c):
    out = {
        "type": c["type"].removesuffix("_off"),
        "assembly_reference": reference_identity(c["assembly_reference"]),
        "component_reference": reference_identity(c["component_reference"]),
        "assembly_side": _effective_side(c, "assembly_side"),
        "component_side": _effective_side(c, "component_side"),
        "offset": _offset(c),
    }
    # Native selections may retain their exact one-level owner occurrence path.
    # Input selections are local to the selected definition, whose identity was checked.
    out["component_reference"]["component_path"] = []
    return out


def _query_row(client, state, row):
    out = deepcopy(row)
    out["id"] = str(row["id"])
    out["selection"] = _selection(client, state, row)
    out["possible_moving_occurrences"] = influence(state, row["id"])
    if all(c["type"] in ("mate", "align", "mate_off", "align_off") for c in row["constraints"]):
        out["edit_request"] = {
            "selection": out["selection"],
            "units": "mm",
            "constraints": [_copy_constraint(c) for c in row["constraints"]],
            "affected_occurrences": out["possible_moving_occurrences"],
        }
    else:
        out["edit_request"] = None
    return out


def _query(opts, one):
    name = engine.model_name(opts["model"], ("asm",))

    def fetch(client):
        state = native_state(client, name)
        common = {
            "model": name,
            "source": "independent native constraint/reference/actual-pose getters",
            "scope": "direct_occurrences_normal_owner_context",
            "reference_catalog": state["reference_catalog"],
            "not_checked": [
                "global_interference",
                "external_unloaded_reuse",
                "manufacturing_intent",
                "construction_datum_dimension_id_crosscheck",
            ],
        }
        if one:
            return common | {"item": _query_row(client, state, _choose(state, opts["item"]))}
        items = [_query_row(client, state, r) for r in state["components"]]
        return common | page(items, opts.get("limit", 100), opts.get("offset", 0))

    return engine.read(opts, fetch)


def component_list(opts):
    return _query(opts, False)


def component_show(opts):
    return _query(opts, True)


def _lookup(state, ref, target, local=False):
    identity = reference_identity(ref)
    if local:
        if identity["model"] != target["model"] or identity["component_path"] not in (
            [],
            [int(target["id"])],
        ):
            raise Error(
                "E_VALIDATION", "component reference must be local to the selected occurrence model"
            )
        identity["component_path"] = [int(target["id"])]
    matches = [r for r in state["reference_catalog"] if reference_identity(r) == identity]
    if len(matches) != 1:
        raise Error(
            "E_CONFLICT",
            "reference is absent, ambiguous or stale; query the actual planar catalog",
            {"reference": ref},
        )
    if matches[0].get("reference_usage") != "editable":
        raise Error(
            "E_UNSUPPORTED",
            "internal construction references are protection-only; use a public datum or face",
            {"reference": ref},
        )
    return matches[0]


def _default_fit(fit):
    required = {
        "type_raw": -1,
        "mode": "default",
        "reference_applicability": "not_applicable",
        "radius_applicability": "not_applicable",
        "outline_applicability": "not_applicable",
        "outline_value_read": False,
    }
    if not isinstance(fit, dict) or any(fit.get(k) != v for k, v in required.items()):
        return False
    if set(fit) - set(required) - {"element_presence", "source", "not_checked"}:
        return False
    if "element_presence" in fit and (
        not isinstance(fit["element_presence"], dict)
        or set(fit["element_presence"]) != {"reference", "radius", "outline"}
        or any(type(v) is not bool for v in fit["element_presence"].values())
    ):
        return False
    return ("not_checked" not in fit or fit["not_checked"] == ["datum_display_outline"]) and (
        "source" not in fit
        or fit["source"]
        == (
            "actual PRO_E_DTMPLN_FIT_TYPE; ProDtmPln.h conditional applicability; "
            "outline pointer not read"
        )
    )


def _construction_bindings(state):
    """Derive internal support roles from actual consumers and complete definitions."""
    rows, result = _rows(state), {}
    for ref in state["reference_catalog"]:
        internal = ref["classification"]["public_feature"] is False
        root_internal = (
            internal
            and ref["model"] == state["model"]
            and ref["component_path"] == []
            and _plane(ref)["kind"] == "datum_plane"
        )
        aux = ref.get("auxiliary")
        if not root_internal:
            if aux is not None:
                _incomplete("construction linkage belongs to a different reference scope")
            continue
        if not isinstance(aux, dict):
            _incomplete("root internal datum lacks its independently read construction definition")
        plane = _plane(ref)
        consumer = str(aux.get("consumer_occurrence_id"))
        children, parents = aux.get("children"), aux.get("parents")
        if (
            aux.get("owner_model") != state["model"]
            or aux.get("feature_id") != plane.get("feature_id")
            or aux.get("surface_id") != ref["item_id"]
            or aux.get("status") != "FEAT_ACTIVE"
            or consumer not in rows
            or children != [int(consumer)]
            or not isinstance(parents, list)
            or len(parents) != 1
            or type(parents[0]) is not int
            or aux.get("link_basis")
            != "internal_visibility_single_consumer_unique_offset_definition"
            or aux.get("driver_crosscheck") != {"status": "not_checked"}
        ):
            _incomplete(
                "internal datum owner, actual sole consumer or linkage source is incomplete"
            )
        definition = aux.get("definition")
        entries = definition.get("constraints") if isinstance(definition, dict) else None
        if (
            not isinstance(definition, dict)
            or type(definition.get("constraint_count")) is not int
            or definition["constraint_count"] != 1
            or definition.get("array_read_complete") is not True
            or definition.get("source")
            != "WFeature.GetElementTree; complete indexed PRO_E_DTMPLN_CONSTRAINTS.GetChildren"
            or not isinstance(entries, list)
            or len(entries) != 1
            or not isinstance(entries[0], dict)
            or type(definition.get("flip_raw")) is not int
            or definition["flip_raw"] not in (0, 1)
            or not _default_fit(definition.get("fit"))
        ):
            _incomplete(
                "only a completely read single-offset internal datum/default fit is supported"
            )
        item = entries[0]
        indexed = item.get("indexed_path")
        paths = item.get("element_paths")
        if (
            type(item.get("index")) is not int
            or item["index"] != 0
            or type(item.get("type_raw")) is not int
            or item["type_raw"] != 3  # ProDtmPln.h PRO_DTMPLN_OFFS, also SDK checked.
            or item.get("units") != "mm"
            or type(item.get("offset_raw")) not in (int, float)
            or not math.isfinite(item["offset_raw"])
            or not isinstance(indexed, list)
            or len(indexed) != 2
            or not isinstance(indexed[0], dict)
            or indexed[0] != {"element_id": DATUM_CONSTRAINT_ARRAY}
            or indexed[1] != {"array_index": 0}
            or not isinstance(paths, dict)
            or set(paths) != set(DATUM_ELEMENTS)
            or any(
                not isinstance(path, list)
                or path[:-1] != indexed
                or not path
                or not isinstance(path[-1], dict)
                or set(path[-1]) != {"element_id"}
                or type(path[-1]["element_id"]) is not int
                or path[-1]["element_id"] != DATUM_ELEMENTS[key]
                for key, path in paths.items()
            )
        ):
            _incomplete(
                "internal datum constraint array/element paths or raw offset are incomplete"
            )
        source = item.get("reference")
        reference_identity(source)
        _reference_path_binding(
            state, rows[consumer], source, False, owner_source="DatumFeature.WFeature.GetSolid"
        )
        bound = _lookup(state, source, rows[consumer])
        if source.get("plane") != bound["plane"]:
            _incomplete("internal datum reference does not match its independent public catalog")
        expected_parent = (
            source["component_path"][0]
            if source["component_path"]
            else _plane(source)["feature_id"]
        )
        if parents != [expected_parent]:
            _incomplete("internal datum actual parent does not identify its definition reference")
        candidates = [
            i
            for i, c in enumerate(rows[consumer]["constraints"])
            if c["type"] in ("mate", "align", "mate_off", "align_off")
            and reference_identity(c["assembly_reference"]) == reference_identity(source)
            and _offset(c) == item["offset_raw"]
        ]
        if (
            len(candidates) != 1
            or type(aux.get("matched_constraint_index")) is not int
            or aux["matched_constraint_index"] != candidates[0]
        ):
            _incomplete("internal datum cannot be uniquely bound to an actual constraint slot")
        _transform(plane.get("frame"))
        if plane["frame"]["origin"] != plane["origin"] or not _close(
            _dot(plane["frame"]["z_axis"], plane["normal"]), 1
        ):
            _incomplete("internal datum plane and raw coordinate framework disagree")
        result[digest(reference_identity(ref))] = (ref, aux, consumer, candidates[0])
    return result


def _reference_world_frame(state, ref):
    p = _plane(ref)
    raw = p.get("frame")
    _transform(raw)
    if raw["origin"] != p["origin"] or not _close(abs(_dot(raw["z_axis"], p["normal"])), 1):
        _incomplete("reference normal and actual native coordinate framework disagree")
    t = (
        _rows(state)[str(ref["component_path"][0])]["component_path_transform"]
        if ref["component_path"]
        else None
    )
    origin, normal = _world(p, t)
    x = (
        [
            sum(t[k][j] * raw["x_axis"][i] for i, k in enumerate(("x_axis", "y_axis", "z_axis")))
            for j in range(3)
        ]
        if t
        else raw["x_axis"]
    )
    return {"origin": origin, "x_axis": x, "y_axis": _cross(normal, x), "z_axis": normal}


def _construction_checks(state):
    checks, rows = [], _rows(state)
    for ref, aux, consumer, index in _construction_bindings(state).values():
        item = aux["definition"]["constraints"][0]
        anchor = _reference_world_frame(state, item["reference"])
        plane = _plane(ref)
        c = rows[consumer]["constraints"][index]
        point, normal = _world(
            _plane(c["component_reference"]), rows[consumer]["component_path_transform"]
        )
        ident = f"{aux['owner_model']}:{aux['feature_id']}"
        checks += [
            engine.check(
                "construction_definition_plane:" + ident,
                _close(abs(_dot(plane["normal"], anchor["z_axis"])), 1)
                and _close(
                    _dot(_sub(plane["origin"], anchor["origin"]), anchor["z_axis"]),
                    item["offset_raw"],
                ),
            ),
            engine.check(
                "construction_consumer_plane:" + ident,
                _close(abs(_dot(plane["normal"], normal)), 1)
                and _close(_dot(_sub(point, plane["origin"]), plane["normal"]), 0),
            ),
        ]
    return checks


def _construction_frame_kept(before, after, old, new):
    """Keep the measured frame relation; only the explicitly bound offset may change."""
    a, b = old[1]["definition"]["constraints"][0], new[1]["definition"]["constraints"][0]
    first, last = (
        _reference_world_frame(before, a["reference"]),
        _reference_world_frame(after, b["reference"]),
    )
    first_axes, last_axes = (
        [first[k] for k in ("x_axis", "y_axis", "z_axis")],
        [last[k] for k in ("x_axis", "y_axis", "z_axis")],
    )
    old_frame, new_frame = _plane(old[0])["frame"], _plane(new[0])["frame"]
    local = [_dot(_sub(old_frame["origin"], first["origin"]), axis) for axis in first_axes]
    local[2] += b["offset_raw"] - a["offset_raw"]
    expected = [
        last["origin"][j] + sum(local[i] * last_axes[i][j] for i in range(3)) for j in range(3)
    ]
    if not all(_close(x, y) for x, y in zip(expected, new_frame["origin"], strict=True)):
        return False
    for key in ("x_axis", "y_axis", "z_axis"):
        coefficients = [_dot(old_frame[key], axis) for axis in first_axes]
        expected = [sum(coefficients[i] * last_axes[i][j] for i in range(3)) for j in range(3)]
        if not all(_close(x, y) for x, y in zip(expected, new_frame[key], strict=True)):
            return False
    return True


def _reference_geometry_checks(before, after, intent):
    first = {digest(reference_identity(r)): r for r in before["reference_catalog"]}
    last = {digest(reference_identity(r)): r for r in after["reference_catalog"]}
    old_aux, new_aux = _construction_bindings(before), _construction_bindings(after)
    moving = set(intent["affected_occurrences"])
    checks = [engine.check("reference_inventory_kept", set(first) == set(last))]
    for key, old in first.items():
        new = last.get(key)
        if new is None:
            continue
        linked = key in old_aux and key in new_aux and old_aux[key][2] in moving
        if not linked:
            checks.append(engine.check("reference_unchanged:" + key, old == new))
            continue
        a, b = deepcopy(old), deepcopy(new)
        for r in (a, b):
            for field in ("origin", "normal", "frame"):
                r["plane"].pop(field)
            # A derived per-reading diagnostic is not a definition or driver identity.
            # Its raw report remains in both frozen observations; Python checks the plane.
            r["auxiliary"].pop("native_plane_equation_check", None)
            r["auxiliary"].pop("parents")
            record = r["auxiliary"]["definition"]["constraints"][0]
            record.pop("reference")
            record.pop("offset_raw")
        checks += [
            engine.check("construction_fixed_state:" + key, a == b),
            engine.check(
                "construction_frame_relation:" + key,
                _construction_frame_kept(before, after, old_aux[key], new_aux[key]),
            ),
        ]
    checks += _construction_checks(before) + _construction_checks(after)
    return [engine.check("reference_geometry_kept", all(c["passed"] for c in checks)), *checks]


def make_intent(state, q):
    target = _rows(state).get(q["selection"]["occurrence_id"])
    if target is None:
        raise Error("E_CONFLICT", "frozen occurrence no longer exists")
    if len(q["constraints"]) != len(target["constraints"]):
        raise Error("E_UNSUPPORTED", "this bounded edit preserves the existing constraint count")
    if any("user_data" not in c for c in target["constraints"]):
        _incomplete("target constraint user-data getter was not read")
    if any(c["user_data"] not in (None, "") for c in target["constraints"]):
        raise Error("E_UNSUPPORTED", "target constraints carry custom data that cannot be replaced")
    moving = influence(state, target["id"])
    proposed = deepcopy(state)
    new = []
    for index, c in enumerate(q["constraints"]):
        a, b = (
            _lookup(state, c["assembly_reference"], target),
            _lookup(state, c["component_reference"], target, True),
        )
        for ref, side_key in ((a, "assembly_side"), (b, "component_side")):
            kind = _plane(ref).get("kind")
            side = c[side_key]
            if kind == "datum_plane" and side not in SIDES[:2]:
                raise Error(
                    "E_VALIDATION", "a datum reference requires an explicit yellow or red side"
                )
            if kind == "physical_plane" and side != "DATUM_SIDE_NONE":
                raise Error("E_VALIDATION", "datum-side flags do not apply to a physical plane")
            if kind not in ("datum_plane", "physical_plane"):
                _incomplete("reference plane kind has not been independently established")
        if a["component_path"] == [int(target["id"])]:
            raise Error("E_VALIDATION", "a component cannot constrain itself")
        new.append(
            deepcopy(c)
            | {
                "assembly_reference": a,
                "component_reference": b,
                "units": "mm",
                "native_type": "ASM_CONSTRAINT_" + c["type"].upper() + "_OFF",
                "attributes": {"raw_null_default": True, "force": None, "ignore": None},
                "user_data": target["constraints"][index]["user_data"],
            }
        )
        new[-1]["component_reference"] = deepcopy(b) | {"component_path": []}
    _rows(proposed)[str(target["id"])]["constraints"] = new
    # A replacement reference may introduce a new dependency or cycle.
    moving = sorted(set(moving) | set(influence(proposed, target["id"], planned=True)))
    if sorted(q["affected_occurrences"]) != moving:
        raise Error(
            "E_CONFLICT",
            "declare the exact possible-moving occurrence set",
            {"expected_affected_occurrences": moving},
        )
    normals = [_plane(c["component_reference"])["normal"] for c in new]
    if not any(
        abs(
            _dot(
                a, [b[1] * c[2] - b[2] * c[1], b[2] * c[0] - b[0] * c[2], b[0] * c[1] - b[1] * c[0]]
            )
        )
        > 1e-6
        for a in normals
        for b in normals
        for c in normals
    ):
        raise Error("E_UNSUPPORTED", "three independent component plane normals are required")
    _precheck_rigid_planes(state, new)
    return {
        "profile": PROFILE,
        "target": str(target["id"]),
        "model": state["model"],
        "constraints": new,
        "affected_occurrences": moving,
        "request": deepcopy(q),
        "pose_prediction": "not_solved; final pose requires independent native getters",
    }


def _world(plane, t):
    if t is None:
        return plane["origin"], plane["normal"]
    axes = [t[k] for k in ("x_axis", "y_axis", "z_axis")]

    def direction(v):
        return [sum(axes[i][j] * v[i] for i in range(3)) for j in range(3)]

    return [a + b for a, b in zip(t["origin"], direction(plane["origin"]), strict=True)], direction(
        plane["normal"]
    )


def _cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _precheck_rigid_planes(state, constraints):
    """Reject algebraic contradictions; this is not a native solve or a result pose."""
    rows = _rows(state)
    equations = []
    for c in constraints:
        a, b = c["assembly_reference"], c["component_reference"]
        at = (
            rows[str(a["component_path"][0])]["component_path_transform"]
            if a["component_path"]
            else None
        )
        ao, an = _world(_plane(a), at)
        bo, bn = _plane(b)["origin"], _plane(b)["normal"]
        if _effective_side(c, "assembly_side") == "DATUM_SIDE_RED":
            an = [-v for v in an]
        if _effective_side(c, "component_side") == "DATUM_SIDE_RED":
            bn = [-v for v in bn]
        wanted = [-v for v in an] if c["type"].startswith("mate") else an
        equations.append((ao, an, bo, bn, wanted, c["offset"]))
    for a in equations:
        for b in equations:
            if not _close(_dot(a[3], b[3]), _dot(a[4], b[4])):
                raise Error(
                    "E_VALIDATION", "requested plane directions cannot share a rigid rotation"
                )
    chosen = next(
        (
            (a, b, c)
            for a in equations
            for b in equations
            for c in equations
            if abs(_dot(a[3], _cross(b[3], c[3]))) > 1e-6
        ),
        None,
    )
    if chosen is None:
        raise Error("E_UNSUPPORTED", "constraint planes do not locate a rigid occurrence")
    local = [e[3] for e in chosen]
    world = [e[4] for e in chosen]
    determinant = _dot(local[0], _cross(local[1], local[2]))
    if not _close(_dot(world[0], _cross(world[1], world[2])), determinant):
        raise Error("E_VALIDATION", "plane directions require a reflected occurrence")
    dual = [_cross(local[1], local[2]), _cross(local[2], local[0]), _cross(local[0], local[1])]

    def rotate(v):
        return [
            sum(world[i][j] * _dot(dual[i], v) / determinant for i in range(3)) for j in range(3)
        ]

    normals = [e[1] for e in chosen]
    rhs = [_dot(e[1], e[0]) + e[5] - _dot(e[1], rotate(e[2])) for e in chosen]
    det = _dot(normals[0], _cross(normals[1], normals[2]))
    vectors = [
        _cross(normals[1], normals[2]),
        _cross(normals[2], normals[0]),
        _cross(normals[0], normals[1]),
    ]
    translation = [sum(rhs[i] * vectors[i][j] / det for i in range(3)) for j in range(3)]
    if any(
        not _close(_dot(e[1], translation), _dot(e[1], e[0]) + e[5] - _dot(e[1], rotate(e[2])))
        for e in equations
    ):
        raise Error("E_VALIDATION", "requested plane offsets are mutually contradictory")


def pose_checks(state, occurrence):
    rows = _rows(state)
    row = rows[str(occurrence)]
    checks = []
    for i, c in enumerate(row["constraints"]):
        if c["type"] not in ("mate", "align", "mate_off", "align_off"):
            checks.append(engine.check(f"pose:{occurrence}:{i}:planar_supported", False))
            continue
        a, b = c["assembly_reference"], c["component_reference"]
        apath = a["component_path"]
        at = rows[str(apath[0])]["component_path_transform"] if apath else None
        ao, an = _world(_plane(a), at)
        bo, bn = _world(_plane(b), row["component_path_transform"])
        if _effective_side(c, "assembly_side") == "DATUM_SIDE_RED":
            an = [-v for v in an]
        if _effective_side(c, "component_side") == "DATUM_SIDE_RED":
            bn = [-v for v in bn]
        mate = c["type"].startswith("mate")
        separation = _dot(_sub(bo, ao), an)
        checks += [
            engine.check(f"pose:{occurrence}:{i}:normal", _close(_dot(an, bn), -1 if mate else 1)),
            engine.check(
                f"pose:{occurrence}:{i}:offset_mm",
                _close(separation, _offset(c)),
                actual_signed_mm=separation,
                expected_mm=_offset(c),
            ),
        ]
    return checks


def _constraint_signature(c):
    out = {
        "type": c["type"].removesuffix("_off"),
        "offset": _offset(c),
        "assembly_reference": reference_identity(c["assembly_reference"]),
        "component_reference": reference_identity(c["component_reference"]),
        "assembly_side": _effective_side(c, "assembly_side"),
        "component_side": _effective_side(c, "component_side"),
        "user_data": c.get("user_data"),
    }
    out["component_reference"]["component_path"] = []
    return out


def compare(before, after, intent):
    validate_state(before)
    validate_state(after)
    old, new = _rows(before), _rows(after)
    target, moving = intent["target"], set(intent["affected_occurrences"])
    checks = [
        engine.check("same_owner", before["model"] == after["model"]),
        engine.check(
            "same_service_generation", before["service_instance_id"] == after["service_instance_id"]
        ),
        engine.check(
            "same_engineering_origins",
            before["model_origins"] == after["model_origins"]
            and before["model_origin_readback"] == after["model_origin_readback"]
            and before["working_directory"] == after["working_directory"],
        ),
        engine.check("same_occurrence_inventory", set(old) == set(new)),
        engine.check(
            "target_constraints_read_back",
            target in new
            and [_constraint_signature(c) for c in new[target]["constraints"]]
            == [_constraint_signature(c) for c in intent["constraints"]],
        ),
    ]
    for ident in old:
        a, b = old[ident], new.get(ident, {})
        checks.append(
            engine.check(
                "occurrence_identity:" + ident,
                all(
                    a.get(k) == b.get(k)
                    for k in ("id", "owner", "component_path", "model", "model_type")
                ),
            )
        )
        if ident != target:
            checks.append(
                engine.check(
                    "non_target_constraints:" + ident, a["constraints"] == b.get("constraints")
                )
            )
        checks.append(
            engine.check(
                "placement_metadata:" + ident,
                a["placement_metadata"] == b.get("placement_metadata"),
            )
        )
        old_children = {str(v) for v in a["children"]}
        new_children = {str(v) for v in b.get("children", [])}
        old_parents = {str(v) for v in a["parents"]}
        new_parents = {str(v) for v in b.get("parents", [])}
        authorized_parent_ids = set()
        for c in [*old[target]["constraints"], *intent["constraints"]]:
            ref = c.get("assembly_reference")
            if isinstance(ref, dict):
                path = ref.get("component_path")
                if path:
                    authorized_parent_ids.add(str(path[0]))
                elif isinstance(ref.get("plane"), dict):
                    authorized_parent_ids.add(str(ref["plane"].get("feature_id")))
        checks.append(
            engine.check(
                "dependency_edges:" + ident,
                old_children ^ new_children
                <= ({target} if ident in authorized_parent_ids else set())
                and old_parents ^ new_parents
                <= (authorized_parent_ids if ident == target else set()),
            )
        )
        if ident not in moving:
            checks.append(
                engine.check(
                    "unaffected_pose:" + ident,
                    a["component_path_transform"] == b.get("component_path_transform"),
                )
            )
        elif ident in new:
            checks.extend(pose_checks(after, ident))
    checks.extend(_reference_geometry_checks(before, after, intent))
    checks.append(
        engine.check(
            "current_dependency_influence_within_authorization",
            set(influence(after, target)) <= moving,
        )
    )
    return {
        "level": "selected_postconditions_verified",
        "coverage": "independent constraint and actual component-path pose getters",
        "checks": checks,
        "not_checked": [
            "global_interference",
            "external_unloaded_reuse",
            "manufacturing_intent",
            "construction_datum_dimension_id_crosscheck",
        ],
    }


def _part_protection(client, name):
    from . import protected_readback

    state = machining.snapshot(client, name)
    state["protected_definitions"] = protected_readback.definitions(client, name, state["model"])
    state["physical_observation"] = protected_readback.physical(client, name, state["model"])
    state["physical_observation"].pop("modified", None)
    for op, key in (("parameter.list", "parameters"), ("relation.list", "relations")):
        data = client.op(op, {"model": name})
        if not isinstance(data.get(key), list) or data.get("reading_failures"):
            _incomplete(
                "constituent engineering attributes are unreadable", model=name, resource=key
            )
        state[key] = data[key]
    # Origin/modified are persistence observations, not model-space geometry.
    modified = state["model"].get("modified")
    state["model"] = {
        k: v
        for k, v in state["model"].items()
        if k not in ("origin", "origin_readback", "modified", "bbox", "mass_properties")
    }
    return state, modified


def snapshot(client, name):
    native = native_state(client, name)
    session = engine.session(client)
    parts, children, origins, modified = {}, {}, {}, {}
    present = set(session["models"])
    # Refuse changing a reused owner definition. Never silently claim one outer occurrence.
    reused = []
    for model in sorted(present):
        if model.endswith(".asm") and model != name:
            shown = engine.show(client, model)
            inventory = shown.get("components")
            if (
                shown.get("model") != model
                or not isinstance(inventory, list)
                or any(
                    not isinstance(c, dict)
                    or not str(c.get("id", "")).isdigit()
                    or not isinstance(c.get("model"), str)
                    or c.get("constraints_error")
                    or c.get("placement_error")
                    for c in inventory
                )
                or len({str(c["id"]) for c in inventory}) != len(inventory)
            ):
                _incomplete("reverse owner inventory is incomplete", model=model)
            reused += [
                {"owner": model, "occurrence": str(c["id"])}
                for c in shown["components"]
                if c.get("model") == name
            ]
    if reused:
        raise Error(
            "E_UNSUPPORTED",
            "editing a reused owner definition requires all ancestor occurrences; "
            "this first scope supports an unreferenced session owner only",
            {"affected_owner_occurrences": reused},
        )
    pending = [r["model"] for r in native["components"]]
    seen = set()
    while pending:
        model = pending.pop()
        if model in seen:
            continue
        if len(seen) >= 64 or model not in present:
            _incomplete("bounded constituent closure is unavailable", model=model)
        seen.add(model)
        shown = engine.show(client, model)
        origins[model] = shown.get("origin")
        modified[model] = shown.get("modified")
        engine.store_directory(shown, session)
        if model.endswith(".prt"):
            parts[model], modified[model] = _part_protection(client, model)
        elif model.endswith(".asm"):
            rows = shown.get("components")
            if not isinstance(rows, list):
                _incomplete("rigid child component inventory unavailable", model=model)
            from .commands.assembly import _replacement_state

            children[model] = _replacement_state(shown)["components"]
            pending.extend(c["model"] for c in rows)
        else:
            raise Error("E_UNSUPPORTED", "constituent is not a part or rigid assembly")
    owner = engine.show(client, name)
    from . import protected_readback

    owner_definitions = protected_readback.definitions(client, name, owner)
    modified[name] = owner.get("modified")
    engine.store_directory(owner, session)
    owner_features = building.features_of(client, name)
    if any(
        f.get("type") not in ("FEATTYPE_COMPONENT", "FEATTYPE_DATUM_PLANE", "FEATTYPE_COORD_SYS")
        or f.get("status") != "FEAT_ACTIVE"
        for f in owner_features
    ):
        raise Error(
            "E_UNSUPPORTED", "owner has engineering features outside the placement-only scope"
        )
    owner_parameters = client.op("parameter.list", {"model": name})
    owner_relations = client.op("relation.list", {"model": name})
    if (
        not isinstance(owner_parameters.get("parameters"), list)
        or owner_parameters.get("reading_failures")
        or owner_relations.get("relations") != []
        or owner_relations.get("reading_failures")
    ):
        raise Error("E_UNSUPPORTED", "owner requires complete parameters and no driving relations")
    return {
        "native": native,
        "parts": parts,
        "rigid_definitions": children,
        "origins": origins,
        "session_models": sorted(present),
        "persistence": {"modified": modified, "source": "Model.GetIsModified"},
        "owner_protection": {
            "protected_definitions": owner_definitions,
            "features": owner_features,
            "parameters": owner_parameters,
            "relations": owner_relations,
            "units": owner.get("units"),
            "material": owner.get("material"),
            "origin": owner.get("origin"),
        },
    }


def geometry_observation(observation):
    """Keep placement/engineering protection separate from model saved-state evidence."""
    return {k: v for k, v in observation.items() if k != "persistence"}


def persistence_state(observation):
    """Dirty models are unsaved; absent or non-boolean readback is explicitly unknown."""
    modified = (observation.get("persistence") or {}).get("modified")
    if not isinstance(modified, dict) or not modified:
        return "unknown"
    if any(value is True for value in modified.values()):
        return "unsaved"
    if any(type(value) is not bool for value in modified.values()):
        return "unknown"
    return "unchanged"


def failure_unchanged(before, after):
    if geometry_observation(before) != geometry_observation(after):
        return False
    if "unknown" in (persistence_state(before), persistence_state(after)):
        return None
    return before == after


def verify(before, after, intent):
    if any(
        not isinstance(v.get("owner_protection"), dict) or not v["owner_protection"]
        for v in (before, after)
    ):
        _incomplete("owner assembly protection is incomplete")
    result = compare(before["native"], after["native"], intent)
    result["checks"] += [
        engine.check(
            "constituent_geometry_dimensions_material_relations", before["parts"] == after["parts"]
        ),
        engine.check(
            "rigid_subassembly_internal_placement",
            before["rigid_definitions"] == after["rigid_definitions"],
        ),
        engine.check("constituent_origin_identity", before["origins"] == after["origins"]),
        engine.check(
            "session_model_inventory", before["session_models"] == after["session_models"]
        ),
        engine.check(
            "owner_definition_parameters_relations",
            before.get("owner_protection") == after.get("owner_protection"),
        ),
    ]
    return result


def _prepare(opts):
    return {
        "name": engine.model_name(opts["model"], ("asm",)),
        "request": validate_request(read_request(opts["request"])),
    }


def _plan(client, opts, pre):
    name, q = pre["name"], pre["request"]
    before = snapshot(client, name)
    state = before["native"]
    target = _choose(state, opts["component"])
    if q["selection"] != _selection(client, state, target):
        raise Error(
            "E_CONFLICT",
            "occurrence selection belongs to another generation or has changed; "
            "re-query before a new preview",
            {"dispatch_state": "not_started", "conflict": "stale_selection"},
        )
    intent = make_intent(state, q)
    baseline_checks = [
        check for ident in intent["affected_occurrences"] for check in pose_checks(state, ident)
    ] + _construction_checks(state)
    if not all(check["passed"] for check in baseline_checks):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "the bounded plane/side/offset convention does not explain the current native pose",
            {"dispatch_state": "not_started", "checks": baseline_checks},
        )
    if opts.get("confirm"):
        retained = operations.get(safety.token_operation(opts["confirm"]))["driver_plan"][
            "base_snapshot"
        ]["extensions"]["creo"]["observation"]
        if (
            retained.get("constraints_before") != before
            or retained.get("constraints_intent") != intent
        ):
            raise Error(
                "E_CONFLICT",
                "constraint or constituent baseline changed after preview",
                {"dispatch_state": "not_started"},
            )

    def check(c, data):
        p.verified_observation = None
        after = snapshot(c, name)
        verification = verify(before, after, intent)
        if same_plan(p, c):
            # Retain the complete observation, including protected constituents and
            # saved state. The driver must account from this exact checked reading.
            verified_after.clear()
            verified_after.update(deepcopy(after))
            p.verified_observation = deepcopy(after)
            verification["observation_sha256"] = digest(after)
        return {
            "model": name,
            "occurrence": str(target["id"]),
            "setter_report": data,
            "independent_state": after["native"],
            "independent_observation": after,
        }, verification

    p = engine.Plan(
        op="assembly.redefine-constraints",
        request={
            "model": name,
            "component": int(target["id"]),
            "units": "mm",
            "expected": state,
            "constraints": q["constraints"],
        },
        target=name,
        binding={"constraints_before": before, "constraints_intent": intent},
        preview={
            "command": COMMAND,
            "model": name,
            "occurrence": str(target["id"]),
            "old_constraints": target["constraints"],
            "new_constraints": intent["constraints"],
            "affected_occurrences": intent["affected_occurrences"],
            "normal_pose": target["component_path_transform"],
            "construction_datums": [
                {
                    "feature_id": aux["feature_id"],
                    "surface_id": aux["surface_id"],
                    "consumer_occurrence": consumer,
                    "constraint_index": index,
                    "definition_before": aux["definition"],
                    "protection": "independently bind the same constraint slot and retain "
                    "the measured frame relation; other internal datums remain unchanged",
                }
                for _, aux, consumer, index in _construction_bindings(state).values()
            ],
            "pose_prediction": intent["pose_prediction"],
            "unchanged": [
                "occurrence identity and model",
                "non-target constraint sets",
                "unaffected actual poses",
                "constituent local geometry/material/dimensions/relations",
                "rigid child definitions",
            ],
            "not_checked": [
                "global_interference",
                "unloaded_external_owner_reuse",
                "construction_datum_dimension_id_crosscheck",
            ],
            "effect": "SetConstraints on the existing feature, then regenerate; "
            "no replacement, deletion, cloning or automatic rollback",
        },
        verify=check,
        observe=lambda c: snapshot(c, name),
        before=before,
        arguments={"model": name, "component": str(target["id"]), "request": q},
    )
    frozen = deepcopy(
        {key: getattr(p, key) for key in ("request", "binding", "preview", "arguments", "before")}
    )
    frozen_intent = deepcopy(intent)
    verified_after = {}
    settled_after = {}

    def same_plan(planned, c):
        return (
            planned is p
            and c is client
            and p.op == "assembly.redefine-constraints"
            and p.target == name
            and intent == frozen_intent
            and not getattr(c, "_native_read_pending", None)
            and not getattr(c, "_native_diagnostic_stop", None)
            and all(getattr(p, key) == value for key, value in frozen.items())
        )

    def verified_guard(planned, c):
        return (
            same_plan(planned, c)
            and bool(verified_after)
            and p.verified_observation == verified_after
        )

    def settled_observation(planned, c):
        return deepcopy(settled_after) if same_plan(planned, c) and settled_after else None

    def observed_failure_unchanged(after):
        if same_plan(p, client):
            settled_after.clear()
            settled_after.update(deepcopy(after))
        return failure_unchanged(before, after)

    p.failure_unchanged = observed_failure_unchanged
    p._verified_observation_guard = verified_guard
    p._settled_observation = settled_observation
    return p


def redefine(opts):
    return engine.write(COMMAND, opts, _prepare, _plan)


def recovery(client, run):
    plan = run["driver_plan"]
    retained = plan["base_snapshot"]["extensions"]["creo"]["observation"]
    before, intent = retained.get("constraints_before"), retained.get("constraints_intent")
    if not before or not intent or intent.get("profile") != PROFILE:
        _incomplete("frozen constraint intent/protection is unavailable")
    _retained_request(run, before, intent)
    if client.health()["service_instance_id"] != plan["target"]["instance_id"]:
        _incomplete("another native generation cannot settle this occurrence edit")
    after = snapshot(client, run["target"])
    checks = verify(before, after, intent)["checks"]
    accepted = all(c["passed"] for c in checks)
    return {
        "accepted": accepted,
        "checks": checks,
        "intent": intent,
        "current": after,
        "can_register": ["not_applied"]
        if before == after
        else ["applied"]
        if accepted
        else ["partial"],
        "coverage": "frozen direct occurrence, complete planar constraints/actual pose, "
        "constituent protection; no replay; saving is separate",
    }


def retained_evidence_sufficient(run, proof):
    retained = run["driver_plan"]["base_snapshot"]["extensions"]["creo"]["observation"]
    before, intent = retained.get("constraints_before"), retained.get("constraints_intent")
    if not before or not intent or intent != proof.get("intent"):
        _incomplete("retained constraint evidence lacks its frozen intent")
    _retained_request(run, before, intent)
    checks = verify(before, proof.get("current") or {}, intent)["checks"]
    if proof.get("accepted") is not all(c["passed"] for c in checks):
        _incomplete("retained constraint conclusion is inconsistent with independent evidence")
    after = proof.get("current")
    outcomes = (
        ["not_applied"] if before == after else ["applied"] if proof["accepted"] else ["partial"]
    )
    if proof.get("can_register") != outcomes:
        _incomplete("retained registration outcomes disagree with independent engineering evidence")


def _retained_request(run, before, intent):
    changes = run["driver_plan"].get("changes") or [{}]
    request = changes[0].get("after") or {}
    selection = (intent.get("request") or {}).get("selection") or {}
    if (
        request.get("model") != run["target"]
        or str(request.get("component")) != intent["target"]
        or request.get("expected") != before["native"]
        or request.get("units") != "mm"
        or request.get("constraints") != intent["request"]["constraints"]
        or selection.get("instance_id") != run["driver_plan"]["target"]["instance_id"]
        or selection.get("state_revision") != digest(before["native"])
    ):
        _incomplete("retained constraint intent does not match the original dispatched request")
