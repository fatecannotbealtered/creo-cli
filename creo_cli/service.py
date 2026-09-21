"""Orchestration and bounded filesystem utilities."""
from __future__ import annotations
import hashlib
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from . import __version__, creoson_env, models, native, registry, safety
from .core import Error, CODES, canonical, read_json, page, atomic_write

RELEASE = {"level": "unpublishable", "fcc_required": True, "fcc_status": "unknown", "mock_upstream_required": True,
           "mock_upstream_status": "unknown", "live_smoke_required_for_stable": True, "live_smoke_status": "missing",
           "reason": "Development snapshot: full FCC certification, pinned spec vendoring, and live Creo evidence are incomplete.",
           "required_evidence": ["functional_contract_coverage_100", "mock_upstream_contract_tests", "pinned_spec_byte_identity", "recorded_live_smoke_for_stable"]}
PATTERN = re.compile(r"^(.+)\.(prt|asm|drw|frm|sec)(?:\.(\d+))?$", re.I)

def scan(root, limit, offset):
    p = Path(root).expanduser().resolve()
    if not p.is_dir():
        raise Error("E_NOT_FOUND", "workspace directory not found")
    rows, errors = [], []
    try:
        with os.scandir(p) as entries:
            for n, ent in enumerate(entries):
                if n >= 50000:
                    raise Error("E_VALIDATION", "scan exceeds 50000-entry ceiling; select a narrower directory")
                if ent.is_symlink() or not ent.is_file(follow_symlinks=False):
                    continue
                m = PATTERN.match(ent.name)
                if not m:
                    continue
                try:
                    st = ent.stat(follow_symlinks=False)
                except OSError:
                    errors.append({"path": ent.name, "code": "E_IO"})
                    continue
                rows.append({"id": ent.name, "name": m[1], "kind": m[2].lower(), "file_version": int(m[3]) if m[3] else None,
                             "size_bytes": st.st_size, "modified_at": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat().replace("+00:00", "Z")})
    except OSError as exc:
        raise Error("E_IO", "cannot enumerate workspace") from exc
    rows.sort(key=lambda r: (r["name"].casefold(), r["kind"], r["file_version"] if r["file_version"] is not None else -1, r["id"]))
    return page(rows, limit, offset)|{"root": str(p), "scan_errors": errors, "complete": not errors,
                                    "provenance": {"backend": "filesystem", "simulation": False},
                                    "not_checked": ["native_file_contents", "subdirectories"], "_untrusted": ["items", "root", "scan_errors"]}

def inspect(path):
    p = Path(path).expanduser()
    if p.is_symlink():
        raise Error("E_FORBIDDEN", "file must not be a symbolic link")
    if not p.is_file():
        raise Error("E_NOT_FOUND", "file not found")
    h, size = hashlib.sha256(), 0
    try:
        with p.open("rb") as f:
            before = os.fstat(f.fileno())
            if before.st_size > 1024**3:
                raise Error("E_VALIDATION", "file exceeds 1 GiB inspection ceiling")
            while block := f.read(1024*1024):
                size += len(block)
                if size > 1024**3:
                    raise Error("E_VALIDATION", "file grew beyond inspection ceiling")
                h.update(block)
            after = os.fstat(f.fileno())
        now = p.stat()
        stamp = lambda s: (s.st_size, s.st_mtime_ns, s.st_ino)
        if stamp(before) != stamp(after) or stamp(now) != stamp(after):
            raise Error("E_CONFLICT", "file changed while hashing")
    except OSError as exc:
        raise Error("E_IO", "file hashing failed") from exc
    return {"path": str(p.absolute()), "sha256": h.hexdigest(), "size_bytes": size,
            "provenance": {"backend": "filesystem", "simulation": False}, "not_checked": ["native_file_contents", "model_validity"], "_untrusted": ["path"]}

