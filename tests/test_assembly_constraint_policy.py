"""Independent policy counterexamples; these are not native qualification evidence."""

from copy import deepcopy
from pathlib import Path

import pytest

from creo_cli import assembly_constraints as policy
from creo_cli.core import Error, digest


def reference(model, item, path=()):
    return {
        "model": model,
        "item_id": item,
        "item_type": "ITEM_SURFACE",
        "component_path": list(path),
    }


def constraint(owner, member, *, axis=0, offset=0, source_path=()):
    return {
        "type": "align",
        "assembly_reference": reference(owner, 5 + axis, source_path),
        "component_reference": reference(member, 5 + axis),
        "assembly_side": "DATUM_SIDE_YELLOW",
        "component_side": "DATUM_SIDE_YELLOW",
        "offset": offset,
    }


def request():
    return {
        "selection": {
            "instance_id": "independent-generation-17",
            "owner": "clamp_jig.asm",
            "occurrence_id": "83",
            "state_revision": "a" * 64,
        },
        "units": "mm",
        "constraints": [
            constraint("clamp_jig.asm", "slider.prt", axis=axis, offset=12 if axis == 0 else 0)
            for axis in range(3)
        ],
        "affected_occurrences": ["126", "83"],
    }


def test_request_preserves_explicit_direction_offset_and_occurrence_identity():
    q = request()
    frozen = deepcopy(q)
    actual = policy.validate_request(q)
    assert actual == frozen
    assert q == frozen


@pytest.mark.parametrize(
    ("kind", "offset", "assembly_side", "component_side"),
    [
        ("align", -7.25, "DATUM_SIDE_RED", "DATUM_SIDE_YELLOW"),
        ("mate", 0, "DATUM_SIDE_YELLOW", "DATUM_SIDE_RED"),
        ("mate", 18.125, "DATUM_SIDE_RED", "DATUM_SIDE_RED"),
    ],
)
def test_request_does_not_normalize_explicit_side_or_signed_offset(
    kind, offset, assembly_side, component_side
):
    q = request()
    q["constraints"][0].update(
        type=kind,
        offset=offset,
        assembly_side=assembly_side,
        component_side=component_side,
    )
    actual = policy.validate_request(q)["constraints"][0]
    assert actual["type"] == kind
    assert actual["offset"] == offset
    assert actual["assembly_side"] == assembly_side
    assert actual["component_side"] == component_side


@pytest.mark.parametrize(
    "mutate",
    [
        lambda q: q.pop("selection"),
        lambda q: q["selection"].pop("state_revision"),
        lambda q: q["selection"].update(instance_id=""),
        lambda q: q["selection"].update(owner="foreign.prt"),
        lambda q: q["selection"].update(occurrence_id="slider"),
        lambda q: q.pop("units"),
        lambda q: q.update(units="unspecified"),
        lambda q: q["constraints"][0].pop("assembly_side"),
        lambda q: q["constraints"][0].pop("component_side"),
        lambda q: q["constraints"][0].pop("offset"),
        lambda q: q["constraints"][0].update(offset=float("nan")),
        lambda q: q["constraints"][0].update(offset=True),
        lambda q: q["constraints"][0].update(type="fix"),
        lambda q: q["constraints"][0].update(assembly_side="AUTOMATIC"),
        lambda q: q["constraints"][0].pop("assembly_reference"),
        lambda q: q["constraints"][0]["component_reference"].pop("item_id"),
        lambda q: q["constraints"][0]["component_reference"].update(component_path=[83]),
        lambda q: q["constraints"][0]["assembly_reference"].update(component_path=[72, 19]),
        lambda q: q["affected_occurrences"].append("83"),
        lambda q: q.update(unrecognized_override=True),
    ],
)
def test_malformed_or_implicit_request_is_rejected_without_mutation(mutate):
    q = request()
    mutate(q)
    before = deepcopy(q)
    with pytest.raises(Error):
        policy.validate_request(q)
    assert repr(q) == repr(before)


def transform(origin):
    return {
        "origin": list(origin),
        "x_axis": [1, 0, 0],
        "y_axis": [0, 1, 0],
        "z_axis": [0, 0, 1],
    }


