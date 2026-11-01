# Third-party notices

This project's own code is MIT-licensed (see `LICENSE`). It depends on the packages below. The list was read from
each package's installed metadata (version tested: the ones shown); check the packages' own license files for the
authoritative text. A binary release (`lrmcp.exe`, built with PyInstaller) bundles these packages and Python itself,
so their licenses apply to that bundle.

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

**Build tools (not shipped in the source tree).** PyInstaller (6.22.3) is licensed "GPLv2-or-later with a special
exception which allows to use PyInstaller to build and distribute non-free programs", per its package metadata.
Inno Setup is used to build the installer.

## Adobe

This project is **not affiliated with, endorsed by, or sponsored by Adobe**. "Adobe" and "Lightroom" are trademarks
of Adobe Inc. They are used here only to say which software this tool works with. The Adobe Lightroom Classic SDK
(documentation, samples, Lua compiler) is **not** part of this repository and must not be committed; get it from
Adobe's developer site and follow its terms. All code here was written from the SDK's API documentation; no Adobe sample
code is included.
