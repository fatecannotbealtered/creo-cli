"""Native source-part color; shared instances are explicitly authorized."""

from .. import appearance
from ..registry import MODEL, REQUEST, Command
from ..schemas import WRITTEN, B, S, array, shape, written

REFERENCE_POLICY = {
    "type": "string",
    "enum": ["preserve", "create_and_bind"],
    "description": "Requested existing-reference native wire policy; the effective binding "
    "change is reference_transition, including first creation under the original preserve policy.",
}
REFERENCE_BINDING = shape(
    {
        "source_context": shape(
            {"model": S, "origin": {"type": ["string", "null"]}}, ("model", "origin")
        ),
        "scope": {"const": "source_part"},
        "selection_model": {"type": ["string", "null"]},
        "selection_model_type": {"type": ["string", "null"]},
        "native_id": {"type": ["string", "null"]},
        "native_id_scope": S,
        "appearance": {"type": ["object", "null"]},
        "assignments": array(shape({})),
        "whole_source_binding_observed": B,
    },
    (
        "source_context",
        "scope",
        "native_id",
        "appearance",
        "assignments",
        "whole_source_binding_observed",
    ),
)
RESULT = shape(
    {
        "model": S,
        "scope": {"const": "source_part"},
        "appearance": {"type": ["object", "null"]},
        "affected_occurrences": array(shape({})),
        "modified": B,
        "reference_binding": REFERENCE_BINDING,
    },
    ("model", "scope", "appearance", "affected_occurrences"),
)
MUTATION_RESULT = shape(
    RESULT["properties"]
    | {
        "reference_action": REFERENCE_POLICY,
        "requested_reference_action": REFERENCE_POLICY,
        "reference_allocation_policy": {
            "type": ["string", "null"],
            "enum": ["random_candidate_native_readback_v1", None],
            "description": "New references use a fresh random candidate name; the actual native "
            "ID is observed after the setter and may differ from that candidate.",
        },
        "reference_transition": {
            "type": "string",
            "enum": list(appearance.REFERENCE_TRANSITIONS),
            "description": "Effective binding intent frozen in this Plan: initial creation, "
            "authorized replacement, preservation, or removal of this model override. "
            "Creation previews have pending_native_allocation and a null unpredicted ID; "
            "successful results contain the independently observed binding.",
        },
        "reference_before": REFERENCE_BINDING
        | {"description": "Observed frozen precondition binding."},
        "reference_after": REFERENCE_BINDING
        | {
            "description": "Actual binding from the same complete "
            "post-operation observation used for verification and the receipt; "
            "never a predicted ID."
        },
    },
    (
        *RESULT["required"],
        "reference_action",
        "requested_reference_action",
        "reference_allocation_policy",
        "reference_transition",
        "reference_before",
        "reference_after",
    ),
)
BASE = {
    "scope": "source_part",
    "source_file_authorized": True,
    "affected_occurrences": [{"assembly": "phone_demo.asm", "component_path": ["40"]}],
}
COMMANDS = [
    Command(
        "appearance show",
        "Read native whole source-part appearance and every current-session affected occurrence",
        appearance.query,
        RESULT,
        (MODEL,),
        untrusted=("appearance", "assignments", "affected_occurrences", "reference_binding"),
        example="--model midframe.prt",
        service_ops=("session.status", "model.show", "geometry.list", "appearance.get"),
    ),
    Command(
        "appearance set",
        "Set exact normalized RGB on an authorized source part; preserve physical material, "
        "geometry and display properties; existing color changes need authorized create_and_bind",
        appearance.set_color,
        written(MUTATION_RESULT),
        (MODEL, REQUEST),
        write=True,
        untrusted=WRITTEN,
        request=appearance.SET_SCHEMA,
        request_example=BASE
        | {
            "rgb": [0.2, 0.4, 0.6],
            "reference_action": "create_and_bind",
            "reference_replacement_authorized": True,
        },
        example="--model midframe.prt --request color.json",
        service_ops=(
            "session.status",
            "model.show",
            "geometry.list",
            "appearance.get",
            "appearance.set",
        ),
    ),
    Command(
        "appearance restore",
        "Restore recorded source display properties (create_and_bind allocates a new native ID), "
        "or native default null; exact shared-occurrence authorization required",
        appearance.restore,
        written(MUTATION_RESULT),
        (MODEL, REQUEST),
        write=True,
        untrusted=WRITTEN,
        request=appearance.RESTORE_SCHEMA,
        request_example=BASE | {"appearance": None},
        example="--model midframe.prt --request restore-color.json",
        service_ops=(
            "session.status",
            "model.show",
            "geometry.list",
            "appearance.get",
            "appearance.restore",
        ),
    ),
]
