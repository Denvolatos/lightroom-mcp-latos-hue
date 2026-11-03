import http.client
import io
import urllib.error
import urllib.request

import pytest

import preview as pv
from preview import PreviewManager, PreviewServer, PreviewStore, develop_version


def jpg(color=(10, 20, 30), size=(64, 40)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class FakeLr:
    """settings 用一个数字代表“编辑版本”；撤销就是把它改回去。"""
    def __init__(self):
        self.connected = True
        self.detail = {"id": "P1", "name": "A.ARW", "info": {"name": "A.ARW", "camera": "Sony X", "iso": "ISO 100", "aperture": "f / 8",
                       "shutter_speed": "1/800", "focal_length": "20 mm", "format": "RAW", "width": 3504, "height": 2336}}
        self.exposure = {"P1": 0.0, "P2": 0.0}
        self.previews = 0
        self.boom_preview = False
        self.boom_develop = False
        self.edges = []

    def selected_detail(self):
        return self.detail

    def develop_of(self, pid):
        if self.boom_develop:
            raise RuntimeError("x")
        return {"settings": {"Exposure2012": self.exposure[pid]}, "hsl": {}, "has_local_adjustments": False, "notes": [str(self.previews)]}

    def preview_bytes(self, pid, edge):
        if self.boom_preview:
            raise RuntimeError("x")
        self.previews += 1
        self.edges.append(edge)
        return jpg(color=(int(self.exposure[pid] * 100) % 255, 0, 0)), "A.ARW"


def make(lr=None):
    lr = lr or FakeLr()
    clock, events = Clock(), []
    server = PreviewServer(PreviewStore())
    server.start()
    m = PreviewManager(lr, server, events.append, clock=clock)
    return m, lr, events, clock, server


# ---------------------------------------------------------------- 编辑版本与缓存
def test_version_ignores_notes_and_tracks_settings():
    a = {"settings": {"Exposure2012": 0}, "hsl": {}, "has_local_adjustments": False, "notes": ["a"]}
    b = dict(a, notes=["b"])
    c = {**a, "settings": {"Exposure2012": 0.1}}
    assert develop_version(a) == develop_version(b) != develop_version(c)


def test_clamp_edge_uses_server_limits():
    assert pv.clamp_edge(10) == 256 and pv.clamp_edge(99999) == 2048 and pv.clamp_edge("x") == 1024 and pv.clamp_edge(1536) == 1536


def test_store_key_eviction_keeps_initial():
    st = PreviewStore(max_cache=2, max_initial=5)
    first = st.put("P1", 1024, "v0", b"a")
    st.set_initial("P1", first)
    for i in range(5):
        st.put("P1", 1024, f"v{i + 1}", b"x")
    assert st.get("P1", 1024, "v0") is first                       # 初始图不被淘汰
    assert st.initial("P1")["id"] == first["id"]
    assert st.get("P1", 1024, "v1") is None and st.get("P1", 1024, "v5") is not None   # 旧的非初始图被淘汰
    assert st.get("P1", 2048, "v0") is None                        # 键含长边
    assert st.bytes_of(first["id"]) == b"a"


def test_store_initial_capacity_drops_oldest_photo():
    st = PreviewStore(max_cache=5, max_initial=2)
    ids = []
    for p in ("A", "B", "C"):
        e = st.put(p, 1024, "v", b"x")
        st.set_initial(p, e)
        ids.append(e["id"])
    assert st.initial("A") is None and st.initial("B") is not None and st.bytes_of(ids[0]) is None


# ---------------------------------------------------------------- 本机图片服务
def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, b"", e.headers


def test_server_serves_only_cached_images_with_token():
    server = PreviewServer(PreviewStore())
    port = server.start()
    try:
        e = server.store.put("P1", 1024, "v", jpg())
        code, body, hdr = get(server.url_for(e))
        assert code == 200 and body == e["bytes"] and hdr["Content-Type"] == "image/jpeg"
        base = f"http://127.0.0.1:{port}"
        bad = [f"{base}/p/wrongtoken/{e['id']}.jpg",                       # 口令不对
               f"{base}/p/{server.token}/{'0' * 16}.jpg",                   # 不在缓存里
               f"{base}/p/{server.token}/{e['id']}.png",                    # 后缀不对
               f"{base}/p/{server.token}/..%2f..%2fWindows%2fwin.ini",      # 路径穿越
               f"{base}/p/{server.token}/../../etc/passwd",
               f"{base}/p/{server.token}/C:/Windows/win.ini",
               f"{base}/{e['id']}.jpg", f"{base}/", f"{base}/p/{server.token}/"]
        for u in bad:
            assert get(u)[0] == 404, u
        # 带查询串不影响匹配，但仍须口令
        assert get(server.url_for(e) + "?x=1")[0] == 200
    finally:
        server.stop()


def test_server_rejects_other_methods_and_foreign_host():
    server = PreviewServer(PreviewStore())
    port = server.start()
    try:
        e = server.store.put("P1", 1024, "v", jpg())
        path = f"/p/{server.token}/{e['id']}.jpg"
        for method in ("POST", "PUT", "DELETE", "HEAD"):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request(method, path)
            assert c.getresponse().status == 405, method
            c.close()
        c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        c.request("GET", path, headers={"Host": "evil.example.com"})        # 防 DNS 重绑定
        assert c.getresponse().status == 404
        c.close()
    finally:
        server.stop()


def test_server_listens_on_loopback_only_and_token_differs():
    a, b = PreviewServer(PreviewStore()), PreviewServer(PreviewStore())
    a.start()
    b.start()
    try:
        assert a._httpd.server_address[0] == "127.0.0.1" and a.token != b.token and len(a.token) >= 20
    finally:
        a.stop()
        b.stop()


# ---------------------------------------------------------------- 管理器：初始/当前、缓存、错误
def due(m, clock, secs=0.0):
    clock.t += secs
    return m.process_due()


def test_first_sight_is_initial_and_same_as_current():
    m, lr, events, clock, server = make()
    try:
        m.request(0)
        assert due(m, clock)
        ev = events[-1]
        assert ev["type"] == "preview" and ev["state"] == "ok" and ev["same"] is True
        assert ev["initial"]["url"] == ev["current"]["url"] and ev["current"]["w"] == 64 and ev["current"]["h"] == 40
        assert ev["photo"]["name"] == "A.ARW" and ev["photo"]["camera"] == "Sony X" and ev["photo"]["size"] == "3504 × 2336"
        assert any(e.get("state") == "loading" for e in events)             # 先显示“正在读取预览”
        assert lr.previews == 1
    finally:
        server.stop()


def test_unchanged_version_hits_cache_no_refetch():
    m, lr, events, clock, server = make()
    try:
        for _ in range(3):
            m.request(0)
            due(m, clock)
        assert lr.previews == 1 and m.fetch_count == 1
        assert len([e for e in events if e.get("state") == "ok"]) == 1       # 内容没变不重复推送
    finally:
        server.stop()


def test_adjust_refreshes_current_initial_unchanged_and_undo_restores_same_entry():
    m, lr, events, clock, server = make()
    try:
        m.request(0)
        due(m, clock)
        first = events[-1]
        lr.exposure["P1"] = 0.1                                              # 已应用调整
        m.request()
        due(m, clock, 1)
        adj = events[-1]
        assert adj["current"]["url"] != first["current"]["url"] and adj["initial"]["url"] == first["initial"]["url"] and adj["same"] is False
        assert lr.previews == 2
        lr.exposure["P1"] = 0.0                                              # 撤销/还原
        m.request()
        due(m, clock, 1)
        back = events[-1]
        assert back["same"] is True and back["current"]["url"] == first["initial"]["url"]
        assert lr.previews == 2                                              # 命中缓存，没有再取图
    finally:
        server.stop()


def test_photo_switch_keeps_each_photos_initial():
    m, lr, events, clock, server = make()
    try:
        m.request(0)
        due(m, clock)
        initial_p1 = events[-1]["initial"]["url"]
        lr.detail = {"id": "P2", "name": "B.ARW", "info": {"name": "B.ARW"}}
        m.request(0)
        due(m, clock)
        assert events[-1]["photo"]["id"] == "P2" and events[-1]["initial"]["url"] != initial_p1 and events[-1]["same"] is True
        lr.exposure["P1"] = 0.2
        lr.detail = {"id": "P1", "name": "A.ARW", "info": {"name": "A.ARW"}}
        m.request(0)
        due(m, clock)
        assert events[-1]["initial"]["url"] == initial_p1 and events[-1]["same"] is False   # 切回来仍是首次看到的那张
    finally:
        server.stop()


def test_no_selection_and_not_connected_and_errors():
    m, lr, events, clock, server = make()
    try:
        lr.detail = {"id": None, "name": None, "info": {}}
        m.refresh()
        assert events[-1]["state"] == "none" and "未选中" in events[-1]["message"]
        lr.detail = {"id": "P1", "name": "A.ARW", "info": {"name": "A.ARW"}}
        lr.boom_preview = True
        m.refresh()
        assert events[-1]["state"] == "error" and events[-1]["message"] == "无法读取预览：请确认 Lightroom 已打开并选中了照片"
        n = len(events)
        m.refresh()                                                          # 同样的失败不重复推送
        assert len(events) == n
        lr.boom_preview = False
        lr.boom_develop = True
        m.refresh()
        assert events[-1]["state"] == "error"
        lr.boom_develop = False
        lr.connected = False
        m.refresh()
        assert events[-1]["state"] == "error"
        lr.connected = True
        m.refresh()
        assert events[-1]["state"] == "ok"                                   # 恢复后自动好转
        assert m.store.initial("P1") is not None
    finally:
        server.stop()


def test_loading_overlay_keeps_old_image_when_refreshing_same_photo():
    m, lr, events, clock, server = make()
    try:
        m.refresh()
        lr.exposure["P1"] = 0.3
        m.refresh()
        kinds = [(e["state"], bool(e.get("loading"))) for e in events]
        assert kinds == [("loading", False), ("ok", False), ("ok", True), ("ok", False)]
    finally:
        server.stop()


# ---------------------------------------------------------------- 防抖与轮询
def test_debounce_merges_requests_and_has_max_wait():
    m, lr, events, clock, server = make()
    try:
        m.refresh()
        base = lr.previews
        for _ in range(5):                                   # 连续调整：每次推迟，合并成一次
            lr.exposure["P1"] += 0.1
            m.request()
            clock.t += 0.3
            assert not m.process_due()
        assert lr.previews == base
        clock.t += 0.7
        assert m.process_due() and lr.previews == base + 1
        assert not m.process_due()                           # 没有新请求就不再刷新
        # 持续不断的请求也不会无限推迟
        t0 = clock.t
        m.request()
        while not m.process_due():
            clock.t += 0.4
            m.request()
            assert clock.t - t0 < 10
        assert clock.t - t0 <= pv.MAX_WAIT_SECONDS + 0.5
    finally:
        server.stop()


def test_immediate_request_pulls_forward():
    m, lr, events, clock, server = make()
    try:
        m.request()
        m.request(0)
        assert m.process_due()
    finally:
        server.stop()


def test_poll_requests_every_interval_only():
    m, lr, events, clock, server = make()
    try:
        m.poll()
        assert m.process_due()
        m.poll()
        assert not m.process_due()                           # 间隔不足不重复请求
        clock.t += pv.POLL_SECONDS
        m.poll()
        assert m.process_due()
    finally:
        server.stop()


def test_poll_detects_selection_change_and_manual_edit():
    m, lr, events, clock, server = make()
    try:
        m.poll()
        m.process_due()
        clock.t += 3.1
        lr.exposure["P1"] = 0.5                              # 用户在 Lightroom 里手动改了
        m.poll()
        m.process_due()
        assert events[-1]["same"] is False
        clock.t += 3.1
        lr.detail = {"id": "P2", "name": "B.ARW", "info": {"name": "B.ARW"}}
        m.poll()
        m.process_due()
        assert events[-1]["photo"]["id"] == "P2"
    finally:
        server.stop()


def test_set_edge_clamps_and_refetches_current_only():
    m, lr, events, clock, server = make()
    try:
        m.refresh()
        first_initial = events[-1]["initial"]["url"]
        assert m.set_edge(99999) == 2048
        assert m.process_due()
        assert lr.edges == [1024, 2048] and events[-1]["edge"] == 2048
        assert events[-1]["initial"]["url"] == first_initial                # 初始图保持首次取图时的版本
    finally:
        server.stop()


def test_payload_urls_point_to_cache_only():
    m, lr, events, clock, server = make()
    try:
        m.refresh()
        ev = events[-1]
        for k in ("initial", "current"):
            code, body, _ = get(ev[k]["url"])
            assert code == 200 and body[:2] == b"\xff\xd8"
    finally:
        server.stop()


def test_backend_tick_polls_previews(tmp_path):
    import backend as be
    from adjustments import AdjustmentTracker

    class L:
        connected = True
        plugin_version = "0.14.0"

        def selected_photo(self):
            return {"id": "P1", "name": "A"}

    class S:
        alive, busy, spawned_at = True, True, 0.0

        def ensure_running(self):
            pass

    class P:
        n = 0

        def poll(self):
            P.n += 1

    clock = Clock()
    b = be.Backend(L(), S(), AdjustmentTracker(), lambda e: None, state_file=None, clock=clock, cleaner=lambda: None, previews=P())
    b.tick()
    assert P.n == 1                                            # 助手忙（正在处理请求）时也照常轮询


# ---------------------------------------------------------------- LrService 取图方法
class FakeBridge:
    connected = True

    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def call(self, cmd, params=None, timeout=30):
        self.calls.append((cmd, params))
        r = self.replies[cmd]
        if isinstance(r, Exception):
            raise r
        return r


def test_lrservice_preview_bytes_only_reads_preview_dir_and_deletes(tmp_path, monkeypatch):
    from lr_service import LrService, _import_server
    _import_server()
    from lightroom_mcp import config
    folder = tmp_path / "previews"
    folder.mkdir()
    monkeypatch.setattr(config, "PREVIEW_DIR", folder)
    good, outside = folder / "p_x.jpg", tmp_path / "secret.jpg"
    good.write_bytes(b"abc")
    outside.write_bytes(b"zzz")
    b = FakeBridge({"get_preview": {"path": str(good), "name": "A.ARW"}})
    lr = LrService(bridge=b, edit_service=object())
    assert lr.preview_bytes("P1", 1024) == (b"abc", "A.ARW") and not good.exists()
    assert b.calls[0] == ("get_preview", {"photo": "P1", "long_edge": 1024})
    b.replies["get_preview"] = {"path": str(outside)}
    with pytest.raises(RuntimeError):
        lr.preview_bytes("P1", 1024)
    assert outside.exists()                                   # 目录外的文件既不读也不删
    b.replies["get_preview"] = {"path": str(folder / ".." / "secret.jpg")}
    with pytest.raises(RuntimeError):
        lr.preview_bytes("P1", 1024)


def test_lrservice_selected_detail():
    from lr_service import LrService
    info = {"id": "P1", "name": "A.ARW", "iso": "ISO 100"}
    lr = LrService(bridge=FakeBridge({"list_selected": {"active_id": "P1", "photos": [{"id": "P0", "name": "Z"}, info]}}), edit_service=object())
    assert lr.selected_detail() == {"id": "P1", "name": "A.ARW", "info": info}
    assert LrService(bridge=FakeBridge({"list_selected": {"count": 0, "photos": []}}), edit_service=object()).selected_detail()["id"] is None
    assert LrService(bridge=FakeBridge({"list_selected": RuntimeError("x")}), edit_service=object()).selected_detail() is None
