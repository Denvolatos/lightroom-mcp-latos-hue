# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""自动重建通道的保护（1.1.1）：有在途命令时不重建；借用模式（常驻 claude）下只有 Lightroom 在运行才重建，并按指数退避。"""
import json
import threading
import time

import backend as be
import lr_service as ls
from adjustments import AdjustmentTracker
from lr_service import LrService


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class SlowBridge:
    connected = False

    def __init__(self):
        self.release = threading.Event()
        self.started = threading.Event()

    def call(self, command, params=None, timeout=30):
        self.started.set()
        self.release.wait(5)
        return {}


def test_inflight_counts_calls_and_blocks_local_restart():
    b = SlowBridge()
    lr = LrService(bridge=b, edit_service=object())
    t = threading.Thread(target=lambda: lr.develop_of("P1"))
    t.start()
    assert b.started.wait(2)
    assert lr.inflight == 1
    assert lr.restart() is False and lr.restart_count == 0                  # 命令还在执行：不拆通道
    b.release.set()
    t.join(5)
    assert lr.inflight == 0


def remote(tmp_path, running, clock):
    state = tmp_path / "s.json"
    state.write_text(json.dumps({"t": time.time(), "connected": False}), encoding="utf-8")
    hooks = []
    lr = LrService(state_file=state, rpc_token="tok", restart_hook=lambda: hooks.append(1), lr_running=lambda: running["v"],
                   clock=clock)
    lr.start()
    return lr, hooks, state


def test_borrowed_mode_does_not_kill_claude_when_lightroom_is_closed(tmp_path):
    clock, running = Clock(), {"v": False}
    lr, hooks, _ = remote(tmp_path, running, clock)
    for _ in range(10):                                                     # Lightroom 没开：每 30 秒一次也不重建
        clock.t += 30
        assert lr.restart() is False
    assert hooks == []
    running["v"] = True
    assert lr.restart() is True and hooks == [1]


def test_borrowed_mode_backs_off_exponentially_and_resets_when_connected(tmp_path):
    clock, running = Clock(), {"v": True}
    lr, hooks, state = remote(tmp_path, running, clock)
    times = []
    for _ in range(40):
        clock.t += 30
        if lr.restart():
            times.append(clock.t)
    gaps = [b - a for a, b in zip(times, times[1:])]
    assert gaps[:4] == [60, 120, 240, 480] and all(g <= ls.REBUILD_BACKOFF_MAX + 30 for g in gaps)
    state.write_text(json.dumps({"t": time.time(), "connected": True}), encoding="utf-8")
    assert lr.connected                                                     # 连上：退避回到起点
    clock.t += 1
    assert lr.restart() is True
    clock.t += 30
    assert lr.restart() is False
    clock.t += 31
    assert lr.restart() is True


class Lr:
    connected = False
    plugin_version = None

    def __init__(self):
        self.inflight, self.restarts = 0, 0

    def restart(self):
        self.restarts += 1
        return True

    def selected_photo(self):
        return None


class Sess:
    alive, busy, spawned_at = True, False, 0.0

    def ensure_running(self):
        return True


def test_backend_does_not_restart_while_a_command_is_in_flight():
    clock, lr = Clock(), Lr()
    b = be.Backend(lr, Sess(), AdjustmentTracker(), lambda e: None, state_file=None, clock=clock, cleaner=lambda: None)
    lr.inflight = 1                                                         # 比如正在导出一张大图
    for _ in range(5):
        clock.t += 40
        b.tick()
    assert lr.restarts == 0 and "restart_lr" not in b.events
    lr.inflight = 0
    clock.t += 40
    b.tick()
    assert lr.restarts == 1
