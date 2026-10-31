"""Exact model identities and conservative claims for an import of unknown model type."""

from __future__ import annotations

import re

MODEL = re.compile(r"^[a-z][a-z0-9_-]{0,30}\.(prt|asm|drw)$", re.I)


def claims(value: str, action: str | None = None, request: dict | None = None) -> set[str]:
    request = request or {}
    if action == "model.import":
        name = str(request.get("name") or value).lower()
        kind = {"part": "prt", "assembly": "asm"}.get(request.get("type"))
        return {name + "." + ext for ext in ((kind,) if kind else ("prt", "asm"))}
    return {value.lower() if MODEL.fullmatch(value) else value}


def target_claims(target: dict, plan: dict | None = None) -> set[str]:
    explicit = target.get("extensions", {}).get("creo", {}).get("object_claims")
    if isinstance(explicit, list) and explicit:
        return set(explicit)
    # Older stored imports used a bare name. Interpret their original request without rewriting.
    change = next(iter((plan or {}).get("changes", [])), {})
    return claims(target["object_id"], change.get("action"), change.get("after"))


def footprints(plan: dict) -> set[str]:
    result = target_claims(plan["target"], plan)
    for dependency in plan.get("base_snapshot", {}).get("dependencies", []):
        name = dependency.get("identity", "")
        if MODEL.fullmatch(name):
            result.add(name.lower())
    return result
