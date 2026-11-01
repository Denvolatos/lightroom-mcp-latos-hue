# Development helpers for running Lua test scripts inside Lightroom through the dev bridge.
# Usage:  . .\server\dev_tools.ps1 ; Invoke-DevScript select_test_photo.lua
#
# Safety: the dev bridge and a normal lrmcp server (for example the one a Claude Code session started) cannot both use
# port 58770. This refuses to run while another program holds the port, and it only deletes the token / dev_enabled
# files if THIS function started the dev bridge (an earlier version of this helper deleted a live server's token file).

function Get-PortOwner {
    $c = Get-NetTCPConnection -LocalPort 58770 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $c) { return $null }
    return Get-CimInstance Win32_Process -Filter "ProcessId=$($c.OwningProcess)"
}

function Invoke-DevScript {
    param([Parameter(Mandatory)][string]$Script, [int]$Timeout = 120)
    $repo = Split-Path $PSScriptRoot -Parent
    $owner = Get-PortOwner
    if ($owner) {
        throw "Port 58770 is in use by $($owner.Name) (PID $($owner.ProcessId)): $($owner.CommandLine). Close that session first; nothing was changed."
    }
    $dev = Start-Process -FilePath python -ArgumentList "-I", "$repo\server\dev_bridge.py" -WindowStyle Hidden -PassThru
    try {
        Start-Sleep -Seconds 2
        $mine = Get-PortOwner
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
        # we own these files only because we started the dev bridge above
        Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object { $_.CommandLine -match "dev_bridge" } |
            ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        Start-Sleep -Seconds 1
        Remove-Item "$env:USERPROFILE\LrMcp\dev_enabled", "$env:USERPROFILE\LrMcp\token" -ErrorAction SilentlyContinue
    }
}
