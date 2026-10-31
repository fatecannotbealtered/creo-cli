"""Explicit owned empty-session termination, verified without post-exit CAD calls."""

from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from . import binding_diagnostics, deployment, engine, operations, paths, runtime_identity, timing
from .core import Error, decode

ENTRYPOINT = "ProEngineerEnd"
MAX_EXIT_MS = 30000
MAX_NATIVE_PREPARATION_BYTES = 8 * 1024 * 1024
UNSIGNED_NATIVE_PROFILE = "creo-13.4.1.0-unsigned-native"
CONFIGURATION_CATALOG_SHA256 = "61c54d38d025d416dc660f070b4634a6c603cbe11f71cc25a1fe395d2f73b649"


def _refuse(code, message):
    raise Error(code, message, {"dispatch_state": "not_started", "automatic_retry": False})


def _required(condition):
    if not condition:
        raise ValueError("owned launch proof is incomplete")


def _regular(path):
    path = Path(path)
    for parent in (path, *path.parents):
        info = parent.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            _refuse("E_FORBIDDEN", "owned-exit paths must not contain links or reparse points")
    return path


def fingerprint(path, *, max_bytes=None):
    path = _regular(path)
    before = path.stat()
    if max_bytes is None:
        raw = path.read_bytes()
    else:
        _required(type(max_bytes) is int and max_bytes > 0)
        _required(before.st_size <= max_bytes)
        with path.open("rb") as stream:
            raw = stream.read(max_bytes + 1)
        _required(len(raw) <= max_bytes)
    after = path.stat()

    def identity(s):
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns

    if identity(before) != identity(after):
        _refuse("E_CONFLICT", "owned-exit evidence changed while reading")
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}, raw


