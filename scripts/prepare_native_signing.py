"""Prepare a new -cd DLL or verify an externally signed return; never sign or set trust.

This developer utility does not start Creo, run the business CLI, import certificates
or modify any config.pro. External signing uses an authorized enterprise/CA signer.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import build_native_sketch  # noqa: E402


def identity(path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}


def local_path(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute() or str(path).startswith("\\\\"):
        raise ValueError("use an absolute local path")
    if any(ord(char) < 32 or char in '"%\r\n' for char in str(path)):
        raise ValueError("path contains unsupported build-shell characters")
    if path.is_symlink() or (path.exists() and path.resolve() != path.absolute()):
        raise ValueError("links and redirected paths are refused")
    return path.resolve()


def write_new(path: Path, data: dict) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(data, stream, indent=2, ensure_ascii=False)
        stream.write("\n")


def prepare(creo: Path, output: Path) -> dict:
    """Compile into a new directory and legally unlock -cd; signing stays pending."""
    if output.exists():
        raise ValueError("output must be a new directory; previous bytes are preserved")
    source_before = identity(build_native_sketch.SOURCE)
    fingerprint = build_native_sketch.fingerprint()
    output.mkdir(parents=True, exist_ok=False)
    unsigned = output / "unsigned" / "creo_cli_sketch.dll"
    record = {
        "schema_version": "1.0",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "status": "preparing",
        "source": source_before,
        "source_fingerprint": fingerprint,
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "creo_loadpoint": str(creo),
        "signing_operations": 0,
        "CAD_calls": 0,
        "certificate_or_policy_changes": 0,
    }
    try:
        record["compile"] = build_native_sketch.build(creo, output=unsigned)
        record["before_unlock"] = identity(unsigned)
        record["unlock_result"] = build_native_sketch.unlock(creo, unsigned, signing_required=True)
        if (
            identity(build_native_sketch.SOURCE) != source_before
            or build_native_sketch.fingerprint() != fingerprint
        ):
            raise ValueError("native source or compile flags changed during preparation")
        record["toolkit_unlocked"] = True
        record["unlock_mode"] = "-cd"
        record["unsigned_retained"] = identity(unsigned)
        signing_input = output / "signing-input" / unsigned.name
        signing_input.parent.mkdir()
        shutil.copyfile(unsigned, signing_input)
        record["signing_input"] = identity(signing_input)
        record["authenticode_verified"] = False
        record["creo_load_trust_verified"] = False
        record["status"] = "pending_authorized_external_authenticode_signing"
        record["ready_for_Creo_load"] = False
    except Exception as error:
        record["status"] = "preparation_failed"
        record["error"] = f"{type(error).__name__}: {error}"
        write_new(output / "preparation.json", record)
        raise
    write_new(output / "preparation.json", record)
    return record


def pe_offsets(raw: bytes) -> tuple[int, int, int, int]:
    """Read documented PE offsets; signature cryptography is delegated to Windows."""
    if len(raw) < 64 or raw[:2] != b"MZ":
        raise ValueError("not a PE DLL")
    pe = struct.unpack_from("<I", raw, 60)[0]
    if pe + 24 > len(raw) or raw[pe : pe + 4] != b"PE\0\0":
        raise ValueError("invalid PE header")
    (machine,) = struct.unpack_from("<H", raw, pe + 4)
    (optional_size,) = struct.unpack_from("<H", raw, pe + 20)
    optional = pe + 24
    if machine != 0x8664 or optional + optional_size > len(raw):
        raise ValueError("an intact AMD64 PE image is required")
    (magic,) = struct.unpack_from("<H", raw, optional)
    if magic != 0x20B or optional_size < 152:
        raise ValueError("an intact PE32+ optional header is required")
    (directories,) = struct.unpack_from("<I", raw, optional + 108)
    if directories < 5:
        raise ValueError("PE security directory absent")
    checksum, security = optional + 64, optional + 112 + 4 * 8
    address, size = struct.unpack_from("<II", raw, security)
    return checksum, security, address, size


def same_signed_payload(before: bytes, after: bytes) -> dict:
    """Require every pre-sign byte except checksum/security entry to be unchanged.

    Accept only a terminal certificate table added after at most seven zero bytes
    of alignment. This is a bounded signing return check, not an Authenticode verifier.
    """
    checksum, security, old_address, old_size = pe_offsets(before)
    a_checksum, a_security, address, size = pe_offsets(after)
    if (checksum, security) != (a_checksum, a_security) or old_address or old_size:
        raise ValueError("preparation must contain the exact unsigned PE input")
    aligned = (len(before) + 7) & ~7
    if address != aligned or size < 8 or address + size != len(after):
        raise ValueError("unexpected certificate-table layout or additional payload")
    if after[len(before) : address] != b"\0" * (address - len(before)):
        raise ValueError("nonzero bytes appeared before the certificate table")
    expected, actual = bytearray(before), bytearray(after[: len(before)])
    for offset, length in ((checksum, 4), (security, 8)):
        expected[offset : offset + length] = b"\0" * length
        actual[offset : offset + length] = b"\0" * length
    if expected != actual:
        raise ValueError("externally signed return changed protected PE or Toolkit-unlock bytes")
    return {
        "all_presign_payload_bytes_preserved": True,
        "certificate_table_bytes": size,
        "alignment_zero_bytes": address - len(before),
    }


def authenticode(path: Path) -> dict:
    """Use Windows public certificate metadata; do not read or export private keys."""
    shell = shutil.which("pwsh")
    if not shell:
        raise ValueError("PowerShell 7 is required for Windows signature verification")
    command = (
        "$ErrorActionPreference='Stop';"
        "$s=Get-AuthenticodeSignature -LiteralPath $env:CREO_CLI_SIGNATURE_FILE;"
        "[ordered]@{status=[string]$s.Status;type=[string]$s.SignatureType;"
        "signer_thumbprint=$(if($s.SignerCertificate){$s.SignerCertificate.Thumbprint}else{$null});"
        "signer_subject=$(if($s.SignerCertificate){$s.SignerCertificate.Subject}else{$null});"
        "timestamp_present=($null -ne $s.TimeStamperCertificate)}|ConvertTo-Json -Compress"
    )
    environment = dict(os.environ, CREO_CLI_SIGNATURE_FILE=str(path))
    result = subprocess.run(
        [shell, "-NoProfile", "-NonInteractive", "-Command", command],
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(result.stdout)


def verify(preparation: Path, signed: Path, signer: str, signtool: Path) -> dict:
    """Validate a returned signature and exact prepared payload without modifying it."""
    if not re.fullmatch(r"[a-fA-F0-9]{40}", signer):
        raise ValueError("an explicitly approved exact signer certificate thumbprint is required")
    prepared = json.loads(preparation.read_text(encoding="utf-8"))
    if (
        prepared.get("status") != "pending_authorized_external_authenticode_signing"
        or prepared.get("unlock_mode") != "-cd"
    ):
        raise ValueError("a successful -cd preparation is required")
    original = local_path(prepared["unsigned_retained"]["path"])
    if identity(original) != prepared["unsigned_retained"]:
        raise ValueError("retained pre-sign input changed")
    before = identity(signed)
    payload = same_signed_payload(original.read_bytes(), signed.read_bytes())
    signature = authenticode(signed)
    if signature.get("status") != "Valid" or signature.get("type") != "Authenticode":
        raise ValueError("Windows Authenticode validation did not report Valid")
    if str(signature.get("signer_thumbprint", "")).lower() != signer.lower():
        raise ValueError("returned signer is not the explicitly approved signer")
    if signature.get("timestamp_present") is not True:
        raise ValueError("an independently validated timestamp is required")
    validation = subprocess.run(
        [str(signtool), "verify", "/pa", "/all", "/v", str(signed)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if validation.returncode != 0:
        raise ValueError("SignTool Authenticode verification failed or warned")
    if identity(signed) != before or identity(original) != prepared["unsigned_retained"]:
        raise ValueError("input changed during verification")
    return {
        "schema_version": "1.0",
        "status": "external_signature_verified_not_loaded",
        "signed_dll": before,
        "preparation": identity(preparation),
        "protected_payload": payload,
        "authenticode": signature,
        "signtool": identity(signtool),
        "signtool_verification": {
            "exit_code": validation.returncode,
            "output": validation.stdout + validation.stderr,
        },
        "authenticode_verified": True,
        "creo_load_trust_verified": False,
        "CAD_calls": 0,
        "certificate_or_policy_changes": 0,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    prepare_parser = actions.add_parser(
        "prepare", help="compile/unlock -cd into new owned output; no signing"
    )
    prepare_parser.add_argument("--creo", required=True)
    prepare_parser.add_argument("--output", required=True)
    verify_parser = actions.add_parser(
        "verify", help="read-only verification of an externally signed return"
    )
    verify_parser.add_argument("--preparation", required=True)
    verify_parser.add_argument("--signed-dll", required=True)
    verify_parser.add_argument("--expected-signer", required=True)
    verify_parser.add_argument("--signtool", required=True)
    verify_parser.add_argument("--report", required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare(local_path(args.creo), local_path(args.output))
        else:
            result = verify(
                local_path(args.preparation),
                local_path(args.signed_dll),
                args.expected_signer,
                local_path(args.signtool),
            )
            write_new(local_path(args.report), result)
        print(json.dumps({"ok": True, "data": result}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(
            json.dumps(
                {"ok": False, "error": f"{type(error).__name__}: {error}"}, ensure_ascii=False
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
