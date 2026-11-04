# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
import json
from pathlib import Path

import claude_bridge as cb


def make_cmd(session=None, tmp=Path(".")):
    return cb.build_command("你好", tmp / "mcp.json", session, "claude")


def test_command_has_required_flags():
    cmd = make_cmd()
    for flag in ["-p", "--strict-mcp-config", "--mcp-config", "--setting-sources", "--disable-slash-commands",
                 "--tools", "--system-prompt", "--allowedTools", "--permission-mode", "--disallowedTools"]:
        assert flag in cmd, flag
    assert cmd[cmd.index("--output-format") + 1] == "stream-json" and "--verbose" in cmd
    assert cmd[cmd.index("--tools") + 1] == ""          # 内置工具全关
    assert cmd[cmd.index("--setting-sources") + 1] == ""


def test_never_bare():
    assert "--bare" not in make_cmd()


def split_allowed(cmd):
    return cmd[cmd.index("--allowedTools") + 1: cmd.index("--disallowedTools")]


def split_disallowed(cmd):
    i = cmd.index("--disallowedTools") + 1
    out = []
    while i < len(cmd) and not cmd[i].startswith("--"):
        out.append(cmd[i])
        i += 1
    return out


def test_confirm_on_writes_go_through_permission_tool():
    cmd = cb.build_command("x", Path("m.json"), None, "claude", confirm=True)
    allowed = split_allowed(cmd)
    assert allowed and all(a.startswith("mcp__lightroom_mcp__lr_") for a in allowed)
    for w in cb.ENABLED_WRITE_TOOLS:                  # 写入类不在放行清单里，必须经确认
        assert f"mcp__lightroom_mcp__{w}" not in allowed
    assert cmd[cmd.index("--permission-mode") + 1] == "default"
    assert cmd[cmd.index("--permission-prompt-tool") + 1] == "mcp__lrapp_confirm__approve"


def test_confirm_off_writes_allowed_directly():
    cmd = cb.build_command("x", Path("m.json"), None, "claude", confirm=False)
    allowed = split_allowed(cmd)
    for w in cb.ENABLED_WRITE_TOOLS:
        assert f"mcp__lightroom_mcp__{w}" in allowed
    assert cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    assert "--permission-prompt-tool" not in cmd


def test_other_writes_always_hidden():
    for confirm in (True, False):
        cmd = cb.build_command("x", Path("m.json"), None, "claude", confirm=confirm)
        blocked = split_disallowed(cmd)
        assert cb.ENABLED_WRITE_TOOLS == ["lr_set_develop", "lr_restore", "lr_restore_original"]
        for w in cb.WRITE_TOOLS:
            full = f"mcp__lightroom_mcp__{w}"
            if w in cb.ENABLED_WRITE_TOOLS:
                assert full not in blocked
            else:
                assert full in blocked and full not in split_allowed(cmd)
    assert set(cb.READONLY_TOOLS).isdisjoint(cb.WRITE_TOOLS)


def test_mcp_config_confirm_server_uses_env_placeholders(tmp_path):
    data = json.loads(cb.write_mcp_config(tmp_path, confirm=True).read_text(encoding="utf-8"))
    assert set(data["mcpServers"]) == {"lightroom_mcp", "lrapp_confirm"}
    env = data["mcpServers"]["lrapp_confirm"]["env"]
    assert env == {"LRAPP_PORT": "${LRAPP_PORT}", "LRAPP_TOKEN": "${LRAPP_TOKEN}"}   # 口令不落盘
    off = json.loads(cb.write_mcp_config(tmp_path, confirm=False).read_text(encoding="utf-8"))
    assert list(off["mcpServers"]) == ["lightroom_mcp"]


def test_readonly_list_matches_server_annotations():
    """以 server/lightroom_mcp/tools.py 的 READ_ONLY 标注为准，避免两边不一致。"""
    import re
    src = (Path(__file__).resolve().parents[2] / "server" / "lightroom_mcp" / "tools.py").read_text(encoding="utf-8")
    pairs = re.findall(r"@mcp\.tool\(annotations=(\w+)[^\n]*\)\n(?:\s*@[^\n]*\n)*\s*def (lr_\w+)", src)
    ro = {n for a, n in pairs if a == "READ_ONLY"}
    wr = {n for a, n in pairs if a != "READ_ONLY"}
    assert ro == set(cb.READONLY_TOOLS)
    assert wr == set(cb.WRITE_TOOLS)
    assert set(cb.ENABLED_WRITE_TOOLS) <= wr


def test_resume_only_when_session():
    assert "--resume" not in make_cmd()
    cmd = make_cmd("abc-123")
    assert cmd[cmd.index("--resume") + 1] == "abc-123"


