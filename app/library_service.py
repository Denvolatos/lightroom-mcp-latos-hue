"""预设 / 经验 / 收藏的后台逻辑（界面左栏三个标签）。

安全约定（与导出、挑片同一风格）：
- 写入 Lightroom 只发生在用户点击"确认套用"之后；确认清单的内容（新值）全部来自后端保存的预设和 Lightroom 当前读数，
  页面只能回传一个一次性的 token，不能改值、不能指定照片、不能传文件路径。
- 套用经 server 的 EditService.apply_settings（我的预设）/ apply_preset（Lightroom 预设）：改前存盘、一次可撤销、遵守只读开关。
- AI 没有任何写预设、写经验、写收藏的工具；"记成经验"只产生一份可编辑草稿，用户点"保存"才写入（note_save）。
- 文件路径只来自系统文件选择窗口（main.py 的 Api 调用），本模块只接收字节内容或把文本交给 Api 写盘。
"""
from __future__ import annotations

import json
import math
import re
import secrets
import threading
import time

import claude_bridge as cb
import library_store as ls
from adjustments import fmt_value
from names import param_name

MSG_NO_LR = "Lightroom 未连接。请确认 Lightroom 已打开且插件已启用。"
MSG_NO_PHOTO = "Lightroom 中没有选中照片。请先在 Lightroom 中选择一张照片。"
MSG_READONLY = "只读模式已开启，不允许修改照片。要套用，请先关闭只读模式。"
MSG_STALE = "确认清单已失效，请重新点击“套用到当前照片”。"
MSG_PHOTO_CHANGED = "Lightroom 中选中的照片已变化，请重新套用。"
MSG_BUSY = "助手正在处理其他请求，请稍候。"
RECORD_TIMEOUT = 120.0
RAW_SHOW = 1500
MAX_TEXT = 60000


# ---------------------------------------------------------------- 强度插值
def _near(a, b) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(abs(x - y) < 1e-3 for x, y in zip(a, b))
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) < 1e-3
    return a == b


def curve_at(flat: list[float], x: float) -> float:
    """分段线性读取曲线在 x 处的值。"""
    xs, ys = flat[0::2], flat[1::2]
    if x <= xs[0]:
        return ys[0]
    for i in range(1, len(xs)):
        if x <= xs[i]:
            t = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + (ys[i] - ys[i - 1]) * t
    return ys[-1]


def blend_curve(cur, target, s: float) -> list[float]:
    """曲线按强度混合：在预设曲线的各个 x 位置上，取 当前曲线(x)×(1−s) + 预设 y×s；结果沿用预设的 x 网格。
    s=1 时恰好等于预设曲线；s 在 (0,1) 时仍保持单调（两条单调曲线的加权平均仍单调）。"""
    xs, ys = target[0::2], target[1::2]
    out: list[float] = []
    for x, y in zip(xs, ys):
        out += [float(x), round(curve_at(cur, x) * (1 - s) + y * s, 2)]
    return out


def blend_hue(cur: float, target: float, s: float) -> float:
    """色相是环形（0–360）：沿较短的弧插值。"""
    d = ((target - cur + 180.0) % 360.0) - 180.0
    return (cur + d * s) % 360.0


