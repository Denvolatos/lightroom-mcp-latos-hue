# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""AI 来源的契约测试：任何来源实现都应通过。贡献者新增来源时，可直接复用本文件自测。

用法（贡献者）：
1. 写一个 harness 类，继承 ProviderContract，实现 make() 与几个"剧情"入口（见下面 FakeHarness / ClaudeHarness）；
2. 把它加到文件末尾，pytest 会把同一组测试跑在你的实现上。
这里的测试都不需要真实模型：用假的输出源演示事件顺序、stop 后继续对话、reset 清空、错误映射为中文、状态返回。
"""
import re
import sys
import threading
import time
from pathlib import Path

import pytest

import claude_bridge as cb
import persistent_session as ps
from providers import ClaudeProvider
from providers.codex_provider import CodexProvider
import providers.codex_provider as cp
from providers.base import AIProvider, READY, UNAVAILABLE, make_status, validate_event

FAKE_CLAUDE = str(Path(__file__).with_name("fake_claude.py"))
HAS_CJK = re.compile(r"[一-鿿]")


# ---------------------------------------------------------------- 演示用的假来源
class FakeProvider(AIProvider):
    """最小的合格实现：按用户消息内容演不同剧情。可作为新来源的参考。
    hello：文字 + 一次工具调用 + 文字；slow：一直输出直到被 stop；boom：出错。"""
    id, display_name, supports_images = "fake", "演示来源", False

    def __init__(self, available: bool = True):
        self._available = available
        self.history: list[str] = []
        self._stop = threading.Event()
        self.closed = False

    def status(self) -> dict:
        if self._available:
            return make_status(True, READY, "可用。", "")
        return make_status(False, UNAVAILABLE, "演示来源未启用。", "请先在设置中启用。")

    def start(self, env=None) -> bool:
        return True

    def send(self, text, on_event, **options) -> None:
        self._stop.clear()
        self.history.append(text)
        if text == "boom":
            on_event({"type": "error", "message": "网络连接异常，请检查网络后重试。"})
            on_event({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
            return
        if text == "slow":
            on_event({"type": "text", "text": "开始"})
            for _ in range(200):
                if self._stop.wait(0.02):
                    on_event({"type": "stopped"})
                    on_event({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
                    return
            on_event({"type": "done", "tokens": 1, "cost": None, "text": "开始", "is_error": False})
            return
        on_event({"type": "text", "text": "好的"})
        on_event({"type": "tool", "name": "lr_status", "id": "T1", "input": {}, "label": "正在确认 Lightroom 连接状态"})
        on_event({"type": "tool_result", "id": "T1", "text": "ok", "is_error": False})
        on_event({"type": "text", "text": "完成"})
        on_event({"type": "done", "tokens": 3, "cost": None, "text": "好的完成", "is_error": False})

    def stop(self) -> None:
        self._stop.set()

    def reset(self) -> None:
        self.history.clear()

    def close(self) -> None:
        self.closed = True


# ---------------------------------------------------------------- 契约
class ProviderContract:
    """子类提供：make()（返回已 start 的来源）、context_size(p)（对话上下文是否为空的度量）、
    NORMAL / SLOW / ERROR 三个用户消息文字（分别触发：正常一轮、可被中断的长回复、出错）。"""
    NORMAL, SLOW, ERROR = "hello", "slow", "boom"
    STOP_TIMEOUT = 5

    def make(self, tmp_path, monkeypatch) -> AIProvider:
        raise NotImplementedError

    def context_size(self, p) -> int:
        raise NotImplementedError

    @pytest.fixture
    def provider(self, tmp_path, monkeypatch):
        p = self.make(tmp_path, monkeypatch)
        yield p
        p.close()

    @staticmethod
    def run(p, text):
        ev: list[dict] = []
        p.send(text, ev.append)
        return ev

    # ---- 元数据 ----
    def test_identity(self, provider):
        assert provider.id and re.fullmatch(r"[a-z][a-z0-9_]*", provider.id)
        assert HAS_CJK.search(provider.display_name)
        assert isinstance(provider.supports_images, bool)

    def test_status_shape(self, provider):
        st = provider.status()
        assert set(st) == {"available", "state", "reason", "next_step"}
        assert isinstance(st["available"], bool) and st["state"] and HAS_CJK.search(st["reason"])
        if not st["available"]:
            assert st["next_step"]            # 不可用时必须告诉用户下一步

    # ---- 事件 ----
    def test_event_order_and_format(self, provider):
        ev = self.run(provider, self.NORMAL)
        for e in ev:
            assert validate_event(e) == [], e
        kinds = [e["type"] for e in ev]
        assert kinds.count("done") == 1 and kinds[-1] == "done"       # 有且仅有一个 done，且是最后一个
        assert "error" not in kinds and not ev[-1]["is_error"]
        assert "text" in kinds
        tools = [e for e in ev if e["type"] == "tool"]
        results = [e for e in ev if e["type"] == "tool_result"]
        assert tools and results
        assert kinds.index("tool") < kinds.index("tool_result")        # 先调用后返回
        assert {r["id"] for r in results} <= {t["id"] for t in tools}  # 返回对应某次调用
        assert all("__" not in t["name"] for t in tools)               # 工具名不含服务前缀

    def test_two_turns_work(self, provider):
        a, b = self.run(provider, self.NORMAL), self.run(provider, self.NORMAL)
        assert a[-1]["type"] == b[-1]["type"] == "done"

    # ---- 中断 ----
    def test_stop_keeps_session(self, provider):
        ev, started = [], threading.Event()

        def emit(e):
            ev.append(e)
            if e["type"] == "text":
                started.set()

        t = threading.Thread(target=provider.send, args=(self.SLOW, emit))
        t.start()
        assert started.wait(self.STOP_TIMEOUT)
        provider.stop()
        t.join(self.STOP_TIMEOUT + 3)
        assert not t.is_alive()
        kinds = [e["type"] for e in ev]
        assert "stopped" in kinds and kinds[-1] == "done" and "error" not in kinds   # 中断不当作错误展示
        assert kinds.index("stopped") < kinds.index("done")
        assert self.run(provider, self.NORMAL)[-1]["is_error"] is False              # 之后仍能继续对话

    # ---- 新对话 ----
    def test_reset_clears_context(self, provider):
        self.run(provider, self.NORMAL)
        assert self.context_size(provider) > 0
        provider.reset()
        assert self.context_size(provider) == 0
        assert self.run(provider, self.NORMAL)[-1]["is_error"] is False

    # ---- 错误 ----
    def test_error_is_chinese_and_ends_with_done(self, provider):
        ev = self.run(provider, self.ERROR)
        errs = [e for e in ev if e["type"] == "error"]
        assert errs and all(HAS_CJK.search(e["message"]) for e in errs)
        assert ev[-1]["type"] == "done" and ev[-1]["is_error"] is True
        assert [e["type"] for e in ev].count("done") == 1

    def test_close_is_idempotent(self, provider):
        provider.close()
        provider.close()


class TestFakeProvider(ProviderContract):
    def make(self, tmp_path, monkeypatch):
        return FakeProvider()

    def context_size(self, p):
        return len(p.history)

    def test_unavailable_status(self):
        st = FakeProvider(available=False).status()
        assert st["available"] is False and st["state"] == UNAVAILABLE and HAS_CJK.search(st["next_step"])


class TestClaudeProvider(ProviderContract):
    """Claude 封装跑同一组契约（用假的 claude 进程，不调用真实模型）。"""
    ERROR = "die"

    def make(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cb, "find_claude", lambda: "claude")
        monkeypatch.setattr(cb, "build_command", lambda *a, **k: [sys.executable, FAKE_CLAUDE])
        monkeypatch.setattr(cb, "write_mcp_config", lambda *a, **k: tmp_path / "x.json")
        monkeypatch.setattr(ps, "INTERRUPT_GRACE", 1)
        monkeypatch.setattr("timing.TIMING_LOG", tmp_path / "t.jsonl")
        p = ClaudeProvider(session=ps.PersistentSession(workdir=tmp_path), login_check=lambda path: True)
        assert p.start()
        return p

    def context_size(self, p):
        return 1 if p.session.session_id else 0


class TestCodexProvider(ProviderContract):
    """Codex JSONL adapter follows the same event and lifecycle contract."""

    def make(self, tmp_path, monkeypatch):
        fake = str(Path(__file__).with_name("fake_codex.py"))
        monkeypatch.setattr(cp, "build_command", lambda path, thread, workdir, prompt:
                            [sys.executable, fake])
        p = CodexProvider(workdir=tmp_path, find=lambda: sys.executable, login_check=lambda path: True)
        assert p.start()
        return p

    def context_size(self, p):
        return 1 if p.thread_id else 0

    def test_long_prompt_uses_stdin(self, provider):
        events = self.run(provider, "长" * 100000)
        assert events[-1]["type"] == "done" and not events[-1]["is_error"]
