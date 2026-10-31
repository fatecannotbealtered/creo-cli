"""dimension list, dimension set, dimension tolerance, model set-tolerance-standard: the numbers a
design is driven by, read and changed the way a person edits one in the model tree -- set,
regenerate, and back out if the model cannot take it -- and the tolerances they are made to."""

from __future__ import annotations

import math
import re

from .. import building, engine, paths
from ..core import Error, digest, number, page
from ..registry import LIMIT, MODEL, OFFSET, Command, Param
from ..schemas import NN, NS, UNITS, WRITTEN, B, N, S, array, listing, shape, written
from ..transport import Client
from ..validation import text, validate

REF = text(pattern=r"^[A-Za-z0-9_-]{1,80}$", maximum=80)
UNITS_FOR = ("mm", "cm", "m", "in", "ft", "deg")
FIT = re.compile(r"^(?:[A-Z]{1,2}|[a-z]{1,2})[0-9]{1,2}$")
# Creo returns a tolerance through its own arithmetic: 20.03 - 20 is 0.030000000000001137.
TOLERANCE_ABS = 1e-9


def _rows(
    client: Client, name: str, feature: str | None = None, *, check_regeneration: bool = False
) -> dict:
    query = {"model": name} | ({"feature": feature} if feature else {})
    if check_regeneration:
        query["check_regeneration"] = True
    data = engine.normalize(client.op("dimension.list", query))
    if data.get("model") != name or not isinstance(data.get("dimensions"), list):
        raise Error("E_PROTOCOL", "dimension read-back lacks the requested model or dimension list")
    # Creo also lists the typeless placeholders a sketch keeps for its references; they drive
    # nothing a person can edit, so they are not offered.
    data["dimensions"] = [d for d in data["dimensions"] if d.get("type")]
    return data


def list_dimensions(opts: dict) -> dict:
    name = engine.model_name(opts["model"], ("prt", "asm"))
    if opts.get("feature"):
        validate(opts["feature"], REF, "feature")

    def fetch(client: Client) -> dict:
        data = _rows(client, name, opts.get("feature"))
        return page(data["dimensions"], opts["limit"], opts["offset"]) | {
            "model": data["model"],
            "units": data["units"],
            # What a sketch holds equal or aligned: change one, the others follow.
            "held_together": data.get("held_together") or [],
            "_untrusted": ["items", "model", "held_together"],
        }

    return engine.read(opts, fetch)


def _prepare_set(opts: dict) -> dict:
    validate(opts["dimension"], REF, "dimension")
    if not math.isfinite(opts["value"]):
        raise Error("E_VALIDATION", "value must be a finite number", {"path": "value"})
    return {"name": engine.model_name(opts["model"], ("prt", "asm"))}


def _target(rows: list, name: str, wanted: str) -> dict:
    target = next(
        (d for d in rows if str(d["name"]).lower() == wanted.lower() or d["id"] == wanted), None
    )
    if target is None:
        raise Error(
            "E_NOT_FOUND",
            "no dimension of that name or id",
            {
                "dimension": wanted,
                "fix": f"creo-cli dimension list --model {name}",
                "_untrusted": ["dimension"],
            },
        )
    return target


def _same_units(target: dict, given: str) -> None:
    unit = building.UNIT_ALIASES.get(str(target["units"]).lower(), target["units"])
    if given != unit:
        raise Error(
            "E_CONFLICT",
            "the dimension is in another unit than --units says; nothing is converted",
            {
                "dimension_units": target["units"],
                "given_units": given,
                "_untrusted": ["dimension_units"],
            },
        )


