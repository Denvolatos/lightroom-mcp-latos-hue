# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""Codex 来源与软件其余功能的集成核对（假 CLI、假 Lightroom，不联网、不调用任何真实模型、不碰 Lightroom）。

覆盖：挑片期间写入一律拒绝（经 Codex 的确认代理）、"逐项确认"开关、来源切换后各功能的通道重绑与进程互不残留、
环境变量传到 CLI 进程、超时提示与挑片/经验的超时判断一致、实验性标记与默认来源。
"""
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import claude_bridge as cb
import codex_proxy
import confirm_hub as ch
import providers
import providers.codex_provider as cp
import settings as st
from providers import ClaudeProvider, available_providers, create_provider
from providers.codex_provider import CodexProvider

WRITES = ("lr_set_develop", "lr_restore", "lr_restore_original")
FAKE_CODEX = str(Path(__file__).with_name("fake_codex.py"))


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "app_settings.json")
    # 已有设置文件 = 升级用户：视为已经选过 AI 来源（全新安装的“请先选择”见 test_provider_choice.py）
    (tmp_path / "app_settings.json").write_text('{"provider": "claude"}', encoding="utf-8")
    monkeypatch.setattr(st, "restrict_to_current_user", lambda p: None)
    monkeypatch.setattr(st.SettingsStore.__init__, "__defaults__", (None, lambda p: None))
    import main
    a = main.Api()
    yield a
    a._shutdown()


def _via_proxy(monkeypatch, hub, token, name="lr_set_develop", args=None):
    monkeypatch.setenv("LRAPP_PORT", str(hub.port))
    monkeypatch.setenv("LRAPP_TOKEN", token)
    return codex_proxy._confirm(name, args if args is not None else {"changes": {"Exposure": 0.1}})


# ---------------------------------------------------------------- 挑片期间的写入禁用（与来源无关）
def test_pick_blocks_every_write_through_codex_proxy_then_normal_after(api, monkeypatch):
    hub, cards = api._hub, []
    hub.timeout = 3

    def emit(ev):
        if ev["type"] == "confirm":
            cards.append(ev)
            hub.answer(ev["id"], True)
    hub.emit = emit
    token = hub.begin_turn()
    assert api._pick_acquire() is True                       # 挑片开始：deny_all
    for name in WRITES:
        assert _via_proxy(monkeypatch, hub, token, name, {"edit_id": "e1"}) is False
    assert cards == []                                       # 没有弹出任何确认卡片
    hub.auto_allow = True                                    # 即使"逐项确认"关着，挑片期间也照样拒绝
    for name in WRITES:
        assert _via_proxy(monkeypatch, hub, token, name, {"edit_id": "e1"}) is False
    api._pick_release()
    token = hub.begin_turn()
    hub.auto_allow = False
    assert _via_proxy(monkeypatch, hub, token) is True       # 挑片结束：恢复正常确认流程（此处卡片被点了"允许"）
    assert len(cards) == 1


def test_pick_denial_message_is_source_independent():
    hub = ch.ConfirmHub(lambda e: None)
    hub.deny_all = True
    for tool in ("lr_set_develop", "mcp__lightroom_mcp__lr_restore", "mcp__lightroom_mcp__lr_restore_original"):
        r = hub.request(tool, {})
        assert r["allow"] is False and "挑片期间" in r["message"]


# ---------------------------------------------------------------- "逐项确认"开关对 Codex 同样生效
def test_confirmation_switch_applies_to_codex_proxy(monkeypatch):
    cards = []

    def emit(ev):
        if ev["type"] == "confirm":
            cards.append(ev)
            hub.answer(ev["id"], False)
    hub = ch.ConfirmHub(emit, timeout=3)
    hub.start()
    try:
        token = hub.begin_turn()
        hub.auto_allow = True                                # 开关关：自动放行，不弹卡片
        assert _via_proxy(monkeypatch, hub, token) is True and cards == []
        hub.auto_allow = False                               # 开关开：弹卡片，用户拒绝 -> 不执行
        assert _via_proxy(monkeypatch, hub, token) is False and len(cards) == 1
        hub.auto_allow = True                                # 开关关也不放行白名单之外的工具
        assert _via_proxy(monkeypatch, hub, token, "lr_export", {}) is False
    finally:
        hub.stop()


def test_send_sets_switch_token_and_env_for_codex(api):
    seen = {}

    class Rec(CodexProvider):
        def send(self, text, on_event, **options):
            seen.update(options, auto=api._hub.auto_allow, token=api._hub._token, text=text)
            on_event({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": False})

    api._provider = api._session = Rec()
    api._persistent = False
    api._backend.wait_ready = lambda: (True, "")
    api._ctx_pending = False
    assert api.send("你好", False)["ok"]
    for _ in range(100):
        if not api._busy:
            break
        time.sleep(0.05)
    assert seen["auto"] is True and seen["confirm"] is False
    assert seen["extra_env"]["LRAPP_PORT"] == str(api._hub.port) and seen["extra_env"]["LRAPP_TOKEN"] == seen["token"]
    assert api._hub._token is None                           # 一轮结束口令作废
    assert api._busy is False


def test_pick_and_library_send_use_codex_per_turn_env(api):
    seen = []

    class Rec(CodexProvider):
        def send(self, text, on_event, **options):
            seen.append(options)

    api._provider = api._session = Rec()
    api._persistent = False
    api._pick_send("p", lambda e: None)
    assert seen[0]["confirm"] is True and set(seen[0]["extra_env"]) == {"LRAPP_PORT", "LRAPP_TOKEN"}


# ---------------------------------------------------------------- 环境变量传到 CLI 进程；新对话；关闭不残留
def _env_cli(tmp_path):
    script = tmp_path / "env_cli.py"
    script.write_text(
        "import json,os,sys\nsys.stdin.read()\n"
        "e=lambda v:print(json.dumps(v),flush=True)\n"
        "e({'type':'thread.started','thread_id':'T1'})\n"
        "e({'type':'item.completed','item':{'id':'a','type':'agent_message',"
        "'text':os.environ.get('LRAPP_PORT','')+'|'+os.environ.get('LRAPP_TOKEN','')}})\n"
        "e({'type':'turn.completed','usage':{}})\n", encoding="utf-8")
    return script


def test_env_reaches_cli_and_new_chat_clears_thread(tmp_path, monkeypatch):
    script = _env_cli(tmp_path)
    monkeypatch.setattr(cp, "build_command", lambda path, thread, workdir, prompt: [sys.executable, str(script)])
    p = CodexProvider(workdir=tmp_path, find=lambda: sys.executable, login_check=lambda _: True)
    events = []
    p.send("hi", events.append, confirm=True, extra_env={"LRAPP_PORT": "4321", "LRAPP_TOKEN": "tok"})
    assert events[-1]["type"] == "done" and not events[-1]["is_error"]
    assert "".join(e["text"] for e in events if e["type"] == "text") == "4321|tok"
    assert p.thread_id == "T1"
    p.reset()                                                # 新对话
    assert p.thread_id is None


def test_close_kills_running_cli_and_leaves_no_process(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "build_command", lambda path, thread, workdir, prompt: [sys.executable, FAKE_CODEX])
    p = CodexProvider(workdir=tmp_path, find=lambda: sys.executable, login_check=lambda _: True)
    events = []
    t = threading.Thread(target=p.send, args=("slow", events.append))
    t.start()
    for _ in range(100):
        if p.busy:
            break
        time.sleep(0.05)
    proc = p._proc
    assert proc is not None
    p.close()
    t.join(10)
    assert not t.is_alive() and proc.poll() is not None and not p.busy and not p.alive
    assert [e["type"] for e in events][-2:] == ["stopped", "done"]


def test_timeout_message_matches_pick_and_library_check(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "build_command", lambda path, thread, workdir, prompt: [sys.executable, FAKE_CODEX])
    monkeypatch.setattr(cp, "TIMEOUT_SECONDS", 0.5)
    p = CodexProvider(workdir=tmp_path, find=lambda: sys.executable, login_check=lambda _: True)
    events = []
    p.send("slow", events.append)
    errs = [e["message"] for e in events if e["type"] == "error"]
    assert errs == [cb.MSG_TIMEOUT]                          # 挑片与"记成经验"都以此判断"超时"
    assert events[-1]["type"] == "done" and events[-1]["is_error"]


# ---------------------------------------------------------------- 来源切换：通道重绑、互不残留
def _patch_main(monkeypatch):
    import main
    made = {"lr": [], "backend": [], "pm": []}

    def mk(kind):
        def f(*a, **k):
            m = MagicMock()
            made[kind].append(m)
            return m
        return f
    monkeypatch.setattr(main, "LrService", mk("lr"))
    monkeypatch.setattr(main, "Backend", mk("backend"))
    monkeypatch.setattr(main, "PreviewManager", mk("pm"))
    monkeypatch.setattr(main, "PreviewServer", lambda *a, **k: MagicMock())
    return made


def test_switch_claude_to_codex_and_back_rebinds_every_service(api, monkeypatch):
    made = _patch_main(monkeypatch)
    claude = api._provider
    assert claude.id == "claude" and api._persistent
    shutdowns = []
    monkeypatch.setattr(claude.session, "shutdown", lambda: shutdowns.append("claude"))
    old_lr = api._lr
    api._borrowing = True                       # 1.1.1：常驻 claude 那条通道连上后才借用；这里模拟已经借用

    api._settings.data["provider"] = "codex"
    assert api._apply_provider_choice()
    assert api._provider.id == "codex" and api._persistent is False and shutdowns == ["claude"]
    new_lr = api._lr
    assert new_lr is made["lr"][-1] and new_lr is not old_lr
    for svc in (api._import, api._export, api._photolib, api._pick, api._apply, api._lib):
        assert svc.lr is new_lr                              # 没有任何功能还指向已停止的旧通道
    assert api._pick.server is api._preview.server and api._hub.current_values == new_lr.current_values
    assert api._backend is made["backend"][-1]

    started = []
    monkeypatch.setattr(ClaudeProvider, "start", lambda self, env=None: started.append(dict(env or {})) or True)
    codex = api._provider
    api._settings.data["provider"] = "claude"
    assert api._apply_provider_choice()
    assert api._provider.id == "claude" and api._persistent is True and codex.alive is False   # Codex 已关闭
    assert started and started[0]["LRAPP_PORT"] == str(api._hub.port) and started[0]["LRAPP_TOKEN"]
    for svc in (api._import, api._export, api._photolib, api._pick, api._apply, api._lib):
        assert svc.lr is api._lr


def test_codex_new_chat_resets_thread_without_switching(api):
    p = CodexProvider(find=lambda: "codex", login_check=lambda _: True)
    p.thread_id = "T9"
    api._provider = api._session = p
    api._persistent = False
    api._settings.data["provider"] = "codex"
    api.reset()
    assert p.thread_id is None and api._provider is p


def test_new_chat_context_block_does_not_depend_on_provider(api, monkeypatch):
    api._provider = api._session = CodexProvider(find=lambda: "codex", login_check=lambda _: True)
    monkeypatch.setattr(api._lib, "context_block", lambda: {"text": "资料块", "used": 1, "eligible": 1, "truncated": False})
    api._ctx_pending = True
    assert api._with_notes("请调亮").startswith("资料块") and api._with_notes("再亮一点") == "再亮一点"


# ---------------------------------------------------------------- 实验性标记与默认来源
def test_codex_is_no_longer_experimental_and_claude_remains_default():
    assert st.DEFAULT_PROVIDER == "claude" and providers.DEFAULT_PROVIDER == "claude"
    ready = {"available": True, "state": "ready", "reason": "已安装并已登录。", "next_step": ""}
    lst = {x["id"]: x for x in available_providers(ready, ready)}
    assert lst["codex"]["experimental"] is False and lst["codex"]["experimental_notice"] == ""
    assert "预览会发送至" in lst["codex"]["privacy_notice"]
    assert lst["claude"]["experimental"] is False and lst["claude"]["experimental_notice"] == ""
    assert create_provider("unknown").id == "claude"


def test_detecting_codex_never_switches_provider(api, monkeypatch):
    monkeypatch.setattr(cp, "find_codex", lambda: "C:/fake/codex.exe")
    monkeypatch.setattr(cp, "check_login", lambda path, run=None: True)
    r = api.get_settings()
    assert r["settings"]["provider"] == "claude" and r["current_provider"] == "claude"
    assert api._settings.data["provider"] == "claude"
    assert next(p for p in r["providers"] if p["id"] == "codex")["experimental"] is False