def plane_reference(model, item, axis, path=(), origin=(0, 0, 0)):
    normal = [0, 0, 0]
    normal[axis] = 1
    return reference(model, item, path) | {
        "plane": {
            "kind": "datum_plane",
            "feature_id": item,
            "units": "mm",
            "origin": list(origin),
            "normal": normal,
            "source": "controlled local fixture of TransformedSurface.GetCoordSys",
        }
    }


def rigid_child(owner):
    return {
        "id": 49,
        "owner": owner,
        "model": "rail.prt",
        "status": "FEAT_ACTIVE",
        "placed": True,
        "packaged": False,
        "underconstrained": False,
        "frozen": False,
        "bulkitem": False,
        "substitute": False,
        "flexible": False,
        "embedded": False,
        "unplaced": False,
        "parents": [5, 6, 7],
        "children": [],
        "transform": transform([0, 0, 0]),
        "placement_metadata": {"supported": True},
        "constraints": [
            {
                "type": "def_placement",
                "native_type": "ASM_CONSTRAINT_DEF_PLACEMENT",
                "assembly_reference": None,
                "component_reference": None,
                "assembly_side": "DATUM_SIDE_NONE",
                "component_side": "DATUM_SIDE_NONE",
                "offset": None,
                "units": "mm",
                "attributes": {"raw_null_default": True, "force": None, "ignore": None},
                "user_data": None,
            }
        ],
    }


def bind_native_references(state):
    """Describe acquired raw selections separately from constructed catalog identities."""
    owner = state["model"]
    for ref in state["reference_catalog"]:
        ref.setdefault("classification", {"public_feature": True, "source": "Feature.GetIsVisible"})
        ref.setdefault("reference_usage", "editable")
        ref.update(
            path_root_model=owner,
            path_root_source="constructed_catalog_owner",
            path_leaf_model=ref["model"],
            path_leaf_source="constructed_catalog_model",
        )
    for row in state["components"]:
        for c in row["constraints"]:
            for role in ("assembly_reference", "component_reference"):
                ref = c.get(role)
                if ref is None:
                    continue
                for catalog_only in ("classification", "reference_usage", "auxiliary"):
                    ref.pop(catalog_only, None)
                local = role == "component_reference" and ref["component_path"] == []
                ref.update(
                    path_present=not local,
                    path_root_model=None if local else owner,
                    path_root_source="Selection.GetPath.returned_null"
                    if local
                    else "ComponentPath.GetRoot",
                    path_leaf_model=ref["model"] if ref["component_path"] else None,
                    path_leaf_source="Selection.GetPath.returned_null"
                    if local
                    else "ComponentPath.GetLeaf"
                    if ref["component_path"]
                    else "not_read_for_empty_path",
                    reference_owner_model=owner,
                    reference_owner_source="ComponentFeat.WFeature.GetSolid",
                )
    return state


