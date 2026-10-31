"""v1.0.2 lifecycle at the existing plan/read-back boundary, for declared paths only.

No backend change: plans and independent checks remain in their domain handlers. The
public plan/receipt/operation shapes are the pinned schemas, not a private protocol.
"""

from __future__ import annotations

import contextvars
import os
import uuid
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from . import dependencies as model_dependencies
from . import (
    driver_schema,
    driver_scope,
    native_diagnostic_recovery,
    native_read_recovery,
    object_identity,
    operations,
    paths,
    process_owner,
    safety,
    timing,
)
from .core import Error, digest

MIGRATED = {
    "service install": ["persist"],
    "workflow run": ["change", "persist", "artifact", "session"],
    "session cd": ["session"],
    "session exit": ["session"],
    "part create": ["session", "change", "persist"],
    "model open": ["session"],
    "model close": ["session"],
    "model discard": ["session", "change"],
    "model set-common-name": ["change"],
    "family-table apply": ["session", "change"],
    "family-table remove-instance": ["change"],
    "model save": ["persist"],
    "model regenerate": ["change"],
    "model import": ["change"],
    "feature extrude": ["change"],
    "feature revolve": ["change"],
    "feature datum-plane": ["change"],
    "feature datum-axis": ["change"],
    "feature chamfer": ["change"],
    "feature hole": ["change"],
    "feature round": ["change"],
    "feature shell": ["change"],
    "feature draft": ["change"],
    "feature rib": ["change"],
    "dimension set": ["change"],
    "dimension set-tolerance": ["change"],
    "model set-tolerance-standard": ["change"],
    "material assign": ["session", "change"],
    "appearance set": ["change"],
    "appearance restore": ["change"],
    "display activate": ["session"],
    "display fit": ["session"],
    "display component-visibility": ["session", "change"],
    "display unexplode": ["session"],
    "assembly create": ["session", "change", "persist"],
    "assembly component add": ["change"],
    "assembly component remove": ["change"],
    "assembly component replace": ["change"],
    "assembly component redefine": ["change"],
    "drawing create": ["change"],
    "drawing view add": ["change"],
    "drawing view move": ["session", "change"],
    "drawing view remove": ["session", "change"],
    "drawing dimension annotate": ["change"],
    "drawing dimension move": ["change"],
    "drawing note add": ["change"],
    "drawing layout apply": ["session", "change"],
    "artifact export": ["artifact"],
    "artifact render": ["session", "artifact"],
    "assembly explode apply": ["session", "change"],
    "drawing dimension add": ["change"],
    "drawing dimension hide": ["change"],
    "drawing note edit": ["change"],
    "drawing table add": ["session", "change"],
    "drawing bom add": ["session", "change"],
    "drawing bom balloons": ["session", "change"],
    "drawing title-block apply": ["session", "change"],
    "drawing table move": ["session", "change"],
    "drawing table remove": ["session", "change"],
    "drawing note remove": ["session", "change"],
    "drawing dimension remove": ["session", "change"],
    "parameter set": ["change"],
    "relation set": ["change"],
    "feature suppress": ["change"],
    "feature resume": ["change"],
    "feature rename": ["change"],
}
WORKFLOW_PARENT = contextvars.ContextVar("workflow_parent", default=None)
PRESENTATION_LIMITS = {
    "session exit": [
        "owned_session_exit 1; exact owned launch/generation/native process creation identity",
        "dangerous scope and explicit flag; raw model inventory must be empty",
        "fixed ProEngineerEnd only; no save, discard, process kill or automatic retry",
        "held xtop handle and correlated native exit witnesses; no post-exit CAD reads",
    ],
    **{
        command: [
            "source_part_appearance 2; whole source-part cosmetic appearance only, "
            "finite normalized RGB without quantization",
            "authorize the owned source file and all exact loaded affected occurrence paths; "
            "unloaded external reuse is not searched",
            "instance-independent overrides, face/body overrides and actual textures refused",
            "create_and_bind requires source_part_appearance_reference 1 and explicit source "
            "reference replacement authorization; native IDs are read back, never predicted",
            "new references also require source_part_appearance_unique_reference 1; a random "
            "candidate is not the actual native ID; other loaded source IDs must remain distinct",
            "same complete verification/effect observation; material, density, geometry, "
            "constraints and other colors protected; explicit save/reopen qualification separate",
        ]
        for command in ("appearance set", "appearance restore")
    },
    **{
        command: [
            "native_presentation 2; matching independent current-model/window/type required",
            "explicit inactive-model activation requires model_context_activation 1: a fixed "
            "registered native command, exact target identity and deferred context readback",
            "fit/visibility/unexplode require an already matching context; they never "
            "silently activate or restart the process",
            "temporary display effects and all related model modified flags observed separately; "
            "saved display persistence and actual image content require separate evidence",
        ]
        for command in (
            "display activate",
            "display fit",
            "display component-visibility",
            "display unexplode",
        )
    },
    "assembly explode apply": [
        "at most ten direct part occurrences; named assembly-axis translations only",
        "replace edits translations in place; no delete-before-create",
        "replace independently preserves the existing native state ID and default identity; "
        "missing identity is incomplete, not a default value",
        "confirmed write temporarily un-explodes for native normal-placement readback",
        "requires geometry_binary64_readback 1, assembly_explosion_context_readback 1 "
        "and matching current assembly/window; "
        "context is rechecked before mutation; no automatic display or activation",
        "the legacy physical_geometry_unchanged check compares mass_properties only; "
        "complete part geometry/material/tolerance protection needs independent task evidence",
        "model show.explosion supplies complete moves/activity; explode show is weaker "
        "enumeration; "
        "query/resolve retain generic snapshot/manual evidence semantics, not reconstructed "
        "explode postconditions",
        "no generic deactivate/restore, nested assembly, animation or workflow composition",
    ],
    "artifact render": [
        "render_state_restoration 3; active part/assembly graphics context with complete "
        "native source appearance/texture inventory; JPEG 64..4000 pixels per side",
        "retains caller framing and explosion; no automatic refit or window switching",
        "full decode and stable complete context readback; visibility/cropping checked separately",
        "failed staging artifacts retained; no overwrite, automatic replay or publication recovery",
        "operation-bound stage and publication identity retained before dispatch; "
        "cross-process lookup is read-only",
    ],
}
ENGINEERING_PROPERTY_LIMITS = {
    "material assign": [
        "mm/tonne parts; concrete modern UTF-8 MTL source bound by identity and SHA256",
        "density-only profile; tonne/mm^3, kg/m^3 or g/cm^3; no material-grade approval",
        "independent assigned density, mass, unchanged geometry and effective "
        "configuration readback",
    ],
    "dimension set-tolerance": [
        "existing non-reference dimensions; explicit units for numeric deviations",
        "numeric limits require regenerated readback and native ISO table detachment capability 1",
        "all nominal values and unrelated tolerances checked; drawing lettering "
        "separately inspected",
    ],
    "model set-tolerance-standard": [
        "loaded native getter/setter required; explicit ISO class only with ISO mode",
        "numeric dimension tolerances and model precision are separate properties",
    ],
}
MACHINING_LIMITS = {
    "feature rib": [
        "one standalone mm housing: one protrusion and one proven inward rectangular shell",
        "one horizontal line on an observed XZ datum, +X right / -Z up / +Y normal; "
        "symmetric whole-mm thickness strictly inside the cavity",
        "preview retains original request and freezes actual two-wall endpoints, "
        "native face identities and the unique floor-facing fill; no direction retries",
        "prismatic_rib_readback 3 requires native rib definition and actual section/references, "
        "complete connected single-body regions and full shell protection",
        "wrong position/fill, missing wall-floor connection, extra body or stale references "
        "cannot establish complete success; no workflow or automatic replay",
    ],
    "feature hole": [
        "native acceptance: simple linearly located through holes in an axis-aligned plate",
        "offsets are signed along reference plane normals; preview states model-space center",
        "reference spelling resolves to observed native identity; "
        "datum display extents are not solid boundaries",
        "unknown-result registration requires fresh current-solid proof "
        "against the retained intent",
        "current-solid cylinders, feature definition, dimensions and thickness span "
        "are read independently",
        "complete holes require full wall area, two connected closed circular rims with "
        "physical cap adjacency, no lateral opening and full cylindrical material removal",
        "new complete mm-hole previews freeze bounded-total-v2: native mm^3 units, "
        "relative total-volume tolerance 1e-6, floor 1e-6 mm^3 AND residual cap 0.001 mm^3; "
        "both intended and observed removal must exceed the effective numeric budget",
        "new complete previews also freeze retained-solid-boundary-v1: exactly two identified "
        "planar end caps may gain the intended circular trim; all other old physical faces "
        "and edges retain their actual identity, owner and geometric state",
        "the finite footprint must stay inside full-thickness planar sides and outside old "
        "axial-cylinder exclusions; one active body, model bbox and explicit standalone "
        "non-family evidence are frozen and protected",
        "complete physical owners and exact new-wall/new-rim inventories are required; an "
        "extra face owned by an existing feature or unrelated face change cannot be waived "
        "by a passing volume residual; axes/datums do not count as physical walls",
        "confirmation and query/resolve reuse the same frozen volume and solid-boundary "
        "policies; missing/unsupported/incomplete v1 cannot establish new applied registration; "
        "legacy inspection and historical receipts retain their original coverage",
        "physical outer bounds only exclude impossible footprints; missing wall or rim "
        "evidence cannot authorize applied registration",
        "threads, counterbores, countersinks, other placements and complex topology "
        "remain unverified",
    ],
    "feature round": [
        "native acceptance: constant-radius round on explicit straight exterior edges",
        "stored pre-round edge references and current solid geometry are distinct observations",
        "unknown-result registration requires constant radius and geometry "
        "at the selected axis-aligned orthogonal exterior edge, "
        "including full extent and curved area",
        "variable radius and complex topology remain unverified; no automatic rollback or replay",
    ],
    "feature shell": [
        "candidate profile: one saved standalone non-family rectangular mm prism, "
        "one explicit top face at maximum model Z, uniform inward thickness",
        "prismatic_shell_readback 2 preserves the requested driving thickness after creation; "
        "requires one active body, complete oriented planar faces, "
        "closed contours, physical edge adjacency and retained native shell definition",
        "wall/bottom/opening regions are compared with frozen pre-write intent; "
        "feature type and reduced volume alone cannot prove applied",
        "closed/outward/multiple-body shells, curved topology and local thickness are refused; "
        "no workflow, automatic replay or manufacturing approval",
    ],
    "feature draft": [
        "candidate profile: one saved standalone rectangular mm prism, one positive-X wall",
        "same actual top +Z datum as neutral and unflipped pull; whole-degree signed angle 1..15",
        "prismatic_draft_readback 1 binds the native single-surface selection, neutral/pull "
        "and constant unsplit angle; complete current plane polygons and adjacency required",
        "top footprint and opposite wall fixed; bottom and Y-wall trimming predicted explicitly",
        "hollow bodies, multiple selected walls, curved/split/variable draft, other frames "
        "and workflow composition are refused; no automatic replay or manufacturing approval",
    ],
}
FAMILY_TABLE_LIMITS = {
    "family-table apply": [
        "one saved part generic; at most four rows/four finite positive length dimension columns",
        "explicit authorized request file; native source and complete family identity required",
        "complete expected columns/rows/cells and inheritance are frozen before writing; "
        "members must identify this generic; post-write tables never define requested intent",
        "part-only session; no open instances at dispatch, nested tables, expressions or "
        "parameter/feature columns; existing rows need this generation's verified owned lineage",
        "retained dispatched assembly/drawing references also refuse edits to existing rows, "
        "even after the referencing model is closed",
        "newly instantiated members stay available for independent native reads; save the "
        "generic, then close only independently clean members; no instance save or discard bypass",
        "768 KiB snapshot; 128 features/4096 geometry items per part; no workflow composition",
        "failure cleanup is an attempt, not a rollback proof; missing instance geometry "
        "keeps recovery incomplete and queries never instantiate models",
    ],
    "family-table remove-instance": [
        "explicit dangerous scope/flag; one exact closed unused row created by a verified "
        "public apply in this instance and owned directory",
        "verified generic save after latest family write; table, model/window, dependencies "
        "and all bound version files rechecked; assembly/drawing combinations are refused",
        "known external references after row creation remain blocking after model close; "
        "reference removal/requalification is not supported by this profile",
        "no implicit close, cascading removal or disk deletion; no assertion about references "
        "outside the complete current session and owned project directory",
        "no workflow, automatic continuation or replay; independently inspect unknown outcomes",
    ],
}
_DRAWING_LAYOUT_LIMITS = [
    "layout_feedback uses already obtained per-sheet/unit rectangle candidates; "
    "raw observations and predicted candidate bounds are separate; no extra CAD getters",
    "R5 legacy_native_aggregate dimension boxes have completeness_not_independently_recorded "
    "and cross_time=unverified; current AABB warnings and two matching reads do not qualify "
    "complete envelopes or cross-time protection",
    "unknown sheet/units, invalid bounds and missing inventories are named unchecked gaps; "
    "different known pages do not intersect; no implicit unit conversion or sheet fallback",
    "duplicate view names/native IDs, ambiguous model/view ownership and sheet conflicts "
    "remain individually unchecked with snapshot/proposal indexes; a proposal excludes "
    "only its uniquely bound identical frozen row, never a name-based set",
    "note bounds cover text only, view bounds are coarse rectangles; leaders, balloon "
    "circles/glyphs, dimension/extension lines, exact contours, complete draft lines, "
    "unreadable alignment and actual table-cell text fit remain unchecked",
    "empty conflicts never means all layout clear: whole_layout_verified=false, "
    "cross_time_protection_verified=false and layout_coverage.complete=false; no automatic "
    "placement or pending-read recovery bypass",
]
DRAWING_EDIT_LIMITS = {
    **{
        command: list(_DRAWING_LAYOUT_LIMITS)
        for command in (
            "drawing view add",
            "drawing view move",
            "drawing dimension annotate",
            "drawing dimension move",
            "drawing table add",
            "drawing table move",
            "drawing bom add",
            "drawing bom balloons",
            "drawing title-block apply",
            "drawing layout plan",
            "drawing layout apply",
        )
    },
    "drawing view remove": [
        "single sheet, one part source, isolated unsectioned general view; "
        "native IDs and sheet bound",
        "no implicit cascade: dependent views, dimensions, notes and balloons are refused",
        "draft entities require full native straight-line IDs, page/view ownership and XYZ "
        "endpoints; arcs/other curves, target attachments or incomplete reads refuse",
        "multi-view alignment readback must be complete; a sole inventoried view proves "
        "there is no other incoming view dependency while preserving its own getter error",
        "placed symbols, datum tags, GTols, model-linked or merged/unreadable "
        "tables are unsupported",
        "256 items per resource, 128 source features, 4096 geometry items, 256 KiB snapshot limit",
        "source geometry and existing files are independently protected; "
        "deletion is unsaved until explicit save",
        "native evidence currently limited to the declared single-view case; "
        "full-tree FCC remains partial",
        "not added to workflow composition; no automatic replay, restore or cancellation",
    ],
    "drawing note edit": [
        "native readonly notes and substituted symbolic SECTION captions are refused in preview",
        "ordinary literal notes remain editable; unavailable editability is disclosed, not assumed",
    ],
}
DRAWING_EDIT_LIMITS["drawing view add"] += [
    "--exploded requires drawing_view_exploded_readback 1 and "
    "assembly_explosion_context_readback 1 "
    "before CAD dispatch; new-service "
    "normal/exploded flags come from independent WView2D.IsExplodedState, with unique "
    "new native view ID, model and sheet; never from the setter or assembly activity",
    "the full raw source inventory and observed-context fields are frozen and strictly compared; "
    "this is not independent proof of normal assembly placement; only "
    "explosion.is_exploded/context/display_readback are excluded from cross-context comparison, "
    "with both raw snapshots retained; global assembly display in drawing context is not_checked; "
    "per-view named exploded-state ID/name remains not_checked because no "
    "supported getter has been established; the frozen active state is never substituted for "
    "the view's state reference; visible separation and save/reopen are separate",
    "old R5 ordinary nonexploded views keep the legacy selected-postcondition scope; "
    "missing new native getter evidence is not synthesized as false",
]
CONSTRUCTION_LIMITS = {
    "model set-common-name": [
        "standalone non-family parts only, with only parts in session; readable native name "
        "and IsCommonNameModifiable required; 1..80 nonempty characters",
        "readback capability 2: complete native origin and family inventories for every "
        "protected part; missing origin is not a working-directory fallback",
        "part geometry/properties, model/window identities and saved-file identities protected; "
        "16 models, 32 windows, 128 features/4096 geometry items per part, 512 KiB snapshot",
        "common name is separate from filename/parameters; no implicit save or associated "
        "BOM/title update; same value does not establish clean memory",
        "not enabled in workflow; recovery requires stable independent current-instance evidence",
    ],
    "model discard": [
        "standalone saved non-family parts only, with only parts in session; explicit dangerous "
        "scope and flag; unknown modified/dependency/identity state refuses",
        "verified public model save in this instance must match latest origin file; prepare "
        "baseline before unwanted edits; do not save unwanted changes to pass the gate",
        "preserve all disk versions, other parts and window identities; 16 models/32 windows, "
        "128 features/4096 geometry items per part and 512 KiB snapshot",
        "window close followed by Erase failure can change the session; absent target alone "
        "does not prove complete discard; explicit reopen verifies baseline",
        "active target window may change; no camera restore, automatic reopen or replay; "
        "not enabled in workflow",
    ],
    "part create": [
        "first-version bytes and file identity must stay stable across modified-state readback",
        "dirty memory is unsaved; unstable evidence is unknown and cannot authorize closing",
    ],
    "assembly create": [
        "first-version bytes and file identity must stay stable across modified-state readback",
        "dirty memory is unsaved; unstable evidence is unknown and cannot authorize closing",
    ],
    "drawing dimension move": [
        "one sheet; at most six read-only samples and 12 seconds within the invocation deadline",
        "two matching anchor-relative observations support only this move's limited "
        "translation consistency; aggregate completeness and cross-time stability "
        "remain unverified",
        "unproved/rerouted bounds are null, verification incomplete, already moved anchor retained",
        "preview flags known sheet/table/text/view conflicts; no leader-routing or layout approval",
    ],
    "feature revolve": [
        "first solid only; one-sided full 360 degree add on the default body; closed orthogonal "
        "rectangle/polygon with at most 16 vertices and one radial interval per axial station",
        "axis lies in the sketch plane, parallel to a sketch coordinate and a model axis",
        "independent native definition/section frame, trimmed face groups, areas and closed "
        "circular rims; raw native curved outlines can be conservative",
        "coplanar shoulders are separate native connected regions with their own radial rims",
        "partial angles, curved profiles, cuts, intersecting solids and creating workflows "
        "are refused before dispatch",
    ],
    "feature datum-plane": [
        "signed offset from a readable plane; native constraint, position and normal verified",
        "infinite geometric datum; display extent is not material or manufacturing datum",
        "angular construction is not supported by this bounded public proof",
    ],
    "feature datum-axis": [
        "two nonparallel planes, one straight edge or one cylindrical face",
        "full unoriented spatial line and native through-reference constraints verified",
        "display endpoints do not bound an infinite datum axis",
    ],
}


