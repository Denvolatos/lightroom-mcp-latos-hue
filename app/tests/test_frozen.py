# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""免 Python 打包：辅助进程命令、资源路径、统一入口分发、配置里不再出现 python 脚本（冻结时）。"""
import sys
from pathlib import Path

import pytest

import claude_bridge
import frozen
import run_latoshue
from providers import codex_provider


def freeze(monkeypatch, exe: Path, meipass: Path | None = None):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    if meipass is not None:
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)


def test_helper_command_dev_uses_python_and_script():
    for name, (script, _flag) in frozen.HELPERS.items():
        cmd = frozen.helper_command(name)
        assert cmd == [sys.executable, str(frozen.APP_DIR / script)]
        assert Path(cmd[1]).is_file()


def test_helper_command_frozen_uses_helper_exe_and_flag(monkeypatch, tmp_path):
    freeze(monkeypatch, tmp_path / "LatosHue.exe")
    assert frozen.helper_command("lr-launcher") == [str((tmp_path / "latoshue-helper.exe").resolve()), "--lr-launcher"]
    assert frozen.helper_command("permission-server")[1] == "--permission-server"
    assert frozen.helper_command("codex-proxy")[1] == "--codex-proxy"
    assert not any(part.endswith(".py") for name in frozen.HELPERS for part in frozen.helper_command(name))


def test_helper_command_unknown_name():
    with pytest.raises(KeyError):
        frozen.helper_command("nope")


def test_every_helper_flag_is_dispatched():
    for _script, flag in frozen.HELPERS.values():
        assert flag in run_latoshue.COMMANDS


def test_resource_paths(monkeypatch, tmp_path):
    assert frozen.web_dir() == frozen.APP_DIR / "web" and (frozen.web_dir() / "index.html").is_file()
    freeze(monkeypatch, tmp_path / "LatosHue.exe", tmp_path / "_internal")
    assert frozen.app_root() == tmp_path / "_internal"
    assert frozen.web_dir() == tmp_path / "_internal" / "web"


def test_resource_path_without_meipass_falls_back_to_exe_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "LatosHue.exe"))
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert frozen.app_root() == tmp_path


def test_lightroom_server_config_frozen_has_no_python(monkeypatch, tmp_path):
    freeze(monkeypatch, tmp_path / "LatosHue.exe")
    cfg = claude_bridge.lightroom_server_config(tmp_path / "state.json")
    assert cfg["command"].endswith("latoshue-helper.exe") and cfg["args"] == ["--lr-launcher"]
    assert cfg["env"] == {"LRAPP_BRIDGE_STATE": str(tmp_path / "state.json"), "LRMCP_APP_MODE": "1"}


def test_lightroom_server_config_dev_unchanged():
    cfg = claude_bridge.lightroom_server_config(Path("s.json"))
    assert cfg["command"] == sys.executable and cfg["args"][0].endswith("lr_launcher.py")
    assert "PYTHONPATH" in cfg["env"] and cfg["env"]["LRAPP_BRIDGE_STATE"] == "s.json"


def test_permission_server_config_frozen(monkeypatch, tmp_path):
    freeze(monkeypatch, tmp_path / "LatosHue.exe")
    cfg = claude_bridge.permission_server_config()
    assert cfg["command"].endswith("latoshue-helper.exe") and cfg["args"] == ["--permission-server"]
    assert cfg["env"] == {"LRAPP_PORT": "${LRAPP_PORT}", "LRAPP_TOKEN": "${LRAPP_TOKEN}"}


def test_codex_command_frozen_points_at_helper(monkeypatch, tmp_path):
    freeze(monkeypatch, tmp_path / "LatosHue.exe")
    cmd = codex_provider.build_command("codex", None, tmp_path, "hi")
    joined = "\n".join(cmd)
    assert "latoshue-helper.exe" in joined and '["--codex-proxy"]' in joined
    assert "codex_proxy.py" not in joined and "python" not in joined.lower()


def test_codex_command_dev_uses_script():
    joined = "\n".join(codex_provider.build_command("codex", None, Path("."), "hi"))
    assert "codex_proxy.py" in joined


def test_dispatch_no_args_starts_gui():
    calls = []
    assert run_latoshue.run([], commands={}, gui=lambda: calls.append("gui") or 0) == 0
    assert calls == ["gui"]


def test_dispatch_subcommands():
    seen = []
    table = {f: (lambda f=f: seen.append(f) or 0) for f in run_latoshue.COMMANDS}
    for flag in run_latoshue.COMMANDS:
        assert run_latoshue.run([flag], commands=table) == 0
    assert seen == list(run_latoshue.COMMANDS)


def test_dispatch_unknown_or_extra_args_rejected():
    called = []
    table = {"--selftest": lambda: called.append(1) or 0}
    assert run_latoshue.run(["--bogus"], commands=table, gui=lambda: called.append("gui")) == 2
    assert run_latoshue.run(["--selftest", "x"], commands=table) == 2
    assert called == []


def test_selftest_passes_in_dev(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out.txt"
    monkeypatch.setenv("LATOSHUE_SELFTEST_OUT", str(out))
    assert frozen.run_selftest() == 0
    assert "SELFTEST PASS" in out.read_text(encoding="utf-8")
    assert "SELFTEST PASS" in capsys.readouterr().out


def test_selftest_reports_missing_resource(tmp_path, monkeypatch):
    monkeypatch.setattr(frozen, "web_dir", lambda: tmp_path)
    ok, lines = frozen.selftest()
    assert not ok and any(l.startswith("FAIL 资源文件") for l in lines)


def test_selftest_without_stdout(tmp_path, monkeypatch):
    monkeypatch.setenv("LATOSHUE_SELFTEST_OUT", str(tmp_path / "o.txt"))
    monkeypatch.setattr(sys, "stdout", None)
    assert frozen.run_selftest() == 0 and (tmp_path / "o.txt").is_file()