def native_state(
    *,
    owner="clamp_jig.asm",
    ids=(22, 83, 126, 157),
    rigid=False,
    instance_id="independent-generation-17",
):
    """A root, two repeated members and a follower; IDs and owner are variable."""
    fixed, target, follower, unrelated = ids
    member = "carriage.asm" if rigid else "slider.prt"
    rows = []
    catalog = [plane_reference(owner, 5 + axis, axis) for axis in range(3)]
    catalog.append(plane_reference(owner, 19, 0, origin=(5, 0, 0)))
    for ident, model, origin in (
        (fixed, "datum_base.prt", [0, 0, 0]),
        (target, member, [0, 0, 0]),
        (follower, "travel_stop.prt", [3, 0, 0]),
        (unrelated, member, [60, 0, 0]),
    ):
        constraints = []
        for axis in range(3):
            own = plane_reference(model, 5 + axis, axis)
            catalog.append(plane_reference(model, 5 + axis, axis, [ident]))
            source_model, source_path = (member, [target]) if ident == follower else (owner, [])
            constraints.append(
                {
                    "type": "align",
                    "native_type": "ASM_CONSTRAINT_ALIGN_OFF",
                    "assembly_reference": plane_reference(
                        source_model, 5 + axis, axis, source_path
                    ),
                    "component_reference": own,
                    "assembly_side": "DATUM_SIDE_YELLOW",
                    "component_side": "DATUM_SIDE_YELLOW",
                    "offset": origin[axis],
                    "units": "mm",
                    "attributes": {"raw_null_default": True, "force": None, "ignore": None},
                    "user_data": None,
                }
            )
        rows.append(
            {
                "id": ident,
                "owner": owner,
                "component_path": [ident],
                "model": model,
                "model_type": "assembly" if model.endswith(".asm") else "part",
                "status": "FEAT_ACTIVE",
                "placed": True,
                "packaged": False,
                "underconstrained": False,
                "frozen": False,
                "bulkitem": False,
                "substitute": False,
                "flexible": False,
                "embedded": False,
                "unplaced": False,
                "parents": [target] if ident == follower else [5, 6, 7],
                "children": [follower] if ident == target else [],
                "constraints": constraints,
                "component_path_transform": transform(origin),
                "placement_metadata": {"supported": True},
            }
        )
        if model.endswith(".asm"):
            rows[-1]["rigid_children"] = [rigid_child(model)]
    directory = str(Path.cwd() / "controlled CAD fixtures")
    models = {owner, *(row["model"] for row in rows)}
    models.update(child["model"] for row in rows for child in row.get("rigid_children", []))
    state = {
        "profile": policy.PROFILE,
        "service_instance_id": instance_id,
        "model": owner,
        "complete": True,
        "working_directory": directory,
        "working_directory_source": "Session.GetCurrentDirectory",
        "model_origins": {model: str(Path(directory) / (model + ".2")) for model in models},
        "model_origin_readback": {
            model: {
                "source": "Model.GetOrigin",
                "read_complete": True,
                "result_category": "returned_string",
            }
            for model in models
        },
        "units": {"length": "mm"},
        "context": {
            "current_model": owner,
            "window_model": owner,
            "is_exploded": False,
            "dynamic_positioning": False,
        },
        "failed_features": [],
        "components": rows,
        "reference_catalog": catalog,
    }
    return bind_native_references(state)


def state_row(state, ident):
    return next(row for row in state["components"] if str(row["id"]) == str(ident))


def state_request(state, ident=83, follower=126, *, offset=12, replace_reference=False):
    row = state_row(state, ident)
    q = request()
    q["selection"].update(
        owner=state["model"], occurrence_id=str(ident), state_revision=digest(state)
    )
    q["constraints"] = []
    for axis in range(3):
        c = constraint(state["model"], row["model"], axis=axis, offset=offset if axis == 0 else 0)
        if axis == 0 and replace_reference:
            c["assembly_reference"]["item_id"] = 19
        q["constraints"].append(c)
    q["affected_occurrences"] = sorted([str(ident), str(follower)])
    return q


def successful_edit(*, replace_reference=False, rigid=False, ids=(22, 83, 126, 157)):
    before = native_state(ids=ids, rigid=rigid)
    target, follower = ids[1:3]
    q = state_request(before, target, follower, replace_reference=replace_reference)
    intent = policy.make_intent(before, q)
    after = deepcopy(before)
    state_row(after, target)["constraints"] = deepcopy(intent["constraints"])
    shift = 17 if replace_reference else 12
    state_row(after, target)["component_path_transform"] = transform([shift, 0, 0])
    state_row(after, follower)["component_path_transform"] = transform([shift + 3, 0, 0])
    bind_native_references(after)
    return before, after, intent


def failed_checks(verification):
    return [c["check"] for c in verification["checks"] if c["passed"] is not True]