def _plan_set(client: Client, opts: dict, pre: dict) -> engine.Plan:
    client.require_capability("dimension_regeneration_readback", 1)
    name = pre["name"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    directory = engine.store_directory(before, s)
    native_files_before = paths.model_files(directory, name)
    reading = _rows(client, name, check_regeneration=True)
    native_before = reading.get("regeneration_check")
    if (
        not isinstance(native_before, dict)
        or native_before.get("completed") is not True
        or native_before.get("model") != name
        or not native_before.get("source")
        or not isinstance(native_before.get("failed_features"), list)
        or not isinstance(native_before.get("checked_feature_ids"), list)
    ):
        raise Error(
            "E_BACKEND_UNAVAILABLE",
            "dimension writes require a service with a completed regeneration-state reader",
            {
                "dispatch_state": "not_started",
                "native_check": native_before,
                "next_action": "use the matching service after existing models are protected; "
                "no dimension write was dispatched",
                "_untrusted": ["native_check"],
            },
        )
    rows = reading["dimensions"]
    wanted = opts["dimension"]
    target = _target(rows, name, wanted)
    _same_units(target, opts["units"])
    if target.get("relation_driven"):
        raise Error(
            "E_CONFLICT",
            "the dimension is driven by a relation; a value set here would be overwritten",
            {"dimension": target["name"], "_untrusted": ["dimension"]},
        )
    if target.get("reference"):
        raise Error(
            "E_VALIDATION",
            "a reference dimension reports geometry and cannot drive it",
            {"dimension": target["name"], "_untrusted": ["dimension"]},
        )
    if target["type"] in ("radius", "diameter") and opts["value"] <= 0:
        raise Error("E_VALIDATION", "a radius or diameter is positive", {"path": "value"})
    old = building.features_of(client, name)
    required_ids = {f["id"] for f in old}
    observed_ids = {str(i) for i in native_before["checked_feature_ids"]}
    if not required_ids <= observed_ids:
        raise Error(
            "E_BACKEND_UNAVAILABLE",
            "the native preflight check does not cover the target's feature inventory",
            {
                "dispatch_state": "not_started",
                "request_sent": False,
                "coverage": {"expected": sorted(required_ids), "observed": sorted(observed_ids)},
                "native_check": native_before,
                "automatic_retry": False,
                "next_action": "inspect the matching service and actual native coverage; "
                "no dimension write was dispatched",
                "_untrusted": ["coverage", "native_check"],
            },
        )

    def verify(c: Client, data: dict):
        result = {"model": name, "value_before": target["value"]}
        verification = {
            "level": "selected_postconditions_verified",
            "checks": [],
            "observations": [
                {
                    "observation": "setter_reply",
                    "source": "dimension.set",
                    "independent": False,
                    "dimension": data.get("dimension"),
                    "volume": data.get("volume"),
                }
            ],
            "not_checked": [
                "design_intent",
                "loaded_service_identity",
                "concurrent_edits",
                "geometry_invariants",
                "native_reopen_of_edited_value",
            ],
        }
        checks = verification["checks"]

        def missing(checks_missing: list[str], code: str):
            verification["status"] = "incomplete"
            verification["not_checked"] += checks_missing
            verification["observations"].append(
                {
                    "observation": "independent_read_back_failed",
                    "code": code,
                    "checks": checks_missing,
                }
            )

        try:
            readback = _rows(c, name, check_regeneration=True)
            source = {
                "operation": "dimension.list",
                "model": name,
                "dimension_id": target["id"],
                "sha256": digest(readback),
                "independent": True,
            }
            matches = [d for d in readback["dimensions"] if d.get("id") == target["id"]]
            if (
                len(matches) != 1
                or not number(matches[0].get("value"))
                or not isinstance(matches[0].get("units"), str)
                or not matches[0]["units"]
                or not isinstance(readback.get("units"), dict)
            ):
                raise Error(
                    "E_PROTOCOL", "independent read-back lacks one numeric target dimension"
                )
            now = matches[0]
            result |= {"units": readback.get("units"), "dimension": now}
            checks += [
                engine.check(
                    "value_as_requested",
                    math.isclose(now["value"], opts["value"], rel_tol=1e-9, abs_tol=TOLERANCE_ABS),
                    expected=opts["value"],
                    observed=now["value"],
                    value=now["value"],
                    unit=now.get("units"),
                    tolerance={"relative": 1e-9, "absolute": TOLERANCE_ABS},
                    source=source,
                ),
                engine.check(
                    "dimension_units_unchanged",
                    building.UNIT_ALIASES.get(str(now.get("units")).lower(), now.get("units"))
                    == opts["units"],
                    expected=opts["units"],
                    observed=now.get("units"),
                    source=source,
                ),
            ]
            native = readback.get("regeneration_check")
            verification["observations"].append(
                {"observation": "regeneration_check", "source": source, "check": native}
            )
            if not isinstance(native, dict) or native.get("completed") is not True:
                missing(["native_failed_features_checked"], "native_check_incomplete")
            elif (
                native.get("model") != name
                or not native.get("source")
                or not isinstance(native.get("failed_features"), list)
                or not isinstance(native.get("checked_feature_ids"), list)
            ):
                missing(["native_failed_features_checked"], "E_PROTOCOL")
            elif not {f["id"] for f in old} <= {str(i) for i in native["checked_feature_ids"]}:
                missing(["native_failed_features_checked"], "native_check_coverage_incomplete")
            else:
                checks.append(
                    engine.check(
                        "native_failed_features_checked",
                        not native["failed_features"],
                        expected=[],
                        observed=native["failed_features"],
                        source=source,
                        native_source=native.get("source"),
                        covered_feature_ids=native["checked_feature_ids"],
                    )
                )
        except Error as exc:
            missing(
                [
                    "value_as_requested",
                    "dimension_units_unchanged",
                    "native_failed_features_checked",
                ],
                exc.code,
            )
        try:
            after_rows = building.features_of(c, name)
            after = {f["id"]: f for f in after_rows}
            checks.append(
                engine.check(
                    "every_feature_still_regenerates",
                    all(f["id"] in after and after[f["id"]]["status"] == f["status"] for f in old),
                    expected=[{"id": f["id"], "status": f["status"]} for f in old],
                    observed=[{"id": f["id"], "status": f["status"]} for f in after_rows],
                    source={
                        "operation": "feature.list",
                        "model": name,
                        "sha256": digest(after_rows),
                        "independent": True,
                    },
                )
            )
            described = engine.show(c, name)
            if described.get("model") != name or not isinstance(described.get("units"), dict):
                raise Error("E_PROTOCOL", "model read-back does not identify the requested model")
            checks.append(
                engine.check(
                    "model_units_unchanged",
                    described.get("units") == before.get("units"),
                    expected=before.get("units"),
                    observed=described.get("units"),
                    source={
                        "operation": "model.show",
                        "model": name,
                        "sha256": digest(described),
                        "independent": True,
                    },
                )
            )
            before_volume = (before.get("mass_properties") or {}).get("volume")
            after_volume = (described.get("mass_properties") or {}).get("volume")
            result["volume"] = {
                "before": before_volume,
                "after": after_volume,
                "change": after_volume - before_volume
                if number(before_volume) and number(after_volume)
                else None,
            }
            verification["observations"].append(
                {
                    "observation": "geometry",
                    "volume": result["volume"],
                    "bounding_box": described.get("bounding_box"),
                    "source": "model.show",
                    "sha256": digest(described),
                    "independent": True,
                    "unit": (described.get("units") or {}).get("length"),
                }
            )
        except Error as exc:
            missing(
                ["every_feature_still_regenerates", "model_units_unchanged", "geometry_observed"],
                exc.code,
            )
        try:
            native_files_after = paths.model_files(directory, name)
            plan.persisted = native_files_after != native_files_before
            result["persistence_scope"] = (
                "observed native-file version changes; edited-value reopen is not checked here"
            )
            verification["observations"].append(
                {
                    "observation": "native_file_persistence",
                    "source": "independent_workspace_version_bytes",
                    "before": native_files_before,
                    "after": native_files_after,
                    "changed": plan.persisted,
                    "independent": True,
                    "cause": (
                        "not established; application auto-save/ModelCHECK may save independently"
                    ),
                }
            )
        except Error as exc:
            missing(["native_file_persistence_observed"], exc.code)
        return result, verification

    plan = engine.Plan(
        op="dimension.set",
        request={"model": name, "dimension": target["id"], "value": opts["value"]},
        target=name,
        binding={
            "model": before,
            "dimension": target,
            "features": old,
            "native_check": native_before,
        },
        preview={
            "command": "dimension set",
            "model": name,
            "dimension": target,
            "from": target["value"],
            "to": opts["value"],
            "units": target["units"],
            "effect": "sets the value and regenerates the model; on a regeneration rejection "
            "restoration is attempted; an incomplete check does not establish restoration",
        },
        verify=verify,
        observe=lambda c: [(d["id"], d["value"]) for d in _rows(c, name)["dimensions"]],
        before=[(d["id"], d["value"]) for d in rows],
        arguments={
            "model": opts["model"],
            "dimension": wanted,
            "value": opts["value"],
            "units": opts["units"],
        },
    )
    return plan


def set_dimension(opts: dict) -> dict:
    return engine.write("dimension set", opts, _prepare_set, _plan_set)


# ------------------------------------------------------------------ tolerances

TOLERANCE_MEANING = {
    "plus_minus": "shown as the value with +plus and -minus after it; the part may measure from "
    "value - minus to value + plus",
    "symmetric": "shown as the value +- the tolerance",
    "limits": "shown as the two limits the part may measure between, instead of the value",
    "fit": "an ISO 286 hole (capitals) or shaft (small letters) class and grade from Creo's own "
    "tables; the limits follow the value",
    "basic": "the exact value a geometric tolerance is measured from, shown boxed, with no "
    "tolerance of its own",
    "nominal": "no tolerance shown; a general tolerance applies, if the drawing states one",
}


def _tolerance(opts: dict) -> dict:
    """Exactly one tolerance, from the flags that give it; lengths only with --units."""
    forms = {
        "plus_minus": opts.get("plus") is not None or opts.get("minus") is not None,
        "symmetric": opts.get("symmetric") is not None,
        "limits": opts.get("upper") is not None or opts.get("lower") is not None,
        "fit": opts.get("fit") is not None,
        "basic": bool(opts.get("basic")),
        "nominal": bool(opts.get("nominal")),
    }
    chosen = [k for k, given in forms.items() if given]
    if len(chosen) != 1:
        raise Error(
            "E_USAGE",
            "give exactly one tolerance: --plus with --minus, --symmetric, --upper with "
            "--lower, --fit, --basic or --nominal",
            {"given": chosen},
        )
    kind = chosen[0]
    if opts.get("show") and kind != "fit":
        raise Error("E_USAGE", "--show says how a fit is shown; it goes with --fit")
    numbers = [
        opts[k] for k in ("plus", "minus", "symmetric", "upper", "lower") if opts.get(k) is not None
    ]
    if any(not math.isfinite(v) for v in numbers):
        raise Error("E_VALIDATION", "tolerances are finite numbers")
    if numbers and not opts.get("units"):
        raise Error("E_USAGE", "a tolerance in numbers needs --units: the dimension's own unit")
    if not numbers and opts.get("units"):
        raise Error("E_USAGE", "--units goes with a tolerance in numbers")
    if kind == "plus_minus":
        if opts.get("plus") is None or opts.get("minus") is None:
            raise Error(
                "E_USAGE", "--plus and --minus go together: +0.1 / -0.05 is --plus 0.1 --minus 0.05"
            )
        if opts["plus"] + opts["minus"] <= 0:
            raise Error(
                "E_VALIDATION",
                "the upper limit must lie above the lower: value + plus above value - minus",
                {"plus": opts["plus"], "minus": opts["minus"]},
            )
        return {"type": "plus_minus", "plus": opts["plus"], "minus": opts["minus"]}
    if kind == "symmetric":
        if opts["symmetric"] <= 0:
            raise Error("E_VALIDATION", "a symmetric tolerance is positive", {"path": "symmetric"})
        return {"type": "symmetric", "value": opts["symmetric"]}
    if kind == "limits":
        if opts.get("upper") is None or opts.get("lower") is None:
            raise Error("E_USAGE", "--upper and --lower go together")
        if opts["upper"] <= opts["lower"]:
            raise Error("E_VALIDATION", "the upper limit lies above the lower", {"path": "upper"})
        return {"type": "limits", "upper": opts["upper"], "lower": opts["lower"]}
    if kind == "fit":
        if not FIT.match(opts["fit"]):
            raise Error(
                "E_VALIDATION",
                "a fit is a hole class in capitals or a shaft class in small letters, and a "
                "grade: H7, g6, JS9",
                {"path": "fit"},
            )
        return {"type": "fit", "fit": opts["fit"], "show": opts.get("show") or "class"}
    return {"type": kind}


def _expected(spec: dict, value: float) -> dict:
    """What a numeric tolerance will read back as: its fields and the limits it allows."""
    kind = spec["type"]
    if kind == "plus_minus":
        return spec | {"upper": value + spec["plus"], "lower": value - spec["minus"]}
    if kind == "symmetric":
        return spec | {"upper": value + spec["value"], "lower": value - spec["value"]}
    return dict(spec)


def _close(a, b) -> bool:
    return isinstance(a, int | float) and isinstance(b, int | float) and abs(a - b) <= TOLERANCE_ABS


def _as_requested(spec: dict, read: dict | None) -> bool:
    read = read or {}
    if read.get("type") != spec["type"]:
        return False
    if spec["type"] == "fit":
        return read.get("fit") == spec["fit"] and read.get("shown") == spec["show"]
    return all(_close(read.get(k), v) for k, v in spec.items() if k != "type")


def _prepare_tolerance(opts: dict) -> dict:
    validate(opts["dimension"], REF, "dimension")
    return {"name": engine.model_name(opts["model"], ("prt", "asm")), "spec": _tolerance(opts)}


def _plan_tolerance(client: Client, opts: dict, pre: dict, *, pending_standard=None) -> engine.Plan:
    name, spec = pre["name"], pre["spec"]
    numeric = spec["type"] in ("plus_minus", "symmetric", "limits")
    if numeric:
        client.require_capability("numeric_tolerance_regeneration_readback", 1)
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    engine.store_directory(before, s)
    rows = _rows(client, name)["dimensions"]
    target = _target(rows, name, opts["dimension"])
    if numeric and (target.get("numeric_tolerance_table") or {}).get("complete") is not True:
        raise Error("E_VERIFY_INCOMPLETE", "numeric tolerance table ownership cannot be read")
    if target.get("reference"):
        raise Error(
            "E_VALIDATION",
            "a reference dimension reports geometry and takes no tolerance",
            {"dimension": target["name"], "_untrusted": ["dimension"]},
        )
    if opts.get("units"):
        _same_units(target, opts["units"])
    if spec["type"] == "fit" and before.get("tolerance_standard") != "iso":
        raise Error(
            "E_CONFLICT",
            "ISO fits come from the ISO/DIN tolerance standard's tables; the model is not in it",
            {
                "tolerance_standard": before.get("tolerance_standard"),
                "fix": f"creo-cli model set-tolerance-standard --model {name} --standard iso",
                "_untrusted": ["tolerance_standard"],
            },
        )
    expected = _expected(spec, target["value"])
    unstable = [
        d["name"]
        for d in rows
        if d["id"] != target["id"]
        and (d.get("tolerance") or {}).get("type") in ("plus_minus", "symmetric", "limits")
        and (d.get("numeric_tolerance_table") or {}).get("assigned") is True
    ]
    if pending_standard:
        frozen = pending_standard.get("numeric_overrides", [])
        current = [
            d
            for d in rows
            if (d.get("tolerance") or {}).get("type") in ("plus_minus", "symmetric", "limits")
        ]
        if (
            not numeric
            or pending_standard.get("model") != name
            or current != frozen
            or any(
                (d.get("numeric_tolerance_table") or {}).get("complete") is not True for d in frozen
            )
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "workflow standard prerequisite does not match the current numeric overrides",
            )
    if numeric and unstable and not pending_standard:
        raise Error(
            "E_CONFLICT",
            "other numeric tolerances remain table-driven; regeneration may change them",
            {
                "dimensions": unstable,
                "next_action": "preview model set-tolerance-standard with the current mode/class "
                "to preserve and detach its numeric overrides first",
            },
        )
    old = building.features_of(client, name)

    def verify(c: Client, data: dict):
        now = next((d for d in _rows(c, name)["dimensions"] if d["id"] == target["id"]), {})
        after = {f["id"]: f for f in building.features_of(c, name)}
        read = now.get("tolerance")
        table = now.get("numeric_tolerance_table") or {}
        table_checks = (
            [
                engine.check(
                    "explicit_numeric_tolerance_not_table_driven",
                    table.get("complete") is True and table.get("assigned") is False,
                    observed=table,
                )
            ]
            if numeric
            else []
        )
        return data, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check(
                    "tolerance_as_requested", _as_requested(expected, read), tolerance=read
                ),
                engine.check(
                    "value_unchanged",
                    _close(now.get("value"), target["value"]),
                    value=now.get("value"),
                ),
                engine.check(
                    "every_feature_still_regenerates",
                    all(f["id"] in after and after[f["id"]]["status"] == f["status"] for f in old),
                ),
            ]
            + table_checks,
            "observations": [
                {
                    "observation": "limits",
                    "upper": (read or {}).get("upper"),
                    "lower": (read or {}).get("lower"),
                },
                {"observation": "tolerance_decimals", "places": data.get("tolerance_decimals")},
            ],
            "not_checked": ["how_a_drawing_letters_it"],
        }

    return engine.Plan(
        op="dimension.tolerance",
        request={"model": name, "dimension": target["id"], "tolerance": spec},
        target=name,
        binding={"model": before, "dimension": target, "features": old},
        preview={
            "command": "dimension tolerance",
            "model": name,
            "dimension": target,
            "from": target.get("tolerance"),
            "to": expected,
            "numeric_table_reference": target.get("numeric_tolerance_table") if numeric else None,
            "workflow_prerequisite": pending_standard,
            "numeric_effect": "detach the selected ISO table reference, set explicit limits, "
            "regenerate and independently inspect"
            if numeric
            else None,
            "meaning": TOLERANCE_MEANING[spec["type"]],
            "effect": "the dimension's tolerance changes, and every drawing that shows the "
            "dimension shows it; the geometry does not change",
            "layout_feedback": "tolerance lettering can enlarge labels; inspect associated drawing "
            "text boxes before moving or exporting; leader intersections require "
            "rendered-page review",
        },
        verify=verify,
        observe=lambda c: [(d["id"], d.get("tolerance")) for d in _rows(c, name)["dimensions"]],
        before=[(d["id"], d.get("tolerance")) for d in rows],
        arguments={
            k: opts[k]
            for k in (
                "model",
                "dimension",
                "plus",
                "minus",
                "symmetric",
                "upper",
                "lower",
                "fit",
                "show",
                "basic",
                "nominal",
                "units",
            )
            if opts.get(k) is not None
        },
    )


