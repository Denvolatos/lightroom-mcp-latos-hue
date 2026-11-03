"""修图助手：打开界面，对话框接到本机已登录的 Claude Code 命令行，可查看并调整照片（支持逐项确认与撤销）。

运行：python app/main.py
"""
import json
import os
import secrets
import sys
import threading
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adjustments import AdjustmentTracker  # noqa: E402
from backend import Backend  # noqa: E402
from confirm_hub import ConfirmHub  # noqa: E402
from lr_service import LrService  # noqa: E402
from providers import available_providers, create_provider, is_selectable  # noqa: E402
import settings as appsettings  # noqa: E402
from import_service import ImportService  # noqa: E402
from export_service import ExportService  # noqa: E402
from pick_service import PickService  # noqa: E402
from pick_apply import ApplyService  # noqa: E402
import library_store as libstore  # noqa: E402
from library_service import LibraryService  # noqa: E402
from preview import PreviewManager, PreviewServer, PreviewStore  # noqa: E402
from photo_library import PhotoLibrary, ThumbStore  # noqa: E402
from ports import STATE_DIR  # noqa: E402

WEB = Path(__file__).resolve().parent / "web" / "index.html"


class Api:
    """页面里用 window.pywebview.api.send(text, confirm) / stop() / reset() / answer(id, allow) /
    undo(edit_id, force) / restore_original(force) / status() 调用。

    注意：pywebview 会把公开属性都当成可调用接口扫描，所以内部状态一律用下划线开头。
    """

    def __init__(self) -> None:
        self._window = None
        # Claude 使用常驻会话；Codex 每轮启动 CLI，由窗口自己的 Bridge 保持 Lightroom 连接。
        self._preferred_persistent = os.environ.get("LRAPP_PER_TURN") != "1"
        self._busy = False
        self._lock = threading.Lock()
        self._tracker = AdjustmentTracker()
        self._rpc_token = secrets.token_urlsafe(24)
        self._settings = appsettings.SettingsStore()
        self._persistent = self._preferred_persistent and self._settings.data["provider"] == "claude"
        state_file = STATE_DIR / "claude_side.json" if self._persistent else None
        # AI 来源经注册表取得；切换来源在下一次“新对话”时生效
        self._provider = create_provider(self._settings.data["provider"], state_file=state_file,
                                         persistent=self._persistent)
        self._state_file = state_file
        self._session = self._provider           # 兼容旧名：Backend / LrService 只用 alive、busy、restart 等
        # 常驻模式：窗口不单独起 Bridge，借用助手里那个服务的通道（Lightroom 插件同时轮询 3 个以上服务会变慢，见 DEV_NOTES）
        self._lr = (LrService(state_file=state_file, rpc_token=self._rpc_token, alive=lambda: self._session.alive,
                              restart_hook=lambda: not self._session.busy and self._session.restart())
                    if self._persistent else LrService())
        self._hub = ConfirmHub(self._emit, current_values=self._lr.current_values)
        self._hub.start()
        self._preview = PreviewManager(self._lr, PreviewServer(PreviewStore()), self._emit)
        self._preview.set_edge(self._settings.data["preview_edge"])
        self._backend = Backend(self._lr, self._session, self._tracker, self._emit, state_file=None, previews=self._preview)
        self._import = ImportService(self._settings, self._lr, self._emit)
        # 软件内的图库（0.11.0）：缩略图走单独的本机图片服务（只服务缓存里的图、带随机口令）
        self._photolib = PhotoLibrary(self._settings, self._lr, self._emit, PreviewServer(ThumbStore()),
                                      on_selected=self._photolib_selected,
                                      busy_fn=lambda: self._import.stage in ("scanning", "copying"))
        self._export = ExportService(self._settings, self._lr, self._emit)
        self._pick = PickService(self._lr, self._preview.server, self._emit, send_fn=self._pick_send, stop_fn=self._pick_stop,
                                 status_fn=lambda: self._provider.status(), ready_fn=lambda: self._backend.wait_ready(),
                                 acquire_fn=self._pick_acquire, release_fn=self._pick_release)
        self._apply = ApplyService(self._lr, self._pick.ranking, self._emit)
        self._ctx_pending = True                 # 新对话的第一条消息带上"经验库"资料块（见 send / reset）
        self._lib = LibraryService(self._lr, libstore.PresetStore(), libstore.NoteStore(), libstore.FavStore(), self._emit,
                                   on_applied=self._lib_applied, photo_fn=lambda: self._backend.photo,
                                   send_fn=self._pick_send, stop_fn=self._pick_stop, status_fn=lambda: self._provider.status(),
                                   ready_fn=lambda: self._backend.wait_ready(), acquire_fn=self._pick_acquire,
                                   release_fn=self._pick_release,
                                   has_adjustments=lambda: any(r.get("status") == "已应用" for r in self._tracker.rows))

    def _start_background(self) -> None:
        """窗口一出现就预热：Bridge、常驻 claude（含 lightroom_mcp 与确认服务）同时启动，之后每条消息零启动开销。"""
        def warm() -> None:
            self._lr.start()
        threading.Thread(target=warm, daemon=True).start()
        if self._persistent:
            token = self._hub.begin_session()
            self._provider.start({"LRAPP_PORT": str(self._hub.port), "LRAPP_TOKEN": token,
                                  "LRAPP_RPC_TOKEN": self._rpc_token})
        self._preview.server.start()
        self._preview.start()
        self._photolib.server.start()
        self._photolib.start()
        self._photolib.refresh()                # 软件启动时读一次图库（之后只在导入完成、加入完成、手动刷新时读）
        self._backend.start()

    def _provider_env(self) -> dict:
        token = self._hub.begin_session()
        return {"LRAPP_PORT": str(self._hub.port), "LRAPP_TOKEN": token, "LRAPP_RPC_TOKEN": self._rpc_token}

    def _apply_provider_choice(self) -> bool:
        """“新对话”时，若设置里的 AI 来源与当前不同，换成新来源并启动。返回是否已换（换了就不必再 reset）。"""
        want = self._settings.data["provider"]
        if want == self._provider.id or not is_selectable(want):
            return False
        next_persistent = (self._preferred_persistent and want == "claude") if want in ("claude", "codex") else self._persistent
        old = self._provider
        mode_changed = next_persistent != self._persistent
        if mode_changed:
            self._backend.stop()
            self._preview.stop()
            self._lr.stop()
            self._persistent = next_persistent
            self._state_file = STATE_DIR / "claude_side.json" if self._persistent else None
        self._provider = create_provider(want, state_file=self._state_file, persistent=self._persistent)
        self._session = self._provider
        old.close()
        if mode_changed:
            self._lr = (LrService(state_file=self._state_file, rpc_token=self._rpc_token,
                                  alive=lambda: self._session.alive,
                                  restart_hook=lambda: not self._session.busy and self._session.restart())
                        if self._persistent else LrService())
            self._hub.current_values = self._lr.current_values
            self._preview = PreviewManager(self._lr, PreviewServer(PreviewStore()), self._emit)
            self._preview.set_edge(self._settings.data["preview_edge"])
            self._backend = Backend(self._lr, self._session, self._tracker, self._emit,
                                    state_file=None, previews=self._preview)
            self._import.lr = self._lr
            self._export.lr = self._lr
            threading.Thread(target=self._lr.start, daemon=True).start()
            self._preview.server.start()
            self._preview.start()
            self._backend.start()
        else:
            self._backend.session = self._provider
        if self._persistent:
            self._provider.start(self._provider_env())
        return True

    def _shutdown(self) -> None:
        self._backend.stop()
        self._preview.stop()
        self._photolib.stop()
        self._photolib.server.stop()
        self._provider.close()
        self._hub.stop()
        self._lr.stop()

    def _tap(self, ev: dict) -> None:
        """软件内部事件联动图库：Lightroom 选区变化 -> 高亮；导入完成 -> 刷新图库；AI 挑片写入 -> 刷新星级与旗标。"""
        lib = getattr(self, "_photolib", None)
        if lib is None:
            return
        t = ev.get("type")
        if t == "selection":
            lib.on_lr_selection(ev)
        elif t == "import_done":
            lib.refresh()
        elif t == "pick_apply_done":
            ids = [r.get("photo_id") for r in ev.get("results") or [] if isinstance(r, dict)]
            threading.Thread(target=lib.refresh_meta, args=(ids,), daemon=True).start()

    def _emit(self, ev: dict) -> None:
        try:
            self._tap(ev)
        except Exception:                        # noqa: BLE001 - 联动出错不影响原有事件
            pass
        if self._window is None:
            return
        try:
            self._window.evaluate_js(
                f"window.onClaudeEvent && window.onClaudeEvent({json.dumps(ev, ensure_ascii=False)})")
        except Exception:
            pass  # 窗口已关闭

    def _on_event(self, ev: dict) -> None:
        """AI 来源的事件：先更新“本次调整”数据，再推给页面。"""
        with self._lock:
            changed = self._tracker.observe(ev)
            rows = self._backend.rows() if changed else None
        self._emit(ev)
        if rows is not None:
            self._emit({"type": "adjust", "rows": rows})
            self._preview.request()          # 调整/撤销/还原有变化：短防抖后刷新“当前”预览
            self._thumbs_stale()

    def _lib_applied(self, edit_id: str, photo_id: str, label: str, changes: list) -> None:
        """软件自己套用预设成功后：把改动加进"本次调整"表，并刷新预览。"""
        with self._lock:
            self._tracker.add_external(edit_id, photo_id, label, changes)
        self._push_rows()
        self._preview.request()
        self._thumbs_stale(photo_id)

    def _thumbs_stale(self, *photo_ids) -> None:
        """照片被调整/撤销/还原：图库里这些照片的缩略图缓存失效并重新取（涉及本次调整表里的照片和当前照片）。"""
        ids = set(i for i in photo_ids if i)
        ids |= {r.get("photo") for r in self._tracker.rows if r.get("photo")}
        cur = (self._backend.photo or {}).get("id")
        if cur:
            ids.add(cur)
        self._photolib.invalidate_thumbs(ids)

    def _photolib_selected(self) -> None:
        """在图库里选中照片后立即刷新“当前照片”（中栏预览、右栏本次调整等），不等 3 秒轮询。"""
        self._backend.refresh_photo()
        self._preview.request(0)

    def _push_rows(self) -> None:
        with self._lock:
            rows = self._backend.rows()
        self._emit({"type": "adjust", "rows": rows})

    def send(self, text: str, confirm: bool = True) -> dict:
        if self._busy:
            return {"ok": False, "message": "上一条请求仍在处理，请稍候。"}
        text = (text or "").strip()
        if not text:
            return {"ok": False, "message": "请输入内容。"}
        self._busy = True
        confirm = bool(confirm)
        self._tracker.confirm_on = confirm

        self._hub.auto_allow = not confirm          # 逐项确认关：写入类工具由确认服务自动放行（进程参数不变）

        def run() -> None:
            try:
                ok, why = self._backend.wait_ready()
                if not ok:
                    self._emit({"type": "error", "message": why})
                    self._emit({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
                    return
                text_out = self._with_notes(text)
                if self._persistent:
                    self._provider.send(text_out, self._on_event)
                else:
                    token = self._hub.begin_turn()
                    env = {"LRAPP_PORT": str(self._hub.port), "LRAPP_TOKEN": token}
                    self._provider.send(text_out, self._on_event, confirm=confirm, extra_env=env)
            except Exception as e:  # 兜底：不让后台线程悄悄死掉
                self._emit({"type": "error", "message": f"程序发生错误：{e}"})
                self._emit({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
            finally:
                if self._persistent:
                    self._hub.finish_turn()
                else:
                    self._hub.end_turn()
                self._busy = False

        threading.Thread(target=run, daemon=True).start()
        return {"ok": True}

    def _with_notes(self, text: str) -> str:
        """新对话的第一条消息：设置里开着"让 AI 参考我的经验库"时，在前面放一段明确标为"资料而非指令"的经验块。
        只在新对话开始时放一次；AI 的工具权限不因此改变（权限由进程参数决定，见 claude_bridge）。"""
        if not self._ctx_pending:
            return text
        self._ctx_pending = False
        if not self._settings.data.get("ai_use_notes", True):
            return text
        try:
            ctx = self._lib.context_block()
        except Exception:                        # noqa: BLE001 - 经验库出问题不影响对话
            return text
        if not ctx["text"]:
            return text
        self._emit({"type": "notes_context", "used": ctx["used"], "eligible": ctx["eligible"], "truncated": ctx["truncated"]})
        return ctx["text"] + "\n\n用户的请求：\n" + text

    def stop(self) -> dict:
        self._hub.cancel_all()
        self._provider.stop()
        return {"ok": True}

    def reset(self) -> dict:
        self._hub.cancel_all()
        self._ctx_pending = True
        if not self._apply_provider_choice():
            self._provider.reset()
        with self._lock:
            self._tracker.reset()
        self._push_rows()
        return {"ok": True}

    def answer(self, cid: str, allow: bool) -> dict:
        return {"ok": self._hub.answer(cid, bool(allow))}

    def status(self) -> dict:
        """真实连接状态（窗口 Bridge + 助手通道），顶栏据此显示“已连接/正在连接/未连接”。"""
        st = self._backend.status()
        st["photo"] = self._backend.photo
        return st

    def undo(self, edit_id: str, force: bool = False) -> dict:
        r = self._lr.undo(edit_id, bool(force))
        if r["ok"]:
            with self._lock:
                self._tracker.mark_undone({edit_id})
            self._push_rows()
            self._preview.request()
            self._thumbs_stale()
        return {"ok": r["ok"], "conflict": r["conflict"], "message": r["message"]}

    def restore_original(self, force: bool = False) -> dict:
        r = self._lr.restore_original(bool(force))
        if r["ok"]:
            undone = set((r.get("result") or {}).get("edits_undone") or [])
            with self._lock:
                self._tracker.mark_undone(undone)
            self._push_rows()
            self._preview.request()
            self._thumbs_stale()
        return {"ok": r["ok"], "conflict": r["conflict"], "message": r["message"]}

    # ---- 设置 ------------------------------------------------------
    def get_settings(self, include_status: bool = True) -> dict:
        """当前设置、AI 来源列表（含状态）、关于信息。include_status=False（启动时）不做登录检测，只取设置值。"""
        cur = self._provider.status() if include_status else {"available": True, "state": "unknown", "reason": "", "next_step": ""}
        return {"settings": dict(self._settings.data),
                "providers": available_providers(cur if self._provider.id == "claude" or not include_status else None,
                                                 cur if self._provider.id == "codex" or not include_status else None),
                "current_provider": self._provider.id, "edges": list(appsettings.EDGE_CHOICES),
                "default_base_folder": appsettings.default_base_folder(), "about": self._about()}

    def _about(self) -> dict:
        lr_ver = None
        try:
            if self._lr.connected and getattr(self._lr, "_bridge", None) is not None:
                lr_ver = str(self._lr._bridge.call("status", timeout=3).get("lightroom_version") or "") or None
        except Exception:
            lr_ver = None
        return {"app_version": appsettings.APP_VERSION, "lightroom_version": lr_ver,
                "plugin_version": getattr(self._lr, "plugin_version", None), "data_dir": appsettings.DATA_DIR_TEXT,
                "project_url": appsettings.PROJECT_URL}

    def check_folder(self, path: str) -> dict:
        return appsettings.validate_folder(path)

    def choose_folder(self, start: str = "") -> dict:
        """弹出系统的文件夹选择对话框，返回 {"ok", "path"}；取消则 ok=False。"""
        if self._window is None:
            return {"ok": False, "path": ""}
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        init = start if start and os.path.isdir(start) else ""
        try:
            res = self._window.create_file_dialog(kind, directory=init)
        except Exception:
            res = None
        return {"ok": bool(res), "path": str(res[0]) if res else ""}

    def save_settings(self, changes: dict, create_missing: bool = False) -> dict:
        """保存设置。逐项确认默认值、预览清晰度立即生效；AI 来源在下一次新对话生效；文件夹仅保存（导入功能后续使用）。"""
        if not isinstance(changes, dict):
            return {"ok": False, "errors": {"_": "设置内容无效。"}, "needs_create": False}
        r = self._settings.update(changes, selectable=is_selectable, create_missing=bool(create_missing))
        if r["ok"] and "preview_edge" in changes:
            self._preview.set_edge(r["settings"]["preview_edge"])
        return r

    # ---- 导入 ------------------------------------------------------
    def choose_source_folder(self) -> dict:
        """点“导入”：先检查（只读开关等），再弹出系统文件夹对话框，选定后在后台扫描。路径只来自这次点击，不接受页面传入的路径。"""
        b = self._import.begin()
        if not b["ok"]:
            return b
        if self._window is None:
            return {"ok": False, "message": ""}
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        try:
            res = self._window.create_file_dialog(kind)
        except Exception:
            res = None
        if not res:
            return {"ok": False, "message": "", "cancelled": True}
        r = self._import.set_source(str(res[0]))
        return {**r, "path": str(res[0])} if r["ok"] else r

    def import_prepare(self, category: str = "") -> dict:
        return self._import.prepare(category)

    def import_start(self, category: str = "", create_base: bool = False) -> dict:
        return self._import.start(category, bool(create_base))

    def import_cancel(self) -> dict:
        return self._import.cancel()

    def import_close(self) -> dict:
        return self._import.close()

    def import_retry_lr(self) -> dict:
        return self._import.retry_lr()

    def import_state(self) -> dict:
        return self._import.state()

    # ---- 图库（0.11.0）：路径一律取设置里的软件文件夹，页面只能传当前图库里已知的照片标识 ----
    def library_state(self) -> dict:
        return self._photolib.state()

    def library_refresh(self) -> dict:
        return self._photolib.refresh()

    def library_thumbnails(self, ids, retry: bool = False) -> dict:
        return self._photolib.request_thumbs(ids, retry)

    def library_select(self, ids, active=None) -> dict:
        return self._photolib.select(ids, active)

    def library_clear_selection(self) -> dict:
        return self._photolib.clear_selection()

    def library_add_missing(self) -> dict:
        return self._photolib.add_missing()

    def library_cancel_add(self) -> dict:
        return self._photolib.cancel_add()

    def library_close_add(self) -> dict:
        return self._photolib.close_add()

    def library_list(self, limit: int = 300) -> dict:
        return self._import.library(limit)

    def open_library(self) -> dict:
        """在资源管理器中打开软件文件夹（只打开设置里的软件文件夹，不接受页面传入的路径）。"""
        base = self._settings.data["base_folder"]
        if not os.path.isdir(base):
            return {"ok": False, "message": "软件文件夹尚不存在。完成一次导入后会自动创建，或在设置中更换。"}
        try:
            os.startfile(base)          # noqa: S606 - Windows 资源管理器
        except (OSError, AttributeError) as e:
            return {"ok": False, "message": f"无法打开文件夹：{e}"}
        return {"ok": True, "message": ""}

    # ---- 导出 ------------------------------------------------------
    def export_dialog_state(self) -> dict:
        """打开导出对话框：当前选中的照片、导出文件夹、上次的选项、能否导出。"""
        return self._export.dialog_state()

    def choose_export_folder(self) -> dict:
        """弹出系统文件夹对话框选择导出位置。路径只来自这次点击，由后端记住；页面不能传入路径。"""
        if self._window is None:
            return {"ok": False, "message": ""}
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        cur = self._export.folder or self._settings.data.get("export_last_folder", "")
        init = cur if cur and os.path.isdir(cur) else ""
        try:
            res = self._window.create_file_dialog(kind, directory=init)
        except Exception:
            res = None
        if not res:
            return {"ok": False, "message": "", "cancelled": True}
        return self._export.set_folder(str(res[0]))

    def export_current_photo(self, options: dict) -> dict:
        """导出当前选中的照片。只用后端记住的文件夹；options 里任何路径字段都被忽略。结果经 export_done 事件给出。"""
        return self._export.export(options)

    def export_state(self) -> dict:
        return self._export.state()

    def export_close(self) -> dict:
        return self._export.close()

    def reveal_last_export(self) -> dict:
        """在资源管理器中显示本次导出的结果文件（路径来自后端记录）。"""
        return self._export.reveal_last()

    # ---- AI 挑片 ---------------------------------------------------
    def _pick_acquire(self) -> bool:
        """与对话共用"忙"标记；挑片期间一切需要确认的工具直接拒绝（AI 只能查看照片）。"""
        with self._lock:
            if self._busy:
                return False
            self._busy = True
        self._hub.deny_all = True
        return True

    def _pick_release(self) -> None:
        self._hub.deny_all = False
        if self._persistent:
            self._hub.finish_turn()
        else:
            self._hub.end_turn()
        self._busy = False

    def _pick_send(self, prompt: str, on_event) -> None:
        if self._persistent:
            self._provider.send(prompt, on_event)
        else:
            token = self._hub.begin_turn()
            self._provider.send(prompt, on_event, confirm=True, extra_env={"LRAPP_PORT": str(self._hub.port), "LRAPP_TOKEN": token})

    def _pick_stop(self) -> None:
        self._hub.cancel_all()
        self._provider.stop()

    def pick_prepare(self) -> dict:
        """点"AI 挑片"：读取 Lightroom 当前选中的照片并检查张数。"""
        return self._pick.prepare()

    def pick_start(self, options: dict) -> dict:
        """开始比较。options 只含评判标准、自定义文字、结果数量；照片由后端自己从 Lightroom 读取。结果经 pick_done 事件给出。"""
        return self._pick.start(options)

    def pick_stop(self) -> dict:
        return self._pick.stop()

    def pick_state(self) -> dict:
        return self._pick.state()

    def pick_close(self) -> dict:
        return self._pick.close()

    def pick_preview(self, photo_id: str) -> dict:
        """放大预览一张本次比较的照片（只接受本次选中照片的 id）。"""
        return self._pick.preview_url(photo_id)

    def pick_apply_prepare(self) -> dict:
        """生成确认清单（原星级/旗标 → 新星级/旗标）。此时不写入任何内容。"""
        return self._apply.prepare()

    def pick_apply_confirm(self, photo_ids: list) -> dict:
        """用户点"确认写入"：只写清单里勾选的照片，且只写星级和旗标。结果经 pick_apply_done 事件给出。"""
        return self._apply.confirm(photo_ids)

    def pick_apply_cancel(self) -> dict:
        return self._apply.cancel()

    def pick_apply_state(self) -> dict:
        return self._apply.state_public()

    def pick_apply_undo(self, force: bool = False) -> dict:
        r = self._apply.undo(bool(force))
        try:
            ids = [x.get("photo_id") for x in r.get("results") or [] if x.get("status") == "undone"]
            threading.Thread(target=self._photolib.refresh_meta, args=(ids,), daemon=True).start()
        except Exception:                        # noqa: BLE001
            pass
        return r

    def pick_apply_close(self) -> dict:
        return self._apply.close()

    def selection_state(self) -> dict:
        """Lightroom 当前选中的全部照片（页面刚加载时取一次，之后靠 selection 事件更新）。"""
        return self._backend.selection_public()

    # ---- 预设 / 经验 / 收藏 ----------------------------------------
    def _file_dialog(self, save: bool, name: str = ""):
        if self._window is None:
            return None
        fd = getattr(webview, "FileDialog", None)
        kind = (getattr(fd, "SAVE", None) if save else getattr(fd, "OPEN", None)) or (webview.SAVE_DIALOG if save else webview.OPEN_DIALOG)
        try:
            if save:
                res = self._window.create_file_dialog(kind, save_filename=name, file_types=("JSON 文件 (*.json)",))
            else:
                res = self._window.create_file_dialog(kind, allow_multiple=False, file_types=("JSON 文件 (*.json)",))
        except Exception:
            return None
        if not res:
            return None
        return str(res if isinstance(res, str) else res[0])

    def _read_picked(self, limit: int):
        """系统文件选择窗口里用户点选的文件；超过 limit 字节不读入。返回 (字节, 错误, 是否取消)。"""
        path = self._file_dialog(False)
        if not path:
            return None, "", True
        try:
            if os.path.getsize(path) > limit:
                return None, f"文件超过 {limit // 1024} KB，已拒绝导入。", False
            return Path(path).read_bytes(), "", False
        except OSError as e:
            return None, f"无法读取文件：{e.strerror or e}", False

    def _write_picked(self, name: str, text: str) -> dict:
        path = self._file_dialog(True, name)
        if not path:
            return {"ok": False, "cancelled": True, "message": ""}
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            Path(path).write_text(text, encoding="utf-8")
        except OSError as e:
            return {"ok": False, "message": f"导出失败：{e.strerror or e}"}
        return {"ok": True, "path": path, "message": "已导出。"}

    def lib_preset_options(self) -> dict:
        return self._lib.save_options()

    def lib_presets(self) -> dict:
        return self._lib.preset_list()

    def lib_preset_save(self, name: str, note: str, groups: list, overwrite: bool = False) -> dict:
        return self._lib.preset_save(name, note, groups, bool(overwrite))

    def lib_preset_rename(self, preset_id: str, new_name: str) -> dict:
        return self._lib.preset_rename(preset_id, new_name)

    def lib_preset_note(self, preset_id: str, note: str) -> dict:
        return self._lib.preset_set_note(preset_id, note)

    def lib_preset_delete(self, preset_id: str) -> dict:
        return self._lib.preset_delete(preset_id)

    def lib_preset_export(self, preset_id: str) -> dict:
        t = self._lib.preset_export_text(preset_id)
        return self._write_picked(t["name"] + ".json", t["text"]) if t["ok"] else t

    def lib_preset_import(self) -> dict:
        raw, err, cancelled = self._read_picked(libstore.MAX_IMPORT_BYTES)
        if cancelled:
            return {"ok": False, "cancelled": True, "message": ""}
        if raw is None:
            return {"ok": False, "message": err}
        return self._lib.preset_import_bytes(raw)

    def lib_preset_import_commit(self, overwrite: bool) -> dict:
        return self._lib.preset_import_commit(bool(overwrite))

    def lib_lr_presets(self, query: str = "") -> dict:
        return self._lib.lr_presets(query)

    def lib_apply_prepare(self, kind: str, ref: str, strength: int = 100) -> dict:
        return self._lib.apply_prepare(kind, ref, strength)

    def lib_apply_confirm(self, token: str) -> dict:
        return self._lib.apply_confirm(token)

    def lib_apply_cancel(self) -> dict:
        return self._lib.apply_cancel()

    def lib_notes(self, query: str = "", tag: str = "") -> dict:
        return self._lib.notes_state(query, tag)

    def lib_note_save(self, note_id: str, fields: dict) -> dict:
        return self._lib.note_save(note_id or None, fields)

    def lib_note_delete(self, note_id: str) -> dict:
        return self._lib.note_delete(note_id)

    def lib_notes_export(self) -> dict:
        t = self._lib.notes_export_text()
        return self._write_picked("经验库.json", t["text"]) if t["ok"] else t

    def lib_notes_import(self) -> dict:
        raw, err, cancelled = self._read_picked(libstore.MAX_NOTES_IMPORT_BYTES)
        if cancelled:
            return {"ok": False, "cancelled": True, "message": ""}
        if raw is None:
            return {"ok": False, "message": err}
        return self._lib.notes_import_bytes(raw)

    def lib_record_available(self) -> dict:
        return {"ok": self._lib.record_available()}

    def lib_record_start(self) -> dict:
        return self._lib.record_start()

    def lib_record_stop(self) -> dict:
        return self._lib.record_stop()

    def lib_record_state(self) -> dict:
        return self._lib.record_state()

    def lib_record_close(self) -> dict:
        return self._lib.record_close()

    def lib_fav_toggle(self, kind: str, key: str, label: str = "") -> dict:
        """收藏/取消收藏。kind="photo" 时不接受页面传来的照片 id，一律用 Lightroom 当前选中的那张。"""
        if kind == "photo":
            p = self._backend.photo or {}
            return self._lib.fav_toggle("photo", p.get("id"), p.get("name") or "")
        return self._lib.fav_toggle(kind, key, label)

    def lib_favs(self) -> dict:
        return self._lib.fav_state()

    def preview_state(self) -> dict:
        """页面刚加载时取最近一次预览内容（之后靠 onClaudeEvent 的 preview 事件更新）。"""
        return self._preview.last or {"state": "loading", "message": "正在读取预览"}

    def set_preview_edge(self, edge) -> dict:
        """预览长边像素（256–2048）；"初始"图保持首次取图时的分辨率。"""
        return {"ok": True, "edge": self._preview.set_edge(edge)}


def main() -> None:
    api = Api()
    api._window = webview.create_window(
        "修图助手",
        WEB.as_uri(),
        js_api=api,
        width=1440,
        height=860,
        min_size=(1100, 680),
        background_color="#17181b",
    )
    webview.start(api._start_background)
    api._shutdown()


if __name__ == "__main__":
    main()