def build_plan(current: dict, preset: dict, strength: int) -> dict:
    """由当前参数、预设参数与强度（1–100）算出要写入的值与确认清单。
    返回 {"values": {键: 新值}, "items": [{key,label,current,new,clipped,curve}], "skipped": [当前照片没有的键], "unchanged": 数量}。"""
    from lr_service import _import_server
    e, _ = _import_server()
    if isinstance(strength, bool) or not isinstance(strength, int) or not 1 <= strength <= 100:
        raise ls.LibraryError("强度需为 1 到 100 的整数。")
    s = strength / 100.0
    values, items, skipped, unchanged = {}, [], [], 0
    for key in sorted(preset):
        target = preset[key]
        if key not in current:
            skipped.append(key)
            continue
        cur = current[key]
        clipped = False
        if key == "WhiteBalance":
            if strength < 100:
                continue                       # 白平衡标签只在 100% 时套用；低强度只插值色温/色调数值
            new = target
        elif key in e.CURVE_KEYS:
            if not isinstance(cur, list) or len(cur) < 4 or len(cur) % 2:
                skipped.append(key)
                continue
            new = [float(v) for v in target] if strength == 100 else blend_curve(cur, target, s)
        else:
            if isinstance(cur, bool) or not isinstance(cur, (int, float)):
                skipped.append(key)
                continue
            if strength == 100:
                new = float(target)
            elif key in ls.HUE_KEYS:
                new = round(blend_hue(float(cur), float(target), s), 2)
            else:
                new = round(float(cur) + (float(target) - float(cur)) * s, 2)
            lo, hi, _ = e.LIMITS[key]
            if new < lo or new > hi:
                new, clipped = min(max(new, lo), hi), True
        if _near(cur, new):
            unchanged += 1
            continue
        values[key] = new
        items.append({"key": key, "label": "白平衡" if key == "WhiteBalance" else param_name(key), "current": fmt_value(cur), "new": fmt_value(new),
                      "clipped": clipped, "curve": isinstance(new, list)})
    return {"values": values, "items": items, "skipped": skipped, "unchanged": unchanged}


# ---------------------------------------------------------------- "记成经验"：提示词与解析
def build_record_prompt() -> str:
    return "\n".join([
        "任务：把本次对话中用户已确认并已成功应用的调整，总结为一条可以复用的调色经验。",
        "",
        "1. 不得调用任何会修改照片的工具，也不要向用户提问；如需核对实际写入的参数值，只可调用只读工具 lr_list_edits。",
        "2. 只总结用户已确认且实际应用的调整；不包含被拒绝、失败或已撤销的调整；不编造没有发生的内容。",
        "3. 正文用正式书面语，写明：画面情况、具体参数及数值（例如“高光 −20、饱和度 +10”）、调整依据、观察到的效果（没有观察到就不写效果）。",
        "",
        "输出格式（严格遵守）：只输出一个 JSON 代码块，代码块之外不要有其他文字：",
        "```json",
        '{"title":"标题","scene":"场景","tags":["标签"],"body":"正文"}',
        "```",
        f"要求：title 不超过 {ls.MAX_TITLE} 字；scene 不超过 {ls.MAX_SCENE} 字，可为空字符串；tags 最多 {ls.MAX_TAGS} 个，每个不超过 {ls.MAX_TAG} 字；"
        f"body 不超过 {ls.MAX_BODY} 字。四个字段都必须出现，不得有其他字段。",
    ])


def _find_note_json(text: str):
    text = (text or "")[:MAX_TEXT]
    cands = [m.group(1) for m in re.finditer(r"```[A-Za-z0-9_-]*[ \t]*\r?\n?(.*?)```", text, re.S)] + [text]
    for body in cands:
        i = body.find("{")
        while i >= 0:
            try:
                obj, _ = json.JSONDecoder().raw_decode(body, i)
                if isinstance(obj, dict) and ("title" in obj or "body" in obj):
                    return obj
            except ValueError:
                pass
            i = body.find("{", i + 1)
    return None


def parse_experience(texts) -> dict:
    """解析"记成经验"的回复。返回 {"ok": True, "draft": {...}} 或 {"ok": False, "message", "raw"}。不抛异常。
    不合规（缺字段、多字段、类型或长度不对）整体拒绝，不做猜测式修补。"""
    if isinstance(texts, str):
        texts = [texts]
    elif not isinstance(texts, (list, tuple)):
        texts = []
    best = ""
    for t in texts:
        t = t if isinstance(t, str) else ""
        best = best or t
        obj = _find_note_json(t)
        if obj is None:
            continue
        if set(obj) != {"title", "scene", "tags", "body"}:
            return {"ok": False, "message": "AI 返回的内容字段不符合要求（需要且仅需要 title、scene、tags、body）。", "raw": _raw(t)}
        try:
            f = ls.validate_note_fields({**obj, "use_in_chat": True})
        except ls.LibraryError as e:
            return {"ok": False, "message": f"AI 返回的内容不合规：{e}", "raw": _raw(t)}
        return {"ok": True, "draft": f}
    return {"ok": False, "message": "未能从 AI 的回复中得到结构化的经验草稿。", "raw": _raw(best)}


