"""The adapter layer: the only code of creo-cli that talks to Creo Parametric (DCLI-260).

Everything that reads or changes a model runs in the host component inside Creo (plugin/),
because Creo's toolkit works only there and only on Creo's main thread (DCLI-262). The
runtime sends those calls to the host itself. What is left for this adapter runs in the CLI:

- ``probe``: find the Creo installation;
- ``sessions``: the running Creo processes, with what their host components report;
- ``plugin_status``, ``plugin_install``, ``plugin_remove``: the host component on disk.

The conformance suites never call this code: they run the tool with ``CREO_CLI_FAKE_HOST``
set, and the fake host answers every capability (DVER-023).
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from .._driver import Adapter as BaseAdapter
from .._driver import AdapterError
from .._driver.adapter import session_id
from .._driver.hostproto import Connection, HostReplyError, NoReply, ProtocolError, Unreachable, read_discovery
from .._driver.records import pid_alive
from . import build, windows

PTC_ROOTS = (r"C:\Program Files\PTC", r"C:\PTC", r"D:\PTC", r"E:\PTC")
SEARCH_DEPTH = 4
PROTOCOL = "1.0.0"
PLUGIN_NAME = "creo-cli-host"
APP_CLASS = "com.fateforge.creocli.host.Host"
JAR = "creo-cli-host.jar"
CONFIG = "creo-cli-host.json"
VERSION_IN_PATH = re.compile(r"Creo (\d+\.\d+\.\d+\.\d+)", re.IGNORECASE)
SESSION_CALL_MS = 1600


def _root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


def _cli_version() -> str:
    try:
        return str(json.loads((_root() / "package.json").read_text(encoding="utf-8"))["version"])
    except (OSError, ValueError, KeyError):
        return "0.0.0"


def common_files() -> list[Path]:
    """Every Creo 'Common Files' directory that holds Object TOOLKIT Java, best guess first."""
    found: list[Path] = []
    for root in PTC_ROOTS:
        queue = [(Path(root), 0)]
        while queue:
            directory, depth = queue.pop(0)
            try:
                children = sorted(directory.iterdir())
            except OSError:
                continue
            for child in children:
                name = child.name.lower()
                if name == "common files" and (child / "text" / "java" / "otk.jar").is_file():
                    found.append(child)
                elif depth < SEARCH_DEPTH and child.is_dir() and name.startswith(("creo", "ptc", "m0", "f0")):
                    queue.append((child, depth + 1))
    return found


def version_of(path: str | os.PathLike[str] | None) -> str | None:
    match = VERSION_IN_PATH.search(str(path or ""))
    return match.group(1) if match else None


class Adapter(BaseAdapter):
    # ------------------------------------------------------------------ probe

    def probe(self, request: dict[str, Any]) -> dict[str, Any]:
        found = common_files()
        if not found:
            return {"found": False}
        install = found[0].parent
        out: dict[str, Any] = {"found": True, "path": str(install), "license": "unknown"}
        version = version_of(install)
        if version:
            out["version"] = version
        return out

    # ------------------------------------------------------------------ sessions

    def _state_dir(self) -> Path:
        state = getattr(self.store, "_state", None)
        if state is not None:
            return Path(state.path)
        return Path(os.environ.get("CREO_CLI_STATE_DIR") or Path.home() / ".creo-cli")

    def sessions(self, request: dict[str, Any]) -> dict[str, Any]:
        hosts = {e["pid"]: e for e in read_discovery(str(self._state_dir() / "hosts")) if pid_alive(e["pid"])}
        items = []
        for pid in windows.processes("xtop.exe"):
            sid = session_id("creo", pid)
            version = version_of(windows.image_path(pid)) or "unknown"
            item: dict[str, Any] = {
                "id": sid, "application": {"name": "Creo Parametric", "version": version}, "pid": pid,
                "owned": False, "generation": 0, "state": "ready", "documents": [], "plugin_loaded": None,
            }
            title = windows.blocker(pid)
            if title is not None:
                item["state"] = "blocked"
                item["blocker"] = {"action": "dismiss_dialog", "title": title}
            entry = hosts.get(pid)
            if entry is not None:
                item["plugin_loaded"] = str(entry.get("plugin_version"))
                self._ask_host(entry, sid, item, documents=title is None)
            items.append(item)
        return {"items": items, "complete": True}

    def _ask_host(self, entry: dict[str, Any], sid: str, item: dict[str, Any], documents: bool) -> None:
        """The generation and the open documents, from the host. A host that cannot be reached
        is reported by the runtime, which probes every host itself (DCLI-205, DCLI-278)."""
        conn = Connection(entry["address"], _cli_version(), PROTOCOL)
        try:
            hello = conn.open(SESSION_CALL_MS)
            item["generation"] = int((hello.get("session") or {}).get("generation", 0))
            if documents:
                docs = conn.call("documents", {"session": sid}, SESSION_CALL_MS).get("items", [])
                item["documents"] = [{"id": d["id"], "path": d.get("path"), "dirty": bool(d.get("dirty"))} for d in docs]
        except HostReplyError as exc:
            if exc.code == "E_BUSY":
                item["state"] = "busy"
        except (Unreachable, NoReply, ProtocolError, OSError, ValueError, KeyError, TypeError):
            pass
        finally:
            conn.close()

    # ------------------------------------------------------------------ the host component on disk

    def _plugin_dir(self, state_dir: str | os.PathLike[str] | None = None) -> Path:
        return Path(state_dir) / "plugin" if state_dir else self._state_dir() / "plugin"

    def plugin_status(self, request: dict[str, Any]) -> dict[str, Any]:
        folder = self._plugin_dir()
        version = None
        try:
            config = json.loads((folder / CONFIG).read_text(encoding="utf-8"))
            if (folder / "protk.dat").is_file() and (folder / str(config["version"]) / JAR).is_file():
                version = str(config["version"])
        except (OSError, ValueError, KeyError):
            version = None
        loaded = []
        for entry in read_discovery(str(self._state_dir() / "hosts")):
            if pid_alive(entry["pid"]):
                loaded.append({"session": entry["_file"][:-5], "version": str(entry.get("plugin_version"))})
        return {
            "name": PLUGIN_NAME, "version_on_disk": version, "protocol_version": PROTOCOL,
            "install_path": str(folder / version) if version else None, "loaded": loaded,
        }

    def plugin_install(self, request: dict[str, Any]) -> dict[str, Any]:
        """Build the host component from its shipped source, unlock it with this computer's own
        license, and install it into plugin/<version>/ of the state directory, with the registry
        file Creo reads and the state directory beside it (DCLI-271, DSEC-050).

        plugin/protk.dat stays at one place across versions: the person's config.pro names it
        once with ``toolkit_registry_file``, and an upgrade only rewrites it. A Creo already
        running keeps the version it loaded (DSEC-052)."""
        source = _root() / "plugin"
        manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
        version = str(request.get("version") or manifest["version"])
        folder = self._plugin_dir(request["state_dir"])
        target = folder / version
        found = common_files()
        if not found:
            raise AdapterError("E_UNSUPPORTED", "No Creo installation with Object TOOLKIT Java was found, so the host "
                               "component cannot be built.", dispatch_state="not_started")
        digest = build.source_digest(source / "src")
        jar = target / JAR
        if not (jar.is_file() and _installed_digest(target) == digest):
            fresh = folder / f".{JAR}.{os.getpid()}.new"
            build.build(source / "src", found[0], fresh)
            try:
                target.mkdir(parents=True, exist_ok=True)
                os.replace(fresh, jar)
            except OSError as exc:
                fresh.unlink(missing_ok=True)
                raise AdapterError("E_NATIVE_FAILURE", f"The host component could not be written to {jar}: {exc}. A "
                                   "running Creo may hold this version; close it and install again.",
                                   dispatch_state="not_started") from None
        try:
            for name, expected in manifest.get("files", {}).items():
                src, dst = source / name, target / name
                if dst.is_file() and _sha256(dst) == expected:
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dst)
                if _sha256(dst) != expected:
                    raise AdapterError("E_NATIVE_FAILURE", f"The copy of {name} does not match its manifest.",
                                       dispatch_state="dispatched")
            registry = _registry(jar)
            config = json.dumps({"state_dir": str(Path(request["state_dir"])), "version": version,
                                 "source_sha256": digest}, indent=2)
            for where in (target, folder):
                _write(where / "protk.dat", registry)
                _write(where / CONFIG, config + "\n")
        except PermissionError as exc:
            raise AdapterError("E_NATIVE_FAILURE", f"The host component could not be written: {exc}.",
                               dispatch_state="dispatched") from None
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable",
                "persistence": "saved", "install_path": str(target), "version": version}

    def plugin_remove(self, request: dict[str, Any]) -> dict[str, Any]:
        folder = self._plugin_dir()
        if not folder.exists():
            return {"dispatch_state": "not_started", "change": "not_applicable", "delivery": "not_applicable",
                    "persistence": "unchanged"}
        try:
            for name in ("protk.dat", CONFIG):
                (folder / name).unlink(missing_ok=True)
            shutil.rmtree(folder)
        except OSError as exc:
            raise AdapterError("E_NATIVE_FAILURE", f"The host component could not be removed completely: {exc}. A "
                               "running Creo may hold its files; close Creo and remove it again.",
                               dispatch_state="dispatched") from None
        return {"dispatch_state": "dispatched", "change": "applied", "delivery": "not_applicable", "persistence": "saved"}


def _registry(jar: Path) -> str:
    """The registry file of an Object TOOLKIT Java application. ``fail_tol true``: without it,
    an application whose start fails makes Creo shut itself down."""
    lines = [
        f"name              {PLUGIN_NAME}",
        "startup           otk_java",
        "toolkit           object",
        "creo_type         parametric",
        f"java_app_class    {APP_CLASS}",
        f"java_app_classpath {jar}",
        "java_app_start    start",
        "java_app_stop     stop",
        "allow_stop        true",
        "fail_tol          true",
        "delay_start       false",
        "end",
    ]
    return "\n".join(lines) + "\n"


def _installed_digest(target: Path) -> str | None:
    """The source digest the installed JAR was built from, as plugin install recorded it."""
    try:
        return str(json.loads((target / CONFIG).read_text(encoding="utf-8"))["source_sha256"])
    except (OSError, ValueError, KeyError):
        return None


def _write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()
