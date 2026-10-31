"""Bind the actual frozen archive to the reviewed controlled runtime and notices."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pefile
from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def inspect(exe: Path, build: Path):
    result = json.loads(build.read_text(encoding="utf-8"))
    profile = json.loads((ROOT / "release/CLIENT-RUNTIME.json").read_text())
    if result["exe"] != {"sha256": sha(exe.read_bytes()), "bytes": exe.stat().st_size}:
        raise ValueError("EXE does not match the immutable build result")
    archive = CArchiveReader(str(exe))
    embedded = archive.extract("CLIENT-BUILD.json")
    binding = json.loads(embedded)
    for key in ("source_commit", "runtime", "runtime_distribution", "source_files"):
        if binding[key] != result[key]:
            raise ValueError("Embedded build provenance differs: " + key)
    if result["runtime"] != profile["required_build_versions"]:
        raise ValueError("Unexpected runtime profile")
    pinned = {Path(n).name.lower(): (n, v) for n, v in profile["native_build_inputs"].items()}
    control_data = (ROOT / "release/CONTROLLED-RUNTIME.json").read_bytes()
    if sha(control_data) != profile["runtime_distribution"]["control_record_sha256"]:
        raise ValueError("Controlled runtime provenance changed")
    control = json.loads(control_data)
    native = {}
    members = {}
    for name in sorted(archive.toc):
        data = archive.extract(name)
        members[name] = {"bytes": len(data), "sha256": sha(data)}
        if not name.lower().endswith((".dll", ".pyd")):
            continue
        relative, expected = pinned.get(name.lower(), (None, None))
        if expected != members[name]:
            raise ValueError("Native member differs from the reviewed controlled runtime: " + name)
        pe = pefile.PE(data=data, fast_load=False)
        if pe.FILE_HEADER.Machine != 0x8664:
            raise ValueError("Unexpected native architecture: " + name)
        fixed = pe.VS_FIXEDFILEINFO[0] if getattr(pe, "VS_FIXEDFILEINFO", None) else None
        version = None
        if fixed:
            version = ".".join(
                str(v)
                for v in (
                    fixed.FileVersionMS >> 16,
                    fixed.FileVersionMS & 65535,
                    fixed.FileVersionLS >> 16,
                    fixed.FileVersionLS & 65535,
                )
            )
        native[name] = members[name] | {
            "controlled_runtime_member": relative,
            "pe_file_version": version,
        }
    for required in ("python315.dll", "_ssl.pyd", "libssl-3.dll", "libcrypto-3.dll", "sqlite3.dll"):
        if required not in native:
            raise ValueError("Required runtime member absent: " + required)
    pyz = archive.open_embedded_archive("PYZ.pyz")
    modules = sorted(pyz.toc)
    # The product is stdlib-only. Build and audit packages must not become runtime payloads.
    forbidden = {
        "pip",
        "pytest",
        "ruff",
        "setuptools",
        "jsonschema",
        "requests",
        "pip_audit",
        "tkinter",
        "test",
        "_testcapi",
        "_testinternalcapi",
        "_testlimitedcapi",
    }
    if {n.split(".")[0] for n in modules} & forbidden:
        raise ValueError("Unexpected build-only package in frozen runtime")
    sbom_data = (ROOT / "release/PYTHON-3.15.2-OFFICIAL-SBOM.json").read_bytes()
    if sha(sbom_data) != profile["upstream_sbom"]["sha256"]:
        raise ValueError("Official upstream SBOM changed")
    packages = {p["SPDXID"]: p for p in json.loads(sbom_data)["packages"]}
    packages["SPDXRef-PACKAGE-cpython"]["downloadLocation"] = profile["runtime_distribution"][
        "cpython_source"
    ]["url"]
    packages["SPDXRef-PACKAGE-xz"].update(
        versionInfo="5.8.4", downloadLocation=profile["runtime_distribution"]["xz_source"]["url"]
    )
    if native["_lzma.pyd"]["sha256"] != control["test_lzma"]["runtime_lzma_sha256"]:
        raise ValueError("Frozen XZ extension is not the exact tested controlled build")
    definitions = [
        (
            "cpython",
            ["python315.dll"],
            "PSF-2.0 and included notices",
            ["PYTHON-3.15.2-LICENSE.txt"],
        ),
        (
            "openssl",
            ["_ssl.pyd", "_hashlib.pyd", "libssl-3.dll", "libcrypto-3.dll"],
            "Apache-2.0",
            ["OpenSSL-3.5.9-LICENSE.txt"],
        ),
        ("sqlite", ["_sqlite3.pyd", "sqlite3.dll"], "Public domain", ["SQLite-NOTICE.txt"]),
        ("libffi", ["_ctypes.pyd", "libffi-8.dll"], "MIT", ["libffi-3.4.4-LICENSE.txt"]),
        ("bzip2", ["_bz2.pyd"], "bzip2-1.0.6", ["bzip2-1.0.8-LICENSE.txt"]),
        (
            "xz",
            ["_lzma.pyd"],
            "0BSD and included notices",
            ["xz-5.8.4-COPYING.txt", "xz-5.8.4-0BSD.txt"],
        ),
        ("mpdecimal", ["_decimal.pyd"], "BSD-2-Clause", ["mpdecimal-4.0.0-LICENSE.txt"]),
        ("zstd", ["_zstd.pyd"], "BSD-3-Clause", ["zstd-1.5.7-LICENSE.txt"]),
        ("zlib-ng", ["python315.dll"], "Zlib", ["zlib-ng-2.2.4-LICENSE.md"]),
        (
            "hacl-star-8ba599b2f6c9701b3dc961db895b0856a2210f76",
            ["python315.dll"],
            "MIT generated code; upstream Apache-2.0 notice retained",
            ["HACL-GENERATED-MIT.txt", "HACL-LICENSE.txt"],
        ),
    ]
    components = []
    for ident, files, license_name, notices in definitions:
        package = packages["SPDXRef-PACKAGE-" + ident]
        if not set(files) <= native.keys():
            raise ValueError("Component's binary is absent: " + ident)
        components.append(
            {
                "name": package["name"],
                "version": package["versionInfo"],
                "source": package["downloadLocation"],
                "upstream_spdx_id": package["SPDXID"],
                "contained_in": files,
                "license": license_name,
                "notices": ["docs/licenses/" + n for n in notices],
                "version_evidence": (
                    "Embedded hashes equal the controlled runtime manifest; "
                    "fixed source inputs and compile/link records identify dependencies"
                ),
            }
        )
    components += [
        {
            "name": "Microsoft Visual C++ runtime",
            "version": native["VCRUNTIME140.dll"]["pe_file_version"],
            "contained_in": ["VCRUNTIME140.dll", "VCRUNTIME140_1.dll"],
            "source": control["unmodified_official_provider_files"]["microsoft_vc_source"]["url"],
            "license": "Microsoft Distributable Code conditions",
            "notices": [
                "docs/licenses/PYTHON-3.15.2-LICENSE.txt",
                "docs/licenses/MICROSOFT-RUNTIME-NOTICE.md",
            ],
        },
        {
            "name": "PyInstaller bootloader and import hooks",
            "version": result["runtime"]["pyinstaller"],
            "source": "https://pypi.org/project/pyinstaller/6.22.3/",
            "license": "GPL-2.0-or-later with Bootloader Exception",
            "notices": ["docs/licenses/PYINSTALLER-6.22.3-COPYING.txt"],
            "stock_bootloader_sha256": result["pyinstaller_bootloader_sha256"],
            "security_checks_enabled": result["stock_bootloader_security_checks"],
        },
    ]
    notice_files = {p for c in components for p in c["notices"]}
    return {
        "schema": "creo-frozen-runtime-distribution/v1",
        "version": "1.1.0-beta.1",
        "client": result["exe"],
        "client_source_commit": result["source_commit"],
        "runtime": result["runtime"],
        "controlled_distribution": profile["runtime_distribution"],
        "controlled_source_proof": {
            "control_record_sha256": sha(control_data),
            "fixed_xz_sources": control["fixed_xz_sources"],
            "xz_static_library_sha256": control["xz_static_library_sha256"],
            "lzma_link_record_sha256": control["lzma_link_record_sha256"],
            "upstream_regressions": control["upstream_regressions"],
            "test_lzma": control["test_lzma"],
            "patches": control["patches"],
        },
        "embedded_client_build_sha256": sha(embedded),
        "components": components,
        "native_files": native,
        "archive_members": members,
        "python_modules": modules,
        "notices": {
            n: {"sha256": sha((ROOT / n).read_bytes()), "bytes": (ROOT / n).stat().st_size}
            for n in sorted(notice_files)
        },
        "windows_ucrt": (
            "Operating-system component on the qualified Windows host; "
            "no ucrtbase.dll or API-set DLLs are bundled"
        ),
        "upstream_sbom_scope": (
            "The full PSF SBOM is baseline provenance; controlled CPython/XZ source "
            "build identities override it. "
            "pip, Tk, Expat and uncollected packages in it are not claimed as shipped"
        ),
        "security_scope": (
            "Official Python/OpenSSL/SQLite/PyInstaller/XZ advisories reviewed 2026-10-31; "
            "fixed PyPI build lock audited separately. "
            "Not a comprehensive native CVE certification or future vulnerability guarantee"
        ),
        "security_sources": profile["security_sources"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", required=True, type=Path)
    parser.add_argument("--build-result", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    value = inspect(args.exe, args.build_result)
    if args.output.exists():
        raise ValueError("Preserve previous inventories; use a new output path")
    args.output.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "exe": value["client"],
                "native_files": len(value["native_files"]),
                "components": len(value["components"]),
            }
        )
    )