def profile():
    return {
        "spec": "tool-driver-cli-spec",
        "spec_version": "1.0.2",
        "schema_version": "2.0",
        "base": {"spec": "ai-native-cli-spec", "version": "v1.6.3"},
        "record": {
            "store": str(safety.directory() / operations.DATABASE),
            "retain_days": None,
            "survives_cli_exit": True,
            "survives_reconnect": True,
            "survives_instance_restart": True,
            "limitations": [
                "local state must remain intact; 5000-record bound fails closed",
                "snapshots remain tied to their original instance; no automatic native replay",
            ],
        },
    }


def command_metadata(command):
    from . import __version__
    from .core import CODES

    return {
        "capability_id": command.replace(" ", "-"),
        "effects": MIGRATED[command],
        "phases": ["observe", "plan", "apply", "verify"],
        "modes": ["file" if command == "service install" else "session"],
        "maturity": "experimental",
        "environments": [
            {
                "application": "Creo Parametric",
                "application_version": "13.4.1.0",
                "platform": "Windows",
                "arch": "x86_64",
                "adapter_version": __version__,
                "mode": "file" if command == "service install" else "session",
                "limitations": [
                    "offline component file installation; loading requires declared "
                    "local Creo/Java dependencies"
                    if command == "service install"
                    else "Object TOOLKIT Java and matching source-bound native library required"
                ],
            }
        ],
        "limits": [
            "command checks only; separate consumer/design-intent verification is required",
            "public runtime adoption is partial; workflow has a bounded public lifecycle",
        ]
        + PRESENTATION_LIMITS.get(command, [])
        + MACHINING_LIMITS.get(command, [])
        + CONSTRUCTION_LIMITS.get(command, [])
        + ENGINEERING_PROPERTY_LIMITS.get(command, [])
        + DRAWING_EDIT_LIMITS.get(command, [])
        + FAMILY_TABLE_LIMITS.get(command, []),
        "recovery": {"atomicity": "none", "undo": False, "idempotent": False, "cancel": False},
        "profiles": ["core", "operation_status"],
        "error_codes": sorted(CODES),
        "evidence_refs": ["docs/ENGINEERING-WORKFLOW.md", "docs/RUNTIME-MIGRATION.md"],
        "result_schema": "urn:tool-driver-cli-spec:receipt:2.0",
    }


def migration():
    from .registry import COMMANDS

    remaining = [
        c.path
        for c in COMMANDS
        if c.write and c.path not in MIGRATED and c.path != "operation resolve"
    ]
    return {
        "status": "partial",
        "migrated_write_paths": sorted(MIGRATED),
        "remaining_write_paths": remaining,
        "record_controls": ["operation show", "operation query", "operation resolve --outcome"],
        "write_paths_total": sum(c.write for c in COMMANDS),
        "migrated_write_paths_count": len(MIGRATED),
        "remaining": [
            "whole-tree behavior FCC and unexecuted native variants; "
            "syntax and discovery schemas are separate",
            "workflow creation/dynamic targets and automatic resume",
            "batch/cancel/resume/late receipt routing",
        ],
    }


class SchemaValidator:
    def validate(self, name, value):
        driver_schema.validate(name, value)


def scope():
    return driver_scope.ScopeResolver("creo-cli", validator=SchemaValidator()).resolve()


def snapshot(value, *, source="live", dependencies=(), source_details=None):
    result = {
        "id": uuid.uuid4().hex,
        "source": source,
        "revision": digest(value),
        "observed_at": operations.now(),
        "dependencies": list(dependencies),
        "extensions": {"creo": {"observation": value}},
    }
    if source_details is not None:
        result["source_details"] = source_details
    return result


@timing.phase("identity_resolution")
def target(client, p):
    if p.op == "session.exit":
        return deepcopy(p.preview["owned_target"])
    if p.op == "service.install":
        return p.preview["file_target"]
    health = client.health()
    instance = health.get("service_instance_id")
    if not isinstance(instance, str) or not instance:
        raise Error(
            "E_BACKEND_UNAVAILABLE",
            "loaded service has no generation identity",
            {"dispatch_state": "not_started"},
        )
    identities = sorted(
        getattr(p, "preview", {}).get(
            "model_footprint", object_identity.claims(p.target, p.op, p.request)
        )
    )
    object_id = (
        p.target
        if p.op != "model.import"
        else identities[0]
        if len(identities) == 1
        else "import-slot:" + p.request["name"].lower()
    )
    return {
        "mode": "session",
        "engine_id": "creo",
        "instance_id": instance,
        "object_id": object_id,
        "locator": client.url + "/models/" + object_id,
        "extensions": {
            "creo": {
                "ownership": "attached",
                "runtime_class": health.get("runtime_class"),
                "source_sha256": health.get("source_sha256"),
                "process_id": health.get("process_id"),
                "object_claims": identities,
            }
        },
    }


