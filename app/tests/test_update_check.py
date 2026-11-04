"""软件检查更新（0.15.0）：版本解析、只认 hue-v、过滤草稿/预发布、缓存、静默失败、关闭时零请求、
打开页面的网址校验、接口不暴露参数、旧设置文件兼容。全部用假 HTTP / 假浏览器 / 假线程，不联网、不开窗口。"""
import inspect
import json

import pytest

import settings as st
import update_check as uc

REPO_URL = "https://github.com/Denvolatos/lightroom-mcp-win/releases/tag/"


def rel(tag, **kw):
    d = {"tag_name": tag, "draft": False, "prerelease": False, "html_url": REPO_URL + tag}
    d.update(kw)
    return d


def body(*releases) -> bytes:
    return json.dumps(list(releases)).encode()


class Net:
    """假 HTTP：记录请求次数；可设返回内容或抛错。"""
    def __init__(self, data=b"[]", exc=None):
        self.data, self.exc, self.calls = data, exc, []

    def __call__(self, url):
        self.calls.append(url)
        if self.exc:
            raise self.exc
        return self.data


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def make(tmp_path, net=None, *, current="0.15.0", enabled=True, clock=None, opened=None):
    net = net if net is not None else Net()
    jobs = []
    c = uc.AppUpdateChecker(current, lambda: enabled, http_get=net, open_url=(opened.append if opened is not None else (lambda u: None)),
                            spawn=jobs.append, clock=clock or Clock(), cache_file=tmp_path / "c.json")
    return c, net, jobs


def run_jobs(jobs):
    while jobs:
        jobs.pop(0)()


# ---------------------------------------------------------------- 版本解析与比较
@pytest.mark.parametrize("text,want", [("hue-v1.2.3", (1, 2, 3)), ("1.2.3", (1, 2, 3)), (" 0.15.0 ", (0, 15, 0)),
                                       ("hue-v0.0.0", (0, 0, 0))])
def test_parse_version_ok(text, want):
    assert uc.parse_version(text) == want


@pytest.mark.parametrize("text", ["v1.2.3", "hue-v1.2", "hue-v1.2.3.4", "hue-v1.2.3-beta", "hue-vx.y.z", "HUE-V1.2.3", "", "hue-v",
                                  "1.2.3\n4", "hue-v1.2.3 rc1", None, 5, [], {"a": 1}, "hue-v-1.2.3", "hue-v99999.1.1"])
def test_parse_version_bad_never_raises(text):
    assert uc.parse_version(text) is None


def test_release_version_requires_prefix():
    assert uc.release_version("hue-v1.0.0") == (1, 0, 0)
    assert uc.release_version("v0.14.0") is None and uc.release_version("1.0.0") is None
    assert uc.release_version(None) is None


def test_is_newer_numeric_not_lexicographic():
    assert uc.is_newer("hue-v0.16.0", "0.15.0") and uc.is_newer("1.0.0", "0.99.99")
    assert uc.is_newer("0.10.0", "0.9.0")
    assert not uc.is_newer("0.15.0", "0.15.0") and not uc.is_newer("0.14.0", "0.15.0")
    assert not uc.is_newer("garbage", "0.15.0") and not uc.is_newer("1.0.0", "dev")


# ---------------------------------------------------------------- 挑选 release
def test_pick_only_hue_prefix_ignores_plugin_tags():
    assert uc.pick_latest([rel("v0.15.0"), rel("v9.9.9"), rel("1.2.3")]) is None
    r = uc.pick_latest([rel("v9.9.9"), rel("hue-v1.0.0"), rel("hue-v1.2.0"), rel("hue-v1.10.0"), rel("hue-v1.9.0")])
    assert r == {"latest": "1.10.0", "url": REPO_URL + "hue-v1.10.0"}


def test_pick_skips_draft_prerelease_and_junk():
    junk = ["x", 5, None, [], {"tag_name": 5}, {"tag_name": "hue-v9.0.0"}, rel("hue-vfoo"), rel("hue-v9.1"), rel("hue-v9.0.0-rc1")]
    r = uc.pick_latest(junk + [rel("hue-v8.0.0", draft=True), rel("hue-v7.0.0", prerelease=True), rel("hue-v1.0.0")])
    assert r["latest"] == "1.0.0"
    assert uc.pick_latest([]) is None
    with pytest.raises(ValueError):
        uc.pick_latest({"tag_name": "hue-v1.0.0"})


