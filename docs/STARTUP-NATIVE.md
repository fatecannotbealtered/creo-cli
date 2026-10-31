# Owned Windows startup

Use the complete verified ZIP. From its root, initialize with
cli/examples/engineering/Initialize-CreoWorkspace.ps1 and explicit absolute paths
for WorkRoot, HistoryDirectory, CreoRoot and JavaHome (see README). The initializer
verifies PACKAGE-MANIFEST.json, installs the original service via the actual EXE's
preview/confirm loop, records its environment and creates empty project/output directories.
There is no private-project restoration step. Retain your existing history directory.

Place package and run under one dedicated workspace. The declared scope includes
the run, package and exact workspace/.creo-cli/staging, with outputs limited to run
and that staging path. It rejects links/junctions and refuses an existing installation.
It never adds authorization after a blocked preview. Explicit initialization authorizes
only the isolated workflow described in README; use copied projects with known rights.

Run Start-CreoWorkspace.ps1 with -WorkRoot and -PreflightOnly first. Inspect its
component, original unlock, NotSigned, host-version and effective-policy results.
Then the same command without -PreflightOnly creates one owned windowed process
with separate startup/runtime/recovery directories. It does not attach to or close
other sessions. The process-local unsigned policy is broader than one DLL; global
policy, trust stores, vendor installation and licensing are not modified.

Before CAD calls, use the environment_variables retained in run/environment.json
for that CLI process. Use the supplied [PowerShell invocation helper](../examples/engineering/Invoke-CreoCli.md)
to pass arguments and retain stdout/stderr/metadata. Verify context and doctor bind
the actual loaded EXE/JAR/DLL, generation and session identity. The preflight is not
startup evidence; installation is not loaded-component evidence.

The direct start-owned-creo.ps1 helper retains its signed and explicit unsigned
profiles. No global reload/restart is an upgrade path. Keep loaded components
immutable; a service upgrade needs a new source-bound generation and owned directories.
Keep pending/unknown receipts and stopped instances. A timeout is not cancellation.
Normal exit uses session exit only for the recorded owned process after clean-model
close and empty-session verification, with fresh confirmation and held-process exit proof.
