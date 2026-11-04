"""Codex's tool surface and write gate must remain code-enforced."""
import json

import codex_proxy
from confirm_hub import ConfirmHub
from providers.codex_provider import TOOLS, build_command


def test_command_exposes_only_proxy_and_no_builtin_file_tools(tmp_path):
    cmd = build_command("codex", None, tmp_path, "hello")
    settings = [cmd[i + 1] for i, part in enumerate(cmd[:-1]) if part == "-c"]
    assert "--ignore-user-config" in cmd and "--strict-config" in cmd
    assert {"shell_tool", "apps", "view_image"} <= {
        cmd[i + 1] for i, part in enumerate(cmd[:-1]) if part == "--disable"}
    assert 'sandbox_mode="read-only"' in settings
    assert 'web_search="disabled"' in settings
    enabled = next(s.split("=", 1)[1] for s in settings if s.startswith("mcp_servers.lightroom_mcp.enabled_tools="))
    assert json.loads(enabled) == TOOLS
    assert 'mcp_servers.lightroom_mcp.env_vars=["LRAPP_PORT", "LRAPP_TOKEN"]' in settings
    assert cmd[-1] == "-" and "hello" not in cmd
    resumed = build_command("codex", "thread-id", tmp_path, "x" * 100000)
    assert resumed[-2:] == ["thread-id", "-"] and len(" ".join(resumed)) < 10000
    assert "--skip-git-repo-check" in resumed


def test_proxy_denies_write_without_valid_confirmation(monkeypatch):
    monkeypatch.delenv("LRAPP_PORT", raising=False)
    monkeypatch.delenv("LRAPP_TOKEN", raising=False)
    assert codex_proxy._confirm("lr_set_develop", {"Exposure2012": 0.1}) is False
    monkeypatch.setenv("LRAPP_PORT", "99999")
    monkeypatch.setenv("LRAPP_TOKEN", "secret")
    assert codex_proxy._confirm("lr_set_develop", {}) is False


def test_proxy_passes_write_only_on_explicit_allow(monkeypatch):
    monkeypatch.setenv("LRAPP_PORT", "12345")
    monkeypatch.setenv("LRAPP_TOKEN", "secret")
    seen = []

    class Reply:
        def __init__(self, allow):
            self.allow = allow

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def read(self):
            return json.dumps({"allow": self.allow}).encode()

    def urlopen(request, timeout):
        seen.append((request.full_url, request.get_header("Authorization"), json.loads(request.data)))
        return Reply(allowed[0])

    allowed = [False]
    monkeypatch.setattr(codex_proxy.urllib.request, "urlopen", urlopen)
    assert codex_proxy._confirm("lr_set_develop", {"Exposure2012": 0.1}) is False
    allowed[0] = True
    assert codex_proxy._confirm("lr_set_develop", {"Exposure2012": 0.1}) is True
    assert all(item[0] == "http://127.0.0.1:12345/ask" and item[1] == "Bearer secret" for item in seen)
    assert all(item[2]["tool_name"] == "mcp__lightroom_mcp__lr_set_develop" for item in seen)


def test_proxy_confirmation_with_actual_hub(monkeypatch):
    choice = [False]
    events = []

    def emit(event):
        events.append(event)
        if event["type"] == "confirm":
            hub.answer(event["id"], choice[0])

    hub = ConfirmHub(emit, timeout=2)
    hub.start()
    try:
        monkeypatch.setenv("LRAPP_PORT", str(hub.port))
        monkeypatch.setenv("LRAPP_TOKEN", hub.begin_turn())
        assert not codex_proxy._confirm("lr_set_develop", {"changes": {"Exposure": 0.1}})
        choice[0] = True
        assert codex_proxy._confirm("lr_set_develop", {"changes": {"Exposure": 0.1}})
        monkeypatch.setenv("LRAPP_TOKEN", "invalid")
        assert not codex_proxy._confirm("lr_set_develop", {})
        assert len([event for event in events if event["type"] == "confirm"]) == 2
    finally:
        hub.stop()
