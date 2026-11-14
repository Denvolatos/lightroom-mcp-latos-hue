# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""AI 来源“首次由用户自己选”（1.1.0）：provider_chosen 的迁移、未选择期间的门控、向导里的选择。
全部用假对象：不开窗口、不启动任何 AI 命令行、不连真实 Lightroom。"""
import json

import pytest

import settings as st
import wizard as wz
from providers import MSG_CHOOSE_AI, NotChosenProvider, is_selectable


# ---------------------------------------------------------------- 设置：迁移规则
def store_at(path):
    return st.SettingsStore(path, restrict=lambda p: None)


def test_fresh_install_has_not_chosen(tmp_path):
    s = store_at(tmp_path / "s.json")                               # 没有设置文件 = 全新安装
    assert s.data["provider_chosen"] is False and s.data["provider"] == "claude"


@pytest.mark.parametrize("content", [{"provider": "codex", "preview_edge": 1536}, {"provider": "claude"}, {}])
def test_existing_file_without_the_key_counts_as_chosen(tmp_path, content):
    p = tmp_path / "s.json"
    p.write_text(json.dumps(content), encoding="utf-8")            # 文件在、但没有这个键 = 升级用户
    s = store_at(p)
    assert s.data["provider_chosen"] is True
    assert s.data["provider"] == content.get("provider", "claude")  # 沿用原来的来源，不打扰


def test_existing_file_with_explicit_false_stays_false(tmp_path):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"provider": "claude", "provider_chosen": False}), encoding="utf-8")
    assert store_at(p).data["provider_chosen"] is False             # 1.1.0 自己写下的“还没选”要保留


@pytest.mark.parametrize("bad", ["yes", 1, None, []])
def test_existing_file_with_invalid_value_counts_as_chosen(tmp_path, bad):
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"provider": "codex", "provider_chosen": bad}), encoding="utf-8")
    assert store_at(p).data["provider_chosen"] is True


@pytest.mark.parametrize("content", ["{坏的", "", "[1,2]", "null"])
def test_unreadable_file_is_not_treated_as_fresh_install(tmp_path, content, monkeypatch):
    monkeypatch.setattr(st, "READ_RETRY_SECONDS", 0)
    p = tmp_path / "s.json"
    p.write_text(content, encoding="utf-8")       # 1.1.1：文件存在但读不出 = 升级用户，不再要求重新选 AI；坏文件留档
    assert store_at(p).data["provider_chosen"] is True
    assert list(tmp_path.glob("s.json.bad-*"))


def test_sanitize_distinguishes_dict_from_missing():
    assert st.sanitize(None)["provider_chosen"] is False
    assert st.sanitize({})["provider_chosen"] is True


def test_update_provider_chosen_is_validated_and_persisted(tmp_path):
    p = tmp_path / "s.json"
    s = store_at(p)
    r = s.update({"provider_chosen": "yes"})
    assert not r["ok"] and "provider_chosen" in r["errors"] and s.data["provider_chosen"] is False
    assert s.update({"provider": "codex", "provider_chosen": True}, selectable=is_selectable)["ok"]
    again = store_at(p)
    assert again.data["provider_chosen"] is True and again.data["provider"] == "codex"


def test_first_save_of_other_settings_keeps_not_chosen(tmp_path):
    """全新安装先保存了别的设置（比如选了工作文件夹）：文件出现了，但“还没选 AI”不能因此变成“已选”。"""
    p = tmp_path / "s.json"
    s = store_at(p)
    assert s.update({"preview_edge": 1536})["ok"]
    assert json.loads(p.read_text(encoding="utf-8"))["provider_chosen"] is False
    assert store_at(p).data["provider_chosen"] is False


# ---------------------------------------------------------------- 向导：未选择时的条目与弹出规则
def checker(provider):
    return wz.WizardChecker(lambda: {"base_folder": "D:\\照片", "wizard_done": True},
                            find_lightroom=lambda c: "C:\\x\\Lightroom.exe", is_running=lambda: True,
                            get_connection=lambda: {"state": "connected", "connected": True},
                            get_provider=lambda: provider, isdir=lambda p: True, spawn=lambda fn: fn())


CHOICES = [
    {"id": "claude", "name": "Claude Code 命令行", "short_name": "Claude", "available": True, "state": "ready",
     "reason": "已安装并已登录。", "next_step": "", "selectable": True, "privacy_notice": ""},
    {"id": "codex", "name": "Codex 命令行", "short_name": "Codex", "available": False, "state": "not_installed",
     "reason": "未安装 Codex 命令行。", "next_step": "请安装 Codex CLI 后重试。", "selectable": True,
     "privacy_notice": "使用 Codex 时，选中照片的预览会发送至所选的 Codex 服务。"},
]


def test_wizard_item_lists_one_button_per_source_with_status_and_privacy():
    ck = checker({"chosen": False, "choices": CHOICES})
    ai = next(i for i in ck.check() if i["id"] == "ai")
    assert ai["state"] == "todo" and ai["need_choice"] is True and "请选择要使用的 AI" in ai["text"]
    assert ai["action"] == ""                                       # 没选之前不显示“更换 AI 来源”
    assert [(c["id"], c["label"]) for c in ai["choices"]] == [("claude", "使用 Claude"), ("codex", "使用 Codex")]
    assert ai["choices"][0]["status"] == "已安装并已登录。" and ai["choices"][0]["ok"] is True
    assert ai["choices"][1]["status"] == "未安装 Codex 命令行。" and ai["choices"][1]["ok"] is False   # 未安装的也列出来、可以选
    assert "预览会发送" in ai["choices"][1]["privacy"] and ai["choices"][0]["privacy"] == ""


def test_wizard_always_opens_until_ai_is_chosen_even_when_done():
    ck = checker({"chosen": False, "choices": CHOICES})
    view = ck.state(True)                                           # wizard_done=True 也要弹
    assert view["auto_open"] is True and view["mark_done"] is False and view["ready"] is False


def test_wizard_after_choice_shows_change_button_and_does_not_force_open():
    ck = checker({"chosen": True, "name": "Claude Code 命令行", "available": True, "state": "ready",
                  "reason": "已安装并已登录。", "next_step": ""})
    view = ck.state(True)
    ai = next(i for i in view["items"] if i["id"] == "ai")
    assert ai["state"] == "ready" and ai["action"] == "choose_ai" and ai["action_label"] == "更换 AI 来源"
    assert "need_choice" not in ai and view["auto_open"] is False


def test_decide_ai_unchosen_always_opens():
    items = [{"id": k, "state": "ready"} for k in wz.ORDER]
    items[-1] = {"id": "ai", "state": "todo", "need_choice": True}
    assert wz.decide(True, items)["open"] is True and wz.decide(False, items)["open"] is True
    items[-1] = {"id": "ai", "state": "todo"}                       # 已选但没装好：只在第一次弹（原规则）
    assert wz.decide(True, items)["open"] is False and wz.decide(False, items)["open"] is True


# ---------------------------------------------------------------- 占位来源
def test_not_chosen_provider_never_starts_anything_and_answers_politely():
    p = NotChosenProvider()
    assert p.start({"X": "1"}) is True and p.ensure_running() is True and p.restart() is True
    assert p.alive is True and p.busy is False and p.spawned_at is None
    stt = p.status()
    assert stt["available"] is False and stt["state"] == "not_chosen" and "环境检查" in stt["next_step"]
    events = []
    p.send("你好", events.append)
    assert [e["type"] for e in events] == ["error", "done"] and events[0]["message"] == MSG_CHOOSE_AI
    p.stop(), p.reset(), p.close()


# ---------------------------------------------------------------- Api：未选择期间的门控与选择
class FakeProbe:
    def rows(self):
        return [dict(c) for c in CHOICES] + [{"id": "api", "name": "API 密钥", "selectable": False, "available": False,
                                              "reason": "后续提供。", "short_name": "API 密钥", "privacy_notice": ""}]


class FakeProvider:
    """记录是否被启动；不产生任何进程。"""
    def __init__(self, pid, log):
        self.id, self._log = pid, log
        self.alive, self.busy, self.spawned_at = True, False, None

    def start(self, env=None):
        self._log.append(("start", self.id))
        return True

    def status(self):
        return {"available": True, "state": "ready", "reason": "已安装并已登录。", "next_step": ""}

    def close(self):
        self._log.append(("close", self.id))

    def reset(self): pass
    def stop(self): pass
    def ensure_running(self): return True
    def restart(self): return True


@pytest.fixture
def env(tmp_path, monkeypatch):
    """全新安装（没有设置文件）的 Api；任何真实来源的创建都会被记录下来。"""
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "app_settings.json")
    monkeypatch.setattr(st.SettingsStore.__init__, "__defaults__", (None, lambda p: None))
    import main
    created = []

    def fake_create(pid, **kw):
        created.append(("create", pid, bool(kw.get("persistent"))))
        return FakeProvider(pid, created)
    monkeypatch.setattr(main, "create_provider", fake_create)
    monkeypatch.setattr(main, "StatusProbe", FakeProbe)
    monkeypatch.setenv("LRAPP_PER_TURN", "1")                       # 选 Claude 时也不重建通道（那条路径由 test_codex_integration 覆盖）
    a = main.Api()
    a._created = created
    yield a
    a._shutdown()


def test_fresh_install_creates_no_ai_provider_and_no_persistent_session(env):
    assert isinstance(env._provider, NotChosenProvider) and env._persistent is False
    assert env._created == []                                       # 连来源对象都没建，更没有进程
    assert env._backend.session is env._provider


def test_ai_entries_are_refused_with_a_friendly_message_until_chosen(env):
    for r in (env.send("提亮一点"), env.pick_prepare(), env.pick_start({}), env.lib_record_start()):
        assert r["ok"] is False and r["need_ai_choice"] is True and r["message"] == MSG_CHOOSE_AI
    assert env._busy is False and env._created == []
    assert env.library_state()["ok"] is True                        # 图库等其他功能照常
    assert env.get_settings(False)["settings"]["provider_chosen"] is False


def test_wizard_state_offers_the_selectable_sources_only(env):
    env._wizard._spawn = lambda fn: fn()
    ai = next(i for i in env.wizard_state(True)["items"] if i["id"] == "ai")
    assert ai["need_choice"] is True and [c["id"] for c in ai["choices"]] == ["claude", "codex"]


@pytest.mark.parametrize("bad", ["api", "unknown", "", None, 5, {"id": "claude"}, "claude; rm -rf", "CLAUDE"])
def test_choose_ai_only_accepts_registered_selectable_ids(env, bad):
    r = env.wizard_choose_ai(bad)
    assert r["ok"] is False and r["message"]
    assert env._settings.data["provider_chosen"] is False and isinstance(env._provider, NotChosenProvider)
    assert env._created == []


@pytest.mark.parametrize("pid", ["claude", "codex"])
def test_choose_ai_saves_and_takes_effect_through_the_switch_path(env, pid):
    env._wizard._spawn = lambda fn: fn()
    r = env.wizard_choose_ai(pid)
    assert r["ok"] is True
    assert env._settings.data["provider"] == pid and env._settings.data["provider_chosen"] is True
    on_disk = json.loads(st.SETTINGS_FILE.read_text(encoding="utf-8"))
    assert on_disk["provider"] == pid and on_disk["provider_chosen"] is True
    assert env._provider.id == pid and env._session is env._provider and env._backend.session is env._provider
    assert env._created[0][:2] == ("create", pid)
    ai = next(i for i in env.wizard_state(True)["items"] if i["id"] == "ai")
    assert "need_choice" not in ai and ai["action"] == "choose_ai"   # 选完后是“更换 AI 来源”
    assert env.wizard_choose_ai("codex")["ok"] is False             # 已选过：不在这里改
    assert env._provider.id == pid


def test_choose_ai_is_refused_while_busy(env):
    env._busy = True
    assert env.wizard_choose_ai("codex")["ok"] is False and env._settings.data["provider_chosen"] is False
    env._busy = False


def test_settings_dialog_cannot_choose_or_flip_the_flag_before_the_wizard(env):
    r = env.save_settings({"provider": "codex", "provider_chosen": True, "preview_edge": 1536})
    assert r["ok"] is True and env._settings.data["preview_edge"] == 1536
    assert env._settings.data["provider"] == "claude" and env._settings.data["provider_chosen"] is False
    env.reset()                                                     # “新对话”也不会因此启动来源
    assert isinstance(env._provider, NotChosenProvider) and env._created == []


def test_upgrade_user_is_not_asked(tmp_path, monkeypatch):
    f = tmp_path / "app_settings.json"
    f.write_text(json.dumps({"provider": "codex", "wizard_done": True}), encoding="utf-8")
    monkeypatch.setattr(st, "SETTINGS_FILE", f)
    monkeypatch.setattr(st.SettingsStore.__init__, "__defaults__", (None, lambda p: None))
    import main
    a = main.Api()
    try:
        assert a._provider.id == "codex" and a._ai_chosen() is True
        assert a.save_settings({"provider_chosen": False})["ok"] and a._ai_chosen() is True   # 页面改不了这个标记
    finally:
        a._shutdown()