def _annotation_path_nodes(nodes, session, roots):
    """Admit only one complete, same-invocation bounded drawing dependency graph."""

    def incomplete(reason):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "fresh annotation dependency closure is incomplete",
            {"reason": reason, "dispatch_state": "not_started", "automatic_retry": False},
        )

    present = session.get("models") if isinstance(session, dict) else None
    if (
        not isinstance(present, list)
        or any(not isinstance(n, str) or not object_identity.MODEL.fullmatch(n) for n in present)
        or len(present) != len(set(present))
    ):
        incomplete("session model identities")
    if not isinstance(nodes, list) or not nodes or len(nodes) > model_dependencies.MAX_MODELS:
        incomplete("node inventory")
    by_name = {}
    for node in nodes:
        if not isinstance(node, dict):
            incomplete("node row")
        name = node.get("identity")
        if (
            not isinstance(name, str)
            or not object_identity.MODEL.fullmatch(name)
            or name not in present
            or name in by_name
        ):
            incomplete("node identity")
        described = node.get("description")
        children = node.get("children")
        revision = node.get("revision")
        kind = {"prt": "part", "asm": "assembly", "drw": "drawing"}[name.rsplit(".", 1)[1].lower()]
        if (
            not isinstance(described, dict)
            or described.get("model") != name
            or described.get("type") != kind
            or not isinstance(revision, str)
            or not revision
            or not isinstance(children, list)
            or any(
                not isinstance(n, str) or not object_identity.MODEL.fullmatch(n) for n in children
            )
            or len(children) != len(set(children))
        ):
            incomplete("node description, revision or children")
        if kind == "drawing":
            expected = described.get("models")
            if not isinstance(expected, list) or any(not isinstance(n, str) for n in expected):
                incomplete("drawing model identities")
        elif kind == "assembly":
            components = described.get("components")
            if not isinstance(components, list) or any(
                not isinstance(c, dict) or not isinstance(c.get("model"), str) for c in components
            ):
                incomplete("component model identities")
            expected = [c["model"].lower() for c in components]
        else:
            expected = []
        family = described.get("family")
        if family is not None and not isinstance(family, dict):
            incomplete("family identity")
        generic = (family or {}).get("generic")
        if generic and kind in ("part", "assembly"):
            if not isinstance(generic, str):
                incomplete("generic identity")
            expected = [*expected, generic.lower()]
        if any(not object_identity.MODEL.fullmatch(n) for n in expected) or set(children) != set(
            expected
        ):
            incomplete("description and dependency edges differ")
        by_name[name] = node
    visiting, visited = set(), set()

    def visit(name, depth):
        if name not in by_name or name in visiting or depth > model_dependencies.MAX_DEPTH:
            incomplete("missing child, cycle or depth bound")
        if name in visited:
            return
        visiting.add(name)
        for child in by_name[name]["children"]:
            visit(child, depth + 1)
        visiting.remove(name)
        visited.add(name)

    for name in roots:
        visit(name, 0)
    if visited != set(by_name):
        incomplete("unrelated extra dependency")


def affected_paths(client, p, nodes=None):
    """All workspace models in a plan's dependencies, not only its primary target."""
    from . import engine

    if p.op in (
        "workflow.run",
        "service.install",
        "model.set-common-name",
        "model.discard",
        "session.exit",
    ):
        return p.preview["scope_paths"]
    if p.op in ("model.export", "model.render"):
        return []  # source models are observed; only declared artifact/staging paths are written
    s = engine.session(client)
    result = []
    roots = model_dependencies.references(p.preview.get("command", ""), p.request) | {p.target}
    if p.op.startswith(("appearance.", "display.")):
        footprint = set(p.preview.get("model_footprint", [])) - {"session:presentation"}
        if any(not object_identity.MODEL.fullmatch(name) for name in footprint):
            raise Error(
                "E_VERIFY_INCOMPLETE", "appearance/display footprint has an invalid model identity"
            )
        roots |= footprint
    if nodes is None:
        nodes = model_dependencies.closure(client, roots)
    else:
        bounded = {
            "drawing bom add": "drawing.add-bom",
            "drawing bom balloons": "drawing.add-balloons",
            "model close": "model.close",
            "drawing add-view": "drawing.add-view",
            "feature extrude": "feature.extrude",
            "assembly add": "assembly.add",
            "model save": "model.save",
            "appearance set": "appearance.set",
            "appearance restore": "appearance.restore",
            "display activate": "display.activate",
            "display fit": "display.fit",
            "display component-visibility": "display.visibility",
            "display unexplode": "display.unexplode",
        }
        declared = set(p.preview.get("model_footprint", []))
        if p.op.startswith("display."):
            declared -= {"session:presentation"}
        if bounded.get(p.preview.get("command")) != p.op or roots != roots | declared:
            raise Error(
                "E_VERIFY_INCOMPLETE", "shared dependency roots exceed bounded annotation paths"
            )
        _annotation_path_nodes(nodes, s, roots)
    related = {n["identity"]: n.get("description") for n in nodes}
    for name in s["models"]:
        if name in related:
            description = related[name]
            if not isinstance(description, dict) or description.get("model") != name:
                raise Error(
                    "E_VERIFY_INCOMPLETE",
                    "dependency description is incomplete; cannot establish its store directory",
                    {"model": name},
                )
            result.append((str(engine.store_directory(description, s)), "change"))
    result.extend((str(file), "observe") for file in p.preview.get("input_files", []))
    if not result and p.op in ("part.create", "assembly.create", "drawing.create", "model.import"):
        result.append((str(engine.working_directory(s)), "change"))
    if p.op == "session.cd":
        result.append((p.request["path"], "session"))
    return result


def outputs_for(p):
    if p.op in ("workflow.run", "service.install"):
        return p.preview["scope_outputs"]
    rows = []
    if p.op == "model.save":
        rows.append(
            {
                "path": str(Path(p.preview["directory"]) / p.preview["next_version"]),
                "effect": "persist",
                "exists": False,
            }
        )
    elif p.op in ("model.export", "model.render"):
        output = p.preview.get("output") or p.arguments.get("output")
        rows.extend(
            [
                {"path": str(output), "effect": "artifact", "exists": Path(output).exists()},
                {
                    "path": str(paths.workspace() / ".creo-cli" / "staging"),
                    "effect": "artifact",
                    "exists": True,
                },
            ]
        )
    return rows


def require_clear(t, dependencies=()):
    def conflicts(run):
        plan = run.get("driver_plan")
        if plan is None:
            return True  # legacy uncertainty has no reliable instance/footprint identity
        other = plan["target"]
        if any(other.get(k) != t.get(k) for k in ("engine_id", "instance_id")):
            return False
        if other.get("mode") == t.get("mode") == "file":
            # A pending directory installation owns its whole subtree. Prefix strings
            # would also block unrelated siblings such as components and components2.
            left, right = (Path(x["object_id"]).resolve() for x in (other, t))
            try:
                common = os.path.normcase(os.path.commonpath((left, right)))
            except ValueError:  # distinct volumes
                return False
            return common in {os.path.normcase(str(left)), os.path.normcase(str(right))}
        return bool(
            object_identity.footprints(plan)
            & (object_identity.target_claims(t) | set(dependencies))
        )

    blocked = [
        r
        for r in operations.selected_runs(
            statuses=operations.UNRESOLVED + ("resolved_manual",), write_cache=True
        )
        if (
            r["status"] in operations.UNRESOLVED
            or (r["status"] == "resolved_manual" and not resolution_evidence_trusted(r))
        )
        and r["operation_id"] != WORKFLOW_PARENT.get()
        and (not r.get("driver_resolution") or not resolution_evidence_trusted(r))
        and conflicts(r)
    ]
    if blocked:
        r = blocked[0]
        raise Error(
            "E_CONFLICT",
            "an earlier operation needs inspection",
            {
                "conflict": "lock_held"
                if r["status"] == "running"
                and r.get("driver_stage") != "finalizing"
                and not process_owner.abandoned(r.get("driver_owner"))
                else "unresolved_operation",
                "active_operation": status(r) if r.get("driver_plan") else r,
                "operation_ids": [r["operation_id"]],
                "dispatch_state": "not_started",
                "next_action": "inspect operation and target, then resolve with evidence",
            },
        )


@timing.phase("observation")
def guard_model(command, client, opts):
    """Block an unresolved footprint before domain planning/getters can mask the conflict."""

    if command == "session exit":
        client.require_capability("owned_session_exit", 1)
    if command in ("drawing note add", "drawing add-note"):
        client.require_capability("simple_drawing_note_readback", 1)
    if command == "drawing view add" and opts.get("exploded"):
        client.require_capability("drawing_view_exploded_readback", 1)
        client.require_capability("assembly_explosion_context_readback", 1)
    if command == "assembly explode apply":
        client.require_capability("assembly_explosion_context_readback", 1)
        client.require_capability("geometry_binary64_readback", 1)
    if command.startswith("appearance "):
        client.require_capability("source_part_appearance", 2)
    if command.startswith("display "):
        client.require_capability("native_presentation", 2)

    capability = {
        "assembly component redefine": "assembly_constraint_redefinition",
        "dimension set": "dimension_regeneration_readback",
        "model regenerate": "model_regeneration",
        "drawing view move": "drawing_window_activation",
        "model set-common-name": "model_management_readback",
        "model discard": "model_management_readback",
        "model close": "model_management_readback",
        "family-table apply": "family_dimension_runtime",
        "family-table remove-instance": "family_dimension_runtime",
        "drawing view remove": "drawing_view_dependencies",
        "drawing layout apply": "drawing_window_activation",
        "drawing title-block apply": "title_projection_arcs",
        "assembly explode apply": "explosion_state_readback",
        "artifact render": "render_state_restoration",
        "feature hole": "machining_feature_readback",
        "feature round": "machining_feature_readback",
        "feature shell": "prismatic_shell_readback",
        "feature draft": "prismatic_draft_readback",
        "feature rib": "prismatic_rib_readback",
        "feature revolve": "revolved_datum_readback",
        "feature datum-plane": "revolved_datum_readback",
        "feature datum-axis": "revolved_datum_readback",
        "material assign": "material_source_binding",
    }.get(command)
    if capability:
        client.require_capability(
            capability,
            3
            if capability in ("prismatic_rib_readback", "render_state_restoration")
            else 2
            if capability
            in (
                "title_projection_arcs",
                "explosion_state_readback",
                "model_management_readback",
                "prismatic_shell_readback",
                "prismatic_rib_readback",
                "assembly_constraint_redefinition",
            )
            else 1,
        )

    roots = model_dependencies.references(command, opts)
    if not roots:
        return
    for name in roots:
        require_clear(target(client, SimpleNamespace(target=name, op=command, request={})), roots)
    nodes = model_dependencies.closure(client, roots)
    for name in roots:
        require_clear(
            target(client, SimpleNamespace(target=name, op=command, request={})),
            [n["identity"] for n in nodes],
        )


_BOUND_CONSTRUCTION_OPS = ("feature.revolve", "feature.datum-plane", "feature.datum-axis")


def _effect_observation(p, client):
    """Admit a leaf's verified snapshot without performing another native read."""
    guard = getattr(p, "_verified_observation_guard", None) or getattr(
        p, "_verified_view_guard", None
    )
    if (
        p.op
        in ("drawing.add-view", "assembly.redefine-constraints", "assembly.explode", "model.close")
        + _BOUND_CONSTRUCTION_OPS
        or guard is not None
    ):
        # This leaf retains an internal preview alias. Its independent verifier
        # additionally binds reuse to the exact Plan, Client and frozen inputs.
        if not callable(guard) or not guard(p, client):
            if (
                p.op
                in ("assembly.redefine-constraints", "assembly.explode", "model.close")
                + _BOUND_CONSTRUCTION_OPS
            ):
                raise Error(
                    "E_VERIFY_INCOMPLETE",
                    "the complete protected observation is not bound to this Plan and Client",
                    {"automatic_retry": False},
                )
            return None
    return getattr(p, "verified_observation", None)