@pytest.mark.parametrize("rigid", [False, True])
@pytest.mark.parametrize("replace_reference", [False, True])
@pytest.mark.parametrize("ids", [(22, 83, 126, 157), (7, 420, 36, 901)])
def test_legal_edit_moves_only_target_and_dependent_with_same_repeated_model_protected(
    rigid, replace_reference, ids
):
    before, after, intent = successful_edit(
        replace_reference=replace_reference, rigid=rigid, ids=ids
    )
    assert policy.influence(before, ids[1]) == sorted(map(str, ids[1:3]))
    assert not failed_checks(policy.compare(before, after, intent))
    assert state_row(after, ids[3]) == state_row(before, ids[3])


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.update(complete=False),
        lambda s: s["context"].update(window_model="foreign.asm"),
        lambda s: s["context"].update(is_exploded=True),
        lambda s: s["context"].update(dynamic_positioning=True),
        lambda s: s["context"].pop("dynamic_positioning"),
        lambda s: s.update(failed_features=[83]),
        lambda s: s["components"].append(deepcopy(s["components"][0])),
        lambda s: state_row(s, 83).update(owner="foreign.asm"),
        lambda s: state_row(s, 83).update(component_path=[2, 83]),
        lambda s: state_row(s, 83).update(underconstrained=True),
        lambda s: state_row(s, 83).update(packaged=True),
        lambda s: state_row(s, 83).update(status="FEAT_SUPPRESSED"),
        lambda s: state_row(s, 83).update(flexible=True),
        lambda s: state_row(s, 83).pop("frozen"),
        lambda s: state_row(s, 83).update(constraints_error={"code": "GetterFailed"}),
        lambda s: state_row(s, 83).update(unplaced=True),
        lambda s: state_row(s, 83).pop("placement_metadata"),
        lambda s: state_row(s, 83)["placement_metadata"].update(supported=False),
        lambda s: state_row(s, 83)["constraints"][0].pop("assembly_side"),
        lambda s: state_row(s, 83)["constraints"][0].pop("offset"),
        lambda s: state_row(s, 83)["constraints"][0].update(offset={"error": "GetterFailed"}),
        lambda s: state_row(s, 83)["constraints"][0]["component_reference"].pop("plane"),
        lambda s: state_row(s, 83)["component_path_transform"].update(x_axis=[2, 0, 0]),
        lambda s: state_row(s, 83)["component_path_transform"].update(z_axis=[0, 0, -1]),
        lambda s: s["reference_catalog"].append(deepcopy(s["reference_catalog"][0])),
    ],
)
def test_incomplete_or_unsupported_state_is_never_admitted(mutate):
    state = native_state()
    mutate(state)
    with pytest.raises(Error):
        policy.validate_state(state)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: state_row(s, 126)["constraints"][0]["assembly_reference"].update(
            component_path=[83, 91]
        ),
        lambda s: state_row(s, 126)["constraints"][0]["assembly_reference"].update(
            model="external.prt"
        ),
        lambda s: state_row(s, 126)["constraints"][0]["component_reference"].update(
            model="wrong_owner.prt"
        ),
        lambda s: state_row(s, 126)["constraints"][0]["component_reference"].update(
            component_path=[83]
        ),
        lambda s: state_row(s, 83)["children"].append(9001),
        lambda s: state_row(s, 126)["children"].append(83),
    ],
)
def test_unprovable_influence_is_refused(mutate):
    state = native_state()
    mutate(state)
    with pytest.raises(Error):
        policy.influence(state, "83")


@pytest.mark.parametrize("declaration", [["83"], ["22", "83", "126"], ["83", "126", "157"]])
def test_missing_or_blanket_influence_authorization_is_refused(declaration):
    state = native_state()
    q = state_request(state)
    q["affected_occurrences"] = declaration
    with pytest.raises(Error):
        policy.make_intent(state, q)


@pytest.mark.parametrize("bad_ref", [reference("clamp_jig.asm", 999), reference("external.asm", 5)])
def test_absent_or_foreign_reference_cannot_enter_intent(bad_ref):
    state = native_state()
    q = state_request(state)
    q["constraints"][0]["assembly_reference"] = bad_ref
    with pytest.raises(Error):
        policy.make_intent(state, q)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: state_row(s, 157)["component_path_transform"]["origin"].__setitem__(0, 60.125),
        lambda s: state_row(s, 126)["component_path_transform"]["origin"].__setitem__(0, 3),
        lambda s: state_row(s, 83)["component_path_transform"]["origin"].__setitem__(0, 12.01),
        lambda s: state_row(s, 126)["constraints"][0].update(offset=2),
        lambda s: state_row(s, 83)["constraints"][0].update(offset=13),
        lambda s: state_row(s, 83).update(model="substituted.prt"),
        lambda s: s["components"].pop(),
        lambda s: s["reference_catalog"][0]["plane"]["origin"].__setitem__(0, 1),
    ],
)
def test_setter_success_cannot_hide_wrong_pose_identity_constraints_or_reference_geometry(mutate):
    before, after, intent = successful_edit()
    mutate(after)
    try:
        verification = policy.compare(before, after, intent)
    except Error:
        return
    assert failed_checks(verification)


