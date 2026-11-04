# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
import json

from timing import TurnTimer


class FakeClock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


def test_stages_and_split():
    c = FakeClock()
    t = TurnTimer("per_turn", clock=c)
    c.t += 0.01; t.mark("spawn")
    c.t += 1.7; t.observe({"type": "session", "id": "S"})
    c.t += 1.0; t.observe({"type": "tool", "name": "lr_status", "id": "T1", "input": {"secret": "x"}})
    c.t += 0.05; t.observe({"type": "tool_result", "id": "T1", "text": "机密内容", "is_error": False})
    c.t += 2.0; t.observe({"type": "text", "text": "回答"}); t.observe({"type": "text", "text": "第二段"})
    c.t += 1.0; t.observe({"type": "done", "tokens": 1})
    s = t.summary()
    assert s["startup_ms"] == 1710.0 and s["marks"]["first_tool"] == 2710.0
    assert s["tools"] == [{"name": "lr_status", "ms": 50.0}]
    assert s["marks"]["first_text"] == 4760.0            # 只记第一次
    assert s["total_ms"] == 5760.0
    assert s["model_ms"] == round(5760.0 - 1710.0 - 50.0, 1)


def test_summary_has_no_content(tmp_path):
    c = FakeClock()
    t = TurnTimer("persistent", clock=c)
    t.observe({"type": "tool", "name": "lr_set_develop", "id": "A", "input": {"changes": {"exposure": 0.2}}})
    t.observe({"type": "tool_result", "id": "A", "text": "TOKEN-SECRET", "is_error": False})
    t.observe({"type": "text", "text": "TOKEN-SECRET"})
    p = tmp_path / "t.jsonl"
    t.write(p)
    text = p.read_text(encoding="utf-8")
    assert "SECRET" not in text and "exposure" not in text and "lr_set_develop" in text
    assert json.loads(text)["mode"] == "persistent"


def test_unknown_result_and_missing_init():
    t = TurnTimer("persistent", clock=FakeClock())
    t.observe({"type": "tool_result", "id": "nope", "text": ""})
    t.observe({"type": "done"})
    s = t.summary()
    assert "startup_ms" not in s and s["tools"][0]["name"] == "?"
