# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""环境检查向导（0.14.0）：四项检查的判定与文案、依赖关系、自动弹出条件、不阻塞、接口不暴露路径、旧设置文件兼容。
全部用假对象：不开窗口、不启动 Lightroom、不连真实 Lightroom/AI、不碰真实照片目录。"""
import inspect
import json
import threading

import pytest

import settings as st
import wizard as wz


def prov(available=True, state="ready", reason="已安装并已登录。", next_step="", name="Claude Code 命令行"):
    return {"name": name, "available": available, "state": state, "reason": reason, "next_step": next_step}


def make(folder_ok=True, base="D:\\照片", lr_found="C:\\x\\Lightroom.exe", running=True, conn=None, provider=None,
         auto="idle", done=False, spawn=None, lr_path=""):
    """返回 (checker, settings 字典)；conn=None 表示已连接。"""
    settings = {"base_folder": base, "lightroom_path": lr_path, "wizard_done": done}
    c = conn if conn is not None else {"state": "connected", "connected": True, "plugin_version": "0.15.0"}
    ck = wz.WizardChecker(lambda: settings, find_lightroom=lambda custom: lr_found, is_running=lambda: running,
                          get_connection=lambda: c, get_provider=lambda: provider or prov(),
                          get_autolaunch=lambda: {"state": auto}, isdir=lambda p: folder_ok, spawn=spawn)
    return ck, settings


def states(ck):
    return {i["id"]: i["state"] for i in ck.check()}


def item(ck, key):
    return next(i for i in ck.check() if i["id"] == key)


DOWN = {"state": "disconnected", "connected": False}


# ---------------------------------------------------------------- 1 照片工作文件夹
def test_all_ready():
    ck, _ = make()
    assert states(ck) == {"folder": "ready", "lightroom": "ready", "plugin": "ready", "ai": "ready"}
    assert "0.15.0" in item(ck, "plugin")["text"]


@pytest.mark.parametrize("base", ["", "   ", None, 5])
def test_folder_not_chosen(base):
    ck, _ = make(base=base)
    it = item(ck, "folder")
    assert it["state"] == "todo" and it["action"] == "choose_folder" and it["action_label"] == "选择文件夹"
    assert "还没有选择" in it["text"]


def test_folder_missing_on_disk():
    ck, _ = make(folder_ok=False)
    it = item(ck, "folder")
    assert it["state"] == "todo" and "找不到" in it["text"] and "D:\\照片" in it["text"] and it["action"] == "choose_folder"


# ---------------------------------------------------------------- 2 Lightroom
def test_lightroom_running_is_ready_even_if_not_found():
    ck, _ = make(lr_found=None)
    assert item(ck, "lightroom")["state"] == "ready"


def test_lightroom_found_but_not_running_tells_user_to_open_it():
    ck, _ = make(running=False, conn=DOWN)
    it = item(ck, "lightroom")
    assert it["state"] == "todo" and "还没有打开" in it["text"] and "请先打开 Lightroom" in it["hint"]
    assert "自动启动" in it["hint"] and it["action"] == ""        # 说明设置里有开关，但向导里不替用户打开


def test_lightroom_not_found_offers_choose_button():
    ck, _ = make(running=False, lr_found=None, conn=DOWN)
    it = item(ck, "lightroom")
    assert it["state"] == "todo" and it["action"] == "choose_lightroom" and it["action_label"] == "选择 Lightroom 程序"


def test_lightroom_uses_user_chosen_path():
    seen = []
    settings = {"base_folder": "D:\\p", "lightroom_path": "D:\\mine\\Lightroom.exe"}
    ck = wz.WizardChecker(lambda: settings, find_lightroom=lambda c: seen.append(c) or c, is_running=lambda: False,
                          get_connection=lambda: {"connected": False}, get_provider=prov, isdir=lambda p: True)
    ck.check()
    assert seen == ["D:\\mine\\Lightroom.exe"]


def test_lightroom_connected_counts_as_running_even_if_process_check_fails():
    ck, _ = make(running=False)                                    # 默认已连接
    assert item(ck, "lightroom")["state"] == "ready"


@pytest.mark.parametrize("auto", ["starting", "already_running"])
def test_lightroom_autolaunching_is_waiting_not_todo(auto):
    ck, _ = make(running=False, auto=auto, conn={"state": "connecting", "connected": False})
    s = states(ck)
    assert s["lightroom"] == "wait" and s["plugin"] == "wait"


@pytest.mark.parametrize("auto", ["not_found", "failed", "timeout", "idle"])
def test_autolaunch_finished_without_success_is_todo(auto):
    ck, _ = make(running=False, auto=auto, conn=DOWN)
    assert states(ck)["lightroom"] == "todo"


# ---------------------------------------------------------------- 3 插件
def test_plugin_waits_for_lightroom():
    ck, _ = make(running=False, conn=DOWN)
    it = item(ck, "plugin")
    assert it["state"] == "wait" and "等待 Lightroom" in it["text"]


def test_plugin_not_connected_gives_plain_troubleshooting():
    ck, _ = make(conn=DOWN)                                        # Lightroom 在运行（进程在），但插件没连上
    it = item(ck, "plugin")
    assert it["state"] == "todo" and "增效工具管理器" in it["hint"] and "已安装并正在运行" in it["hint"]
    assert "重新载入增效工具" in it["hint"]
    shown = json.dumps(it, ensure_ascii=False).replace("LrMCP", "")      # 插件名 LrMCP 是 Lightroom 里实际显示的名字
    assert not any(w in shown for w in ("MCP", "token", "桥接"))


def test_plugin_connecting_is_wait():
    ck, _ = make(conn={"state": "connecting", "connected": False})
    assert item(ck, "plugin")["state"] == "wait"


def test_plugin_ready_without_version():
    ck, _ = make(conn={"state": "connected", "connected": True})
    assert item(ck, "plugin")["text"] == "插件已连接。"


# ---------------------------------------------------------------- 4 AI 来源
def test_ai_ready_uses_provider_text():
    ck, _ = make(provider=prov(reason="已安装并已登录。"))
    it = item(ck, "ai")
    assert it["state"] == "ready" and "Claude Code 命令行" in it["text"] and "已安装并已登录" in it["text"]


def test_ai_unknown_login_but_available_is_ready_with_next_step():
    ck, _ = make(provider=prov(True, "unknown", "已安装，登录状态无法判断。", "如发送消息时提示未登录，请在终端运行 claude 并输入 /login。"))
    it = item(ck, "ai")
    assert it["state"] == "ready" and "/login" in it["hint"]


@pytest.mark.parametrize("state,reason,step", [
    ("not_installed", "未安装 Claude Code 命令行。", "请安装 Claude Code，并在终端运行 claude，输入 /login 完成登录。"),
    ("not_logged_in", "已安装，但尚未登录。", "请在终端运行 claude，输入 /login 完成登录。")])
def test_ai_unavailable_shows_reason_and_next_step_without_action(state, reason, step):
    ck, _ = make(provider=prov(False, state, reason, step))
    it = item(ck, "ai")
    assert it["state"] == "todo" and reason in it["text"] and it["hint"] == step and it["action"] == ""


def test_ai_unavailable_without_next_step_has_fallback():
    ck, _ = make(provider=prov(False, "unavailable", "不可用。", ""))
    assert "设置" in item(ck, "ai")["hint"]


def test_codex_text_comes_from_provider():
    ck, _ = make(provider=prov(False, "not_logged_in", "已安装，但尚未登录。", "请在终端运行 codex login。", name="Codex 命令行"))
    it = item(ck, "ai")
    assert "Codex 命令行" in it["text"] and "codex login" in it["hint"]


def test_ai_is_independent_of_other_items():
    ck, _ = make(base="", running=False, conn={"connected": False})
    assert states(ck)["ai"] == "ready"


# ---------------------------------------------------------------- 出错只影响单项
def test_a_check_that_raises_only_marks_that_item():
    settings = {"base_folder": "D:\\p"}

    def boom(*a):
        raise RuntimeError("x")
    ck = wz.WizardChecker(lambda: settings, find_lightroom=boom, is_running=boom, get_connection=lambda: {"connected": False},
                          get_provider=prov, isdir=lambda p: True)
    s = {i["id"]: i for i in ck.check()}
    assert s["folder"]["state"] == "ready" and s["ai"]["state"] == "ready"
    assert s["lightroom"]["state"] == "todo" and "重新检查" in s["lightroom"]["text"]
    assert s["plugin"]["state"] == "wait"


# ---------------------------------------------------------------- 总体与自动弹出条件
def test_state_ready_message():
    ck, _ = make(spawn=lambda f: f())
    r = ck.state(True)
    assert r["ready"] is True and r["checking"] is False and "都准备好了" in r["message"]


def ready_items():
    ck, _ = make()
    return ck.check()


def test_decide_all_ready_first_run_marks_done_without_opening():
    assert wz.decide(False, ready_items()) == {"open": False, "mark_done": True}


def test_decide_all_ready_already_done_does_nothing():
    assert wz.decide(True, ready_items()) == {"open": False, "mark_done": False}


def test_decide_first_run_with_a_todo_opens():
    ck, _ = make(provider=prov(False, "not_logged_in", "尚未登录。", "请登录。"))
    assert wz.decide(False, ck.check()) == {"open": True, "mark_done": False}


def test_decide_done_with_non_folder_todo_does_not_open():
    ck, _ = make(provider=prov(False, "not_logged_in", "尚未登录。", "请登录。"))
    assert wz.decide(True, ck.check()) == {"open": False, "mark_done": False}


@pytest.mark.parametrize("done", [False, True])
@pytest.mark.parametrize("kw", [{"base": ""}, {"folder_ok": False}])
def test_decide_no_folder_always_opens(done, kw):
    ck, _ = make(**kw)
    assert wz.decide(done, ck.check()) == {"open": True, "mark_done": False}


def test_decide_wait_items_do_not_trigger_first_run_popup():
    ck, _ = make(running=False, auto="starting", conn={"state": "connecting", "connected": False})
    assert wz.decide(False, ck.check()) == {"open": False, "mark_done": False}


def test_state_carries_decision_and_done_flag():
    ck, settings = make(base="", spawn=lambda f: f())
    r = ck.state(True)
    assert r["auto_open"] is True and r["wizard_done"] is False
    settings["wizard_done"] = True
    r = ck.state()
    assert r["wizard_done"] is True and r["auto_open"] is True     # 没选文件夹：即使 wizard_done 也必弹


# ---------------------------------------------------------------- 重新检查不阻塞
def test_first_state_returns_checking_placeholder_immediately():
    started = []
    ck, _ = make(spawn=started.append)                             # 线程没真正跑
    r = ck.state()
    assert r["checking"] is True and r["ready"] is False and r["auto_open"] is False and r["mark_done"] is False
    assert [i["state"] for i in r["items"]] == ["wait"] * 4 and r["items"][0]["text"] == "检查中…"
    assert len(started) == 1


def test_recheck_returns_old_result_while_checking_and_does_not_start_twice():
    jobs = []
    ck, _ = make(spawn=jobs.append)
    ck.state()
    jobs.pop()()                                                   # 第一次检查完成
    r = ck.state()
    assert r["checking"] is False and r["ready"] is True and not jobs
    r = ck.state(True)                                             # 点“重新检查”：先返回旧结果，标记检查中
    assert r["checking"] is True and r["ready"] is True and len(jobs) == 1
    ck.state(True)
    ck.state(True)
    assert len(jobs) == 1                                          # 检查进行中不重复起
    jobs.pop()()
    assert ck.state()["checking"] is False


def test_slow_check_runs_in_background_and_state_does_not_wait():
    gate = threading.Event()

    def slow_provider():
        gate.wait(10)
        return prov()
    settings = {"base_folder": "D:\\p"}
    ck = wz.WizardChecker(lambda: settings, find_lightroom=lambda c: "L", is_running=lambda: True,
                          get_connection=lambda: {"connected": True}, get_provider=slow_provider, isdir=lambda p: True)
    r = ck.state()                                                 # 真线程；AI 状态卡住时 state() 仍立刻返回
    assert r["checking"] is True
    gate.set()
    for _ in range(300):
        if not ck.state()["checking"]:
            break
        threading.Event().wait(0.02)
    assert ck.state()["ready"] is True


def test_stale_result_triggers_background_recheck():
    t = [0.0]
    jobs = []
    settings = {"base_folder": "D:\\p"}
    ck = wz.WizardChecker(lambda: settings, find_lightroom=lambda c: "L", is_running=lambda: True,
                          get_connection=lambda: {"connected": True}, get_provider=prov, isdir=lambda p: True,
                          spawn=jobs.append, clock=lambda: t[0])
    ck.state()
    jobs.pop()()
    ck.state()
    assert not jobs
    t[0] += wz.STALE_SECONDS + 1
    assert ck.state()["checking"] is True and len(jobs) == 1


def test_spawn_failure_does_not_stick_in_checking():
    def bad(f):
        raise RuntimeError("no thread")
    ck, _ = make(spawn=bad)
    assert ck.state()["checking"] is False
    assert ck.state()["checking"] is False                          # 下次还会再试，不会卡死


def test_invalidate_forces_recheck_on_next_state():
    jobs = []
    ck, _ = make(spawn=jobs.append)
    ck.state()
    jobs.pop()()
    ck.invalidate()
    assert ck.state()["checking"] is True and len(jobs) == 1


# ---------------------------------------------------------------- 设置：wizard_done
def test_default_false_and_old_settings_file_loads(tmp_path):
    assert st.defaults()["wizard_done"] is False
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"schema": 1, "provider": "claude", "confirm_default": False, "preview_edge": 1536}), encoding="utf-8")
    store = st.SettingsStore(p, restrict=lambda x: None)           # 旧文件没有 wizard_done 字段
    assert store.data["wizard_done"] is False and store.data["confirm_default"] is False and store.data["preview_edge"] == 1536


@pytest.mark.parametrize("bad", ["yes", 1, None, [], 0])
def test_sanitize_resets_non_bool_wizard_done(bad):
    assert st.sanitize({"wizard_done": bad})["wizard_done"] is False


def test_sanitize_keeps_true():
    assert st.sanitize({"wizard_done": True})["wizard_done"] is True


def test_update_wizard_done(tmp_path):
    store = st.SettingsStore(tmp_path / "s.json", restrict=lambda x: None)
    assert store.update({"wizard_done": True})["settings"]["wizard_done"] is True
    assert st.SettingsStore(tmp_path / "s.json", restrict=lambda x: None).data["wizard_done"] is True
    r = store.update({"wizard_done": "yes"})
    assert not r["ok"] and "wizard_done" in r["errors"] and store.data["wizard_done"] is True


# ---------------------------------------------------------------- Api：接口不暴露路径
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "app_settings.json")
    monkeypatch.setattr(st.SettingsStore.__init__, "__defaults__", (None, lambda p: None))
    import main
    a = main.Api()
    yield a
    a._shutdown()


def test_api_signatures_take_no_path_or_command(api):
    assert list(inspect.signature(api.wizard_state).parameters) == ["refresh"]
    assert list(inspect.signature(api.wizard_done).parameters) == ["flag"]
    assert list(inspect.signature(api.wizard_pick_folder).parameters) == []
    assert list(inspect.signature(api.wizard_pick_lightroom).parameters) == []


def test_api_wizard_done_only_accepts_bool_and_only_touches_that_setting(api):
    before = dict(api._settings.data)
    assert api.wizard_done("yes")["ok"] is False and api.wizard_done(1)["ok"] is False
    assert api._settings.data == before
    assert api.wizard_done(True) == {"ok": True, "wizard_done": True}
    after = dict(api._settings.data)
    after.pop("wizard_done"), before.pop("wizard_done")
    assert after == before
    assert api.wizard_done(False)["wizard_done"] is False


def test_api_wizard_state_is_non_blocking_and_has_no_secrets(api):
    jobs = []
    api._wizard._spawn = jobs.append                               # 不真的跑检查
    r = api.wizard_state(True)
    assert r["checking"] is True and len(r["items"]) == 4 and len(jobs) == 1
    assert set(r) == {"items", "ready", "checking", "wizard_done", "auto_open", "mark_done", "message"}
    assert "token" not in json.dumps(r).lower()


class FakeWindow:
    def __init__(self, result):
        self.result, self.calls = result, 0

    def create_file_dialog(self, kind, **kw):
        self.calls += 1
        return self.result


def test_api_pick_folder_path_comes_only_from_dialog(api, tmp_path):
    api._photolib.refresh = lambda: {"ok": True}                    # 不真的去读图库/连 Lightroom
    folder = tmp_path / "照片"
    folder.mkdir()
    api._window = FakeWindow((str(folder),))
    r = api.wizard_pick_folder()
    assert r["ok"] is True and api._settings.data["base_folder"] == str(folder)
    api._window = FakeWindow(None)                                   # 取消：什么都不变
    r = api.wizard_pick_folder()
    assert r["ok"] is False and r["cancelled"] is True and api._settings.data["base_folder"] == str(folder)


def test_api_pick_folder_rejects_bad_location(api):
    api._photolib.refresh = lambda: {"ok": True}
    api._window = FakeWindow(("C:\\Windows",))
    r = api.wizard_pick_folder()
    assert r["ok"] is False and r["message"] and api._settings.data["base_folder"] == ""


def test_api_pick_lightroom_saves_only_dialog_choice(api, tmp_path):
    exe = tmp_path / "Adobe" / "Lightroom.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"x")
    api._window = FakeWindow((str(exe),))
    r = api.wizard_pick_lightroom()
    assert r["ok"] is True and api._settings.data["lightroom_path"] == str(exe)
    other = tmp_path / "cmd.exe"
    other.write_bytes(b"x")
    api._window = FakeWindow((str(other),))
    r = api.wizard_pick_lightroom()
    assert r["ok"] is False and r["message"] and api._settings.data["lightroom_path"] == str(exe)
    api._window = FakeWindow(None)
    assert api.wizard_pick_lightroom()["cancelled"] is True
