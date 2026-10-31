"""Complete observed display state; no inferred restoration or automatic recovery."""

import copy
import math
import re

from .core import Error

ASSEMBLY_CONTEXT_SOURCE = (
    "Session.GetCurrentModel/GetCurrentWindow; Window.GetModel; Model.GetType/GetFileName"
)


def _native_window_id(value):
    # Window.GetId is a Java int; this profile admits nonnegative actual window IDs.
    # The producer uses String.valueOf, so Boolean/integer/default/placeholder inputs
    # are not native identity evidence. Window zero is valid, not an absence sentinel.
    return (
        isinstance(value, str)
        and re.fullmatch(r"0|[1-9][0-9]{0,9}", value) is not None
        and int(value) <= 2147483647
    )


def numbers(values, size):
    return (
        isinstance(values, list)
        and len(values) == size
        and all(type(x) in (int, float) and math.isfinite(x) for x in values)
    )


def equivalent(a, b):
    if type(a) in (int, float) and type(b) in (int, float):
        return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-8)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equivalent(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equivalent(x, y) for x, y in zip(a, b, strict=True))
    return type(a) is type(b) and a == b


def _display_context(data, *, drawing_inventory=False):
    context, display = data.get("context"), data.get("display_readback")
    if not isinstance(context, dict) or not isinstance(display, dict):
        raise Error("E_VERIFY_INCOMPLETE", "explosion display context provenance is missing")
    current, window = context.get("current_model"), context.get("window_model")
    common = (
        context.get("complete") is True
        and "error" not in context
        and isinstance(current, str)
        and current == window
        and context.get("current_model_type") == context.get("window_model_type")
        and _native_window_id(context.get("window_id"))
        and context.get("source") == ASSEMBLY_CONTEXT_SOURCE
        and display.get("source") == "Assembly.GetIsExploded"
        and "error" not in display
    )
    if (
        common
        and context.get("kind") == "assembly"
        and context.get("assembly_context_admitted") is True
        and current == context.get("target_model")
        and context.get("current_model_type") == "assembly"
        and display.get("complete") is True
        and display.get("status") == "observed"
        and type(display.get("value")) is bool
        and display["value"] is data.get("is_exploded")
    ):
        return
    if (
        drawing_inventory
        and common
        and context.get("kind") == "drawing"
        and context.get("assembly_context_admitted") is False
        and context.get("current_model_type") == "drawing"
        and current.lower().endswith(".drw")
        and display.get("complete") is False
        and display.get("status") == "not_checked"
        and display.get("reason") == "not_applicable_in_drawing_context; GetIsExploded not called"
        and display.get("value") is None
        and data.get("is_exploded") is None
    ):
        return
    raise Error(
        "E_VERIFY_INCOMPLETE",
        "matching assembly display context or explicit drawing inventory context is required",
        {"context": context, "display_readback": display},
    )


def explosion(model, *, drawing_inventory=False):
    data = model.get("explosion")
    if not isinstance(data, dict) or data.get("complete") is not True or "error" in data:
        raise Error("E_VERIFY_INCOMPLETE", "complete explosion/display state is required")
    states = data.get("states")
    _display_context(data, drawing_inventory=drawing_inventory)
    if model.get("model") is not None and data["context"].get("target_model") != model["model"]:
        raise Error("E_VERIFY_INCOMPLETE", "explosion context belongs to another target model")
    if not isinstance(states, list):
        raise Error("E_VERIFY_INCOMPLETE", "explosion state inventory unreadable")
    if any(
        not isinstance(s, dict) or type(s.get("id")) not in (str, int) or not str(s["id"])
        for s in states
    ) or len({str(s["id"]) for s in states}) != len(states):
        raise Error("E_VERIFY_INCOMPLETE", "explosion state IDs are not unique")
    for state in states:
        if (
            state.get("id") is None
            or not isinstance(state.get("name"), str)
            or not state["name"]
            or type(state.get("active")) is not bool
            or type(state.get("is_default")) is not bool
        ):
            raise Error("E_VERIFY_INCOMPLETE", "explosion identity or active state unreadable")
        moves = state.get("moves")
        if not isinstance(moves, list):
            raise Error("E_VERIFY_INCOMPLETE", "explosion moves could not be read")
        for move in moves:
            if (
                not isinstance(move, dict)
                or not isinstance(move.get("type"), str)
                or not isinstance(move.get("components"), list)
                or not move["components"]
                or not numbers(move.get("direction"), 3)
                or not numbers([move.get("distance")], 1)
                or not isinstance(move.get("component_paths"), list)
                or len(move["component_paths"]) != len(move["components"])
                or any(
                    not isinstance(path, list) or not path or str(path[-1]) != str(component)
                    for path, component in zip(
                        move["component_paths"], move["components"], strict=True
                    )
                )
            ):
                raise Error("E_VERIFY_INCOMPLETE", "full explosion move references/vector required")
    active = [s for s in states if s["active"]]
    expected = None if not active else str(active[0]["id"])
    if len(active) > 1 or data.get("active_state_id") != expected:
        raise Error("E_VERIFY_INCOMPLETE", "active explosion and inventory disagree")
    return data


