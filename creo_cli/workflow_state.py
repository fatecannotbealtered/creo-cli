"""Observed workflow file transitions and final per-object persistence, not replay."""

from copy import deepcopy
from pathlib import Path

from . import driver, engine, paths, safety, timing
from .core import Error, decode, digest, read_bytes, request_path


def _file_input(path):
    """One bounded stable byte read; material inputs are not JSON requests."""
    source = request_path(path).absolute()
    try:
        before = source.stat()
        raw = read_bytes(source)
        after = source.stat()
    except FileNotFoundError as exc:
        raise Error(
            "E_NOT_FOUND",
            "request file disappeared before a stable read",
            {"path": str(source), "_untrusted": ["path"]},
        ) from exc
    except OSError as exc:
        raise Error(
            "E_IO",
            "request file cannot be inspected",
            {"path": str(source), "_untrusted": ["path"]},
        ) from exc

    def stamp(s):
        return (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)

    if stamp(before) != stamp(after):
        raise Error(
            "E_CONFLICT", "request file changed while being read", {"conflict": "state_drift"}
        )
    import hashlib

    return {
        "path": str(source),
        "resolved_path": str(source.resolve()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "size_bytes": len(raw),
        "file_identity": list(stamp(after)),
    }, raw


def file_input(path):
    return _file_input(path)[0]


def request_file(path):
    metadata, raw = _file_input(path)
    return metadata | {"content": decode(raw)}


def locations(client, nodes, outputs, inputs=None):
    session = engine.session(client)
    return {
        "models": {
            n["identity"]: str(engine.store_directory(n["description"], session)) for n in nodes
        },
        "outputs": sorted({o["path"] for o in outputs if o.get("exists") is not True}),
        "inputs": sorted(inputs or []),
    }


@timing.phase("state_read")
def files(where):
    inputs = {}
    for path in where.get("inputs", []):
        try:
            inputs[path] = file_input(path)
        except (Error, OSError) as exc:
            inputs[path] = {"path": path, "unavailable": getattr(exc, "code", type(exc).__name__)}
    return {
        "inputs": inputs,
        "models": {
            name: paths.model_files(Path(directory), name)
            for name, directory in where["models"].items()
        },
        "outputs": {
            p: paths.artifact(Path(p)) if Path(p).exists() else None for p in where["outputs"]
        },
        "configuration": {
            "scope": driver.scope().record,
            "policy": safety.policy(),
            "workspace": str(paths.workspace()),
        },
    }


def require_files(expected, observed):
    if digest(expected) != digest(observed):
        raise Error(
            "E_CONFLICT",
            "workflow file inputs or configuration drifted",
            {
                "conflict": "state_drift",
                "dispatch_state": "not_started",
                "expected_sha256": digest(expected),
                "observed_sha256": digest(observed),
            },
        )


def advance_files(expected, observed, command, receipt):
    """Only add a verified, exactly identified artifact; retain every previous hash."""
    allowed = deepcopy(expected)
    if command == "model save" and receipt["outcome"]["persistence"] == "saved":
        name = receipt["target"]["object_id"]
        old = expected["models"][name]
        new = [v for v in observed["models"][name] if v["path"] not in {v["path"] for v in old}]
        artifacts = receipt["artifacts"]
        if len(new) == len(artifacts) == 1 and all(
            new[0][k] == artifacts[0][k] for k in ("path", "sha256")
        ):
            allowed["models"][name] = old + new
            if new[0]["path"] in allowed["outputs"] and allowed["outputs"][new[0]["path"]] is None:
                allowed["outputs"][new[0]["path"]] = new[0]
    elif command == "artifact export":
        for artifact in receipt["artifacts"]:
            path = artifact["path"]
            current = observed["outputs"].get(path)
            if (
                path in allowed["outputs"]
                and allowed["outputs"][path] is None
                and current
                and current["sha256"] == artifact["sha256"]
            ):
                allowed["outputs"][path] = current
    # Request bytes are never rebased by a domain write. Check the next boundary,
    # keeping the just-completed leaf's success and original input fingerprints.
    require_files(allowed, observed | {"inputs": expected.get("inputs", {})})
    return allowed


def persistence(run, rows):
    """Aggregate in order, keeping partial/unknown evidence even if later steps saved."""
    initial = run.get("workflow_initial_models", {})
    final = run.get("workflow_final_models", {})
    states, evidence = {}, {}
    partial = False
    unfulfilled_save = False
    for row in rows:
        context = row.get("extensions", {}).get("creo", {})
        if context.get("command") == "model save" and context.get("target"):
            name = context["target"]
            states.setdefault(
                name, "unsaved" if initial.get(name, {}).get("modified") is True else "unchanged"
            )
            evidence.setdefault(name, [])
            if not row.get("receipt") or row["receipt"]["outcome"]["persistence"] != "saved":
                unfulfilled_save = True
    for row in rows:
        receipt = row.get("receipt")
        if not receipt or not set(receipt["effects"]) & {"change", "persist"}:
            continue
        name = receipt["target"]["object_id"]
        outcome = receipt["outcome"]
        state = states.setdefault(
            name, "unsaved" if initial.get(name, {}).get("modified") is True else "unchanged"
        )
        evidence.setdefault(name, []).append(receipt["operation_id"])
        if outcome["persistence"] == "unknown" or outcome["change"] == "unknown":
            states[name] = "unknown"
        elif outcome["persistence"] == "partial":
            states[name] = "partial"
            partial = True
        elif "persist" in receipt["effects"] and outcome["persistence"] == "saved":
            states[name] = "saved" if state != "unknown" else "unknown"
        elif outcome["change"] in ("applied", "partial"):
            states[name] = "unsaved" if state not in ("unknown", "partial") else state
        elif outcome["persistence"] == "unsaved" and state not in ("unknown", "partial"):
            states[name] = "unsaved"
    for name, state in list(states.items()):
        modified = final.get(name, {}).get("modified")
        object_receipts = [
            r["receipt"]
            for r in rows
            if r.get("receipt") and r["receipt"]["target"]["object_id"] == name
        ]
        no_changes = all(r["outcome"]["change"] == "not_applied" for r in object_receipts)
        if state not in ("unknown", "partial") and modified is True:
            states[name] = "unsaved"
        elif (
            state == "unsaved"
            and modified is False
            and no_changes
            and initial.get(name, {}).get("modified") is False
        ):
            states[name] = (
                "saved"
                if any(r["outcome"]["persistence"] == "saved" for r in object_receipts)
                else "unchanged"
            )
        elif state == "saved":
            states[name] = (
                "unsaved" if modified is True else "saved" if modified is False else "unknown"
            )
        elif state not in ("unknown", "partial") and modified is not False:
            states[name] = "unknown"
    values = set(states.values())
    overall = (
        "unknown"
        if "unknown" in values
        else "partial"
        if partial
        or "partial" in values
        or {"saved", "unsaved"} <= values
        or unfulfilled_save
        and "saved" in values
        else "unsaved"
        if "unsaved" in values
        else "saved"
        if "saved" in values
        else "unchanged"
        if values
        else "not_applicable"
    )
    return overall, [
        {
            "object_id": name,
            "state": state,
            "modified": final.get(name, {}).get("modified"),
            "evidence_refs": ["operation:" + ident for ident in evidence[name]],
        }
        for name, state in sorted(states.items())
    ]
