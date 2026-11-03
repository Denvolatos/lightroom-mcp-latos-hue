"""“本次调整”表格的数据：从 claude 的事件流里读出每次写入的参数、改前、改后、状态、依据。

事件来源：tool（含输入参数）与 tool_result（含 edit_id 与改前改后）；必要时用 ~/LrMcp/edits/ 里的记录补全。
"""
from __future__ import annotations

import json
from pathlib import Path

from names import param_name

STATUS_PENDING = "待确认"
STATUS_RUNNING = "处理中"
STATUS_OK = "已应用"
STATUS_FAILED = "失败"
STATUS_DENIED = "已拒绝"
STATUS_UNDONE = "已撤销"

EDIT_DIR = Path.home() / "LrMcp" / "edits"
SET_TOOL = "lr_set_develop"


def fmt_value(v) -> str:
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return format(float(v), ".4g")
    if isinstance(v, list):
        return "曲线(" + str(len(v) // 2) + " 点)"
    return "—" if v is None else str(v)


def load_record(edit_id: str, directory: Path = EDIT_DIR) -> dict | None:
    try:
        return json.loads((directory / f"{edit_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _result_json(text: str) -> dict | None:
    """工具结果可能是纯 JSON，也可能在 JSON 之后带有“[Image: ...]”等附加文字（预览图），所以只解析开头的 JSON 对象。"""
    try:
        start = (text or "").index("{")
        data, _ = json.JSONDecoder().raw_decode(text[start:])
        if isinstance(data, dict) and set(data) == {"result"} and isinstance(data["result"], str):
            data = _result_json(data["result"])      # 个别客户端会把文本再包一层 {"result": "..."}
    except (TypeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class AdjustmentTracker:
    def __init__(self, confirm_on: bool = True, edit_dir: Path = EDIT_DIR):
        self.confirm_on = confirm_on
        self.edit_dir = edit_dir
        self.rows: list[dict] = []
        self.current_photo: str | None = None   # 当前选中照片的 id（由窗口定期读取），用来给新行打标记
        self._calls: dict[str, dict] = {}     # tool_use_id -> {"name","row_ids"}
        self._text = ""                       # 上一次工具调用之后 AI 说的文字

    def reset(self) -> None:
        self.rows, self._calls, self._text = [], {}, ""

    # ---- 事件入口 --------------------------------------------------
    def observe(self, ev: dict) -> bool:
        """处理一个事件，表格有变化时返回 True。"""
        t = ev.get("type")
        if t == "text":
            self._text += ev.get("text", "")
            return False
        if t == "tool":
            changed = self._on_tool(ev)
            self._text = ""
            return changed
        if t == "tool_result":
            return self._on_result(ev)
        return False

    def _on_tool(self, ev: dict) -> bool:
        name, tid = ev.get("name", ""), ev.get("id") or ""
        if name != SET_TOOL:
            self._calls[tid] = {"name": name, "row_ids": []}
            return False
        inp = ev.get("input") or {}
        reason = str(inp.get("reason") or "").strip() or self._text.strip()[:120]
        ids = []
        target = inp.get("photo")
        photo = self.current_photo if target in (None, "", "selected") else target
        for key, to in (inp.get("changes") or {}).items():
            rid = f"{tid}:{key}"
            ids.append(rid)
            self.rows.append({"rid": rid, "edit_id": None, "key": key, "label": param_name(key),
                              "before": "—", "after": fmt_value(to), "reason": reason, "photo": photo,
                              "status": STATUS_PENDING if self.confirm_on else STATUS_RUNNING})
        self._calls[tid] = {"name": name, "row_ids": ids}
        return bool(ids)

    def _row(self, rid: str) -> dict | None:
        return next((r for r in self.rows if r["rid"] == rid), None)

    def _on_result(self, ev: dict) -> bool:
        call = self._calls.get(ev.get("id") or "")
        if not call:
            return False
        name, text = call["name"], ev.get("text", "")
        if name == SET_TOOL:
            return self._on_set_result(call, ev, text)
        if name in ("lr_restore", "lr_restore_original") and not ev.get("is_error"):
            return self._on_restore_result(text)
        return False

    def _on_set_result(self, call: dict, ev: dict, text: str) -> bool:
        data = _result_json(text)
        if ev.get("is_error") or not data or "edit_id" not in data:
            denied = ("拒绝" in text and "用户" in text) or "视为拒绝" in text or "已被停止" in text or "denied" in text.lower()
            status = STATUS_DENIED if denied else STATUS_FAILED
            for rid in call["row_ids"]:
                r = self._row(rid)
                if r:
                    r["status"], r["note"] = status, text[:200]
            return True
        by_key = {c.get("parameter"): c for c in data.get("changes", [])}
        record = load_record(data["edit_id"], self.edit_dir) or {}
        for rid in call["row_ids"]:
            r = self._row(rid)
            if not r:
                continue
            c = by_key.get(r["key"], {})
            before = c.get("before", record.get("before", {}).get(r["key"]))
            after = c.get("after", record.get("after", {}).get(r["key"]))
            r["edit_id"] = data["edit_id"]
            r["photo"] = data.get("photo_id") or record.get("photo_id") or r.get("photo")
            r["before"] = fmt_value(before)
            r["after"] = fmt_value(after if after is not None else c.get("requested"))
            r["status"] = STATUS_OK if c.get("ok", True) else STATUS_FAILED
            if not r["reason"]:
                r["reason"] = str(record.get("reason") or "")[:120]
        return True

    def _on_restore_result(self, text: str) -> bool:
        data = _result_json(text) or {}
        undone = set(data.get("edits_undone") or [])
        if data.get("restored"):
            undone.add(data["restored"])
        return self.mark_undone(undone)

    def add_external(self, edit_id: str, photo: str | None, label: str, changes: list[dict]) -> None:
        """软件自己写入的调整（套用预设）也显示在"本次调整"里，可逐条撤销。changes: [{key, before, after}]。"""
        for c in changes:
            key = c.get("key")
            self.rows.append({"rid": f"lib:{edit_id}:{key}", "edit_id": edit_id, "key": key, "label": param_name(key),
                              "before": fmt_value(c.get("before")), "after": fmt_value(c.get("after")),
                              "reason": f"套用{label}", "photo": photo, "status": STATUS_OK})

    def mark_undone(self, edit_ids) -> bool:
        changed = False
        for r in self.rows:
            if r["edit_id"] in edit_ids and r["status"] != STATUS_UNDONE:
                r["status"], changed = STATUS_UNDONE, True
        return changed

    def mark_all_undone(self) -> bool:
        changed = False
        for r in self.rows:
            if r["status"] == STATUS_OK:
                r["status"], changed = STATUS_UNDONE, True
        return changed

    def snapshot(self, photo: str | None = None) -> list[dict]:
        """photo 给定时只返回这张照片的行（照片未知的行也显示，避免漏掉进行中的调整）；换照片时表格不会混入上一张的记录。"""
        return [dict(r) for r in self.rows if photo is None or r.get("photo") in (None, photo)]