def record_confirmation_refusal(run, error, actual_binding=None):
    """Append this undispatched write attempt; preserve any original execution/reader facts."""
    if "confirmation_attempt" in error.details:
        return
    error.details.setdefault("operation_id", run["operation_id"])
    error.details.setdefault("dispatch_state", "not_started")
    try:
        attempt = operations.record_confirmation_rejection(run, error, actual_binding)
    except Error as recording:
        error.details["confirmation_attempt_record_error"] = recording.code
        error.details["confirmation_attempt_retained"] = False
        return
    error.details["confirmation_attempt"] = {
        key: attempt[key]
        for key in (
            "attempt_id",
            "status",
            "terminal",
            "dispatch_state",
            "write_started",
            "original_operation_status",
        )
    }
    error.details["confirmation_attempt_retained"] = True


def _admit_confirmation(opts, run, binding, missing, grant, local_install):
    operation_id = run["operation_id"]
    if run.get("driver_plan") is None:
        raise Error("E_CONFLICT", "no retained public plan", {"conflict": "token_mismatch"})
    if run["status"] != "planned":
        raise Error(
            "E_CONFLICT",
            "operation was already dispatched",
            {
                "conflict": "token_used",
                "operation_id": operation_id,
            },
        )
    if run["driver_binding"].get("driver_scope_sha256") != binding["driver_scope_sha256"]:
        from . import binding_diagnostics

        raise Error(
            "E_CONFLICT",
            "task scope changed since preview",
            {
                "conflict": "scope_changed",
                "operation_id": operation_id,
                "dispatch_state": "not_started",
                "changed": ["driver_scope_sha256"],
                "binding_difference": binding_diagnostics.differences(
                    run["driver_binding"], binding
                ),
            },
        )
    if missing:
        denied = driver_scope.forbidden(grant, missing)
        denied.details |= {"operation_id": operation_id, "dispatch_state": "not_started"}
        raise denied
    if local_install:
        if safety.permission() != "write":
            raise Error("E_FORBIDDEN", "installation needs explicit write permission")
    else:
        safety.require_write()
    safety.consume(opts.get("confirm"), binding, expected_binding=run["driver_binding"])


def write(command, opts, client, p):
    from . import engine

    effects = p.effects or MIGRATED[command]
    local_install = p.op == "service.install"
    if not local_install:
        client._guard_pending_read(p.op)
    safety.actor()
    policy = (
        {
            "permission": safety.permission(),
            "confirm_allowed": safety.permission() == "write",
            "native_opt_in_required": False,
        }
        if local_install
        else safety.policy()
    )
    if command in ("drawing view move", "drawing layout apply"):
        client.require_capability("drawing_window_activation", 1)
        p.first = lambda c: c.op("drawing.activate", {"model": p.target}, write=True)
    t = target(client, p)
    grant = scope()
    outputs = outputs_for(p)
    roots = (
        set(p.preview.get("model_footprint", []))
        | model_dependencies.references(command, p.request)
        | {p.target}
    )
    fresh_nodes = None
    bounded = {
        "drawing bom add": ("drawing.add-bom", "drawing bom add"),
        "drawing bom balloons": ("drawing.add-balloons", "drawing bom balloons"),
        "model close": ("model.close", "model close"),
        "drawing view add": ("drawing.add-view", "drawing add-view"),
        "feature extrude": ("feature.extrude", "feature extrude"),
        "assembly component add": ("assembly.add", "assembly add"),
        "model save": ("model.save", "model save"),
        "appearance set": ("appearance.set", "appearance set"),
        "appearance restore": ("appearance.restore", "appearance restore"),
        "display activate": ("display.activate", "display activate"),
        "display fit": ("display.fit", "display fit"),
        "display component-visibility": ("display.visibility", "display component-visibility"),
        "display unexplode": ("display.unexplode", "display unexplode"),
    }
    if command in bounded:
        path_roots = model_dependencies.references(p.preview.get("command", ""), p.request) | {
            p.target
        }
        if p.op.startswith(("appearance.", "display.")):
            roots.discard("session:presentation")
            path_roots |= set(p.preview.get("model_footprint", [])) - {"session:presentation"}
        expected_op, expected_preview = bounded[command]
        if (
            p.op != expected_op
            or p.preview.get("command") != expected_preview
            or path_roots != roots
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE", "shared dependency roots exceed bounded annotation paths"
            )
        # This is the existing final fresh closure, obtained after this Plan was
        # built. Both path authorization and token/conflict binding use these exact
        # nodes. No preflight observation or previous invocation is reused.
        fresh_nodes = model_dependencies.closure(client, roots)
        touched = affected_paths(client, p, fresh_nodes)
    else:
        touched = affected_paths(client, p)
    missing = grant.missing(
        effects=effects,
        dangerous=bool(opts.get("dangerous")),
        target=t,
        outputs=outputs,
        paths=touched,
    )
    maximum = grant.max_operations
    used = (
        sum(
            r.get("started_at") is not None and r.get("scope_id") == grant.scope_id
            for r in operations.summaries(write_cache=True)
        )
        if maximum is not None
        else 0
    )
    cost = p.preview.get("operation_cost", 1)
    if maximum is not None and used + cost > maximum:
        missing["limit"] = {"max_operations": maximum, "used": used}
    if p.op == "workflow.run":
        missing.update(p.preview["scope_missing"])
    # Do not bind the random staging directory allocated by each export preview.
    binding = safety.scope(
        command, p.target, {"arguments": p.arguments, "request": p.request}, digest(p.binding)
    )
    if local_install:
        binding["native_opt_in"] = False
    binding.update(
        driver_scope_sha256=digest(grant.record),
        driver_target=t,
        driver_effects=effects,
        driver_paths=touched,
        driver_outputs=outputs,
    )
    execution_budget = timing.execution_profile()
    if execution_budget is not None:
        binding["driver_execution_budget"] = execution_budget
        p.preview["execution_budget"] = execution_budget
    nodes = (
        []
        if local_install
        else fresh_nodes
        if fresh_nodes is not None
        else model_dependencies.closure(client, roots)
    )
    dependencies = model_dependencies.snapshots(nodes)
    require_clear(t, [row["identity"] for row in dependencies])
    binding["driver_dependencies"] = dependencies
    if opts.get("dry_run"):
        op_id = opts.get("_workflow_operation_id") or uuid.uuid4().hex
        token, expires = safety.issue(binding, operation_id=op_id)
        mixed = p.op in ("model.save", "model.open", "model.import", "workflow.run") or command in (
            "drawing view remove",
            "family-table apply",
            "family-table remove-instance",
        )
        base = snapshot(
            p.binding,
            dependencies=dependencies,
            source="disk" if local_install else "mixed" if mixed else "live",
            source_details={
                "live": "domain plan getters",
                "disk": "input file or saved-version hashes",
            }
            if mixed
            else None,
        )
        if p.op == "session.exit":
            base["extensions"]["creo"]["process_observation"] = deepcopy(p.before["process"])
            base["extensions"]["creo"]["state_revision_projection"] = deepcopy(
                p.preview["state_revision_projection"]
            )
        public = {
            "plan_id": uuid.uuid4().hex,
            "operation_id": op_id,
            "capability_id": command.replace(" ", "-"),
            "target": t,
            "base_snapshot": base,
            "authorization_scope_id": grant.scope_id or "read-only",
            "effects": effects,
            "level": "plan",
            "changes": [
                {
                    "action": p.op,
                    "resource": p.target,
                    "summary": str(p.preview.get("effect") or p.preview.get("note") or command),
                    "after": p.request,
                }
            ],
            "outputs": outputs,
            "unknowns": ["precondition check and API apply are not atomic"],
            "constraints": [
                "component files only; no registration, loading or restart"
                if local_install
                else "explicitly terminate only the exact owned empty session; "
                "no automatic save/discard/kill"
                if p.op == "session.exit"
                else "attached user instance; no automatic shutdown",
                "no automatic retry after dispatch",
            ],
            "trial_snapshot": None,
            "can_apply": not missing and policy["confirm_allowed"],
            "expires_at": expires,
            "extensions": {"creo": p.preview | {"policy": policy, "scope_missing": missing}},
            "_untrusted": ["extensions.creo"],
        }
        timing.stamp(public)
        driver_schema.validate("plan", public)
        operations.record_plan(command, p.target, p.request, client.url, public, binding)
        return {
            "preview": public,
            "confirm_token": token,
            "expires_at": expires,
            "_untrusted": ["preview"],
        }
    operation_id = safety.token_operation(opts.get("confirm"))
    run = operations.get(operation_id)
    try:
        _admit_confirmation(opts, run, binding, missing, grant, local_install)
    except Error as exc:
        record_confirmation_refusal(run, exc, binding)
        raise
    try:
        output = engine.execute(command, client, p, planned=run)
    except Error as exc:
        try:
            current = operations.get(operation_id)
        except Error:
            current = run | {"status": "unknown"}
        if current.get("driver_stage") == "finalizing":
            current["status"] = current.get("domain_status", "unknown")
        pending = native_read_recovery.capture_client(
            current, client
        ) or native_read_recovery.capture(current, exc)
        diagnostic = native_diagnostic_recovery.capture_client(
            current, client
        ) or native_diagnostic_recovery.capture(current, exc)
        if pending or diagnostic:
            current.setdefault("driver_effect_readback_error", deepcopy(diagnostic or pending))
            current["driver_effect_observed"] = False
        settled_reader = getattr(p, "_settled_observation", None)
        settled = (
            settled_reader(p, client)
            if p.op == "assembly.explode"
            and callable(settled_reader)
            and not (pending or diagnostic)
            else None
        )
        if p.op in _BOUND_CONSTRUCTION_OPS:
            # A failed verifier must never be replaced by an unverified later
            # getter. Only its own complete, bound observation may settle effects.
            settled = (
                settled_reader(p, client)
                if callable(settled_reader) and not (pending or diagnostic)
                else None
            )
            if settled is not None:
                current["driver_effect_readback"] = deepcopy(settled)
                current["driver_effect_readback_source"] = (
                    "independent construction observation checked by this Plan and Client"
                )
                current["driver_effect_observed"] = True
            else:
                current["driver_effect_observed"] = False
                first_reader = getattr(p, "_first_verification_failure", None)
                first_error = (
                    first_reader(p, client)
                    if callable(first_reader) and not (pending or diagnostic)
                    else None
                )
                if first_error is not None:
                    current["driver_effect_readback_error"] = deepcopy(first_error)
                if current["status"] != "failed_before_write":
                    current["status"] = "unknown"
        elif not (pending or diagnostic) and (
            current["status"] not in ("unknown", "running", "failed_before_write")
            or settled is not None
        ):
            try:
                if settled is None:
                    settled = settled_reader(p, client) if callable(settled_reader) else None
                verified = settled if settled is not None else _effect_observation(p, client)
                current["driver_effect_readback"] = (
                    deepcopy(verified) if verified is not None else p.observe(client)
                )
                if verified is not None:
                    current["driver_effect_readback_source"] = (
                        "independent failure-settling observation bound to this Plan and Client"
                        if settled is not None
                        else "independent snapshot checked by this leaf verifier"
                    )
                current["driver_effect_observed"] = True
            except Error as readback_error:
                current["driver_effect_observed"] = False
                current["driver_effect_readback_error"] = native_read_recovery.error_record(
                    readback_error
                )
                if current.get("native_close_read_refusal"):
                    # The narrow unchanged classification is useful only with
                    # its original bound observation. Never replace it with B.
                    current["status"] = "unknown"
                pending = native_read_recovery.capture(current, readback_error)
                diagnostic = native_diagnostic_recovery.capture(current, readback_error)
        receipt = make_receipt(current, p, exc.details.get("receipt"), exc)
        if p.op == "workflow.run":
            outcome_code = error_for(receipt, exc.code)
            current["status"] = (
                "unknown"
                if outcome_code in ("E_OUTCOME_UNKNOWN", "E_NATIVE_DIAGNOSTIC")
                else "partial"
                if outcome_code == "E_PARTIAL"
                else "failed_before_write"
            )
            current["driver_stage"] = "finished"
        current["driver_receipt"] = receipt
        current["finished_at"] = operations.now()
        try:
            operations.update(current)
        except Error as recording:
            exc.details.update(record_store_unavailable=True, record_error=recording.code)
            current["status"] = "unknown"
            receipt = make_receipt(current, p, error=exc)
        exc.details.update(
            receipt=receipt,
            operation_id=operation_id,
            dispatch_state="dispatched"
            if exc.details.get("request_sent") or exc.details.get("service_reported_done")
            else "unknown",
            next_action="inspect the operation and actual target; never blindly repeat the write",
        )
        exc.details.update(native_read_recovery.details(pending))
        exc.details.update(native_diagnostic_recovery.details(diagnostic))
        code = error_for(receipt, exc.code)
        if code != exc.code:
            exc.details.setdefault("cause_code", exc.code)
        raise Error(code, exc.message, exc.details) from exc
    current = operations.get(operation_id)
    current["status"] = output["status"]
    current["driver_stage"] = "finalizing"
    try:
        verified = _effect_observation(p, client)
        current["driver_effect_readback"] = (
            deepcopy(verified) if verified is not None else p.observe(client)
        )
        current["driver_effect_readback_source"] = (
            "independent snapshot checked by this leaf verifier"
            if verified is not None
            else "independent post-verification reading"
        )
        current["driver_effect_observed"] = True
    except Error as readback_error:
        current["driver_effect_observed"] = False
        current["driver_effect_readback_error"] = native_read_recovery.error_record(readback_error)
        native_read_recovery.capture(current, readback_error)
        native_diagnostic_recovery.capture(current, readback_error)
    receipt = make_receipt(current, p, output)
    if receipt["outcome"]["change"] == "unknown":
        current["status"] = "unknown"
    code = error_for(receipt, None)
    if code == "E_OUTCOME_UNKNOWN":
        current["status"] = "unknown"
    elif code == "E_PARTIAL":
        current["status"] = "partial"
    current.update(driver_receipt=receipt, finished_at=operations.now(), driver_stage="finished")
    try:
        operations.update(current)
    except Error as recording:
        current["status"] = "unknown"
        unknown_receipt = make_receipt(current, p)
        raise Error(
            "E_NATIVE_DIAGNOSTIC"
            if native_diagnostic_recovery.diagnostic_error(current)
            else "E_OUTCOME_UNKNOWN",
            "could not retain the completed outcome",
            {
                "operation_id": operation_id,
                "receipt": unknown_receipt,
                "dispatch_state": "dispatched",
                "record_error": recording.code,
            }
            | native_read_recovery.details(native_read_recovery.pending_error(current))
            | native_diagnostic_recovery.details(
                native_diagnostic_recovery.diagnostic_error(current)
            ),
        ) from recording
    if current["status"] == "unknown":
        raise Error(
            "E_NATIVE_DIAGNOSTIC"
            if native_diagnostic_recovery.diagnostic_error(current)
            else "E_OUTCOME_UNKNOWN",
            "completion reported but actual effect could not be established",
            {"operation_id": operation_id, "receipt": receipt, "dispatch_state": "dispatched"}
            | native_read_recovery.details(native_read_recovery.pending_error(current))
            | native_diagnostic_recovery.details(
                native_diagnostic_recovery.diagnostic_error(current)
            ),
        )
    if code:
        details = {"operation_id": operation_id, "receipt": receipt, "dispatch_state": "dispatched"}
        details.update(
            native_diagnostic_recovery.details(native_diagnostic_recovery.diagnostic_error(current))
        )
        if p.op == "workflow.run":
            details["workflow"] = current["driver_workflow"]
        raise Error(code, "observed workflow effects are only partially persisted", details)
    return output | {"receipt": receipt}


