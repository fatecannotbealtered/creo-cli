"""What every feature-building command shares: the reading it plans against, and the checks it
reads back afterwards.

A feature is planned against the part as it is now -- its length unit, its tree, the
geometry the request names -- and the token is bound to that reading. After Creo builds it,
the new feature is read back: active, of the kind asked for, under the name asked for, and
every feature that was there before still there in the same state.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import engine, native_read_recovery
from .core import Error
from .transport import Client

UNIT_ALIASES = {
    "mm": "mm",
    "millimeter": "mm",
    "cm": "cm",
    "m": "m",
    "in": "in",
    "inch": "in",
    "ft": "ft",
    "foot": "ft",
}
# Relative disagreement tolerated before a volume is said not to match what the request
# implies. Creo holds an ellipse as a spline: the first live one measured 3e-6 away.
VOLUME_TOLERANCE = 1e-4
RESULT_KEYS = ("model", "units", "feature", "volume")
REFERENCE_FIELDS = (
    "ref",
    "kind",
    "type",
    "feature",
    "normal",
    "origin",
    "axis",
    "radius",
    "outward",
    "start",
    "end",
    "direction",
    "length",
    "area",
)


@dataclass
class Context:
    session: dict
    before: dict  # model show
    features: list  # the full tree, internal features included
    directory: Path  # where the part is stored back


def features_of(client: Client, name: str) -> list[dict]:
    return engine.normalize(client.op("feature.list", {"model": name, "include_internal": True}))[
        "features"
    ]


def check_units(model: dict, units: str) -> None:
    length = (model.get("units") or {}).get("length")
    if not isinstance(length, str) or not length:
        raise Error(
            "E_NATIVE_FAILURE",
            "Creo did not report the part's length unit, so the request's units cannot be checked",
        )
    if UNIT_ALIASES.get(length.strip().lower()) != units:
        raise Error(
            "E_CONFLICT",
            "the part's length unit is not the one the request states; nothing is converted",
            {
                "part_length_unit": length,
                "request_units": units,
                "_untrusted": ["part_length_unit"],
            },
        )


def context(client: Client, name: str, q: dict, *, units: bool = True) -> Context:
    s = engine.session(client)
    if not s["creation_api"]:
        raise Error(
            "E_BACKEND_UNAVAILABLE",
            "this Creo session offers no creation API, so features cannot be built",
            {
                "fix": "the service must run as an Object TOOLKIT Java application under the "
                "ObjectToolkitJava licence"
            },
        )
    engine.require_in_session(s, name)
    before = engine.show(client, name)
    directory = engine.store_directory(before, s)
    if units:
        check_units(before, q["units"])
    features = features_of(client, name)
    if q.get("name") and any(
        str(f.get("name") or "").upper() == q["name"].upper() for f in features
    ):
        raise Error(
            "E_CONFLICT",
            "the part already has a feature of that name",
            {"name": q["name"], "_untrusted": ["name"]},
        )
    return Context(s, before, features, directory)


def references(client: Client, name: str, refs: list[str]) -> dict[str, dict]:
    """Every reference the request names, as geometry list reports it. One that does not
    exist is refused here, before anything is sent to Creo."""
    if not refs:
        return {}
    described = engine.normalize(client.op("geometry.list", {"model": name}))
    if described.get("model") != name or not isinstance(described.get("items"), list):
        raise Error("E_VERIFY_INCOMPLETE", "geometry references could not be read completely")
    found = resolve_references(described["items"], refs)
    return {
        ref: {
            k: hit[k]
            for k in REFERENCE_FIELDS
            if k in hit and not (hit.get("kind") == "datum_plane" and k == "area")
        }
        for ref, hit in found.items()
    }


def reference_key(ref: str) -> str:
    """Case and numeric spelling do not change a native item's identity."""
    kind, colon, ident = ref.partition(":")
    if colon and kind.lower() in ("surface", "edge", "axis") and ident.isdecimal():
        return kind.lower() + ":" + str(int(ident))
    return ref.casefold()


def resolve_references(items: list[dict], refs: list[str]) -> dict[str, dict]:
    """Resolve only actually observed objects, including named datum/item-ID aliases."""
    by_ref = {}
    for item in items:
        aliases = [item["ref"]]
        kind = "surface" if item.get("kind") == "datum_plane" else item.get("kind")
        if kind in ("surface", "edge", "axis") and item.get("id") is not None:
            aliases.append(f"{kind}:{item['id']}")
        for alias in aliases:
            key = reference_key(alias)
            if key in by_ref and by_ref[key] != item:
                raise Error(
                    "E_VERIFY_INCOMPLETE",
                    "native geometry reference is ambiguous",
                    {"reference": alias},
                )
            by_ref[key] = item
    out = {}
    for ref in refs:
        hit = by_ref.get(reference_key(ref))
        if hit is None:
            raise Error(
                "E_NOT_FOUND",
                "the request names geometry the part does not have",
                {
                    "reference": ref,
                    "fix": "read geometry list for the actual target model",
                    "_untrusted": ["reference"],
                },
            )
        out[ref] = hit
    return out


