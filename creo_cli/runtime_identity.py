"""Read-only Windows runtime evidence and a fail-closed candidate identity gate.

PID alone is not identity. Pin process creation times and check both snapshots,
the actual ancestor chain, DLL module list and Java's open JAR handles. Disk
hashes describe the locked backing files, not a hash of relocated memory pages.
"""

from __future__ import annotations

import ctypes
import os
import re
import uuid
from collections.abc import Callable
from datetime import datetime
from pathlib import Path


def _path(value: str | Path) -> str:
    return os.path.normcase(os.path.realpath(value))


def validate_candidate(
    health: dict,
    before: list[dict],
    after: list[dict],
    pin: dict,
    expected: dict,
    native_image: list[str],
    modules: list[str],
    open_jars: list[str],
    sha: Callable[[Path], str],
    verified_load: dict | None = None,
) -> dict:
    """Validate observations; this predicate never launches or changes a process."""
    errors: list[str] = []
    if health.get("ok") is not True or health.get("service") != "creo-cli":
        errors.append("health is not a running creo-cli service")
    if health.get("source_sha256") != expected["source_sha256"]:
        errors.append("loaded Java source marker differs from the candidate")
    if health.get("service_instance_id") != pin.get("service_instance_id"):
        errors.append("service generation changed since the connection was pinned")
    if not pin.get("service_instance_id"):
        errors.append("service generation identity is unavailable")
    java_pid, host_pid = pin.get("java_pid"), pin.get("native_pid")
    if type(java_pid) is not int or type(host_pid) is not int or min(java_pid, host_pid) < 1:
        errors.append("pinned process identifiers are invalid")
    if type(health.get("process_id")) is not int or health.get("process_id") != java_pid:
        errors.append("health process differs from the pinned Java process")
    try:
        image_pid = int(native_image[0]) if len(native_image) == 2 else None
    except (ValueError, TypeError):
        image_pid = None
    if image_pid != host_pid:
        errors.append("native handshake host differs from the pinned host")
    if len(native_image) != 2 or _path(native_image[1]) != _path(expected["native"]["path"]):
        errors.append("native handshake path differs from the candidate")

    snapshots = []
    for label, rows in (("before", before), ("after", after)):
        by_pid = {row["pid"]: row for row in rows}
        snapshots.append(by_pid)
        if len(by_pid) != len(rows):
            errors.append(label + " snapshot contains duplicate process identifiers")
        chain, current = [], java_pid
        while current in by_pid and current not in chain and len(chain) < 32:
            chain.append(current)
            if current == host_pid:
                break
            child = by_pid[current]
            parent = by_pid.get(child.get("parent_pid"))
            if not parent:
                break
            try:
                if int(parent["creation_filetime"]) > int(child["creation_filetime"]):
                    errors.append(label + " parent PID was reused after the child was created")
            except (KeyError, ValueError, TypeError):
                errors.append(label + " process creation time is unavailable")
                break
            current = parent["pid"]
        if not chain or chain[-1] != host_pid or java_pid == host_pid:
            errors.append(label + " Java process is not a descendant of the native Creo host")
        if chain != pin.get("chain"):
            errors.append(label + " ancestor chain differs from the pinned connection")
        for pid in pin.get("chain", []):
            row = by_pid.get(pid, {})
            created = row.get("creation_filetime")
            if not created or created != pin.get("process_creations", {}).get(str(pid)):
                errors.append(label + " process creation identity differs from the pin")
        for pid, executable in (
            (java_pid, expected["java_path"]),
            (host_pid, expected["host_path"]),
        ):
            row = by_pid.get(pid, {})
            if _path(row.get("actual_image", "")) != _path(executable):
                errors.append(label + " actual process image differs from the expected executable")
            if row.get("actual_process_machine") != "0x8664":
                errors.append(label + " process architecture is not AMD64")
    for pid in pin.get("chain", []):
        if snapshots[0].get(pid) != snapshots[1].get(pid):
            errors.append("process identity changed while runtime evidence was collected")
    try:
        reported = datetime.fromisoformat(health["process_started_at"].replace("Z", "+00:00"))
        if reported.tzinfo is None:
            raise ValueError("missing timezone")
        actual = (int(snapshots[0][java_pid]["creation_filetime"]) - 116444736000000000) / 1e7
        # ProcessHandle reports millisecond precision; Windows provides 100 ns ticks.
        if abs(reported.timestamp() - actual) > 0.001:
            errors.append("health process start time differs from the actual Java process")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        errors.append("health process start identity is unavailable")

    if _path(expected["native"]["path"]) not in {_path(p) for p in modules}:
        errors.append("Windows module inventory does not contain the candidate DLL")
    jar_open_now = _path(expected["jar"]["path"]) in {_path(p) for p in open_jars}
    prior_load_matches = bool(
        verified_load
        and verified_load.get("identity", {}).get("passed") is True
        and verified_load.get("runtime_pin") == pin
        and verified_load.get("expected_identity") == expected
        and _path(expected["jar"]["path"]) in {_path(p) for p in verified_load.get("open_jars", [])}
    )
    if not jar_open_now and not prior_load_matches:
        errors.append(
            "candidate JAR is neither open nor bound by a verified load in this generation"
        )
    for name in ("native", "jar"):
        artifact = expected[name]
        try:
            if sha(Path(artifact["path"])) != artifact["sha256"]:
                errors.append(name + " backing-file hash differs from the candidate")
        except OSError:
            errors.append(name + " backing-file hash could not be read")
    return {
        "passed": not errors,
        "errors": errors,
        "java_pid": java_pid,
        "native_host_pid": host_pid,
        "service_instance_id": pin.get("service_instance_id"),
        "jar_binding": "current_open_handle" if jar_open_now else "same_generation_verified_load",
        "limits": [
            "Module/open-handle paths and backing-file hashes; memory pages are not hashed",
            "Process observations bracket the gate; no atomic OS/Creo transaction is claimed",
        ],
    }


