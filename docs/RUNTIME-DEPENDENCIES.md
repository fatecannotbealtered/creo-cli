# Runtime components and redistribution

The complete Windows x64 package uses the unchanged 1.1.0-beta.1 client from source
8049e16f0ffcf6b84188f037f94d6d0f57f85274 and unchanged JAR/DLL from source
156a619cecdb17714481a7dbe2807ebc1a2d8699. It is a repack, not a new component build.
See COMPONENT-ORIGINS.json and PACKAGE-MANIFEST.json for exact bytes and sources.

| Component | License / responsibility |
|---|---|
| Original CLI, Java service and native adapter | Project MIT; ordinary unlocked native adapter, NotSigned |
| Python 3.12.10 and collected libraries | Full Python license and third-party conditions in docs/licenses |
| PyInstaller 6.21.0 bootloader | COPYING and Bootloader Exception in docs/licenses |
| Driver schemas and adapted scope checks | Apache-2.0, current attribution and fixed PIN in .agent/driver |
| Inherited ai-native-cli-spec v1.6.3 | MIT, project copyright notice retained |
| Microsoft VC/UCRT files embedded in EXE | Applicable Microsoft/Python binary redistribution conditions |
| Creo, ucore68.dll, SDK, Java runtime and licenses | Supplied by the user's licensed installation; not bundled |

The bounded host was Windows x64, Creo 13.4.1.0 (build 2026163), JDK 25.0.3 and
PowerShell 7.4+. Java's target bytecode level does not qualify Java 17 as a host.
The C DLL dynamically imports ucore68.dll from Creo; the package does not redistribute it.
The unlocked Java application still requires the applicable PTC runtime/development
license options. Unlocking is separate from Windows Authenticode signing.

PTC describes distribution of unlocked applications subject to the applicable
agreement in its [native TOOLKIT guide](https://support.ptc.com/help/creo_toolkit/protoolkit_pma/r13/usascii/creo_toolkit/user_guide/Unlocking_a_Creo_Toolkit_Application.html)
and [Java guide](https://support.ptc.com/help/creo_toolkit/otk_java_pma/r13/usascii/creo_toolkit/user_guide/Unlocking_Running_and_Signing_the_Creo_Object_TOOLKIT_Java_Application.html).
These are references, not a redistribution grant for vendor SDK or program files.
The supplier documentation, models, installation files and license material are excluded.