def make_receipt(run, p, output=None, error=None):
    from . import engine

    if p.op == "workflow.run":
        from .workflow_tasks import aggregate_receipt

        return timing.stamp(
            native_diagnostic_recovery.annotate_receipt(
                native_read_recovery.annotate_receipt(
                    aggregate_receipt(run, p, output, error),
                    native_read_recovery.pending_error(run)
                    or native_read_recovery.pending_error(error),
                ),
                native_diagnostic_recovery.diagnostic_error(run)
                or native_diagnostic_recovery.diagnostic_error(error),
            )
        )
    plan = run["driver_plan"]
    old = output or {}
    v = old.get("verification") or {
        "status": "incomplete",
        "checks": [],
        "not_checked": ["requested_postconditions"],
    }
    if run.get("driver_effect_observed") is False and (
        p.op == "assembly.redefine-constraints"
        or (p.op == "model.close" and v.get("status") == "passed")
        or (p.op in _BOUND_CONSTRUCTION_OPS and v.get("status") == "passed")
    ):
        v = v | {
            "status": "incomplete",
            "not_checked": list(
                dict.fromkeys([*v.get("not_checked", []), "postconditions_read_back_independently"])
            ),
        }
    state = run["status"]
    known_unchanged = state in ("failed_before_write", "failed_unchanged")
    unknown = state in ("running", "unknown")
    close_refusal = run.get("native_close_read_refusal")
    close_unchanged = bool(
        p.op == "model.close"
        and isinstance(close_refusal, dict)
        and close_refusal.get("stage") == "model_close_stage"
        and close_refusal.get("mutation_started") is False
        and close_refusal.get("observation_bound") is True
        and close_refusal.get("state_after") == "observed_unchanged"
        and run.get("driver_effect_observed") is True
        and engine._complete_close_observation(run.get("driver_effect_readback"))
        and digest(run["driver_effect_readback"]) == digest(p.before)
    )
    if close_refusal and not close_unchanged:
        known_unchanged = False
    observed = old.get("result")
    mixed = p.op in ("model.save", "workflow.run", "part.create", "assembly.create") or run[
        "command"
    ] in ("drawing view remove", "family-table apply", "family-table remove-instance")
    snap = (
        snapshot(
            observed,
            source="disk"
            if p.op in ("model.export", "service.install")
            else "mixed"
            if mixed
            else "live",
            source_details={
                "live": "domain verification getters",
                "disk": "actual saved file bytes"
                if p.op in ("model.save", "part.create", "assembly.create")
                else "retained leaf receipts and version/output hashes",
            }
            if mixed
            else None,
        )
        if observed is not None
        else None
    )
    checks = [
        {
            "id": c["check"],
            "status": "passed"
            if c.get("passed") is True
            else "failed"
            if c.get("passed") is False
            else "incomplete",
            "required": True,
            **(
                {"reason": c.get("reason", "required independent evidence unavailable")}
                if c.get("passed") is None
                else {}
            ),
            "evidence_ref": f"operation:{run['operation_id']}:domain-check:{i}",
            "extensions": {"creo": c},
        }
        for i, c in enumerate(v.get("checks") or [])
    ]
    verified = v.get("status", "incomplete")
    if not checks or snap is None:
        verified = "incomplete"
    verification = {
        "status": verified,
        "scope": "declared command postconditions; wider engineering/consumer checks are separate",
        "snapshot_id": snap["id"] if snap else None,
        "coverage": "complete" if verified == "passed" else "partial" if checks else "none",
        "checks": checks,
        "not_checked": [
            {
                "id": str(k),
                "required": str(k)
                in ("postconditions_read_back_independently", "requested_postconditions"),
                "reason": {
                    "postconditions_read_back_independently": (
                        "required postconditions could not be read back; see native observations"
                    ),
                    "requested_postconditions": (
                        "required postcondition evidence is unavailable in this receipt"
                    ),
                }.get(str(k), "outside this command's declared verification scope"),
            }
            for k in v.get("not_checked", [])
        ],
        "evidence_refs": [c["evidence_ref"] for c in checks],
        "extensions": {"creo": v},
    }
    if verified == "incomplete":
        verification["reason"] = "requested independent postconditions could not all be established"
    effects = plan["effects"]
    artifact_only = effects == ["artifact"]
    persistence = (
        "unknown"
        if unknown and "persist" in effects
        else "unchanged"
        if known_unchanged
        else "saved"
        if "persist" in effects and state == "completed"
        else "unknown"
        if "persist" in effects
        else "not_applicable"
        if artifact_only or effects == ["session"]
        else "unsaved"
    )
    artifacts = []
    if observed and isinstance(observed, dict):
        file = observed.get("artifact")
        if file:
            artifacts.append(
                {
                    "id": "saved-model",
                    "path": file["path"],
                    "sha256": file["sha256"],
                    "source_snapshot_id": plan["base_snapshot"]["id"],
                }
            )
        elif observed.get("file") and observed.get("sha256"):
            artifacts.append(
                {
                    "id": "export",
                    "path": observed["file"],
                    "sha256": observed["sha256"],
                    "source_snapshot_id": plan["base_snapshot"]["id"],
                }
            )
    artifacts_after = getattr(p, "artifacts_after", None)
    if artifacts_after is not None and state != "failed_before_write":
        try:
            known_files = artifacts_after()
        except (Error, OSError):
            unknown = True
            verification["status"] = "incomplete"
            known_files = []
        for file in known_files:
            if not any(a["path"] == file["path"] for a in artifacts):
                artifacts.append(
                    {
                        "id": "observed-artifact-" + str(len(artifacts)),
                        "path": file["path"],
                        "sha256": file["sha256"],
                        "source_snapshot_id": plan["base_snapshot"]["id"],
                    }
                )
    if p.op == "model.save" and not unknown and not known_unchanged:
        new_version = next(
            (c for c in v.get("checks", []) if c["check"] == "one_new_version_on_disk"), None
        )
        old_versions = next(
            (c for c in v.get("checks", []) if c["check"] == "older_versions_untouched"), None
        )
        if new_version and new_version.get("files") == []:
            persistence = "unchanged"
        elif (
            old_versions
            and old_versions.get("passed") is False
            or new_version
            and len(new_version.get("files", [])) > 1
        ):
            persistence = "partial"
        elif artifacts:
            persistence = "saved"
    if p.op in ("family.set", "family.remove") and not known_unchanged:
        before = (
            plan["base_snapshot"]
            .get("extensions", {})
            .get("creo", {})
            .get("observation", {})
            .get("family_before")
        )
        after = run.get("driver_effect_readback") or (
            (observed or {}).get("readback") if isinstance(observed, dict) else None
        )
        if (
            isinstance(before, dict)
            and isinstance(after, dict)
            and before.get("files") != after.get("files")
        ):
            persistence = "partial"
    if p.op in ("part.create", "assembly.create") and not unknown and not known_unchanged:
        saved_state = next(
            (c for c in v.get("checks", []) if c["check"] == "created_model_saved_state_readable"),
            None,
        )
        first_version = next(
            (c for c in v.get("checks", []) if c["check"] == "first_version_on_disk"), None
        )
        stable = next(
            (
                c
                for c in v.get("checks", [])
                if c["check"] == "first_version_stable_during_readback"
            ),
            None,
        )
        if not stable or stable.get("passed") is not True:
            persistence = "unknown"
            artifacts = []
        elif saved_state and saved_state.get("observed_modified") is True:
            persistence = "unsaved"
        elif (
            saved_state
            and saved_state["passed"]
            and saved_state.get("observed_modified") is False
            and first_version
            and first_version["passed"]
            and artifacts
        ):
            persistence = "saved"
        elif first_version and len(first_version.get("files", [])) > 1:
            persistence = "partial"
        else:
            persistence = "unknown"
    receipt = {
        "operation_id": run["operation_id"],
        "capability_id": plan["capability_id"],
        "plan_id": plan["plan_id"],
        "target": plan["target"],
        "authorization_scope_id": plan["authorization_scope_id"],
        "effects": effects,
        "snapshot_before": plan["base_snapshot"],
        "snapshot_after": snap,
        "outcome": {
            "execution": "completed"
            if run.get("service_reported_done") is True
            or (error and error.details.get("service_reported_done") is True)
            or bool(run.get("native_write_returned"))
            else "unknown"
            if unknown
            else "failed"
            if error and not error.details.get("service_reported_done")
            else "completed",
            "change": "unknown"
            if unknown and not artifact_only
            else "not_applied"
            if known_unchanged or artifact_only or effects == ["persist"]
            else "partial"
            if state == "partial"
            else "applied",
            "persistence": persistence,
            "delivery": "not_applicable",
            "verification": verification,
        },
        "failed_stage": None
        if unknown
        else "persist"
        if error and "persist" in effects
        else "verify"
        if verified != "passed"
        else "apply"
        if error
        else None,
        "changed_items": [],
        "artifacts": artifacts,
        "deliveries": [],
        "recovery": {
            "action": "inspect" if error else "none",
            "reason": "independent inspection required before further writes"
            if error
            else "declared checks completed",
            "supported": True,
        },
        "extensions": {
            "creo": {
                "legacy_status": state,
                "artifact_state": "unknown"
                if unknown and artifact_only
                else "created"
                if artifacts and artifact_only
                else "not_created"
                if known_unchanged and artifact_only
                else "not_applicable",
                "domain_result": observed,
            }
        },
        "_untrusted": ["extensions.creo", "snapshot_before", "snapshot_after"],
    }
    execution_budget = plan.get("extensions", {}).get("creo", {}).get("execution_budget")
    if execution_budget is not None:
        receipt["extensions"]["creo"]["execution_budget"] = deepcopy(execution_budget)
    if p.op == "model.close" and close_refusal and v.get("status") == "incomplete":
        # Verification incompleteness says nothing by itself about session
        # mutation. Only a returned no-mutation refusal plus the same complete,
        # guarded observation can establish not_applied; all other such effects
        # remain unknown, including a dirty-only or unbound failure observation.
        receipt["outcome"]["change"] = "not_applied" if close_unchanged else "unknown"
        if close_refusal:
            receipt["extensions"]["creo"]["native_close_read_refusal"] = deepcopy(close_refusal)
        if run.get("driver_effect_observed") is True:
            receipt["extensions"]["creo"]["effects_readback"] = {
                "source": run.get("driver_effect_readback_source"),
                "before": p.before,
                "after": run["driver_effect_readback"],
            }
    if p.op == "assembly.redefine-constraints":
        from . import assembly_constraints

        actual = run.get("driver_effect_readback")
        if run.get("driver_effect_observed") is True and isinstance(actual, dict):
            receipt["outcome"]["persistence"] = assembly_constraints.persistence_state(actual)
        elif state != "failed_before_write":
            receipt["outcome"]["persistence"] = "unknown"
    if p.op == "assembly.explode":
        actual = run.get("driver_effect_readback")
        modified = (
            actual.get("physical", {}).get("modified")
            if run.get("driver_effect_observed") is True and isinstance(actual, dict)
            else None
        )
        if type(modified) is bool:
            receipt["outcome"]["persistence"] = "unsaved" if modified else "unchanged"
        elif state != "failed_before_write":
            receipt["outcome"]["persistence"] = "unknown"
    if p.op in _BOUND_CONSTRUCTION_OPS and run.get("driver_effect_observed") is not True:
        if state != "failed_before_write":
            receipt["outcome"]["persistence"] = "unknown"
        if run.get("driver_effect_readback_error"):
            receipt["extensions"]["creo"]["effects_readback_error"] = deepcopy(
                run["driver_effect_readback_error"]
            )
    if "change" in effects and not unknown and not known_unchanged:
        if run.get("driver_effect_observed") is True:
            actual = run["driver_effect_readback"]
            receipt["outcome"]["change"] = (
                "not_applied"
                if (
                    assembly_constraints.geometry_observation(actual)
                    == assembly_constraints.geometry_observation(p.before)
                    if p.op == "assembly.redefine-constraints"
                    else digest(actual) == digest(p.before)
                )
                else "partial"
                if state == "partial"
                else "applied"
            )
            receipt["extensions"]["creo"]["effects_readback"] = {
                "source": run.get(
                    "driver_effect_readback_source", "independent plan.observe getter"
                ),
                "before": p.before,
                "after": actual,
            }
            if receipt["outcome"]["change"] != "not_applied":
                receipt["changed_items"] = [
                    {
                        "id": p.target,
                        "change": "observed target state changed",
                        "evidence_ref": f"operation:{run['operation_id']}:effects_readback",
                    }
                ]
            elif (
                isinstance(p.before, dict)
                and p.before.get("modified") is False
                and p.before.get("origin")
            ):
                receipt["outcome"]["persistence"] = "unchanged"
        else:
            receipt["outcome"]["change"] = "unknown"
            if run.get("driver_effect_readback_error"):
                receipt["extensions"]["creo"]["effects_readback_error"] = deepcopy(
                    run["driver_effect_readback_error"]
                )
                receipt["failed_stage"] = "verify"
    if p.op in _BOUND_CONSTRUCTION_OPS and state != "failed_before_write":
        actual = (
            run.get("driver_effect_readback") if run.get("driver_effect_observed") is True else None
        )
        model = actual.get("model") if isinstance(actual, dict) else None
        modified = model.get("modified") if isinstance(model, dict) else None
        old_model = p.before.get("model") if isinstance(p.before, dict) else None
        if modified is True:
            receipt["outcome"]["persistence"] = "unsaved"
        elif (
            modified is False
            and receipt["outcome"]["change"] == "not_applied"
            and isinstance(old_model, dict)
            and old_model.get("modified") is False
        ):
            receipt["outcome"]["persistence"] = "unchanged"
        else:
            receipt["outcome"]["persistence"] = "unknown"
    if p.op in (
        "feature.hole",
        "feature.round",
        "feature.shell",
        "feature.draft",
        "feature.rib",
        "dimension.tolerance",
        "model.set-tolerance-standard",
        "material.assign",
        "model.set-common-name",
    ):
        actual_model = (run.get("driver_effect_readback") or {}).get("model")
        if known_unchanged:
            actual_model = (getattr(p, "before", None) or {}).get("model")
        modified = (actual_model or {}).get("modified")
        receipt["outcome"]["persistence"] = (
            "unknown"
            if unknown or type(modified) is not bool
            else "unsaved"
            if modified
            or (
                p.op == "model.set-common-name"
                and not known_unchanged
                and actual_model
                and actual_model.get("common_name")
                != ((getattr(p, "before", None) or {}).get("model") or {}).get("common_name")
            )
            else "unchanged"
        )
    if p.op in ("feature.shell", "feature.draft", "feature.rib"):
        before = getattr(p, "before", None)
        after = run.get("driver_effect_readback")
        if (
            isinstance(before, dict)
            and isinstance(after, dict)
            and before.get("files") != after.get("files")
        ):
            receipt["outcome"]["persistence"] = "partial"
    if p.op == "model.discard":
        before = getattr(p, "before", None)
        after = before if known_unchanged else run.get("driver_effect_readback")
        receipt["outcome"]["persistence"] = (
            "unknown"
            if unknown or not isinstance(after, dict) or not isinstance(before, dict)
            else "partial"
            if after.get("files") != before.get("files")
            else "unsaved"
            if (after.get("model") or {}).get("modified") is True
            else "unknown"
            if after.get("model") is not None and type(after["model"].get("modified")) is not bool
            else "unchanged"
        )
    if (
        p.op
        in (
            "model.set-common-name",
            "model.discard",
            "feature.shell",
            "feature.draft",
            "feature.rib",
        )
        and not unknown
        and error
        and receipt["outcome"]["change"] == "applied"
        and verified != "passed"
    ):
        receipt["outcome"]["change"] = "partial"
    if p.op == "model.export" and (run.get("driver_export") or unknown):
        from . import export_record

        recovery = (
            export_record.retained(run)
            if getattr(p, "retained_only", False)
            else export_record.inspect(run)
        )
        receipt["extensions"]["creo"]["export_recovery"] = recovery
        for file in recovery["artifacts"]:
            if not any(item["path"] == file["path"] for item in artifacts):
                artifacts.append(
                    {
                        "id": "retained-export-" + str(len(artifacts)),
                        "path": file["path"],
                        "sha256": file["sha256"],
                        "source_snapshot_id": plan["base_snapshot"]["id"],
                    }
                )
        receipt["extensions"]["creo"]["artifact_state"] = (
            "observed_on_disk"
            if artifacts
            else "unknown"
            if unknown or recovery["state"] == "evidence_incomplete"
            else "not_created"
        )
    if p.op.startswith(("display.", "appearance.")):
        actual = (
            getattr(p, "before", None) if known_unchanged else run.get("driver_effect_readback")
        )
        models = actual.get("models") if isinstance(actual, dict) else None
        flags = [model.get("modified") for model in models.values()] if models else []
        receipt["outcome"]["persistence"] = (
            "unknown"
            if unknown or not flags or any(type(flag) is not bool for flag in flags)
            else "unsaved"
            if any(flags)
            else "unchanged"
        )
        persistence_key = (
            "display_persistence" if p.op.startswith("display.") else "appearance_persistence"
        )
        receipt["extensions"]["creo"][persistence_key] = {
            "basis": "independent modified flags from the same complete effect observation",
            "model_modified": (
                {name: model.get("modified") for name, model in models.items()} if models else None
            ),
            "saved_presentation_persistence_verified": False,
        }
        if p.op.startswith("appearance."):
            from .appearance import reference_binding

            reference_request = getattr(p, "request", None)
            if not isinstance(reference_request, dict):
                reference_request = None

            def observed_reference(state):
                source_models = state.get("models") if isinstance(state, dict) else None
                source_colors = state.get("colors") if isinstance(state, dict) else None
                if (
                    not isinstance(source_models, dict)
                    or not isinstance(source_colors, dict)
                    or not isinstance(source_models.get(p.target), dict)
                    or not isinstance(source_colors.get(p.target), dict)
                ):
                    return {"observation_status": "not_observed"}
                try:
                    return reference_binding(source_colors[p.target], source_models[p.target])
                except (Error, KeyError, TypeError) as reference_error:
                    return {
                        "observation_status": "incomplete",
                        "error_code": getattr(reference_error, "code", "E_VERIFY_INCOMPLETE"),
                    }

            receipt["extensions"]["creo"]["appearance_reference"] = {
                "action": (
                    reference_request["reference_transition"]
                    if reference_request is not None
                    and reference_request.get("reference_transition")
                    in ("create_initial_binding", "restore_native_default")
                    else reference_request.get("reference_action", "preserve")
                    if reference_request is not None
                    else None
                ),
                "requested_reference_action": (
                    reference_request.get("reference_action", "preserve")
                    if reference_request is not None
                    else None
                ),
                "reference_transition": (
                    reference_request.get("reference_transition")
                    if reference_request is not None
                    else None
                ),
                "reference_replacement_authorized": (
                    reference_request.get("reference_replacement_authorized", False)
                    if reference_request is not None
                    else None
                ),
                "target": p.target,
                "scope": "source_part",
                "before": observed_reference(getattr(p, "before", None)),
                "after": observed_reference(actual),
                "affected_occurrences": (
                    actual.get("affected_occurrences") if isinstance(actual, dict) else None
                ),
                "basis": "frozen plan and the same complete independent effect observation",
                "native_id_prediction_used": False,
                "saved_reopen_binding_verified": False,
            }
    if p.op == "model.render":
        from . import render_record
        from .presentation import equivalent

        actual = (run.get("driver_effect_readback") or {}).get("presentation")
        actual_model = (run.get("driver_effect_readback") or {}).get("physical")
        retained = run.get("driver_render") or {}
        binding = getattr(p, "binding", None) or retained.get("before") or {}
        prior = binding.get("presentation")
        if known_unchanged:
            actual = prior
            actual_model = binding.get("model")
        uncertain = (
            unknown
            or prior is None
            or actual is None
            or actual_model is None
            or actual.get("complete") is not True
        )
        receipt["outcome"]["change"] = (
            "unknown"
            if uncertain
            else "not_applied"
            if equivalent(prior, actual) and equivalent(binding.get("model"), actual_model)
            else "partial"
        )
        source_parts = actual.get("native_part_appearances") if isinstance(actual, dict) else None
        prior_parts = prior.get("native_part_appearances") if isinstance(prior, dict) else None
        owner_modified = actual.get("modified") if isinstance(actual, dict) else None
        source_modified = (
            {
                name: value.get("modified") if isinstance(value, dict) else None
                for name, value in source_parts.items()
            }
            if isinstance(source_parts, dict)
            else None
        )
        complete_modified = (
            not uncertain
            and type(owner_modified) is bool
            and isinstance(source_parts, dict)
            and isinstance(prior_parts, dict)
            and source_parts.keys() == prior_parts.keys()
            and all(
                isinstance(value, dict)
                and value.get("complete") is True
                and value.get("model") == name
                and type(value.get("modified")) is bool
                for name, value in source_parts.items()
            )
            and (
                p.target not in source_parts or source_parts[p.target]["modified"] == owner_modified
            )
        )
        receipt["outcome"]["persistence"] = (
            "unknown"
            if not complete_modified
            else "unsaved"
            if owner_modified or any(source_modified.values())
            else "unchanged"
        )
        receipt["extensions"]["creo"]["render_persistence"] = {
            "basis": "owner and complete source-part modified flags from the same "
            "presentation observation",
            "owner_modified": owner_modified,
            "source_modified": source_modified,
            "saved_display_persistence_verified": False,
        }
        receipt["extensions"]["creo"]["artifact_state"] = (
            "observed_on_disk" if artifacts else "unknown" if unknown else "not_created"
        )
        receipt["extensions"]["creo"]["presentation_after"] = actual
        if retained or unknown:
            recovery = render_record.inspect(run)
            receipt["extensions"]["creo"]["render_recovery"] = recovery
            for file in recovery["artifacts"]:
                if not any(a["path"] == file["path"] for a in artifacts):
                    artifacts.append(
                        {
                            "id": "retained-render-" + str(len(artifacts)),
                            "path": file["path"],
                            "sha256": file["sha256"],
                            "source_snapshot_id": plan["base_snapshot"]["id"],
                        }
                    )
            receipt["extensions"]["creo"]["artifact_state"] = (
                "unknown"
                if recovery["state"] == "evidence_incomplete"
                else "observed_on_disk"
                if artifacts
                else "unknown"
                if unknown
                else "not_created"
            )
    if p.op == "service.install":
        from . import service_installation

        inspection = {
            "state": "evidence_incomplete",
            "can_register": [],
            "accepted": False,
            "creo_load_verified": False,
            "reason": "retained record only; use operation query for a current "
            "authorized file observation",
        }
        if not getattr(p, "retained_only", False):
            try:
                inspection = service_installation.inspect(run)
            except (Error, OSError) as exc:
                # A revoked read grant cannot turn an earlier copy into zero dispatch.
                # Public query still refuses; the receipt retains the known effects
                # with incomplete current evidence, without reading past the gate.
                inspection.update(
                    reason="current installation observation is unavailable; "
                    "retain prior dispatch facts and inspect after authorization is restored",
                    observation_error=exc.code if isinstance(exc, Error) else "E_IO",
                )
        receipt["extensions"]["creo"]["installation"] = inspection
        receipt["outcome"]["persistence"] = (
            "unknown"
            if unknown
            else "unchanged"
            if known_unchanged
            else "unchanged"
            if inspection["state"] == "preexisting_unchanged"
            else "saved"
            if state == "completed" and inspection["state"] == "files_complete"
            else "partial"
            if state == "partial" and inspection["state"] in ("partial_files", "files_complete")
            else "unknown"
        )
    pending = native_read_recovery.pending_error(run) or native_read_recovery.pending_error(error)
    if pending and "change" in effects and run.get("driver_effect_observed") is not True:
        receipt["outcome"]["persistence"] = "unknown"
    native_read_recovery.annotate_receipt(receipt, pending)
    diagnostic = native_diagnostic_recovery.diagnostic_error(
        run
    ) or native_diagnostic_recovery.diagnostic_error(error)
    if diagnostic:
        # A setter-completion fact does not supply independent effects or save evidence.
        receipt["outcome"]["change"] = (
            "unknown" if "change" in effects else receipt["outcome"]["change"]
        )
        receipt["outcome"]["persistence"] = "unknown"
        receipt["outcome"]["verification"]["status"] = "incomplete"
        receipt["outcome"]["verification"]["reason"] = (
            "native diagnostics stopped required read-back; "
            "retained earlier checks do not establish current health"
        )
        receipt["outcome"]["verification"]["coverage"] = (
            "partial" if receipt["outcome"]["verification"]["checks"] else "none"
        )
        if run.get("native_write_returned"):
            receipt["extensions"]["creo"]["native_write_returned"] = deepcopy(
                run["native_write_returned"]
            )
        native_diagnostic_recovery.annotate_receipt(receipt, diagnostic)
    if not getattr(p, "retained_only", False):
        # A reconstructed unknown receipt describes the original call; this lookup's
        # timing must never become part of its state or resolution confirmation binding.
        timing.stamp(receipt)
    driver_schema.validate("receipt", receipt)
    return receipt


