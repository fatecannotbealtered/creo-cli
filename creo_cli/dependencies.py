"""One bounded dependency closure shared by leaf preflight, public plans and workflows."""

from . import engine, object_identity, timing
from .core import Error, digest

MAX_MODELS = 1000
MAX_DEPTH = 32


def references(command, values):
    names = set()
    for field in ("model", "of", "component", "with"):
        value = values.get(field)
        if not value:
            continue
        # Occurrence selectors are IDs; their model comes from the assembly's closure.
        if field == "component" and str(value).isdigit():
            continue
        kinds = ("prt", "asm", "drw")
        if field == "model":
            if command.startswith("assembly "):
                kinds = ("asm",)
            elif command.startswith("drawing "):
                kinds = ("drw",)
        elif field in ("of", "component", "with"):
            kinds = ("prt", "asm")
        names.add(engine.model_name(value, kinds, field))
    return names


@timing.phase("dependency_scan")
def closure(client, roots):
    session = engine.session(client)
    present = set(session["models"])
    nodes, visiting = {}, set()

    def incomplete(name, reason):
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "dependency closure is incomplete",
            {
                "model": name,
                "reason": reason,
                "dispatch_state": "not_started",
                "automatic_retry": False,
            },
        )

    def visit(name, depth):
        if name in visiting:
            incomplete(name, "cyclic model references")
        if name in nodes:
            return
        if depth > MAX_DEPTH or len(nodes) + len(visiting) >= MAX_MODELS:
            incomplete(name, "dependency depth or model-count bound exceeded")
        if name not in present:
            incomplete(name, "a referenced dependency is absent from the session")
        visiting.add(name)
        try:
            described = engine.show(client, name)
        except Error as exc:
            if exc.code in ("E_NATIVE_READ_PENDING", "E_NATIVE_DIAGNOSTIC"):
                raise
            incomplete(name, "model getter failed: " + exc.code)
        kind = described.get("type")
        if described.get("model") != name:
            incomplete(name, "model getter returned a different identity")
        if kind == "assembly":
            rows = described.get("components")
            if not isinstance(rows, list) or any(
                not isinstance(c, dict) or not c.get("model") for c in rows
            ):
                incomplete(name, "component identities were not completely read")
            children = [c["model"].lower() for c in rows]
        elif kind == "drawing":
            children = described.get("models")
            if not isinstance(children, list) or any(not isinstance(c, str) for c in children):
                incomplete(name, "drawing model identities were not completely read")
        elif kind == "part":
            children = []
        else:
            incomplete(name, "unsupported or unreadable model kind")
        generic = (described.get("family") or {}).get("generic")
        if generic and kind in ("part", "assembly"):
            children = [*children, generic.lower()]
        if any(not object_identity.MODEL.fullmatch(c) for c in children):
            incomplete(name, "a dependency has no exact typed model identity")
        for child in sorted(set(children)):
            visit(child, depth + 1)
        revision = {"model": described}
        if kind in ("part", "assembly"):
            for op, key in (("parameter.list", "parameters"), ("relation.list", "relations")):
                try:
                    values = client.op(op, {"model": name})
                except Error as exc:
                    if exc.code in ("E_NATIVE_READ_PENDING", "E_NATIVE_DIAGNOSTIC"):
                        raise
                    incomplete(name, "revision getter failed: " + exc.code)
                if (
                    not isinstance(values.get(key), list)
                    or values.get("reading_failures")
                    or any(
                        isinstance(row, dict) and row.get("error") for row in values.get(key, [])
                    )
                ):
                    incomplete(name, "revision getter omitted " + key)
                revision[key] = values[key]
        nodes[name] = {
            "identity": name,
            "revision": digest(revision),
            "children": sorted(set(children)),
            "description": described,
        }
        visiting.remove(name)

    for name in sorted(set(roots)):
        if name in present:
            visit(name, 0)
    return [nodes[name] for name in sorted(nodes)]


def snapshots(nodes):
    return [{"identity": n["identity"], "revision": n["revision"]} for n in nodes]
