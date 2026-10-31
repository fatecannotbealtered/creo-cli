"""Signing deployment boundaries; synthetic PE data and fake tools, no CAD/signing."""

from __future__ import annotations

import json
import struct
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts import build_native_sketch as native
from scripts import prepare_native_signing as deployment


def unsigned_pe() -> bytes:
    data = bytearray(517)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 60, 128)
    data[128:132] = b"PE\0\0"
    struct.pack_into("<H", data, 132, 0x8664)
    struct.pack_into("<H", data, 148, 240)
    struct.pack_into("<H", data, 152, 0x20B)
    struct.pack_into("<I", data, 260, 16)
    payload = b"original-unlock-data"
    data[-len(payload) :] = payload
    return bytes(data)


def signed_pe(data: bytes) -> bytes:
    result = bytearray(data)
    checksum, security, _, _ = deployment.pe_offsets(data)
    address = (len(data) + 7) & ~7
    result.extend(b"\0" * (address - len(data)))
    certificate = struct.pack("<IHH", 16, 0x200, 2) + b"TESTONLY"
    struct.pack_into("<I", result, checksum, 0xABCDEF00)
    struct.pack_into("<II", result, security, address, len(certificate))
    result.extend(certificate)
    return bytes(result)


def test_only_checksum_security_entry_certificate_and_zero_alignment_can_change():
    before = unsigned_pe()
    assert deployment.same_signed_payload(before, signed_pe(before)) == {
        "all_presign_payload_bytes_preserved": True,
        "certificate_table_bytes": 16,
        "alignment_zero_bytes": 3,
    }


@pytest.mark.parametrize("offset", [400, 500, 160])
def test_changed_code_unlock_overlay_or_header_is_rejected(offset):
    before = unsigned_pe()
    changed = bytearray(signed_pe(before))
    changed[offset] ^= 1
    with pytest.raises(ValueError, match="protected PE"):
        deployment.same_signed_payload(before, bytes(changed))


def test_extra_overlay_and_nonzero_alignment_are_rejected():
    before = unsigned_pe()
    with pytest.raises(ValueError, match="layout"):
        deployment.same_signed_payload(before, signed_pe(before) + b"extra")
    changed = bytearray(signed_pe(before))
    changed[len(before)] = 1
    with pytest.raises(ValueError, match="nonzero"):
        deployment.same_signed_payload(before, bytes(changed))


def test_already_signed_input_is_not_a_preparation():
    data = signed_pe(unsigned_pe())
    with pytest.raises(ValueError, match="unsigned PE"):
        deployment.same_signed_payload(data, data)


def preparation_files(tmp_path: Path):
    original = tmp_path / "original.dll"
    original.write_bytes(unsigned_pe())
    signed = tmp_path / "returned.dll"
    signed.write_bytes(signed_pe(original.read_bytes()))
    preparation = tmp_path / "preparation.json"
    preparation.write_text(
        json.dumps(
            {
                "status": "pending_authorized_external_authenticode_signing",
                "unlock_mode": "-cd",
                "unsigned_retained": deployment.identity(original),
            }
        ),
        encoding="utf-8",
    )
    tool = tmp_path / "signtool.exe"
    tool.write_bytes(b"declared-tool-fixture")
    return original, signed, preparation, tool


def signature(**overrides):
    return {
        "status": "Valid",
        "type": "Authenticode",
        "signer_thumbprint": "a" * 40,
        "timestamp_present": True,
        **overrides,
    }


def test_verified_signature_never_claims_native_loaded_or_changes_inputs(tmp_path):
    original, signed, preparation, tool = preparation_files(tmp_path)
    old = (original.read_bytes(), signed.read_bytes())
    with (
        patch.object(deployment, "authenticode", return_value=signature()),
        patch.object(
            deployment.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="fixture verify", stderr=""),
        ) as invoke,
    ):
        result = deployment.verify(preparation, signed, "a" * 40, tool)
    assert result["authenticode_verified"] is True
    assert result["creo_load_trust_verified"] is False
    assert result["CAD_calls"] == result["certificate_or_policy_changes"] == 0
    assert (original.read_bytes(), signed.read_bytes()) == old
    assert invoke.call_args.args[0][1:5] == ["verify", "/pa", "/all", "/v"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"status": "NotSigned"}, "Valid"),
        ({"status": "UnknownError"}, "Valid"),
        ({"type": "Catalog"}, "Valid"),
        ({"signer_thumbprint": "b" * 40}, "approved signer"),
        ({"timestamp_present": False}, "timestamp"),
    ],
)
def test_invalid_unknown_wrong_signer_and_missing_timestamp_refuse(tmp_path, change, message):
    _, signed, preparation, tool = preparation_files(tmp_path)
    with (
        patch.object(deployment, "authenticode", return_value=signature(**change)),
        patch.object(deployment.subprocess, "run") as invoke,
        pytest.raises(ValueError, match=message),
    ):
        deployment.verify(preparation, signed, "a" * 40, tool)
    invoke.assert_not_called()


