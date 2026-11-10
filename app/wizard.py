# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""环境检查向导（0.14.0）：用一个清单告诉用户哪项已就绪、哪项没好、下一步怎么办。

- 四项检查，全部只读，不自动修复任何东西：照片工作文件夹 -> Lightroom -> Lightroom 插件 -> AI 来源；
- 每项状态三种：ready（已就绪）/ todo（需要处理）/ wait（等待：依赖前一项，或正在启动/连接中）；
- 耗时的检查（查进程、探测 Lightroom、AI 命令行的登录状态）都在后台线程里做，界面只取上一次的结果；
  `WizardChecker.state()` 立刻返回，`checking` 为真表示后台正在重新检查；
- 所有系统访问（读设置、找 Lightroom、查进程、连接状态、AI 来源状态、自动启动状态、文件夹是否存在、起线程）都可注入，
  测试里全部用假对象。本模块不收任何路径或命令，路径只来自设置里已保存的值。
"""
from __future__ import annotations

import os
import threading
import time

READY, TODO, WAIT = "ready", "todo", "wait"
FOLDER, LIGHTROOM, PLUGIN, AI = "folder", "lightroom", "plugin", "ai"
ORDER = (FOLDER, LIGHTROOM, PLUGIN, AI)
TITLES = {FOLDER: "照片工作文件夹", LIGHTROOM: "Lightroom", PLUGIN: "Lightroom 插件", AI: "AI 助手"}
STALE_SECONDS = 5.0                    # 结果超过这么久，下一次取状态时顺带在后台重新检查

# 界面上的按钮对应的动作（页面只能点按钮，不能传路径）
ACT_FOLDER, ACT_LIGHTROOM, ACT_AI = "choose_folder", "choose_lightroom", "choose_ai"
LABELS = {ACT_FOLDER: "选择文件夹", ACT_LIGHTROOM: "选择 Lightroom 程序", ACT_AI: "更换 AI 来源"}
MSG_CHOOSE_AI = "请选择要使用的 AI。"
HINT_CHOOSE_AI = ("软件用的是你电脑上已经安装并登录的 AI 命令行，不保存你的账号。点下面的按钮选一个；"
                  "还没安装的也可以先选，选了之后这里会告诉你下一步怎么装、怎么登录。以后可以在“设置”里更换。")

MSG_CHECKING = "检查中…"
MSG_FAILED = "这一项暂时没能检查，请点“重新检查”。"
MSG_ALL_READY = "都准备好了，可以开始修图。"
HINT_OPEN_LR = ("请先打开 Lightroom。设置里有“自动启动 Lightroom”开关，打开后，以后启动本软件时会自动在后台打开它。"
                "这里不会替你打开。")
HINT_PLUGIN = ("请在 Lightroom 的 文件 → 增效工具管理器 里确认 LrMCP 显示“已安装并正在运行”；"
               "如果不是，点“重新载入增效工具”，等几秒再点下面的“重新检查”。")


def _item(key: str, state: str, text: str, hint: str = "", action: str = "") -> dict:
    return {"id": key, "title": TITLES[key], "state": state, "text": text, "hint": hint,
            "action": action, "action_label": LABELS.get(action, "")}


def decide(wizard_done: bool, items: list[dict]) -> dict:
    """启动时的决定。open：要不要自动弹出向导；mark_done：全部就绪时把 wizard_done 置真（不弹）。
    没选工作文件夹、或还没选 AI 来源时必弹，不管 wizard_done；其余情况只在第一次（wizard_done 为假）且有任一项需要处理时弹。
    “等待”不算需要处理（比如 Lightroom 正在自动启动、插件正在连接），避免白白弹出。"""
    by_id = {i["id"]: i for i in items}
    folder_bad = by_id.get(FOLDER, {}).get("state") == TODO
    ai_unchosen = bool(by_id.get(AI, {}).get("need_choice"))
    any_todo = any(i["state"] == TODO for i in items)
    all_ready = bool(items) and all(i["state"] == READY for i in items)
    opening = folder_bad or ai_unchosen or (not wizard_done and any_todo)
    return {"open": opening, "mark_done": (not opening) and (not wizard_done) and all_ready}


class WizardChecker:
    """四项检查的执行与缓存。

    get_settings()        -> 设置字典（只读 base_folder / lightroom_path）
    find_lightroom(custom)-> Lightroom.exe 路径或 None
    is_running()          -> Lightroom 是否在运行
    get_connection()      -> Backend.status() 的结果（state/connected/plugin_version）
    get_provider()        -> {"name","available","state","reason","next_step"}（当前选中的 AI 来源）；
                             还没选择时是 {"chosen": False, "choices": [每个可选来源的 id/name/short_name/状态/privacy_notice]}
    get_autolaunch()      -> AutoLaunch.state()：自动启动进行中时，Lightroom/插件显示“等待”而不是“需要处理”
    spawn(fn)             -> 起后台线程（测试里可换成同步或手动执行）
    """

    def __init__(self, get_settings, *, find_lightroom, is_running, get_connection, get_provider,
                 get_autolaunch=lambda: {"state": "idle"}, isdir=os.path.isdir, spawn=None, clock=time.monotonic):
        self._settings, self._find, self._running = get_settings, find_lightroom, is_running
        self._conn, self._provider, self._autolaunch = get_connection, get_provider, get_autolaunch
        self._isdir, self._clock = isdir, clock
        self._spawn = spawn or self._spawn_thread
        self._lock = threading.Lock()
        self._checking = False
        self._snapshot: list[dict] | None = None
        self._at = 0.0

    @staticmethod
    def _spawn_thread(fn) -> None:
        threading.Thread(target=fn, daemon=True).start()

    # ---- 对外 ------------------------------------------------------
    def state(self, refresh: bool = False) -> dict:
        """立刻返回上一次的结果（没有结果时是“检查中”的占位）；需要时在后台启动一次重新检查，从不阻塞。"""
        start = False
        with self._lock:
            stale = self._snapshot is None or self._clock() - self._at > STALE_SECONDS
            if (refresh or stale) and not self._checking:
                self._checking = True
                start = True
            items, checking = self._snapshot, self._checking
        if start:
            try:
                self._spawn(self._run)
            except Exception:                            # noqa: BLE001 - 起不了线程就当没检查，不卡住界面
                with self._lock:
                    self._checking = False
            with self._lock:                             # 线程可能已经（同步地）做完，取最新的
                items, checking = self._snapshot, self._checking
        return self._view(items, checking)

    def _view(self, items, checking: bool) -> dict:
        done = bool((self._settings() or {}).get("wizard_done") is True)
        if items is None:
            items = [_item(k, WAIT, MSG_CHECKING) for k in ORDER]
            return {"items": items, "ready": False, "checking": checking, "wizard_done": done, "auto_open": False,
                    "mark_done": False, "message": MSG_CHECKING}
        ready = all(i["state"] == READY for i in items)
        d = decide(done, items)
        return {"items": [dict(i) for i in items], "ready": ready, "checking": checking, "wizard_done": done,
                "auto_open": d["open"], "mark_done": d["mark_done"], "message": MSG_ALL_READY if ready else ""}

    def invalidate(self) -> None:
        """设置变了（选了文件夹/Lightroom）：下一次取状态时重新检查。"""
        with self._lock:
            self._at = float("-inf")

    # ---- 后台检查 --------------------------------------------------
    def _run(self) -> None:
        try:
            items = self.check()
        finally:
            with self._lock:
                self._checking = False
        with self._lock:
            self._snapshot, self._at = items, self._clock()

    def check(self) -> list[dict]:
        """同步做完四项检查（测试直接调用）。每一项出任何错都只影响那一项。"""
        s = self._settings() or {}
        out: dict[str, dict] = {}
        out[FOLDER] = self._safe(FOLDER, lambda: self._check_folder(s))
        out[LIGHTROOM] = self._safe(LIGHTROOM, lambda: self._check_lightroom(s))
        out[PLUGIN] = self._safe(PLUGIN, lambda: self._check_plugin(out[LIGHTROOM]))
        out[AI] = self._safe(AI, self._check_ai)
        return [out[k] for k in ORDER]

    @staticmethod
    def _safe(key: str, fn) -> dict:
        try:
            return fn()
        except Exception:                                # noqa: BLE001
            return _item(key, TODO, MSG_FAILED)

    def _check_folder(self, s: dict) -> dict:
        base = s.get("base_folder")
        base = base.strip() if isinstance(base, str) else ""
        if not base:
            return _item(FOLDER, TODO, "还没有选择照片工作文件夹。",
                         "导入的照片会复制到这个文件夹里，原片不会被移动或删除。请选一个空间够用的位置。", ACT_FOLDER)
        if not self._isdir(base):
            return _item(FOLDER, TODO, f"之前选的文件夹找不到了：{base}",
                         "可能是被移动或删除了，或者所在的移动硬盘没接上。接好硬盘，或重新选择一个文件夹。", ACT_FOLDER)
        return _item(FOLDER, READY, f"已选择：{base}")

    def _autolaunching(self) -> bool:
        try:
            return (self._autolaunch() or {}).get("state") in ("starting", "already_running")
        except Exception:                                # noqa: BLE001
            return False

    def _connection(self) -> dict:
        try:
            return self._conn() or {}
        except Exception:                                # noqa: BLE001
            return {}

    def _check_lightroom(self, s: dict) -> dict:
        conn = self._connection()
        if conn.get("connected") or self._running():     # 插件都连上了，Lightroom 一定在运行（查进程偶尔会失败）
            return _item(LIGHTROOM, READY, "Lightroom 正在运行。")
        if self._autolaunching():
            return _item(LIGHTROOM, WAIT, "正在自动启动 Lightroom，请稍候…")
        found = self._find(s.get("lightroom_path") or "")
        if found:
            return _item(LIGHTROOM, TODO, "已找到 Lightroom 程序，但它还没有打开。", HINT_OPEN_LR)
        return _item(LIGHTROOM, TODO, "没有找到 Lightroom 程序，它也没有在运行。",
                     "如果已经安装，请点“选择 Lightroom 程序”，找到安装目录里的 Lightroom.exe；也可以直接手动打开 Lightroom。",
                     ACT_LIGHTROOM)

    def _check_plugin(self, lr: dict) -> dict:
        if lr["state"] != READY:
            return _item(PLUGIN, WAIT, "等待 Lightroom。", "Lightroom 打开之后才能检查插件。")
        conn = self._connection()
        if conn.get("connected"):
            ver = conn.get("plugin_version")
            return _item(PLUGIN, READY, "插件已连接" + (f"（版本 {ver}）。" if ver else "。"))
        if conn.get("state") == "connecting" or self._autolaunching():
            return _item(PLUGIN, WAIT, "正在连接 Lightroom 的插件，请稍候…")
        return _item(PLUGIN, TODO, "Lightroom 已经打开，但插件还没连上。", HINT_PLUGIN)

    @staticmethod
    def _choice(c: dict) -> dict:
        """向导里的一个可选来源：按钮文字、状态（已安装并已登录 / 已安装但尚未登录 / 未安装，用来源自己的文案）、数据去向提示。"""
        short = c.get("short_name") or c.get("name") or c["id"]
        return {"id": c["id"], "label": f"使用 {short}", "name": c.get("name") or short,
                "status": c.get("reason") or "状态未知。", "ok": bool(c.get("available")),
                "privacy": c.get("privacy_notice") or ""}

    def _check_ai(self) -> dict:
        p = self._provider() or {}
        if p.get("chosen") is False:                     # 第一次使用：由用户自己选，软件不替用户定
            item = _item(AI, TODO, MSG_CHOOSE_AI, HINT_CHOOSE_AI)
            item["need_choice"] = True
            item["choices"] = [self._choice(c) for c in p.get("choices") or [] if isinstance(c, dict) and c.get("id")]
            return item
        name = p.get("name") or "AI 来源"
        title_text = f"{name}：" + (p.get("reason") or "状态未知。")
        if p.get("available"):
            return _item(AI, READY, title_text, p.get("next_step") or "", ACT_AI)
        hint = p.get("next_step") or "请到设置里换一个可用的 AI 来源，或按上面的提示处理。"
        return _item(AI, TODO, title_text, hint, ACT_AI)
