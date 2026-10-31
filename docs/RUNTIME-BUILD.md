# Controlled Windows runtime build

The client uses a project-controlled CPython 3.15.2 build with XZ 5.8.4. It is
not a stock PSF binary package. Exact source URLs, commits and archive hashes are
in release/CONTROLLED-RUNTIME-INPUTS.json; compiler/configuration and resulting
native-file identities are in release/CONTROLLED-RUNTIME.json.

The existing MSVC 17.14 toolchain builds ordinary x64 Release CPython. The original
CPython C sources are unchanged. The recorded _lzma project patch links the new
static liblzma built from the full official XZ 5.8.4 library sources. Merely adding
an XZ DLL would not update this statically linked extension.

Use a new isolated directory containing the verified CPython and XZ sources and
the seven fixed dependencies under CPython's externals directory. No installation,
global trust change or new credentials is part of the build. The relevant commands
below use placeholders for the existing tools and source/build directories:

```text
cmake -S <xz-source> -B <xz-build> -G "Visual Studio 17 2022" -A x64
  -DBUILD_SHARED_LIBS=OFF -DBUILD_TESTING=ON -DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreadedDLL
  -DCMAKE_C_FLAGS="/guard:cf /utf-8"
  -DXZ_TOOL_XZ=OFF -DXZ_TOOL_XZDEC=OFF -DXZ_TOOL_LZMADEC=OFF -DXZ_TOOL_LZMAINFO=OFF
  -DXZ_NLS=OFF -DXZ_DOC=OFF
cmake --build <xz-build> --config Release --target liblzma test_index test_alone_decoder --parallel 4
```

Apply the recorded _lzma build-project wiring. Run MSBuild from CPython's PCbuild
directory with the properties below. The relative source paths and local props file
remove build-directory disclosure from diagnostics; /PDBALTPATH:%_PDB% retains a
path-free PDB reference. Stack protection, CFG, ASLR and NX remain enabled.
The separate mpdecimal patch adds one standard #line directive for the header's
diagnostic filename; its arithmetic, error branches and original line numbers
are unchanged. Preserve this modification record with the original BSD notice.

```text
environment: _LINK_=/guard:cf /PDBALTPATH:%_PDB%
environment: GIT_CEILING_DIRECTORIES=<isolated-build-root>
MSBuild pcbuild.proj /t:Build /m:4 /p:Configuration=Release /p:Platform=x64
  /p:PlatformToolset=v143 /p:IncludeExternals=true /p:IncludeTkinter=false
  /p:IncludeTests=true /p:KillPython=false /p:EnableControlFlowGuard=Guard
  /p:PythonForBuild=<verified-bootstrap-python> /p:PySourcePath=..\ /p:ExternalsDir=..\externals\
  /p:lzmaDir=<xz-source>/ /p:ControlledLzmaLibrary=<xz-build>/Release/lzma.lib
  /p:ForceImportBeforeCppTargets=<no-host-paths.props>
```

Validation runs unmodified CPython test_lzma and the original upstream functions
test_reuse_after_failure and test_decode_empty_and_append using the upstream test
selector. The complete original archives are preserved; unrelated hostile corpus
is outside this two-regression selection. No library source or test function is
removed or changed. Exact compile/link input identities bind _lzma.pyd to this library.

The assembled private build runtime uses the compiled core/extensions and standard
library, the pinned official Python dependency binaries for OpenSSL/libffi, and
the reviewed Microsoft VC files from the official Python distribution. The complete
client is then frozen with scripts/build_public_client.py and the fixed build lock.
No DLL is replaced inside a frozen client. JAR/DLL service components are unchanged.

Sources, configuration and commands can be reproduced with the recorded toolchain.
Bit-for-bit reproducibility across different machines/toolchain revisions is not
claimed; PE/PDB metadata can differ. Different native bytes require a new reviewed
runtime profile and fresh package checks rather than silently changing the pins.
