# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""端口选择与失效公告清理（只在 app/ 内处理，不改 server/ 与 plugin/）。

背景（实测，见 DEV_NOTES）：插件对每个服务端口各有一个轮询任务。服务关闭后，若很快（约 12 秒内）又有新服务占用同一个端口，
旧轮询任务还握着旧口令，要等最长 10 秒的长轮询结束并遭遇一次 401 后才重新读取口令，新服务要 8–11 秒才被发现，
超过服务端等待连接的 6 秒，表现为“Lightroom 没连上”。做法：端口按“最久未使用”优先，避免马上复用；并清理失效公告。
"""
from __future__ import annotations

import json
import os
import socket
import time
from pathlib import Path

HOST = "127.0.0.1"
FIRST_PORT, PORT_COUNT = 58770, 20
HOME = Path.home() / "LrMcp"
SERVERS_DIR = HOME / "servers"
STATE_DIR = HOME / "app_state"
PORT_LOG = STATE_DIR / "port_usage.json"


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def port_order(usage_file: Path = PORT_LOG) -> list[int]:
    """候选端口顺序：从未用过的最先，其次按上次使用时间从早到晚；58770（兼容旧插件的口令文件）放最后。"""
    usage = _load(usage_file)
    ports = [p for p in range(FIRST_PORT + 1, FIRST_PORT + PORT_COUNT)]
    ports.sort(key=lambda p: float(usage.get(str(p), 0) or 0))
    return ports + [FIRST_PORT]


def note_port_used(port: int, usage_file: Path = PORT_LOG, now: float | None = None) -> None:
    try:
        usage_file.parent.mkdir(parents=True, exist_ok=True)
        usage = _load(usage_file)
        usage[str(port)] = now if now is not None else time.time()
        tmp = usage_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(usage), encoding="utf-8")
        os.replace(tmp, usage_file)
    except OSError:
        pass


def _listening(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((HOST, port)) == 0


def clean_stale_announcements(servers_dir: Path = SERVERS_DIR, listening=_listening) -> list[int]:
    """删除“端口上已没有服务”的公告文件（被强制结束的进程不会自己清理）。返回被删除的端口。
    公告是在端口绑定之后才写的，所以没人监听的公告一定是失效的。连续两次探测都无人监听才删，避免误删刚启动的服务。"""
    removed: list[int] = []
    for f in list(servers_dir.glob("*.txt")):
        try:
            port = int(f.stem)
        except ValueError:
            continue
        if listening(port) or listening(port):
            continue
        try:
            f.unlink()
            removed.append(port)
        except OSError:
            pass
    return removed


# ---------------------------------------------------------------- 旧版服务（1.1.1）
# 用户电脑上可能还开着以前版本的 lrmcp 服务（单独安装的 lrmcp.exe，或开发时 python 运行的 lightroom_mcp），
# 插件对每个登记的服务都轮询，旧服务的长轮询会让 Lightroom 每条命令慢约 10 秒。环境检查里找出来，用户点按钮才结束它们。
STILL_ACTIVE = 259
_CMDLINE_CACHE: dict[int, str] = {}


def read_announcement(path: Path) -> dict:
    """读一个 servers/<端口>.txt（每行 key=value：port / token / pid / version）。读不出返回 {}。"""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    out = {}
    for line in text.splitlines():
        k, sep, v = line.partition("=")
        if sep:
            out[k.strip()] = v.strip()
    return out


def version_tuple(v) -> tuple | None:
    try:
        parts = tuple(int(x) for x in str(v).strip().split("."))
    except (TypeError, ValueError):
        return None
    return parts if parts else None


def is_older(version, current: str) -> bool:
    """登记的版本是否比当前软件旧。没写版本或写得看不懂的也算旧（现在的服务都会写版本）。"""
    cur, v = version_tuple(current), version_tuple(version)
    if cur is None:
        return False
    if v is None:
        return True
    n = max(len(cur), len(v))
    return v + (0,) * (n - len(v)) < cur + (0,) * (n - len(cur))


def is_lrmcp_process(info: dict | None) -> bool:
    """只认这两种：进程名是 lrmcp.exe；或者是 python 并且命令行里运行的是 lightroom_mcp。其他一律不动。"""
    if not info:
        return False
    name = os.path.basename(str(info.get("name") or "")).lower()
    if name == "lrmcp.exe":
        return True
    if name.startswith("python") and name.endswith(".exe"):
        return "lightroom_mcp" in str(info.get("cmdline") or "").lower()
    return False


def _cmdline(pid: int) -> str:
    """进程命令行（只在进程名是 python 时才查；按进程号缓存）。"""
    if pid in _CMDLINE_CACHE:
        return _CMDLINE_CACHE[pid]
    import subprocess
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
                           capture_output=True, text=True, timeout=10, check=False,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        out = (r.stdout or "").strip()
    except (OSError, ValueError, subprocess.SubprocessError):
        return ""
    _CMDLINE_CACHE[pid] = out
    return out


def process_info(pid: int) -> dict | None:
    """进程还活着就返回 {"pid", "name": 完整程序路径, "cmdline"}，否则（或查不了）返回 None。只读，不结束任何进程。"""
    if os.name != "nt" or not isinstance(pid, int) or pid <= 0:
        return None
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    h = k.OpenProcess(0x1000, False, pid)                  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return None
    try:
        code = wintypes.DWORD()
        if not k.GetExitCodeProcess(h, ctypes.byref(code)) or code.value != STILL_ACTIVE:
            return None
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        name = buf.value if k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else ""
    finally:
        k.CloseHandle(h)
    base = os.path.basename(name).lower()
    cmd = _cmdline(pid) if base.startswith("python") else ""
    return {"pid": pid, "name": name, "cmdline": cmd}


def kill_process(pid: int) -> bool:
    """结束一个进程（只给 stop_old_servers 用，调用前已核对过进程名）。"""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.OpenProcess.restype = wintypes.HANDLE
    h = k.OpenProcess(0x0001, False, pid)                  # PROCESS_TERMINATE
    if not h:
        return False
    try:
        return bool(k.TerminateProcess(h, 1))
    finally:
        k.CloseHandle(h)


def find_old_servers(current_version: str, servers_dir: Path = SERVERS_DIR, proc_info=process_info) -> list[dict]:
    """登记文件里、版本比当前旧、进程还活着并且确实是 lrmcp 的服务。返回 [{"port","pid","version","file","name"}]。
    版本不旧的（包括本软件自己的服务）根本不查进程。"""
    found: list[dict] = []
    try:
        files = sorted(servers_dir.glob("*.txt"))
    except OSError:
        return found
    for f in files:
        info = read_announcement(f)
        if not info or not is_older(info.get("version"), current_version):
            continue
        try:
            pid = int(info.get("pid") or 0)
        except ValueError:
            continue
        if pid <= 0 or pid == os.getpid():
            continue
        try:
            proc = proc_info(pid)
        except Exception:                                   # noqa: BLE001
            proc = None
        if not is_lrmcp_process(proc):
            continue
        found.append({"port": info.get("port") or f.stem, "pid": pid, "version": info.get("version") or "",
                      "file": f, "name": os.path.basename(str(proc.get("name") or ""))})
    return found


def stop_old_servers(current_version: str, servers_dir: Path = SERVERS_DIR, proc_info=process_info,
                     kill=kill_process) -> dict:
    """结束旧版服务并删除它们的登记文件。动手前重新查一遍、再核对一次进程名（不符合就不动）。
    返回 {"stopped": [端口], "failed": [端口]}。"""
    stopped, failed = [], []
    for s in find_old_servers(current_version, servers_dir, proc_info):
        try:
            again = proc_info(s["pid"])
        except Exception:                                   # noqa: BLE001
            again = None
        if not is_lrmcp_process(again):
            continue                                        # 进程已经不在或者换成了别的程序：不动
        try:
            ok = bool(kill(s["pid"]))
        except Exception:                                   # noqa: BLE001
            ok = False
        if not ok:
            failed.append(s["port"])
            continue
        try:
            Path(s["file"]).unlink(missing_ok=True)
        except OSError:
            pass
        stopped.append(s["port"])
    return {"stopped": stopped, "failed": failed}
