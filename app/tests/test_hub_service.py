# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
import json
import threading
import urllib.request

import adjustments as adj
import confirm_hub as ch
import lr_launcher
from lr_service import LrService


# ---------------------------------------------------------------- 逐项确认（常驻会话）
def test_auto_allow_skips_card_for_write_tools_only():
    events = []
    hub = ch.ConfirmHub(events.append)
    hub.auto_allow = True
    assert hub.request("mcp__lightroom_mcp__lr_set_develop", {"changes": {"Exposure": 0.2}}) == {"allow": True, "message": ""}
    assert events == []                                                                 # 没有弹卡片
    hub.auto_allow = False
    hub.timeout = 0.2
    r = hub.request("mcp__lightroom_mcp__lr_set_develop", {"changes": {"Exposure": 0.2}})
    assert r["allow"] is False and any(e["type"] == "confirm" for e in events)           # 开关打开：弹卡片，超时即拒绝


def test_auto_allow_does_not_cover_other_tools():
    hub = ch.ConfirmHub(lambda e: None, timeout=0.2)
    hub.auto_allow = True
    assert hub.request("mcp__lightroom_mcp__lr_export", {})["allow"] is False


def test_session_token_survives_turns_and_pending_cleared():
    events = []
    hub = ch.ConfirmHub(events.append, timeout=5)
    port = hub.start()
    token = hub.begin_session()
    out = {}

    def ask():
        req = urllib.request.Request(f"http://127.0.0.1:{port}/ask", method="POST",
                                     data=json.dumps({"tool_name": "lr_set_develop", "input": {"changes": {"Exposure": 1}}}).encode(),
                                     headers={"Authorization": f"Bearer {token}"})
        out["r"] = json.loads(urllib.request.urlopen(req, timeout=10).read())

    t = threading.Thread(target=ask); t.start()
    for _ in range(50):
        if any(e["type"] == "confirm" for e in events):
            break
        threading.Event().wait(0.05)
    hub.finish_turn()                                                                    # 一轮结束：未应答的确认被取消，但口令仍有效
    t.join(5)
    assert out["r"]["allow"] is False
    assert hub._token == token
    hub.stop()


# ---------------------------------------------------------------- 本次调整：按照片打标记
def test_rows_tagged_with_photo_and_result_overrides(tmp_path):
    tr = adj.AdjustmentTracker(edit_dir=tmp_path)
    tr.current_photo = "P1"
    tr.observe({"type": "tool", "name": "lr_set_develop", "id": "T", "input": {"changes": {"Exposure": 0.2}}})
    assert tr.rows[0]["photo"] == "P1"
    res = json.dumps({"edit_id": "E1", "photo_id": "P9", "changes": [{"parameter": "Exposure", "before": 0, "after": 0.2, "ok": True}]})
    tr.observe({"type": "tool_result", "id": "T", "text": res})
    assert tr.rows[0]["photo"] == "P9" and tr.rows[0]["status"] == adj.STATUS_OK     # 以工具结果里的照片 id 为准
    assert tr.snapshot("P1") == [] and len(tr.snapshot("P9")) == 1 and len(tr.snapshot()) == 1


def test_explicit_photo_argument_wins():
    tr = adj.AdjustmentTracker()
    tr.current_photo = "P1"
    tr.observe({"type": "tool", "name": "lr_set_develop", "id": "T", "input": {"photo": "P5", "changes": {"Exposure": 1}}})
    assert tr.rows[0]["photo"] == "P5"


# ---------------------------------------------------------------- LrService（假 Bridge）
class FakeBridge:
    def __init__(self, connected=True, reply=None, boom=False):
        self.connected, self.reply, self.boom = connected, reply, boom
        self.plugin_version = "0.13.0"

    def call(self, cmd, params=None, timeout=30):
        if self.boom:
            raise RuntimeError("x")
        return self.reply


def test_selected_photo_reads_active():
    lr = LrService(bridge=FakeBridge(reply={"active_id": "P1", "photos": [{"id": "P1", "name": "A.ARW"}]}), edit_service=object())
    assert lr.selected_photo() == {"id": "P1", "name": "A.ARW"} and lr.plugin_version == "0.13.0"
    assert LrService(bridge=FakeBridge(reply={"count": 0, "photos": []}), edit_service=object()).selected_photo() == {"id": None, "name": None}
    assert LrService(bridge=FakeBridge(connected=False), edit_service=object()).selected_photo() is None
    assert LrService(bridge=FakeBridge(boom=True), edit_service=object()).selected_photo() is None


def test_wait_connected():
    lr = LrService(bridge=FakeBridge(connected=False), edit_service=object())
    assert lr.wait_connected(0.3) is False
    lr2 = LrService(bridge=FakeBridge(connected=True), edit_service=object())
    assert lr2.wait_connected(0.3) is True


# ---------------------------------------------------------------- 助手通道状态文件
def test_launcher_state_file_has_no_secrets(tmp_path):
    class B:
        port, connected, plugin_version, token = 58773, True, "0.13.0", "SECRET-TOKEN"

    p = tmp_path / "s.json"
    lr_launcher.write_state(p, B())
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["connected"] is True and data["port"] == 58773 and "SECRET" not in p.read_text(encoding="utf-8")


# ---------------------------------------------------------------- 借用助手通道（只剩一个新服务）
class RpcBridge:
    port, plugin_version, connected = 58773, "0.13.0", True

    def call(self, command, params=None, timeout=30.0):
        if command == "boom":
            from lightroom_mcp.bridge import BridgeTimeout
            raise BridgeTimeout("超时了")
        return {"echo": command, "params": params}


def make_remote(tmp_path, token="tok", alive=True):
    import time as _t
    srv = lr_launcher.start_rpc(RpcBridge(), "tok")
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"t": _t.time(), "connected": True, "rpc_port": srv.server_address[1],
                                 "plugin_version": "0.13.0"}), encoding="utf-8")
    from lr_service import RemoteBridge
    return srv, RemoteBridge(state, token, alive=lambda: alive)


def test_remote_bridge_roundtrip_and_errors(tmp_path):
    import pytest
    from lightroom_mcp.bridge import BridgeTimeout, PluginNotConnected
    srv, rb = make_remote(tmp_path)
    try:
        assert rb.connected and rb.plugin_version == "0.13.0"
        assert rb.call("list_selected", {"limit": 1}) == {"echo": "list_selected", "params": {"limit": 1}}
        with pytest.raises(BridgeTimeout):
            rb.call("boom")                                                  # 服务端异常类型原样还原，LrService 据此翻成中文
        srv2, bad = make_remote(tmp_path, token="wrong")
        with pytest.raises(Exception):
            bad.call("x")                                                    # 口令错误被拒绝
        srv2.shutdown()
        rb._alive = lambda: False
        assert not rb.connected
        with pytest.raises(PluginNotConnected):
            rb.call("x")
    finally:
        srv.shutdown()


def test_lrservice_remote_mode_has_no_own_bridge(tmp_path):
    srv, rb = make_remote(tmp_path)
    try:
        lr = LrService(state_file=tmp_path / "s.json", rpc_token="tok")
        assert lr.start() and lr.connected and lr.selected_photo() is not None
        hooks = []
        lr2 = LrService(state_file=tmp_path / "s.json", rpc_token="tok", restart_hook=lambda: hooks.append(1),
                        lr_running=lambda: True)                            # 1.1.1：Lightroom 在运行才重建
        lr2.start()
        assert lr2.restart() and hooks == [1]                                # 借用模式的“重新登记”=重建助手进程
        lr.stop()                                                            # 不会关掉别人的服务
    finally:
        srv.shutdown()