def error_for(receipt, fallback):
    if native_diagnostic_recovery.diagnostic_error(receipt) or fallback == "E_NATIVE_DIAGNOSTIC":
        return "E_NATIVE_DIAGNOSTIC"
    o = receipt["outcome"]
    if (
        any(
            o[k] in ("unknown", "running")
            for k in ("execution", "change", "persistence", "delivery")
        )
        or receipt["extensions"]["creo"].get("artifact_state") == "unknown"
    ):
        return "E_OUTCOME_UNKNOWN"
    if (
        any(o[k] == "partial" for k in ("change", "persistence", "delivery"))
        or o["execution"] in ("failed", "interrupted", "not_started")
        and (o["change"] == "applied" or o["persistence"] == "saved" or receipt["artifacts"])
    ):
        return "E_PARTIAL"
    return fallback


def inspection_status(run, kind):
    """Validate retained evidence bytes locally; return a bounded summary, never raw paths."""
    recorded = run.get("driver_" + kind + "_resolution")
    if not recorded:
        return None
    out = {
        key: recorded.get(key)
        for key in ("evidence_id", "sha256", "accepted", "registered_outcome")
    }
    out["evidence_status"] = "unavailable"
    out["evidence_integrity"] = "unavailable"
    out["current_requirements_satisfied"] = False
    try:
        evidence = operations.load_query(recorded.get("evidence_id", ""))
        proof = evidence.get("observation", {}).get(kind + "_verification")
        if (
            not isinstance(proof, dict)
            or evidence.get("operation_id") != run["operation_id"]
            or recorded.get("sha256") != recorded.get("evidence_id", "").split("-")[-1]
            or proof.get("accepted") != recorded.get("accepted")
            or recorded.get("registered_outcome") not in proof.get("can_register", [])
        ):
            raise Error("E_INTEGRITY", "retained inspection does not match its registration")
        checks = proof.get("checks")
        if not isinstance(checks, list) or not checks:
            raise Error("E_VERIFY_INCOMPLETE", "retained inspection check summary missing")
        out.update(
            evidence_status="verified",
            evidence_integrity="valid",
            summary={
                "checks": len(checks),
                "passed": sum(c.get("passed") is True for c in checks),
                "coverage": str(proof.get("coverage", "retained command inspection"))[:1000],
            },
            source={
                "kind": "retained_independent_observation",
                "observed_at": evidence.get("at"),
                "instance_id": run["driver_plan"]["target"].get("instance_id"),
                "baseline_snapshot_id": run["driver_plan"]["base_snapshot"]["id"],
            },
        )
        if kind == "view_removal":
            out["summary"]["draft_entity_details_retained"] = isinstance(
                proof.get("current", {}).get("resources", {}).get("entities"), list
            )
        if kind in (
            "view_removal",
            "model_management",
            "family_table",
            "prismatic",
            "prismatic_draft",
            "prismatic_rib",
            "simple_note",
            "assembly_constraints",
        ):
            from . import (
                assembly_constraints,
                drawing_note_recovery,
                drawing_views,
                family_runtime,
                model_management,
                prismatic,
                prismatic_draft,
                prismatic_rib,
            )

            try:
                module = {
                    "view_removal": drawing_views,
                    "model_management": model_management,
                    "family_table": family_runtime,
                    "prismatic": prismatic,
                    "prismatic_draft": prismatic_draft,
                    "prismatic_rib": prismatic_rib,
                    "simple_note": drawing_note_recovery,
                    "assembly_constraints": assembly_constraints,
                }[kind]
                module.retained_evidence_sufficient(run, proof)
            except (Error, KeyError, TypeError, ValueError) as exc:
                out.update(
                    evidence_status="insufficient",
                    code="E_VERIFY_INCOMPLETE",
                    limitation=str(exc)[:1000],
                    next_action=(
                        "historical receipt and registration are preserved; valid hashes do not "
                        "prove complete observations. Query only within current scope; if the "
                        "original baseline cannot establish required identities, keep this "
                        "operation unresolved and do not replay the write"
                    ),
                )
                return out
        out["current_requirements_satisfied"] = True
    except (Error, OSError, TypeError, ValueError, KeyError) as exc:
        out.update(
            evidence_status="invalid"
            if isinstance(exc, Error) and exc.code == "E_INTEGRITY"
            else "unavailable",
            evidence_integrity="invalid"
            if isinstance(exc, Error) and exc.code == "E_INTEGRITY"
            else "unavailable",
            code=exc.code if isinstance(exc, Error) else "E_VERIFY_INCOMPLETE",
            next_action="retain the registration and original receipt; restore exact evidence "
            "bytes from a verified backup; do not replay the native operation",
        )
    return out


