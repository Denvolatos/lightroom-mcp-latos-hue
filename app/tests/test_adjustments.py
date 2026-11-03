"""“本次调整”：事件解析、编辑记录读取、中文参数名、撤销调用（假 EditService）。"""
import json
import sys
from pathlib import Path

import adjustments as adj
import lr_service
from names import PARAM_NAMES, param_name

SET_INPUT = {"changes": {"Highlights2012": -35, "Exposure2012": 0.2}, "reason": "压低天空高光"}
SET_RESULT = json.dumps({
    "edit_id": "20261103-120000-ab12", "photo": "A.ARW", "verified": True,
    "changes": [
        {"parameter": "Highlights2012", "before": 0, "requested": -35, "after": -35, "ok": True},
        {"parameter": "Exposure2012", "before": 0, "requested": 0.2, "after": 0.1, "ok": False}]})


def tool_ev(name="lr_set_develop", tid="T1", inp=None):
    return {"type": "tool", "name": name, "id": tid, "input": inp if inp is not None else SET_INPUT}


def test_param_names():
    assert param_name("Highlights2012") == "高光" and param_name("Exposure2012") == "曝光"
    assert param_name("HueAdjustmentBlue") == "蓝色色相"
    assert param_name("SomethingUnknown") == "SomethingUnknown"      # 找不到显示原名


def test_every_server_parameter_has_chinese_name():
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "server"))
    from lightroom_mcp.edits import CURVE_KEYS, LIMITS
    missing = [k for k in list(LIMITS) + list(CURVE_KEYS) if k not in PARAM_NAMES]
    assert missing == []


def test_pending_then_applied(tmp_path):
    t = adj.AdjustmentTracker(confirm_on=True, edit_dir=tmp_path)
    t.observe({"type": "text", "text": "先压低高光。"})
    assert t.observe(tool_ev()) is True
    assert [r["status"] for r in t.rows] == ["待确认", "待确认"]
    assert t.rows[0]["label"] == "高光" and t.rows[0]["after"] == "-35" and t.rows[0]["reason"] == "压低天空高光"
    assert t.observe({"type": "tool_result", "id": "T1", "text": SET_RESULT, "is_error": False}) is True
    hl, ex = t.rows
    assert (hl["status"], hl["before"], hl["after"], hl["edit_id"]) == ("已应用", "0", "-35", "20261103-120000-ab12")
    assert ex["status"] == "失败" and ex["after"] == "0.1"           # ok=false 视为未达到预期


def test_running_status_when_confirm_off(tmp_path):
    t = adj.AdjustmentTracker(confirm_on=False, edit_dir=tmp_path)
    t.observe(tool_ev())
    assert t.rows[0]["status"] == "处理中"


def test_reason_falls_back_to_preceding_text(tmp_path):
    t = adj.AdjustmentTracker(edit_dir=tmp_path)
    t.observe({"type": "text", "text": "天空偏亮，"})
    t.observe({"type": "text", "text": "先降低高光。"})
    t.observe(tool_ev(inp={"changes": {"Highlights2012": -10}}))
    assert t.rows[0]["reason"] == "天空偏亮，先降低高光。"
    t.observe(tool_ev(tid="T2", inp={"changes": {"Tint": 1}}))             # 文字已被上一步消耗，没有则留空
    assert t.rows[1]["reason"] == ""


def test_denied_and_failed(tmp_path):
    t = adj.AdjustmentTracker(edit_dir=tmp_path)
    t.observe(tool_ev())
    t.observe({"type": "tool_result", "id": "T1", "text": "用户在界面中拒绝了该项调整，未执行。", "is_error": True})
    assert {r["status"] for r in t.rows} == {"已拒绝"}
    t.observe(tool_ev(tid="T2", inp={"changes": {"Tint": 1}}))
    t.observe({"type": "tool_result", "id": "T2", "text": "插件没有连上", "is_error": True})
    assert t.rows[-1]["status"] == "失败"
    t.observe(tool_ev(tid="T3", inp={"changes": {"Tint": 1}}))
    t.observe({"type": "tool_result", "id": "T3", "text": f"确认超过 {120} 秒未响应，已视为拒绝，未执行。", "is_error": True})
    assert t.rows[-1]["status"] == "已拒绝"
    t.observe(tool_ev(tid="T4", inp={"changes": {"Tint": 1}}))
    t.observe({"type": "tool_result", "id": "T4", "text": "未获用户确认，已视为拒绝，未执行。", "is_error": True})
    assert t.rows[-1]["status"] == "已拒绝"


def test_wrapped_result_text_is_unwrapped(tmp_path):
    t = adj.AdjustmentTracker(edit_dir=tmp_path)
    t.observe(tool_ev(inp={"changes": {"Highlights2012": -35}}))
    t.observe({"type": "tool_result", "id": "T1", "text": json.dumps({"result": SET_RESULT}), "is_error": False})
    assert t.rows[0]["status"] == "已应用"


