# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""启动界面：内容、交接逻辑（只显示一次、出错也能回到主界面、看门狗兜底）、窗口创建与失败回退、与 Api.ui_ready 的衔接。
全部使用假窗口对象：不会弹出任何窗口。"""
import threading
import types

import pytest

import settings as st
import splash as sp


# ---------------------------------------------------------------- 内容
def test_assets_exist_and_icon_is_png_data_uri():
    assert sp.ICON_ICO.is_file() and sp.ICON_PNG.is_file()
    uri = sp.icon_data_uri()
    assert uri.startswith("data:image/png;base64,") and len(uri) < 60_000        # 小图，内嵌即可


def test_html_has_name_version_and_progress_text():
    h = sp.splash_html("0.13.0", "正在检查环境…")
    assert "Latos Hue 修图助手" in h and "版本 0.13.0" in h and "正在检查环境…" in h
    assert "data:image/png;base64," in h and "setText" in h and "border-radius" in h


def test_html_escapes_and_survives_missing_icon():
    h = sp.splash_html("<b>1</b>", "<script>x</script>", icon_uri="")
    assert "<b>1</b>" not in h and "<script>x</script>" not in h
    assert 'class="ic"' in h                                                     # 没有图标也有占位，不报错
    assert sp.icon_data_uri(sp.ASSETS / "nope.png") == ""


def test_round_corners_never_raises_with_fake_window():
    class W:
        native = None
    assert sp.round_corners(W()) is False


# ---------------------------------------------------------------- 交接
@pytest.fixture(autouse=True)
def _no_min_wait(monkeypatch):
    monkeypatch.setattr(sp, "MIN_SECONDS", 0)          # 其余测试不等最短停留；下面专门测它


class FakeWin:
    def __init__(self, name, fail=()):
        self.name, self.fail, self.calls = name, set(fail), []
        self.done = threading.Event()

    def _do(self, what, *a):
        self.calls.append((what,) + a)
        self.done.set()
        if what in self.fail:
            raise RuntimeError(what)

    def show(self):
        self._do("show")

    def destroy(self):
        self._do("destroy")

    def evaluate_js(self, js):
        self._do("js", js)


class FakeTimer:
    """不真的计时：测试里手动调用 fire() 模拟"到点"。"""
    def __init__(self, seconds, fn):
        self.seconds, self.fn, self.started, self.cancelled, self.daemon = seconds, fn, False, False, False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def fire(self):
        self.fn()


def make(splash=None, main=None, **kw):
    splash = splash or FakeWin("splash")
    main = main or FakeWin("main")
    c = sp.SplashController(splash, main, timer_factory=FakeTimer, **kw)
    c.start()
    return c, splash, main


def finish_and_wait(c):
    assert c.finish() is True
    c._handover.join(5)


def test_finish_shows_main_then_closes_splash_once():
    c, s, m = make()
    finish_and_wait(c)
    assert m.calls == [("show",)] and s.calls == [("destroy",)]
    assert c.finish() is False and c.done                                       # 再次调用什么也不做
    assert m.calls == [("show",)] and s.calls == [("destroy",)]
    assert c._timer.cancelled


def test_set_text_goes_to_splash_as_json_string():
    c, s, m = make()
    c.set_text('正在启动"后台"服务…')
    assert s.done.wait(5)
    assert s.calls[0] == ("js", 'setText("正在启动\\"后台\\"服务…")')              # 引号被正确转义，不会注入脚本
    finish_and_wait(c)
    c.set_text("晚了")                                                           # 结束后的文字被忽略
    assert not [x for x in s.calls if x[0] == "js" and "晚了" in x[1]]


def test_watchdog_hands_over_even_if_page_never_reports_ready():
    c, s, m = make()
    assert c._timer.started and c._timer.seconds == sp.WATCHDOG_SECONDS
    c._timer.fire()
    c._handover.join(5)
    assert m.calls == [("show",)] and s.calls == [("destroy",)]


def test_errors_in_windows_never_escape_and_splash_still_closes():
    c, s, m = make(main=FakeWin("main", fail={"show"}), splash=FakeWin("splash", fail={"js"}))
    c.set_text("x")
    assert s.done.wait(5)                                                       # evaluate_js 抛错被吞掉
    finish_and_wait(c)
    assert ("destroy",) in s.calls                                              # 主窗口 show 失败也继续关闭启动窗口


def test_blocked_splash_call_does_not_block_handover_or_caller():
    gate = threading.Event()

    class Stuck(FakeWin):
        def evaluate_js(self, js):                                              # 模拟页面没加载好、调用一直阻塞
            self.calls.append(("js", js))
            gate.wait(10)

    s = Stuck("splash")
    c, _, m = make(splash=s)
    c.set_text("a")                                                             # 立即返回（只排队）
    finish_and_wait(c)
    assert m.calls == [("show",)] and ("destroy",) in s.calls
    gate.set()


def test_without_splash_window_finish_only_shows_main():
    m = FakeWin("main")
    c = sp.SplashController(None, m, timer_factory=FakeTimer)
    c.start()
    c.set_text("无事发生")
    finish_and_wait(c)
    assert m.calls == [("show",)]


# ---------------------------------------------------------------- 窗口创建
class Events:
    def __init__(self):
        self.handlers = []

    def __iadd__(self, h):
        self.handlers.append(h)
        return self


class CreatedWin:
    def __init__(self, title, kw):
        self.title, self.kw = title, kw
        self.events = types.SimpleNamespace(shown=Events(), closed=Events())


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "app_settings.json")
    monkeypatch.setattr(st.SettingsStore.__init__, "__defaults__", (None, lambda p: None))
    import main
    a = main.Api()
    yield a
    a._shutdown()


def test_setup_windows_main_first_hidden_then_frameless_splash(api):
    import main
    made = []

    def create(title, url=None, **kw):
        made.append(CreatedWin(title, dict(kw, url=url)))
        return made[-1]
    ctrl = main.setup_windows(api, create)
    assert [w.title for w in made] == ["修图助手", sp.TITLE]                      # 主窗口先创建（保证它是主窗口）
    assert made[0].kw["hidden"] is True and made[0].kw["js_api"] is api
    k = made[1].kw
    assert k["frameless"] and k["on_top"] and not k["resizable"] and (k["width"], k["height"]) == (sp.WIDTH, sp.HEIGHT)
    assert "js_api" not in k and st.APP_VERSION in k["html"] and k["url"] is None   # 启动窗口不带任何接口
    assert ctrl.splash is made[1] and ctrl.main is made[0] and api._splash is ctrl
    assert made[0].events.closed.handlers and made[1].events.shown.handlers


def test_setup_windows_falls_back_when_splash_creation_fails(api):
    import main
    calls = []

    def create(title, url=None, **kw):
        calls.append(title)
        if len(calls) == 2:
            raise RuntimeError("boom")
        return CreatedWin(title, kw)
    ctrl = main.setup_windows(api, create)
    assert ctrl.splash is None and ctrl.main is api._window                      # 没有启动窗口，之后只负责显示主窗口


def test_setup_windows_without_splash_shows_main_directly(api):
    import main
    made = []
    ctrl = main.setup_windows(api, lambda t, url=None, **kw: made.append(kw) or CreatedWin(t, kw), use_splash=False)
    assert ctrl is None and len(made) == 1 and made[0]["hidden"] is False and api._splash is None


# ---------------------------------------------------------------- 与 Api 衔接
def test_api_ui_ready_finishes_splash_once_and_is_safe_without_it(api):
    assert api.ui_ready() == {"ok": True}                                        # 没有启动界面时也安全
    c, s, m = make()
    api._splash = c
    assert api.ui_ready() == {"ok": True}
    c._handover.join(5)
    assert m.calls == [("show",)] and s.calls == [("destroy",)]
    api.ui_ready()                                                               # 重复调用无副作用
    assert m.calls == [("show",)]


def test_api_progress_text_is_forwarded(api):
    c, s, m = make()
    api._splash = c
    api._splash_text(sp.TEXT_SERVICES)
    assert s.done.wait(5) and sp.TEXT_SERVICES in s.calls[0][1]
    api._splash = None
    api._splash_text("没有启动界面也不报错")


def test_min_display_time_delays_handover_but_not_the_caller():
    now = [100.0]
    slept = []
    s, m = FakeWin("splash"), FakeWin("main")
    c = sp.SplashController(s, m, timer_factory=FakeTimer, min_seconds=3.5, clock=lambda: now[0], sleep=slept.append)
    c.start()
    now[0] = 100.8                                    # 主界面 0.8 秒就准备好了
    assert c.finish() is True
    c._handover.join(5)
    assert len(slept) == 1 and abs(slept[0] - 2.7) < 1e-6          # 还要再停 2.7 秒
    assert [x[0] for x in m.calls] == ["show"] and [x[0] for x in s.calls] == ["destroy"]


def test_min_display_time_not_waited_when_already_elapsed_or_no_splash():
    now = [0.0]
    slept = []
    s, m = FakeWin("splash"), FakeWin("main")
    c = sp.SplashController(s, m, timer_factory=FakeTimer, min_seconds=3.5, clock=lambda: now[0], sleep=slept.append)
    c.start()
    now[0] = 25.0                                     # 看门狗到点：早就超过最短停留
    finish_and_wait(c)
    assert slept == []
    c2 = sp.SplashController(None, FakeWin("main"), timer_factory=FakeTimer, min_seconds=3.5,
                             clock=lambda: 0.0, sleep=slept.append)
    c2.start()
    assert c2.finish() is True
    c2._handover.join(5)
    assert slept == []                                # 没有启动窗口就不等


def test_centered_origin_centres_in_work_area_and_clamps():
    assert sp.centered_origin((0, 0, 1920, 1040), 460, 280) == (730, 380)
    assert sp.centered_origin((1920, 0, 3840, 1080), 460, 280) == (2650, 400)        # 第二块显示器
    assert sp.centered_origin((0, 0, 300, 200), 460, 280) == (0, 0)                  # 窗口比工作区大：不出现负坐标


def test_center_window_never_raises_with_fake_window():
    class W:
        native = None
    assert sp.center_window(W()) is False