def resolution_evidence_trusted(run):
    kind = {
        "drawing view remove": "view_removal",
        "model set-common-name": "model_management",
        "model discard": "model_management",
        "family-table apply": "family_table",
        "family-table remove-instance": "family_table",
        "feature shell": "prismatic",
        "feature draft": "prismatic_draft",
        "feature rib": "prismatic_rib",
        "drawing note add": "simple_note",
        "assembly component redefine": "assembly_constraints",
    }.get(run.get("command"))
    if kind and run.get("driver_resolution"):
        evidence = inspection_status(run, kind)
        return (
            evidence is not None
            and evidence["evidence_status"] == "verified"
            and evidence.get("current_requirements_satisfied") is True
        )
    return True


def status(run):
    plan = run["driver_plan"]
    if run["status"] == "running" and (
        run.get("driver_stage") == "finalizing" or process_owner.abandoned(run.get("driver_owner"))
    ):
        run = run | {"status": "unknown"}
    if (
        run["status"] in operations.UNRESOLVED
        and run["status"] != "running"
        and run.get("driver_receipt") is None
    ):
        binding = (
            plan.get("base_snapshot", {}).get("extensions", {}).get("creo", {}).get("observation")
        )
        run = run | {
            "driver_receipt": make_receipt(
                run | {"status": "unknown"},
                SimpleNamespace(
                    op=plan["changes"][0]["action"],
                    target=plan["target"]["object_id"],
                    before=None,
                    binding=binding if isinstance(binding, dict) else {},
                    retained_only=True,
                ),
            )
        }
        run["driver_receipt"]["recovery"] = {
            "action": "inspect",
            "supported": True,
            "reason": "retained evidence only; original completion remains unresolved",
        }
    result = {
        "operation_id": run["operation_id"],
        "capability_id": plan["capability_id"],
        "request_id": None,
        "plan_id": plan["plan_id"],
        "plan": plan,
        "target": plan["target"],
        "status": {
            "completed": "succeeded",
            "resolved_manual": "unknown",
            "verification_failed": "failed",
            "verification_incomplete": "failed",
            "failed_before_write": "failed",
            "failed_unchanged": "failed",
        }.get(run["status"], run["status"]),
        "stage": "apply" if run["status"] == "running" else None,
        "observed_at": operations.now(),
        "started_at": run.get("started_at"),
        "finished_at": run.get("finished_at"),
        "record": {
            "availability": "available",
            "retain_until": None,
            "survives_cli_exit": True,
            "survives_reconnect": True,
            "survives_instance_restart": True,
            "limitations": [
                "local state must be retained; original snapshots remain tied to the old instance"
            ],
        },
        "commands": {
            "lookup": {
                "argv": ["operation", "show", "--id", run["operation_id"]],
                "read_only": True,
            },
            "result": None,
            "cancel": None,
        },
        "blocked": None,
        "resolution": run.get("driver_resolution"),
        "stop_observed": run.get("status_before_resolution", run["status"])
        in (
            "completed",
            "partial",
            "failed_before_write",
            "failed_unchanged",
            "verification_failed",
            "verification_incomplete",
        ),
        "receipt": run.get("driver_receipt"),
    }
    attempts = operations.confirmation_attempts(run["operation_id"])
    if attempts:
        result.setdefault("extensions", {}).setdefault("creo", {})["confirmation_attempts"] = (
            attempts
        )
    pending = native_read_recovery.pending_error(run)
    if pending:
        result.setdefault("extensions", {}).setdefault("creo", {})["native_read_error"] = pending
    diagnostic = native_diagnostic_recovery.diagnostic_error(run)
    if diagnostic:
        result.setdefault("extensions", {}).setdefault("creo", {})["native_diagnostic_error"] = (
            diagnostic
        )
    if run.get("owned_exit_diagnostics") is not None:
        result.setdefault("extensions", {}).setdefault("creo", {})["owned_exit_diagnostics"] = (
            deepcopy(run["owned_exit_diagnostics"])
        )
    if run.get("driver_workflow"):
        result.setdefault("extensions", {}).setdefault("creo", {})["workflow"] = run[
            "driver_workflow"
        ]
    if run.get("workflow_parent_id"):
        result.setdefault("extensions", {}).setdefault("creo", {}).update(
            workflow_parent_id=run["workflow_parent_id"], workflow_step_id=run["workflow_step_id"]
        )
    for kind in (
        "machining",
        "installation",
        "construction",
        "view_removal",
        "model_management",
        "family_table",
        "prismatic",
        "prismatic_draft",
        "prismatic_rib",
        "simple_note",
        "assembly_constraints",
    ):
        if run.get("driver_" + kind + "_resolution"):
            result.setdefault("extensions", {}).setdefault("creo", {})[kind + "_inspection"] = (
                inspection_status(run, kind)
                if kind
                in (
                    "view_removal",
                    "model_management",
                    "family_table",
                    "prismatic",
                    "prismatic_draft",
                    "prismatic_rib",
                    "simple_note",
                    "assembly_constraints",
                )
                else run["driver_" + kind + "_resolution"]
            )
    driver_schema.validate("operation-status", result)
    return result


