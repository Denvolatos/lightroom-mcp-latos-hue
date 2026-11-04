# Third-party notices

From the commits of 2026-11-03 on, this project's own code is licensed under the GNU AGPL-3.0 (`AGPL-3.0-only`, see `LICENSE`);
the releases v0.1.0 to v0.14.0 stay MIT-licensed. The sections below list what the binary releases bundle. Versions and licenses were
read from the installed package metadata (`importlib.metadata`) of the build environment; check each package's own license file for
the authoritative text. Copies of the license files are in the `licenses/` folder of the source tree.

## A. `lrmcp.exe` (command-line server, built with PyInstaller)

A binary release of `lrmcp.exe` bundles these packages and Python itself, so their licenses apply to that bundle. It depends on the packages below.

| Package | Version tested | License (from metadata) |
|---|---|---|
| mcp, mcp-types | 2.3.0 | MIT |
| pillow | 13.0.0 | MIT-CMU |
| pydantic, pydantic_core | 2.14.2 / 2.50.2 | MIT |
| starlette | 1.10.0 | BSD-3-Clause |
| uvicorn | 0.54.0 | BSD-3-Clause |
| sse-starlette | 3.6.0 | BSD-3-Clause |
| httpx2, httpcore2 | 2.16.0 | BSD-3-Clause |
| anyio | 4.16.0 | MIT |
| h11 | 0.16.0 | MIT |
| click | 8.5.0 | BSD-3-Clause |
| idna | 3.20 | BSD-3-Clause |
| jsonschema, jsonschema-specifications, referencing, rpds-py, attrs | 4.26.0 / 2025.9.1 / 0.37.0 / 2026.9.1 / 26.1.0 | MIT |
| annotated-types, typing-inspection, truststore, PyJWT | 0.8.0 / 0.4.4 / 0.10.5 / 2.15.1 | MIT |
| opentelemetry-api, python-multipart | 1.45.2 / 0.0.33 | Apache-2.0 |
| typing_extensions | 4.16.0 | PSF-2.0 |
| pywin32 (Windows only) | 312 | PSF |
| cryptography (needed by `PyJWT[crypto]`; its binary wheels include OpenSSL, see its notices) | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| cffi / pycparser (needed by cryptography) | 2.1.1 / 3.12 | MIT-0 / BSD-3-Clause |
| setuptools (bundled by PyInstaller) | 84.2.1 | MIT |
| Python itself (bundled in the binary release) | 3.12 | PSF License |

**Compatibility.** Every package above is under a permissive license (MIT, MIT-CMU, MIT-0, BSD-3-Clause, Apache-2.0, PSF) that is
generally regarded as compatible with the AGPL-3.0 (Apache-2.0 is compatible with the GPLv3 family). This is our reading, not
legal advice (待验证 by a lawyer if it matters to you). The packages keep their own licenses.

**Build tools (not shipped in the source tree).** PyInstaller (6.22.3) is licensed "GPLv2-or-later with a special
exception which allows to use PyInstaller to build and distribute non-free programs", per its package metadata.
Inno Setup is used to build the installer.

## B. Latos Hue desktop app (`LatosHue.exe`, folder `_internal`)

The list is the module table (PYZ) of the PyInstaller build in `build\app_dist\LatosHue` plus the `*.dist-info` folders and
DLLs found in `_internal`, mapped to the installed packages. Version = version installed in the build environment.

| Package | Version | License (SPDX, from metadata) | Project page |
|---|---|---|---|
| pywebview | 6.2.1 | BSD-3-Clause (metadata: BSD classifier and "BSD 3-Clause License" text) | https://pywebview.flowrl.com/ |
| pythonnet | 3.2.1 | MIT | https://pythonnet.github.io/ |
| clr_loader | 0.3.1 | MIT (no SPDX field in metadata; the license file is the MIT text) | https://github.com/pythonnet/clr-loader |
| pillow | 13.0.0 | MIT-CMU | https://pillow.readthedocs.io |
| mcp, mcp-types | 2.3.0 | MIT | https://modelcontextprotocol.io |
| httpx2, httpcore2 | 2.16.0 | BSD-3-Clause | https://github.com/pydantic/httpx2 |
| anyio | 4.16.0 | MIT | https://github.com/agronholm/anyio |
| h11 | 0.16.0 | MIT | https://github.com/python-hyper/h11 |
| idna | 3.20 | BSD-3-Clause | https://github.com/kjd/idna |
| pydantic / pydantic_core | 2.14.2 / 2.50.2 | MIT | https://github.com/pydantic/pydantic |
| annotated-types, typing-inspection | 0.8.0 / 0.4.4 | MIT | https://github.com/annotated-types/annotated-types , https://github.com/pydantic/typing-inspection |
| typing_extensions | 4.16.0 | PSF-2.0 | https://github.com/python/typing_extensions |
| starlette | 1.10.0 | BSD-3-Clause | https://github.com/Kludex/starlette |
| uvicorn | 0.54.0 | BSD-3-Clause | https://uvicorn.dev/ |
| sse-starlette | 3.6.0 | BSD-3-Clause | https://github.com/sysid/sse-starlette |
| python-multipart | 0.0.33 | Apache-2.0 | https://github.com/Kludex/python-multipart |
| click | 8.5.0 | BSD-3-Clause | https://click.palletsprojects.com/ |
| jsonschema, jsonschema-specifications, referencing | 4.26.0 / 2025.9.1 / 0.37.0 | MIT | https://github.com/python-jsonschema/jsonschema |
| rpds-py | 2026.9.1 | MIT | https://github.com/crate-py/rpds |
| attrs | 26.1.0 | MIT | https://www.attrs.org/ |
| opentelemetry-api | 1.45.2 | Apache-2.0 | https://github.com/open-telemetry/opentelemetry-python |
| truststore | 0.10.5 | MIT | https://github.com/sethmlarson/truststore |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause (its wheels include OpenSSL) | https://github.com/pyca/cryptography |
| cffi / pycparser | 2.1.1 / 3.12 | MIT-0 / BSD-3-Clause | https://cffi.readthedocs.io/ , https://github.com/eliben/pycparser |
| pywin32 | 312 | PSF (metadata says "PSF"; exact SPDX id 待验证) | https://github.com/mhammond/pywin32 |
| bottle | 0.13.4 | MIT | http://bottlepy.org/ |
| proxy_tools | 0.1.0 | MIT (metadata only; the package ships no license file) | http://github.com/jtushman/proxy_tools |
| PyInstaller (the bootloader of both .exe files and its run-time hooks; its other Python modules are excluded since 1.0.0) | 6.22.3 | GPL-2.0-or-later WITH Bootloader-exception; run-time hooks Apache-2.0 | https://pyinstaller.org |
| Python itself (`python312.dll`, standard library) | 3.12.16 | PSF-2.0 | https://www.python.org |