def creoson_checks() -> list[dict]:
    """Doctor checks for the primary route: is the toolkit there, and can we write?

    Offline by design, like the rest of doctor. Liveness of the service is a separate
    question with its own command (`creoson status`), and the fix text says so rather
    than making doctor reach out over the network.
    """
    env = creoson_env.probe()
    if env["api_toolkit_present"]:
        toolkit = {"status": "pass", "fix": None}
    elif env["streamed_delivery"]:
        # The case that cost a day: the toolkit is not merely unselected, it cannot be
        # added, because a streamed build has no installer to re-run.
        toolkit = {"status": "fail",
                   "fix": "Creo appears to be delivered by an application-streaming player, which "
                          "ships without the API toolkits and has no installer to add them. CREOSON "
                          "needs a standard licensed installation with the "
                          f"'{creoson_env.TOOLKIT_COMPONENT}' component selected."}
    else:
        toolkit = {"status": "fail",
                   "fix": f"re-run the Creo installer and select API Toolkits -> "
                          f"'{creoson_env.TOOLKIT_COMPONENT}' (it is free with a Creo seat, and it is "
                          f"what ships {creoson_env.JLINK_JAR}; there has been no separate J-Link "
                          f"installer since Creo 4.0)"}
    java = env["java_runtime"]
    space = env["workspace"]
    return [
        {"check": "creo_api_toolkit", **toolkit,
         "message": env["api_toolkit_detail"],
         "details": {"creo_load_point": env["creo_load_point"], "streamed_delivery": env["streamed_delivery"]}},
        {"check": "creo_otk_java_runtime",
         "status": "pass" if java["source"] == "PRO_JAVA_COMMAND" and java["resolved"] else "warn",
         "fix": None if java["source"] == "PRO_JAVA_COMMAND" and java["resolved"] else
                "set PRO_JAVA_COMMAND to a Java 25 java.exe and restart Creo; Creo 13.4 needs Java 25 "
                "for synchronous Object TOOLKIT Java and fails the application during load when it "
                "cannot find one, before the application logs anything (see docs/CREO_SETUP.md)",
         "message": java["detail"]},
        {"check": "creoson_service", "status": "warn",
         "fix": "run `creo-cli creoson status` to probe the service; doctor stays offline",
         "message": "liveness is not checked here"},
        {"check": "creoson_workspace",
         "status": "pass" if space["usable"] else "warn",
         "fix": None if space["usable"] else "set CREO_CLI_WORKSPACE to an existing disposable directory "
                                             "with no symlink or junction in its path",
         "message": space["detail"]},
    ]