def test_pick_skips_release_with_bad_url():
    bad = rel("hue-v5.0.0", html_url="https://evil.example/Denvolatos/lightroom-mcp-win/releases/tag/hue-v5.0.0")
    assert uc.pick_latest([bad, rel("hue-v1.0.0")])["latest"] == "1.0.0"


# ---------------------------------------------------------------- 网址校验
@pytest.mark.parametrize("url", [REPO_URL + "hue-v1.0.0", "https://github.com/Denvolatos/lightroom-mcp-win/releases/latest"])
def test_url_ok(url):
    assert uc.valid_release_url(url)


@pytest.mark.parametrize("url", [
    "http://github.com/Denvolatos/lightroom-mcp-win/releases/tag/x", "javascript:alert(1)", "file:///C:/Windows/notepad.exe",
    "data:text/html,hi", "ftp://github.com/Denvolatos/lightroom-mcp-win/releases/x", "", None, 5,
    "github.com/Denvolatos/lightroom-mcp-win/releases/x",
    "https://github.com/Denvolatos/lightroom-mcp-win", "https://github.com/Denvolatos/lightroom-mcp-win/releases/",
    "https://github.com/Denvolatos/lightroom-mcp-win/issues/1", "https://github.com/Other/lightroom-mcp-win/releases/tag/x",
    "https://github.com/Denvolatos/lightroom-mcp-win-evil/releases/tag/x",
    "https://github.com.evil.com/Denvolatos/lightroom-mcp-win/releases/tag/x",
    "https://evil.com/github.com/Denvolatos/lightroom-mcp-win/releases/tag/x",
    "https://user@github.com/Denvolatos/lightroom-mcp-win/releases/tag/x",
    "https://github.com:444/Denvolatos/lightroom-mcp-win/releases/tag/x",
    "https://github.com@evil.com/Denvolatos/lightroom-mcp-win/releases/tag/x",
    "https://github.com/Denvolatos/lightroom-mcp-win/releases/../../evil",
    "https://github.com/Denvolatos/lightroom-mcp-win/releases/tag/x y",
    "https://github.com/Denvolatos/lightroom-mcp-win/releases/tag/x\nHost: evil",
    "https://api.github.com/Denvolatos/lightroom-mcp-win/releases/1",
    "https://github.com/denvolatos/lightroom-mcp-win/releases/tag/x",
    "https://github.com/Denvolatos/lightroom-mcp-win/releases/" + "a" * 400,
])
def test_url_rejected(url):
    assert not uc.valid_release_url(url)


# ---------------------------------------------------------------- 后台检查、缓存
def test_no_hue_release_means_latest_no_error(tmp_path):
    c, net, jobs = make(tmp_path, Net(body(rel("v0.15.0"), rel("v0.14.0"))))
    c.start_background()
    assert c.state()["state"] == uc.IDLE and len(jobs) == 1 and net.calls == []   # 后台线程还没跑：不阻塞
    run_jobs(jobs)
    s = c.state()
    assert s["state"] == uc.LATEST and s["message"] == uc.MSG_LATEST and s["latest"] == ""
    assert net.calls == [uc.RELEASES_URL]


def test_new_version_available_and_open_page(tmp_path):
    opened = []
    c, net, jobs = make(tmp_path, Net(body(rel("hue-v0.16.0"), rel("v0.99.0"))), opened=opened)
    c.start_background()
    run_jobs(jobs)
    s = c.state()
    assert s["state"] == uc.AVAILABLE and s["latest"] == "0.16.0" and "0.16.0" in s["message"]
    assert c.open_page() == {"ok": True, "message": ""} and opened == [REPO_URL + "hue-v0.16.0"]


def test_same_or_older_hue_release_is_latest(tmp_path):
    c, _, jobs = make(tmp_path, Net(body(rel("hue-v0.15.0"), rel("hue-v0.1.0"))))
    c.start_background()
    run_jobs(jobs)
    assert c.state()["state"] == uc.LATEST


