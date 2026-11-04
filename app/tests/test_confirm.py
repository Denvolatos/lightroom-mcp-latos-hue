# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""逐项确认：确认卡片内容、允许/拒绝/超时/取消、口令校验、permission_server 的返回格式。全部用假数据，不碰 Lightroom。"""
import json
import threading
import urllib.error
import urllib.request

import confirm_hub as ch
import permission_server as ps


def make_hub(timeout=5, current=None):
    events = []
    hub = ch.ConfirmHub(events.append, timeout=timeout, current_values=current)
    hub.start()
    return hub, events


def ask(hub, token, tool="mcp__lightroom_mcp__lr_set_develop", inp=None):
    inp = inp or {"changes": {"Highlights2012": -35}, "reason": "天空高光过亮"}
    req = urllib.request.Request(
        f"http://127.0.0.1:{hub.port}/ask", method="POST",
        data=json.dumps({"tool_name": tool, "input": inp, "tool_use_id": "T1"}).encode("utf-8"),
        headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def answer_when_card_appears(hub, events, allow):
    def run():
        for _ in range(200):
            cards = [e for e in events if e["type"] == "confirm"]
            if cards:
                hub.answer(cards[0]["id"], allow)
                return
            threading.Event().wait(0.02)
    threading.Thread(target=run, daemon=True).start()


def test_card_content_with_current_values():
    card = ch.describe_request("mcp__lightroom_mcp__lr_set_develop",
                               {"changes": {"Highlights2012": -35}, "reason": "依据"}, {"Highlights2012": 0.0})
    assert card["title"] == "拟调整" and card["reason"] == "依据"
    assert card["items"] == [{"key": "Highlights2012", "label": "高光", "from": "0", "to": "-35"}]
    assert ch.describe_request("lr_set_develop", {"changes": {"Tint": 3}})["items"][0]["from"] == "—"
    assert "强制" in ch.describe_request("lr_restore", {"edit_id": "x", "force": True})["reason"]
    assert ch.describe_request("lr_restore_original", {})["kind"] == "restore_original"


def test_allow():
    hub, events = make_hub(current=lambda keys: {"Highlights2012": 0.0})
    tok = hub.begin_turn()
    answer_when_card_appears(hub, events, True)
    r = ask(hub, tok)
    assert r["allow"] is True
    card = [e for e in events if e["type"] == "confirm"][0]
    assert card["items"][0]["from"] == "0" and card["items"][0]["to"] == "-35"
    assert [e for e in events if e["type"] == "confirm_done"][0]["allow"] is True
    hub.stop()


def test_deny():
    hub, events = make_hub()
    tok = hub.begin_turn()
    answer_when_card_appears(hub, events, False)
    r = ask(hub, tok)
    assert r["allow"] is False and r["message"] == ch.MSG_DENIED
    hub.stop()


def test_timeout_counts_as_deny():
    hub, events = make_hub(timeout=0.3)
    tok = hub.begin_turn()
    r = ask(hub, tok)
    assert r["allow"] is False and r["message"] == ch.MSG_TIMEOUT
    assert ch.TIMEOUT_SECONDS == 120
    hub.stop()


def test_cancel_all_denies_pending():
    hub, events = make_hub()
    tok = hub.begin_turn()

    def cancel():
        for _ in range(200):
            if any(e["type"] == "confirm" for e in events):
                hub.cancel_all()
                return
            threading.Event().wait(0.02)
    threading.Thread(target=cancel, daemon=True).start()
    r = ask(hub, tok)
    assert r["allow"] is False and r["message"] == ch.MSG_CANCELLED
    hub.stop()


def test_wrong_or_expired_token_rejected():
    hub, events = make_hub()
    tok = hub.begin_turn()
    try:
        ask(hub, "wrong")
        assert False, "应被拒绝"
    except urllib.error.HTTPError as e:
        assert e.code == 401
    hub.end_turn()
    try:
        ask(hub, tok)       # 本轮结束后口令作废
        assert False, "应被拒绝"
    except urllib.error.HTTPError as e:
        assert e.code == 401
    assert not [e for e in events if e["type"] == "confirm"]
    hub.stop()


def test_answer_unknown_id():
    hub, _ = make_hub()
    assert hub.answer("nope", True) is False
    hub.stop()


def test_decision_json_format():
    inp = {"changes": {"Tint": 1}}
    allow = json.loads(ps.decision_json({"allow": True}, inp))
    assert allow == {"behavior": "allow", "updatedInput": inp}
    deny = json.loads(ps.decision_json({"allow": False, "message": "拒绝"}, inp))
    assert deny == {"behavior": "deny", "message": "拒绝"}
    assert json.loads(ps.decision_json({}, inp))["behavior"] == "deny"      # 缺字段默认拒绝


def test_permission_server_denies_when_window_unreachable(monkeypatch):
    monkeypatch.delenv("LRAPP_PORT", raising=False)
    assert ps.ask_window("t", {})["allow"] is False
    monkeypatch.setenv("LRAPP_PORT", "1")          # 无人监听
    monkeypatch.setenv("LRAPP_TOKEN", "x")
    r = ps.ask_window("t", {})
    assert r["allow"] is False and "拒绝" in r["message"]


def test_permission_server_end_to_end_with_hub(monkeypatch):
    hub, events = make_hub()
    tok = hub.begin_turn()
    monkeypatch.setenv("LRAPP_PORT", str(hub.port))
    monkeypatch.setenv("LRAPP_TOKEN", tok)
    answer_when_card_appears(hub, events, True)
    assert ps.ask_window("lr_set_develop", {"changes": {"Tint": 2}}, "T9")["allow"] is True
    hub.stop()