def test_actual_reference_plane_cannot_disagree_with_frozen_catalog_to_fake_correct_offset():
    before, after, intent = successful_edit()
    own_plane = state_row(after, 83)["constraints"][0]["component_reference"]["plane"]
    own_plane["origin"][0] = 1
    state_row(after, 83)["component_path_transform"]["origin"][0] = 11
    state_row(after, 126)["component_path_transform"]["origin"][0] = 14
    try:
        result = policy.compare(before, after, intent)
    except Error:
        return
    assert failed_checks(result)


def test_fresh_readback_cannot_omit_parent_child_identity_changes():
    before, after, intent = successful_edit()
    state_row(after, 83)["children"] = [126, 157]
    state_row(after, 157)["parents"] = [83]
    result = policy.compare(before, after, intent)
    assert failed_checks(result)


def test_target_constraint_cannot_become_forced_or_ignored_while_pose_stays_correct():
    before, after, intent = successful_edit()
    state_row(after, 83)["constraints"][0]["attributes"] = {
        "raw_null_default": False,
        "force": True,
        "ignore": True,
    }
    try:
        result = policy.compare(before, after, intent)
    except Error:
        return
    assert failed_checks(result)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.update(components=[None]),
        lambda s: state_row(s, 83).update(constraints=[None]),
        lambda s: s.update(reference_catalog=[None]),
    ],
)
def test_malformed_observation_yields_structured_error(mutate):
    state = native_state()
    mutate(state)
    with pytest.raises(Error):
        policy.validate_state(state)


def test_named_repeated_member_remains_ambiguous_and_exact_occurrence_is_unique():
    state = native_state()
    with pytest.raises(Error) as exc:
        policy._choose(state, "slider.prt")
    assert exc.value.code == "E_CONFLICT"
    assert policy._choose(state, "83")["id"] == 83


class NoCadClient:
    def __init__(self, instance="independent-generation-17"):
        self.instance = instance
        self.cad_calls = []

    def health(self):
        return {"service_instance_id": self.instance}

    def op(self, name, *args, **kwargs):
        self.cad_calls.append(name)
        pytest.fail("the isolated policy must refuse before CAD dispatch: " + name)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda q: q["selection"].update(instance_id="other-generation"),
        lambda q: q["selection"].update(owner="other_owner.asm"),
        lambda q: q["selection"].update(occurrence_id="157"),
        lambda q: q["selection"].update(state_revision="f" * 64),
    ],
)
def test_stale_or_foreign_selection_stops_before_dispatch(monkeypatch, mutate):
    state = native_state()
    q = state_request(state)
    mutate(q)
    monkeypatch.setattr(policy, "snapshot", lambda c, name: {"native": state})
    client = NoCadClient()
    with pytest.raises(Error) as exc:
        policy._plan(client, {"component": "83"}, {"name": state["model"], "request": q})
    assert exc.value.code == "E_CONFLICT"
    assert exc.value.details["dispatch_state"] == "not_started"
    assert client.cad_calls == []


def test_pending_snapshot_preserves_original_error_and_never_asks_another_getter(monkeypatch):
    state = native_state()
    q = state_request(state)
    original = Error(
        "E_NATIVE_READ_PENDING",
        "read may still be executing",
        {
            "dispatch_state": "unknown",
            "operation": "assembly.constraint-state",
            "cli_invocation_id": "pending-origin",
            "cause": {"code": "E_NETWORK"},
        },
    )

    def pending(client, name):
        raise original

    monkeypatch.setattr(policy, "snapshot", pending)
    client = NoCadClient()
    with pytest.raises(Error) as exc:
        policy._plan(client, {"component": "83"}, {"name": state["model"], "request": q})
    assert exc.value is original
    assert client.cad_calls == []
    assert original.details["cause"] == {"code": "E_NETWORK"}


def test_second_independent_intent_after_reload_can_make_a_different_edit():
    _, reloaded, _ = successful_edit()
    q = state_request(reloaded, offset=-4)
    frozen = deepcopy(reloaded)
    intent = policy.make_intent(reloaded, q)
    edited = deepcopy(reloaded)
    state_row(edited, 83)["constraints"] = deepcopy(intent["constraints"])
    state_row(edited, 83)["component_path_transform"] = transform([-4, 0, 0])
    state_row(edited, 126)["component_path_transform"] = transform([-1, 0, 0])
    bind_native_references(edited)
    assert not failed_checks(policy.compare(reloaded, edited, intent))
    assert reloaded == frozen


