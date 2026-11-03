"""注册表与 Claude 来源状态检测。"""
import json
import subprocess

import providers
from providers import available_providers, create_provider, is_selectable
from providers.base import make_status, validate_event
from providers.claude_provider import ClaudeProvider, check_login
from providers.codex_stub import CodexProvider


class _Idle:
    alive = busy = False
    spawned_at = None


def mk(found, logged):
    return ClaudeProvider(session=_Idle(), find=lambda: found, login_check=lambda p: logged)


def test_status_variants():
    assert mk(None, None).status()["state"] == "not_installed"
    assert not mk(None, None).status()["available"]
    st = mk("claude", False).status()
    assert st["state"] == "not_logged_in" and not st["available"] and "/login" in st["next_step"]
    st = mk("claude", True).status()
    assert st["state"] == "ready" and st["available"]
    st = mk("claude", None).status()
    assert st["state"] == "unknown" and st["available"]        # 无法判断时不阻止使用，失败时再提示


def test_status_is_cached_between_calls():
    calls = []
    t = [0.0]
    p = ClaudeProvider(session=_Idle(), find=lambda: "claude", clock=lambda: t[0],
                       login_check=lambda path: calls.append(1) or True)
    p.status(); p.status()
    assert len(calls) == 1
    t[0] = 100
    p.status()
    assert len(calls) == 2


def test_check_login_parses_only_logged_in_flag():
    def runner(out):
        return lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=out, stderr="")
    assert check_login("claude", runner(json.dumps({"loggedIn": True, "email": "x"}))) is True
    assert check_login("claude", runner(json.dumps({"loggedIn": False}))) is False
    assert check_login("claude", runner("not json")) is None
    assert check_login("claude", runner(json.dumps({"other": 1}))) is None

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("claude", 1)
    assert check_login("claude", boom) is None


def test_registry_lists_claude_and_two_placeholders():
    lst = available_providers(make_status(True, "ready", "已安装并已登录。", ""))
    assert [x["id"] for x in lst] == ["claude", "codex", "api"]
    assert lst[0]["available"] and lst[0]["selectable"]
    for x in lst[1:]:
        assert not x["available"] and not x["selectable"] and "后续提供" in x["reason"]
    assert "欢迎贡献" in lst[1]["reason"] and "DeepSeek" in lst[2]["reason"]


def test_selectable_and_create():
    assert is_selectable("claude") and not is_selectable("codex") and not is_selectable("api") and not is_selectable("x")
    p = create_provider("codex", session=_Idle())            # 未实现的 id 回退到默认来源
    assert p.id == "claude"


def test_codex_stub_is_unavailable_and_raises():
    c = CodexProvider()
    assert not c.status()["available"]
    for fn in (lambda: c.start(), lambda: c.send("x", print), c.stop, c.reset, c.close):
        try:
            fn()
        except NotImplementedError:
            continue
        raise AssertionError("骨架方法应抛 NotImplementedError")


def test_validate_event_detects_problems():
    assert validate_event({"type": "text", "text": "a"}) == []
    assert validate_event({"type": "tool", "name": "x"})
    assert validate_event({"type": "nope"})
