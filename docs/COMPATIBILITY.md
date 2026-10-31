# Compatibility

What has run, where, and what has not.

Historical baseline `4a8d3fb` evidence is preserved unchanged. Current acceptance is
recorded by round, exact source and loaded components. Use the current engineering
delivery index for the tested scope; the candidate remains beta/FCC partial.

Dimension writes first require the process-only health capability
`dimension_regeneration_readback: 1`; revision/capability declarations do not prove loaded
JAR/DLL or application-instance identity. See service compatibility (private historical record).
Its dimension planning requires `dimension.list` with `check_regeneration=true` to return
completed checker metadata; an older service is refused before the dimension write.
Normal dimension queries retain their existing shape. Native getter faults after a write
leave an incomplete receipt; an unobservable changed target remains unknown. Offline
fixtures and the CPU-only Java scanner tests do not prove runtime SDK/license behavior.

| Surface | Status | Evidence |
|---|---|---|
| Creo Parametric 13.4.1.0 (build 2026163), Windows 11, Object TOOLKIT Java licence, JDK 25.0.3 | Bounded native cases only; neither the command inventory nor migrated-path count proves all variants. Beta/FCC partial. | Per-round evidence summaries and final component bindings under `docs/evidence/` |
| The native sketch library on that Creo | Verified live (rectangles, polygons, circles, the centerline a revolve turns about) | same record |
| The service installed from a bundle (`service install`), registered through `toolkit_registry_file` | Verified by hand on that Creo: the service and the library loaded from the installed directory | `docs/SERVICE.md` |
| Creo's standard templates and sheet formats (`mmns_part_solid_abs`, `mmns_asm_design_abs`, the `a0`..`f` drawing templates) | Verified live for millimetre parts, assemblies and an A3 drawing | same record |
| Other Creo 13.x builds | Not qualified by this trial | none |
| Creo 12 and earlier | Not supported by this trial | none |
| Java 17 / service compile target 17 | Compile target only; runtime Java 17 is not verified. The verified host uses JDK 25.0.3 | Actual source/component binding |
| PyInstaller single EXE | Includes the Python client runtime; no separate Python or Node is required. JAR/DLL are external components | `build.py` and the actual engineer package manifest |
| Supplied START/startup scripts | Require PowerShell 7.4 or later; direct EXE use does not impose that script dependency | Script `#requires` declarations |
| Creo without the `ObjectToolkitJava` licence | The service cannot start as an Object TOOLKIT Java application; nothing works | none |
| Creo delivered by application streaming (PTC trial) | Not usable: no API toolkits, no installer to add them | `doctor` detects it |
| Rebuilt Windows client, official Python 3.15.2/OpenSSL 3.5.9/SQLite 3.53.4 | Bounded offline contract, continuing-history and exact-package checks; original JAR/DLL unchanged | CLIENT-ARTIFACT.json, RUNTIME-DISTRIBUTION.json and package manifest |
| Other Python versions, Linux or macOS | Historical source checks do not qualify this Windows distribution on other hosts | Not qualified for this beta |
| win32-x64 public candidate | Bounded unsigned beta; full FCC, clean-machine deployment and npm publication are not qualified | Exact package manifest and release notes |

Creo itself runs only on Windows, so every command that talks to Creo needs the CLI on
the same Windows machine: the service listens on loopback only.

A different Creo configuration can change behaviour the tests cannot see: another
default template (units), `config.pro` options such as `default_dec_places` or
`pro_material_dir` (where `material list` looks), a localized installation (feature types
are reported by enum name, not the localized label, for this reason). When something
differs, retain local records and inspect process/component provenance first. Only after
the original call has ended and the instance permits CAD reads may `doctor` or
`session status` run; those commands cannot prove that a stopped native call has ended.

The r26-C3 constraint package and its r27 receipt-fix successor do not automatically
inherit all r25-S12 or r20b drawing qualifications. The current handoff (private historical record)
separates artifact/scenario evidence. See [runtime dependencies](RUNTIME-DEPENDENCIES.md)
for bundled versus legal host components and the optional frozen STEP investigation.

The live record builds millimetre parts and, from Creo's default template on this machine,
an inch part; other unit systems (`cm`, `m`, `ft` requests) are exercised only against the
substitute.