def protected_snapshot(native):
    return {
        "native": deepcopy(native),
        "parts": {
            "slider.prt": {
                "geometry": {"surface:91": {"type": "plane", "origin": [0, 0, 3]}},
                "dimensions": [{"name": "d7", "value": 31.125, "tolerance": {"plus": 0.2}}],
                "material": "SYNTHETIC_ACCEPTANCE_ALUMINUM",
                "relations": ["d9 = d7 / 2"],
                "parameters": [{"name": "PURPOSE", "value": "SYNTHETIC"}],
            }
        },
        "rigid_definitions": {
            "carriage.asm": [{"id": "49", "model": "rail.prt", "transform": transform([0, 5, 0])}]
        },
        "origins": {"slider.prt": "C:/owned/fixture/slider.prt.3"},
        "session_models": [native["model"], "slider.prt", "travel_stop.prt"],
        "owner_protection": {
            "features": [{"id": "5", "type": "FEATTYPE_DATUM_PLANE", "status": "FEAT_ACTIVE"}],
            "parameters": {"parameters": [{"name": "PURPOSE", "value": "SYNTHETIC"}]},
            "relations": {"relations": []},
            "units": {"length": "mm"},
            "material": None,
            "origin": "C:/owned/fixture/clamp_jig.asm.2",
        },
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s["parts"]["slider.prt"]["geometry"]["surface:91"]["origin"].__setitem__(2, 4),
        lambda s: s["parts"]["slider.prt"]["dimensions"][0].update(value=31.1250000001),
        lambda s: s["parts"]["slider.prt"]["dimensions"][0]["tolerance"].update(plus=0.1),
        lambda s: s["parts"]["slider.prt"].update(material="OTHER_MATERIAL"),
        lambda s: s["parts"]["slider.prt"].update(relations=[]),
        lambda s: s["parts"]["slider.prt"]["parameters"][0].update(value="OTHER"),
        lambda s: s["rigid_definitions"]["carriage.asm"][0]["transform"]["origin"].__setitem__(
            1, 6
        ),
        lambda s: s["origins"].update({"slider.prt": "C:/unowned/slider.prt.3"}),
        lambda s: s["session_models"].append("unrequested.prt"),
        lambda s: s["owner_protection"]["parameters"]["parameters"][0].update(value="OTHER"),
        lambda s: s["owner_protection"]["relations"].update(relations=["d11 = 5"]),
        lambda s: s["owner_protection"]["features"][0].update(status="FEAT_SUPPRESSED"),
    ],
)
def test_constituent_and_rigid_definition_protection_are_not_pose_exemptions(mutate):
    native_before, native_after, intent = successful_edit(rigid=True)
    before, after = protected_snapshot(native_before), protected_snapshot(native_after)
    assert not failed_checks(policy.verify(before, after, intent))
    mutate(after)
    assert failed_checks(policy.verify(before, after, intent))


def retained_run(before, intent):
    return {
        "target": intent["model"],
        "driver_plan": {
            "target": {"instance_id": "independent-generation-17"},
            "changes": [
                {
                    "action": "assembly.redefine-constraints",
                    "after": {
                        "model": intent["model"],
                        "component": intent["target"],
                        "units": "mm",
                        "expected": deepcopy(before["native"]),
                        "constraints": deepcopy(intent["request"]["constraints"]),
                    },
                }
            ],
            "base_snapshot": {
                "extensions": {
                    "creo": {
                        "observation": {
                            "constraints_before": before,
                            "constraints_intent": intent,
                        }
                    }
                }
            },
        },
    }


@pytest.mark.parametrize("wrong_pose", [False, True])
def test_query_recovery_and_retained_registration_use_same_independent_pose_predicate(
    monkeypatch, wrong_pose
):
    native_before, native_after, intent = successful_edit()
    before, after = protected_snapshot(native_before), protected_snapshot(native_after)
    if wrong_pose:
        state_row(after["native"], 83)["component_path_transform"]["origin"][0] = 14
    run = retained_run(before, intent)
    untouched = deepcopy(run)
    monkeypatch.setattr(policy, "snapshot", lambda client, name: deepcopy(after))
    proof = policy.recovery(NoCadClient(), run)
    assert proof["accepted"] is (not wrong_pose)
    assert proof["can_register"] == (["partial"] if wrong_pose else ["applied"])
    assert bool(failed_checks(policy.verify(before, after, intent))) is wrong_pose
    policy.retained_evidence_sufficient(run, proof)
    assert run == untouched
    if wrong_pose:
        forged = deepcopy(proof)
        forged["accepted"] = True
        with pytest.raises(Error):
            policy.retained_evidence_sufficient(run, forged)