def validate_java_candidate(
    health: dict,
    before: list[dict],
    after: list[dict],
    pin: dict,
    expected: dict,
    open_jars: list[str],
    sha: Callable[[Path], str],
) -> dict:
    """Independent Java-only observation; never admits the full native backend.

    A current open JAR handle is required. This deliberately accepts no retained
    verified-load anchor and makes no DLL-handshake or module-presence claim.
    """
    errors = []
    if health.get("ok") is not True or health.get("service") != "creo-cli":
        errors.append("health is not a running creo-cli service")
    if health.get("protocol") != 2:
        errors.append("Java runtime protocol is not 2")
    source = expected.get("source_sha256")
    if not isinstance(source, str) or not re.fullmatch(r"[a-f0-9]{64}", source):
        errors.append("expected Java source fingerprint is unavailable")
    if health.get("source_sha256") != source:
        errors.append("loaded Java source marker differs from the candidate")
    app_class = expected.get("java_app_class")
    if not isinstance(app_class, str) or not app_class or health.get("runtime_class") != app_class:
        errors.append("loaded Java entry class differs from the candidate")
    generation = pin.get("service_instance_id")
    try:
        if not isinstance(generation, str) or str(uuid.UUID(generation)) != generation.lower():
            raise ValueError("invalid UUID")
    except (ValueError, AttributeError):
        errors.append("service generation UUID is unavailable")
    if health.get("service_instance_id") != generation:
        errors.append("service generation changed since the connection was pinned")
    java_pid, host_pid = pin.get("java_pid"), pin.get("native_pid")
    if type(java_pid) is not int or type(host_pid) is not int or min(java_pid, host_pid) < 1:
        errors.append("pinned process identifiers are invalid")
    if type(health.get("process_id")) is not int or health.get("process_id") != java_pid:
        errors.append("health process differs from the pinned Java process")
    snapshots = []
    for label, rows in (("before", before), ("after", after)):
        by_pid = {row["pid"]: row for row in rows}
        snapshots.append(by_pid)
        if len(by_pid) != len(rows):
            errors.append(label + " snapshot contains duplicate process identifiers")
        chain, current = [], java_pid
        while current in by_pid and current not in chain and len(chain) < 32:
            chain.append(current)
            if current == host_pid:
                break
            child = by_pid[current]
            parent = by_pid.get(child.get("parent_pid"))
            if not parent:
                break
            try:
                if int(parent["creation_filetime"]) > int(child["creation_filetime"]):
                    errors.append(label + " parent PID was reused after the child was created")
            except (KeyError, ValueError, TypeError):
                errors.append(label + " process creation time is unavailable")
                break
            current = parent["pid"]
        if not chain or chain[-1] != host_pid or java_pid == host_pid:
            errors.append(label + " Java process is not a descendant of the declared Creo host")
        if chain != pin.get("chain"):
            errors.append(label + " ancestor chain differs from the pinned connection")
        for pid in pin.get("chain", []):
            row = by_pid.get(pid, {})
            created = row.get("creation_filetime")
            if not created or created != pin.get("process_creations", {}).get(str(pid)):
                errors.append(label + " process creation identity differs from the pin")
        for pid, executable in (
            (java_pid, expected["java_path"]),
            (host_pid, expected["host_path"]),
        ):
            row = by_pid.get(pid, {})
            if _path(row.get("actual_image", "")) != _path(executable):
                errors.append(label + " actual process image differs from the declared executable")
            if row.get("actual_process_machine") != "0x8664":
                errors.append(label + " process architecture is not AMD64")
    for pid in pin.get("chain", []):
        if snapshots[0].get(pid) != snapshots[1].get(pid):
            errors.append("process identity changed while Java runtime evidence was collected")
    try:
        reported = datetime.fromisoformat(health["process_started_at"].replace("Z", "+00:00"))
        if reported.tzinfo is None:
            raise ValueError("missing timezone")
        actual = (int(snapshots[0][java_pid]["creation_filetime"]) - 116444736000000000) / 1e7
        if abs(reported.timestamp() - actual) > 0.001:
            errors.append("health process start time differs from the actual Java process")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError):
        errors.append("health process start identity is unavailable")
    jar = expected["jar"]
    jar_open_now = _path(jar["path"]) in {_path(value) for value in open_jars}
    if not jar_open_now:
        errors.append("candidate JAR has no current open handle in the Java process")
    try:
        if sha(Path(jar["path"])) != jar["sha256"]:
            errors.append("jar backing-file hash differs from the candidate")
    except OSError:
        errors.append("jar backing-file hash could not be read")
    return {
        "passed": not errors,
        "profile": "java_component_only",
        "errors": errors,
        "java_pid": java_pid,
        "creo_host_pid": host_pid,
        "service_instance_id": generation,
        "jar_binding": "current_open_handle" if jar_open_now else "unverified",
        "native_dll_verified": False,
        "full_engineering_qualified": False,
        "limits": [
            "Java source/class, process identities and current open JAR backing-file hash only",
            "No DLL handshake, native module or native feature availability is established",
            "No retained load anchor is accepted; live memory pages are not hashed",
            "Read-only metadata; a Java-only causal trial requires explicit separate authorization",
        ],
    }


