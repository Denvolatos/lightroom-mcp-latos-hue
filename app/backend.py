# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""后台总管：常驻会话预热、连接状态、自动恢复、当前照片跟踪。界面进程里只有一个实例。

巡检线程每 2 秒执行一次 tick()：
- claude 进程意外退出 -> 用 --resume 重建；
- 窗口自己的 Bridge 长时间连不上 -> 换新端口重新登记（插件约 2 秒内重新发现）；
- 助手那条通道长时间没连上而窗口这条已连上 -> 重建 claude 进程（新进程换新端口）；
- 定期清理失效的服务公告。
选区轮询（1.1.1 起单独一个线程，约每 1 秒）：一次 list_selected 同时得到“当前这一张”和“全部选中的照片”，
同时交给中栏预览（PreviewManager.show），预览不再自己读选区；选区没变时预览不调 get_develop。
全部在 app/ 内完成，用户不需要重载插件或重启软件。
"""
from __future__ import annotations

import threading
import time

import connection as conn
from lr_service import wait_foreground_idle
from ports import clean_stale_announcements

TICK_SECONDS = 2.0
SIDE_RETRY_SECONDS = 20         # 助手通道启动后这么久仍未连上，就重建一次
SIDE_MAX_ATTEMPTS = 3           # 连续重建次数上限，之后冷却一段时间再试
SIDE_COOLDOWN_SECONDS = 120
LR_RESTART_SECONDS = 30         # 窗口自己的 Bridge 连不上时，每隔这么久换端口重登记一次
CLEAN_SECONDS = 30
PHOTO_POLL_SECONDS = 1.0       # 选区轮询周期（1.1.1：3 → 1，且和预览共用一次 list_selected）
POLL_YIELD_SECONDS = 3.0       # 选区轮询为正在进行的前台请求（取预览、选中）最多让路这么久
WAIT_READY_SECONDS = 25        # 发送消息时若尚未连接，最多等多久


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
        self._photo_lock = threading.Lock()         # refresh_photo / adopt_photo 的结果按发起顺序生效，回得慢的旧结果丢弃
        self._photo_seq = 0
        self._photo_applied = 0
        self._poll_wake = threading.Event()
        self._poll_thread: threading.Thread | None = None
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
        # 有在途命令时不重建：插件执行长命令（导出、缩略图、大文件夹）时不发轮询，看起来像断开，其实还在干活
        if not st["app"] and self._down_since is not None and not self._inflight():
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
            self.previews.poll()                    # 只是偶尔复查一次调整参数（Lightroom 里手动改了），见 preview.POLL_SECONDS
        # 选区轮询：start() 之后在单独的线程里跑（不再阻塞巡检）；没启动线程（测试）时在这里顺带做
        if self._poll_thread is None and st["app"] and now - self._last_photo_poll >= PHOTO_POLL_SECONDS:
            self._last_photo_poll = now
            self.refresh_photo()
        return st

    def _inflight(self) -> bool:
        try:
            return int(getattr(self.lr, "inflight", 0) or 0) > 0
        except Exception:                           # noqa: BLE001
            return False

    def _holding(self) -> bool:
        try:
            return bool(self._hold_restart and self._hold_restart())
        except Exception:                           # noqa: BLE001 - 查询出错按“不暂停”，保持原有行为
            return False

    def refresh_photo(self) -> None:
        """一次 list_selected 同时得到“当前这一张”和“全部选中的照片”，并交给中栏预览（预览不再自己读选区）。
        可被多个线程同时调用：结果按发起顺序生效，比后来者先发起、却后回来的结果直接丢弃（不会让旧照片盖住新照片）。"""
        with self._photo_lock:
            self._photo_seq += 1
            seq = self._photo_seq
        read_all = getattr(self.lr, "selected_all_info", None) or getattr(self.lr, "selected_all", None)
        detail = None
        if read_all is not None:
            allsel = read_all()
            if allsel is None:
                return
            aid = allsel.get("active_id")
            sel = {"id": aid, "name": next((p.get("name") for p in allsel["photos"] if p.get("id") == aid), None)} if aid \
                else {"id": None, "name": None}
            detail = dict(sel)
            if isinstance(allsel.get("info"), dict):                # 预览信息条用的相机、ISO 等（只有 selected_all_info 带）
                detail["info"] = allsel["info"].get(aid) or {}
        else:
            allsel = None
            sel = self.lr.selected_photo()
            if sel is None:
                return
        with self._photo_lock:
            if seq < self._photo_applied:
                return                                  # 过期：更新的结果已经用上了
            self._photo_applied = seq
            if allsel is not None:
                self._set_selection(allsel)
            self._apply_photo(sel)
        if detail is not None and self.previews is not None and hasattr(self.previews, "show"):
            self.previews.show(detail)

    def adopt_photo(self, photo_id, name=None) -> None:
        """软件自己刚选中了这张照片（图库点选，插件已回报选中结果）：不再读一次选区，直接把它当成当前照片。
        之前发起、还没回来的轮询结果会被丢弃；下一次轮询再以 Lightroom 实际选区为准。"""
        with self._photo_lock:
            self._photo_seq += 1
            self._photo_applied = self._photo_seq
            self._apply_photo({"id": photo_id, "name": name})

    def _apply_photo(self, sel: dict) -> None:
        old = (self.photo or {}).get("id")
        self.photo = sel
        self.tracker.current_photo = sel.get("id")
        if sel.get("id") != old:
            self.emit({"type": "photo", "id": sel.get("id"), "name": sel.get("name")})
            self.emit({"type": "adjust", "rows": self.tracker.snapshot(sel.get("id"))})

    def refresh_photo_async(self) -> None:
        """尽快在后台读一次选区（不占用调用者的线程）。轮询线程在跑就叫醒它，否则临时起一个线程。"""
        if self._poll_thread is not None:
            self._poll_wake.set()
            return
        threading.Thread(target=self._safe_refresh, daemon=True).start()

    def _safe_refresh(self) -> None:
        try:
            if self.lr.connected:
                self.refresh_photo()
        except Exception:                           # noqa: BLE001 - 后台线程不能悄悄死掉
            pass

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
        self._poll_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        self._poll_thread.start()

    def _loop(self) -> None:
        while not self._stop.wait(TICK_SECONDS):
            try:
                self.tick()
            except Exception:
                pass

    def _poll_loop(self) -> None:
        """选区轮询线程：约每 PHOTO_POLL_SECONDS 一次（refresh_photo_async 可以提前叫醒）。
        list_selected 可能要排在插件队列里等，放在这里就不会拖住 tick（状态灯、自动恢复）。"""
        while not self._stop.is_set():
            self._poll_wake.wait(PHOTO_POLL_SECONDS)
            self._poll_wake.clear()
            if self._stop.is_set():
                break
            wait_foreground_idle(self.lr, POLL_YIELD_SECONDS)   # 预览正在取图：先让它（当前照片已由 adopt_photo / show 告知）
            self._safe_refresh()

    def stop(self) -> None:
        self._stop.set()
        self._poll_wake.set()