def test_recovery_does_not_infer_applied_from_an_unchanged_target(monkeypatch):
    native_before, _, intent = successful_edit()
    before = protected_snapshot(native_before)
    monkeypatch.setattr(policy, "snapshot", lambda client, name: deepcopy(before))
    proof = policy.recovery(NoCadClient(), retained_run(before, intent))
    assert proof["accepted"] is False
    assert proof["can_register"] == ["not_applied"]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda row: row.pop("rigid_children"),
        lambda row: row.update(rigid_children=None),
        lambda row: row.update(rigid_children=[None]),
        lambda row: row["rigid_children"].append(deepcopy(row["rigid_children"][0])),
        lambda row: row["rigid_children"][0].update(owner="foreign.asm"),
        lambda row: row["rigid_children"][0].update(model="nested_again.asm"),
        lambda row: row["rigid_children"][0].update(status="FEAT_SUPPRESSED"),
        lambda row: row["rigid_children"][0].update(placed=False),
        lambda row: row["rigid_children"][0].update(flexible=True),
        lambda row: row["rigid_children"][0].update(substitute=True),
        lambda row: row["rigid_children"][0].pop("bulkitem"),
        lambda row: row["rigid_children"][0].pop("constraints"),
        lambda row: row["rigid_children"][0].pop("placement_metadata"),
        lambda row: row["rigid_children"][0]["placement_metadata"].update(supported=False),
        lambda row: row["rigid_children"][0]["transform"].update(x_axis=[2, 0, 0]),
        lambda row: row["rigid_children"][0]["constraints"][0].update(
            attributes={"raw_null_default": False, "force": True, "ignore": False}
        ),
    ],
)
def test_rigid_assembly_requires_complete_supported_internal_occurrences(mutate):
    state = native_state(rigid=True)
    mutate(state_row(state, 83))
    with pytest.raises(Error):
        policy.validate_state(state)


def test_new_target_custom_data_cannot_be_hidden_by_matching_solved_pose():
    before, after, intent = successful_edit()
    state_row(after, 83)["constraints"][0]["user_data"] = "UNREQUESTED-DATA"
    assert failed_checks(policy.compare(before, after, intent))


def test_missing_owner_protection_is_incomplete_even_when_both_snapshots_omit_it():
    native_before, native_after, intent = successful_edit()
    before, after = protected_snapshot(native_before), protected_snapshot(native_after)
    before.pop("owner_protection")
    after.pop("owner_protection")
    try:
        result = policy.verify(before, after, intent)
    except Error:
        return
    assert failed_checks(result)


def test_predictable_conflict_same_plane_pair_cannot_require_two_different_offsets():
    state = native_state()
    state_row(state, 83)["constraints"].append(deepcopy(state_row(state, 83)["constraints"][0]))
    q = state_request(state, offset=12)
    duplicate = deepcopy(q["constraints"][0])
    duplicate["offset"] = 13
    q["constraints"].append(duplicate)
    policy.validate_request(q)
    before = deepcopy((state, q))
    with pytest.raises(Error):
        policy.make_intent(state, q)
    assert (state, q) == before


def test_predictable_conflict_rigid_rotation_cannot_map_orthogonal_normals_to_parallel():
    state = native_state()
    q = state_request(state)
    q["constraints"][1]["assembly_reference"] = deepcopy(q["constraints"][0]["assembly_reference"])
    policy.validate_request(q)
    before = deepcopy((state, q))
    with pytest.raises(Error):
        policy.make_intent(state, q)
    assert (state, q) == before


@pytest.mark.parametrize("side", ["assembly_side", "component_side"])
def test_datum_side_none_is_refused_before_setting_constraints(side):
    state = native_state()
    q = state_request(state)
    q["constraints"][0][side] = "DATUM_SIDE_NONE"
    with pytest.raises(Error):
        policy.make_intent(state, q)


