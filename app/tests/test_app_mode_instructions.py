# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""软件启动的 lightroom_mcp 带 LRMCP_APP_MODE=1；说明、系统提示只提软件开放的工具；Codex 代理转发服务端说明。"""
import re
import sys
from types import SimpleNamespace

import claude_bridge as cb
import codex_proxy

sys.path.insert(0, str(cb.REPO / "server"))
from lightroom_mcp import tools  # noqa: E402

OPEN = set(cb.READONLY_TOOLS + cb.ENABLED_WRITE_TOOLS)


def test_server_config_sets_app_mode():
    cfg = cb.lightroom_server_config()
    assert cfg["env"]["LRMCP_APP_MODE"] == "1"
    assert cb.lightroom_server_config(state_file=cb.WORKDIR / "s.json")["env"]["LRMCP_APP_MODE"] == "1"
    assert tools.APP_MODE_ENV in cb.APP_MODE_ENV


def test_app_instructions_and_system_prompt_only_name_open_tools():
    for text in (tools.INSTRUCTIONS_APP, tools.PLAN_DESCRIPTION_APP, tools.SET_DESCRIPTION_APP, cb.SYSTEM_PROMPT):
        assert set(re.findall(r"\blr_[a-z_]+", text)) <= OPEN
    assert "软件界面" in cb.SYSTEM_PROMPT


def test_codex_proxy_forwards_instructions():
    assert codex_proxy.server_instructions(SimpleNamespace(instructions="说明")) == "说明"
    assert codex_proxy.server_instructions(SimpleNamespace(instructions="  ")) is None
    assert codex_proxy.server_instructions(SimpleNamespace()) is None