def _windows():
    if os.name != "nt":
        raise OSError("Windows runtime evidence is available only on Windows")
    from ctypes import wintypes as w

    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.argtypes, k.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
    k.CloseHandle.argtypes = [w.HANDLE]
    k.QueryFullProcessImageNameW.argtypes = [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)]
    k.GetProcessTimes.argtypes = [w.HANDLE, *([ctypes.POINTER(w.FILETIME)] * 4)]
    k.IsWow64Process2.argtypes = [w.HANDLE, ctypes.POINTER(w.USHORT), ctypes.POINTER(w.USHORT)]
    return k, w


def processes() -> list[dict]:
    k, w = _windows()

    class Entry(ctypes.Structure):
        _fields_ = [
            ("size", w.DWORD),
            ("usage", w.DWORD),
            ("pid", w.DWORD),
            ("heap", ctypes.c_size_t),
            ("module", w.DWORD),
            ("threads", w.DWORD),
            ("parent", w.DWORD),
            ("priority", w.LONG),
            ("flags", w.DWORD),
            ("name", w.WCHAR * 260),
        ]

    k.CreateToolhelp32Snapshot.argtypes, k.CreateToolhelp32Snapshot.restype = (
        [w.DWORD, w.DWORD],
        w.HANDLE,
    )
    k.Process32FirstW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    k.Process32NextW.argtypes = [w.HANDLE, ctypes.POINTER(Entry)]
    snap = k.CreateToolhelp32Snapshot(2, 0)
    if snap == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    rows = []
    try:
        entry = Entry()
        entry.size = ctypes.sizeof(entry)
        more = k.Process32FirstW(snap, ctypes.byref(entry))
        while more:
            row = {"pid": entry.pid, "parent_pid": entry.parent, "name": entry.name}
            handle = k.OpenProcess(0x1000, False, entry.pid)
            if handle:
                try:
                    image, size = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
                    if k.QueryFullProcessImageNameW(handle, 0, image, ctypes.byref(size)):
                        row["actual_image"] = image.value
                    created, exited, kernel, user = (w.FILETIME() for _ in range(4))
                    if k.GetProcessTimes(
                        handle, *(ctypes.byref(t) for t in (created, exited, kernel, user))
                    ):
                        row["creation_filetime"] = str(
                            (created.dwHighDateTime << 32) | created.dwLowDateTime
                        )
                    machine, native = w.USHORT(), w.USHORT()
                    if k.IsWow64Process2(handle, ctypes.byref(machine), ctypes.byref(native)):
                        row["actual_process_machine"] = hex(machine.value or native.value)
                finally:
                    k.CloseHandle(handle)
            rows.append(row)
            more = k.Process32NextW(snap, ctypes.byref(entry))
    finally:
        k.CloseHandle(snap)
    return rows


