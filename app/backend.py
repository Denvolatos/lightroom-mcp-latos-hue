# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""后台总管：常驻会话预热、连接状态、自动恢复、当前照片跟踪。界面进程里只有一个实例。

巡检线程每 2 秒执行一次 tick()：
- claude 进程意外退出 -> 用 --resume 重建；
- 窗口自己的 Bridge 长时间连不上 -> 换新端口重新登记（插件约 2 秒内重新发现）；
- 助手那条通道长时间没连上而窗口这条已连上 -> 重建 claude 进程（新进程换新端口）；
- 定期清理失效的服务公告；定期读取当前选中的照片（换照片时“本次调整”表格只显示这张照片的记录）。
全部在 app/ 内完成，用户不需要重载插件或重启软件。
"""
from __future__ import annotations

import threading
import time

import connection as conn
from ports import clean_stale_announcements

TICK_SECONDS = 2.0
SIDE_RETRY_SECONDS = 20         # 助手通道启动后这么久仍未连上，就重建一次
SIDE_MAX_ATTEMPTS = 3           # 连续重建次数上限，之后冷却一段时间再试
SIDE_COOLDOWN_SECONDS = 120
LR_RESTART_SECONDS = 30         # 窗口自己的 Bridge 连不上时，每隔这么久换端口重登记一次
CLEAN_SECONDS = 30
PHOTO_POLL_SECONDS = 3
WAIT_READY_SECONDS = 25         # 发送消息时若尚未连接，最多等多久


class Backend:
    def __init__(self, lr, session, tracker, emit, state_file=None, clock=time.monotonic,
                 cleaner=clean_stale_announcements, previews=None, hold_restart=None):
        self._hold_restart = hold_restart           # () -> bool：为真时暂停“换端口重建 Lightroom 通道”（刚自动启动 Lightroom 的宽限期）
        self.previews = previews                    # PreviewManager（可为空）：巡检时顺带请求刷新中栏预览
        self.lr, self.session, self.tracker, self.emit = lr, session, tracker, emit
        self.state_file = state_file
        self._clock = clock
        self._cleaner = cleaner
        self._lock = threading.Lock()
        t = clock()
        self._down_since: float | None = t          # None 表示当前已连接
        self._last_status: tuple | None = None
        self._side_attempts = 0
        self._side_cooldown_until = 0.0
        self._last_lr_restart = t
        self._last_clean = t
        self._last_photo_poll = -PHOTO_POLL_SECONDS
        self.photo: dict | None = None
        self.selection: dict = {"count": 0, "photos": [], "active_id": None}   # Lightroom 当前选中的全部照片（只读）
        self._sel_key: tuple | None = None
        self.events: list[str] = []                 # 恢复动作记录（便于测试与排查，不含敏感内容）
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # ---- 状态 ------------------------------------------------------
    def status(self) -> dict:
        now = self._clock()
        side = conn.read_side_state(self.state_file) if self.state_file is not None else None
        if side is not None and not self.session.alive:
            side = {"connected": False, "stale": True}      # 助手进程已不在：状态文件即使还新也不算数
        app_ok = bool(self.lr.connected)
        connected_now = app_ok and (side is None or bool(side.get("connected")))
        with self._lock:
            if connected_now:
                self._down_since = None
            elif self._down_since is None:
                self._down_since = now
            down_for = 0.0 if self._down_since is None else now - self._down_since
        st = conn.evaluate(app_ok, side, down_for)
        st["plugin_version"] = getattr(self.lr, "plugin_version", None)
        st["claude_alive"] = bool(self.session.alive)
        return st

    def _push_status(self, st: dict) -> None:
        key = (st["state"], st["hint"], st["claude_alive"])
        if self._last_status != key:
            self._last_status = key
            self.emit({"type": "status", **st})

    # ---- 巡检 ------------------------------------------------------
    def tick(self) -> dict:
        now = self._clock()
        busy = self.session.busy
        if not busy and not self.session.alive:
            self.events.append("restart_claude")
            self.session.ensure_running()
        st = self.status()
        self._push_status(st)
        side_known = st["side"] is not None
        # 窗口这条已连上，助手那条迟迟没连上：重建 claude（换新端口）
        if st["app"] and side_known and not st["side"] and not busy and self.session.spawned_at is not None:
            if now >= self._side_cooldown_until and now - self.session.spawned_at > SIDE_RETRY_SECONDS:
                self._side_attempts += 1
                self.events.append("restart_side")
                if self._side_attempts >= SIDE_MAX_ATTEMPTS:
                    self._side_attempts = 0
                    self._side_cooldown_until = now + SIDE_COOLDOWN_SECONDS
                self.session.restart()
        elif st["connected"]:
            self._side_attempts = 0
        # 窗口自己的通道连不上：换端口重新登记
        if not st["app"] and self._down_since is not None:
            if (now - self._down_since > LR_RESTART_SECONDS and now - self._last_lr_restart > LR_RESTART_SECONDS
                    and not self._holding()):
                self._last_lr_restart = now
                self.events.append("restart_lr")
                self.lr.restart()
        if now - self._last_clean > CLEAN_SECONDS:
            self._last_clean = now
            try:
                self._cleaner()
            except Exception:
                pass
        if self.previews is not None and st["app"]:
            self.previews.poll()
        if st["app"] and not busy and now - self._last_photo_poll >= PHOTO_POLL_SECONDS:
            self._last_photo_poll = now
            self.refresh_photo()
        return st

    def _holding(self) -> bool:
        try:
            return bool(self._hold_restart and self._hold_restart())
        except Exception:                           # noqa: BLE001 - 查询出错按“不暂停”，保持原有行为
            return False

    def refresh_photo(self) -> None:
        """一次 list_selected 同时得到“当前这一张”和“全部选中的照片”（没有增加调用次数）。"""
        if hasattr(self.lr, "selected_all"):
            allsel = self.lr.selected_all()
            if allsel is None:
                return
            aid = allsel.get("active_id")
            sel = {"id": aid, "name": next((p.get("name") for p in allsel["photos"] if p.get("id") == aid), None)} if aid                 else {"id": None, "name": None}
            self._set_selection(allsel)
        else:
            sel = self.lr.selected_photo()
            if sel is None:
                return
        old = (self.photo or {}).get("id")
        self.photo = sel
        self.tracker.current_photo = sel.get("id")
        if sel.get("id") != old:
            self.emit({"type": "photo", "id": sel.get("id"), "name": sel.get("name")})
            self.emit({"type": "adjust", "rows": self.tracker.snapshot(sel.get("id"))})

    def _set_selection(self, allsel: dict) -> None:
        key = (allsel.get("count"), allsel.get("active_id"), tuple((p["id"], p.get("name")) for p in allsel["photos"]))
        self.selection = {"count": allsel.get("count", 0), "active_id": allsel.get("active_id"), "photos": list(allsel["photos"])}
        if key != self._sel_key:
            self._sel_key = key
            self.emit({"type": "selection", **self.selection_public()})

    def selection_public(self) -> dict:
        """给页面的选中照片：数量与名字列表（id 也给，页面不会拿它做别的事）。"""
        s = self.selection
        return {"count": s.get("count", 0), "active_id": s.get("active_id"),
                "photos": [{"id": p["id"], "name": p.get("name")} for p in s.get("photos", [])]}

    def rows(self) -> list[dict]:
        return self.tracker.snapshot((self.photo or {}).get("id"))

    # ---- 发送前等待连接 --------------------------------------------
    def wait_ready(self, timeout: float = WAIT_READY_SECONDS, sleep=time.sleep) -> tuple[bool, str]:
        """发送消息前确认已连接；尚未连接时先自动等待（有上限）并提示，而不是直接失败。"""
        end = self._clock() + timeout
        announced = False
        while True:
            if not self.session.alive:
                self.session.ensure_running()
            st = self.status()
            if st["connected"] and self.session.alive:
                return True, ""
            if not announced:
                announced = True
                self.emit({"type": "connecting", "message": "正在连接 Lightroom，请稍候"})
            if self._clock() >= end:
                return False, (st["hint"] if not st["connected"] else "助手进程未能启动，请稍后重试。")
            sleep(0.5)

    # ---- 生命周期 --------------------------------------------------
    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self.tick()
            except Exception:
                pass

    def stop(self) -> None:
        self._stop.set()