def changelog(since):
    if since and not re.fullmatch(r"\d+\.\d+\.\d+", since):
        raise Error("E_VALIDATION", "--since expects a stable semantic version")
    entries, current, category = [], None, None
    for line in (Path(__file__).parent/"CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"## \[(\d+\.\d+\.\d+)\] - (\d{4}-\d{2}-\d{2})", line)
        if m:
            current = {"version": m[1], "date": m[2], "changes": {k: [] for k in ("added", "changed", "fixed", "removed", "deprecated", "security")}}
            entries.append(current)
            category = None
        elif line.startswith("### "):
            category = line[4:].strip().lower()
        elif current and category in current["changes"] and line.startswith("- "):
            current["changes"][category].append(line[2:])
    if since:
        key = tuple(map(int, since.split(".")))
        entries = [e for e in entries if tuple(map(int, e["version"].split("."))) > key]
    return {"current_version": __version__, "since": since, "entries": entries}

def backend(opts):
    return models.Mock(opts.get("model")) if opts.get("backend") == "mock" else native.Native(opts.get("model"), opts.get("timeout", 30))

def execute(path, o):
    from .creoson_catalog import BY_PATH
    from . import creoson_engine, creoson_transport
    if path in BY_PATH or path.startswith(("creoson ", "workflow ")):
        return creoson_engine.dispatch(path, o)
    if path == "reference":
        commands = [c for c in registry.COMMANDS if not o.get("command") or c.path == o["command"]]
        if not commands:
            raise Error("E_NOT_FOUND", "command not present in live contract")
        selected = {c.schema for c in commands}|({"dry_run"} if any(c.write for c in commands) else set())
        return {"tool": "creo-cli", "version": __version__, "risk_tier": "T1", "release_readiness": RELEASE,
                "commands": [c.describe() for c in commands], "schemas": {k: v for k, v in registry.SCHEMAS.items() if not o.get("command") or k in selected},
                "error_codes": {k: {"exit": v[0], "retryable": v[1]} for k, v in CODES.items()},
                "exit_codes": {str(n): text for n, text in ((0, "success"), (1, "nonretryable failure"), (2, "usage/validation"), (3, "not found"), (4, "permission/config"), (5, "confirmation required"), (6, "conflict"), (7, "transient"), (8, "timeout"), (9, "reserved human action"), (130, "interrupted"))}, "global_flags": registry.GLOBALS}
    if path == "context":
        return {"version": __version__, "credentials": {"configured": False, "kind": "none_required"},
                "config": {"permission": safety.permission(), "state_directory": str(safety.directory()), "default_backend": "native", "native_write_opt_in": os.environ.get("CREO_CLI_EXPERIMENTAL_NATIVE_WRITES") == "1"},
                "native": native.probe(), "creoson": creoson_transport.configuration(), "_untrusted": ["config.state_directory"]}
    if path == "doctor":
        checks = [{"check": k, "status": "pass" if v else "warn", "fix": None if v else "see docs/NATIVE_ADAPTER.md; offline commands remain usable"}
                  for k, v in native.probe().items() if k not in ("configured", "license_status", "live_verified")]
        checks += creoson_checks()
        checks += [{"check": "native_live_evidence", "status": "warn", "fix": "record a disposable-part live run"},
                   {"check": "release_readiness", "status": "fail", "fix": RELEASE["reason"], "details": {"level": RELEASE["level"]}}]
        return {"checks": checks}
    if path == "changelog":
        return changelog(o.get("since"))
    if path == "system capabilities":
        return {"backends": [{"name": "creoson", "status": "experimental_not_live_verified", "simulation": False, "operations": sorted(BY_PATH)}, {"name": "native", "status": "experimental" if native.probe()["configured"] else "unavailable", "simulation": False},
                             {"name": "mock", "status": "available", "simulation": True}, {"name": "filesystem", "status": "available", "simulation": False}],
                "native_live_verified": False, "unsupported_domains": ["native_feature_creation", "assembly_arbitrary_constraints", "stress_analysis", "interference", "windchill", "self_update"]}
    if path == "workspace scan":
        return scan(o["root"], o["limit"], o["offset"])
    if path == "workspace inspect":
        return inspect(o["file"])
    if path == "snapshot validate":
        s = models.validate(read_json(o["input"]))
        return {"valid": True, "kind": "snapshot", "summary": {"model": s["model"]["id"], "simulation": s["provenance"]["simulation"], "observed_state_digest": models.revision(s)}, "_untrusted": ["summary"]}
    if path == "snapshot diff":
        return page(models.diff(read_json(o["input"]), read_json(o["other"])), o["limit"], o["offset"])
    if path == "change validate":
        c = models.validate_change(read_json(o["changeset"]))
        return {"valid": True, "kind": "changeset", "summary": {"model": c["model"], "operation_count": len(c["operations"])}, "_untrusted": ["summary"]}
    if path == "change history":
        return page(safety.history(), o["limit"], o["offset"])
    if path == "session status" and o.get("backend") == "mock" and not o.get("model"):
        return {"connected": False, "current_model": None, "models_loaded": 0, "provenance": {"backend": "mock", "simulation": True}, "_untrusted": ["current_model"]}
    b = backend(o)
    if path == "session status":
        if b.name == "native":
            return b.request("session.status")
        s = b.observe()[0]
        return {"connected": False, "current_model": s["model"]["id"], "models_loaded": 1, "provenance": s["provenance"], "_untrusted": ["current_model"]}
    if path == "model init":
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,30}", o["name"]):
            raise Error("E_VALIDATION", "fixture name must be 1..31 lowercase ASCII letters/digits/underscores, starting with a letter")
        if b.path.exists():
            raise Error("E_CONFLICT", "destination already exists")
        bound = safety.scope(path, "mock", b.target, {"name": o["name"]}, "absent")
        if o["dry_run"]:
            token, expires = safety.issue(bound)
            return {"preview": {"create": b.target, "simulation": True}, "confirm_token": token, "expires_at": expires, "provenance": {"backend": "mock", "simulation": True}, "not_checked": ["all_cad_geometry"], "_untrusted": ["preview"]}
        safety.require_write()
        def create():
            s = models.sample(o["name"])
            atomic_write(b.path, canonical(s)+b"\n", overwrite=False)
            return s
        with safety.lock(b.target):
            safety.consume(o.get("confirm"), bound)
            return safety.audited(path, b.target, create)
    if path in ("change preview", "change apply"):
        change = models.validate_change(read_json(o["changeset"]))
        s, rev = b.observe()
        _, changes = models.plan(s, change)
        preview = {"model": s["model"]["id"], "changes": changes, "operation_count": len(changes), "risk_tier": "T1",
                   "simulation": b.name == "mock", "saves_to_disk": b.name == "mock", "geometry_evaluated": False,
                   "warning": "A parameter plan is not a geometry preview; native edits remain unsaved."}
        common = {"preview": preview, "provenance": s["provenance"], "not_checked": s["not_checked"], "_untrusted": ["preview"]}
        if path == "change preview":
            return common|{"revision": rev}
        bound = safety.scope(path, b.name, b.target, change, rev)
        if o["dry_run"]:
            token, expires = safety.issue(bound)
            return common|{"confirm_token": token, "expires_at": expires}
        safety.require_write(native=b.name == "native")
        if b.name == "native":
            return b.request("change.apply", changeset=change, expected_revision=rev, confirm_token=o.get("confirm"))
        with safety.lock(b.target):
            safety.consume(o.get("confirm"), bound)
            return safety.audited(path, b.target, lambda: b.apply(change, rev))
    if path.startswith("model "):
        leaf = path.split()[1]
        if leaf == "snapshot":
            return b.observe()[0]
        if b.name == "native":
            result = b.request("model."+leaf)
            if leaf == "info":
                return result
            rows = result["items"]
        else:
            s = b.observe()[0]
            if leaf == "info":
                return {"model": s["model"], "provenance": s["provenance"], "_untrusted": ["model"]}
            rows = [s["model"]] if leaf == "list" else s[leaf]
        if leaf != "relations":
            key = "name" if leaf == "parameters" else "id"
            rows = sorted(rows, key=lambda row: row[key])
        if o.get("name"):
            needle = o["name"].casefold()
            rows = [r for r in rows if needle in str(r.get("name", r.get("symbol", r.get("id", "")))).casefold()]
        return page(rows, o["limit"], o["offset"])|{"provenance": {"backend": b.name, "simulation": b.name == "mock"}, "not_checked": ["cad_geometry"]}
    raise Error("E_USAGE", "unknown command")