def drawing_source(model):
    """Protection projection: exclude only context-dependent global display evidence.

    Original before/after snapshots remain separate evidence. All engineering fields,
    both state inventories, active/default IDs, component transforms and constraints
    remain exact. This is not normal-placement derivation or per-view state identity.
    """
    explosion(model, drawing_inventory=True)
    projected = copy.deepcopy(model)
    for key in ("is_exploded", "context", "display_readback"):
        projected["explosion"].pop(key, None)
    return projected


def normal_components(components, state):
    """Mathematical derivation from recorded origins, not actual normal placement proof.

    ComponentFeat.GetPosition is initial placement, which constraints may override.
    ComponentPath.GetTransform(true) maps the member to the root; the inspected API
    does not establish cross-display invariance. Subtracting direct translations
    from those recorded origins is only a consistency calculation. Independent
    actual normal placement requires matching non-exploded assembly-context native
    observations. The context gate below continues to reject drawing-mode input.
    """
    explosion({"explosion": state})
    rows = copy.deepcopy(components)
    if not state["is_exploded"]:
        return rows
    active = next((s for s in state["states"] if s["active"]), None)
    if active is None:
        raise Error("E_VERIFY_INCOMPLETE", "exploded display has no readable active state")
    by_id = {str(row["id"]): row for row in rows}
    seen = set()
    for move in active["moves"]:
        if move["type"] != "translate" or any(len(path) != 1 for path in move["component_paths"]):
            raise Error("E_UNSUPPORTED", "normal placement requires direct translation moves")
        if not math.isclose(math.hypot(*move["direction"]), 1, rel_tol=1e-9, abs_tol=1e-9):
            raise Error("E_VERIFY_INCOMPLETE", "native translation direction is not a unit vector")
        for ident in map(str, move["components"]):
            if ident not in by_id or ident in seen:
                raise Error("E_VERIFY_INCOMPLETE", "ambiguous explosion occurrence reference")
            seen.add(ident)
            for key in ("position", "component_path_transform"):
                if key not in by_id[ident]:
                    continue
                transform = by_id[ident][key]
                if not isinstance(transform, dict) or not numbers(transform.get("origin"), 3):
                    raise Error("E_VERIFY_INCOMPLETE", "component transform cannot be interpreted")
                transform["origin"] = [
                    x - direction * move["distance"]
                    for x, direction in zip(transform["origin"], move["direction"], strict=True)
                ]
    return rows


def render_state(client, model):
    from . import appearance, engine

    client.require_capability("render_state_restoration", 3)
    data = engine.normalize(client.op("model.render-state", {"model": model}))
    matrix = data.get("view_transform")
    screen = data.get("screen") or {}
    datums = data.get("datums") or {}
    if (
        data.get("complete") is not True
        or data.get("model") != model
        or data.get("window") is None
        or data.get("active_window") is None
        or not isinstance(data.get("active_model"), str)
        or not data["active_model"].lower().endswith((".prt", ".asm"))
        or type(data.get("modified")) is not bool
        or not isinstance(matrix, list)
        or len(matrix) != 4
        or not all(numbers(row, 4) for row in matrix)
        or not numbers([screen.get(k) for k in ("pan_x", "pan_y", "zoom")], 3)
        or set(datums) != {"display_planes", "display_axes", "display_points", "display_coord_sys"}
        or any(not isinstance(v, str) or not v for v in datums.values())
        or data.get("context_complete") is not True
        or not isinstance(data.get("current_model"), str)
        or data["current_model"].lower() != model
        or not isinstance(data.get("window_model"), str)
        or data["window_model"].lower() != model
        or data.get("current_model_type") != ("assembly" if model.endswith(".asm") else "part")
        or data.get("window_model_type") != data.get("current_model_type")
    ):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "complete render view/window/config state required",
            {"observed": data},
        )
    if model.endswith(".asm"):
        explosion({"explosion": data.get("explosion")})
    colors = data.get("native_part_appearances")
    expected = {name for name in engine.session(client)["models"] if name.endswith(".prt")}
    if not isinstance(colors, dict) or set(colors) != expected:
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "render requires complete actual source appearance readback for every session part",
            {
                "expected_models": sorted(expected),
                "observed_models": sorted(colors) if isinstance(colors, dict) else None,
            },
        )
    for name, native in colors.items():
        appearance.validate_color_state(native, name)
    return data


def settled_render_state(client, model):
    """At most three independent reads; require two consecutive complete equal states.

    Creo's raster export can return before its display update becomes observable.
    This is observation only: no write, retry, restoration or changed comparison rule.
    A missing getter still fails immediately, and a stable wrong state remains wrong.
    """
    samples = []
    for _ in range(3):
        samples.append(render_state(client, model))
        if len(samples) >= 2 and equivalent(samples[-2], samples[-1]):
            return samples[-1], samples
    raise Error(
        "E_VERIFY_INCOMPLETE",
        "render state did not settle within three independent observations",
        {"observations": samples, "write_replayed": False},
    )