def _recovery_evidence(launch, runtime):
    """Prove fresh recovery storage and the same ready observation for this seat.

    Runtime directory contents change during normal Creo use. Only fixed startup
    inputs and complete recorded native/OS observations enter this binding.
    """
    _required(launch["recovery_isolation_verified"] is True)
    declared = launch["recovery_isolation"]

    def same_snapshot(left, right):
        return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(
            right, sort_keys=True, allow_nan=False
        )

    _required(same_snapshot(declared, launch["deployment_preflight"]["recovery_isolation"]))
    _required(declared["new_paths_before_launch"] is True)
    _required(declared["empty_before_dispatch"] is True)
    _required(declared["previous_recovery_data_read_copied_removed"] is False)
    _required(declared["recording"] == "yes")
    _required(_regular(runtime).is_dir())

    def directory(value, expected):
        _required(isinstance(value, str) and 0 < len(value) <= 32767)
        _required('"' not in value and not any(ord(char) < 32 for char in value))
        _required(Path(value).is_absolute())
        _required(engine.same_path(value, expected))
        _regular(value)  # Check raw traversal components before lexical canonicalization.
        path = paths.contained(os.path.abspath(value), directory=True)
        _required(engine.same_path(path, expected) and _regular(path).is_dir())
        return str(path)

    workflow = directory(declared["workflow_root"], runtime / "wfroot")
    history = directory(declared["last_session_directory_path"], runtime / "session-history")
    startup = Path(launch["startup"])
    configured = declared["configured_directory_value"]
    _required(isinstance(configured, str) and configured not in ("", "."))
    _required(not Path(configured).is_absolute())
    _required(all(0x21 <= ord(char) <= 0x7E and char not in '":!#' for char in configured))
    _required(configured == os.path.relpath(history, startup))
    _required(engine.same_path(startup / configured, history))
    actual = launch["recovery_configuration"]
    session = launch["session_readiness"]
    _required(type(launch["session_readiness_attempts"]) is int)
    _required(launch["session_readiness_attempts"] == 1)
    _required(session["ok"] is True and session["session_reachable"] is True)
    _required(same_snapshot(actual, session["recovery_configuration"]))
    _required(actual["complete"] is True)
    _required(
        actual["workflow_root_source"]
        == "Java process environment inherited from owned Creo launcher"
    )
    _required(
        actual["configuration_source"]
        == "BaseSession.GetConfigOptionValues(last_session_directory_path)"
        "/GetConfigOption(last_session_retrieval)"
    )
    directory(actual["workflow_root"], runtime / "wfroot")
    directory(actual["last_session_directory_path"], runtime / "session-history")
    _required(type(actual["last_session_directory_path_value_count"]) is int)
    _required(actual["last_session_directory_path_value_count"] == 1)
    _required(isinstance(actual["last_session_retrieval"], str))
    _required(actual["last_session_retrieval"].lower() == "yes")
    for option in ("last_session_directory_path", "last_session_retrieval"):
        _required(actual[option + "_readback"] == "observed")
        _required(actual.get(option + "_error_class") is None)
    generated = launch["deployment_preflight"]["generated_startup_files"]
    _required(isinstance(generated, list) and len(generated) == 3)
    fixed_files, raw_files = {}, {}
    for expected in generated:
        name = Path(expected["path"]).name
        _required(name in {"protk.dat", "config.pro", "process-launch-spec.json"})
        _required(name not in fixed_files and engine.same_path(expected["path"], startup / name))
        _required(type(expected["bytes"]) is int and expected["bytes"] > 0)
        _required(isinstance(expected["sha256"], str))
        _required(re.fullmatch("[a-f0-9]{64}", expected["sha256"]) is not None)
        observed, raw = fingerprint(expected["path"])
        _required(observed["sha256"] == expected["sha256"])
        _required(observed["bytes"] == expected["bytes"])
        fixed_files[name], raw_files[name] = observed, raw
    _required(len(raw_files["config.pro"]) <= 65536)
    settings = {}
    for line in raw_files["config.pro"].decode("utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith(("!", "#")):
            continue
        parts = line.split(maxsplit=1)
        key = parts[0].lower()
        if key in {"last_session_directory_path", "last_session_retrieval"}:
            _required(len(parts) == 2 and key not in settings)
            settings[key] = parts[1]
    _required(settings["last_session_directory_path"] == configured)
    _required(settings["last_session_retrieval"].lower() == "yes")
    _required(len(raw_files["process-launch-spec.json"]) <= 1024 * 1024)
    spec = json.loads(raw_files["process-launch-spec.json"].decode("utf-8-sig"))
    _required(engine.same_path(spec["working_directory"], startup))
    _required(engine.same_path(spec["environment"]["CREO_CLI_CONFIG_DIR"], runtime))
    _required(engine.same_path(spec["environment"]["PTC_WF_ROOT"], workflow))
    pin = launch["runtime_pin"]
    source = launch["health"]["source_sha256"]
    _required(isinstance(source, str) and re.fullmatch("[a-f0-9]{64}", source) is not None)
    windows = launch["recovery_window_observations"]
    _required(isinstance(windows, list) and len(windows) == 2)
    before = datetime.fromisoformat(launch["started_before_utc"].replace("Z", "+00:00"))
    previous_time = before
    for phase, observation in zip(
        ("before_authenticated_readiness", "after_authenticated_readiness"), windows, strict=True
    ):
        _required(observation["phase"] == phase)
        _required(type(observation["native_pid"]) is int)
        _required(observation["native_pid"] == pin["native_pid"])
        _required(isinstance(observation["native_creation_filetime"], str))
        _required(observation["native_creation_filetime"].isdigit())
        _required(
            observation["native_creation_filetime"]
            == pin["process_creations"][str(pin["native_pid"])]
        )
        _required(observation["service_instance_id"] == pin["service_instance_id"])
        _required(observation["component_source_sha256"] == source)
        _required(
            observation["source"]
            == "OS EnumWindows/GetWindowThreadProcessId; only exact owned native PID; read-only"
        )
        _required(observation["recovery_dialogs"] == [])
        _required(observation["visible_windows_only"] is True)
        for count in ("desktop_input_count", "CUA_input_count"):
            _required(type(observation[count]) is int and observation[count] == 0)
        _required(isinstance(observation["at_utc"], str))
        when = datetime.fromisoformat(observation["at_utc"].replace("Z", "+00:00"))
        _required(when.utcoffset() is not None and when.utcoffset().total_seconds() == 0)
        _required(when >= previous_time)
        since_1601 = when - datetime(1601, 1, 1, tzinfo=UTC)
        ticks = (
            since_1601.days * 86400 + since_1601.seconds
        ) * 10_000_000 + since_1601.microseconds * 10
        _required(int(observation["native_creation_filetime"]) <= ticks)
        previous_time = when
    return {
        "workflow_root": workflow,
        "last_session_directory_path": history,
        "configured_directory_value": configured,
        "empty_before_dispatch": declared["empty_before_dispatch"],
        "fixed_startup_files": fixed_files,
        "native_observation": copy.deepcopy(actual),
        "owned_window_observations": copy.deepcopy(windows),
        "directory_contents_hashed": False,
    }


def _policy_evidence(launch, creo, installation):
    """Retain the full-policy route or prove the exact scoped unsigned profile.

    A recorded applicable boolean cannot substitute for its native observations,
    ordinary-unlock evidence, current files and precise installed-version scope.
    """
    preflight = launch.get("deployment_preflight")
    trial = preflight.get("internal_trial") if isinstance(preflight, dict) else None
    profile = trial.get("policy_profile") if isinstance(trial, dict) else None
    if launch.get("deployment_policy_verified") is True and profile != UNSIGNED_NATIVE_PROFILE:
        return None  # Existing formal/default full-policy contract remains unchanged.
    _required(isinstance(preflight, dict) and isinstance(trial, dict))
    _required(preflight["trust_policy_requested"] == "internal-unsigned-trial")
    _required(profile == UNSIGNED_NATIVE_PROFILE)
    _required(launch["qualification"] == "internal_unsigned_full_components_automatic_startup")
    for key, expected in (
        ("deployment_policy_verified", False),
        ("applicable_policy_verified", True),
        ("signed_apps_verified", False),
        ("full_policy_option_set_verified", False),
    ):
        _required(launch[key] is expected)
    _required(preflight["internal_isolation"]["complete"] is True)
    _required(trial["unlock_mode"] == "-c" and trial["toolkit_unlocked"] is True)
    _required(trial["authenticode_verified"] is False)
    qualified = trial["policy_profile_qualification"]
    _required(qualified["profile"] == UNSIGNED_NATIVE_PROFILE)
    _required(qualified["product_version"] == "13.4.1.0")
    _required(qualified["file_version"] == "41,0,2026,163")
    _required(qualified["applicable_configuration"] == {"open_protk_unsigned_apps": "always"})
    _required(qualified["signed_apps_verified"] is False)
    _required(qualified["full_policy_option_set_verified"] is False)
    observed_files = {}

    def bound_file(name, expected, at_path=None, *, max_bytes=None):
        _required(isinstance(expected, dict) and isinstance(expected["path"], str))
        _required(Path(expected["path"]).is_absolute())
        _required(not expected["path"].startswith("\\\\"))
        _required(isinstance(expected["sha256"], str))
        _required(re.fullmatch("[a-f0-9]{64}", expected["sha256"]) is not None)
        _required(type(expected["bytes"]) is int and expected["bytes"] > 0)
        if max_bytes is not None:
            _required(expected["bytes"] <= max_bytes)
        if at_path is not None:
            _required(engine.same_path(expected["path"], at_path))
        actual, raw = fingerprint(expected["path"], max_bytes=max_bytes)
        _required(actual["sha256"] == expected["sha256"])
        _required(actual["bytes"] == expected["bytes"])
        observed_files[name] = actual
        return raw

    bound_file(
        "native_host", qualified["native_host"], creo / "Common Files/x86e_win64/obj/xtop.exe"
    )
    catalog = qualified["configuration_catalog"]
    _required(catalog["sha256"] == CONFIGURATION_CATALOG_SHA256)
    bound_file(
        "configuration_catalog",
        catalog,
        creo / "Common Files/help/reference/pma/usascii/configoptions.pdf",
    )
    files = trial["files"]
    _required(set(files) == {"creo-cli.exe", "creo-cli-service.jar", "creo_cli_sketch.dll"})
    for name in sorted(files):
        target = (
            paths.contained(files[name]["path"]) if name == "creo-cli.exe" else installation / name
        )
        bound_file(name, files[name], target)
    bound_file("registry", trial["registry"], installation / "protk.dat")
    preparation_raw = bound_file(
        "native_preparation", trial["native_preparation"], max_bytes=MAX_NATIVE_PREPARATION_BYTES
    )
    _required(len(preparation_raw) <= MAX_NATIVE_PREPARATION_BYTES)
    preparation = json.loads(preparation_raw.decode("utf-8-sig"))
    _required(preparation["status"] == "ordinary_unlocked_internal_unsigned")
    _required(preparation["unlock_mode"] == "-c" and preparation["toolkit_unlocked"] is True)
    _required(preparation["authenticode_status"] == "NotSigned")
    unlock = preparation["ordinary_unlock"]
    _required(type(unlock["exit_code"]) is int and unlock["exit_code"] == 0)
    _required(unlock["success_marker"] == "Successfully unlocked application.")
    _required(type(preparation["dll"]["bytes"]) is int)
    for key in ("sha256", "bytes"):
        _required(preparation["dll"][key] == files["creo_cli_sketch.dll"][key])
    signature = preflight["native_signature"]
    _required(signature["status"] == "NotSigned" and signature["signature_type"] == "None")
    _required(signature["authenticode_verified"] is False)
    _required(signature["publisher_pin_matched"] is False)
    _required(signature["signer_thumbprint"] is None and signature["signer_subject"] is None)
    _required(signature["timestamp_present"] is False)
    _required(engine.same_path(signature["path"], installation / "creo_cli_sketch.dll"))
    _required(signature["sha256"] == files["creo_cli_sketch.dll"]["sha256"])
    policy = launch["effective_deployment_policy"]
    _required(policy["policy_profile"] == UNSIGNED_NATIVE_PROFILE)
    _required(policy["complete"] is False and policy["signed_apps"] is None)
    _required(policy["applicable_policy_verified"] is True)
    _required(policy["signed_apps_verified"] is False)
    _required(policy["full_policy_option_set_verified"] is False)
    _required(
        isinstance(policy["unsigned_apps"], str) and policy["unsigned_apps"].lower() == "always"
    )
    _required(
        policy["source"]
        == "BaseSession.GetConfigOption(open_protk_signed_apps/open_protk_unsigned_apps)"
    )
    signed, unsigned = policy["signed_observation"], policy["unsigned_observation"]
    for kind, observation in (("signed", signed), ("unsigned", unsigned)):
        _required(observation["option"] == f"open_protk_{kind}_apps")
        _required(observation["raw_truncated"] is False)
        _required(
            all(key in observation for key in ("raw", "exception_category", "exception_class"))
        )
    _required(unsigned["status"] == "recognized" and isinstance(unsigned["raw"], str))
    _required(len(unsigned["raw"]) <= 64 and unsigned["raw"].strip().lower() == "always")
    _required(unsigned["exception_category"] is None and unsigned["exception_class"] is None)
    no_signed_failure = signed["exception_category"] is None and signed["exception_class"] is None
    _required(
        signed["status"] == "unsupported_null"
        and signed["raw"] is None
        and no_signed_failure
        or signed["status"] == "unsupported_empty"
        and signed["raw"] == ""
        and no_signed_failure
        or signed["status"] == "unsupported_not_found"
        and signed["raw"] is None
        and signed["exception_category"] == "XToolkitNotFound"
        and isinstance(signed["exception_class"], str)
        and 0 < len(signed["exception_class"]) <= 256
    )
    return {
        "policy_profile": profile,
        "files": observed_files,
        "actual_policy": copy.deepcopy(policy),
        "recovery_evidence": _recovery_evidence(
            launch, paths.contained(launch["runtime"], directory=True)
        ),
    }


def _new_json(path, value):
    with Path(path).open("xb") as stream:
        stream.write((json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode())
        stream.flush()
        os.fsync(stream.fileno())


class ProcessHandle:
    """Read-only handle to one exact Windows process, never a termination handle."""

    def __init__(self, pid, birth, image):
        if os.name != "nt":
            _refuse("E_UNSUPPORTED", "owned-session exit requires Windows process identity")
        if type(pid) is not int or not 0 < pid <= 0xFFFFFFFF:
            _refuse("E_VALIDATION", "owned process PID must be a positive Windows DWORD")
        from ctypes import wintypes as w

        self.k, self.w = ctypes.WinDLL("kernel32", use_last_error=True), w
        k = self.k
        k.OpenProcess.argtypes, k.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        k.CloseHandle.argtypes = [w.HANDLE]
        k.GetProcessTimes.argtypes = [w.HANDLE, *([ctypes.POINTER(w.FILETIME)] * 4)]
        k.QueryFullProcessImageNameW.argtypes = [
            w.HANDLE,
            w.DWORD,
            w.LPWSTR,
            ctypes.POINTER(w.DWORD),
        ]
        k.WaitForSingleObject.argtypes, k.WaitForSingleObject.restype = [w.HANDLE, w.DWORD], w.DWORD
        k.GetExitCodeProcess.argtypes = [w.HANDLE, ctypes.POINTER(w.DWORD)]
        k.GetTickCount64.restype = ctypes.c_ulonglong
        self.pid, self.birth, self.image = pid, str(birth), str(Path(image))
        self._verified_identity = None
        self._termination_started = False
        self.handle = k.OpenProcess(0x100000 | 0x1000, False, pid)
        if not self.handle:
            failure = self._api_error(
                "cannot hold the exact owned xtop process handle", "OpenProcess", "open_handle"
            )
            failure.details.update(dispatch_state="not_started", automatic_retry=False)
            raise failure
        try:
            observed = self.observe()
            if not observed["alive"]:
                _refuse("E_CONFLICT", "owned native process already exited before dispatch")
        except BaseException:
            self.close()
            raise

    def _api_error(self, message, api, stage):
        # Capture immediately: a later successful API call may replace this code.
        return Error(
            "E_VERIFY_INCOMPLETE",
            message,
            {
                "windows_api": api,
                "win32_error": ctypes.get_last_error(),
                "process_observation_stage": stage,
            },
        )

    def _wait(self):
        waited = self.k.WaitForSingleObject(self.handle, 0)
        if waited not in (0, 258):
            failure = self._api_error(
                "held process wait state is unavailable", "WaitForSingleObject", "wait_state"
            )
            failure.details["wait_result"] = waited
            if waited != 0xFFFFFFFF:
                failure.details.pop("win32_error")  # Not a documented GetLastError failure.
            raise failure
        return waited

    def _times(self):
        w, k = self.w, self.k
        created, exited, kernel, user = w.FILETIME(), w.FILETIME(), w.FILETIME(), w.FILETIME()
        if not k.GetProcessTimes(
            self.handle, *[ctypes.byref(v) for v in (created, exited, kernel, user)]
        ):
            raise self._api_error(
                "held process creation identity is unavailable",
                "GetProcessTimes",
                "creation_and_exit_times",
            )
        birth = str((created.dwHighDateTime << 32) | created.dwLowDateTime)
        if birth != self.birth:
            raise Error("E_CONFLICT", "held process does not match the exact owned native identity")
        return birth, str((exited.dwHighDateTime << 32) | exited.dwLowDateTime)

    def _live_image(self):
        w, k = self.w, self.k
        size, name = w.DWORD(32768), ctypes.create_unicode_buffer(32768)
        if not k.QueryFullProcessImageNameW(self.handle, 0, name, ctypes.byref(size)):
            raise self._api_error(
                "held native executable identity is unavailable",
                "QueryFullProcessImageNameW",
                "live_image_identity",
            )
        if not engine.same_path(name.value, self.image):
            raise Error("E_CONFLICT", "held process does not match the exact owned native identity")
        return name.value

    def _identity(self):
        identity = self._verified_identity
        if identity is None:
            raise Error("E_CONFLICT", "held process image identity has not been verified")
        if identity["creation_filetime"] != self.birth or not engine.same_path(
            identity["image"], self.image
        ):
            raise Error("E_CONFLICT", "held process does not match the exact owned native identity")
        return identity

    def _terminal(self):
        identity = self._identity()
        # The exit FILETIME is undefined before termination. Always read it AFTER
        # this same handle signaled, including an alive-to-exited image-query race.
        birth, exited = self._times()
        if exited == "0":
            raise Error(
                "E_VERIFY_INCOMPLETE",
                "held process exit time is unavailable",
                {"windows_api": "GetProcessTimes", "process_observation_stage": "exit_time"},
            )
        value = self.w.DWORD()
        if not self.k.GetExitCodeProcess(self.handle, ctypes.byref(value)):
            raise self._api_error(
                "native process exit code is unavailable", "GetExitCodeProcess", "exit_code"
            )
        return self._state(
            birth,
            identity["image"],
            False,
            value.value,
            exited,
            "cached image verified on same held handle while alive",
            identity["at_utc"],
        )

    def _state(self, birth, image, alive, code, exited, image_source, image_at):
        return {
            "pid": self.pid,
            "creation_filetime": birth,
            "image": image,
            "image_source": image_source,
            "image_verified_at_utc": image_at,
            "observation_phase": "termination_dispatch"
            if self._termination_started
            else "live_identity_validation",
            "alive": alive,
            "signaled": not alive,
            "exit_code": code,
            "exit_filetime": exited,
            "source": "held Windows process handle; "
            "GetProcessTimes/WaitForSingleObject/GetExitCodeProcess",
        }

    def observe(self):
        if not self.handle:
            raise Error("E_VERIFY_INCOMPLETE", "original held process handle is closed")
        if self._wait() == 0:
            return self._terminal()
        if self._termination_started:
            identity = self._identity()
            birth, _ = self._times()
            if self._wait() == 0:
                return self._terminal()
            return self._state(
                birth,
                identity["image"],
                True,
                None,
                None,
                "cached image verified on same held handle while alive",
                identity["at_utc"],
            )
        birth, _ = self._times()
        try:
            image = self._live_image()
        except Error as exc:
            if exc.code != "E_VERIFY_INCOMPLETE" or self._wait() != 0:
                raise
            return self._terminal()
        if self._wait() == 0:
            return self._terminal()
        at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        if self._verified_identity is None:
            self._verified_identity = {"creation_filetime": birth, "image": image, "at_utc": at}
        return self._state(
            birth,
            image,
            True,
            None,
            None,
            "QueryFullProcessImageNameW on same held handle while alive",
            at,
        )

    def begin_termination(self):
        """Freshly verify identity before the single bound native exit dispatch.

        The same held Windows process object keeps its identity while shutting
        down. Its image query may become unavailable before its wait signals;
        only image provenance is cached, never creation/wait/exit state.
        """
        if self._termination_started:
            _refuse("E_CONFLICT", "owned process termination dispatch was already prepared")
        if not self.observe()["alive"]:
            _refuse("E_CONFLICT", "owned native process exited before dispatch")
        self._identity()
        self._termination_started = True

    def tick(self):
        return int(self.k.GetTickCount64())

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None


def prepare(opts):
    path = paths.contained(opts["launch_record"])
    file, raw = fingerprint(path)
    if len(raw) > 1024 * 1024:
        _refuse("E_VALIDATION", "owned launch record exceeds its bound")
    try:
        launch = json.loads(raw.decode("utf-8-sig"))
        pin = launch["runtime_pin"]
        _required(launch["status"] == "ready")
        _required(launch["require_native"] is True and launch["native_load_verified"] is True)
        _required(launch.get("ownership", "owned") == "owned")
        _required(type(launch["launcher_pid"]) is int and launch["launcher_pid"] > 0)
        _required(str(launch["launcher_creation_filetime"]).isdigit())
        _required(launch["argument_transport"] == "ProcessStartInfo.ArgumentList")
        _required(launch["desktop_input_count"] == 0 and launch["cua_input_count"] == 0)
        before = datetime.fromisoformat(launch["started_before_utc"].replace("Z", "+00:00"))
        _required(before.utcoffset() is not None)
        _required(type(pin["native_pid"]) is int and pin["native_pid"] > 0)
        _required(str(pin["process_creations"][str(pin["native_pid"])]).isdigit())
        _required(pin["service_instance_id"] == launch["health"]["service_instance_id"])
        runtime = paths.contained(launch["runtime"], directory=True)
        installation = paths.contained(launch["installation"], directory=True)
        _required(Path(launch["startup"]).resolve() == path.parent.resolve())
        creo = Path(launch["executable"]).parents[2]
        java = Path(launch["java_executable"]).parent.parent
        policy_evidence = _policy_evidence(launch, creo, installation)
        producer_file, producer_raw = fingerprint(path.parent / "launcher-process.json")
        producer = json.loads(producer_raw.decode("utf-8-sig"))
        _required(producer["launcher_pid"] == launch["launcher_pid"])
        _required(producer["launcher_creation_filetime"] == launch["launcher_creation_filetime"])
        _required(producer["process_host_pid"] == launch["process_host_pid"])
        _required(producer["input_method"] == "ProcessStartInfo.ArgumentList")
        _required(producer["desktop_inputs"] == 0 and producer["CUA_inputs"] == 0)
        _required(engine.same_path(producer["executable"], launch["executable"]))
        _required(producer["arguments"] == launch["launch_arguments"])
    except (KeyError, TypeError, ValueError, AssertionError, IndexError, OSError) as exc:
        raise Error(
            "E_FORBIDDEN",
            "a complete, full-component owned ready launch record is required",
            {"dispatch_state": "not_started", "automatic_retry": False},
        ) from exc
    return {
        "path": path,
        "file": file,
        "launch": launch,
        "pin": pin,
        "runtime": runtime,
        "installation": installation,
        "creo": creo,
        "java": java,
        "producer_file": producer_file,
        "policy_evidence": policy_evidence,
    }


def native_launcher_link(pid):
    """Narrow read-only WMI query; retain parsed -ppid, never raw command lines."""
    if type(pid) is not int or pid < 1 or os.name != "nt":
        _refuse("E_VERIFY_INCOMPLETE", "owned native launcher association is unavailable")
    shell = shutil.which("pwsh") or shutil.which("powershell")
    if not shell:
        _refuse("E_BACKEND_UNAVAILABLE", "PowerShell is required for the owned launcher link query")
    script = (
        "$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false);"
        f"$p=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}';"
        "if($null-eq$p){throw 'native process absent'};"
        "$m=[regex]::Match([string]$p.CommandLine,'(?:^|\\s)-ppid\\s+(?<id>[0-9]+)(?:\\s|$)');"
        "if(-not$m.Success){throw 'native launcher link absent'};"
        "@{pid=[int]$p.ProcessId;launcher_pid=[int]$m.Groups['id'].Value}|ConvertTo-Json -Compress"
    )
    try:
        result = subprocess.run(
            [shell, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            timeout=8,
            creationflags=0x08000000,
            check=True,
        )
        return json.loads(result.stdout.decode("utf-8-sig"))
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise Error(
            "E_VERIFY_INCOMPLETE",
            "fresh native -ppid launcher association cannot be established",
            {"dispatch_state": "not_started", "automatic_retry": False},
        ) from exc


def ownership(pre, rows, link):
    launch, pin = pre["launch"], pre["pin"]
    by_pid = {row["pid"]: row for row in rows}
    native = by_pid.get(pin["native_pid"])
    launch_birth = str(launch["launcher_creation_filetime"])
    native_birth = str(pin["process_creations"][str(pin["native_pid"])])
    before = datetime.fromisoformat(launch["started_before_utc"].replace("Z", "+00:00"))
    since_1601 = before - datetime(1601, 1, 1, tzinfo=UTC)
    before_tick = (
        since_1601.days * 86400 + since_1601.seconds
    ) * 10_000_000 + since_1601.microseconds * 10
    if (
        not native
        or native.get("creation_filetime") != native_birth
        or not engine.same_path(
            native.get("actual_image", ""), pre["creo"] / "Common Files/x86e_win64/obj/xtop.exe"
        )
        or link != {"pid": pin["native_pid"], "launcher_pid": launch["launcher_pid"]}
        or not before_tick <= int(launch_birth) <= int(native_birth)
    ):
        _refuse("E_FORBIDDEN", "native process is not bound to this owned launcher generation")
    launcher = by_pid.get(launch["launcher_pid"])
    state = "launcher_gone_with_durable_birth_and_live_native_ppid"
    if launcher:
        birth = launcher.get("creation_filetime")
        if birth == launch_birth:
            if not engine.same_path(launcher.get("actual_image", ""), launch["executable"]):
                _refuse("E_FORBIDDEN", "owned launcher executable differs")
            state = "fresh_matching_launcher_and_live_native_ppid"
        elif not birth or not birth.isdigit() or int(birth) <= int(native_birth):
            _refuse("E_FORBIDDEN", "launcher PID is reused or ambiguous before native creation")
        else:
            state = "old_launcher_gone_PID_reused_after_native_birth_with_durable_old_link"
    return {
        "state": state,
        "launcher_pid": launch["launcher_pid"],
        "launcher_creation_filetime": launch_birth,
        "native_pid": pin["native_pid"],
        "native_creation_filetime": native_birth,
        "live_native_ppid": link["launcher_pid"],
        "producer_file": pre["producer_file"],
    }


def _no_unresolved(instance):
    for run in operations.selected_runs(statuses=operations.UNRESOLVED):
        if run.get("status") not in operations.UNRESOLVED or run.get("driver_resolution"):
            continue
        plan = run.get("driver_plan") or {}
        if not plan or (plan.get("target") or {}).get("instance_id") == instance:
            _refuse(
                "E_CONFLICT",
                "unresolved calls prevent termination; preserve the instance and original records",
            )


def _witness(runtime, operation, kind):
    path = runtime / f"owned-exit-{operation}.{kind}.json"
    if not path.exists():
        return None
    evidence, raw = fingerprint(path)
    if len(raw) > 16384:
        raise Error("E_VERIFY_INCOMPLETE", "owned-exit witness exceeds its bound")
    try:
        data = decode(raw.decode("utf-8"))
    except Error as exc:
        cause = exc.__cause__
        if exc.code == "E_VALIDATION" and isinstance(cause, json.JSONDecodeError):
            # CREATE_NEW precedes the native writer's flush. Keep only this
            # syntax-read condition in the existing bounded file-poll loop;
            # strict duplicate/nonfinite failures remain domain errors.
            raise json.JSONDecodeError(cause.msg, cause.doc, cause.pos) from exc
        raise
    if not isinstance(data, dict):
        raise ValueError("owned-exit witness must be a JSON object")
    return {"file": evidence, "data": data}


def evidence(handle, runtime, operation, *, on_process=None, on_read_error=None):
    try:
        process = handle.observe()
    except (Error, OSError, ValueError) as exc:
        if on_read_error:
            on_read_error("process", exc)
        raise
    if on_process:
        on_process(process)
    result = {"process": process, "operation_id": operation, "entrypoint": ENTRYPOINT}
    for kind in ("entered", "returned", "stop", "failed", "cancelled", "unavailable"):
        try:
            result[kind] = _witness(runtime, operation, kind)
        except (Error, OSError, ValueError) as exc:
            if on_read_error:
                on_read_error(kind, exc)
            raise
    return result


def qualified(observation, expected):
    process = observation["process"]
    entered = (observation.get("entered") or {}).get("data", {})
    if not (
        process.get("signaled") is True
        and process.get("alive") is False
        and type(process.get("exit_code")) is int
        and process["exit_code"] == 0
        and process.get("pid") == expected["expected_pid"]
        and process.get("creation_filetime") == expected["expected_creation_filetime"]
        and engine.same_path(process.get("image", ""), expected["expected_native_image"])
    ):
        return False
    common = {
        "operation_id": observation["operation_id"],
        "service_instance_id": expected["service_instance_id"],
        "native_pid": expected["expected_pid"],
        "native_creation_filetime": expected["expected_creation_filetime"],
    }
    if (
        any(entered.get(k) != v for k, v in common.items())
        or entered.get("status") != "native_entered"
    ):
        return False
    if (
        entered.get("entrypoint") != ENTRYPOINT
        or entered.get("raw_java_empty_checked") is not True
        or entered.get("native_known_types_empty") is not True
        or entered.get("empty_models") is not True
        or type(entered.get("native_type_count")) is not int
        or entered["native_type_count"] != 11
    ):
        return False
    returned_present = observation.get("returned") is not None
    returned = (observation.get("returned") or {}).get("data", {})
    stop = (observation.get("stop") or {}).get("data", {})
    returned_ok = (
        all(returned.get(k) == v for k, v in common.items())
        and returned.get("status") == "native_returned"
        and returned.get("entrypoint") == ENTRYPOINT
        and returned.get("api_called") is True
        and type(returned.get("native_return_code")) is int
        and returned.get("native_return_code") == 0
    )
    stop_ok = (
        all(stop.get(k) == v for k, v in common.items())
        and stop.get("status") == "service_stop_after_owned_native_entry"
        and stop.get("entered_sha256") == observation["entered"]["file"]["sha256"]
    )
    unavailable_present = observation.get("unavailable") is not None
    unavailable_data = (observation.get("unavailable") or {}).get("data", {})
    unavailable = (
        unavailable_data.get("status") == "native_return_unavailable_after_entry"
        and unavailable_data.get("communication_kind")
        in {
            "com.ptc.pfc.pfcExceptions.XToolkitCommError",
            "com.ptc.pfc.pfcExceptions.XToolkitAppCommunicationFailure",
        }
        and unavailable_data.get("operation_id") == observation["operation_id"]
        and unavailable_data.get("service_instance_id") == expected["service_instance_id"]
        and unavailable_data.get("entered_sha256") == observation["entered"]["file"]["sha256"]
    )
    return (
        not observation.get("failed")
        and not observation.get("cancelled")
        and (
            returned_ok
            and (not unavailable_present or unavailable)
            or (not returned_present and stop_ok and (not unavailable_present or unavailable))
        )
    )


def plan(client, opts, pre):
    client.require_capability("owned_session_exit", 1)
    pin = pre["pin"]
    instance = pin["service_instance_id"]
    _no_unresolved(instance)
    current = deployment.inspect(
        pre["installation"], creo=str(pre["creo"]), java_home=str(pre["java"]), timeout=5
    )
    if current.get("loaded_verified") is not True or current.get("runtime_pin") != pin:
        _refuse(
            "E_VERIFY_INCOMPLETE",
            "fresh full-component identity does not match this exact owned launch",
        )
    if not engine.same_path(current["runtime_configuration"]["state_directory"], pre["runtime"]):
        _refuse("E_CONFLICT", "runtime differs from the declared owned launch")
    owned = ownership(pre, runtime_identity.processes(), native_launcher_link(pin["native_pid"]))
    image = pre["creo"] / "Common Files/x86e_win64/obj/xtop.exe"
    expected = {
        "expected_pid": pin["native_pid"],
        "expected_creation_filetime": str(pin["process_creations"][str(pin["native_pid"])]),
        "service_instance_id": instance,
        "runtime_directory": str(pre["runtime"]),
        "source_sha256": current["component_source_sha256"],
        "expected_native_image": str(image),
    }
    read_ms = int((timing.deadline(30) - time.monotonic()) * 1000)
    if read_ms < 1:
        _refuse("E_TIMEOUT", "CLI deadline elapsed before owned exit inventory read")
    state = client.op(
        "session.exit-state",
        {**expected, "read_deadline_epoch_ms": str(int(time.time() * 1000) + read_ms)},
    )
    if (
        type(state.get("raw_model_count")) is not int
        or state["raw_model_count"] != 0
        or state.get("raw_models") != []
        or state.get("models_complete") is not True
        or state.get("native_exit_available") is not True
        or state.get("service_instance_id") != instance
        or state.get("source_sha256") != expected["source_sha256"]
    ):
        _refuse(
            "E_CONFLICT", "normal-close every model first; a complete raw empty session is required"
        )
    with_handle = ProcessHandle(
        expected["expected_pid"], expected["expected_creation_filetime"], image
    )
    try:
        initial = with_handle.observe()
    finally:
        with_handle.close()
    # This command binds process state, not when a fresh image measurement was
    # made. Keep every other present/future field bound and preserve the complete
    # raw observation separately in the preview, before-state and receipt.
    bound_process = copy.deepcopy(initial)
    bound_process.pop("image_verified_at_utc", None)
    revision_projection = {
        "scope": "session.exit confirmation state revision only",
        "excluded_fields": ["process.image_verified_at_utc"],
        "reason": "fresh image measurement time is provenance, not process state",
        "protected_fields": "every other observed process field remains bound without projection",
        "raw_observation": "initial_process_observation and snapshot process_observation",
    }
    binding = {
        "launch_file": pre["file"],
        "expected": expected,
        "raw_empty": state,
        "process": bound_process,
        "owned_launcher": owned,
    }
    if pre.get("policy_evidence") is not None:
        binding["deployment_policy_evidence"] = pre["policy_evidence"]
    holder, verified = {}, {}

    def sample(value):
        captured = time.monotonic()
        deadline = holder.get("deadline")
        return {
            "state": copy.deepcopy(value),
            "sampled_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "within_deadline": captured < deadline if deadline is not None else None,
            "monotonic": captured,
        }

    def retain_process(value):
        # Keep this before any witness read: a partially written/unreadable file
        # must not discard the same held handle's successful process sample.
        holder["last_process_observation"] = sample(value)

    def retain_read_error(kind, exc):
        category = "process" if kind == "process" else "witness"
        count = category + "_read_error_count"
        holder[count] = holder.get(count, 0) + 1
        detail = {
            "source": "same held process" if kind == "process" else "owned-exit witness file",
            "witness": None if kind == "process" else kind,
            "error_type": type(exc).__name__,
            "sampled_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }
        if isinstance(exc, Error):
            detail["cause_code"] = exc.code
        safe = binding_diagnostics.sanitize(
            {"message": str(exc), "details": exc.details if isinstance(exc, Error) else {}}
        )
        detail["message"] = safe["message"][:1024]
        detail["details"] = safe["details"]
        for key in ("errno", "winerror"):
            value = getattr(exc, key, None)
            if type(value) is int:
                detail[key] = value
        holder["last_" + category + "_read_error"] = detail

    def retain_diagnostics(run, exc, acknowledgement):
        captured = time.monotonic()

        def retained(key):
            value = copy.deepcopy(holder.get(key))
            if value is not None:
                value["age_ms"] = round(max(0, captured - value.pop("monotonic")) * 1000, 3)
            return value

        diagnostic = {
            "schema_version": "1.0",
            "operation_id": holder["operation"],
            "entrypoint": ENTRYPOINT,
            "retained_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "sampling_scope": "this apply invocation and its original held native process handle",
            "latest_process_observation": retained("last_process_observation"),
            "latest_complete_observation": retained("last_complete_observation"),
            "process_read_error_count": holder.get("process_read_error_count", 0),
            "witness_read_error_count": holder.get("witness_read_error_count", 0),
            "last_process_read_error": copy.deepcopy(holder.get("last_process_read_error")),
            "last_witness_read_error": copy.deepcopy(holder.get("last_witness_read_error")),
            "request_acknowledgement": copy.deepcopy(acknowledgement),
            "handle_open_during_retention": holder["handle"].handle is not None,
            "qualification": (
                "diagnostic samples only; no normal-termination qualification is added"
            ),
            "limitations": [
                "last samples are not a new observation at error-report time",
                "separate sample times must not be combined into a passed verification",
                "no process reopening, PID lookup or post-failure CAD read was performed",
            ],
        }
        run["owned_exit_diagnostics"] = copy.deepcopy(diagnostic)
        exc.details["owned_exit_diagnostics"] = copy.deepcopy(diagnostic)
        exc.details["_untrusted"] = list(
            dict.fromkeys([*exc.details.get("_untrusted", []), "owned_exit_diagnostics"])
        )
        if run.get("status") not in operations.STATUSES:
            # Direct callback tests have no durable operation context. Production
            # dispatch always supplies the run created by engine.execute.
            exc.details["exit_diagnostics_checkpoint"] = "no_operation_record_context"
            return
        try:
            # Persist while the original handle is still held. The later engine
            # checkpoint preserves UNKNOWN; this is not a completion receipt.
            operations.checkpoint_domain(run)
        except (Error, sqlite3.Error, OSError) as recording:
            exc.details.update(
                exit_diagnostics_checkpoint="unavailable",
                exit_diagnostics_record_error=recording.code
                if isinstance(recording, Error)
                else "E_IO",
                exit_diagnostics_record_error_type=type(recording).__name__,
            )
        else:
            exc.details["exit_diagnostics_checkpoint"] = "retained"

    def prepare_dispatch(run):
        if fingerprint(pre["path"])[0] != pre["file"]:
            _refuse("E_CONFLICT", "owned launch changed before dispatch")
        if pre.get("policy_evidence") is not None:
            try:
                _required(
                    _policy_evidence(pre["launch"], pre["creo"], pre["installation"])
                    == pre["policy_evidence"]
                )
            except (Error, KeyError, TypeError, ValueError, OSError, IndexError) as exc:
                raise Error(
                    "E_CONFLICT",
                    "scoped deployment policy evidence changed before exit dispatch",
                    {"dispatch_state": "not_started", "automatic_retry": False},
                ) from exc
        handle = ProcessHandle(
            expected["expected_pid"], expected["expected_creation_filetime"], image
        )
        holder.update(handle=handle, operation=run["operation_id"])
        try:
            _new_json(
                pre["runtime"] / f"owned-exit-{run['operation_id']}.intent.json",
                {
                    **expected,
                    "operation_id": run["operation_id"],
                    "entrypoint": ENTRYPOINT,
                    "raw_empty": state,
                    "launch_sha256": pre["file"]["sha256"],
                },
            )
        except BaseException:
            handle.close()
            raise

    def observe(_client):
        if not same_plan(p, _client):
            raise Error(
                "E_VERIFY_INCOMPLETE", "owned-exit observation is not bound to this Plan and Client"
            )
        if not holder:
            return {"process": initial, "dispatch_state": "not_started"}
        if holder["handle"].handle is None:
            cached_process = holder.get("last_process_observation")
            return copy.deepcopy(
                holder.get(
                    "last_observation",
                    {
                        "process": cached_process["state"] if cached_process else initial,
                        "exit_evidence": "incomplete",
                        "process_sample_after_dispatch_available": cached_process is not None,
                    },
                )
            )
        observed = evidence(
            holder["handle"],
            pre["runtime"],
            holder["operation"],
            on_process=retain_process,
            on_read_error=retain_read_error,
        )
        holder["last_observation"] = copy.deepcopy(observed)
        holder["last_complete_observation"] = sample(observed)
        return observed

    def apply(c, run):
        handle = holder["handle"]
        ack = None
        try:
            deadline = timing.deadline(MAX_EXIT_MS / 1000)
            holder["deadline"] = deadline
            if not same_plan(p, c) or holder["operation"] != run["operation_id"]:
                _refuse(
                    "E_VERIFY_INCOMPLETE",
                    "owned-exit dispatch is not bound to this Plan and intent",
                )
            try:
                handle.begin_termination()
            except (Error, OSError, KeyboardInterrupt) as exc:
                retain_read_error("process", exc)
                if isinstance(exc, KeyboardInterrupt):
                    raise Error(
                        "E_INTERRUPTED",
                        "owned exit was interrupted before native dispatch",
                        {
                            "request_sent": False,
                            "dispatch_state": "not_started",
                            "cause_code": "E_INTERRUPTED",
                            "exception_type": "KeyboardInterrupt",
                            "automatic_retry": False,
                        },
                    ) from None
                if not isinstance(exc, Error):
                    raise Error(
                        "E_VERIFY_INCOMPLETE",
                        "owned process identity could not be read before exit dispatch",
                        {
                            "request_sent": False,
                            "dispatch_state": "not_started",
                            "exception_type": type(exc).__name__,
                        },
                    ) from None
                exc.details.update(request_sent=False, dispatch_state="not_started")
                raise
            budget_ms = int((deadline - time.monotonic()) * 1000)
            if budget_ms < 1:
                _refuse("E_TIMEOUT", "CLI deadline elapsed before owned native exit dispatch")
            request = {
                **expected,
                "operation_id": run["operation_id"],
                "deadline_tick_ms": str(handle.tick() + budget_ms),
                "ttl_ms": budget_ms,
                "deadline_epoch_ms": str(int(time.time() * 1000) + budget_ms),
            }
            ack = c.op("session.exit", request, write=True)
            if (
                not isinstance(ack, dict)
                or ack.get("status") != "request_scheduled"
                or ack.get("operation_id") != run["operation_id"]
            ):
                raise Error(
                    "E_OUTCOME_UNKNOWN",
                    "exit request acknowledgement is incomplete",
                    {"request_sent": True, "automatic_retry": False},
                )
            while True:
                if time.monotonic() >= deadline:
                    raise Error(
                        "E_OUTCOME_UNKNOWN",
                        "owned exit deadline elapsed; do not retry or query CAD",
                        {"request_sent": True, "started": True, "automatic_retry": False},
                    )
                try:
                    observed = observe(c)
                    if time.monotonic() >= deadline:
                        raise Error(
                            "E_OUTCOME_UNKNOWN",
                            "owned exit deadline elapsed; do not retry or query CAD",
                            {"request_sent": True, "started": True, "automatic_retry": False},
                        )
                    if qualified(observed, expected):
                        verified.update(copy.deepcopy(observed))
                        return {"exit_observation": observed, "request_acknowledgement": ack}
                    returned = (observed.get("returned") or {}).get("data", {})
                    bad_return = observed.get("returned") is not None and (
                        returned.get("api_called") is not True
                        or type(returned.get("native_return_code")) is not int
                        or returned.get("native_return_code") != 0
                    )
                    if (
                        bad_return
                        or observed.get("failed")
                        or observed.get("cancelled")
                        or (
                            observed["process"]["signaled"]
                            and observed["process"]["exit_code"] != 0
                        )
                    ):
                        raise Error(
                            "E_OUTCOME_UNKNOWN",
                            "owned native exit lacks complete normal-termination evidence",
                            {
                                "request_sent": True,
                                "started": True,
                                "automatic_retry": False,
                                "exit_observation": observed,
                            },
                        )
                except (OSError, ValueError):
                    pass  # a witness may be in the bounded CreateNew/flush interval
                if time.monotonic() >= deadline:
                    raise Error(
                        "E_OUTCOME_UNKNOWN",
                        "owned exit deadline elapsed; do not retry or query CAD",
                        {"request_sent": True, "started": True, "automatic_retry": False},
                    )
                time.sleep(0.05)
        except Error as exc:
            if ack is not None and exc.code != "E_OUTCOME_UNKNOWN":
                failure = Error(
                    "E_OUTCOME_UNKNOWN",
                    "owned-exit evidence became unreadable after dispatch",
                    {
                        "request_sent": True,
                        "started": True,
                        "automatic_retry": False,
                        "cause_code": exc.code,
                    },
                )
                retain_diagnostics(run, failure, ack)
                raise failure from None
            retain_diagnostics(run, exc, ack)
            raise
        except (OSError, KeyboardInterrupt) as exc:
            failure = engine.local_outcome_unknown(exc)
            retain_diagnostics(run, failure, ack)
            raise failure from None
        finally:
            handle.close()

    def verify(_c, data):
        observation = data.get("exit_observation")
        passed = (
            same_plan(p, _c)
            and bool(verified)
            and observation == verified
            and qualified(observation, expected)
        )
        if passed:
            p.verified_observation = copy.deepcopy(observation)
        return {
            "exit_observation": observation,
            "pre_dispatch_process_observation": copy.deepcopy(initial),
            "request_acknowledgement": copy.deepcopy(data.get("request_acknowledgement")),
            "persistence": "not_applicable",
            "entrypoint": ENTRYPOINT,
        }, {
            "level": "selected_postconditions_verified",
            "checks": [
                engine.check(
                    "owned_native_process_normally_terminated_with_correlated_evidence", passed
                )
            ],
            "observations": [
                {"observation": "same_held_process_and_native_exit_witnesses", "state": observation}
            ],
            "not_checked": ["full_cold_start_cycle_qualification_is_separate"],
        }

    owned_target = {
        "mode": "session",
        "engine_id": "creo",
        "instance_id": instance,
        "object_id": "session",
        "locator": client.url + "/session",
        "extensions": {
            "creo": {
                "ownership": "owned",
                "native_pid": expected["expected_pid"],
                "native_creation_filetime": expected["expected_creation_filetime"],
                "source_sha256": expected["source_sha256"],
            }
        },
    }
    p = engine.Plan(
        op="session.exit",
        request=expected,
        target="session",
        binding=binding,
        preview={
            "command": "session exit",
            "effect": "Terminate only this exact owned empty Creo session and its synchronous "
            "TOOLKIT children; no save/discard/close-model/kill",
            "owned_target": owned_target,
            "scope_paths": [(str(pre["path"]), "observe"), (str(pre["runtime"]), "session")],
            "launch_file": pre["file"],
            "entrypoint": ENTRYPOINT,
            "raw_model_count": 0,
            "initial_process_observation": copy.deepcopy(initial),
            "state_revision_projection": revision_projection,
        },
        verify=verify,
        observe=observe,
        before={"process": initial},
        arguments={"launch_record": str(pre["path"])},
        apply=apply,
        prepare_dispatch=prepare_dispatch,
        effects=["session"],
    )
    frozen = copy.deepcopy(
        {
            key: getattr(p, key)
            for key in (
                "request",
                "binding",
                "preview",
                "arguments",
                "before",
                "effects",
                "op",
                "target",
            )
        }
    )

    def same_plan(planned, c):
        return (
            planned is p
            and c is client
            and all(getattr(p, key) == value for key, value in frozen.items())
        )

    p._verified_observation_guard = lambda planned, c: (
        same_plan(planned, c) and bool(verified) and p.verified_observation == verified
    )
    p.failure_unchanged = lambda _after: None
    return p


def execute(opts):
    if opts.get("dangerous") is not True:
        _refuse("E_FORBIDDEN", "owned-session termination requires the explicit dangerous flag")
    if engine.CAPTURE.get() is not None:
        _refuse("E_UNSUPPORTED", "owned-session termination is a standalone lifecycle step")
    return engine.write("session exit", opts, prepare, plan)
