"""An offline, operation-owned installation of unchanged component bytes.

This is a domain plan for the existing public runtime, not a loader or a new executor.
Only a new target may be populated. Interrupted targets remain for inspection; there is
no automatic completion, replacement, deletion, registration or application restart.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

from . import driver, engine, operations, paths, safety, service_bundle, timing, transport
from .core import Error, atomic_write, canonical

OWNER = "installation-operation.json"
REGISTRY = "protk.dat"
MAX_MEMBERS = 32
JAVA_CLASS = re.compile(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")


def _path(value):
    path = Path(value).expanduser().absolute()
    if any(ch in str(path) for ch in ("\r", "\n", "\0", '"')):
        raise Error(
            "E_VALIDATION", "installation paths must not contain registry control characters"
        )
    paths.no_links(path)
    return path.resolve()


def _identity(stat):
    return [stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns]


def fingerprint(path):
    paths.no_links(path)
    before = path.stat()
    if not path.is_file() or before.st_size > service_bundle.MAX_FILE * 4:
        raise Error("E_VALIDATION", "installation input is not a bounded regular file")
    value = {
        "sha256": service_bundle.sha256(path),
        "bytes": before.st_size,
        "file_identity": _identity(before),
    }
    if _identity(path.stat()) != value["file_identity"]:
        raise Error("E_CONFLICT", "installation file changed during observation")
    return value


def _manifest(value, members):
    if (
        not isinstance(value, dict)
        or value.get("tool") != "creo-cli"
        or not isinstance(value.get("service_version"), str)
        or not service_bundle.VERSION.fullmatch(value["service_version"])
    ):
        raise Error("E_VALIDATION", "invalid service bundle manifest")
    if value.get("protocol") != transport.PROTOCOL:
        raise Error("E_CONFLICT", "bundle and CLI protocols differ")
    files = value.get("files")
    if (
        not isinstance(files, dict)
        or service_bundle.JAR not in files
        or set(files) - {service_bundle.JAR, service_bundle.DLL}
    ):
        raise Error("E_VALIDATION", "manifest must declare the JAR and optionally the native DLL")
    for name, expected in files.items():
        if name not in members:
            raise Error("E_VALIDATION", "bundle lacks a declared file", {"file": name})
        if not isinstance(expected, dict) or any(
            expected.get(k) != members[name][k] for k in ("sha256", "bytes")
        ):
            raise Error("E_INTEGRITY", "bundle payload differs from its manifest", {"file": name})
    app_class = value.get("java_app_class", service_bundle.APP_CLASS)
    if not isinstance(app_class, str) or not JAVA_CLASS.fullmatch(app_class):
        raise Error("E_VALIDATION", "invalid Java application entry class")
    profile = value.get("runtime_profile") or {}
    if not isinstance(profile, dict):
        raise Error("E_VALIDATION", "runtime profile must be an object")
    if profile.get("mode") == "fixed":
        raise Error(
            "E_UNSUPPORTED", "fixed development profiles cannot be installed as movable bundles"
        )
    return value


@timing.phase("state_read")
def source_snapshot(value):
    source = _path(value)
    driver.scope().require(effects=["observe"], paths=[(str(source), "observe")])
    try:
        members = {}
        if source.is_dir():
            entries = sorted(source.iterdir())
            if len(entries) > MAX_MEMBERS:
                raise Error("E_VALIDATION", "too many bundle entries")
            directory_before = _identity(source.stat())
            for entry in entries:
                members[entry.name] = fingerprint(entry)
            if members.get(service_bundle.MANIFEST, {}).get("bytes", 0) > 128 * 1024:
                raise Error("E_VALIDATION", "bundle manifest exceeds 128 KiB")
            raw_manifest = (source / service_bundle.MANIFEST).read_bytes()
            if (
                hashlib.sha256(raw_manifest).hexdigest()
                != members[service_bundle.MANIFEST]["sha256"]
            ):
                raise Error("E_CONFLICT", "bundle manifest changed during observation")
            manifest = json.loads(raw_manifest.decode("utf-8"))
            if directory_before != _identity(source.stat()):
                raise Error("E_CONFLICT", "bundle membership changed during observation")
            identity = directory_before
            container = None
            kind = "directory"
        elif source.is_file() and source.suffix.lower() == ".zip":
            container = fingerprint(source)
            with zipfile.ZipFile(source) as archive:
                entries = [entry for entry in archive.infolist() if not entry.is_dir()]
                if len(entries) > MAX_MEMBERS:
                    raise Error("E_VALIDATION", "too many bundle archive entries")
                prefixes = set()
                for entry in entries:
                    name = entry.filename.replace("\\", "/")
                    path = PurePosixPath(name)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or ":" in name
                        or entry.file_size > service_bundle.MAX_FILE
                    ):
                        raise Error("E_VALIDATION", "unsafe or oversized bundle archive entry")
                    if path.name in members:
                        raise Error("E_VALIDATION", "duplicate archive payload name")
                    prefixes.add(str(path.parent))
                    raw = archive.read(entry)
                    if path.name == service_bundle.MANIFEST and len(raw) > 128 * 1024:
                        raise Error("E_VALIDATION", "bundle manifest exceeds 128 KiB")
                    members[path.name] = {
                        "sha256": hashlib.sha256(raw).hexdigest(),
                        "bytes": len(raw),
                        "archive_entry": entry.filename,
                    }
                if len(prefixes) != 1 or service_bundle.MANIFEST not in members:
                    raise Error("E_VALIDATION", "archive must contain one flat service bundle")
                manifest = json.loads(
                    archive.read(members[service_bundle.MANIFEST]["archive_entry"]).decode("utf-8")
                )
            if fingerprint(source) != container:
                raise Error("E_CONFLICT", "bundle archive changed during observation")
            identity = container["file_identity"]
            kind = "zip"
        else:
            raise Error(
                "E_NOT_FOUND", "no readable service directory or ZIP", {"path": str(source)}
            )
        _manifest(manifest, members)
        return {
            "path": str(source),
            "kind": kind,
            "identity": identity,
            "container": container,
            "members": members,
            "manifest": manifest,
        }
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        raise Error(
            "E_VALIDATION",
            "service bundle cannot be completely read",
            {"reason": type(exc).__name__},
        ) from exc


@timing.phase("state_read")
def target_snapshot(target):
    target = _path(target)
    if not target.exists():
        return {
            "path": str(target),
            "exists": False,
            "files": {},
            "parent_exists": target.parent.exists(),
        }
    if not target.is_dir():
        raise Error("E_CONFLICT", "installation target is not a directory")
    rows = sorted(target.iterdir())
    if len(rows) > MAX_MEMBERS:
        raise Error("E_VERIFY_INCOMPLETE", "installation target has too many entries")
    if any(not row.is_file() for row in rows):
        raise Error("E_CONFLICT", "installation target has unexpected non-file entries; preserved")
    return {
        "path": str(target),
        "exists": True,
        "parent_exists": target.parent.exists(),
        "identity": _identity(target.stat()),
        "files": {row.name: fingerprint(row) for row in rows},
    }


def target_identity(target):
    path = _path(target)
    name = os.path.normcase(str(path))
    return {
        "mode": "file",
        "engine_id": "creo",
        "instance_id": None,
        "object_id": name,
        "locator": path.as_uri(),
        "extensions": {
            "creo": {"object_claims": [name], "ownership": "explicit installation directory"}
        },
    }


def expected_files(source, target):
    manifest = source["manifest"]
    registry = service_bundle.registry(
        target / service_bundle.JAR,
        auto_start=True,
        native_dll=target / service_bundle.DLL if service_bundle.DLL in manifest["files"] else None,
        app_class=manifest.get("java_app_class", service_bundle.APP_CLASS),
    ).encode("utf-8")
    expected = {
        name: {k: source["members"][name][k] for k in ("sha256", "bytes")}
        for name in [*manifest["files"], service_bundle.MANIFEST]
    }
    expected[REGISTRY] = {"sha256": hashlib.sha256(registry).hexdigest(), "bytes": len(registry)}
    return expected, registry


def matches(snapshot, expected):
    return snapshot["exists"] and all(
        name in snapshot["files"]
        and all(snapshot["files"][name][k] == value for k, value in values.items())
        for name, values in expected.items()
    )


@timing.phase("installation_copy")
def _copy_file(source, destination):
    with source.open("rb") as handle:
        raw = handle.read(service_bundle.MAX_FILE + 1)
    if len(raw) > service_bundle.MAX_FILE:
        raise Error("E_VALIDATION", "component grew beyond the copy limit")
    atomic_write(destination, raw, overwrite=False)


def plan(opts):
    source = source_snapshot(opts["from"])
    manifest = source["manifest"]
    target = _path(
        opts.get("target") or safety.directory() / "service" / manifest["service_version"]
    )
    if source["kind"] == "directory" and target.is_relative_to(Path(source["path"])):
        raise Error(
            "E_VALIDATION",
            "installation target must be outside the directory source bundle",
            {
                "source": source["path"],
                "target": str(target),
                "dispatch_state": "not_started",
                "next_action": "choose a sibling directory outside the source bundle",
            },
        )
    if opts.get("target"):
        target = paths.contained(str(target), exists=False)
        if not target.parent.is_dir():
            raise Error("E_VALIDATION", "create the owned installation workspace parent first")
    identity = target_identity(target)
    driver.require_clear(identity)
    before = target_snapshot(target)
    expected, registry = expected_files(source, target)
    if before["exists"] and not matches(before, expected):
        raise Error(
            "E_CONFLICT",
            "existing installation target is different or incomplete; it is preserved",
            {"path": str(target)},
        )
    registry_sha = expected[REGISTRY]["sha256"]
    owner = {}

    def prepare_dispatch(run):
        value = {
            "operation_id": run["operation_id"],
            "target": str(target),
            "source": source,
            "expected_files": expected,
            "before": before,
            "registry_sha256": registry_sha,
            "automatic_retry": False,
            "phase": "prepared",
        }
        run["installation_ownership"] = value
        operations.update(run)  # failure here is zero filesystem dispatch
        owner.update(value)

    def observe(_client):
        return target_snapshot(target)

    def apply(_client, record):
        if source_snapshot(source["path"]) != source or target_snapshot(target) != before:
            raise Error(
                "E_CONFLICT",
                "installation source or target changed before copying",
                {"request_sent": False},
            )
        if before["exists"]:
            return {"already_installed": True}
        record["installation_ownership"]["phase"] = "copying"
        operations.update(record)  # no filesystem dispatch until this checkpoint is reliable
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.mkdir(exist_ok=False)
        except FileExistsError as exc:
            raise Error(
                "E_CONFLICT",
                "installation target appeared before dispatch",
                {"request_sent": not before["parent_exists"] and target.parent.exists()},
            ) from exc
        try:
            atomic_write(
                target / OWNER,
                canonical({k: owner[k] for k in ("operation_id", "target", "registry_sha256")}),
                overwrite=False,
            )
            for name in [*manifest["files"], service_bundle.MANIFEST]:
                if name == service_bundle.MANIFEST:
                    atomic_write(target / REGISTRY, registry, overwrite=False)
                if source["kind"] == "directory":
                    _copy_file(Path(source["path"]) / name, target / name)
                else:
                    with zipfile.ZipFile(source["path"]) as archive:
                        raw = archive.read(source["members"][name]["archive_entry"])
                    atomic_write(target / name, raw, overwrite=False)
                if any(
                    fingerprint(target / name)[k] != expected[name][k] for k in ("sha256", "bytes")
                ):
                    raise Error(
                        "E_INTEGRITY", "copied installation bytes differ", {"request_sent": True}
                    )
            if source_snapshot(source["path"]) != source:
                raise Error(
                    "E_CONFLICT",
                    "source changed while installation was copied",
                    {"request_sent": True},
                )
            record["installation_ownership"]["phase"] = "files_written"
            operations.update(record)
            return {"already_installed": False}
        except (OSError, Error) as exc:
            raise Error(
                "E_IO",
                "installation did not complete; retain files and inspect the operation",
                {"request_sent": True, "reason": type(exc).__name__, "automatic_retry": False},
            ) from exc

    def verify(_client, result):
        observed = target_snapshot(target)
        checks = [
            engine.check("installed_file_bytes_and_registry", matches(observed, expected)),
            engine.check(
                "source_identity_and_bytes_unchanged", source_snapshot(source["path"]) == source
            ),
        ]
        done = {
            "installed_to": str(target),
            "protk_dat": str(target / REGISTRY),
            "files": {name: str(target / name) for name in expected},
            "version": manifest["service_version"],
            "already_installed": result["already_installed"],
            "creo_load_verified": False,
            "observed_files": observed,
            "then": [
                "Use only a private startup directory; follow docs/WINDOWS-DEPLOYMENT.md",
                "Use examples/engineering/start-owned-creo.ps1 with explicit Creo, Java, "
                "installation, new startup and runtime directories; both components auto-start",
                "Require its owned-process readiness result, then run doctor with the "
                "installation path and verify loaded components separately",
            ],
        }
        return done, {
            "level": "selected_postconditions_verified",
            "checks": checks,
            "not_checked": [
                "Creo loading, licensing, cross-machine portability and redistribution rights"
            ],
        }

    p = engine.Plan(
        op="service.install",
        request={"source": source["path"], "target": str(target)},
        target=str(target),
        binding={"source": source, "target": before, "expected_files": expected},
        preview={
            "command": "service install",
            "from": source["path"],
            "installs_to": str(target),
            "version": manifest["service_version"],
            "files": expected,
            "already_installed": before["exists"],
            "effect": "persist an independently checked component directory; "
            "no Creo registration or loading",
            "source": source,
            "file_target": identity,
            "then": [
                "toolkit_registry_file belongs only in an explicitly owned startup config.pro"
            ],
            "scope_paths": [
                (source["path"], "observe"),
                (str(target), "persist"),
                (str(target.parent), "persist"),
            ],
            "scope_outputs": [
                {"path": str(target), "effect": "persist", "exists": before["exists"]}
            ],
        },
        verify=verify,
        observe=observe,
        before=before,
        apply=apply,
        prepare_dispatch=prepare_dispatch,
        persisted=True,
        arguments={"from": opts["from"], "target": opts.get("target")},
    )
    p.artifacts_after = lambda: [
        {"path": str(target / name), "sha256": row["sha256"]}
        for name, row in target_snapshot(target)["files"].items()
    ]
    return SimpleNamespace(url=target.as_uri()), p


def _inspect(run):
    """Independent file observation from durable ownership; no live Plan or CAD."""
    owner = run.get("installation_ownership")
    if not isinstance(owner, dict):
        return {
            "state": "evidence_incomplete",
            "can_register": [],
            "reason": "record has no durable installation ownership",
            "creo_load_verified": False,
        }
    try:
        target = _path(owner["target"])
        observed = target_snapshot(target)
        before = owner["before"]
        evidence = {
            "observed": observed,
            "expected_files": owner["expected_files"],
            "creo_load_verified": False,
            "automatic_retry": False,
        }
        if before["exists"] and observed == before:
            return evidence | {"state": "preexisting_unchanged", "can_register": ["not_applied"]}
        if not observed["exists"]:
            return evidence | {
                "state": "no_target_observed",
                "can_register": ["not_applied"]
                if owner.get("phase") == "prepared" and observed == before
                else [],
                "reason": "prepared checkpoint precedes every local file dispatch; "
                "after copying started, current absence alone cannot prove no earlier effect",
            }
        marker = json.loads((target / OWNER).read_text(encoding="utf-8"))
        if marker != {key: owner[key] for key in ("operation_id", "target", "registry_sha256")}:
            return evidence | {
                "state": "evidence_incomplete",
                "can_register": [],
                "reason": "target ownership does not match this operation",
            }
        complete = matches(observed, owner["expected_files"])
        if not complete:
            return evidence | {"state": "partial_files", "can_register": ["partial"]}
        try:
            source_matches = source_snapshot(owner["source"]["path"]) == owner["source"]
        except (Error, OSError):
            return evidence | {
                "state": "input_unverifiable",
                "can_register": ["partial"],
                "files_complete": True,
            }
        if not source_matches:
            return evidence | {
                "state": "input_changed",
                "can_register": ["partial"],
                "source_matches": False,
                "files_complete": complete,
            }
        return evidence | {
            "state": "files_complete" if complete else "partial_files",
            "can_register": ["applied"] if complete else ["partial"],
        }
    except (Error, OSError, ValueError, KeyError) as exc:
        return {
            "state": "evidence_incomplete",
            "can_register": [],
            "reason": type(exc).__name__,
            "creo_load_verified": False,
        }


def inspect(run):
    owner = run.get("installation_ownership")
    if isinstance(owner, dict) and isinstance(owner.get("target"), str):
        target = _path(owner["target"])
        # Current permission, including roots and selectors, precedes any target
        # enumeration or content read. Do not turn refusal into incomplete evidence.
        driver.scope().require(
            effects=["observe"],
            target=target_identity(target),
            paths=[(str(target), "observe")],
        )
    result = _inspect(run)
    result["accepted"] = result["state"] == "files_complete"
    return result