def tolerance_dimension(opts: dict) -> dict:
    def planned(client, options, prepared):
        from ..engineering_properties import checked_plan

        result = _plan_tolerance(client, options, prepared)
        return checked_plan(client, result, target_dimension=result.request["dimension"])

    return engine.write("dimension tolerance", opts, _prepare_tolerance, planned)


def plan_workflow_tolerance(client, options, prepared, prerequisite):
    """Plan a numeric leaf with a retained prerequisite; never dispatch this plan."""
    from ..engineering_properties import checked_plan

    result = _plan_tolerance(client, options, prepared, pending_standard=prerequisite)
    return checked_plan(client, result, target_dimension=result.request["dimension"])


def _prepare_standard(opts: dict) -> dict:
    if opts.get("class") and opts["standard"] != "iso":
        raise Error(
            "E_USAGE", "a general tolerance class belongs to the ISO/DIN standard: --standard iso"
        )
    return {"name": engine.model_name(opts["model"], ("prt", "asm"))}


def _plan_standard(client: Client, opts: dict, pre: dict) -> engine.Plan:
    name = pre["name"]
    s = engine.session(client)
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    engine.store_directory(before, s)
    if before.get("tolerance_standard") is None:
        raise Error(
            "E_UNSUPPORTED",
            "a model's tolerance standard is read and set by the native library, which this Creo "
            "session has not loaded",
            {"fix": "register creo_cli_sketch.dll with the service (docs/SERVICE.md)"},
        )
    dimensions = _rows(client, name)["dimensions"]
    numeric_overrides = [
        d
        for d in dimensions
        if (d.get("tolerance") or {}).get("type") in ("plus_minus", "symmetric", "limits")
    ]
    if numeric_overrides:
        client.require_capability("tolerance_standard_numeric_preservation", 1)
        if any(
            (d.get("numeric_tolerance_table") or {}).get("complete") is not True
            for d in numeric_overrides
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE", "existing numeric tolerance table references are incomplete"
            )
    if opts["standard"] == "ansi" and any(
        (d.get("tolerance") or {}).get("type") == "fit" for d in dimensions
    ):
        raise Error("E_UNSUPPORTED", "ANSI transition cannot preserve existing ISO fits")
    old = building.features_of(client, name)
    volume = (before.get("mass_properties") or {}).get("volume")

    def verify(c: Client, data: dict):
        now = engine.show(c, name)
        after = {f["id"]: f for f in building.features_of(c, name)}
        volume_after = (now.get("mass_properties") or {}).get("volume")
        checks = [
            engine.check(
                "standard_as_requested",
                now.get("tolerance_standard") == opts["standard"],
                standard=now.get("tolerance_standard"),
            ),
            engine.check(
                "geometry_unchanged",
                volume is None
                or (
                    volume_after is not None
                    and math.isclose(volume_after, volume, rel_tol=1e-9, abs_tol=1e-9)
                ),
                volume_before=volume,
                volume_after=volume_after,
            ),
            engine.check(
                "every_feature_still_regenerates",
                all(f["id"] in after and after[f["id"]]["status"] == f["status"] for f in old),
            ),
        ]
        if opts.get("class"):
            checks.append(
                engine.check(
                    "class_as_requested",
                    now.get("tolerance_class") == opts["class"],
                    tolerance_class=now.get("tolerance_class"),
                )
            )
        return data, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "observations": [],
            "not_checked": ["how_a_drawing_letters_it"],
        }

    return engine.Plan(
        op="model.set-tolerance-standard",
        request={"model": name, "standard": opts["standard"]}
        | ({"class": opts["class"]} if opts.get("class") else {}),
        target=name,
        binding={"model": before, "features": old},
        preview={
            "command": "model set-tolerance-standard",
            "model": name,
            "standard": {"from": before.get("tolerance_standard"), "to": opts["standard"]},
            "class": {"from": before.get("tolerance_class"), "to": opts.get("class")},
            "numeric_overrides_preserved": numeric_overrides,
            "effect": "ISO/DIN makes ISO fits (H7, g6) available and gives every dimension "
            "without a tolerance of its own the ISO 2768 general tolerance of its class; the model "
            "regenerates and its geometry does not change",
        },
        verify=verify,
        observe=lambda c: [
            engine.show(c, name).get(k) for k in ("tolerance_standard", "tolerance_class")
        ],
        before=[before.get(k) for k in ("tolerance_standard", "tolerance_class")],
        arguments={k: opts[k] for k in ("model", "standard", "class") if opts.get(k) is not None},
    )


