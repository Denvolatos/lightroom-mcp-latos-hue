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
