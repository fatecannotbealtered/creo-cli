"""One invocation budget and bounded, payload-free phase measurements."""

import contextvars
import time
from contextlib import contextmanager
from copy import deepcopy

from . import execution_budgets

_deadline = contextvars.ContextVar("command_deadline", default=None)
_measurement = contextvars.ContextVar("command_measurement", default=None)
_execution_profile = contextvars.ContextVar("execution_profile", default=None)


def execution_profile():
    return deepcopy(_execution_profile.get())


def deadline(timeout):
    own = time.monotonic() + timeout
    parent = _deadline.get()
    return min(own, parent) if parent is not None else own


@contextmanager
def command(name, seconds):
    selected = execution_budgets.selected(name, seconds)
    parent_profile = _execution_profile.get()
    # A nested leaf cannot expand an ordinary parent invocation's native wait cap.
    if _deadline.get() is not None:
        selected = parent_profile
    profile_token = _execution_profile.set(selected)
    started = time.monotonic()
    budget = _deadline.set(deadline(seconds))
    meter = {"started": started, "seconds": seconds, "stages": {}, "rpc": {}, "stack": []}
    marker = _measurement.set(meter)
    try:
        yield
    finally:
        _measurement.reset(marker)
        _deadline.reset(budget)
        _execution_profile.reset(profile_token)


@contextmanager
def phase(name):
    meter = _measurement.get()
    if meter is None:
        yield
        return
    row = {"name": name, "started": time.monotonic(), "children": 0.0}
    meter["stack"].append(row)
    try:
        yield
    finally:
        elapsed = time.monotonic() - row["started"]
        meter["stack"].pop()
        if meter["stack"]:
            meter["stack"][-1]["children"] += elapsed
        total = meter["stages"].setdefault(name, {"calls": 0, "seconds": 0.0, "self_seconds": 0.0})
        total["calls"] += 1
        total["seconds"] += elapsed
        total["self_seconds"] += max(0.0, elapsed - row["children"])


def runtime_startup(seconds):
    """Measure main-entry parsing/import time; excludes the external frozen bootloader."""
    meter = _measurement.get()
    if meter is not None:
        seconds = max(0.0, seconds)
        meter["stages"]["startup"] = {"calls": 1, "seconds": seconds, "self_seconds": seconds}


@contextmanager
def rpc(name, write):
    kind = (
        "export"
        if name in ("model.export", "model.render")
        else "native_execution"
        if write
        else "state_read"
    )
    started = time.monotonic()
    with phase(kind):
        try:
            yield
        finally:
            meter = _measurement.get()
            if meter is not None:
                key = (name, write)
                total = meter["rpc"].setdefault(key, {"count": 0, "seconds": 0.0})
                total["count"] += 1
                total["seconds"] += time.monotonic() - started


def report():
    meter = _measurement.get()
    if meter is None:
        return None
    now = time.monotonic()
    stages = {name: dict(values) for name, values in meter["stages"].items()}
    for name in (
        "startup",
        "observation",
        "identity_resolution",
        "history_read",
        "dependency_scan",
        "planning",
        "state_read",
        "native_execution",
        "verification",
        "record_write",
        "export",
    ):
        stages.setdefault(name, {"calls": 0, "seconds": 0.0, "self_seconds": 0.0})
    for index, row in enumerate(meter["stack"]):
        child = now - meter["stack"][index + 1]["started"] if index + 1 < len(meter["stack"]) else 0
        elapsed = now - row["started"]
        total = stages.setdefault(row["name"], {"calls": 0, "seconds": 0.0, "self_seconds": 0.0})
        total["calls"] += 1
        total["seconds"] += elapsed
        total["self_seconds"] += max(0.0, elapsed - row["children"] - child)
    return {
        "scope": "current CLI invocation, cumulative through this observation",
        "budget_seconds": meter["seconds"],
        "elapsed_seconds": round(time.monotonic() - meter["started"], 6),
        "remaining_seconds": round(max(0.0, _deadline.get() - time.monotonic()), 6),
        "stages": {
            name: {key: round(value, 6) for key, value in values.items()}
            for name, values in sorted(stages.items())
        },
        "rpc": [
            {
                "operation": name,
                "write": write,
                "count": values["count"],
                "seconds": round(values["seconds"], 6),
            }
            for (name, write), values in sorted(meter["rpc"].items())
        ],
        "limits": [
            "stage seconds are inclusive; self_seconds exclude instrumented child stages",
            "calls count instrumented routines, not physical disk syscalls; "
            "active stages are sampled to date",
            "RPC seconds include queue, transport and service time; they are not native CPU time",
            "a retained report precedes its own final record commit; "
            "envelope duration includes return preparation",
            "deadlines do not cancel a native operation that has already started",
            "startup measures CLI main-entry setup; external frozen bootloader and CAD cold "
            "startup are measured by the launcher, not included here",
        ],
    }


def stamp(value):
    measured = report()
    if measured is not None:
        value.setdefault("extensions", {}).setdefault("creo", {})["timing"] = measured
    return value
