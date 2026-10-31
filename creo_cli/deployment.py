"""Read installed bytes and independently identify a running copy on this Windows host."""

import json
from pathlib import Path

from . import runtime_identity, safety, service_bundle, service_installation
from .core import Error, atomic_write, canonical, digest
from .transport import Client


def _java_pin(health, rows, host):
    """Derive an OS ancestor identity without substituting a DLL witness."""
    by_pid = {row["pid"]: row for row in rows}
    current = health.get("process_id")
    chain, host_pid = [], None
    while type(current) is int and current in by_pid and current not in chain and len(chain) < 32:
        chain.append(current)
        row = by_pid[current]
        if runtime_identity._path(row.get("actual_image", "")) == runtime_identity._path(host):
            host_pid = current
            break
        current = row.get("parent_pid")
    return {
        "java_pid": health.get("process_id"),
        "native_pid": host_pid,
        "chain": chain,
        "process_creations": {str(pid): by_pid[pid].get("creation_filetime") for pid in chain},
        "service_instance_id": health.get("service_instance_id"),
    }


def files(directory):
    target = service_installation._path(directory)
    observed = service_installation.target_snapshot(target)
    manifest = json.loads((target / service_bundle.MANIFEST).read_text(encoding="utf-8"))
    service_installation._manifest(manifest, observed["files"])
    expected, _ = service_installation.expected_files(
        {"manifest": manifest, "members": observed["files"]}, target
    )
    if not service_installation.matches(observed, expected):
        raise Error(
            "E_INTEGRITY", "installed component or registry bytes differ from the declared target"
        )
    return target, manifest, observed


