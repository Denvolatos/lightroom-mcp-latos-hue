# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""1.1.1 单实例：第二次打开时把已有窗口拿到前台后退出；辅助子命令不受影响；检查失败不阻止启动。"""
import os
import secrets

import pytest

import main
import run_latoshue


class FakeKernel:
    def __init__(self, handle=1, err=0, boom=False):
        self.handle, self.err, self.boom, self.closed = handle, err, boom, []

    def CreateMutexW(self, attrs, owner, name):
        if self.boom:
            raise OSError("no")
        self.name = name
        return self.handle

    def last_error(self):
        return self.err

    def CloseHandle(self, h):
        self.closed.append(h)


def test_first_instance_gets_the_mutex():
    k = FakeKernel()
    assert main.acquire_single_instance(kernel32=k) is True and k.name == main.MUTEX_NAME


def test_second_instance_is_detected_and_closes_its_handle():
    k = FakeKernel(handle=7, err=main.ERROR_ALREADY_EXISTS)
    assert main.acquire_single_instance(kernel32=k) is False and k.closed == [7]


@pytest.mark.parametrize("k", [FakeKernel(handle=0), FakeKernel(boom=True)])
def test_failures_never_block_startup(k):
    assert main.acquire_single_instance(kernel32=k) is True


@pytest.mark.skipif(os.name != "nt", reason="Windows 命名互斥锁")
def test_real_windows_mutex_detects_second_owner():
    name = "Local\\LatosHue.Test." + secrets.token_hex(6)
    keep = main._instance_handle
    try:
        assert main.acquire_single_instance(name) is True
        assert main.acquire_single_instance(name) is False          # 同名互斥锁已存在
    finally:
        main._instance_handle = keep


class FakeUser32:
    def __init__(self, windows):
        self.windows, self.calls = windows, []      # {title: (hwnd, visible, iconic)}

    def FindWindowW(self, cls, title):
        return self.windows.get(title, (0, False, False))[0]

    def _w(self, hwnd):
        return next(v for v in self.windows.values() if v[0] == hwnd)

    def IsWindowVisible(self, hwnd):
        return self._w(hwnd)[1]

    def IsIconic(self, hwnd):
        return self._w(hwnd)[2]

    def ShowWindow(self, hwnd, cmd):
        self.calls.append(("show", hwnd, cmd))

    def SetForegroundWindow(self, hwnd):
        self.calls.append(("front", hwnd))


def test_activate_restores_and_fronts_the_main_window():
    u = FakeUser32({main.MAIN_TITLE: (11, True, True)})
    assert main.activate_existing_window(user32=u) is True
    assert u.calls == [("show", 11, 9), ("front", 11)]


def test_activate_falls_back_to_splash_while_main_window_is_hidden():
    import splash
    u = FakeUser32({main.MAIN_TITLE: (11, False, False), splash.TITLE: (12, True, False)})
    assert main.activate_existing_window(user32=u) is True and u.calls == [("front", 12)]


def test_main_exits_without_creating_anything_when_already_running(monkeypatch):
    activated = []
    monkeypatch.setattr(main, "acquire_single_instance", lambda: False)
    monkeypatch.setattr(main, "activate_existing_window", lambda: activated.append(1) or True)
    monkeypatch.setattr(main, "Api", lambda: pytest.fail("不应再创建第二个实例"))
    main.main()
    assert activated == [1]


def test_helper_subcommands_do_not_touch_the_mutex(monkeypatch):
    monkeypatch.setattr(main, "acquire_single_instance", lambda: pytest.fail("辅助子命令不应检查单实例"))
    ran = []
    table = {"--lr-launcher": lambda: ran.append("lr") or 0}
    assert run_latoshue.run(["--lr-launcher"], commands=table, gui=lambda: pytest.fail("不应启动界面")) == 0
    assert ran == ["lr"]
