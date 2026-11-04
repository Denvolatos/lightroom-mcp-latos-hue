; SPDX-License-Identifier: AGPL-3.0-only
; Copyright (C) 2026 Denvolatos and contributors
; Inno Setup script for Lightroom MCP (LrMCP). Build with build.ps1 (it passes /DAppVer=x.y.z).
; Per-user install, no administrator rights needed. Run it as a normal user, NOT from a program that Claude
; Desktop started: Claude Desktop is an MSIX app and redirects AppData writes of its child processes.
#ifndef AppVer
  #define AppVer "0.0.0"
#endif
#ifndef DistDir
  #define DistDir "..\build\release_dist"
#endif

[Setup]
AppId={{7B8E2C41-5A0D-4E3B-9F6A-1D2C3E4F5A6B}
AppName=Lightroom MCP (LrMCP)
AppVersion={#AppVer}
AppPublisher=Denvolatos
DefaultDirName={localappdata}\Programs\LrMCP
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\build\installer
OutputBaseFilename=LrMCP-Setup-v{#AppVer}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayName=Lightroom MCP (LrMCP)
InfoAfterFile=after.txt
LicenseFile=..\LICENSE

[Files]
; the server (PyInstaller folder build, includes Python)
Source: "{#DistDir}\lrmcp\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; the Lightroom plug-in (staged by build.ps1 without the development helpers); {userappdata} = %APPDATA%
Source: "..\build\stage\LrMcp.lrplugin\*"; DestDir: "{userappdata}\Adobe\Lightroom\Modules\LrMcp.lrplugin"; Flags: recursesubdirs createallsubdirs ignoreversion

[Run]
Filename: "{app}\lrmcp.exe"; Parameters: "register"; Description: "Register with Claude Code / Codex (recommended)"; Flags: postinstall runhidden skipifsilent

[UninstallRun]
Filename: "{app}\lrmcp.exe"; Parameters: "unregister"; Flags: runhidden; RunOnceId: "LrMcpUnregister"
