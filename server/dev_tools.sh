#!/usr/bin/env bash
# Development helper (macOS/Linux): run a Lua dev script inside Lightroom through the dev bridge.
# Usage:  bash server/dev_tools.sh select_raw.lua [timeout_seconds]   (python must be the one with lightroom_mcp installed)
# The bash twin of dev_tools.ps1. Same safety rules: the dev bridge picks its own free port, this refuses to start a second
# one, and it only removes its own dev_enabled / dev_server.txt / servers/<port>.txt files.

invoke_dev_script() {
    local script="$1" timeout="${2:-120}"
    local repo; repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    local dir="$HOME/LrMcp"
    if [ -f "$dir/dev_enabled" ]; then
        echo "A dev bridge seems to be running already (dev_enabled exists). Stop it first; nothing was changed." >&2
        return 1
    fi
    python -I "$repo/server/dev_bridge.py" >/dev/null 2>&1 &
    local pid=$!
    local result="" i
    sleep 2
    if ! kill -0 "$pid" 2>/dev/null; then echo "the dev bridge did not start" >&2; return 1; fi
    for i in 1 2 3 4 5 6 7 8 9 10 11 12; do
        result="$(python -I "$repo/server/dev_run.py" "$script" "$timeout" 2>&1)"
        case "$result" in *"NOT POLLING"*|*"cannot reach"*) sleep 3 ;; *) break ;; esac
    done
    local port=""
    [ -f "$dir/dev_server.txt" ] && port="$(sed -n 's/^port=//p' "$dir/dev_server.txt")"
    kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
    sleep 1
    rm -f "$dir/dev_enabled" "$dir/dev_server.txt"
    [ -n "$port" ] && rm -f "$dir/servers/$port.txt"
    echo "$result"
}

invoke_dev_script "$@"