def test_missing_explicit_signer_or_tampered_preparation_refuses_before_tools(tmp_path):
    original, signed, preparation, tool = preparation_files(tmp_path)
    with pytest.raises(ValueError, match="thumbprint"):
        deployment.verify(preparation, signed, "", tool)
    original.write_bytes(original.read_bytes() + b"tampered")
    with (
        patch.object(deployment, "authenticode") as invoke,
        pytest.raises(ValueError, match="pre-sign input"),
    ):
        deployment.verify(preparation, signed, "a" * 40, tool)
    invoke.assert_not_called()


def test_signtool_failure_or_warning_refuses(tmp_path):
    _, signed, preparation, tool = preparation_files(tmp_path)
    for code in (1, 2):
        with (
            patch.object(deployment, "authenticode", return_value=signature()),
            patch.object(
                deployment.subprocess,
                "run",
                return_value=SimpleNamespace(returncode=code, stdout="", stderr="fixture failure"),
            ),
            pytest.raises(ValueError, match="SignTool"),
        ):
            deployment.verify(preparation, signed, "a" * 40, tool)


def test_changed_return_during_windows_verification_is_rejected(tmp_path):
    _, signed, preparation, tool = preparation_files(tmp_path)

    def changing_return(_):
        signed.write_bytes(signed.read_bytes() + b"changed during verification")
        return signature()

    with (
        patch.object(deployment, "authenticode", side_effect=changing_return),
        patch.object(
            deployment.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
        ),
        pytest.raises(ValueError, match="during verification"),
    ):
        deployment.verify(preparation, signed, "a" * 40, tool)


def test_cd_unlock_is_not_an_authenticode_signature():
    response = SimpleNamespace(
        returncode=0,
        stdout=b"Successfully unlocked application.\nAlert: sign using signtool.\n",
        stderr=b"",
    )
    with patch.object(native.subprocess, "run", return_value=response) as invoke:
        assert "signtool" in native.unlock(
            Path("installed-creo"), Path("owned.dll"), signing_required=True
        )
    assert "-cd" in invoke.call_args.args[0]


def test_false_zero_success_without_unlock_witness_refuses():
    response = SimpleNamespace(
        returncode=0, stdout=b"tool completed without unlock witness", stderr=b""
    )
    with patch.object(native.subprocess, "run", return_value=response), pytest.raises(RuntimeError):
        native.unlock(Path("installed-creo"), Path("owned.dll"))


def test_prepare_preserves_separate_input_and_records_pending_not_signed(tmp_path):
    source = tmp_path / "source.c"
    source.write_text("int fixture;", encoding="utf-8")

    def compile_fixture(_, *, output):
        output.parent.mkdir(parents=True)
        output.write_bytes(unsigned_pe())
        return {"dll": str(output)}

    target = tmp_path / "new-preparation"
    with (
        patch.object(native, "SOURCE", source),
        patch.object(native, "build", side_effect=compile_fixture),
        patch.object(native, "unlock", return_value="Successfully unlocked application.") as unlock,
        patch.object(deployment.subprocess, "check_output", return_value="fixture-source-commit\n"),
    ):
        result = deployment.prepare(tmp_path / "creo", target)
    assert unlock.call_args.kwargs["signing_required"] is True
    assert result["unlock_mode"] == "-cd"
    assert result["authenticode_verified"] is result["creo_load_trust_verified"] is False
    assert result["ready_for_Creo_load"] is False
    assert result["unsigned_retained"]["sha256"] == result["signing_input"]["sha256"]
    assert result["unsigned_retained"]["path"] != result["signing_input"]["path"]
    with pytest.raises(ValueError, match="new directory"):
        deployment.prepare(tmp_path / "creo", target)


def test_existing_stamp_never_proves_authenticode_or_creo_trust(tmp_path):
    output = tmp_path / "known.dll"
    output.write_bytes(b"known toolkit-unlocked fixture")
    stamp = tmp_path / "known.stamp.json"
    stamp.write_text(
        json.dumps(
            {
                "source": "known-source",
                "dll_sha256": deployment.identity(output)["sha256"],
                "toolkit_unlocked": True,
                "unlock_mode": "-c",
            }
        ),
        encoding="utf-8",
    )
    with (
        patch.object(native, "OUTPUT", output),
        patch.object(native, "STAMP", stamp),
        patch.object(native, "fingerprint", return_value="known-source"),
        patch.object(native, "build") as compile_new,
    ):
        result = native.ensure(tmp_path / "creo")
    compile_new.assert_not_called()
    assert result["toolkit_unlocked"] is True
    assert result["authenticode_verified"] is result["creo_load_trust_verified"] is False
    assert "signed" not in result