def physical_state():
    state = native_state()
    for ref in state["reference_catalog"]:
        ref["plane"]["kind"] = "physical_plane"
    for row in state["components"]:
        for c in row["constraints"]:
            for role in ("assembly_reference", "component_reference"):
                c[role]["plane"]["kind"] = "physical_plane"
            c["assembly_side"] = "DATUM_SIDE_NONE"
            c["component_side"] = "DATUM_SIDE_NONE"
    return state


def test_explicit_physical_plane_none_sides_are_supported():
    state = physical_state()
    q = state_request(state)
    for c in q["constraints"]:
        c["assembly_side"] = "DATUM_SIDE_NONE"
        c["component_side"] = "DATUM_SIDE_NONE"
    policy.make_intent(state, q)


@pytest.mark.parametrize("side", ["assembly_side", "component_side"])
def test_physical_plane_datum_side_is_refused_before_setting_constraints(side):
    state = physical_state()
    q = state_request(state)
    for c in q["constraints"]:
        c["assembly_side"] = "DATUM_SIDE_NONE"
        c["component_side"] = "DATUM_SIDE_NONE"
    q["constraints"][0][side] = "DATUM_SIDE_RED"
    q["constraints"][1][side] = "DATUM_SIDE_RED"
    # Two flips permit a proper rigid rotation; refusal must be the side contract.
    with pytest.raises(Error):
        policy.make_intent(state, q)


@pytest.mark.parametrize("kind", [None, "cylinder", "unknown"])
def test_missing_or_unsupported_plane_kind_cannot_be_used_as_a_planar_reference(kind):
    state = native_state()
    for ref in state["reference_catalog"]:
        if ref["model"] == state["model"] and ref["item_id"] == 5:
            if kind is None:
                ref["plane"].pop("kind")
            else:
                ref["plane"]["kind"] = kind
    for row in state["components"]:
        for c in row["constraints"]:
            ref = c["assembly_reference"]
            if ref["model"] == state["model"] and ref["item_id"] == 5:
                if kind is None:
                    ref["plane"].pop("kind")
                else:
                    ref["plane"]["kind"] = kind
    q = state_request(state)
    with pytest.raises(Error):
        policy.make_intent(state, q)


def test_retained_registration_cannot_claim_not_applied_for_a_changed_wrong_pose(monkeypatch):
    native_before, native_after, intent = successful_edit()
    before, after = protected_snapshot(native_before), protected_snapshot(native_after)
    state_row(after["native"], 83)["component_path_transform"]["origin"][0] = 14
    run = retained_run(before, intent)
    monkeypatch.setattr(policy, "snapshot", lambda client, name: deepcopy(after))
    proof = policy.recovery(NoCadClient(), run)
    assert proof["accepted"] is False and proof["can_register"] == ["partial"]
    proof["can_register"] = ["not_applied"]
    with pytest.raises(Error):
        policy.retained_evidence_sufficient(run, proof)


def test_exact_native_component_path_is_preserved_but_edit_input_is_local():
    before = native_state()
    for row in before["components"]:
        for c in row["constraints"]:
            c["component_reference"]["component_path"] = [row["id"]]
    bind_native_references(before)
    frozen = deepcopy(before)
    policy.validate_state(before)
    assert policy.influence(before, "83") == ["126", "83"]
    for c in state_row(before, 83)["constraints"]:
        assert policy._copy_constraint(c)["component_reference"]["component_path"] == []
    q = state_request(before)
    policy.validate_request(q)
    intent = policy.make_intent(before, q)
    after = deepcopy(before)
    state_row(after, 83)["constraints"] = deepcopy(intent["constraints"])
    for c in state_row(after, 83)["constraints"]:
        c["component_reference"]["component_path"] = [83]
    bind_native_references(after)
    state_row(after, 83)["component_path_transform"] = transform([12, 0, 0])
    state_row(after, 126)["component_path_transform"] = transform([15, 0, 0])
    assert not failed_checks(policy.compare(before, after, intent))
    assert before == frozen
    assert state_row(before, 83)["constraints"][0]["component_reference"]["component_path"] == [83]


@pytest.mark.parametrize("path", [[157], [2, 83], [126]])
def test_component_side_native_path_cannot_select_a_different_or_nested_occurrence(path):
    state = native_state()
    state_row(state, 83)["constraints"][0]["component_reference"]["component_path"] = path
    with pytest.raises(Error):
        policy.influence(state, "83")