def test_cache_hit_within_24h_makes_no_request(tmp_path):
    clock = Clock()
    c, net, jobs = make(tmp_path, Net(body(rel("hue-v1.0.0"))), clock=clock)
    c.start_background()
    run_jobs(jobs)
    assert len(net.calls) == 1
    clock.t += 23 * 3600
    c2, net2, jobs2 = make(tmp_path, Net(body()), clock=clock)           # 新进程，同一个缓存文件
    c2.start_background()
    assert jobs2 == [] and net2.calls == []
    s = c2.state()
    assert s["state"] == uc.AVAILABLE and s["latest"] == "1.0.0"       # 直接用缓存里的结果


def test_cache_expires_after_24h(tmp_path):
    clock = Clock()
    c, _, jobs = make(tmp_path, Net(body(rel("hue-v1.0.0"))), clock=clock)
    c.start_background()
    run_jobs(jobs)
    clock.t += 25 * 3600
    c2, net2, jobs2 = make(tmp_path, Net(body(rel("hue-v1.1.0"))), clock=clock)
    c2.start_background()
    run_jobs(jobs2)
    assert len(net2.calls) == 1 and c2.state()["latest"] == "1.1.0"


def test_cache_in_future_is_not_trusted(tmp_path):
    clock = Clock()
    (tmp_path / "c.json").write_text(json.dumps({"checked_at": clock.t + 10**7, "latest": "", "url": ""}), encoding="utf-8")
    c, net, jobs = make(tmp_path, Net(body()), clock=clock)
    c.start_background()
    run_jobs(jobs)
    assert len(net.calls) == 1


def test_cache_file_name_differs_from_server_cache():
    assert uc.CACHE_FILE.name == "app_update_check.json" and uc.CACHE_FILE.name != "update_check.json"


@pytest.mark.parametrize("content", ["not json", "[]", "5", '{"checked_at": "x"}', '{"checked_at": true}',
                                     '{"checked_at": 1, "latest": "evil", "url": "x"}',
                                     '{"checked_at": 1, "latest": "9.9.9", "url": "javascript:alert(1)"}'])
def test_bad_cache_is_ignored(tmp_path, content):
    (tmp_path / "c.json").write_text(content, encoding="utf-8")
    c, net, jobs = make(tmp_path, Net(body()))
    assert c.state()["state"] == uc.IDLE
    c.start_background()
    run_jobs(jobs)
    assert len(net.calls) == 1 and c.state()["state"] == uc.LATEST


def test_cached_bad_url_cannot_be_opened(tmp_path):
    (tmp_path / "c.json").write_text(json.dumps({"checked_at": 1, "latest": "9.9.9", "url": "file:///C:/x"}), encoding="utf-8")
    opened = []
    c, _, _ = make(tmp_path, opened=opened)
    assert c.open_page()["ok"] is False and opened == []


# ---------------------------------------------------------------- 失败静默
@pytest.mark.parametrize("net", [Net(exc=OSError("offline")), Net(exc=TimeoutError()), Net(b"<html>rate limited</html>"),
                                 Net(b'{"message": "API rate limit exceeded"}'), Net(b"\xff\xfe"), Net(exc=RuntimeError("boom")),
                                 Net(exc=ValueError("响应过大"))])
def test_background_failure_is_silent(tmp_path, net):
    c, _, jobs = make(tmp_path, net)
    c.start_background()
    run_jobs(jobs)                                                        # 不抛异常
    s = c.state()
    assert s["state"] == uc.IDLE and s["message"] == ""                   # 什么提示都没有
    assert not (tmp_path / "c.json").exists()                             # 失败不写缓存，下次启动再试


def test_manual_failure_shows_unavailable(tmp_path):
    c, _, jobs = make(tmp_path, Net(exc=OSError("offline")))
    r = c.check_now()
    assert r["state"] == uc.CHECKING and r["message"] == uc.MSG_CHECKING
    run_jobs(jobs)
    assert c.state()["state"] == uc.UNAVAILABLE and c.state()["message"] == uc.MSG_UNAVAILABLE