def test_record_on_disk_fills_gaps(tmp_path):
    (tmp_path / "20261103-120000-ab12.json").write_text(json.dumps(
        {"edit_id": "20261103-120000-ab12", "reason": "记录里的依据", "before": {"Highlights2012": 5.0},
         "after": {"Highlights2012": -30.0}}), encoding="utf-8")
    t = adj.AdjustmentTracker(edit_dir=tmp_path)
    t.observe(tool_ev(inp={"changes": {"Highlights2012": -30}, "reason": ""}))
    t.observe({"type": "tool_result", "id": "T1", "text": json.dumps({"edit_id": "20261103-120000-ab12"}), "is_error": False})
    r = t.rows[0]
    assert (r["before"], r["after"], r["reason"]) == ("5", "-30", "记录里的依据")


def test_read_tools_do_not_create_rows(tmp_path):
    t = adj.AdjustmentTracker(edit_dir=tmp_path)
    assert t.observe(tool_ev("lr_status", "S1", {})) is False
    assert t.observe({"type": "tool_result", "id": "S1", "text": "{}", "is_error": False}) is False
    assert t.rows == []


def test_restore_result_marks_rows_undone(tmp_path):
    t = adj.AdjustmentTracker(edit_dir=tmp_path)
    t.observe(tool_ev())
    t.observe({"type": "tool_result", "id": "T1", "text": SET_RESULT, "is_error": False})
    t.observe(tool_ev("lr_restore", "R1", {"edit_id": "20261103-120000-ab12"}))
    t.observe({"type": "tool_result", "id": "R1", "text": json.dumps({"restored": "20261103-120000-ab12"}), "is_error": False})
    assert {r["status"] for r in t.rows} == {"已撤销"}


# ---------------------------------------------------------------- 撤销调用（假 Bridge / 假 EditService）
class FakeEdits:
    def __init__(self, error=None):
        self.calls, self.error = [], error

    def restore(self, edit_id, force=False):
        self.calls.append(("restore", edit_id, force))
        if self.error:
            raise self.error
        return {"restored": edit_id}

    def restore_original(self, photo="selected", dry_run=False, force=False):
        self.calls.append(("restore_original", photo, dry_run, force))
        if self.error:
            raise self.error
        return {"edits_undone": ["a", "b"]}


def test_undo_calls_restore_without_force_by_default():
    fake = FakeEdits()
    svc = lr_service.LrService(bridge=object(), edit_service=fake)
    r = svc.undo("E1")
    assert r["ok"] and fake.calls == [("restore", "E1", False)]          # 默认绝不 force
    assert svc.undo("E1", True)["ok"] and fake.calls[-1] == ("restore", "E1", True)


def test_undo_conflict_is_reported_not_forced():
    fake = FakeEdits(RuntimeError("这些参数在修改后又发生变化，直接还原会覆盖后续调整：Highlights2012"))
    r = lr_service.LrService(bridge=object(), edit_service=fake).undo("E1")
    assert r["ok"] is False and r["conflict"] is True and "Highlights2012" in r["message"]
    assert fake.calls == [("restore", "E1", False)]                      # 没有自动重试 force


def test_restore_original_never_dry_run_never_force_by_default():
    fake = FakeEdits()
    r = lr_service.LrService(bridge=object(), edit_service=fake).restore_original()
    assert r["ok"] and fake.calls == [("restore_original", "selected", False, False)]


def test_plugin_not_connected_message_is_plain():
    class PluginNotConnected(RuntimeError):
        pass
    r = lr_service.LrService(bridge=object(), edit_service=FakeEdits(PluginNotConnected("x"))).undo("E1")
    assert r["ok"] is False and r["conflict"] is False and "Lightroom" in r["message"] and "插件" in r["message"]


def test_mark_undone_in_tracker_after_service_success(tmp_path):
    t = adj.AdjustmentTracker(edit_dir=tmp_path)
    t.observe(tool_ev())
    t.observe({"type": "tool_result", "id": "T1", "text": SET_RESULT, "is_error": False})
    assert t.mark_undone({"20261103-120000-ab12"}) is True
    assert t.mark_undone({"20261103-120000-ab12"}) is False


def test_result_with_trailing_image_markers_still_parses(tmp_path):
    """真实调用里模型常带 preview=true，结果文字在 JSON 之后还有 [Image: ...] 标记（实测踩过）。"""
    t = adj.AdjustmentTracker(edit_dir=tmp_path)
    t.observe(tool_ev())
    text = SET_RESULT + "[Image: source: C:/x/a.jpg][Image: source: C:/x/b.jpg]"
    t.observe({"type": "tool_result", "id": "T1", "text": text, "is_error": False})
    assert t.rows[0]["status"] == "已应用" and t.rows[0]["edit_id"] == "20261103-120000-ab12"
