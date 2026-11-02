# Build the release: tests -> lrmcp.exe (PyInstaller) -> staged plug-in -> installer (Inno Setup).
# Usage (Windows PowerShell, from the repository root):  powershell -ExecutionPolicy Bypass -File build.ps1
# Needs the conda environment "lrmcp" (mcp, pillow, pytest, pyinstaller) and Inno Setup 6.
param([switch]$SkipTests)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$py = Join-Path $env:USERPROFILE "miniconda3\envs\lrmcp\python.exe"
$iscc = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
foreach ($p in @($py, $iscc)) { if (-not (Test-Path $p)) { throw "missing: $p" } }

# version: single source is server\lightroom_mcp\__init__.py
$init = Get-Content (Join-Path $repo "server\lightroom_mcp\__init__.py") -Raw
if ($init -notmatch '__version__\s*=\s*"([^"]+)"') { throw "cannot read version" }
$version = $Matches[1]
Write-Host "== LrMCP $version =="

# the plug-in's own version must match (Version.lua and Info.lua)
$pluginVersion = (Get-Content (Join-Path $repo "plugin\lrmcp.lrdevplugin\Version.lua") -Raw) -replace '(?s).*return\s+"([^"]+)".*', '$1'
if ($pluginVersion -ne $version) { Write-Warning "plug-in version $pluginVersion differs from server version $version" }

if (-not $SkipTests) {
    Write-Host "-- unit tests"
    Push-Location (Join-Path $repo "server")
    & $py -m pytest -q
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "tests failed" }
    Pop-Location
}

# The release is built in its own folder: build\dist may be the lrmcp.exe that an AI client has registered and is running
# right now, and Windows will not let PyInstaller delete its files.
$distRoot = Join-Path $repo "build\release_dist"

Write-Host "-- lrmcp.exe"
Push-Location (Join-Path $repo "server")
& $py -m PyInstaller --noconfirm --clean --onedir --name lrmcp --paths "$repo\server" `
    --collect-submodules lightroom_mcp --exclude-module mcp.cli `
    --distpath "$distRoot" --workpath "$repo\build\work" --specpath "$repo\build" "$repo\server\run_lrmcp.py"
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "PyInstaller failed" }
Pop-Location

Write-Host "-- stage plug-in (without development helpers)"
$stage = Join-Path $repo "build\stage\LrMcp.lrplugin"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force $stage | Out-Null
$devOnly = @("DevRun.lua", "devscripts")
Get-ChildItem (Join-Path $repo "plugin\lrmcp.lrdevplugin") | Where-Object { $devOnly -notcontains $_.Name } |
    Copy-Item -Destination $stage -Recurse

Write-Host "-- installer"
& $iscc "/DAppVer=$version" "/DDistDir=$distRoot" (Join-Path $repo "installer\lrmcp.iss")
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

$out = Get-ChildItem (Join-Path $repo "build\installer") -Filter "LrMCP-Setup-*.exe" | Sort-Object LastWriteTime | Select-Object -Last 1
Write-Host ("done: {0} ({1} MB)" -f $out.FullName, [math]::Round($out.Length / 1MB, 1))
