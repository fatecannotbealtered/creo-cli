# Microsoft runtime components

Microsoft runtime files supplied with the official Python Windows distribution
retain their original notices and applicable Microsoft Distributable Code terms.
The exact component filenames and hashes are in RUNTIME-DISTRIBUTION.json.
The client contains VCRUNTIME140.dll and VCRUNTIME140_1.dll from that official ZIP.
Windows UCRT/API-set libraries are provided by the host operating system; this
package does not contain ucrtbase.dll or API-set DLLs.

Preserve the complete Microsoft binary-build conditions in
PYTHON-3.15.2-LICENSE.txt. Project MIT does not apply to these runtime components.
Their distribution is limited by the supplier's applicable terms, including
preservation of notices, protection of the Microsoft components, and the Windows
platform restriction. This notice does not grant rights to other Microsoft files.

References:
- https://learn.microsoft.com/en-us/legal/windows-sdk/license
- https://learn.microsoft.com/en-us/legal/windows-sdk/redist
- https://learn.microsoft.com/en-us/cpp/windows/universal-crt-deployment