def inspect(directory, *, creo=None, java_home=None, timeout=5):
    result = {
        "files_verified": False,
        "loaded_verified": False,
        "java_loaded_verified": False,
        "native_loaded_verified": False,
        "installation": str(directory),
        "limits": [
            "same host only; no clean-machine, cross-version or redistribution certification",
            "backing-file hashes and OS observations, not hashes of live memory pages",
        ],
    }
    try:
        target, manifest, observed = files(directory)
        result.update(
            files_verified=True,
            installation=str(target),
            component_files={name: observed["files"][name] for name in manifest["files"]},
            java_app_class=manifest.get("java_app_class"),
            component_source_sha256=manifest.get("component_source_sha256"),
            runtime_profile=manifest.get("runtime_profile"),
        )
        if not creo or not java_home:
            result["next_action"] = (
                "provide --creo <directory containing Common Files> and "
                "--java-home <JDK directory> for runtime identity verification"
            )
            return result
        host = Path(creo).resolve() / "Common Files/x86e_win64/obj/xtop.exe"
        java = Path(java_home).resolve() / "bin/java.exe"
        if not host.is_file() or not java.is_file():
            raise Error(
                "E_NOT_FOUND",
                "declared local Creo or Java executable is missing",
                {"creo_host": str(host), "java_executable": str(java)},
            )
        with Client(timeout) as client:
            health = client.health()
        configuration = health.get("runtime_configuration") or {}
        result["observed_runtime"] = {
            "source_sha256": health.get("source_sha256"),
            "runtime_class": health.get("runtime_class"),
            "service_instance_id": health.get("service_instance_id"),
            "process_started_at": health.get("process_started_at"),
            "identity_status": "handshake_only",
        }
        if (
            health.get("runtime_configuration_contract") != 1
            or configuration.get("portable_profile") is not True
        ):
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "running component does not expose the portable runtime profile",
            )
        if health.get("runtime_class") != manifest.get("java_app_class"):
            raise Error("E_VERIFY_FAILED", "running Java entry class differs from the installation")
        rows = runtime_identity.processes()
        by_pid = {row["pid"]: row for row in rows}
        java_pid = health["process_id"]
        if type(java_pid) is not int or java_pid < 1:
            raise Error("E_VERIFY_INCOMPLETE", "health Java process identifier is invalid")
        image_file = Path(configuration["state_directory"]) / "native-loaded-image.txt"
        expected = {
            "source_sha256": manifest.get("component_source_sha256"),
            "java_path": str(java),
            "host_path": str(host),
            "jar": {
                "path": str(target / service_bundle.JAR),
                "sha256": manifest["files"][service_bundle.JAR]["sha256"],
            },
            "native": {
                "path": str(target / service_bundle.DLL),
                "sha256": manifest["files"][service_bundle.DLL]["sha256"],
            },
        }
        native_error = None
        modules = None
        try:
            image = image_file.read_text(encoding="utf-8").splitlines()
            host_pid = int(image[0])
            chain, current = [], java_pid
            while current in by_pid and current not in chain and len(chain) < 32:
                chain.append(current)
                if current == host_pid:
                    break
                current = by_pid[current]["parent_pid"]
            pin = {
                "java_pid": java_pid,
                "native_pid": host_pid,
                "chain": chain,
                "process_creations": {
                    str(pid): by_pid[pid].get("creation_filetime") for pid in chain
                },
                "service_instance_id": health["service_instance_id"],
            }
            modules = runtime_identity.modules(host_pid)
        except (OSError, ValueError, IndexError) as exc:
            native_error = {
                "code": "E_VERIFY_INCOMPLETE",
                "reason": "native loaded-image witness absent"
                if isinstance(exc, FileNotFoundError)
                else "native loaded-image or module observation unavailable",
                "kind": "native_witness_absent"
                if isinstance(exc, FileNotFoundError)
                else "native_observation_unavailable",
                "witness_path": str(image_file),
                "exception_type": type(exc).__name__,
                "module_inventory_observed": modules is not None,
            }
        jar_error = None
        try:
            jars = runtime_identity.open_jars(java_pid)
        except OSError as exc:
            jars = []
            jar_error = {
                "code": "E_VERIFY_INCOMPLETE",
                "reason": "current Java open-JAR handles could not be observed",
                "exception_type": type(exc).__name__,
            }
        after = runtime_identity.processes()
        java_pin = _java_pin(health, rows, host)
        java_gate = runtime_identity.validate_java_candidate(
            health,
            rows,
            after,
            java_pin,
            expected | {"java_app_class": manifest.get("java_app_class")},
            jars,
            lambda path: service_bundle.sha256(Path(path)),
        )
        if jar_error:
            java_gate["errors"].append(jar_error["reason"])
            java_gate["passed"] = False
        result.update(
            java_loaded_verified=java_gate["passed"],
            java_runtime_identity=java_gate,
            java_runtime_pin=java_pin,
            service_instance_id=health["service_instance_id"],
            runtime_configuration=configuration,
        )
        if native_error or jar_error:
            result["diagnostic"] = native_error or jar_error
            result["native_runtime_observation"] = native_error or {
                "kind": "full_identity_incomplete",
                "reason": jar_error["reason"],
            }
            if jar_error:
                result["java_runtime_observation_error"] = jar_error
            result["next_action"] = (
                "Java component identity only is verified; native DLL evidence remains absent "
                "or incomplete. Retain trust/license blockers. Only an explicitly authorized "
                "JavaOnlyDiagnostic causal trial may use this partial observation; "
                "the full native backend and engineering acceptance remain unverified."
                if java_gate["passed"]
                else "Java/native runtime identity is incomplete; inspect the component-specific "
                "errors and retained trust/license blockers; do not infer loaded state or retry CAD"
            )
            return result
        anchor_dir = safety.directory(True) / "runtime-load-observations"
        from .paths import no_links

        no_links(anchor_dir)
        anchor = anchor_dir / (digest([str(target), health["service_instance_id"]]) + ".json")
        previous = json.loads(anchor.read_text(encoding="utf-8")) if anchor.exists() else None
        gate = runtime_identity.validate_candidate(
            health,
            rows,
            after,
            pin,
            expected,
            image,
            modules,
            jars,
            lambda path: service_bundle.sha256(Path(path)),
            verified_load=previous,
        )
        result.update(
            loaded_verified=gate["passed"],
            native_loaded_verified=gate["passed"],
            runtime_identity=gate,
            service_instance_id=health["service_instance_id"],
            runtime_configuration=configuration,
            process_identities=[by_pid[pid] for pid in chain],
            runtime_pin=pin,
            observation_anchor=str(anchor),
        )
        if (
            gate["passed"]
            and gate.get("jar_binding") == "current_open_handle"
            and not anchor.exists()
        ):
            anchor_dir.mkdir(parents=True, exist_ok=True)
            retained = {
                "health": health,
                "identity": gate,
                "runtime_pin": pin,
                "expected_identity": expected,
                "processes": [by_pid[pid] for pid in chain],
                "native_modules": [str(target / service_bundle.DLL)],
                "open_jars": jars,
                "read_only": True,
            }
            atomic_write(anchor, canonical(retained), overwrite=False)
        result["next_action"] = (
            "read session status and independently verify the engineering task"
            if gate["passed"]
            else "inspect the identity mismatches; do not treat copied files as loaded"
        )
    except (Error, OSError, ValueError, KeyError, RuntimeError) as exc:
        result["diagnostic"] = {
            "code": exc.code if isinstance(exc, Error) else "E_VERIFY_INCOMPLETE",
            "reason": exc.message if isinstance(exc, Error) else type(exc).__name__,
        }
        result["next_action"] = (
            "verify declared local dependencies, private startup/runtime paths and "
            "the owned automatic startup/readiness record; retain trust/license blockers "
            "and preserve existing instances"
        )
    return result