def set_tolerance_standard(opts: dict) -> dict:
    def planned(client, options, prepared):
        from ..engineering_properties import checked_plan

        return checked_plan(client, _plan_standard(client, options, prepared))

    return engine.write("model set-tolerance-standard", opts, _prepare_standard, planned)


ROW = shape(
    {
        "id": S,
        "name": S,
        "value": N,
        "units": {"type": ["string", "null"]},
        "type": S,
        "feature": {"type": ["object", "null"]},
        "relation_driven": B,
        "reference": B,
        "in_sketch": {"type": ["boolean", "null"]},
        "measures": NS,
        "text": array(S),
        "tolerance": {"type": ["object", "null"]},
        "numeric_tolerance_table": {"type": ["object", "null"]},
    },
    ("id", "name", "value", "units", "type"),
)
HELD = array(
    shape(
        {"feature": {"type": ["object", "null"]}, "held": S, "between": array(S)},
        ("held", "between"),
    )
)
COMMANDS = [
    Command(
        "dimension list",
        "The dimensions of the features a person sees, or of one feature: name, value, units, "
        "kind, owner, and whether it lives in the feature's sketch or is the feature's own "
        "(an extrusion's depth); for a sketch's, what it measures",
        list_dimensions,
        listing(ROW, model=S, units=UNITS, held_together=HELD),
        (
            MODEL,
            Param("feature", description="only this feature's dimensions (name or id)"),
            LIMIT,
            OFFSET,
        ),
        untrusted=("items", "model", "held_together"),
        example="--model block",
        service_ops=("dimension.list",),
        sort="feature order, then Creo's order within a feature",
    ),
    Command(
        "dimension set",
        "Change one dimension and regenerate; a value the model cannot take is backed out",
        set_dimension,
        written(
            shape(
                {
                    "model": S,
                    "units": UNITS,
                    "dimension": ROW,
                    "value_before": N,
                    "volume": shape({"before": NN, "after": NN, "change": NN}, ()),
                },
                ("model", "dimension"),
            )
        ),
        (
            MODEL,
            Param("dimension", required=True, description="the dimension's name (d4) or id"),
            Param("value", "number", required=True, description="the new value"),
            Param(
                "units",
                required=True,
                choices=UNITS_FOR,
                description="the unit the value is in: the model's length unit, or deg",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model block --dimension d12 --value 8 --units mm",
        service_ops=("dimension.list", "dimension.set"),
    ),
    Command(
        "dimension tolerance",
        "Give one dimension its tolerance: plus and minus, symmetric, limits, an ISO fit (H7, "
        "g6), basic, or none; drawings that show it follow",
        tolerance_dimension,
        written(
            shape(
                {
                    "model": S,
                    "units": UNITS,
                    "dimension": ROW,
                    "tolerance_before": {"type": ["object", "null"]},
                    "tolerance_decimals": {"type": ["integer", "null"]},
                },
                ("model", "dimension"),
            )
        ),
        (
            MODEL,
            Param("dimension", required=True, description="the dimension's name (d4) or id"),
            Param("plus", "number", description="with --minus: the upper deviation, +0.1 is 0.1"),
            Param("minus", "number", description="with --plus: the lower deviation, -0.05 is 0.05"),
            Param("symmetric", "number", description="+- this much"),
            Param("upper", "number", description="with --lower: the upper limit itself"),
            Param("lower", "number", description="with --upper: the lower limit itself"),
            Param(
                "fit",
                description="an ISO 286 class and grade: capitals for a hole (H7), small letters "
                "for a shaft (g6); the model must be in the ISO/DIN standard",
            ),
            Param(
                "show",
                choices=("class", "deviations", "limits"),
                description="how a fit is shown: H7 (class, the default), H7 (+0.021/0), or "
                "H7 (20.021/20.000)",
            ),
            Param(
                "basic",
                "boolean",
                description="the exact value a geometric tolerance is measured from",
            ),
            Param("nominal", "boolean", description="no tolerance of its own"),
            Param(
                "units",
                choices=UNITS_FOR,
                description="with a tolerance in numbers: the dimension's unit, or deg",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model shaft --dimension d4 --fit g6",
        service_ops=("dimension.list", "dimension.tolerance"),
    ),
    Command(
        "model set-tolerance-standard",
        "Put a part or assembly in the ANSI or the ISO/DIN tolerance standard -- ISO fits need "
        "ISO/DIN -- and give it an ISO 2768 general tolerance class",
        set_tolerance_standard,
        written(
            shape(
                {
                    "model": S,
                    "standard": NS,
                    "standard_before": NS,
                    "class": NS,
                    "class_before": NS,
                    "volume": shape({"before": NN, "after": NN, "change": NN}, ()),
                },
                ("model", "standard"),
            )
        ),
        (
            MODEL,
            Param(
                "standard",
                required=True,
                choices=("ansi", "iso"),
                description="the tolerance standard",
            ),
            Param(
                "class",
                choices=("fine", "medium", "coarse", "very_coarse"),
                description="ISO/DIN only: the general tolerance class, ISO 2768 f, m, c or v",
            ),
        ),
        write=True,
        untrusted=WRITTEN,
        example="--model shaft --standard iso --class medium",
        service_ops=("model.show", "model.set-tolerance-standard"),
    ),
]
