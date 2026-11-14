# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""修图助手：打开界面，对话框接到本机已登录的 Claude Code 命令行，可查看并调整照片（支持逐项确认与撤销）。

运行：python app/main.py
"""
import json
import os
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path

import webview

sys.path.insert(0, str(Path(__file__).resolve().parent))
import frozen  # noqa: E402
import connection as connmod  # noqa: E402
from adjustments import AdjustmentTracker, fmt_value  # noqa: E402
from names import param_name  # noqa: E402
import lr_autostart  # noqa: E402
import splash as splashmod  # noqa: E402
import update_check as updatemod  # noqa: E402
import wizard as wizardmod  # noqa: E402
from backend import Backend  # noqa: E402
from confirm_hub import ConfirmHub  # noqa: E402
from lr_service import LrService, valid_edit_id, version_name_error  # noqa: E402
from providers import (MSG_CHOOSE_AI, NotChosenProvider, StatusProbe, available_providers, create_provider,  # noqa: E402
                       is_selectable)
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
import ports as portsmod  # noqa: E402

WEB = frozen.web_dir() / "index.html"
MSG_AI_BUSY = "AI 正在处理（对话、AI 挑片或“记成经验”还没结束）。请等它完成，或先点“停止”，再试一次。"
MSG_PLAN_STALE = "请先重新预演这批照片。"
UNKNOWN_STATUS = {"available": False, "state": "unknown", "reason": "状态未知。", "next_step": ""}
ABOUT_QUERY_TIMEOUT = 3.0        # 打开设置时向 Lightroom 要版本号：请求本身的超时
ABOUT_WAIT_SECONDS = 1.5         # 设置对话框最多为它等这么久；没等到先显示“未知”，结果到了记进缓存，下次打开就有
LR_VERSION_TTL = 300.0           # Lightroom 版本号缓存多久
MSG_VERSION_STALE = "版本内容已经变了，或者这次确认已经用过。请重新点“应用版本”查看差异。"


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
        # 还没选 AI 来源（全新安装）：用占位来源，不启动任何 AI 命令行；窗口自己起 Bridge 连 Lightroom，
        # 图库、导入、导出、预设照常可用。用户在“环境检查”里选了之后，由 wizard_choose_ai 换成真正的来源。
        chosen = self._ai_chosen()
        self._persistent = chosen and self._preferred_persistent and self._settings.data["provider"] == "claude"
        state_file = STATE_DIR / "claude_side.json" if self._persistent else None
        # AI 来源经注册表取得；切换来源在下一次“新对话”时生效
        self._provider = (create_provider(self._settings.data["provider"], state_file=state_file, persistent=self._persistent)
                          if chosen else NotChosenProvider())
        self._probe = None                       # 未选择时用来显示各来源“已安装 / 已登录”的探测器（用到才建）
        self._state_file = state_file
        self._session = self._provider           # 兼容旧名：Backend / LrService 只用 alive、busy、restart 等
        # 常驻模式最终会借用助手里那个服务的通道，窗口不再单独起 Bridge（Lightroom 插件同时轮询 3 个以上服务会变慢，见 DEV_NOTES）。
        # 但只有 claude 真的启动、它那条通道也连上了 Lightroom 之后才切过去（见 _watch_side）；在那之前、或 claude 没装/没登录/
        # 启动失败时，一直用窗口自己的 Bridge，图库、导出、预设、版本照常可用。
        self._borrowing = False
        self._startup_errors: list[str] = []     # 启动时没能完成的步骤（见 _start_background）
        self._mode_lock = threading.RLock()
        self._closing = threading.Event()
        self._lr = self._make_lr(False)
        self._hub = ConfirmHub(self._emit, current_values=self._lr.current_values)
        self._hub.start()
        self._preview = PreviewManager(self._lr, PreviewServer(PreviewStore()), self._emit)
        self._preview.set_edge(self._settings.data["preview_edge"])
        self._backend = Backend(self._lr, self._session, self._tracker, self._emit, state_file=None, previews=self._preview,
                                 hold_restart=self._autolaunch_in_grace)
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
        # 自动启动 Lightroom（设置里的开关，默认关）：只在软件启动时跑一次；连上与否沿用 Backend 的真实连接判定
        self._autolaunch = lr_autostart.AutoLaunch(lambda: self._settings.data,
                                                   lambda: bool(self._backend.status().get("connected")), self._emit)
        # 环境检查向导（0.14.0）：四项只读检查，耗时的在后台线程；页面只能取状态、点按钮，不能传路径
        self._wizard = wizardmod.WizardChecker(lambda: self._settings.data, find_lightroom=lr_autostart.find_lightroom,
                                               is_running=lr_autostart.is_running,
                                               get_connection=self._wizard_connection,
                                               get_provider=self._wizard_provider, get_autolaunch=self._autolaunch.state,
                                               get_old_servers=lambda: portsmod.find_old_servers(appsettings.APP_VERSION))
        # 检查更新（0.15.0）：只提示，不下载不安装；启动时在后台查一次（设置可关），页面只能取状态、点按钮，不传地址
        self._updates = updatemod.AppUpdateChecker(appsettings.APP_VERSION,
                                                   lambda: self._settings.data.get("check_updates") is True)
        self._splash = None                      # 启动界面控制器（main() 里设置；没有启动界面时为空）
        self._pending_lr_path = ""               # 用户在文件对话框里点选、尚未保存的 Lightroom 路径
        self._ctx_pending = True                 # 新对话的第一条消息带上"经验库"资料块（见 send / reset）
        self._batch_pending = ""                 # 页面已看过的单次批量预演计划
        self._batch_photo_ids = []
        self._batch_done = set()                 # 本次运行里由软件执行的批次编号：只有它们能“整批还原”
        self._version_pending = None             # 页面已看过的版本差异（一次性令牌 + 当时的照片与参数），见 version_plan
        self._lib = LibraryService(self._lr, libstore.PresetStore(), libstore.NoteStore(), libstore.FavStore(), self._emit,
                                   on_applied=self._lib_applied, photo_fn=lambda: self._backend.photo,
                                   send_fn=self._pick_send, stop_fn=self._pick_stop, status_fn=lambda: self._provider.status(),
                                   ready_fn=lambda: self._backend.wait_ready(), acquire_fn=self._pick_acquire,
                                   release_fn=self._pick_release,
                                   has_adjustments=lambda: any(r.get("status") == "已应用" for r in self._tracker.rows))

    def _start_background(self) -> None:
        """窗口一出现就预热：Bridge、常驻 claude（含 lightroom_mcp 与确认服务）同时启动，之后每条消息零启动开销。
        每一步单独兜底：任何一步出错只把原因推给页面，后面的照常做；连接巡检（backend.start）最先启动，一定会执行。
        图库刷新放在最后：它会推事件给页面，而页面还没加载好时推事件会等待，不能挡住前面的步骤。"""
        self._splash_text(splashmod.TEXT_SERVICES)
        launching = bool(self._startup_step("自动启动 Lightroom", self._autolaunch.start))   # 开关为开时后台最小化启动
        self._startup_step("Lightroom 通道", lambda: threading.Thread(target=self._lr.start, daemon=True).start())
        self._startup_step("连接巡检", self._backend.start)
        self._startup_step("检查更新", self._updates.start_background)   # 开关为开时后台查一次；失败静默
        if self._persistent:
            self._startup_step("AI 助手", self._start_resident)
        self._startup_step("预览服务", lambda: (self._preview.server.start(), self._preview.start()))
        self._startup_step("图库服务", lambda: (self._photolib.server.start(), self._photolib.start()))
        self._splash_text(splashmod.TEXT_CONNECT_LR if launching else splashmod.TEXT_LOADING)
        self._startup_step("读取图库", self._photolib.refresh)          # 软件启动时读一次；连接恢复后再补读

    def _startup_step(self, name: str, fn):
        """启动时的一步：出错不往外抛，把原因作为一条错误消息推给页面（沿用 onClaudeEvent 的 error 事件）。"""
        try:
            return fn()
        except Exception as e:                   # noqa: BLE001
            self._startup_errors.append(name)
            try:
                self._emit({"type": "error", "message": f"启动时“{name}”没能完成（{type(e).__name__}）。"
                                                        "其他功能不受影响；如果一直不正常，请重新打开软件。"})
            except Exception:                    # noqa: BLE001
                pass
            return None

    def _splash_text(self, text: str) -> None:
        if self._splash is not None:
            self._splash.set_text(text)

    def ui_ready(self) -> dict:
        """主界面准备好了（页面在启动完成后调用一次）：关闭启动界面、显示主窗口。"""
        if self._splash is not None:
            self._splash.finish()
        return {"ok": True}

    def _ai_chosen(self) -> bool:
        return self._settings.data.get("provider_chosen") is True

    def _write_block(self) -> str | None:
        """软件界面直接触发的写入（版本、批量复用）能不能现在做。AI 正在处理一轮对话、AI 挑片或“记成经验”进行中
        （共用 _busy，挑片期间确认服务还处于 deny_all）时拒绝，避免软件和 AI 同时改同一张照片。返回原因或 None。"""
        if self._busy or bool(getattr(self._session, "busy", False)):
            return MSG_AI_BUSY
        return None

    def _provider_env(self) -> dict:
        token = self._hub.begin_session()
        return {"LRAPP_PORT": str(self._hub.port), "LRAPP_TOKEN": token, "LRAPP_RPC_TOKEN": self._rpc_token}

    def _apply_provider_choice(self) -> bool:
        """“新对话”时，若设置里的 AI 来源与当前不同，换成新来源并启动。返回是否已换（换了就不必再 reset）。"""
        want = self._settings.data["provider"]
        if not self._ai_chosen() or want == self._provider.id or not is_selectable(want):
            return False
        next_persistent = (self._preferred_persistent and want == "claude") if want in ("claude", "codex") else self._persistent
        with self._mode_lock:
            old = self._provider
            self._persistent = next_persistent
            self._state_file = STATE_DIR / "claude_side.json" if self._persistent else None
            self._provider = create_provider(want, state_file=self._state_file, persistent=self._persistent)
            self._session = self._provider
            if self._borrowing:
                # 借用的是旧 claude 的通道，它马上要关：先换回窗口自己的 Bridge
                self._switch_lr(False)
            else:
                self._backend.session = self._provider
            old.close()
        if self._persistent:
            self._start_resident()
        return True

    # ---- 窗口的 Lightroom 通道：自己的 Bridge / 借用常驻 claude 的通道 ----
    def _make_lr(self, borrow: bool):
        if borrow:
            return LrService(state_file=self._state_file, rpc_token=self._rpc_token, alive=lambda: self._session.alive,
                             restart_hook=lambda: not self._session.busy and self._session.restart())
        return LrService()

    def _switch_lr(self, borrow: bool) -> None:
        """换窗口的 Lightroom 通道，并让所有持有它的功能（预览、巡检、图库、导入、导出、挑片、预设）指向新的对象。"""
        with self._mode_lock:
            self._backend.stop()
            self._preview.stop()
            self._lr.stop()
            self._borrowing = borrow
            self._lr = self._make_lr(borrow)
            self._hub.current_values = self._lr.current_values
            self._preview = PreviewManager(self._lr, PreviewServer(PreviewStore()), self._emit)
            self._preview.set_edge(self._settings.data["preview_edge"])
            self._backend = Backend(self._lr, self._session, self._tracker, self._emit,
                                    state_file=None, previews=self._preview,
                                    hold_restart=self._autolaunch_in_grace)
            self._rebind_lr_services()
            if borrow:
                self._lr.start()                 # 借用模式的 start 只是建对象，不阻塞
            else:
                threading.Thread(target=self._lr.start, daemon=True).start()
            self._preview.server.start()
            self._preview.start()
            self._backend.start()

    def _start_resident(self) -> bool:
        """启动常驻 claude（失败不抛出），并在后台等它那条通道连上 Lightroom 后再切到借用模式。返回是否启动成功。"""
        provider = self._provider
        try:
            ok = bool(provider.start(self._provider_env()))
        except Exception:                        # noqa: BLE001 - 启动失败：继续用窗口自己的 Bridge
            ok = False
        threading.Thread(target=self._watch_side, args=(provider,), daemon=True).start()
        return ok

    def _side_ready(self, provider) -> bool:
        if not bool(getattr(provider, "alive", False)) or self._state_file is None:
            return False
        side = connmod.read_side_state(self._state_file)
        return bool(side.get("connected") and side.get("rpc_port"))

    def _watch_side(self, provider, interval: float = 1.0) -> None:
        """常驻 claude 那条通道连上 Lightroom 之后才切到借用模式（不在处理请求时切）。claude 没装/没登录时一直等着，
        窗口继续用自己的 Bridge；以后 claude 被巡检重建并连上了，照样会切过去。来源换掉或软件关闭就结束。"""
        while not self._closing.is_set():
            if self._provider is not provider or not self._persistent or self._borrowing:
                return
            try:
                if self._side_ready(provider) and not self._busy and not bool(getattr(provider, "busy", False)):
                    with self._mode_lock:
                        if self._provider is provider and self._persistent and not self._borrowing:
                            self._switch_lr(True)
                    return
            except Exception:                    # noqa: BLE001 - 读状态出错：下次再看
                pass
            self._closing.wait(interval)

    def _rebind_lr_services(self) -> None:
        """换了 LrService / 预览服务（Claude 常驻会话与 Codex 每轮启动之间切换）后，让所有持有它们的功能指向新的对象，
        否则图库、AI 挑片、预设/经验、导入、导出会继续使用已停止的旧通道。"""
        for svc in (self._import, self._export, self._photolib, self._pick, self._apply, self._lib):
            svc.lr = self._lr
        self._pick.server = self._preview.server
        self._pick.store = self._preview.server.store

    def _shutdown(self) -> None:
        """关闭软件时依次停掉各项服务。每一步单独兜底：前面哪一步出错，后面的（尤其是关 claude 进程树、确认服务、
        撤下 Bridge 公告）照样执行。"""
        closing = getattr(self, "_closing", None)
        if closing is not None:
            closing.set()                        # 让等待切换通道的后台线程结束
        steps = (lambda: self._autolaunch.stop(),        # 只停止等待；不会关闭用户的 Lightroom
                 lambda: self._backend.stop(),
                 lambda: self._preview.stop(),
                 lambda: self._photolib.stop(),
                 lambda: self._photolib.server.stop(),
                 lambda: self._provider.close(),
                 lambda: self._hub.stop(),
                 lambda: self._lr.stop())
        for step in steps:
            try:
                step()
            except Exception:                    # noqa: BLE001 - 关闭时出错也要继续关后面的
                pass

    def _tap(self, ev: dict) -> None:
        """软件内部事件联动图库：Lightroom 选区变化 -> 高亮；导入完成 -> 刷新图库；AI 挑片写入 -> 刷新星级与旗标。"""
        lib = getattr(self, "_photolib", None)
        if lib is None:
            return
        t = ev.get("type")
        if t == "status" and ev.get("connected"):
            lib.refresh()
        elif t == "selection":
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
        if not self._ai_chosen():
            return {"ok": False, "need_ai_choice": True, "message": MSG_CHOOSE_AI}
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

    def _busy_refusal(self, plain: bool = False) -> dict | None:
        """页面直接触发的写入（套用预设、撤销、还原到原始状态）在 AI 处理中 / AI 挑片进行中时拒绝。
        只拦这几个页面接口；AI 自己发起的写入走确认服务（confirm_hub），不经过这里。"""
        block = self._write_block()
        if not block:
            return None
        if plain:
            return {"ok": False, "busy": True, "message": block}
        return {"ok": False, "conflict": False, "busy": True, "message": block}

    def undo(self, edit_id: str, force: bool = False) -> dict:
        refused = self._busy_refusal()
        if refused:
            return refused
        r = self._lr.undo(edit_id, bool(force))
        if r["ok"]:
            with self._lock:
                self._tracker.mark_undone({edit_id})
            self._push_rows()
            self._preview.request()
            self._thumbs_stale()
        return {"ok": r["ok"], "conflict": r["conflict"], "message": r["message"]}

    def restore_original(self, force: bool = False) -> dict:
        refused = self._busy_refusal()
        if refused:
            return refused
        r = self._lr.restore_original(bool(force))
        if r["ok"]:
            undone = set((r.get("result") or {}).get("edits_undone") or [])
            with self._lock:
                self._tracker.mark_undone(undone)
            self._push_rows()
            self._preview.request()
            self._thumbs_stale()
        return {"ok": r["ok"], "conflict": r["conflict"], "message": r["message"]}

    # ---- 多版本（0.x 起的服务端功能，1.1.0 接到界面）---------------
    # 页面只能传版本名和一次性令牌；照片一律是 Lightroom 当前选中的那张，参数差异由后端自己记住。
    def versions_state(self) -> dict:
        return self._lr.versions()

    def version_preview(self, name: str) -> dict:
        bad = version_name_error(name)
        if bad:
            return {"ok": False, "message": bad}
        result = self._lr.version_picture(name)
        if not result["ok"]:
            return result
        data = result["result"]
        if not data["bytes"]:
            return {"ok": False, "message": "这个版本没有预览图。"}
        entry = self._preview.server.store.put(data["photo_id"], 512, "saved:" + name, data["bytes"])
        return {"ok": True, "result": {"photo_id": data["photo_id"], "url": self._preview.server.url_for(entry)}}

    def version_plan(self, name: str) -> dict:
        """当前照片与这个版本的差异（只读）。同时记下“给页面看过的方案”和一个一次性令牌：
        之后 version_apply 只认这个令牌，照片、当前参数、版本内容都以这里记下的为准，不由页面回传。"""
        self._version_pending = None
        bad = version_name_error(name)
        if bad:
            return {"ok": False, "message": bad}
        result = self._lr.version_record(name)
        if result["ok"]:
            data = result["result"]
            token = secrets.token_urlsafe(12)
            self._version_pending = {"token": token, "name": data["name"], "photo_id": data["photo_id"],
                                     "current": dict(data["current"]), "target": dict(data["target"])}
            # 页面只需要“显示用”的条目（中文名 + 格式化好的数值）和令牌；参数字典留在后端
            items = [{"label": param_name(k), "before": fmt_value(data["current"].get(k)),
                      "after": fmt_value(data["target"].get(k))} for k in data["changed"]]
            result["result"] = {"photo_id": data["photo_id"], "name": data["name"], "count": len(items),
                                "items": items, "token": token}
        return result

    def version_save(self, name: str) -> dict:
        """把当前照片的参数存成一个命名版本（只写软件自己的版本记录，不改照片）。"""
        bad = version_name_error(name)
        if bad:
            return {"ok": False, "message": bad}
        block = self._write_block()
        if block:
            return {"ok": False, "busy": True, "message": block}
        return self._lr.save_version(name.strip())

    def version_apply(self, token: str) -> dict:
        """用户在确认对话框里点了“应用”：只接受 version_plan 给出的令牌（一次性）。"""
        pending, self._version_pending = self._version_pending, None
        if (pending is None or not isinstance(token, str)
                or not secrets.compare_digest(token.encode("utf-8"), pending["token"].encode("utf-8"))):
            return {"ok": False, "stale": True, "message": MSG_VERSION_STALE}
        block = self._write_block()
        if block:
            return {"ok": False, "busy": True, "message": block}
        name = pending["name"]
        result = self._lr.apply_version(name, pending["photo_id"], pending["current"], pending["target"])
        if result["ok"] and result["result"].get("edit_id"):
            data = result["result"]
            changes = [{"key": c["parameter"], "before": c["before"], "after": c["after"]}
                       for c in data.get("changes", [])]
            self._lib_applied(data["edit_id"], data["photo_id"], "版本：" + name, changes)
        return result

    # ---- 批量复用单张调整：预演 → 确认 → 应用 → 整批还原 -----------
    def batch_plan_from_edit(self, edit_id: str) -> dict:
        if not valid_edit_id(edit_id):
            return {"ok": False, "message": "这条调整记录无效，请刷新后再试。"}
        block = self._write_block()
        if block:
            return {"ok": False, "busy": True, "message": block}
        self._batch_pending = ""                 # 新的预演开始：上一份计划作废
        self._batch_photo_ids = []
        result = self._lr.batch_plan_from_edit(edit_id)
        if result["ok"]:
            plan = result["result"]
            self._batch_pending = plan.get("plan_id") or ""
            self._batch_photo_ids = [p["photo_id"] for p in plan.get("photos", []) if p.get("will_change")]
            for p in plan.get("photos", []):         # 显示用：参数中文名 + 格式化好的数值
                for c in p.get("changes") or []:
                    c["label"] = param_name(c.get("parameter") or "")
                    c["before_text"], c["after_text"] = fmt_value(c.get("before")), fmt_value(c.get("after"))
            plan["skipped_labels"] = [param_name(k) for k in plan.get("skipped_parameters") or []]
            plan["delta_items"] = [{"label": param_name(k), "delta": ("+" if v > 0 else "") + fmt_value(v)}
                                   for k, v in (plan.get("deltas") or {}).items()]
        return result

    def batch_apply(self, plan_id: str) -> dict:
        if (not isinstance(plan_id, str) or not plan_id or not self._batch_pending
                or not secrets.compare_digest(plan_id.encode("utf-8"), self._batch_pending.encode("utf-8"))):
            return {"ok": False, "stale": True, "message": MSG_PLAN_STALE}
        block = self._write_block()
        if block:                                # 计划保留：等 AI 忙完可以直接再点一次
            return {"ok": False, "busy": True, "message": block}
        self._batch_pending = ""
        photo_ids, self._batch_photo_ids = self._batch_photo_ids, []
        result = self._lr.batch_apply(plan_id)
        if result["ok"]:
            batch_id = result["result"].get("batch_id")
            if valid_edit_id(batch_id):
                self._batch_done.add(batch_id)
            if result["result"].get("changed"):
                self._preview.request()
                self._thumbs_stale(*photo_ids)
        return result

    def batch_undo(self, batch_id: str) -> dict:
        """整批还原：只接受本次运行里软件自己执行过的批次编号（不是任意一条修改记录）。"""
        if not valid_edit_id(batch_id) or batch_id not in self._batch_done:
            return {"ok": False, "message": "找不到这一批修改。请在“本次调整”里逐张撤销。"}
        block = self._write_block()
        if block:
            return {"ok": False, "busy": True, "message": block}
        result = self._lr.undo(batch_id)
        if result["ok"]:
            if not (result.get("result") or {}).get("problems"):
                self._batch_done.discard(batch_id)
            self._preview.request()
            self._thumbs_stale()
        return result

    # ---- 设置 ------------------------------------------------------
    def get_settings(self, include_status: bool = True) -> dict:
        """当前设置、AI 来源列表（含状态）、关于信息。include_status=False（启动时）不做登录检测，只取设置值。"""
        unknown = {"available": True, "state": "unknown", "reason": "", "next_step": ""}
        self._pending_lr_path = ""
        detected = lr_autostart.find_lightroom(self._settings.data.get("lightroom_path") or "") if include_status else None
        claude_st = self._provider_status("claude") if include_status else unknown
        codex_st = self._provider_status("codex") if include_status else unknown
        return {"lightroom_detected": detected or "", "settings": dict(self._settings.data),
                "providers": available_providers(claude_st, codex_st),
                "current_provider": self._provider.id, "edges": list(appsettings.EDGE_CHOICES),
                "default_base_folder": appsettings.default_base_folder(),
                "about": self._about(ABOUT_QUERY_TIMEOUT if include_status else None)}

    def _status_probe(self):
        if getattr(self, "_probe", None) is None:
            self._probe = StatusProbe()
        return self._probe

    def _provider_status(self, pid: str) -> dict:
        """某个 AI 来源的状态。当前来源用它自己的 status()；另一个用常驻的探测器 StatusProbe（各自 30 秒缓存），
        不再每次新建实例、每次都跑一遍 claude/codex 的登录检测子进程。"""
        if pid == self._provider.id:
            return self._provider.status()
        inst = getattr(self._status_probe(), "_" + pid, None)
        try:
            return inst.status() if inst is not None else dict(UNKNOWN_STATUS)
        except Exception:                        # noqa: BLE001
            return dict(UNKNOWN_STATUS)

    def _lr_version(self, timeout: float | None) -> str | None:
        """Lightroom 版本号（缓存 LR_VERSION_TTL 秒）。timeout=None 只读缓存；否则在后台线程里问，最多等 ABOUT_WAIT_SECONDS。"""
        cache = getattr(self, "_lr_ver_cache", None)          # (取到的时间, 版本号)
        if cache and cache[1] and time.monotonic() - cache[0] < LR_VERSION_TTL:
            return cache[1]
        if timeout is None:
            return None
        bridge = getattr(self._lr, "_bridge", None)
        if not self._lr.connected or bridge is None:
            return None
        got = {}

        def ask() -> None:
            try:
                ver = str(bridge.call("status", timeout=timeout).get("lightroom_version") or "") or None
            except Exception:                    # noqa: BLE001
                return
            got["v"] = ver
            if ver:
                self._lr_ver_cache = (time.monotonic(), ver)
        t = threading.Thread(target=ask, daemon=True)
        t.start()
        t.join(min(timeout, ABOUT_WAIT_SECONDS))
        return got.get("v")

    def _about(self, timeout: float | None = ABOUT_QUERY_TIMEOUT) -> dict:
        """关于信息。timeout：向 Lightroom 要版本号的请求超时；None（启动时，界面等着它才显示）不问 Lightroom，只用缓存。"""
        try:
            lr_ver = self._lr_version(timeout)
        except Exception:                        # noqa: BLE001
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
        # Lightroom 路径不接受页面直接传入：只能是用户刚在文件对话框里点选的那个（pending），或清除
        choice = changes.get("lightroom_path_choice")
        changes = {k: v for k, v in changes.items() if k not in ("lightroom_path", "lightroom_path_choice", "provider_chosen")}
        if not self._ai_chosen():
            # 第一次选 AI 来源只能在“环境检查”里点按钮（wizard_choose_ai）；设置对话框保存时带上的下拉框默认值不算选择
            changes.pop("provider", None)
        if choice == "clear":
            changes["lightroom_path"] = ""
        elif choice == "pending" and self._pending_lr_path:
            changes["lightroom_path"] = self._pending_lr_path
        before = {k: self._settings.data.get(k) for k in ("base_folder", "gallery_folder")}
        r = self._settings.update(changes, selectable=is_selectable, create_missing=bool(create_missing))
        if r["ok"]:
            self._pending_lr_path = ""
            if "preview_edge" in changes:
                self._preview.set_edge(r["settings"]["preview_edge"])
            if any(r["settings"].get(k) != v for k, v in before.items()):
                # 换了工作文件夹或浏览目录：图库按新文件夹重新读取，向导下一次重新检查（与 wizard_pick_folder 一致）
                self._wizard.invalidate()
                self._photolib.refresh()
        return r

    def choose_lightroom_path(self) -> dict:
        """弹出系统文件选择窗口，让用户点选 Lightroom.exe。路径只来自这次点击，校验通过后暂存，点"保存"才写入设置。"""
        if self._window is None:
            return {"ok": False, "path": "", "message": ""}
        fd = getattr(webview, "FileDialog", None)
        kind = getattr(fd, "OPEN", None) or webview.OPEN_DIALOG
        try:
            res = self._window.create_file_dialog(kind, allow_multiple=False, file_types=("Lightroom 程序 (*.exe)",))
        except Exception:
            res = None
        if not res:
            return {"ok": False, "path": "", "message": "", "cancelled": True}
        ok = lr_autostart.valid_lightroom_path(str(res if isinstance(res, str) else res[0]))
        if not ok:
            return {"ok": False, "path": "", "message": "请选择名为 Lightroom.exe 的程序文件（本机磁盘上）。"}
        self._pending_lr_path = ok
        return {"ok": True, "path": ok, "message": ""}

    # ---- 环境检查向导 ----------------------------------------------
    def _wizard_connection(self) -> dict:
        """向导用的连接状态：Backend.status() 再加两项，让向导把“插件没连上”和“AI 那一侧没连上”分开说：
        borrowing：窗口是否借用常驻 claude 的通道；ai_side：常驻 claude 里的 Lightroom 服务是否连上（不用常驻会话时为 None）。"""
        st = dict(self._backend.status())
        st["borrowing"] = bool(getattr(self, "_borrowing", False))
        st["ai_side"] = None
        if self._persistent and self._state_file is not None:
            alive = bool(getattr(self._provider, "alive", False))
            st["ai_side"] = alive and bool(connmod.read_side_state(self._state_file).get("connected"))
        return st

    def _wizard_provider(self) -> dict:
        """设置里选中的 AI 来源的状态（名称 + available/state/reason/next_step）；与 get_settings 用同一套文案。
        还没选择时返回 {"chosen": False, "choices": [...]}：每个可选来源一项，带安装/登录状态和数据去向说明。"""
        if not self._ai_chosen():
            return {"chosen": False, "choices": [p for p in self._status_probe().rows() if p.get("selectable")]}
        want = self._settings.data["provider"]
        # 只检查选中的那个来源（当前来源或带缓存的探测器）；另一个不检查，向导每 5 秒刷新时不再起登录检测子进程
        want_st = self._provider_status(want)
        for p in available_providers(want_st if want == "claude" else dict(UNKNOWN_STATUS),
                                     want_st if want == "codex" else dict(UNKNOWN_STATUS)):
            if p["id"] == want:
                return p
        return {"name": "AI 来源", "available": False, "state": "unknown", "reason": "没有找到所选的 AI 来源。", "next_step": ""}

    def wizard_state(self, refresh: bool = False) -> dict:
        """四项检查的当前结果。立刻返回上一次的结果（checking 为真表示后台正在检查，页面稍后再取）；不收任何路径。"""
        return self._wizard.state(bool(refresh))

    def wizard_done(self, flag: bool) -> dict:
        """记下“向导不用再自动弹出”（flag=True）。只改 wizard_done 这一项设置。"""
        if not isinstance(flag, bool):
            return {"ok": False, "message": "参数无效。"}
        r = self._settings.update({"wizard_done": flag}, selectable=is_selectable)
        return {"ok": r["ok"], "wizard_done": r["settings"].get("wizard_done", False)}

    def wizard_choose_ai(self, provider_id: str) -> dict:
        """向导里点“使用 Claude / 使用 Codex”：第一次选择 AI 来源。只接受注册表里可选的来源 id；
        保存 provider 并把 provider_chosen 置真，然后走和“切换来源”同一条路径（_apply_provider_choice）立即生效。
        已经选过的不在这里改（到设置里换，下一次“新对话”生效）。"""
        if not isinstance(provider_id, str) or not is_selectable(provider_id):
            return {"ok": False, "message": "这个 AI 来源暂时不能选。"}
        if self._ai_chosen():
            return {"ok": False, "message": "已经选择过 AI 来源。要更换，请到“设置”里修改。"}
        if self._busy:
            return {"ok": False, "message": MSG_AI_BUSY}
        saved = self._settings.update({"provider": provider_id, "provider_chosen": True}, selectable=is_selectable)
        if not saved["ok"]:
            return {"ok": False, "message": next(iter(saved["errors"].values()), "设置未保存。")}
        self._ctx_pending = True
        try:
            self._apply_provider_choice()
        except Exception as e:                   # noqa: BLE001 - 选择已保存；启动失败的原因会在向导的 AI 项里显示
            self._wizard.invalidate()
            return {"ok": True, "message": f"已选择，但 AI 没能启动：{type(e).__name__}。请点“重新检查”。"}
        self._wizard.invalidate()
        return {"ok": True, "message": ""}

    def wizard_stop_old_servers(self) -> dict:
        """向导“旧版服务”一项的按钮：结束登记文件里版本较旧、进程名核对无误的 lrmcp 服务，并删除它们的登记文件。不收任何参数。"""
        try:
            r = portsmod.stop_old_servers(appsettings.APP_VERSION)
        except Exception as e:                   # noqa: BLE001
            self._wizard.invalidate()
            return {"ok": False, "stopped": 0, "message": f"没能关闭旧版服务（{type(e).__name__}）。"}
        self._wizard.invalidate()
        if r["failed"]:
            return {"ok": False, "stopped": len(r["stopped"]),
                    "message": f"有 {len(r['failed'])} 个旧版服务没能关闭（可能需要管理员权限）。可以重启电脑，或在任务管理器里结束 lrmcp。"}
        return {"ok": True, "stopped": len(r["stopped"]), "message": ""}

    def wizard_pick_folder(self) -> dict:
        """向导第 1 项的按钮：弹出系统文件夹对话框，选中后直接保存为照片工作文件夹。路径只来自这次点击。"""
        r = self.choose_folder(self._settings.data.get("base_folder") or "")
        if not r.get("ok"):
            return {"ok": False, "cancelled": True, "message": ""}
        saved = self._settings.update({"base_folder": r["path"]}, selectable=is_selectable)
        if not saved["ok"]:
            return {"ok": False, "cancelled": False, "message": next(iter(saved["errors"].values()), "设置未保存。")}
        self._wizard.invalidate()
        self._photolib.refresh()                 # 工作文件夹变了：图库按新文件夹重新读取
        return {"ok": True, "cancelled": False, "message": ""}

    def gallery_pick_folder(self) -> dict:
        """选择要浏览的照片文件夹，不改变导入副本的保存位置。"""
        r = self.choose_folder(appsettings.browse_folder(self._settings.data))
        if not r.get("ok"):
            return {"ok": False, "cancelled": True, "message": ""}
        saved = self._settings.update({"gallery_folder": r["path"]}, selectable=is_selectable)
        if not saved["ok"]:
            return {"ok": False, "cancelled": False, "message": next(iter(saved["errors"].values()), "目录未保存。")}
        self._photolib.refresh()
        return {"ok": True, "cancelled": False, "message": ""}

    def wizard_pick_lightroom(self) -> dict:
        """向导第 2 项的按钮：弹出系统文件选择窗口，选中 Lightroom.exe 后直接保存。路径只来自这次点击。"""
        r = self.choose_lightroom_path()
        if not r.get("ok"):
            return {"ok": False, "cancelled": bool(r.get("cancelled")), "message": r.get("message", "")}
        saved = self.save_settings({"lightroom_path_choice": "pending"})
        if not saved["ok"]:
            return {"ok": False, "cancelled": False, "message": next(iter(saved["errors"].values()), "设置未保存。")}
        self._wizard.invalidate()
        return {"ok": True, "cancelled": False, "message": ""}

    # ---- 检查更新 --------------------------------------------------
    def update_state(self) -> dict:
        """当前的更新状态（只读缓存/内存，不联网）：state 为 idle / checking / latest / available / unavailable。"""
        return self._updates.state()

    def check_update_now(self) -> dict:
        """手动检查更新（忽略缓存）：立刻返回“检查中”，结果在后台取到后由 update_state() 读出。不收任何参数。"""
        return self._updates.check_now()

    def open_update_page(self) -> dict:
        """用系统浏览器打开新版本的发布页。不收任何地址：只打开本软件自己缓存的、经过校验的本仓库 releases 链接。"""
        return self._updates.open_page()

    def _autolaunch_in_grace(self) -> bool:
        al = getattr(self, "_autolaunch", None)
        return bool(al and al.in_grace())

    def autolaunch_state(self) -> dict:
        """自动启动 Lightroom 的当前状态（页面刚加载时取一次，之后靠 lr_launch 事件更新）。"""
        return self._autolaunch.state()

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
        """在资源管理器中打开当前浏览文件夹，不接受页面传入的路径。"""
        base = appsettings.browse_folder(self._settings.data)
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
        if not self._ai_chosen():
            return {"ok": False, "need_ai_choice": True, "message": MSG_CHOOSE_AI}
        return self._pick.prepare()

    def pick_start(self, options: dict) -> dict:
        """开始比较。options 只含评判标准、自定义文字、结果数量；照片由后端自己从 Lightroom 读取。结果经 pick_done 事件给出。"""
        if not self._ai_chosen():
            return {"ok": False, "need_ai_choice": True, "message": MSG_CHOOSE_AI}
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
        refused = self._busy_refusal(plain=True)
        if refused:
            return refused
        return self._lib.apply_prepare(kind, ref, strength)

    def lib_apply_confirm(self, token: str) -> dict:
        refused = self._busy_refusal(plain=True)
        if refused:
            return refused                       # 确认清单保留：AI 忙完后可以直接再点“确认套用”
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
        if not self._ai_chosen():
            return {"ok": False, "need_ai_choice": True, "message": MSG_CHOOSE_AI}
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


MAIN_TITLE = "修图助手"                    # 主窗口标题（单实例激活时按它找窗口）
MUTEX_NAME = "Local\\LatosHue.SingleInstance"   # 安装器 installer/latoshue.iss 的 AppMutex 用同一个名字
ERROR_ALREADY_EXISTS = 183
_instance_handle = None                    # 互斥锁句柄：整个进程期间保持打开


def acquire_single_instance(name: str = MUTEX_NAME, kernel32=None) -> bool:
    """占用单实例互斥锁。返回 False 表示已有一个 Latos Hue 在运行。非 Windows 或任何调用失败都返回 True（不阻止启动）。
    只在图形界面入口（main）里调用；latoshue-helper 的子命令不经过这里，不受影响。"""
    global _instance_handle
    if kernel32 is None and os.name != "nt":
        return True
    try:
        import ctypes
        from ctypes import wintypes
        k = kernel32
        if k is None:
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.CreateMutexW.restype = wintypes.HANDLE
            k.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            ctypes.set_last_error(0)
        handle = k.CreateMutexW(None, False, name)
        err = k.last_error() if hasattr(k, "last_error") else ctypes.get_last_error()
        if not handle:
            return True
        if err == ERROR_ALREADY_EXISTS:
            try:
                k.CloseHandle(handle)
            except Exception:                    # noqa: BLE001
                pass
            return False
        _instance_handle = handle
        return True
    except Exception:                            # noqa: BLE001 - 检查失败不能让软件打不开
        return True


def activate_existing_window(titles=(MAIN_TITLE, splashmod.TITLE), user32=None) -> bool:
    """把已经在运行的那个实例的窗口拿到前台（最小化的先还原）。主窗口还隐藏着（启动画面阶段）就激活启动画面。"""
    if user32 is None and os.name != "nt":
        return False
    try:
        if user32 is None:
            import ctypes
            user32 = ctypes.windll.user32
        for title in titles:
            hwnd = user32.FindWindowW(None, title)
            if not hwnd or not user32.IsWindowVisible(hwnd):
                continue
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)       # SW_RESTORE
            user32.SetForegroundWindow(hwnd)
            return True
    except Exception:                            # noqa: BLE001
        pass
    return False


OLD_WEBVIEW_PREFIX = ".latoshue-webview-"


def webview_storage_dir(env=None) -> str | None:
    """WebView2 的数据目录：固定放在本机 %LOCALAPPDATA%\\LatosHue\\WebView2（不在照片盘上，每次复用，冷启动更快）。
    配合 pywebview 默认的 private_mode，不保存 Cookie 和网页存储。拿不到或建不了就返回 None（用 pywebview 的默认位置）。"""
    env = os.environ if env is None else env
    root = env.get("LOCALAPPDATA")
    if not root:
        return None
    path = Path(root) / "LatosHue" / "WebView2"
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return str(path)


def clean_old_webview_dirs(base: str) -> list[str]:
    """删除工作文件夹里旧版本留下的 .latoshue-webview-* 目录（只看这一层、只删目录、只删这个前缀）；失败忽略。返回删掉的名字。"""
    import shutil
    removed: list[str] = []
    try:
        if not base or not os.path.isdir(base):
            return removed
        entries = list(os.scandir(base))
    except OSError:
        return removed
    for e in entries:
        try:
            if e.name.startswith(OLD_WEBVIEW_PREFIX) and e.is_dir(follow_symlinks=False):
                shutil.rmtree(e.path, ignore_errors=True)
                if not os.path.exists(e.path):
                    removed.append(e.name)
        except OSError:
            pass
    return removed


def setup_windows(api, create_window=None, use_splash: bool = True):
    """创建主窗口（先隐藏）和启动窗口，返回启动界面控制器（没有启动界面时为 None，主窗口直接显示）。
    主窗口先创建，保证它是 pywebview 的主窗口：启动窗口关闭不会让程序退出。创建启动窗口出任何错，都退回"直接显示主窗口"。"""
    create_window = create_window or webview.create_window
    api._window = create_window(MAIN_TITLE, WEB.as_uri(), js_api=api, width=1440, height=860, min_size=(960, 620),
                                background_color="#17181b", hidden=use_splash)
    if not use_splash:
        return None
    sp = None
    try:
        sp = create_window(splashmod.TITLE, html=splashmod.splash_html(appsettings.APP_VERSION), width=splashmod.WIDTH,
                           height=splashmod.HEIGHT, resizable=False, frameless=True, easy_drag=True, on_top=True,
                           background_color="#17181b")
        sp.events.shown += lambda: (splashmod.center_window(sp), splashmod.round_corners(sp))
    except Exception:                            # noqa: BLE001 - 启动界面出问题不能影响软件本身
        sp = None
    ctrl = splashmod.SplashController(sp, api._window)
    api._splash = ctrl
    try:
        api._window.events.closed += ctrl.finish     # 主窗口被关掉时，也要把启动窗口收掉
    except Exception:                            # noqa: BLE001
        pass
    return ctrl


def main() -> None:
    if not acquire_single_instance():
        activate_existing_window()               # 已经开着一个：把它拿到前台，这次直接退出（不再起第二套 claude 和 Bridge）
        return
    api = Api()
    ctrl = setup_windows(api, use_splash=os.environ.get("LRAPP_NO_SPLASH") != "1")
    icon = str(splashmod.ICON_ICO) if splashmod.ICON_ICO.is_file() else None   # 窗口与任务栏图标（丝带）

    def run() -> None:
        if ctrl is not None:
            ctrl.start()
            if ctrl.splash is None:              # 没能创建启动窗口：直接显示主窗口
                ctrl.finish()
        api._start_background()
    base = api._settings.data.get("base_folder") or ""
    # 旧版本每次在照片工作文件夹里建的 WebView2 临时目录：后台顺带清掉（只删这个前缀的目录，删不掉就算了）
    threading.Thread(target=clean_old_webview_dirs, args=(base,), daemon=True).start()
    try:
        webview.start(run, icon=icon, storage_path=webview_storage_dir())
    finally:
        api._shutdown()


if __name__ == "__main__":
    main()
