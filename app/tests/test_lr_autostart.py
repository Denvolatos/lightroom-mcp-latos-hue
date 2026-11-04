# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""自动启动 Lightroom：路径校验与探测、是否已在运行、STARTUPINFO 参数、启动流程的各种结果、设置校验、Api 不接受页面传来的路径。
全部使用假对象：不会真的启动 Lightroom，也不会弹出任何窗口。"""
import os
import subprocess
import types

import pytest

import lr_autostart as la
import settings as st


def make_exe(folder, name="Lightroom.exe"):
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_bytes(b"MZ")
    return str(p)


# ---------------------------------------------------------------- 路径校验
def test_valid_path_accepts_real_lightroom_exe(tmp_path):
    exe = make_exe(tmp_path / "Adobe Lightroom Classic")
    assert la.valid_lightroom_path(exe) == exe
    assert la.valid_lightroom_path('  "' + exe + '"  ') == exe
    assert la.valid_lightroom_path(exe.replace("Lightroom.exe", "LIGHTROOM.EXE")) is not None      # 文件名大小写不敏感


@pytest.mark.parametrize("bad", [None, 5, "", "   ", "Lightroom.exe", "\\\\server\\share\\Lightroom.exe", "//server/share/Lightroom.exe",
                                 "C:Lightroom.exe", "bad\x00C:\\Lightroom.exe"])
def test_valid_path_rejects_garbage(bad):
    assert la.valid_lightroom_path(bad) is None


def test_valid_path_rejects_wrong_name_missing_and_folder(tmp_path):
    other = make_exe(tmp_path / "x", "notepad.exe")
    assert la.valid_lightroom_path(other) is None
    assert la.valid_lightroom_path(str(tmp_path / "nope" / "Lightroom.exe")) is None
    (tmp_path / "dir" / "Lightroom.exe").mkdir(parents=True)          # 同名但是文件夹
    assert la.valid_lightroom_path(str(tmp_path / "dir" / "Lightroom.exe")) is None
    assert la.valid_lightroom_path(make_exe(tmp_path / "y", "Lightroom.exe.bat")) is None


def test_valid_path_rejects_command_line_style_input(tmp_path):
    exe = make_exe(tmp_path / "L")
    assert la.valid_lightroom_path(exe + " --evil") is None
    assert la.valid_lightroom_path(exe + " & calc.exe") is None


# ---------------------------------------------------------------- 探测
def test_find_prefers_custom_then_registry_then_program_files(tmp_path):
    custom = make_exe(tmp_path / "custom")
    reg = make_exe(tmp_path / "reg")
    pf = tmp_path / "PF"
    pfexe = make_exe(pf / "Adobe" / "Adobe Lightroom Classic")
    env = {"ProgramFiles": str(pf)}
    assert la.find_lightroom(custom, env, lambda: reg) == custom
    assert la.find_lightroom("", env, lambda: reg) == reg
    assert la.find_lightroom("", env, lambda: None) == pfexe
    assert la.find_lightroom(str(tmp_path / "gone" / "Lightroom.exe"), env, lambda: None) == pfexe   # 自选路径失效时回退探测


def test_find_returns_none_and_survives_registry_errors(tmp_path):
    def boom():
        raise OSError("registry")
    assert la.find_lightroom("", {"ProgramFiles": str(tmp_path / "empty")}, boom) is None
    assert la.find_lightroom("", {}, lambda: "C:\\not\\there\\Lightroom.exe") is None


def test_find_rejects_registry_value_with_wrong_file(tmp_path):
    notepad = make_exe(tmp_path / "n", "notepad.exe")
    assert la.find_lightroom("", {}, lambda: notepad) is None


# ---------------------------------------------------------------- 是否在运行
def fake_run(stdout="", exc=None, calls=None):
    def run(cmd, **kw):
        if calls is not None:
            calls.append((cmd, kw))
        if exc:
            raise exc
        return types.SimpleNamespace(stdout=stdout, returncode=0)
    return run


def test_is_running_true_false_and_hidden_window():
    calls = []
    row = '"Lightroom.exe","1234","Console","1","900,000 K"\n'
    assert la.is_running(fake_run(row, calls=calls)) is True
    assert la.is_running(fake_run("INFO: No tasks are running which match the specified criteria.\n")) is False
    cmd, kw = calls[0]
    assert cmd[0] == "tasklist" and "IMAGENAME eq Lightroom.exe" in cmd
    assert kw["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)          # 不弹窗
    assert kw["timeout"] > 0


@pytest.mark.parametrize("exc", [OSError("x"), subprocess.TimeoutExpired("tasklist", 15), subprocess.SubprocessError("y")])
def test_is_running_failure_means_not_running(exc):
    assert la.is_running(fake_run(exc=exc)) is False


# ---------------------------------------------------------------- 启动参数
class FakeStartupInfo:
    def __init__(self):
        self.dwFlags = 0
        self.wShowWindow = 1


def test_build_startupinfo_minimized_no_activate():
    si = la.build_startupinfo(FakeStartupInfo)
    assert si.wShowWindow == 7 == la.SW_SHOWMINNOACTIVE
    assert si.dwFlags & getattr(subprocess, "STARTF_USESHOWWINDOW", 1)


def test_launch_minimized_arguments(tmp_path, monkeypatch):
    exe = make_exe(tmp_path / "L")
    monkeypatch.setattr(subprocess, "STARTUPINFO", FakeStartupInfo, raising=False)
    seen = {}

    def popen(args, **kw):
        seen["args"], seen["kw"] = args, kw
    assert la.launch_minimized(exe, popen) is True
    assert seen["args"] == [exe]                                         # 只有 exe 本身，没有任何命令行参数
    kw = seen["kw"]
    assert kw["startupinfo"].wShowWindow == 7
    assert kw["creationflags"] == getattr(subprocess, "CREATE_NO_WINDOW", 0)
    assert "shell" not in kw or kw["shell"] is False


def test_launch_refuses_illegal_paths_and_never_calls_popen(tmp_path):
    def popen(*a, **k):
        raise AssertionError("不应启动")
    other = make_exe(tmp_path / "o", "calc.exe")
    for bad in (other, "", None, "C:\\x\\Lightroom.exe", make_exe(tmp_path / "ok") + " /s"):
        assert la.launch_minimized(bad, popen) is False


def test_launch_failure_is_reported_not_raised(tmp_path):
    exe = make_exe(tmp_path / "L")

    def popen(*a, **k):
        raise OSError("blocked")
    assert la.launch_minimized(exe, popen) is False


# ---------------------------------------------------------------- 启动流程
class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def flow(settings, *, running=False, exe="C:\\LR\\Lightroom.exe", launched=True, connect_after=None, timeout=120.0):
    clock = Clock()
    events, calls = [], {"launch": [], "find": []}

    def find(custom):
        calls["find"].append(custom)
        return exe

    def launch(path):
        calls["launch"].append(path)
        return launched
    al = la.AutoLaunch(lambda: settings, lambda: connect_after is not None and clock.t >= connect_after, events.append,
                       running_fn=lambda: running, find_fn=find, launch_fn=launch, sleep=clock.sleep, clock=clock,
                       timeout=timeout)
    return al, events, calls


def states(events):
    return [e["state"] for e in events]


def test_off_does_nothing():
    al, ev, calls = flow({"auto_launch_lightroom": False})
    assert al.start() is False and al.run() == la.IDLE
    assert calls["launch"] == [] and ev == []
    al2, _, _ = flow({})                                                 # 字段缺失按关闭处理
    assert al2.start() is False


@pytest.mark.parametrize("val", [1, "true", None])
def test_only_real_true_turns_it_on(val):
    al, ev, calls = flow({"auto_launch_lightroom": val})
    assert al.run() == la.IDLE and calls["launch"] == []


def test_already_running_does_not_launch():
    al, ev, calls = flow({"auto_launch_lightroom": True}, running=True, connect_after=4)
    assert al.run() == la.CONNECTED
    assert calls["launch"] == [] and calls["find"] == []
    assert states(ev) == [la.ALREADY, la.CONNECTED]


def test_launches_then_connects():
    al, ev, calls = flow({"auto_launch_lightroom": True, "lightroom_path": "C:\\mine\\Lightroom.exe"}, connect_after=20)
    assert al.run() == la.CONNECTED
    assert calls["find"] == ["C:\\mine\\Lightroom.exe"] and calls["launch"] == ["C:\\LR\\Lightroom.exe"]
    assert states(ev) == [la.STARTING, la.CONNECTED]
    assert al.state()["state"] == la.CONNECTED and ev[0]["type"] == "lr_launch" and ev[0]["message"]


def test_not_found_is_friendly():
    al, ev, calls = flow({"auto_launch_lightroom": True}, exe=None)
    assert al.run() == la.NOT_FOUND and calls["launch"] == []
    assert "手动" in ev[-1]["message"]


def test_launch_failure():
    al, ev, _ = flow({"auto_launch_lightroom": True}, launched=False)
    assert al.run() == la.FAILED and states(ev) == [la.STARTING, la.FAILED]


def test_timeout_after_limit():
    al, ev, _ = flow({"auto_launch_lightroom": True}, connect_after=None, timeout=120.0)
    assert al.run() == la.TIMEOUT and states(ev)[-1] == la.TIMEOUT


def test_exceptions_never_escape():
    def boom(*a):
        raise RuntimeError("x")
    al = la.AutoLaunch(lambda: {"auto_launch_lightroom": True}, lambda: False, lambda e: None, running_fn=boom)
    assert al.run() == la.FAILED
    al2 = la.AutoLaunch(lambda: {"auto_launch_lightroom": True}, lambda: True, boom, running_fn=lambda: True)
    assert al2.run() == la.CONNECTED                                     # 推送出错不影响流程


def test_stop_ends_waiting_without_touching_lightroom():
    clock = Clock()
    holder = {}

    def sleep(s):
        clock.sleep(s)
        holder["al"].stop()
    al = la.AutoLaunch(lambda: {"auto_launch_lightroom": True}, lambda: False, lambda e: None, running_fn=lambda: True,
                       sleep=sleep, clock=clock)
    holder["al"] = al
    al.run()
    assert al.state()["state"] == la.ALREADY                             # 停止后不再判超时，也没有任何"关闭"动作


def test_start_runs_in_background_thread_once():
    al, ev, calls = flow({"auto_launch_lightroom": True}, connect_after=0)
    assert al.start() is True
    al._thread.join(5)
    assert al.state()["state"] == la.CONNECTED
    assert al.start() is False                                           # 只跑一次


# ---------------------------------------------------------------- 设置校验
def test_defaults_off_and_empty_path():
    d = st.defaults()
    assert d["auto_launch_lightroom"] is False and d["lightroom_path"] == ""


def test_sanitize_fixes_bad_values(tmp_path):
    bad = st.sanitize({"auto_launch_lightroom": "yes", "lightroom_path": 5})
    assert bad["auto_launch_lightroom"] is False and bad["lightroom_path"] == ""
    assert st.sanitize({"lightroom_path": "C:\\nowhere\\Lightroom.exe"})["lightroom_path"] == ""
    exe = make_exe(tmp_path / "L")
    good = st.sanitize({"lightroom_path": exe, "auto_launch_lightroom": True})
    assert good["lightroom_path"] == exe and good["auto_launch_lightroom"] is True


@pytest.fixture
def store(tmp_path):
    return st.SettingsStore(tmp_path / "s.json", restrict=lambda p: None)


def test_update_accepts_switch_and_path(store, tmp_path):
    exe = make_exe(tmp_path / "L")
    r = store.update({"auto_launch_lightroom": True, "lightroom_path": exe})
    assert r["ok"] and r["settings"]["auto_launch_lightroom"] is True and r["settings"]["lightroom_path"] == exe
    r = store.update({"lightroom_path": ""})
    assert r["ok"] and r["settings"]["lightroom_path"] == ""


@pytest.mark.parametrize("bad", ["C:\\Windows\\System32\\cmd.exe", "C:\\x\\Lightroom.exe", 7, None, "\\\\h\\s\\Lightroom.exe"])
def test_update_rejects_bad_path_and_saves_nothing(store, bad):
    r = store.update({"lightroom_path": bad, "auto_launch_lightroom": True})
    assert not r["ok"] and "lightroom_path" in r["errors"]
    assert store.data["auto_launch_lightroom"] is False                 # 整体不保存


@pytest.mark.parametrize("bad", ["true", 1, None])
def test_update_rejects_non_bool_switch(store, bad):
    r = store.update({"auto_launch_lightroom": bad})
    assert not r["ok"] and "auto_launch_lightroom" in r["errors"]


# ---------------------------------------------------------------- Api：页面不能传任意路径
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "app_settings.json")
    monkeypatch.setattr(st.SettingsStore.__init__, "__defaults__", (None, lambda p: None))
    import main
    a = main.Api()
    yield a
    a._shutdown()


def test_api_ignores_path_sent_by_page(api, tmp_path):
    evil = make_exe(tmp_path / "evil")                                   # 即使是合法的 Lightroom.exe，页面直接传也不接受
    r = api.save_settings({"lightroom_path": evil, "auto_launch_lightroom": True})
    assert r["ok"] and r["settings"]["lightroom_path"] == "" and r["settings"]["auto_launch_lightroom"] is True
    r = api.save_settings({"lightroom_path_choice": "pending"})          # 没有点选过 -> 不生效
    assert r["ok"] and r["settings"]["lightroom_path"] == ""


class FakeWindow:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def create_file_dialog(self, kind, **kw):
        self.calls.append((kind, kw))
        return self.result


def test_api_choose_path_file_filter_is_valid_for_pywebview(api, tmp_path):
    """真机教训：文件类型字符串格式不对时 pywebview 会抛错，被吞掉后表现为“点了没反应”。"""
    from webview.util import parse_file_type
    win = FakeWindow((make_exe(tmp_path / "L"),))
    api._window = win
    api.choose_lightroom_path()
    for ft in win.calls[0][1]["file_types"]:
        parse_file_type(ft)


def test_api_choose_path_then_save_and_clear(api, tmp_path):
    exe = make_exe(tmp_path / "L")
    api._window = FakeWindow((exe,))
    r = api.choose_lightroom_path()
    assert r["ok"] and r["path"] == exe
    assert api.get_settings(False)["settings"]["lightroom_path"] == ""   # 只是暂存，没保存；重新读取设置会丢弃暂存
    api.choose_lightroom_path()
    assert api.save_settings({"lightroom_path_choice": "pending"})["settings"]["lightroom_path"] == exe
    assert api.save_settings({"lightroom_path_choice": "clear"})["settings"]["lightroom_path"] == ""


def test_api_choose_path_rejects_wrong_file_and_cancel(api, tmp_path):
    api._window = FakeWindow((make_exe(tmp_path / "o", "notepad.exe"),))
    r = api.choose_lightroom_path()
    assert not r["ok"] and r["message"]
    assert api.save_settings({"lightroom_path_choice": "pending"})["settings"]["lightroom_path"] == ""
    api._window = FakeWindow(None)
    assert api.choose_lightroom_path().get("cancelled") is True
    api._window = None
    assert api.choose_lightroom_path()["ok"] is False


def test_api_autolaunch_state_and_no_exposed_paths(api):
    assert api.autolaunch_state()["state"] == la.IDLE
    import inspect
    for name in ("choose_lightroom_path", "autolaunch_state"):
        assert not [p for p in inspect.signature(getattr(api, name)).parameters]   # 这两个接口都不收任何参数


# ---- 启动宽限期（0.13.1）：刚自动启动 Lightroom 的前 90 秒，软件不换端口重建通道 ----
def grace_flow(settings, *, running=False, grace=90.0):
    al, ev, calls = flow(settings, running=running, connect_after=None)
    al.grace = grace
    return al, ev, calls


def test_grace_constant_is_90_and_shorter_than_timeout():
    assert la.GRACE_SECONDS == 90.0 and la.GRACE_SECONDS < la.CONNECT_TIMEOUT


def test_in_grace_false_before_run_and_when_disabled():
    al, ev, _ = grace_flow({"auto_launch_lightroom": False})
    assert al.in_grace() is False
    al.run()
    assert al.in_grace() is False


def test_in_grace_during_starting_then_expires():
    clock = Clock()
    al = la.AutoLaunch(lambda: {"auto_launch_lightroom": True}, lambda: False, lambda e: None,
                       running_fn=lambda: False, find_fn=lambda c: r"C:\LR\Lightroom.exe", launch_fn=lambda p: True,
                       sleep=lambda s: None, clock=clock)
    seen = []

    def sleep(s):
        seen.append((clock.t, al.in_grace()))
        clock.t += s
    al._sleep = sleep
    assert al.run() == la.TIMEOUT
    inside = [g for t, g in seen if t < 90.0]
    outside = [g for t, g in seen if t >= 90.0]
    assert inside and all(inside) and outside and not any(outside)
    assert al.in_grace() is False                         # 超时之后不再是宽限期


def test_in_grace_when_already_running_and_ends_on_connect():
    clock = Clock()
    box = {"c": False}
    al = la.AutoLaunch(lambda: {"auto_launch_lightroom": True}, lambda: box["c"], lambda e: None,
                       running_fn=lambda: True, find_fn=lambda c: None, launch_fn=lambda p: True,
                       sleep=lambda s: None, clock=clock)
    seen = []

    def sleep(s):
        seen.append(al.in_grace())
        clock.t += s
        if clock.t >= 10:
            box["c"] = True
    al._sleep = sleep
    assert al.run() == la.CONNECTED
    assert seen and all(seen) and al.in_grace() is False   # 已连上：宽限期结束


def test_no_grace_when_not_found_or_failed():
    al, _, _ = flow({"auto_launch_lightroom": True}, exe=None)
    al.run()
    assert al.in_grace() is False
    al, _, _ = flow({"auto_launch_lightroom": True}, launched=False)
    al.run()
    assert al.in_grace() is False


def test_timeout_message_is_specific():
    m = la.MESSAGES[la.TIMEOUT]
    assert "增效工具管理器" in m and "LrMCP" in m and "重新载入增效工具" in m and "插件还没连上" in m
    al, ev, _ = flow({"auto_launch_lightroom": True}, connect_after=None)
    al.run()
    assert ev[-1]["state"] == la.TIMEOUT and ev[-1]["message"] == m
    assert la.CONNECT_TIMEOUT == 120.0


def test_clean_environment_drops_own_dirs_and_packager_vars():
    own = r"C:\Apps\Latos Hue\_internal"
    env = {"Path": os.pathsep.join([own, r"C:\APPS\LATOS HUE", r"C:\Windows\System32", r"C:\Apps\Latos Hue Other"]),
           "_MEIPASS2": own, "_PYI_APPLICATION_HOME_DIR": own, "PYTHONHOME": "x", "PYTHONPATH": "y", "TEMP": "t"}
    out = la.clean_environment(env, own_dirs=[own, r"C:\Apps\Latos Hue"])
    assert out["Path"].split(os.pathsep) == [r"C:\Windows\System32", r"C:\Apps\Latos Hue Other"]   # 同名前缀的别的目录保留
    assert "_MEIPASS2" not in out and "_PYI_APPLICATION_HOME_DIR" not in out and "PYTHONHOME" not in out and "PYTHONPATH" not in out
    assert out["TEMP"] == "t" and env["Path"].startswith(own)                                          # 不改原字典


def test_launch_passes_a_clean_environment(tmp_path):
    exe = make_exe(tmp_path / "L")
    seen = {}

    def popen(args, **kw):
        seen.update(kw)
    assert la.launch_minimized(exe, popen) is True
    assert isinstance(seen["env"], dict) and "env" in seen
