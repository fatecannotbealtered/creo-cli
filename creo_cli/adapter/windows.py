"""What the adapter asks Windows: the running Creo processes and the windows that block them.

Creo Parametric runs as ``xtop.exe``, and its Java applications, the host component among them,
in a ``java.exe`` it starts. A modal dialog disables the window it belongs to, so a Creo process
whose own top-level window is disabled is held by a dialog; the dialog is the enabled window of
that process, and its title says what it is.
"""
from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes
from typing import Any

WINDOWS = sys.platform == "win32"
TH32CS_SNAPPROCESS = 0x2
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
GW_OWNER = 4


class PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD), ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t), ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long), ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def _kernel() -> Any:
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                  ctypes.POINTER(wintypes.DWORD)]
    return kernel


def _entries() -> list[tuple[int, int, str]]:
    """Every running process: its ID, its parent's ID and its executable name in lower case."""
    if not WINDOWS:
        return []
    kernel = _kernel()
    snapshot = kernel.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snapshot or snapshot == wintypes.HANDLE(-1).value:
        return []
    found = []
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        more = kernel.Process32FirstW(snapshot, ctypes.byref(entry))
        while more:
            found.append((int(entry.th32ProcessID), int(entry.th32ParentProcessID), entry.szExeFile.lower()))
            more = kernel.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel.CloseHandle(snapshot)
    return found


def processes(name: str = "xtop.exe") -> list[int]:
    """The IDs of the running processes with this executable name."""
    return sorted(pid for pid, _, exe in _entries() if exe == name)


def started_by(root: int, name: str = "xtop.exe") -> list[int]:
    """The processes with this executable name that root started, itself or through the processes
    it started, such as the xtop.exe that parametric.exe starts."""
    entries = _entries()
    parent_of = {pid: parent for pid, parent, _ in entries}
    found = []
    for pid, parent, exe in entries:
        seen = set()
        while exe == name and parent and parent not in seen:
            if parent == root:
                found.append(pid)
                break
            seen.add(parent)
            parent = parent_of.get(parent, 0)
    return sorted(found)


def java_children(pid: int) -> list[int]:
    """The Java processes a Creo process started to run its Java applications in."""
    return sorted(child for child, parent, exe in _entries() if parent == pid and exe in ("java.exe", "javaw.exe"))


def image_path(pid: int) -> str | None:
    """The full path of a process's executable, or None when it cannot be read."""
    if not WINDOWS:
        return None
    kernel = _kernel()
    handle = kernel.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(1024)
        buffer = ctypes.create_unicode_buffer(1024)
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return None
        return buffer.value
    finally:
        kernel.CloseHandle(handle)


MAIN_TITLE = re.compile(r"(^| - )Creo Parametric \d+(\.\d+)*$")


def is_main_title(title: str) -> bool:
    """A Creo main window: "DISC - Creo Parametric 13", or "Creo Parametric 13" with no model."""
    return bool(MAIN_TITLE.search(title))


def blocker(pid: int) -> str | None:
    """The title of the dialog that holds this process, or None when nothing holds it.

    The process is held when a visible top-level window of it is a dialog: a titled window
    that is not a main window, or any window while a main window is disabled. Creo 13.4 does
    not disable its main window under a modal dialog (measured with File > Options and a
    toolkit message dialog), so the title tells them apart; a modeless Creo window also
    counts, which errs on the side of the person. Every titled window of the Java process Creo
    started counts too: a Java application's dialog holds the Java applications started after
    it, the host component among them (measured with a Swing dialog while Creo 13.4 starts).
    The title is the application's own text: untrusted.
    """
    if not WINDOWS:
        return None
    user = ctypes.WinDLL("user32", use_last_error=True)
    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user.EnumWindows.argtypes = [enum_proc, wintypes.LPARAM]
    user.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user.IsWindowVisible.argtypes = [wintypes.HWND]
    user.IsWindowEnabled.argtypes = [wintypes.HWND]
    user.GetWindow.restype = wintypes.HWND
    user.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    mains: list[tuple[int, bool]] = []
    others: list[str] = []
    java = set(java_children(pid))

    def visit(hwnd: int, _: int) -> bool:
        owner = wintypes.DWORD()
        user.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if (owner.value != pid and owner.value not in java) or not user.IsWindowVisible(hwnd):
            return True
        enabled = bool(user.IsWindowEnabled(hwnd))
        title = ctypes.create_unicode_buffer(512)
        user.GetWindowTextW(hwnd, title, 512)
        if owner.value in java or user.GetWindow(hwnd, GW_OWNER) or not is_main_title(title.value):
            if enabled and title.value:
                others.append(title.value)
        else:
            mains.append((hwnd, enabled))
        return True

    user.EnumWindows(enum_proc(visit), 0)
    if others:
        return others[0]
    if mains and any(not enabled for _, enabled in mains):
        return ""
    return None