def test_spawn_failure_does_not_stick_in_checking(tmp_path):
    def boom(fn):
        raise RuntimeError("no threads")
    c = uc.AppUpdateChecker("0.15.0", lambda: True, http_get=Net(), open_url=lambda u: None, spawn=boom, cache_file=tmp_path / "c.json")
    assert c.check_now()["state"] == uc.UNAVAILABLE
    c.start_background()                                                  # 也不抛
    assert c.check_now()["state"] == uc.UNAVAILABLE


def test_oversized_response_rejected_by_default_fetcher(monkeypatch):
    class Resp:
        def __init__(self, n):
            self.n = n

        def read(self, k):
            return b"x" * min(self.n, k)

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    import urllib.request
    seen = {}

    def fake(req, timeout):
        seen["timeout"], seen["headers"] = timeout, {k.lower(): v for k, v in req.header_items()}
        return Resp(uc.MAX_BYTES + 500)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    with pytest.raises(ValueError):
        uc.http_get(uc.RELEASES_URL)
    assert seen["timeout"] == 8.0
    assert "authorization" not in seen["headers"] and "cookie" not in seen["headers"]
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: Resp(100))
    assert uc.http_get(uc.RELEASES_URL) == b"x" * 100


def test_request_url_is_fixed_github_api():
    assert uc.RELEASES_URL.startswith("https://api.github.com/repos/Denvolatos/lightroom-mcp-win/releases")


# ---------------------------------------------------------------- 开关
def test_disabled_makes_zero_requests_and_no_notice(tmp_path):
    (tmp_path / "c.json").write_text(json.dumps({"checked_at": 1, "latest": "9.9.9", "url": REPO_URL + "hue-v9.9.9"}), encoding="utf-8")
    opened = []
    c, net, jobs = make(tmp_path, enabled=False, opened=opened)
    c.start_background()
    s = c.state()
    assert jobs == [] and net.calls == [] and s["state"] == uc.IDLE and s["enabled"] is False
    assert c.open_page()["ok"] is False and opened == []


def test_enabled_must_be_real_true(tmp_path):
    c = uc.AppUpdateChecker("0.15.0", lambda: "yes", http_get=Net(), open_url=lambda u: None, spawn=lambda f: None, cache_file=tmp_path / "c.json")
    assert c.state()["enabled"] is False
    c2 = uc.AppUpdateChecker("0.15.0", lambda: 1 / 0, http_get=Net(), open_url=lambda u: None, spawn=lambda f: None, cache_file=tmp_path / "c.json")
    c2.start_background()
    assert c2.state()["enabled"] is False


def test_manual_check_ignores_cache_and_works_even_when_auto_is_off(tmp_path):
    clock = Clock()
    (tmp_path / "c.json").write_text(json.dumps({"checked_at": clock.t, "latest": "", "url": ""}), encoding="utf-8")
    c, net, jobs = make(tmp_path, Net(body(rel("hue-v2.0.0"))), enabled=False, clock=clock)
    c.check_now()
    run_jobs(jobs)
    assert len(net.calls) == 1 and c.state()["state"] == uc.AVAILABLE


def test_manual_check_not_started_twice(tmp_path):
    c, net, jobs = make(tmp_path, Net(body()))
    c.check_now()
    c.check_now()
    assert len(jobs) == 1
    run_jobs(jobs)
    assert len(net.calls) == 1 and c.state()["state"] == uc.LATEST


def test_state_does_not_touch_network(tmp_path):
    c, net, jobs = make(tmp_path)
    for _ in range(5):
        c.state()
    assert net.calls == [] and jobs == []


def test_dev_version_compared_numerically(tmp_path):
    c, _, jobs = make(tmp_path, Net(body(rel("hue-v0.9.0"))), current="0.10.0")
    c.start_background()
    run_jobs(jobs)
    assert c.state()["state"] == uc.LATEST
    c2, _, jobs2 = make(tmp_path / "x", Net(body(rel("hue-v0.11.0"))), current="0.10.0")
    c2.start_background()
    run_jobs(jobs2)
    assert c2.state()["state"] == uc.AVAILABLE


def test_unparseable_current_never_offers_update(tmp_path):
    c, _, jobs = make(tmp_path, Net(body(rel("hue-v9.0.0"))), current="dev")
    c.start_background()
    run_jobs(jobs)
    assert c.state()["state"] == uc.LATEST