def feature_by_ref(features: list[dict], wanted: str) -> dict:
    for f in features:
        if str(f.get("name") or "").upper() == wanted.upper() or f["id"] == wanted:
            return f
    raise Error(
        "E_NOT_FOUND",
        "no feature of that name or id in the part",
        {"feature": wanted, "_untrusted": ["feature"]},
    )


def matches(change: float | None, expected: float, tolerance: float = VOLUME_TOLERANCE) -> bool:
    return change is not None and abs(change - expected) <= tolerance * max(1.0, abs(expected))


def feature_name_intent(request: dict) -> dict:
    """Freeze whether the caller chose a name or left Creo's native name unchanged."""
    name = request.get("name")
    if name is None:
        return {"policy": "native_default", "name": None}
    return {"policy": "requested", "name": name}


def require_feature_name_intent(intent: Any) -> dict:
    """Missing historical intent is not evidence that the caller omitted a name."""
    if (
        not isinstance(intent, dict)
        or set(intent) != {"policy", "name"}
        or intent.get("policy") not in ("requested", "native_default")
        or (
            intent.get("policy") == "requested"
            and (not isinstance(intent.get("name"), str) or not intent["name"])
        )
        or (intent.get("policy") == "native_default" and intent.get("name") is not None)
    ):
        raise Error("E_VERIFY_INCOMPLETE", "explicit frozen feature-name intent is unavailable")
    return intent


def retained_feature_name_intent(run: dict, intent: dict) -> dict:
    """Require the retained policy to agree with the original frozen native request."""
    naming = require_feature_name_intent(intent.get("name_intent"))
    changes = (run.get("driver_plan") or {}).get("changes") or [{}]
    request = changes[0].get("after")
    if (
        not isinstance(request, dict)
        or request.get("model") != run.get("target")
        or feature_name_intent(request) != naming
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE", "frozen feature-name policy does not match its original request"
        )
    return naming


def feature_readback_checks(
    before_features: list[dict],
    after_features: list[dict],
    feature_id: str,
    expected_type: str,
    name_intent: dict,
) -> list[dict]:
    """Judge the new native feature row independently of the mutation's reply."""
    naming = require_feature_name_intent(name_intent)
    ident = str(feature_id) if feature_id is not None else None
    old_ids = {str(f["id"]) for f in before_features}
    matching = [f for f in after_features if ident is not None and str(f.get("id")) == ident]
    actual = matching[0] if len(matching) == 1 else {}
    checks = [
        engine.check("feature_in_part", len(matching) == 1),
        engine.check("independent_feature_added", len(matching) == 1 and ident not in old_ids),
        engine.check(
            "feature_active", actual.get("status") == "FEAT_ACTIVE", status=actual.get("status")
        ),
        engine.check(
            "feature_type_as_requested",
            actual.get("type") == expected_type,
            expected=expected_type,
            actual=actual.get("type"),
        ),
    ]
    observed = actual.get("name")
    present = "name" in actual
    if naming["policy"] == "requested":
        checks.append(
            engine.check(
                "feature_name_as_requested",
                present
                and isinstance(observed, str)
                and observed.casefold() == naming["name"].casefold(),
                expected=naming["name"],
                observed=observed,
                name_field_present=present,
            )
        )
    else:
        checks.append(
            engine.check(
                "feature_name_native_default",
                present and (observed is None or isinstance(observed, str)),
                policy="native_default",
                observed=observed,
                name_field_present=present,
            )
        )
    return checks


