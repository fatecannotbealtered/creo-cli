"""Build and retain source-bound signed components; never start or stop Creo."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts import build_native_sketch, build_service, reload_service  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--creo", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--namespace", default="")
    parser.add_argument("--runtime-state", type=Path)
    parser.add_argument("--native-handshake", type=Path)
    parser.add_argument("--runtime-port", type=int, default=9167)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    os.environ.update(TEMP=str(out), TMP=str(out), PROCESSOR_ARCHITECTURE="AMD64")
    names = set()
    for flags in (("ls-files", "-z"), ("ls-files", "--others", "--exclude-standard", "-z")):
        names.update(subprocess.check_output(["git", *flags], cwd=ROOT).decode().split("\0"))
    source = {}
    for name in sorted(names - {"", "HANDOFF.md"}):
        original, retained = ROOT / name, out / "source" / name
        if original.is_file():
            retained.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, retained)
            source[name] = sha(retained)
    record = {
        "at_utc": datetime.now(UTC).isoformat(),
        "source_root": str(ROOT),
        "source_files": source,
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(source, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT)
        .decode()
        .strip(),
        "creo": str(args.creo),
        "java_home": str(args.java_home),
        "native_compile_flags": build_native_sketch.COMPILE_FLAGS,
        "native_system_libraries": build_native_sketch.SYSTEM_LIBS,
    }
    try:
        profile = None
        if args.runtime_state:
            if not args.native_handshake or not args.namespace:
                raise ValueError("a live profile requires namespace and native handshake path")
            profile = {
                "state_directory": args.runtime_state.resolve().as_posix(),
                "native_id_file": args.native_handshake.resolve().as_posix(),
                "port": args.runtime_port,
            }
        record["app_class"] = (args.namespace or "com.fateforge.creocli.service") + ".Service"
        record["runtime_profile"] = profile
        record["java"] = build_service.build(
            args.creo, args.java_home, namespace=args.namespace, runtime_profile=profile
        )
        record["java_signing"] = reload_service.unlock(
            args.creo, build_service.BUILD / build_service.JAR_NAME, record["app_class"]
        )
        if "Successfully unlocked application" not in record["java_signing"]:
            raise RuntimeError("PTC did not report Java unlock completion")
        record["native"] = build_native_sketch.ensure(args.creo)
        with zipfile.ZipFile(build_service.BUILD / build_service.JAR_NAME) as jar:
            required = {"META-INF/PTC.SF", "META-INF/PTC.DSA"}
            if not required <= set(jar.namelist()):
                raise RuntimeError("PTC JAR signature entries are missing")
            record["java_signatures"] = sorted(required)
        record["source_lock"] = json.loads(
            (build_service.BUILD / "classes-source/source-lock.json").read_text(encoding="utf-8")
        )
        shutil.copytree(build_service.BUILD / "classes-source", out / "generated-source")
        files = {}
        for key, original in {
            "jar": build_service.BUILD / build_service.JAR_NAME,
            "native": build_native_sketch.OUTPUT,
        }.items():
            retained = out / original.name
            shutil.copyfile(original, retained)
            files[key] = {
                "path": str(retained),
                "sha256": sha(retained),
                "bytes": retained.stat().st_size,
            }
        record["files"] = files
        record["otk_sha256"] = sha(build_service.otk_jar(args.creo))
        record["success"] = True
    except Exception as error:
        record["success"] = False
        record["error"] = type(error).__name__ + ": " + str(error)
    (out / "candidate.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "success": record["success"],
                "candidate": str(out / "candidate.json"),
                "error": record.get("error"),
            }
        )
    )
    return 0 if record["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
