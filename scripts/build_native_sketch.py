"""Compile the native sketch library the Creo-side service loads beside its jar.

Object TOOLKIT Java cannot project model references into a sketch, and a sketch made
of several entities -- a rectangle, a polygon -- is rejected by Creo without them.
The C toolkit can, so this small DLL does exactly that and nothing else; see
service/native/creo_cli_sketch.c and docs/SERVICE.md.

Building needs the MSVC toolchain PTC names for Creo 13 (Visual Studio 2022 or its
Build Tools, C++ workload) and the Creo Parametric Toolkit headers and libraries.
Using the result needs neither build tool. Toolkit unlock, Windows Authenticode
signing and Creo's loading policy are separate deployment requirements.

  python scripts/build_native_sketch.py [--creo "<Creo load point>"]

The flags are PTC's own, from protoolkit/x86e_win64/obj/make_install, so the DLL is
built the way PTC builds its examples: static CRT, protk_dll_NU.lib, the two ICU
libraries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import build_service  # noqa: E402

SOURCE = ROOT / "service" / "native" / "creo_cli_sketch.c"
OUTPUT = build_service.BUILD / "creo_cli_sketch.dll"
VSWHERE = (
    Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))
    / "Microsoft Visual Studio"
    / "Installer"
    / "vswhere.exe"
)
# From PTC's make_install for x86e_win64.
COMPILE_FLAGS = [
    "-c",
    "-nologo",
    "-GS",
    "-fp:precise",
    "-D_WSTDIO_DEFINED",
    "-DPRO_MACHINE=36",
    "-DPRO_OS=4",
    # C4819: PTC's headers hold characters outside a CJK console's code
    # page. It is noise about comments, on every Chinese Windows.
    "-wd4819",
]
SYSTEM_LIBS = [
    "libcmt.lib",
    "kernel32.lib",
    "user32.lib",
    "wsock32.lib",
    "advapi32.lib",
    "mpr.lib",
    "winspool.lib",
    "netapi32.lib",
    "psapi.lib",
    "gdi32.lib",
    "shell32.lib",
    "comdlg32.lib",
    "ole32.lib",
    "ws2_32.lib",
]


def vcvars() -> Path:
    """The MSVC environment script, found the way Microsoft documents: vswhere."""
    if not VSWHERE.is_file():
        raise RuntimeError(
            "no Visual Studio installation found (vswhere.exe missing); install Visual Studio "
            "2022 Build Tools with the C++ workload to build the native sketch library"
        )
    result = subprocess.run(
        [
            str(VSWHERE),
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    location = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
    script = Path(location) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
    if not location or not script.is_file():
        raise RuntimeError(
            "Visual Studio is installed without the C++ x64 build tools; add the "
            "'Desktop development with C++' workload"
        )
    return script


def build(creo: Path, *, output: Path | None = None) -> dict:
    """Compile and link; this function does not unlock, sign or establish trust."""
    target = output if output is not None else OUTPUT
    common = creo / "Common Files"
    includes = common / "protoolkit" / "includes"
    libraries = common / "protoolkit" / "x86e_win64" / "obj"
    for needed in (includes / "ProSection.h", libraries / "protk_dll_NU.lib"):
        if not needed.is_file():
            raise RuntimeError(
                f"{needed} not found; the 'Creo Parametric Toolkit' installer component "
                "is needed to build the native sketch library (see docs/CREO_SETUP.md)"
            )
    target.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="creo-cli-native-"))
    obj = work / "creo_cli_sketch.obj"
    compile_cmd = " ".join(["cl", *COMPILE_FLAGS, f'-I"{includes}"', f'-Fo"{obj}"', f'"{SOURCE}"'])
    link_cmd = " ".join(
        [
            "link",
            "/nologo",
            "/dll",
            "/subsystem:console",
            "/machine:amd64",
            "/debug:none",
            f'-out:"{target}"',
            f'"{obj}"',
            f'"{libraries / "protk_dll_NU.lib"}"',
            f'"{libraries / "ucore.lib"}"',
            f'"{libraries / "udata.lib"}"',
            *SYSTEM_LIBS,
        ]
    )
    batch = work / "build.bat"
    batch.write_text(
        "\r\n".join(
            [
                "@echo off",
                # vcvars64.bat calls vswhere by name; put it on PATH so it does not complain.
                f'set "PATH={VSWHERE.parent};%PATH%"',
                f'call "{vcvars()}" >nul || exit /b 1',
                compile_cmd + " || exit /b 2",
                link_cmd + " || exit /b 3",
            ]
        )
        + "\r\n",
        encoding="ascii",
    )
    environment = dict(os.environ)
    # cmd.exe will not run a .bat from the working directory when this is set.
    environment["MSYS_NO_PATHCONV"] = "1"
    result = subprocess.run(
        ["cmd.exe", "/c", str(batch)],
        capture_output=True,
        cwd=str(work),
        env=environment,
        stdin=subprocess.DEVNULL,
    )
    output = (build_service.decode(result.stdout) + build_service.decode(result.stderr)).strip()
    if result.returncode != 0:
        step = {1: "setting up MSVC", 2: "compiling", 3: "linking"}.get(
            result.returncode, "building"
        )
        raise RuntimeError(f"{step} the native sketch library failed:\n{output[-3000:]}")
    return {
        "dll": str(target),
        "dll_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "compiler_output": [line for line in output.splitlines() if line.strip()][-5:],
        "toolkit_unlocked": False,
        "authenticode_verified": False,
        "creo_load_trust_verified": False,
    }


STAMP = OUTPUT.with_name(OUTPUT.name + ".stamp.json")


def fingerprint() -> str:
    """What the DLL is built from: the source and every flag that shapes the binary."""
    material = SOURCE.read_bytes() + json.dumps([COMPILE_FLAGS, SYSTEM_LIBS]).encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def ensure(creo: Path) -> dict:
    """Reuse exact known Toolkit-unlocked bytes; never infer signature or trust.

    The local stamp records this build step only. Authenticode and the effective
    per-session loading policy require independent deployment verification.
    """
    wanted = fingerprint()
    try:
        stamp = json.loads(STAMP.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stamp = {}
    if (
        OUTPUT.is_file()
        and stamp.get("source") == wanted
        and stamp.get("dll_sha256") == hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
        and stamp.get("toolkit_unlocked") is True
        and stamp.get("unlock_mode") == "-c"
    ):
        return {
            "dll": str(OUTPUT),
            "rebuilt": False,
            "dll_sha256": stamp["dll_sha256"],
            "toolkit_unlocked": True,
            "unlock_mode": "-c",
            "authenticode_verified": False,
            "authenticode_status": "not_checked",
            "creo_load_trust_verified": False,
            "reason": (
                "source and exact Toolkit-unlocked bytes unchanged; "
                "signature and Creo trust not inferred"
            ),
        }
    built = build(creo)
    built["toolkit_unlock_result"] = unlock(creo, OUTPUT)
    built["toolkit_unlocked"] = True
    built["unlock_mode"] = "-c"
    built["authenticode_verified"] = False
    built["authenticode_status"] = "not_checked"
    built["creo_load_trust_verified"] = False
    built["dll_sha256"] = hashlib.sha256(OUTPUT.read_bytes()).hexdigest()
    STAMP.write_text(
        json.dumps(
            {
                "source": wanted,
                "dll_sha256": built["dll_sha256"],
                "toolkit_unlocked": True,
                "unlock_mode": "-c",
            }
        ),
        encoding="utf-8",
    )
    built["rebuilt"] = True
    built["note"] = (
        "Toolkit unlock is not Authenticode signing or Creo load authorization; "
        "inspect the signed deployment separately"
    )
    return built


def unlock(creo: Path, dll: Path, *, signing_required: bool = False) -> str:
    """Unlock with the legitimate seat; -cd prepares mandatory external signing.

    Neither mode creates an Authenticode signature or changes the loading policy.
    """
    script = creo / "Parametric" / "bin" / "protk_unlock.bat"
    environment = dict(os.environ)
    if os.name == "nt" and not environment.get("PROCESSOR_ARCHITECTURE"):
        import ctypes

        system = ctypes.create_string_buffer(64)
        ctypes.windll.kernel32.GetNativeSystemInfo(system)
        architecture = int.from_bytes(system.raw[:2], "little")
        if architecture != 9:
            raise RuntimeError("this installed Creo x64 unlock requires an actual AMD64 host")
        environment["PROCESSOR_ARCHITECTURE"] = "AMD64"
    environment["MSYS_NO_PATHCONV"] = "1"
    result = subprocess.run(
        ["cmd.exe", "/c", str(script), "-cd" if signing_required else "-c", str(dll)],
        capture_output=True,
        cwd=str(script.parent),
        env=environment,
        stdin=subprocess.DEVNULL,
    )
    output = (build_service.decode(result.stdout) + build_service.decode(result.stderr)).strip()
    if (
        result.returncode != 0
        or "Cannot detect what machine type" in output
        or "ERROR" in output
        or "Successfully unlocked application" not in output
    ):
        raise RuntimeError(output[-2000:] or "protk_unlock failed")
    return output.splitlines()[-1]


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--creo", help="Creo load point; probed when omitted")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--no-unlock",
        action="store_true",
        help="skip Toolkit unlock; establishes no deployment readiness",
    )
    mode.add_argument(
        "--prepare-for-signing",
        action="store_true",
        help="unlock with -cd; mandatory external Authenticode signing still required",
    )
    a = p.parse_args()
    try:
        from scripts import reload_service

        creo = reload_service.load_point(a.creo)
        built = build(creo)
        if not a.no_unlock:
            built["toolkit_unlock_result"] = unlock(
                creo, Path(built["dll"]), signing_required=a.prepare_for_signing
            )
            built["toolkit_unlocked"] = True
            built["unlock_mode"] = "-cd" if a.prepare_for_signing else "-c"
            built["authenticode_verified"] = False
            built["creo_load_trust_verified"] = False
            built["dll_sha256"] = hashlib.sha256(Path(built["dll"]).read_bytes()).hexdigest()
    except (OSError, RuntimeError) as failure:
        print(json.dumps({"ok": False, "error": str(failure)}, indent=2))
        return 1
    print(json.dumps({"ok": True, **built}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