def resolve(opts):
    try:
        return _resolve(opts)
    except Error as exc:
        operations.retain_pending_inspection(operations.get(opts["id"]), exc, "operation resolve")
        raise


def _resolve(opts):
    """Record explicit inspection; never reapply or overwrite the original receipt."""
    with safety.lock():
        run = operations.get(opts["id"])
        if run["status"] == "running":
            if run.get("driver_stage") != "finalizing" and not process_owner.abandoned(
                run.get("driver_owner")
            ):
                raise Error(
                    "E_CONFLICT",
                    "live or unexpired owner cannot be resolved",
                    {"conflict": "lock_held"},
                )
            # The CLI vanished. Application-side completion remains unknown; never infer no effect.
            run["driver_receipt"] = status(run)["receipt"]
            run["status"] = "unknown"
        if run["status"] not in operations.UNRESOLVED or run.get("driver_resolution"):
            raise Error("E_CONFLICT", "operation does not require resolution")
        if (
            not opts.get("outcome")
            or not opts.get("evidence")
            or len(opts["evidence"].strip()) < 10
        ):
            raise Error(
                "E_VALIDATION", "resolution requires --outcome and substantive --evidence text"
            )
        plan = run["driver_plan"]
        grant = scope()
        grant.require(
            effects=plan["effects"],
            target=plan["target"],
            outputs=plan["outputs"],
            paths=run["driver_binding"]["driver_paths"],
        )
        inspection = None
        inspection_kind = "machining"
        local_install = run["command"] == "service install"
        policy = (
            {
                "permission": safety.permission(),
                "confirm_allowed": safety.permission() == "write",
                "native_opt_in_required": False,
            }
            if local_install
            else safety.policy()
        )
        if local_install:
            from . import service_installation

            inspection_kind = "installation"
            inspection = service_installation.inspect(run)
            if opts["outcome"] not in inspection["can_register"]:
                raise Error(
                    "E_VERIFY_FAILED" if inspection["can_register"] else "E_VERIFY_INCOMPLETE",
                    "independent installation files do not support this registration",
                    {"operation_id": run["operation_id"], "inspection": inspection},
                )
        if run["command"] == "drawing note add":
            from . import drawing_note_recovery
            from .transport import Client

            inspection_kind = "simple_note"
            with Client(opts.get("timeout", 30)) as client:
                inspection = drawing_note_recovery.recovery(client, run)
            if opts["outcome"] not in inspection["can_register"]:
                raise Error(
                    "E_VERIFY_INCOMPLETE",
                    "independent note identity and protected-state evidence "
                    "does not support registration",
                    {"operation_id": run["operation_id"], "inspection": inspection},
                )
        if run["command"] == "assembly component redefine":
            from . import assembly_constraints
            from .transport import Client

            inspection_kind = "assembly_constraints"
            with Client(opts.get("timeout", 30)) as client:
                inspection = assembly_constraints.recovery(client, run)
            if opts["outcome"] not in inspection["can_register"]:
                raise Error(
                    "E_VERIFY_FAILED" if inspection["can_register"] else "E_VERIFY_INCOMPLETE",
                    "independent occurrence constraints, solved poses and protected-state "
                    "evidence do not support registration",
                    {"operation_id": run["operation_id"], "inspection": inspection},
                )
        if run["command"] in ("feature hole", "feature round"):
            from . import machining
            from .transport import Client

            with Client(opts.get("timeout", 30)) as client:
                inspection = machining.recovery(client, run)
            if opts["outcome"] not in inspection["can_register"]:
                raise Error(
                    "E_VERIFY_FAILED" if inspection["can_register"] else "E_VERIFY_INCOMPLETE",
                    "independent current-solid inspection does not support this resolution; "
                    "original outcome remains unresolved",
                    {
                        "operation_id": run["operation_id"],
                        "requested_outcome": opts["outcome"],
                        "inspection": inspection,
                    },
                )
        if run["command"] in ("feature revolve", "feature datum-plane", "feature datum-axis"):
            from . import revolved
            from .transport import Client

            inspection_kind = "construction"
            with Client(opts.get("timeout", 30)) as client:
                inspection = revolved.recovery(client, run)
            if opts["outcome"] not in inspection["can_register"]:
                raise Error(
                    "E_VERIFY_FAILED" if inspection["can_register"] else "E_VERIFY_INCOMPLETE",
                    "independent construction inspection does not support this registration",
                    {"operation_id": run["operation_id"], "inspection": inspection},
                )
        if run["command"] == "drawing view remove":
            from . import drawing_views
            from .transport import Client

            inspection_kind = "view_removal"
            with Client(opts.get("timeout", 30)) as client:
                inspection = drawing_views.recovery(client, run)
            if opts["outcome"] not in inspection["can_register"]:
                raise Error(
                    "E_VERIFY_FAILED" if inspection["can_register"] else "E_VERIFY_INCOMPLETE",
                    ("independent view and source-model inspection does not support registration"),
                    {"operation_id": run["operation_id"], "inspection": inspection},
                )
        if run["command"] in ("model set-common-name", "model discard"):
            from . import model_management
            from .transport import Client

            inspection_kind = "model_management"
            with Client(opts.get("timeout", 30)) as client:
                inspection = model_management.recovery(client, run)
            if opts["outcome"] not in inspection["can_register"]:
                raise Error(
                    "E_VERIFY_FAILED" if inspection["can_register"] else "E_VERIFY_INCOMPLETE",
                    "independent model/window/file evidence does not support registration",
                    {"operation_id": run["operation_id"], "inspection": inspection},
                )
        if run["command"] in ("family-table apply", "family-table remove-instance"):
            from . import family_runtime
            from .transport import Client

            inspection_kind = "family_table"
            with Client(opts.get("timeout", 30)) as client:
                inspection = family_runtime.recovery(client, run)
            if opts["outcome"] not in inspection["can_register"]:
                raise Error(
                    "E_VERIFY_FAILED" if inspection["can_register"] else "E_VERIFY_INCOMPLETE",
                    "independent table/instance/protected-state evidence "
                    "does not support registration",
                    {"operation_id": run["operation_id"], "inspection": inspection},
                )
        if run["command"] in ("feature shell", "feature draft", "feature rib"):
            from . import prismatic, prismatic_draft, prismatic_rib
            from .transport import Client

            inspection_kind, domain = {
                "feature shell": ("prismatic", prismatic),
                "feature draft": ("prismatic_draft", prismatic_draft),
                "feature rib": ("prismatic_rib", prismatic_rib),
            }[run["command"]]
            with Client(opts.get("timeout", 30)) as client:
                inspection = domain.recovery(client, run)
            if opts["outcome"] not in inspection["can_register"]:
                raise Error(
                    "E_VERIFY_FAILED" if inspection["can_register"] else "E_VERIFY_INCOMPLETE",
                    "independent prismatic intent and current body "
                    "do not support this registration",
                    {"operation_id": run["operation_id"], "inspection": inspection},
                )
        bound = safety.scope(
            "operation resolve",
            run["operation_id"],
            {"outcome": opts["outcome"], "evidence": opts["evidence"]},
            digest(run),
        )
        bound["driver_scope_sha256"] = digest(grant.record)
        if local_install:
            bound["native_opt_in"] = False
        if inspection is not None:
            bound[inspection_kind + "_inspection_sha256"] = digest(inspection)
        if opts.get("dry_run"):
            token, expiry = safety.issue(bound)
            preview = {
                "plan_id": uuid.uuid4().hex,
                "operation_id": run["operation_id"],
                "capability_id": "operation-resolve",
                "target": plan["target"],
                "base_snapshot": snapshot(run, source="disk"),
                "authorization_scope_id": grant.scope_id,
                "effects": plan["effects"],
                "level": "plan",
                "changes": [
                    {
                        "action": "record_resolution",
                        "resource": run["operation_id"],
                        "summary": "record inspection; preserve target and original receipt",
                    }
                ],
                "outputs": [],
                "unknowns": [],
                "constraints": ["local record control with independent reads; no native mutation"],
                "trial_snapshot": None,
                "can_apply": policy["confirm_allowed"],
                "expires_at": expiry,
                "extensions": {
                    "creo": {
                        "policy": policy,
                        "outcome": opts["outcome"],
                        "original_operation": run["operation_id"],
                        **(
                            {inspection_kind + "_inspection": inspection}
                            if inspection is not None
                            else {}
                        ),
                    }
                },
            }
            driver_schema.validate("plan", preview)
            return {
                "preview": preview,
                "confirm_token": token,
                "expires_at": expiry,
            }
        if local_install:
            if safety.permission() != "write":
                raise Error(
                    "E_FORBIDDEN", "inspection registration needs explicit write permission"
                )
        else:
            safety.require_write()
        if opts.get("confirm"):
            safety.consume(opts.get("confirm"), bound)
        if inspection is not None:
            evidence = operations.save_query(run, {inspection_kind + "_verification": inspection})
            run["driver_" + inspection_kind + "_resolution"] = {
                "evidence_id": evidence["evidence_id"],
                "sha256": evidence["sha256"],
                "accepted": inspection["accepted"],
                "registered_outcome": opts["outcome"],
            }
        run["driver_resolution"] = {
            "outcome": opts["outcome"],
            "evidence": opts["evidence"],
            "resolved_at": operations.now(),
            "recorded_by": bound["account"],
        }
        run["status_before_resolution"] = run["status"]
        run["status"] = "resolved_manual"
        operations.update(run)
        return {"operation_status": status(run)}
