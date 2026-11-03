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
from preview import PreviewManager, PreviewServer, PreviewStore  # noqa: E402
from ports import STATE_DIR  # noqa: E402

WEB = Path(__file__).resolve().parent / "web" / "index.html"


class Api:
    """页面里用 window.pywebview.api.send(text, confirm) / stop() / reset() / answer(id, allow) /
    undo(edit_id, force) / restore_original(force) / status() 调用。

    注意：pywebview 会把公开属性都当成可调用接口扫描，所以内部状态一律用下划线开头。
    """

    def __init__(self) -> None:
        self._window = None
        # 默认用常驻会话；设环境变量 LRAPP_PER_TURN=1 可回到“每条消息新启动一次 claude”（用于对比与排查）
        self._persistent = os.environ.get("LRAPP_PER_TURN") != "1"
        self._busy = False
        self._lock = threading.Lock()
        self._tracker = AdjustmentTracker()
        state_file = STATE_DIR / "claude_side.json" if self._persistent else None
        self._rpc_token = secrets.token_urlsafe(24)
        self._settings = appsettings.SettingsStore()
        # AI 来源经注册表取得（目前只有 claude）；切换来源在下一次“新对话”时生效
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
        self._export = ExportService(self._settings, self._lr, self._emit)

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
        self._backend.start()

    def _provider_env(self) -> dict:
        token = self._hub.begin_session()
        return {"LRAPP_PORT": str(self._hub.port), "LRAPP_TOKEN": token, "LRAPP_RPC_TOKEN": self._rpc_token}

    def _apply_provider_choice(self) -> bool:
        """“新对话”时，若设置里的 AI 来源与当前不同，换成新来源并启动。返回是否已换（换了就不必再 reset）。"""
        want = self._settings.data["provider"]
        if want == self._provider.id or not is_selectable(want):
            return False
        old = self._provider
        self._provider = create_provider(want, state_file=self._state_file, persistent=self._persistent)
        self._session = self._provider
        self._backend.session = self._provider
        old.close()
        self._provider.start(self._provider_env())
        return True

    def _shutdown(self) -> None:
        self._backend.stop()
        self._preview.stop()
        self._provider.close()
        self._hub.stop()
        self._lr.stop()

    def _emit(self, ev: dict) -> None:
        if self._window is None:
            return
        try:
            self._window.evaluate_js(
                f"window.onClaudeEvent && window.onClaudeEvent({json.dumps(ev, ensure_ascii=False)})")
        except Exception:
            pass  # 窗口已关闭

    def _on_event(self, ev: dict) -> None:
        """claude 的事件：先更新“本次调整”数据，再推给页面。"""
        with self._lock:
            changed = self._tracker.observe(ev)
            rows = self._backend.rows() if changed else None
        self._emit(ev)
        if rows is not None:
            self._emit({"type": "adjust", "rows": rows})
            self._preview.request()          # 调整/撤销/还原有变化：短防抖后刷新“当前”预览

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
                if self._persistent:
                    self._provider.send(text, self._on_event)
                else:
                    token = self._hub.begin_turn()
                    env = {"LRAPP_PORT": str(self._hub.port), "LRAPP_TOKEN": token}
                    self._provider.send(text, self._on_event, confirm=confirm, extra_env=env)
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

    def stop(self) -> dict:
        self._hub.cancel_all()
        self._provider.stop()
        return {"ok": True}

    def reset(self) -> dict:
        self._hub.cancel_all()
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
        return {"ok": r["ok"], "conflict": r["conflict"], "message": r["message"]}

    def restore_original(self, force: bool = False) -> dict:
        r = self._lr.restore_original(bool(force))
        if r["ok"]:
            undone = set((r.get("result") or {}).get("edits_undone") or [])
            with self._lock:
                self._tracker.mark_undone(undone)
            self._push_rows()
            self._preview.request()
        return {"ok": r["ok"], "conflict": r["conflict"], "message": r["message"]}

    # ---- 设置 ------------------------------------------------------
    def get_settings(self, include_status: bool = True) -> dict:
        """当前设置、AI 来源列表（含状态）、关于信息。include_status=False（启动时）不做登录检测，只取设置值。"""
        cur = self._provider.status() if include_status else {"available": True, "state": "unknown", "reason": "", "next_step": ""}
        return {"settings": dict(self._settings.data), "providers": available_providers(cur),
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
