# Build Latos Hue (the desktop app) as a Python-free program folder: build\app_dist\LatosHue\
# Usage (Windows PowerShell, from the repository root):  powershell -ExecutionPolicy Bypass -File build_app.ps1
# Needs the conda environment "lrmcp" (pywebview, mcp, pillow, pytest, pyinstaller). No installer yet (next step).
param([switch]$SkipTests)

$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$py = Join-Path $env:USERPROFILE "miniconda3\envs\lrmcp\python.exe"
if (-not (Test-Path $py)) { throw "missing: $py" }

$settings = Get-Content (Join-Path $repo "app\settings.py") -Raw
if ($settings -notmatch 'APP_VERSION\s*=\s*"([^"]+)"') { throw "cannot read app version" }
Write-Host "== Latos Hue $($Matches[1]) =="

if (-not $SkipTests) {
    Write-Host "-- unit tests (app)"
    & $py -m pytest -q (Join-Path $repo "app\tests")
    if ($LASTEXITCODE -ne 0) { throw "tests failed" }
}

# Its own folder: build\dist and build\release_dist hold lrmcp.exe, which an AI client may be running right now.
$distRoot = Join-Path $repo "build\app_dist"
$work = Join-Path $repo "build\app_work"
Write-Host "-- LatosHue.exe + latoshue-helper.exe"
& $py -m PyInstaller --noconfirm --clean --distpath "$distRoot" --workpath "$work" (Join-Path $repo "app\latoshue.spec")
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$out = Join-Path $distRoot "LatosHue"
foreach ($f in @("LatosHue.exe", "latoshue-helper.exe")) {
    if (-not (Test-Path (Join-Path $out $f))) { throw "missing in output: $f" }
}

Write-Host "-- self test (no window)"
$result = Join-Path $env:TEMP "latoshue_selftest_build.txt"
Remove-Item $result -ErrorAction SilentlyContinue
$env:LATOSHUE_SELFTEST_OUT = $result
$p = Start-Process -FilePath (Join-Path $out "LatosHue.exe") -ArgumentList "--selftest" -Wait -PassThru
Remove-Item Env:\LATOSHUE_SELFTEST_OUT
if (Test-Path $result) { Get-Content $result -Encoding UTF8 }
if ($p.ExitCode -ne 0) { throw "self test failed (exit $($p.ExitCode))" }

$mb = [math]::Round((Get-ChildItem $out -Recurse -File | Measure-Object Length -Sum).Sum / 1MB, 1)
Write-Host ("done: {0} ({1} MB)" -f $out, $mb)
