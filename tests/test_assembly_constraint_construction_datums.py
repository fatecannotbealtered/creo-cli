"""Sanitized C2007-shaped construction-plane cases, not actual Creo acceptance.

The original receipt and its SHA binding stay in local evidence. These fixtures have
different model names, IDs, occurrence counts and offsets and never open that file.
"""

from copy import deepcopy

import pytest

from creo_cli import assembly_constraints as policy
from creo_cli.core import Error
from tests.test_assembly_constraint_policy import (
    bind_native_references,
    failed_checks,
    native_state,
    plane_reference,
    state_request,
    state_row,
    transform,
)


def with_frames(state):
    refs = list(state["reference_catalog"])
    for row in state["components"]:
        for c in row["constraints"]:
            refs += [c[k] for k in ("assembly_reference", "component_reference") if c.get(k)]
    axes = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    for ref in refs:
        p = ref["plane"]
        axis = axes.index(p["normal"])
        p["frame"] = {
            "origin": deepcopy(p["origin"]),
            "x_axis": deepcopy(axes[(axis + 1) % 3]),
            "y_axis": deepcopy(axes[(axis + 2) % 3]),
            "z_axis": deepcopy(p["normal"]),
        }
        p["feature_owner"] = ref["model"]
    return state


def add_internal(state, *, consumer=83, feature=917, surface=918, index=0):
    c = state_row(state, consumer)["constraints"][index]
    offset = c["offset"]
    origin = [0, 0, 0]
    origin[index] = offset
    ref = plane_reference(state["model"], surface, index, origin=origin)
    ref["plane"].update(
        feature_id=feature, feature_name="construction", feature_owner=state["model"]
    )
    ref.update(
        classification={"public_feature": False, "source": "Feature.GetIsVisible"},
        reference_usage="protection_only",
    )
    source = deepcopy(c["assembly_reference"])
    source["reference_owner_source"] = "DatumFeature.WFeature.GetSolid"
    path = [{"element_id": 410}, {"array_index": 0}]
    ref["auxiliary"] = {
        "owner_model": state["model"],
        "feature_id": feature,
        "surface_id": surface,
        "status": "FEAT_ACTIVE",
        "parents": [source["plane"]["feature_id"]],
        "children": [consumer],
        "definition": {
            "array_read_complete": True,
            "source": (
                "WFeature.GetElementTree; complete indexed PRO_E_DTMPLN_CONSTRAINTS.GetChildren"
            ),
            "constraint_count": 1,
            "constraints": [
                {
                    "index": 0,
                    "indexed_path": path,
                    "element_paths": {
                        "type": path + [{"element_id": 412}],
                        "reference": path + [{"element_id": 413}],
                        "offset": path + [{"element_id": 414}],
                    },
                    "type_raw": 3,
                    "reference": source,
                    "offset_raw": offset,
                    "units": "mm",
                }
            ],
            "flip_raw": 0,
            "fit": {
                "type_raw": -1,
                "mode": "default",
                "reference_applicability": "not_applicable",
                "radius_applicability": "not_applicable",
                "outline_applicability": "not_applicable",
                "outline_value_read": False,
            },
        },
        "consumer_occurrence_id": consumer,
        "matched_constraint_index": index,
        "link_basis": "internal_visibility_single_consumer_unique_offset_definition",
        "driver_crosscheck": {"status": "not_checked"},
    }
    state["reference_catalog"].append(ref)
    with_frames(state)
    bind_native_references(state)
    return ref


def internal(state, feature=917):
    return next(r for r in state["reference_catalog"] if r["plane"]["feature_id"] == feature)


def construction_edit(*, all_target_axes=False):
    before = with_frames(native_state())
    add_internal(before)
    if all_target_axes:
        add_internal(before, feature=919, surface=920, index=1)
        add_internal(before, feature=921, surface=922, index=2)
    add_internal(before, consumer=157, feature=927, surface=928)
    q = state_request(before)
    intent = policy.make_intent(before, q)
    after = deepcopy(before)
    state_row(after, 83)["constraints"] = deepcopy(intent["constraints"])
    state_row(after, 83)["component_path_transform"] = transform([12, 0, 0])
    state_row(after, 126)["component_path_transform"] = transform([15, 0, 0])
    moved = internal(after)
    moved["plane"]["origin"] = [12, 0, 0]
    moved["plane"]["frame"]["origin"] = [12, 0, 0]
    moved["auxiliary"]["definition"]["constraints"][0]["offset_raw"] = 12
    bind_native_references(after)
    return before, after, intent


def rejected_read_or_comparison(before, after, intent):
    try:
        result = policy.compare(before, after, intent)
    except Error:
        return
    assert failed_checks(result)


