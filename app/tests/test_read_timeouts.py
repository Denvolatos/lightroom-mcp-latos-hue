# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""读取类调用的超时策略（1.1.0，对齐 PR #7 的“8→40 秒”）：周期性调用短超时，用户主动触发的才用长超时；
读取失败给界面的是分好类的一句话，异常原文只进日志。全部用假对象。"""
import logging
import threading

import pytest

import lr_service as ls
import main
from lr_service import LrService, friendly_read_error, patient


class FakeBridge:
    connected = True

    def __init__(self):
        self.timeouts = []
        self.boom = None

    def call(self, command, params=None, timeout=30.0):
        self.timeouts.append((command, timeout))
        if self.boom:
            raise self.boom
        if command == "list_selected":
            return {"active_id": "P1", "count": 1, "photos": [{"id": "P1", "name": "A.ARW"}]}
        if command == "status":
            return {"lightroom_version": "15.0"}
        return {"settings": {}}


def service():
    b = FakeBridge()
    return LrService(bridge=b, edit_service=object()), b


def test_policy_constants():
    assert ls.POLL_READ_TIMEOUT <= 10 and ls.DEVELOP_READ_TIMEOUT <= 20     # 周期性调用：原值附近
    assert ls.USER_READ_TIMEOUT == 40                                        # 用户可以等的操作：PR #7 的值
    assert ls.POLL_READ_TIMEOUT < ls.USER_READ_TIMEOUT


def test_periodic_reads_use_short_timeouts():
    svc, b = service()
    svc.selected_all(), svc.selected_photo(), svc.selected_detail(), svc.develop_of("P1")
    assert b.timeouts == [("list_selected", ls.POLL_READ_TIMEOUT)] * 3 + [("get_develop", ls.DEVELOP_READ_TIMEOUT)]


def test_user_triggered_reads_use_the_long_timeout_and_restore_afterwards():
    svc, b = service()
    with patient(svc):
        svc.selected_all(), svc.selected_detail(), svc.selected_photo()
        with patient(svc):                                          # 可以嵌套
            svc.develop_of("P1")
        svc.selected_all()
    svc.selected_all()
    assert [t for _, t in b.timeouts] == [40, 40, 40, 40, 40, ls.POLL_READ_TIMEOUT]


def test_patience_does_not_leak_to_other_threads():
    """用户在界面线程里等一个慢操作时，后台巡检线程的读取仍然是短超时。"""
    svc, b = service()
    seen = []
    with patient(svc):
        t = threading.Thread(target=lambda: (svc.selected_all(), seen.append(b.timeouts[-1][1])))
        t.start()
        t.join(5)
    assert seen == [ls.POLL_READ_TIMEOUT]


def test_patient_is_a_no_op_for_test_doubles():
    class Fake:
        pass
    with patient(Fake()):
        pass


def test_backend_tick_and_preview_paths_do_not_ask_for_patience():
    """巡检线程（Backend.refresh_photo）与预览线程（PreviewManager.refresh）不能出现 patient()。"""
    import inspect

    import backend
    import preview
    assert "patient(" not in inspect.getsource(backend)
    assert "patient(" not in inspect.getsource(preview.PreviewManager)


def test_user_paths_ask_for_patience():
    import inspect

    import export_service
    import library_service
    import pick_service
    for mod, n in ((export_service, 2), (pick_service, 2), (library_service, 2)):
        assert inspect.getsource(mod).count("with patient(self.lr)") == n


class BridgeTimeout(RuntimeError):
    pass


class PluginNotConnected(RuntimeError):
    pass


@pytest.mark.parametrize("exc,expect", [
    (BridgeTimeout("插件没有在 10 秒内回应命令 list_selected。"), ls.MSG_READ_TIMEOUT),
    (PluginNotConnected("x"), ls.MSG_READ_OFFLINE),
    (RuntimeError("C:\\Users\\someone\\LrMcp\\previews\\p.jpg token=abc123 port 49152"), ls.MSG_READ_FAILED),
    (OSError(13, "Permission denied", "C:\\secret\\file.jpg"), ls.MSG_READ_FAILED)])
def test_friendly_read_error_never_echoes_the_exception_text(exc, expect):
    msg = friendly_read_error(exc)
    assert msg == expect
    for leak in ("C:\\", "token", "abc123", "49152", "secret"):
        assert leak not in msg


def test_selected_detail_failure_keeps_details_in_the_log_only(caplog):
    svc, b = service()
    b.boom = RuntimeError("C:\\Users\\someone\\LrMcp\\servers\\49152.txt token=abc123")
    with caplog.at_level(logging.WARNING, logger="latoshue.lr"):
        assert svc.selected_detail() is None
    assert svc.last_selected_error == ls.MSG_READ_FAILED
    assert "abc123" in caplog.text                                  # 详细原因在日志里
    b.boom = None
    assert svc.selected_detail()["id"] == "P1" and svc.last_selected_error is None


def test_about_does_not_ask_lightroom_at_startup():
    api = main.Api.__new__(main.Api)
    svc, b = service()
    api._lr = svc
    assert api._about(None)["lightroom_version"] is None and b.timeouts == []      # 启动时：界面在等，不问 Lightroom
    assert api._about(10)["lightroom_version"] == "15.0" and b.timeouts[-1][0] == "status"   # 打开设置时才问