def plan(
    *,
    op: str,
    command: str,
    name: str,
    q: dict,
    ctx: Context,
    request: dict,
    preview: dict,
    expected_type: str,
    arguments: dict,
    expected_change: float | None = None,
    volume_meaning: str = "",
    exact_volume: bool = False,
    result_keys: tuple = (),
    extra_checks: Callable[[Client, dict], list] | None = None,
    extra_observations: Callable[[dict], list] | None = None,
    binding: Any = None,
    volume_tolerance: float = VOLUME_TOLERANCE,
) -> engine.Plan:
    """The plan every feature-building command confirms: its preview, its token binding, and
    the read-back that says whether Creo built what was asked."""
    before_rows = {f["id"]: f for f in ctx.features}
    naming = feature_name_intent(q)

    def verify(c: Client, data: dict):
        feature = data["feature"]
        result = {k: data[k] for k in (*RESULT_KEYS, *result_keys) if k in data}
        change = (data.get("volume") or {}).get("change")
        checks = [
            engine.check(
                "feature_active",
                feature.get("status") == "FEAT_ACTIVE",
                status=feature.get("status"),
            ),
            engine.check(
                "feature_type_as_requested",
                feature.get("type") == expected_type,
                expected=expected_type,
                actual=feature.get("type"),
            ),
        ]
        if q.get("name"):
            checks.append(
                engine.check(
                    "feature_name_as_requested",
                    str(feature.get("name") or "").upper() == q["name"].upper(),
                )
            )
        observations = []
        if expected_change is not None:
            result["volume"] = dict(result["volume"]) | {
                "expected_change": expected_change,
                "matches_request": matches(change, expected_change, volume_tolerance),
            }
            if exact_volume:
                checks.append(
                    engine.check(
                        "volume_change_as_expected",
                        matches(change, expected_change, volume_tolerance),
                        change=change,
                        expected_change=expected_change,
                    )
                )
            else:
                observations.append(
                    {
                        "observation": "volume",
                        "change": change,
                        "expected_change": expected_change,
                        "matches_request": matches(change, expected_change, volume_tolerance),
                        "meaning": volume_meaning,
                    }
                )
        if extra_observations:
            observations += extra_observations(data)
        try:
            after_features = features_of(c, name)
            after = {f["id"]: f for f in after_features}
            units_after = engine.show(c, name).get("units")
        except Error as exc:
            # The checks so far rest on the service's own reply; nothing was read back.
            observations.append(
                {
                    "observation": "independent_read_back_failed",
                    "code": exc.code,
                    "error": native_read_recovery.error_record(exc),
                }
            )
            return result, {
                "level": "service_reply_only",
                "status": "incomplete",
                "checks": checks,
                "observations": observations,
                "not_checked": [
                    "feature_in_part",
                    "independent_feature_added",
                    "feature_active",
                    "feature_type_as_requested",
                    "feature_name_as_requested"
                    if naming["policy"] == "requested"
                    else "feature_name_native_default",
                    "existing_features_unchanged",
                    "units_unchanged",
                ],
            }
        independent = feature_readback_checks(
            ctx.features, after_features, feature.get("id"), expected_type, naming
        )
        reply_checks = {c["check"]: c for c in checks}
        checks = []
        for check in independent:
            reply = reply_checks.pop(check["check"], None)
            if reply is not None:
                check["service_reply_passed"] = reply["passed"]
                check["passed"] = check["passed"] and reply["passed"]
            checks.append(check)
        checks += list(reply_checks.values())
        checks += [
            engine.check(
                "existing_features_unchanged",
                all(
                    i in after and after[i]["status"] == f["status"] for i, f in before_rows.items()
                ),
            ),
            engine.check("units_unchanged", units_after == ctx.before.get("units")),
        ]
        if extra_checks:
            checks += extra_checks(c, data)
        observations.append(
            {
                "observation": "new_features",
                "features": [f for i, f in after.items() if i not in before_rows],
            }
        )
        return result, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "observations": observations,
            "not_checked": ["design_intent"],
        }

    return engine.Plan(
        op=op,
        request=request,
        target=name,
        binding={
            "model": ctx.before,
            "features": ctx.features,
            "name_intent": naming,
            "store_directory": str(ctx.directory),
            "extra": binding,
        },
        preview={"command": command, "model": name, "units": ctx.before.get("units")}
        | preview
        | {
            "name_intent": naming,
            "part_now": {
                "volume": (ctx.before.get("mass_properties") or {}).get("volume"),
                "features": ctx.before.get("feature_count"),
                "unsaved_changes": ctx.before.get("modified"),
            },
            "saves_to_disk": False,
        },
        verify=verify,
        observe=lambda c: {
            "model": _settled(engine.show(c, name)),
            "features": features_of(c, name),
        },
        before={"model": _settled(ctx.before), "features": ctx.features},
        arguments=arguments,
    )


def _settled(shown: dict) -> dict:
    """A part as a failed write is judged by: whether it holds unsaved changes is left out. A
    feature Creo made and the service deleted again leaves the part marked modified with
    nothing in it changed (measured: a rib that would not close), which is not a change to
    acknowledge."""
    return {k: v for k, v in shown.items() if k != "modified"}


def distance_along(origin: list, normal: list, point: list) -> float:
    return sum((p - o) * n for p, o, n in zip(point, origin, normal, strict=True))


def parallel(a: list, b: list) -> bool:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    return math.isclose(abs(dot), 1.0, abs_tol=1e-6)