@pytest.mark.parametrize("all_target_axes", [False, True])
def test_bound_internal_offset_plane_may_follow_exact_authorized_consumer(all_target_axes):
    before, after, intent = construction_edit(all_target_axes=all_target_axes)
    frozen = deepcopy((before, after))
    assert not failed_checks(policy.compare(before, after, intent))
    assert len(before["reference_catalog"]) == len(after["reference_catalog"])
    assert internal(after)["plane"]["origin"] == [12, 0, 0]
    assert internal(after, 927) == internal(before, 927)
    assert (before, after) == frozen


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["auxiliary"].update(owner_model="foreign.asm"),
        lambda r: r["auxiliary"].update(feature_id=999),
        lambda r: r["auxiliary"].update(surface_id=999),
        lambda r: r["auxiliary"].update(children=[157]),
        lambda r: r["auxiliary"].update(parents=[999]),
        lambda r: r["auxiliary"].update(consumer_occurrence_id=157),
        lambda r: r["auxiliary"].update(matched_constraint_index=1),
        lambda r: r["auxiliary"]["definition"]["constraints"][0]["reference"].update(
            path_root_model="foreign.asm"
        ),
        lambda r: r["auxiliary"]["definition"].update(array_read_complete=False),
        lambda r: r["auxiliary"]["definition"].update(constraint_count=2),
        lambda r: r["auxiliary"]["definition"]["constraints"][0].pop("offset_raw"),
        lambda r: r["auxiliary"]["definition"]["constraints"][0].update(type_raw=999),
        lambda r: r["auxiliary"]["definition"]["constraints"][0].update(index=1),
        lambda r: r["auxiliary"]["definition"]["constraints"][0]["element_paths"]["type"][
            -1
        ].update(element_id=414),
        lambda r: r.pop("auxiliary"),
        lambda r: r["classification"].update(source="name_and_count_guess"),
        lambda r: r["auxiliary"].update(status="FEAT_SUPPRESSED"),
    ],
)
def test_internal_identity_definition_and_unique_source_must_be_complete(mutate):
    state = with_frames(native_state())
    r = add_internal(state)
    mutate(r)
    with pytest.raises(Error):
        policy.make_intent(state, state_request(state))


def test_duplicate_constraint_slots_cannot_be_disambiguated_by_supplied_index_hint():
    state = with_frames(native_state())
    row = state_row(state, 83)
    row["constraints"].append(deepcopy(row["constraints"][0]))
    add_internal(state)
    q = state_request(state)
    q["constraints"].append(deepcopy(q["constraints"][0]))
    with pytest.raises(Error):
        policy.make_intent(state, q)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda r: r["plane"].update(origin=[13, 0, 0]),
        lambda r: r["plane"]["frame"].update(origin=[13, 0, 0]),
        lambda r: r["plane"]["frame"].update(x_axis=[0, -1, 0], y_axis=[0, 0, -1]),
        lambda r: r["plane"].update(normal=[0, 1, 0]),
        lambda r: r["auxiliary"]["definition"]["constraints"][0].update(offset_raw=13),
        lambda r: r["auxiliary"]["definition"].update(flip_raw=1),
        lambda r: r["auxiliary"]["definition"]["fit"].update(type_raw=0),
        lambda r: r["auxiliary"]["definition"]["fit"].pop("outline_value_read"),
        lambda r: r["auxiliary"]["definition"]["constraints"][0]["reference"].update(item_id=6),
    ],
)
def test_motion_exemption_cannot_hide_wrong_plane_frame_offset_flip_fit_or_reference(mutate):
    before, after, intent = construction_edit()
    mutate(internal(after))
    rejected_read_or_comparison(before, after, intent)


def test_unrelated_consumer_internal_plane_remains_strictly_protected():
    before, after, intent = construction_edit()
    r = internal(after, 927)
    r["plane"]["origin"][0] += 1
    r["plane"]["frame"]["origin"][0] += 1
    rejected_read_or_comparison(before, after, intent)


@pytest.mark.parametrize("rigid", [False, True])
def test_part_or_rigid_definition_internal_plane_is_not_an_owner_motion_exemption(rigid):
    before = with_frames(native_state(rigid=rigid))
    add_internal(before)
    member = state_row(before, 83)["model"]
    extra = plane_reference(member, 988, 2, [83])
    extra["plane"].update(feature_id=987)
    extra.update(
        classification={"public_feature": False, "source": "Feature.GetIsVisible"},
        reference_usage="protection_only",
    )
    before["reference_catalog"].append(extra)
    with_frames(before)
    bind_native_references(before)
    intent = policy.make_intent(before, state_request(before))
    after = deepcopy(before)
    state_row(after, 83)["constraints"] = deepcopy(intent["constraints"])
    state_row(after, 83)["component_path_transform"] = transform([12, 0, 0])
    state_row(after, 126)["component_path_transform"] = transform([15, 0, 0])
    moved = internal(after)
    moved["plane"]["origin"] = [12, 0, 0]
    moved["plane"]["frame"]["origin"] = [12, 0, 0]
    moved["auxiliary"]["definition"]["constraints"][0]["offset_raw"] = 12
    bind_native_references(after)
    assert not failed_checks(policy.compare(before, after, intent))
    part_internal = next(r for r in after["reference_catalog"] if r["item_id"] == 988)
    part_internal["plane"]["origin"][2] = 1
    rejected_read_or_comparison(before, after, intent)


@pytest.mark.parametrize("consumer", [83, 157])
def test_internal_owner_plane_is_never_an_editable_ground_reference(consumer):
    state = with_frames(native_state())
    r = add_internal(state, consumer=consumer)
    q = state_request(state)
    q["constraints"][0]["assembly_reference"] = policy.reference_identity(r)
    with pytest.raises(Error):
        policy.make_intent(state, q)
