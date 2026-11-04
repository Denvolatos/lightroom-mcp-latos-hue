# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""自动启动 Lightroom（0.13.0）：软件打开时，若设置里开着开关、Lightroom 还没在运行，就在后台把它最小化地启动起来。

- 只会启动固定的 Lightroom.exe：路径必须是本机盘符里真实存在的、文件名为 Lightroom.exe 的文件；
  不执行页面或用户传来的任何命令行，启动时不带参数；
- 用 tasklist 查是否已在运行（不弹窗）；启动用 STARTUPINFO + SW_SHOWMINNOACTIVE（最小化、不抢焦点、不弹控制台）；
- 软件退出时不关闭 Lightroom；找不到、启动失败、等不到插件连上，都只是给出温和提示，不报错、不崩溃。
所有对系统的访问（查进程、读注册表、启动进程、时钟）都可以注入，便于测试，测试里不会真的启动 Lightroom。
"""
from __future__ import annotations

import contextlib
import glob
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

EXE_NAME = "Lightroom.exe"
SW_SHOWMINNOACTIVE = 7                 # 最小化并显示，不激活（不抢焦点）
CONNECT_TIMEOUT = 120.0                # 启动后最多等多久让插件连上（插件每 2 秒扫描一次，Lightroom 本身启动也要时间）
POLL_SECONDS = 2.0
GRACE_SECONDS = 90.0                   # 软件刚启动 Lightroom 后的宽限期：这段时间插件还没加载，软件不会换端口重建通道
APP_PATHS_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\Lightroom.exe"

# 界面状态
IDLE, STARTING, CONNECTED, ALREADY, NOT_FOUND, FAILED, TIMEOUT = (
    "idle", "starting", "connected", "already_running", "not_found", "failed", "timeout")
MESSAGES = {
    IDLE: "",
    STARTING: "正在启动 Lightroom…",
    CONNECTED: "Lightroom 已连接",
    ALREADY: "Lightroom 已经在运行，正在连接…",
    NOT_FOUND: "没找到 Lightroom，请手动打开。也可以在设置里选择 Lightroom 的位置。",
    FAILED: "没能自动启动 Lightroom，请手动打开。",
    TIMEOUT: "Lightroom 已经打开，但插件还没连上。请在 Lightroom 的 文件 → 增效工具管理器 里确认 LrMCP 显示“已安装并正在运行”，必要时点“重新载入增效工具”。",
}


# ---------------------------------------------------------------- 路径校验与探测
def valid_lightroom_path(path) -> str | None:
    """合法返回规范化后的路径，否则返回 None。要求：字符串、本机盘符（不接受网络路径）、文件存在、文件名恰为 Lightroom.exe。"""
    if not isinstance(path, str):
        return None
    raw = path.strip().strip('"')
    if not raw or "\x00" in raw or raw.startswith(("\\\\", "//")):
        return None
    if not re.match(r"^[A-Za-z]:[\\/]", raw):
        return None
    try:
        p = Path(os.path.abspath(raw))
    except (OSError, ValueError):
        return None
    if p.name.lower() != EXE_NAME.lower() or not p.is_file():
        return None
    return str(p)


def _registry_app_path() -> str | None:
    """从 App Paths 注册表项读 Lightroom.exe 的路径（读不到返回 None）。"""
    try:
        import winreg
    except ImportError:
        return None
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            with winreg.OpenKey(hive, APP_PATHS_KEY) as k:
                return str(winreg.QueryValueEx(k, "")[0])
        except OSError:
            continue
    return None


def find_lightroom(custom: str = "", env=None, registry=_registry_app_path) -> str | None:
    """先用设置里用户自选的路径；否则查注册表 App Paths，再查 Program Files 下常见目录。找不到返回 None。"""
    env = os.environ if env is None else env
    c = valid_lightroom_path(custom) if custom else None
    if c:
        return c
    try:
        reg = valid_lightroom_path(registry() or "")
    except Exception:                                  # noqa: BLE001 - 注册表读不了不影响后面的探测
        reg = None
    if reg:
        return reg
    roots = []
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        v = env.get(var)
        if v and v not in roots:
            roots.append(v)
    for root in roots:
        for pattern in (os.path.join(glob.escape(root), "Adobe", "Adobe Lightroom Classic*", EXE_NAME),
                        os.path.join(glob.escape(root), "Adobe", "Lightroom Classic*", EXE_NAME)):
            for hit in sorted(glob.glob(pattern)):
                ok = valid_lightroom_path(hit)
                if ok:
                    return ok
    return None


# ---------------------------------------------------------------- 是否在运行 / 启动
def _no_window_flags() -> int:
    return getattr(subprocess, "CREATE_NO_WINDOW", 0)


def is_running(run=subprocess.run) -> bool:
    """用 tasklist 查 Lightroom.exe 是否在运行（隐藏窗口）。查询失败按“没在运行”处理——最坏是多启动一次，
    而 Lightroom 自己是单实例，再次启动只会把已有窗口带出来，所以不会开出第二个。"""
    try:
        r = run(["tasklist", "/FI", f"IMAGENAME eq {EXE_NAME}", "/NH", "/FO", "CSV"], capture_output=True, text=True,
                timeout=15, creationflags=_no_window_flags())
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return EXE_NAME.lower() in (r.stdout or "").lower()


def build_startupinfo(factory=None):
    """STARTUPINFO：dwFlags 带 STARTF_USESHOWWINDOW，wShowWindow=SW_SHOWMINNOACTIVE。非 Windows 返回 None。"""
    factory = factory or getattr(subprocess, "STARTUPINFO", None)
    if factory is None:
        return None
    si = factory()
    si.dwFlags |= getattr(subprocess, "STARTF_USESHOWWINDOW", 1)
    si.wShowWindow = SW_SHOWMINNOACTIVE
    return si


def clean_environment(env=None, own_dirs=None) -> dict:
    """给 Lightroom 用的干净环境变量：去掉本软件自己的目录和打包工具留下的变量。
    真机教训：用户选了 D:\Latos Hue 安装后，软件拉起的 Lightroom 把软件目录里的 VCRUNTIME140.dll 加载进了自己的进程，
    导致覆盖安装时报"拒绝访问"（文件被 Lightroom 占着），也有版本混用的风险。所以子进程看不到软件自己的目录。"""
    env = dict(os.environ if env is None else env)
    if own_dirs is None:
        own_dirs = [d for d in (getattr(sys, "_MEIPASS", None), os.path.dirname(sys.executable)) if d]
    own = [os.path.normcase(os.path.abspath(d)) for d in own_dirs]

    def is_own(entry: str) -> bool:
        if not entry.strip():
            return False
        e = os.path.normcase(os.path.abspath(entry.strip().strip('"')))
        return any(e == d or e.startswith(d + os.sep) for d in own)
    for key in [k for k in env if k.upper() == "PATH"]:
        env[key] = os.pathsep.join(x for x in env[key].split(os.pathsep) if not is_own(x))
    for key in [k for k in env if k.upper().startswith(("_PYI", "_MEIPASS")) or k.upper() in ("PYTHONHOME", "PYTHONPATH")]:
        del env[key]
    return env


_DLL_LOCK = threading.Lock()


@contextlib.contextmanager
def no_inherited_dll_directory(kernel32=None, frozen=None, restore_dir=None):
    """启动子进程期间，临时撤掉本进程的"附加 DLL 目录"（SetDllDirectory）。
    真机教训（1.0.2 仍未修好的真正原因）：打包后的软件启动时用 SetDllDirectory 把自己的 _internal 目录加进 DLL 搜索路径，
    Windows 会把这个路径带给它创建的子进程（子进程的 DllPath 字段）。Lightroom 因此从软件目录里加载了 VCRUNTIME140.dll，
    把文件占住，覆盖安装/卸载就报"拒绝访问"。所以在创建 Lightroom 进程的这一瞬间先清空，创建完立刻恢复（本进程自己
    以后还要按需加载 DLL）。只在打包后的 Windows 程序里生效；失败一律忽略。"""
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if not frozen:
        yield
        return
    try:
        if kernel32 is None:
            import ctypes
            kernel32 = ctypes.windll.kernel32
    except Exception:                                  # noqa: BLE001 - 不是 Windows：什么都不做
        yield
        return
    restore = restore_dir or getattr(sys, "_MEIPASS", None) or os.path.dirname(sys.executable)
    with _DLL_LOCK:
        reset = False
        try:
            reset = bool(kernel32.SetDllDirectoryW(None))
        except Exception:                              # noqa: BLE001
            reset = False
        try:
            yield
        finally:
            if reset:
                try:
                    kernel32.SetDllDirectoryW(restore)
                except Exception:                      # noqa: BLE001
                    pass


def launch_minimized(exe: str, popen=subprocess.Popen, env=None) -> bool:
    """最小化、不抢焦点地启动 exe；启动后不等待、不接管（软件退出时 Lightroom 继续运行）。路径不合法直接拒绝。"""
    ok = valid_lightroom_path(exe)
    if not ok:
        return False
    try:
        with no_inherited_dll_directory():
            popen([ok], startupinfo=build_startupinfo(), creationflags=_no_window_flags(),
                  stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True,
                  cwd=str(Path(ok).parent), env=clean_environment() if env is None else env)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return True


# ---------------------------------------------------------------- 自动启动流程
class AutoLaunch:
    """软件启动时跑一次：开关开 + 没在运行 -> 启动 -> 等插件连上。状态经 emit 推给界面，也可用 state() 取。"""

    def __init__(self, get_settings, connected_fn, emit, *, running_fn=is_running, find_fn=find_lightroom,
                 launch_fn=launch_minimized, sleep=time.sleep, clock=time.monotonic,
                 timeout: float = CONNECT_TIMEOUT, poll: float = POLL_SECONDS, grace: float = GRACE_SECONDS):
        self._settings = get_settings            # () -> 设置字典
        self._connected = connected_fn           # () -> bool：插件是否已连上
        self._emit = emit
        self._running, self._find, self._launch = running_fn, find_fn, launch_fn
        self._sleep, self._clock = sleep, clock
        self.timeout, self.poll, self.grace = timeout, poll, grace
        self._grace_until: float | None = None   # 宽限期结束时间（None = 没有宽限期）
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._state = {"state": IDLE, "message": ""}

    def state(self) -> dict:
        with self._lock:
            return dict(self._state)

    def in_grace(self) -> bool:
        """软件刚自动启动了 Lightroom（或发现它刚开着、正在等插件连上）的前 GRACE_SECONDS 秒内为 True。
        已连上、失败、超时、没开自动启动时都是 False。Backend 用它暂停“换端口重建通道”。"""
        with self._lock:
            if self._state["state"] not in (STARTING, ALREADY) or self._grace_until is None:
                return False
            return self._clock() < self._grace_until

    def _set(self, state: str) -> None:
        with self._lock:
            self._state = {"state": state, "message": MESSAGES[state]}
            ev = {"type": "lr_launch", **self._state}
        try:
            self._emit(ev)
        except Exception:                        # noqa: BLE001 - 推送失败不影响流程
            pass

    def start(self) -> bool:
        """开关为开才起后台线程；返回是否起了线程。"""
        data = self._settings() or {}
        if data.get("auto_launch_lightroom") is not True or self._thread is not None:
            return False
        self._thread = threading.Thread(target=self.run, daemon=True)
        self._thread.start()
        return True

    def _begin_grace(self) -> None:
        with self._lock:
            self._grace_until = self._clock() + self.grace

    def stop(self) -> None:
        self._stop.set()                         # 只停止等待；不会去关闭 Lightroom

    def run(self) -> str:
        """同步执行整个流程，返回最终状态（测试直接调用）。任何异常都落到 FAILED，不向外抛。"""
        try:
            return self._run()
        except Exception:                        # noqa: BLE001
            self._set(FAILED)
            return FAILED

    def _run(self) -> str:
        data = self._settings() or {}
        if data.get("auto_launch_lightroom") is not True:
            return IDLE
        if self._running():
            self._begin_grace()
            self._set(ALREADY)
        else:
            exe = self._find(data.get("lightroom_path") or "")
            if not exe:
                self._set(NOT_FOUND)
                return NOT_FOUND
            self._begin_grace()
            self._set(STARTING)
            if not self._launch(exe):
                self._set(FAILED)
                return FAILED
        deadline = self._clock() + self.timeout
        while not self._stop.is_set():
            if self._connected():
                self._set(CONNECTED)
                return CONNECTED
            if self._clock() >= deadline:
                self._set(TIMEOUT)
                return TIMEOUT
            self._sleep(self.poll)
        return self.state()["state"]
