# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
# Development helpers for running Lua test scripts inside Lightroom through the dev bridge.
# Usage:  . .\server\dev_tools.ps1 ; Invoke-DevScript select_test_photo.lua
#
# Safety: the dev bridge announces itself in ~/LrMcp/dev_server.txt and picks its own free port, so it can run next to
# real lrmcp servers. This refuses to start a second dev bridge, and it only deletes its own dev_enabled / dev_server.txt /
# servers\<port>.txt files (an earlier version deleted a live server's token file).

function Get-DevBridge {
    # the dev bridge announces itself in ~/LrMcp/dev_server.txt; a real lrmcp server on another port does not matter
    $f = "$env:USERPROFILE\LrMcp\dev_server.txt"
    if (-not (Test-Path $f)) { return $null }
    $port = ((Get-Content $f) | Where-Object { $_ -like "port=*" }) -replace "port=", ""
    $c = Get-NetTCPConnection -LocalPort ([int]$port) -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $c) { return $null }
    return Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)"
}

function Invoke-DevScript {
    param([Parameter(Mandatory)][string]$Script, [int]$Timeout = 120)
    $repo = Split-Path $PSScriptRoot -Parent
    $existing = Get-DevBridge
    if ($existing) {
        throw "A dev bridge is already running (PID $($existing.ProcessId)). Stop it first; nothing was changed."
    }
    $dev = Start-Process -FilePath python -ArgumentList "-I", "$repo\server\dev_bridge.py" -WindowStyle Hidden -PassThru
    try {
        Start-Sleep -Seconds 2
        $mine = Get-DevBridge
        if (-not $mine -or $mine.CommandLine -notmatch "dev_bridge") { throw "the dev bridge did not start" }
        $result = ""
        for ($i = 0; $i -lt 12; $i++) {
            $result = (python -I "$repo\server\dev_run.py" $Script $Timeout) -join "`n"
            if ($result -notmatch "NOT POLLING|cannot reach") { break }
            Start-Sleep -Seconds 3
        }
        return $result
    }
    finally {
        # we own these files only because we started the dev bridge above; a real server's files are not touched
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "dev_bridge" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        Start-Sleep -Seconds 1
        $port = $null
        if (Test-Path "$env:USERPROFILE\LrMcp\dev_server.txt") {
            $port = ((Get-Content "$env:USERPROFILE\LrMcp\dev_server.txt") | Where-Object { $_ -like "port=*" }) -replace "port=", ""
        }
        Remove-Item "$env:USERPROFILE\LrMcp\dev_enabled", "$env:USERPROFILE\LrMcp\dev_server.txt" -ErrorAction SilentlyContinue
        if ($port) { Remove-Item "$env:USERPROFILE\LrMcp\servers\$port.txt" -ErrorAction SilentlyContinue }
    }
}