def test_mcp_config_has_no_secrets(tmp_path):
    p = cb.write_mcp_config(tmp_path)
    assert "key" not in p.read_text(encoding="utf-8").lower()


def line(**o):
    return json.dumps(o, ensure_ascii=False)


def test_parse_session_text_tool_done():
    st = {}
    assert cb.parse_line(line(type="system", subtype="init", session_id="S1"), st) == [{"type": "session", "id": "S1"}]
    ev = cb.parse_line(line(type="stream_event", event={"type": "content_block_delta",
                                                          "delta": {"type": "text_delta", "text": "你好"}}), st)
    assert ev == [{"type": "text", "text": "你好"}]
    ev = cb.parse_line(line(type="assistant", message={"content": [
        {"type": "text", "text": "你好"},
        {"type": "tool_use", "name": "mcp__lightroom_mcp__lr_status", "input": {}}]}), st)
    assert [e["type"] for e in ev] == ["tool"]            # 文字已流式输出过，不重复
    assert ev[0]["name"] == "lr_status" and "Lightroom" in ev[0]["label"]
    assert ev[0]["input"] == {} and "id" in ev[0]
    ev = cb.parse_line(line(type="result", is_error=False, result="好", session_id="S1", total_cost_usd=0.04,
                            usage={"input_tokens": 2, "cache_creation_input_tokens": 100,
                                   "cache_read_input_tokens": 10, "output_tokens": 4}), st)
    assert ev[-1]["type"] == "done" and ev[-1]["tokens"] == 116 and ev[-1]["cost"] == 0.04


def test_assistant_text_without_streaming():
    ev = cb.parse_line(line(type="assistant", message={"content": [{"type": "text", "text": "整段"}]}), {})
    assert ev == [{"type": "text", "text": "整段"}]


def test_garbage_and_blank_lines_ignored():
    assert cb.parse_line("") == [] and cb.parse_line("not json") == []


def test_error_result_is_friendly():
    ev = cb.parse_line(line(type="result", is_error=True, result="Not logged in · Please run /login", usage={}), {})
    assert ev[0]["type"] == "error" and "/login" in ev[0]["message"] and "终端" in ev[0]["message"]
    assert ev[-1]["type"] == "done" and ev[-1]["is_error"]


def test_friendly_errors_in_chinese():
    assert "尚未登录" in cb.friendly_error("Not logged in")
    assert "额度" in cb.friendly_error("5-hour usage limit reached")
    assert "网络" in cb.friendly_error("getaddrinfo ENOTFOUND")
    assert "发生错误" in cb.friendly_error("weird")
    assert "claude" in cb.MSG_NO_CLAUDE and "180" in cb.MSG_TIMEOUT


def test_missing_claude_gives_chinese_message(monkeypatch):
    monkeypatch.setattr(cb, "find_claude", lambda: None)
    out = []
    cb.ClaudeSession().send("hi", out.append)
    assert out[0] == {"type": "error", "message": cb.MSG_NO_CLAUDE}
    assert out[-1]["type"] == "done" and out[-1]["is_error"]


def test_timeout_gives_chinese_message(monkeypatch, tmp_path):
    import sys
    monkeypatch.setattr(cb, "find_claude", lambda: "claude")
    monkeypatch.setattr(cb, "build_command", lambda *a, **k: [sys.executable, "-c", "import time; time.sleep(30)"])
    monkeypatch.setattr(cb, "TIMEOUT_SECONDS", 1)
    out = []
    cb.ClaudeSession(tmp_path).send("hi", out.append)
    assert any(e["type"] == "error" and e["message"] == cb.MSG_TIMEOUT for e in out)
    assert out[-1]["type"] == "done"


def test_parse_tool_result():
    ev = cb.parse_line(line(type="user", message={"content": [
        {"type": "tool_result", "tool_use_id": "T1", "content": [{"type": "text", "text": "结果"}], "is_error": True}]}), {})
    assert ev == [{"type": "tool_result", "id": "T1", "text": "结果", "is_error": True}]
    ev = cb.parse_line(line(type="user", message={"content": [
        {"type": "tool_result", "tool_use_id": "T2", "content": "纯文本"}]}), {})
    assert ev[0]["text"] == "纯文本" and ev[0]["is_error"] is False


def test_system_prompt_is_formal():
    for word in ("哈", "呢", "吧", "！", "你好", "大白话"):
        assert word not in cb.SYSTEM_PROMPT
    assert "正式" in cb.SYSTEM_PROMPT and "reason" in cb.SYSTEM_PROMPT