def modules(pid: int) -> list[str]:
    k, w = _windows()
    handle = k.OpenProcess(0x410, False, pid)
    if not handle:
        raise ctypes.WinError(ctypes.get_last_error())
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.EnumProcessModulesEx.argtypes = [
        w.HANDLE,
        ctypes.POINTER(w.HMODULE),
        w.DWORD,
        ctypes.POINTER(w.DWORD),
        w.DWORD,
    ]
    psapi.GetModuleFileNameExW.argtypes = [w.HANDLE, w.HMODULE, w.LPWSTR, w.DWORD]
    try:
        array, needed = (w.HMODULE * 8192)(), w.DWORD()
        if not psapi.EnumProcessModulesEx(
            handle, array, ctypes.sizeof(array), ctypes.byref(needed), 3
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        if needed.value > ctypes.sizeof(array):
            raise OSError("process module inventory exceeds bounded capacity")
        paths = []
        for module in array[: needed.value // ctypes.sizeof(w.HMODULE)]:
            path = ctypes.create_unicode_buffer(32768)
            if not psapi.GetModuleFileNameExW(handle, module, path, len(path)):
                raise ctypes.WinError(ctypes.get_last_error())
            paths.append(path.value)
        return paths
    finally:
        k.CloseHandle(handle)


def open_jars(pid: int) -> list[str]:
    """Query disk file handles only; no JVM attach, injection or registry change."""
    k, w = _windows()
    ntdll = ctypes.WinDLL("ntdll")
    ntdll.NtQuerySystemInformation.argtypes = [
        w.ULONG,
        ctypes.c_void_p,
        w.ULONG,
        ctypes.POINTER(w.ULONG),
    ]
    ntdll.NtQuerySystemInformation.restype = w.LONG
    size = 1 << 20
    while size <= 128 << 20:
        buffer, needed = ctypes.create_string_buffer(size), w.ULONG()
        status = ntdll.NtQuerySystemInformation(64, buffer, size, ctypes.byref(needed))
        if status == 0:
            break
        if status & 0xFFFFFFFF != 0xC0000004:
            raise OSError("Windows handle inventory refused: " + hex(status & 0xFFFFFFFF))
        size = max(size * 2, needed.value)
    else:
        raise OSError("system handle inventory exceeds bounded capacity")

    class Entry(ctypes.Structure):
        _fields_ = [
            ("object", ctypes.c_size_t),
            ("pid", ctypes.c_size_t),
            ("handle", ctypes.c_size_t),
            ("access", w.ULONG),
            ("backtrace", w.USHORT),
            ("type", w.USHORT),
            ("attributes", w.ULONG),
            ("reserved", w.ULONG),
        ]

    count = ctypes.c_size_t.from_buffer(buffer).value
    offset = ctypes.sizeof(ctypes.c_size_t) * 2
    if offset + count * ctypes.sizeof(Entry) > size:
        raise OSError("Windows handle inventory is truncated")
    source = k.OpenProcess(0x40, False, pid)
    if not source:
        raise ctypes.WinError(ctypes.get_last_error())
    k.GetCurrentProcess.restype = w.HANDLE
    k.DuplicateHandle.argtypes = [
        w.HANDLE,
        w.HANDLE,
        w.HANDLE,
        ctypes.POINTER(w.HANDLE),
        w.DWORD,
        w.BOOL,
        w.DWORD,
    ]
    k.GetFileType.argtypes = [w.HANDLE]
    k.GetFinalPathNameByHandleW.argtypes = [w.HANDLE, w.LPWSTR, w.DWORD, w.DWORD]
    paths = set()
    try:
        for index in range(count):
            entry = Entry.from_buffer(buffer, offset + index * ctypes.sizeof(Entry))
            if entry.pid != pid:
                continue
            duplicate = w.HANDLE()
            if not k.DuplicateHandle(
                source, entry.handle, k.GetCurrentProcess(), ctypes.byref(duplicate), 0, False, 2
            ):
                continue
            try:
                if k.GetFileType(duplicate) != 1:
                    continue
                path = ctypes.create_unicode_buffer(32768)
                length = k.GetFinalPathNameByHandleW(duplicate, path, len(path), 0)
                if 0 < length < len(path) and path.value.lower().endswith(".jar"):
                    value = path.value
                    paths.add(value[4:] if value.startswith("\\\\?\\") else value)
            finally:
                k.CloseHandle(duplicate)
    finally:
        k.CloseHandle(source)
    return sorted(paths)