def _raw(text: str) -> str:
    t = (text or "").strip()
    return t[:RAW_SHOW] + ("…" if len(t) > RAW_SHOW else "")


class _Collector:
    def __init__(self):
        self.text, self.error, self.stopped, self.done = [], None, False, None

    def on_event(self, ev: dict) -> None:
        t = ev.get("type")
        if t == "text":
            self.text.append(str(ev.get("text", "")))
        elif t == "error":
            self.error = str(ev.get("message", ""))
        elif t == "stopped":
            self.stopped = True
        elif t == "done":
            self.done = ev


def _err_text(e: Exception) -> str:
    name, msg = type(e).__name__, str(e).strip()
    if name == "ReadOnlyError":
        return MSG_READONLY
    if name == "PluginNotConnected":
        return MSG_NO_LR
    if name == "BridgeTimeout":
        return "Lightroom 没有在时限内回复，结果不确定。请在 Lightroom 中检查这张照片，必要时在“本次调整”中撤销。"
    return msg or "操作失败。"


# ---------------------------------------------------------------- 服务
class LibraryService:
    """lr 需要：connected、readonly_error()、current_photo_settings()、apply_settings(...)、apply_lr_preset(...)、list_lr_presets(...)。
    on_applied(edit_id, photo_id, label, rows)：写入成功后通知"本次调整"表。
    send_fn / stop_fn / status_fn / ready_fn / acquire_fn / release_fn / has_adjustments：与 AI 挑片同一做法。"""

    def __init__(self, lr, presets: ls.PresetStore, notes: ls.NoteStore, favs: ls.FavStore, emit, *, on_applied=None, photo_fn=None,
                 send_fn=None, stop_fn=None, status_fn=None, ready_fn=None, acquire_fn=None, release_fn=None,
                 has_adjustments=None, record_timeout: float = RECORD_TIMEOUT):
        self.lr, self.presets, self.notes, self.favs, self.emit = lr, presets, notes, favs, emit
        self._on_applied = on_applied or (lambda *a, **k: None)
        self._photo = photo_fn or (lambda: None)
        self._send, self._stop_fn = send_fn, stop_fn or (lambda: None)
        self._status = status_fn or (lambda: {"available": True, "reason": "", "next_step": ""})
        self._ready = ready_fn or (lambda: (True, ""))
        self._acquire = acquire_fn or (lambda: True)
        self._release = release_fn or (lambda: None)
        self._has_adj = has_adjustments or (lambda: False)
        self.record_timeout = record_timeout
        self._lock = threading.Lock()
        self._pending: dict | None = None            # 套用确认清单
        self._pending_import: dict | None = None     # 等待"是否覆盖"的预设导入
        self._lr_cache: dict[str, dict] = {}         # 最近一次列出的 Lightroom 预设（id → 行）
        self.record_stage = "idle"                   # idle | running | done
        self.record_result: dict | None = None
        self._stopping = False
        self._timed_out = False
        self._timer = None

    # ---- 我的预设：列表 / 保存 / 管理 ------------------------------
    def save_options(self) -> dict:
        return {"groups": [{"id": g, "label": ls.GROUP_LABELS[g], "default": g in ls.DEFAULT_GROUPS} for g in ls.GROUPS],
                "limits": {"name": ls.MAX_NAME, "note": ls.MAX_NOTE}, "photo": self._photo()}

    def preset_list(self) -> dict:
        favs = {f["key"] for f in self.favs.list() if f["type"] == "preset"}
        rows = [{"id": p["id"], "name": p["name"], "note": p["note"], "groups": [ls.GROUP_LABELS[g] for g in p["groups"]],
                 "count": len(p["settings"]), "modified": p["modified"], "fav": p["name"] in favs} for p in self.presets.list()]
        return {"ok": True, "presets": rows, "max": ls.MAX_PRESETS}

    def _pick_settings(self, settings: dict, groups: list[str]) -> tuple[dict, int]:
        out, dropped = {}, 0
        for k, v in settings.items():
            if ls.group_of(k) not in groups:
                continue
            try:
                out.update(ls.validate_settings({k: v}))
            except ls.LibraryError:
                dropped += 1
        return out, dropped

    def preset_save(self, name, note, groups, overwrite: bool = False) -> dict:
        try:
            name = ls.clean_line(name, ls.MAX_NAME, "名称")
            note = ls.clean_block(note or "", ls.MAX_NOTE, "备注", required=False)
            groups = ls.clean_groups(groups)
            if self.presets.exists_name(name) and not overwrite:
                return {"ok": False, "exists": True, "message": f"已有名为“{name}”的预设。是否覆盖？"}
            if not self.lr.connected:
                return {"ok": False, "message": MSG_NO_LR}
            snap = self.lr.current_photo_settings()
            if snap is None:
                return {"ok": False, "message": MSG_NO_PHOTO}
            settings, dropped = self._pick_settings(snap["settings"], groups)
            if not settings:
                return {"ok": False, "message": "所选分组中没有可保存的参数。"}
            rec = self.presets.save(name, note, groups, settings, overwrite=bool(overwrite))
        except ls.LibraryError as e:
            return {"ok": False, "message": str(e)}
        except OSError as e:
            return {"ok": False, "message": f"保存失败：{e.strerror or e}"}
        return {"ok": True, "id": rec["id"], "name": rec["name"], "count": len(rec["settings"]), "dropped": dropped,
                "message": f"已保存预设“{rec['name']}”（{len(rec['settings'])} 项参数）。"}

    def preset_rename(self, pid, new_name) -> dict:
        try:
            old = self.presets.get(pid)
            new = self.presets.rename(pid, new_name)
            if new["name"] != old["name"]:
                self.favs.rename("preset", old["name"], new["name"])
        except ls.LibraryError as e:
            return {"ok": False, "message": str(e)}
        except OSError as e:
            return {"ok": False, "message": f"保存失败：{e.strerror or e}"}
        return {"ok": True, "id": new["id"]}

    def preset_set_note(self, pid, note) -> dict:
        try:
            self.presets.set_note(pid, note)
        except ls.LibraryError as e:
            return {"ok": False, "message": str(e)}
        return {"ok": True}

    def preset_delete(self, pid) -> dict:
        try:
            rec = self.presets.get(pid)
            self.presets.delete(pid)
            self.favs.remove("preset", rec["name"])
        except ls.LibraryError as e:
            return {"ok": False, "message": str(e)}
        except OSError as e:
            return {"ok": False, "message": f"删除失败：{e.strerror or e}"}
        return {"ok": True}

    def preset_export_text(self, pid) -> dict:
        try:
            obj = self.presets.export_obj(pid)
        except ls.LibraryError as e:
            return {"ok": False, "message": str(e)}
        return {"ok": True, "name": obj["name"], "text": json.dumps(obj, ensure_ascii=False, indent=1)}

    def preset_import_bytes(self, raw: bytes) -> dict:
        """导入一个预设文件的内容（字节由 Api 在用户选择文件后读出，已限制大小）。重名时返回 exists=True，等用户确认覆盖。"""
        try:
            parsed = ls.parse_preset_file(raw)
            if self.presets.exists_name(parsed["name"]):
                with self._lock:
                    self._pending_import = parsed
                return {"ok": False, "exists": True, "name": parsed["name"], "message": f"已有名为“{parsed['name']}”的预设。是否覆盖？"}
            return self._commit_import(parsed, False)
        except ls.LibraryError as e:
            return {"ok": False, "message": str(e)}

    def preset_import_commit(self, overwrite: bool) -> dict:
        with self._lock:
            parsed, self._pending_import = self._pending_import, None
        if parsed is None:
            return {"ok": False, "message": "没有待导入的预设。"}
        if not overwrite:
            return {"ok": False, "cancelled": True, "message": ""}
        return self._commit_import(parsed, True)

    def _commit_import(self, parsed: dict, overwrite: bool) -> dict:
        try:
            rec = self.presets.save(parsed["name"], parsed["note"], parsed["groups"], parsed["settings"], overwrite=overwrite)
        except ls.LibraryError as e:
            return {"ok": False, "message": str(e)}
        except OSError as e:
            return {"ok": False, "message": f"保存失败：{e.strerror or e}"}
        return {"ok": True, "name": rec["name"], "message": f"已导入预设“{rec['name']}”（{len(rec['settings'])} 项参数）。"}

    # ---- Lightroom 自带 / 用户预设（只读列表）----------------------
    def lr_presets(self, query: str = "") -> dict:
        if not self.lr.connected:
            return {"ok": False, "message": MSG_NO_LR}
        q = (query or "").strip() if isinstance(query, str) else ""
        word = q.split()[0] if q.split() else ""
        try:
            data = self.lr.list_lr_presets(word[:40], 50)
        except Exception as e:                  # noqa: BLE001
            return {"ok": False, "message": _err_text(e)}
        rows = [r for r in (data.get("presets") or []) if isinstance(r, dict) and isinstance(r.get("id"), str)]
        with self._lock:
            self._lr_cache = {r["id"]: r for r in rows}
        favs = {f["key"] for f in self.favs.list() if f["type"] == "lr_preset"}
        groups: dict[str, list] = {}
        for r in rows:
            folder = str(r.get("folder") or "（未分组）")[:80]
            key = f"{folder}/{str(r.get('name') or '')[:80]}"
            groups.setdefault(folder, []).append({"id": r["id"], "name": str(r.get("name") or "（未命名）")[:80], "masks": bool(r.get("has_masks") or r.get("masks")),
                                                  "key": key, "fav": key in favs})
        note = f"共 {data.get('total', len(rows))} 个预设，" + (f"匹配 {data.get('matched', len(rows))} 个，" if word else "") + f"显示 {len(rows)} 个。"
        if (data.get("matched") or 0) > len(rows) or (not word and (data.get("total") or 0) > len(rows)):
            note += "请输入关键词缩小范围。"
        return {"ok": True, "groups": [{"folder": k, "presets": v} for k, v in groups.items()], "note": note}

    # ---- 套用：确认清单 → 写入 -------------------------------------
    def apply_prepare(self, kind, ref, strength=100) -> dict:
        """生成确认清单（不写入）。kind="mine"：ref 是预设 id；kind="lr"：ref 是最近一次列表里的 Lightroom 预设 id。"""
        if kind not in ("mine", "lr"):
            return {"ok": False, "message": "套用类型无效。"}
        if not self.lr.connected:
            return {"ok": False, "message": MSG_NO_LR}
        ro = self.lr.readonly_error()
        if ro:
            return {"ok": False, "readonly": True, "message": MSG_READONLY}
        snap = self.lr.current_photo_settings()
        if snap is None:
            return {"ok": False, "message": MSG_NO_PHOTO}
        token = secrets.token_urlsafe(12)
        try:
            if kind == "mine":
                preset = self.presets.get(ref)
                plan = build_plan(snap["settings"], preset["settings"], strength)
                if not plan["values"]:
                    return {"ok": False, "nothing": True, "message": "当前照片已经是这个预设（在所选强度下）的状态，无需套用。"}
                pending = {"token": token, "kind": kind, "preset": preset["name"], "photo_id": snap["id"], "values": plan["values"],
                           "strength": strength}
                out = {"ok": True, "token": token, "kind": kind, "title": f"套用预设“{preset['name']}”（强度 {strength}%）",
                       "photo": snap.get("name"), "items": plan["items"], "skipped": [param_name(k) for k in plan["skipped"]],
                       "clipped": sum(1 for i in plan["items"] if i["clipped"]), "unchanged": plan["unchanged"]}
            else:
                with self._lock:
                    row = self._lr_cache.get(ref) if isinstance(ref, str) else None
                if row is None:
                    return {"ok": False, "message": "该预设不在当前列表中，请重新搜索后再选择。"}
                if row.get("has_masks") or row.get("masks"):
                    return {"ok": False, "message": "该预设包含蒙版（局部调整），无法套用。请选择不带蒙版的预设。"}
                if snap.get("has_local_adjustments"):
                    return {"ok": False, "message": "当前照片已有蒙版（局部调整），套用 Lightroom 预设可能影响它们且无法安全还原，已取消。"}
                name = str(row.get("name") or "")
                pending = {"token": token, "kind": kind, "preset": name, "photo_id": snap["id"], "lr_id": ref}
                out = {"ok": True, "token": token, "kind": kind, "title": f"套用 Lightroom 预设“{name}”", "photo": snap.get("name"),
                       "items": [], "note": f"将套用 Lightroom 预设“{name}”。预设可能一次改动许多参数；改前会保存这张照片的完整快照，可在“本次调整”中撤销。"}
        except ls.LibraryError as e:
            return {"ok": False, "message": str(e)}
        with self._lock:
            self._pending = pending
        return out

    def apply_cancel(self) -> dict:
        with self._lock:
            self._pending = None
        return {"ok": True}

    def apply_confirm(self, token) -> dict:
        with self._lock:
            p = self._pending
            if p is None or not isinstance(token, str) or not secrets.compare_digest(token, p["token"]):
                return {"ok": False, "message": MSG_STALE}
            self._pending = None
        if not self.lr.connected:
            return {"ok": False, "message": MSG_NO_LR}
        if self.lr.readonly_error():
            return {"ok": False, "readonly": True, "message": MSG_READONLY}
        cur = self._photo() or {}
        if cur.get("id") and cur["id"] != p["photo_id"]:
            return {"ok": False, "message": MSG_PHOTO_CHANGED}
        label = f"预设“{p['preset']}”" + (f" {p['strength']}%" if p["kind"] == "mine" else "")
        try:
            if p["kind"] == "mine":
                res = self.lr.apply_settings(p["values"], f"套用我的预设：{p['preset']}（强度 {p['strength']}%）", label, p["photo_id"])
            else:
                res = self.lr.apply_lr_preset(p["lr_id"], f"套用 Lightroom 预设：{p['preset']}", p["photo_id"])
        except Exception as e:                  # noqa: BLE001
            uncertain = type(e).__name__ == "BridgeTimeout"
            return {"ok": False, "uncertain": uncertain, "message": _err_text(e)}
        if not res.get("edit_id"):
            return {"ok": True, "edit_id": None, "changed": 0, "message": res.get("note") or "没有做任何改动。"}
        rows = [{"key": c.get("parameter"), "before": c.get("before"), "after": c.get("after")} for c in (res.get("changes") or [])
                if isinstance(c, dict) and c.get("parameter")]
        for k in res.get("curves_changed") or []:
            rows.append({"key": k, "before": None, "after": None})
        try:
            self._on_applied(res["edit_id"], p["photo_id"], label, rows)
        except Exception:                       # noqa: BLE001 - 通知表格失败不影响已完成的写入
            pass
        return {"ok": True, "edit_id": res["edit_id"], "changed": res.get("settings_changed", len(rows)), "verified": bool(res.get("verified", True)),
                "message": f"已套用{label}，共改动 {res.get('settings_changed', len(rows))} 项。可在“本次调整”中撤销。"}

    # ---- 经验 ------------------------------------------------------
    def notes_state(self, query: str = "", tag: str = "") -> dict:
        favs = {f["key"] for f in self.favs.list() if f["type"] == "note"}
        rows = [{**n, "fav": n["id"] in favs} for n in self.notes.list(query, tag)]
        ctx = ls.build_context(self.notes.list())
        return {"ok": True, "notes": rows, "tags": self.notes.all_tags(), "max": ls.MAX_NOTES,
                "context": {"used": ctx["used"], "eligible": ctx["eligible"], "truncated": ctx["truncated"]}}

    def note_save(self, nid, fields) -> dict:
        try:
            n = self.notes.update(nid, fields) if nid else self.notes.add(fields)
        except ls.LibraryError as e:
            return {"ok": False, "message": str(e)}
        except OSError as e:
            return {"ok": False, "message": f"保存失败：{e.strerror or e}"}
        return {"ok": True, "id": n["id"]}

    def note_delete(self, nid) -> dict:
        try:
            self.notes.delete(nid)
            self.favs.remove("note", nid)
        except ls.LibraryError as e:
            return {"ok": False, "message": str(e)}
        except OSError as e:
            return {"ok": False, "message": f"删除失败：{e.strerror or e}"}
        return {"ok": True}

    def notes_export_text(self) -> dict:
        obj = self.notes.export_obj()
        if not obj["notes"]:
            return {"ok": False, "message": "经验库是空的，没有可导出的内容。"}
        return {"ok": True, "text": json.dumps(obj, ensure_ascii=False, indent=1), "count": len(obj["notes"])}

    def notes_import_bytes(self, raw: bytes) -> dict:
        try:
            n = self.notes.import_obj(raw)
        except ls.LibraryError as e:
            return {"ok": False, "message": str(e)}
        except OSError as e:
            return {"ok": False, "message": f"保存失败：{e.strerror or e}"}
        return {"ok": True, "count": n, "message": f"已导入 {n} 条经验。"}

    def context_block(self) -> dict:
        """新对话开始时要放进上下文的资料块（调用方先看设置里的开关）。"""
        return ls.build_context(self.notes.list())

    # ---- 记成经验 --------------------------------------------------
    def record_available(self) -> bool:
        return bool(self._has_adj())

    def record_start(self) -> dict:
        with self._lock:
            if self.record_stage == "running":
                return {"ok": False, "message": "正在生成草稿，请稍候。"}
        if not self._has_adj():
            return {"ok": False, "message": "本次对话中还没有已应用的调整，没有可记录的做法。"}
        st = self._status()
        if not st.get("available", True):
            return {"ok": False, "message": (st.get("reason") or "AI 来源不可用。") + (" " + st["next_step"] if st.get("next_step") else "")}
        if self._send is None or not self._acquire():
            return {"ok": False, "message": MSG_BUSY}
        with self._lock:
            self.record_stage, self.record_result = "running", None
            self._stopping = self._timed_out = False
        threading.Thread(target=self._record_run, daemon=True).start()
        return {"ok": True, "message": ""}

    def _on_timeout(self) -> None:
        self._timed_out = True
        try:
            self._stop_fn()
        except Exception:                       # noqa: BLE001
            pass

    def _record_run(self) -> None:
        t0 = time.monotonic()
        col = _Collector()
        try:
            ok, why = self._ready()
            if not ok:
                res = {"ok": False, "message": why or MSG_NO_LR, "raw": ""}
            else:
                self._timer = threading.Timer(self.record_timeout, self._on_timeout)
                self._timer.daemon = True
                self._timer.start()
                try:
                    self._send(build_record_prompt(), col.on_event)
                finally:
                    self._timer.cancel()
                res = self._record_finish(col)
        except Exception as e:                  # noqa: BLE001
            res = {"ok": False, "message": f"程序发生错误：{e}", "raw": ""}
        finally:
            try:
                self._release()
            except Exception:                   # noqa: BLE001
                pass
        d = col.done or {}
        res.update(elapsed=round(time.monotonic() - t0, 1), tokens=d.get("tokens"), cost=d.get("cost"))
        with self._lock:
            self.record_stage, self.record_result = "done", res
        self.emit({"type": "record_done", **res})

    def _record_finish(self, col: _Collector) -> dict:
        if self._timed_out or col.error == cb.MSG_TIMEOUT:
            return {"ok": False, "message": f"等待超过 {int(self.record_timeout)} 秒仍无结果，已停止。", "raw": ""}
        if self._stopping or col.stopped:
            return {"ok": False, "message": "已停止。", "raw": ""}
        d = col.done or {}
        final, streamed = str(d.get("text") or ""), "".join(col.text)
        if (col.error or d.get("is_error")) and not (final or streamed).strip():
            return {"ok": False, "message": col.error or "AI 来源未返回结果，请稍后重试。", "raw": ""}
        return parse_experience([final, streamed])

    def record_stop(self) -> dict:
        with self._lock:
            running = self.record_stage == "running"
            if running:
                self._stopping = True
        if running:
            try:
                self._stop_fn()
            except Exception:                   # noqa: BLE001
                pass
        return {"ok": True}

    def record_state(self) -> dict:
        with self._lock:
            return {"stage": self.record_stage, "result": dict(self.record_result) if self.record_result else None}

    def record_close(self) -> dict:
        with self._lock:
            if self.record_stage == "done":
                self.record_stage, self.record_result = "idle", None
        return {"ok": True}

    # ---- 收藏 ------------------------------------------------------
    def fav_toggle(self, typ, key, label="") -> dict:
        """收藏/取消收藏。我的预设、Lightroom 预设、经验必须真实存在；照片由 Api 传入当前选中照片的 id 与名称。"""
        try:
            if typ == "preset":
                if not any(p["name"] == key for p in self.presets.list()):
                    return {"ok": False, "message": "找不到这个预设。"}
            elif typ == "note":
                self.notes.get(key)
            elif typ == "lr_preset":
                if not isinstance(key, str) or not key.strip():
                    return {"ok": False, "message": "收藏项无效。"}
            elif typ == "photo":
                if not isinstance(key, str) or not key:
                    return {"ok": False, "message": MSG_NO_PHOTO}
            else:
                return {"ok": False, "message": "收藏类型无效。"}
            r = self.favs.toggle(typ, key, label)
        except ls.LibraryError as e:
            return {"ok": False, "message": str(e)}
        except OSError as e:
            return {"ok": False, "message": f"保存失败：{e.strerror or e}"}
        return {"ok": True, **r}

    def fav_state(self) -> dict:
        """收藏列表，按类型分组。标注每项是否仍然存在（预设/经验被删时已随之移除；Lightroom 预设与照片无法在本机核对）。"""
        items = self.favs.list()
        presets = {p["name"]: p for p in self.presets.list()}
        notes = {n["id"]: n for n in self.notes.list()}
        groups = {"preset": [], "lr_preset": [], "note": [], "photo": []}
        for f in items:
            if f["type"] == "preset":
                p = presets.get(f["key"])
                if p:
                    groups["preset"].append({**f, "preset_id": p["id"]})
            elif f["type"] == "note":
                n = notes.get(f["key"])
                if n:
                    groups["note"].append({**f, "label": n["title"]})
            else:
                groups[f["type"]].append(f)
        photo = self._photo() or {}
        return {"ok": True, "groups": groups, "total": sum(len(v) for v in groups.values()), "max": ls.MAX_FAVORITES,
                "photo_fav": bool(photo.get("id")) and any(f["type"] == "photo" and f["key"] == photo.get("id") for f in items)}
