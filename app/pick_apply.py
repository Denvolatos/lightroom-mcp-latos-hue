# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""把 AI 挑片的建议写进 Lightroom（只在用户点击确认清单后才执行）。

约定：
- 只改星级（rating）与旗标（flag）；不传关键词、标题、说明等其他字段（lr.set_rating_flag 只接收这两项）。
- 清单内容（照片、原值、新值）来自后端保存的挑片结果和 Lightroom 当前读取的值；页面只能回传"勾选了哪些 photo_id"，
  不能改新值，也不能加入不在清单里的照片。
- 写入前后各查一次只读开关，开着则整体拒绝。逐张写入、逐张记录；改前旧值由 server 的 EditService 存盘，可还原。
- 撤销用 server 的 restore（遵守还原冲突保护，默认不强制）；本阶段不受"逐项确认"开关影响（用户点确认清单即许可）。
"""
from __future__ import annotations

import threading

FLAG_LABEL = {"pick": "留用", "none": "无旗标", "reject": "排除"}
MSG_READONLY = "只读模式已开启，不允许修改照片。要写入星级和旗标，请先关闭只读模式。"
MSG_NO_LR = "Lightroom 未连接。请确认 Lightroom 已打开且插件已启用。"
MSG_NOTHING = "没有可写入的建议。请先完成一次 AI 挑片。"
MSG_CONFLICT = "这张照片的星级或旗标在写入之后又被改动过，直接还原会覆盖这些改动。"
UNDO_REASON = "AI 挑片（用户确认）"


def rating_text(r) -> str:
    return "无星级" if not r else f"{int(r)} 星"


def _norm_rating(v) -> int:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0


class ApplyService:
    """lr 需要：connected、readonly_error()、metadata_of(id)、set_rating_flag(id, rating, flag, reason)、latest_meta_edit(id)、undo(edit_id, force)。
    get_ranking()：返回挑片结果里通过校验的排名条目（服务端副本）。"""

    def __init__(self, lr, get_ranking, emit):
        self.lr, self.get_ranking, self.emit = lr, get_ranking, emit
        self._lock = threading.Lock()
        self.stage = "idle"            # idle | confirm | writing | done
        self.items: list[dict] = []    # 确认清单
        self.results: list[dict] = []
        self.summary: dict | None = None

    # ---- 确认清单 --------------------------------------------------
    def prepare(self) -> dict:
        """生成确认清单：每张照片的原星级/旗标 → 新星级/旗标（原值此刻从 Lightroom 读取）。"""
        with self._lock:
            if self.stage == "writing":
                return {"ok": False, "message": "正在写入，请等待完成。"}
        ranking = self.get_ranking()
        if not ranking:
            return {"ok": False, "message": MSG_NOTHING}
        if not self.lr.connected:
            return {"ok": False, "message": MSG_NO_LR}
        ro = self.lr.readonly_error()
        if ro:
            return {"ok": False, "readonly": True, "message": MSG_READONLY}
        items = []
        for r in ranking:
            it = {"photo_id": r["photo_id"], "name": r.get("name"), "rank": r.get("rank"),
                  "new_rating": r["stars"], "new_flag": r["flag"], "error": ""}
            try:
                meta = (self.lr.metadata_of(r["photo_id"]) or {}).get("metadata") or {}
                it["old_rating"], it["old_flag"] = _norm_rating(meta.get("rating")), meta.get("flag") or "none"
            except Exception as e:                    # noqa: BLE001
                it["old_rating"], it["old_flag"] = None, None
                it["error"] = "无法读取这张照片当前的星级和旗标：" + (str(e) or type(e).__name__)
            it["changed"] = (not it["error"]) and (it["old_rating"] != it["new_rating"] or it["old_flag"] != it["new_flag"])
            items.append(it)
        with self._lock:
            self.items = items
            self.stage = "confirm"
            self.results, self.summary = [], None
        return {"ok": True, "items": [self._public_item(i) for i in items]}

    @staticmethod
    def _public_item(i: dict) -> dict:
        return {"photo_id": i["photo_id"], "name": i["name"], "rank": i.get("rank"),
                "old_rating": i["old_rating"], "old_flag": i["old_flag"], "new_rating": i["new_rating"], "new_flag": i["new_flag"],
                "changed": i["changed"], "error": i["error"],
                "old_text": f"{rating_text(i['old_rating'])} / {FLAG_LABEL.get(i['old_flag'], '—')}" if i["old_rating"] is not None else "—",
                "new_text": f"{rating_text(i['new_rating'])} / {FLAG_LABEL.get(i['new_flag'], '—')}"}

    def cancel(self) -> dict:
        with self._lock:
            if self.stage == "confirm":
                self.stage, self.items = "idle", []
        return {"ok": True}

    # ---- 写入 ------------------------------------------------------
    def confirm(self, photo_ids) -> dict:
        """用户点"确认写入"。photo_ids：勾选的照片 id；只接受确认清单里"有变化"的照片。"""
        if not isinstance(photo_ids, list) or not all(isinstance(x, str) for x in photo_ids):
            return {"ok": False, "message": "勾选内容无效。"}
        with self._lock:
            if self.stage != "confirm":
                return {"ok": False, "message": "确认清单已失效，请重新点击“应用建议的星级和旗标”。"}
            by_id = {i["photo_id"]: i for i in self.items}
            chosen = list(dict.fromkeys(photo_ids))
            bad = [p for p in chosen if p not in by_id or not by_id[p]["changed"]]
            if bad:
                return {"ok": False, "message": "勾选内容不在确认清单内，已拒绝。"}
            if not chosen:
                return {"ok": False, "message": "请至少勾选一张照片。"}
            todo = [dict(by_id[i["photo_id"]]) for i in self.items if i["photo_id"] in chosen]
        if not self.lr.connected:
            return {"ok": False, "message": MSG_NO_LR}
        if self.lr.readonly_error():
            return {"ok": False, "readonly": True, "message": MSG_READONLY}
        with self._lock:
            self.stage = "writing"
            self.results, self.summary = [], None
        self.emit({"type": "pick_apply_progress", "i": 0, "n": len(todo), "name": ""})
        threading.Thread(target=self._write_all, args=(todo,), daemon=True).start()
        return {"ok": True, "message": ""}

    def _write_all(self, todo: list[dict]) -> None:
        results: list[dict] = []
        abort = ""
        for idx, it in enumerate(todo):
            row = {"photo_id": it["photo_id"], "name": it["name"], "old_rating": it["old_rating"], "old_flag": it["old_flag"],
                   "new_rating": it["new_rating"], "new_flag": it["new_flag"], "edit_id": None, "undone": False}
            if abort:
                results.append({**row, "status": "failed", "message": abort})
                continue
            self.emit({"type": "pick_apply_progress", "i": idx, "n": len(todo), "name": it["name"] or ""})
            rating = it["new_rating"] if it["new_rating"] != it["old_rating"] else None
            flag = it["new_flag"] if it["new_flag"] != it["old_flag"] else None
            try:
                data = self.lr.set_rating_flag(it["photo_id"], rating, flag, UNDO_REASON) or {}
                row["edit_id"] = data.get("edit_id")
                if data.get("verified") is False:
                    row.update(status="uncertain", message="已发出写入，但未能核对结果。请在 Lightroom 中确认这张照片的星级和旗标。")
                else:
                    row.update(status="ok", message="")
            except Exception as e:                  # noqa: BLE001
                name = type(e).__name__
                msg = str(e).strip()
                if name == "ReadOnlyError":
                    row.update(status="failed", message=MSG_READONLY)
                    abort = "只读模式已开启，未写入。"
                elif name == "PluginNotConnected":
                    row.update(status="failed", message="Lightroom 插件未连接，未写入。")
                    abort = "Lightroom 插件未连接，未写入。"
                elif name == "BridgeTimeout":
                    row.update(status="uncertain", message="Lightroom 没有在时限内回复，不确定是否已写入。请在 Lightroom 中确认这张照片的星级和旗标。",
                               edit_id=self._safe_latest(it["photo_id"]))
                else:
                    row.update(status="failed", message=msg or "写入失败。")
            results.append(row)
        counts = {k: sum(1 for r in results if r["status"] == k) for k in ("ok", "failed", "uncertain")}
        with self._lock:
            self.stage = "done"
            self.results = results
            self.summary = {"n": len(results), **counts}
        self.emit({"type": "pick_apply_done", **self.state_public()})

    def _safe_latest(self, photo_id: str):
        try:
            return self.lr.latest_meta_edit(photo_id)
        except Exception:
            return None

    # ---- 撤销 ------------------------------------------------------
    def undo(self, force: bool = False) -> dict:
        """撤销这次写入：对本次每条有记录的写入逐张还原（server 的 restore；默认不强制，遇到"之后又改过"会提示冲突）。"""
        with self._lock:
            if self.stage != "done":
                return {"ok": False, "message": "没有可撤销的写入。"}
            targets = [r for r in self.results if r.get("edit_id") and r["status"] in ("ok", "uncertain") and not r["undone"]]
        if not targets:
            return {"ok": False, "message": "没有可撤销的写入。"}
        out, conflicts = [], 0
        for r in targets:
            res = self.lr.undo(r["edit_id"], bool(force))
            if res.get("ok"):
                r["undone"] = True
                out.append({"photo_id": r["photo_id"], "name": r["name"], "status": "undone", "message": ""})
            else:
                conflicts += 1 if res.get("conflict") else 0
                msg = MSG_CONFLICT if res.get("conflict") else res.get("message", "")
                out.append({"photo_id": r["photo_id"], "name": r["name"], "status": "conflict" if res.get("conflict") else "failed",
                            "message": msg})
        ok_n = sum(1 for o in out if o["status"] == "undone")
        return {"ok": ok_n == len(out), "partial": 0 < ok_n < len(out), "conflict": conflicts > 0, "results": out,
                "message": "" if ok_n == len(out) else "部分照片未能还原，详见下方。"}

    # ---- 状态 ------------------------------------------------------
    def state_public(self) -> dict:
        with self._lock:
            return {"stage": self.stage, "summary": self.summary,
                    "results": [{k: v for k, v in r.items() if k != "edit_id"} | {"has_edit": bool(r.get("edit_id"))} for r in self.results]}

    def close(self) -> dict:
        with self._lock:
            if self.stage in ("done", "confirm"):
                self.stage, self.items, self.results, self.summary = "idle", [], [], None
        return {"ok": True}
