# Experimental PTC VB API adapter

## Status

This is implementation source with interface-shaped tests, **not** a recorded
run against an installed PTC SDK. It has not been compiled/loaded against your
Creo version or licensed environment. Expect installation-specific typelib,
COM conversion, unit-system and regeneration behavior to need verification.
No native production-readiness claim is made.

## Required environment

Use compatible 64-bit x86 Windows Python and the installed Creo VB API components.
Install the optional Python binding explicitly. Set `PRO_COMM_MSG_EXE` to the
communication program in your actual Creo installation, not a guessed path.
Register PTC's COM components using the installation's documented procedure; this
CLI does not elevate privileges or register software. Open a disposable part
manually in an unambiguous running Creo session. Keep a recoverable baseline.

The local probe checks platform/architecture, pywin32 presence, the communication
executable and `pfcls.CCpfcAsyncConnection` registration. It reports license status
as unknown. These checks do not connect to Creo or prove runtime compatibility.

## Current connection/operation design

The worker uses the documented `CCpfcAsyncConnection` factory, connects to the
running session, hashes its connection identity and detaches at the end. It does
not terminate Creo. JSON actions are allowlisted; raw code/macros are not accepted.
Model selection is exact loaded filename, case-insensitive, with ambiguity refused.
It never auto-retrieves a model from a guessed working directory.

Snapshot revision is a digest of observed metadata/values/relations/features and
session identity; it is not a PTC revision stamp or full BREP fingerprint. Reads
are not an atomic snapshot while the GUI or another automation client is editing.
The user must prevent concurrent work. Observe and approve the preview's model.

Write scope is limited to existing parameters and linear dimensions on a part.
Types are preserved; relation-driven, angular, radial/diameter and unknown dimensions
are refused. Dimensions use the reported principal unit-system name and raw model
unit values; no assumption that every installation reports mm. The current
implementation's unit handling needs live verification before engineering use.

The worker checks modifiability without prompting, consumes the token, records an
audit start, edits, regenerates, checks new failed features and rereads requested
values. It does not save. On failure, it attempts to restore values and regenerate,
but explicitly reports that the entire model is not proven restored.

`--timeout` bounds the external worker wait. A request already executing in Creo
may outlive the worker. This is unknown state, not proof that nothing changed.
No CLI command saves, closes, opens, creates or exports a native model yet.

## Primary API references consulted

Public Creo 13 VB API reference pages (documentation research, not executable evidence):
- Async connection lifecycle, connection identity and disconnect/end distinction:
  https://support.ptc.com/help/creo_toolkit/vbapi_pma/r13/usascii/creo_toolkit/api/dita/t-pfcAsyncConnection-AsyncConnection.html
- Model metadata and modifiability:
  https://support.ptc.com/help/creo_toolkit/vbapi_pma/r13/usascii/creo_toolkit/api/dita/t-pfcModel-Model.html
- Base dimensions, dimension types and value handling:
  https://support.ptc.com/help/creo_toolkit/vbapi_pma/r13/usascii/creo_toolkit/api/dita/t-pfcDimension-BaseDimension.html
- Parameter owner, typed parameter values and relation-driven status:
  https://support.ptc.com/help/creo_toolkit/vbapi_pma/r13/usascii/creo_toolkit/api/dita/t-pfcModelItem-ParameterOwner.html
- Session model enumeration:
  https://support.ptc.com/help/creo_toolkit/vbapi_pma/r13/usascii/creo_toolkit/api/dita/t-pfcSession-BaseSession.html
- Solid features, failed features, principal units and regeneration:
  https://support.ptc.com/help/creo_toolkit/vbapi_pma/r13/usascii/creo_toolkit/api/dita/t-pfcSolid-Solid.html

The source's dynamic COM names, casts and call signatures still require validation
against the installed typelib. Fake objects deliberately do not claim to prove
those bindings. Never change that status merely because Python unit tests pass.