def test_browser_failure_is_reported_not_raised(tmp_path):
    def boom(u):
        raise OSError("no browser")
    c = uc.AppUpdateChecker("0.15.0", lambda: True, http_get=Net(body(rel("hue-v1.0.0"))), open_url=boom, spawn=lambda f: f(),
                            cache_file=tmp_path / "c.json")
    c.start_background()
    assert c.state()["state"] == uc.AVAILABLE and c.open_page()["ok"] is False


def test_open_page_when_no_update_does_nothing(tmp_path):
    opened = []
    c, _, jobs = make(tmp_path, Net(body()), opened=opened)
    c.start_background()
    run_jobs(jobs)
    assert c.open_page()["ok"] is False and opened == []


# ---------------------------------------------------------------- 设置
def test_default_check_updates_true_and_old_file_loads(tmp_path):
    assert st.defaults()["check_updates"] is True
    f = tmp_path / "old.json"
    f.write_text(json.dumps({"schema": 1, "provider": "claude", "wizard_done": True}), encoding="utf-8")   # 旧文件没有这一项
    store = st.SettingsStore(f, restrict=lambda x: None)
    assert store.data["check_updates"] is True and store.data["wizard_done"] is True


def test_sanitize_check_updates():
    assert st.sanitize({"check_updates": False})["check_updates"] is False
    for bad in ("no", 0, None, 1, []):
        assert st.sanitize({"check_updates": bad})["check_updates"] is True


def test_update_check_updates(tmp_path):
    store = st.SettingsStore(tmp_path / "s.json", restrict=lambda x: None)
    assert store.update({"check_updates": False})["settings"]["check_updates"] is False
    assert st.SettingsStore(tmp_path / "s.json", restrict=lambda x: None).data["check_updates"] is False
    r = store.update({"check_updates": "off"})
    assert not r["ok"] and "check_updates" in r["errors"] and store.data["check_updates"] is False


def test_app_version():
    assert st.APP_VERSION == "0.16.0"


# ---------------------------------------------------------------- Api
@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "app_settings.json")
    monkeypatch.setattr(st.SettingsStore.__init__, "__defaults__", (None, lambda p: None))
    monkeypatch.setattr(uc, "CACHE_FILE", tmp_path / "app_update_check.json")
    import main
    a = main.Api()
    a._updates = uc.AppUpdateChecker(st.APP_VERSION, lambda: a._settings.data.get("check_updates") is True,
                                     http_get=Net(body(rel("hue-v3.0.0"))), open_url=lambda u: None, spawn=lambda f: None,
                                     cache_file=tmp_path / "x.json")
    yield a
    a._shutdown()


def test_api_methods_take_no_parameters(api):
    for name in ("update_state", "check_update_now", "open_update_page"):
        assert list(inspect.signature(getattr(api, name)).parameters) == []


def test_api_flow_and_no_secrets(api):
    assert api.update_state()["state"] == uc.IDLE
    assert api.check_update_now()["state"] == uc.CHECKING
    assert set(api.update_state()) == {"state", "current", "latest", "message", "enabled"}
    assert api.open_update_page()["ok"] is False


def test_api_does_not_touch_network_on_construction(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "SETTINGS_FILE", tmp_path / "app_settings.json")
    monkeypatch.setattr(st.SettingsStore.__init__, "__defaults__", (None, lambda p: None))
    monkeypatch.setattr(uc, "CACHE_FILE", tmp_path / "app_update_check.json")
    calls = []
    monkeypatch.setattr(uc, "http_get", lambda *a, **k: calls.append(a) or b"[]")
    import main
    a = main.Api()
    a.update_state()
    a._shutdown()
    assert calls == []


def test_default_http_get_is_wired_not_shadowed(monkeypatch, tmp_path):
    """真机前自查：不注入 http_get 时，默认联网函数必须真的被调用（曾因参数同名遮蔽而恒为 TypeError）。"""
    calls = []
    monkeypatch.setattr(uc, "_default_http_get", lambda url, **kw: calls.append((url, kw)) or b"[]")
    c = uc.AppUpdateChecker("0.15.0", cache_file=tmp_path / "c.json")
    assert c._get("https://api.github.com/x") == b"[]"
    assert calls and calls[0][1].get("version") == "0.15.0"
