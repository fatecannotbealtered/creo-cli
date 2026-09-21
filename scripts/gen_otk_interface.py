"""Derive a checkable index of the Creo Object TOOLKIT Java interface.

J-Link, which CREOSON is built on, cannot create features -- it can only modify
existing ones or place UDFs. Creating geometry needs the licensed Object TOOLKIT
Java surface, whose element-tree API lives in the `wfc` namespace that J-Link does
not ship at all. Command schemas for that surface have to be written against the
real vocabulary, not transcribed from prose: there are thousands of element ids and
a mistyped one is a runtime failure on live Creo, which is exactly the feedback loop
this project does not have.

So the same discipline applied to CREOSON applies here. The authority is the shipped
`otk.jar` itself, introspected with javap, rather than documentation about it:

  python scripts/gen_otk_interface.py --from "<Creo>/Common Files" [--java-home <jdk>]
  python scripts/gen_otk_interface.py --check

Produces contract/otk-interface.json: element ids, feature types, the creation-path
class signatures, and provenance tying all of it to one jar by digest.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INDEX = ROOT / "contract" / "otk-interface.json"
JAR_SUBPATH = ("text", "java", "otk.jar")

# The classes an implementation actually calls to build and commit a feature tree.
# Listed explicitly so the index stays a contract rather than a dump of 3500 classes.
CREATION_API = (
    "com.ptc.wfc.wfcElementTree.ElementTree",
    "com.ptc.wfc.wfcElementTree.Element",
    "com.ptc.wfc.wfcElementTree.ElementPath",
    "com.ptc.wfc.wfcElementTree.Elements",
    "com.ptc.wfc.wfcElementTree.ElemPathItem",
    "com.ptc.pfc.pfcFeature.FeatureCreateInstructions",
    "com.ptc.pfc.pfcFeature.Feature",
    "com.ptc.pfc.pfcSolid.Solid",
    "com.ptc.pfc.pfcPart.Part",
)
ENUM_CLASSES = {
    "element_ids": "com.ptc.wfc.wfcElemIds.wfcElemIds",
    "feature_types": "com.ptc.pfc.pfcFeature.FeatureType",
}
CONSTANT = re.compile(r"public static final int ([A-Za-z_][A-Za-z0-9_]*) = (-?\d+);")


def javap(java_home: Path | None, jar: Path, *args: str) -> str:
    binary = str(java_home / "bin" / "javap") if java_home else "javap"
    result = subprocess.run([binary, "-cp", str(jar), *args],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0 and not result.stdout:
        raise RuntimeError((result.stderr or "javap failed").strip()[:300])
    return result.stdout


def constants(java_home: Path | None, jar: Path, class_name: str) -> dict[str, int]:
    """Constant name -> value, normalized past PTC's typesafe-enum convention.

    These classes declare each value twice: `int _FEATTYPE_HOLE = 1` alongside the
    typed object `FeatureType FEATTYPE_HOLE`. Only the first carries a readable
    value, so the underscore is stripped and the logical name is what the index
    records -- looking up FEATTYPE_HOLE should not require knowing the convention.
    """
    text = javap(java_home, jar, "-constants", class_name)
    return {name.lstrip("_") if name.startswith("_") else name: int(value)
            for name, value in CONSTANT.findall(text)}


def signatures(java_home: Path | None, jar: Path, class_name: str) -> list[str]:
    lines = []
    for line in javap(java_home, jar, class_name).splitlines():
        line = line.strip()
        if line.startswith("public") and line.endswith(";"):
            lines.append(line)
    return lines


def namespaces(jar: Path) -> dict[str, int]:
    """Class counts per top-level namespace.

    pfc is the domain J-Link also ships; wfc is the licensed extension. The ratio is
    the honest measure of what the free tier leaves out, so it is recorded rather
    than asserted in prose somewhere.
    """
    import zipfile
    counts: dict[str, int] = {}
    with zipfile.ZipFile(jar) as archive:
        for name in archive.namelist():
            if not name.endswith(".class"):
                continue
            parts = name.split("/")
            # Require a package below com/ptc: classes sitting directly there are not
            # namespaces, and counting them makes the pfc-vs-wfc ratio meaningless.
            if len(parts) > 3 and parts[0] == "com" and parts[1] == "ptc":
                counts[parts[2]] = counts.get(parts[2], 0) + 1
    return dict(sorted(counts.items()))


def derive(common_files: Path, java_home: Path | None) -> dict:
    jar = common_files.joinpath(*JAR_SUBPATH)
    digest = hashlib.sha256(jar.read_bytes()).hexdigest()
    index: dict = {
        "$comment": "DERIVED, DO NOT HAND-EDIT. Regenerate with scripts/gen_otk_interface.py "
                    "--from <Creo Common Files>. An interface index used to check the catalog "
                    "against the shipped library; it is not PTC source and bundles nothing.",
        "library": "Creo Object TOOLKIT Java",
        "jar_relative_path": "/".join(JAR_SUBPATH),
        "jar_sha256": digest,
        "jar_size_bytes": jar.stat().st_size,
        "namespace_class_counts": namespaces(jar),
    }
    for key, class_name in ENUM_CLASSES.items():
        values = constants(java_home, jar, class_name)
        if not values:
            raise RuntimeError(f"no constants read from {class_name}")
        index[key] = {"source_class": class_name, "count": len(values), "values": dict(sorted(values.items()))}
    index["creation_api"] = {name: signatures(java_home, jar, name) for name in CREATION_API}
    return index


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="source", help="Creo 'Common Files' directory")
    p.add_argument("--java-home", help="JDK to take javap from; defaults to javap on PATH")
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    if a.check:
        if not INDEX.is_file():
            print(json.dumps({"ok": False, "error": "contract/otk-interface.json is missing"}))
            return 1
        index = json.loads(INDEX.read_text(encoding="utf-8"))
        print(json.dumps({"ok": True, "jar_sha256": index["jar_sha256"],
                          "element_ids": index["element_ids"]["count"],
                          "feature_types": index["feature_types"]["count"]}))
        return 0
    if not a.source:
        print(json.dumps({"ok": False, "error": "--from is required when not checking"}))
        return 1
    common = Path(a.source).expanduser()
    java_home = Path(a.java_home).expanduser() if a.java_home else (
        Path(os.environ["JAVA_HOME"]) if os.environ.get("JAVA_HOME") else None)
    try:
        index = derive(common, java_home)
    except (OSError, RuntimeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 1
    INDEX.parent.mkdir(parents=True, exist_ok=True)
    with io.open(INDEX, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(index, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(json.dumps({"ok": True, "written": str(INDEX.relative_to(ROOT)),
                      "element_ids": index["element_ids"]["count"],
                      "feature_types": index["feature_types"]["count"],
                      "namespaces": index["namespace_class_counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
