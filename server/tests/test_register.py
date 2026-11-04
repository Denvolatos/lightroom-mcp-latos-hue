# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
from lightroom_mcp import register


def test_dry_run_runs_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(register.subprocess, "run", lambda *a, **k: calls.append(a))
    monkeypatch.setattr(register.shutil, "which", lambda name: f"C:\\tools\\{name}.exe")
    lines = register.register(dry_run=True)
    assert calls == []
    assert any("Claude Code" in l and "演练" in l for l in lines)
    assert any("Codex" in l and "演练" in l for l in lines)


def test_commands_use_snake_case_name_and_stdio(monkeypatch):
    seen = []

    class Done:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(register.subprocess, "run", lambda args, **k: seen.append(args) or Done())
    monkeypatch.setattr(register.shutil, "which", lambda name: f"C:\\tools\\{name}.exe")
    register.register()
    add_claude = next(a for a in seen if a[1:3] == ["mcp", "add"] and a[0].endswith("claude.exe"))
    assert "lightroom_mcp" in add_claude and "stdio" in add_claude and "--scope" in add_claude and "--" in add_claude
    add_codex = next(a for a in seen if a[1:3] == ["mcp", "add"] and a[0].endswith("codex.exe"))
    assert add_codex[3] == "lightroom_mcp" and "--" in add_codex


def test_missing_clients_are_skipped(monkeypatch):
    monkeypatch.setattr(register.shutil, "which", lambda name: None)
    lines = register.register(dry_run=False)
    assert sum("已跳过" in l for l in lines) == 2


def test_failure_is_reported(monkeypatch):
    class Bad:
        returncode = 1
        stdout = ""
        stderr = "boom"

    monkeypatch.setattr(register.subprocess, "run", lambda *a, **k: Bad())
    monkeypatch.setattr(register.shutil, "which", lambda name: f"C:\\tools\\{name}.exe")
    assert any(l.startswith("❌") for l in register.register())