PyInstaller: only its compiled bootloader (inside `LatosHue.exe` and `latoshue-helper.exe`) is shipped; its `COPYING.txt` gives unlimited
permission to embed the bootloader in the programs it builds (GPL-2.0-or-later WITH Bootloader-exception). The other `PyInstaller.*` Python
modules (GPL-2.0-or-later, no such exception) are excluded from the build since 1.0.0. The bootloader exception is our reading, not legal advice
(待验证 by a lawyer if it matters to you).

**Native libraries in `_internal`** (license from the conda package metadata of the build environment): OpenSSL 3.5.9
(`libssl-3-x64.dll`, `libcrypto-3-x64.dll`, Apache-2.0), libffi 3.4.8 (`ffi.dll`, MIT), libexpat 2.9.0 (`libexpat.dll`, MIT), bzip2 1.0.8
(`LIBBZ2.dll`, bzip2-1.0.8), zlib 1.3.2 (`zlib.dll`, Zlib), liblzma from xz 5.8.4 (`liblzma.dll`; conda lists the whole xz package as
"LGPL-2.1-or-later and GPL-2.0-or-later and 0BSD"; the library itself should be 0BSD, 待验证), the Microsoft Visual C++ runtime
(`VCRUNTIME140*.dll`, conda license id `LicenseRef-MicrosoftVisualCpp2015-2022Runtime`) and the Universal CRT (`ucrtbase.dll`,
`api-ms-win-*.dll`, `LicenseRef-MicrosoftWindowsSDK10`). The Microsoft files are redistributable runtime files; their exact terms are 待验证.

**WebView2 SDK files inside pywebview** (`webview\lib`): `Microsoft.Web.WebView2.Core.dll`, `Microsoft.Web.WebView2.WinForms.dll`,
`WebView2Loader.dll` (file version 1.0.3856.49, Microsoft; project page https://aka.ms/webview). pywebview ships no separate license
text for them and their license is 待验证 (check the license page of the NuGet package `Microsoft.Web.WebView2`).
`WebBrowserInterop.*.dll` belongs to pywebview, `ClrLoader.dll` to clr_loader (both listed above).

## C. Not shipped by this project, but involved

- **Microsoft Edge WebView2 Runtime** is *not* distributed with this software. The Latos Hue window uses it, so it must already be
  installed on the user's system.
- **Inno Setup** (6.x) is used to generate the installer. Its license (`license.txt` in the Inno Setup folder; copy in
  `licenses/Inno-Setup-6/`) permits use, alteration and redistribution for any purpose, including commercial, provided its copyright
  notices and conditions are kept; the installer program contains Inno's run-time code, so those notices apply to it.
- **PyInstaller** is a build tool (see above; its bootloader is embedded in the .exe files).
- **Adobe Lightroom Classic and the Adobe SDK** are not included in any form (see the Adobe section below).

## Contributions under the MIT license / 按 MIT 许可提交的贡献

Code contributed before 2026-11-03 under the MIT license stays under the MIT license, together with its copyright notice:
2026-11-03 之前按 MIT 许可提交的代码仍保留 MIT 许可及其版权声明：

- **Galio1991** — pull requests #1 and #2 (guarded edit restoration, review and edit-reuse workflow).

```
MIT License

Copyright (c) 2026 Galio1991

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation
files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy,
modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software
is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES
OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

Contributions submitted from 2026-11-03 on are licensed under the AGPL-3.0, as stated in `CONTRIBUTING.md`.
自 2026-11-03 起提交的贡献按 AGPL-3.0 授权，见 `CONTRIBUTING.md`。

## Adobe

This project is **not affiliated with, endorsed by, or sponsored by Adobe**. "Adobe" and "Lightroom" are trademarks
of Adobe Inc. They are used here only to say which software this tool works with. The Adobe Lightroom Classic SDK
(documentation, samples, Lua compiler) is **not** part of this repository and must not be committed; get it from
Adobe's developer site and follow its terms. All code here was written from the SDK's API documentation; no Adobe sample
code is included.
