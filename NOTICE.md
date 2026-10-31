# Third-party notices

Creo and Creo Parametric are trademarks of PTC Inc. This independent project is
not provided, endorsed or sponsored by PTC. Project-authored CLI, service, adapters
and Skills are MIT licensed. The source includes API identifiers and tree structures,
not vendor documentation or SDK code. User models, supplier binaries, headers,
libraries, license files and SDK samples are excluded from the public materials.

The complete package contains the project's original unlocked JAR and native DLL.
They rely on a user's separately licensed Creo/API installation. The native DLL is
NotSigned; ordinary unlocking does not create a Windows publisher signature, and
Java unlocking does not remove its runtime license requirements. See
[runtime dependencies](docs/RUNTIME-DEPENDENCIES.md) for the supplier's official guidance.

The unchanged frozen client embeds Python 3.12.10 and dependencies collected by
PyInstaller 6.21.0. Preserve the complete [Python license and binary-build conditions](docs/licenses/PYTHON-3.12.10-LICENSE.md)
and [PyInstaller COPYING and Bootloader Exception](docs/licenses/PYINSTALLER-6.21.0-COPYING.md).
These notices retain the embedded libraries' terms, including applicable Microsoft
VC/UCRT conditions; project MIT is not a substitute license for these components.
No separate ucore68.dll, Java runtime or PTC vendor runtime is redistributed.

Driver schemas and adapted scope checks retain their original source PIN and use
Apache-2.0 under the copyright holder's current licensing statement. See
[driver attribution](.agent/driver/SDK-NOTICE.txt), [LICENSE](.agent/driver/LICENSE),
[current notices](.agent/driver/THIRD_PARTY_NOTICES.md) and [asset inventory](.agent/driver/DISTRIBUTION.json).
The inherited ai-native-cli-spec v1.6.3 baseline remains MIT; its original copyright
and license notice is retained in the current notices and project LICENSE.
