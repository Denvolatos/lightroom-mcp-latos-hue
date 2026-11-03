import json
import time

import backend as be
import connection as conn
import ports
from adjustments import AdjustmentTracker


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class FakeLr:
    def __init__(self):
        self.connected = False
        self.plugin_version = "0.13.0"
        self.restarts = 0
        self.photo = {"id": "P1", "name": "A.ARW"}

    def restart(self):
        self.restarts += 1
        return True

    def selected_photo(self):
        return self.photo


class FakeSession:
    def __init__(self):
        self.alive = True
        self.busy = False
        self.spawned_at = 0.0
        self.ensure_calls = 0
        self.restarts = 0
        self.clock = None

    def ensure_running(self):
        self.ensure_calls += 1
        self.alive = True
        return True

    def restart(self, resume=True):
        self.restarts += 1
        self.spawned_at = self.clock() if self.clock else 0.0
        return True


def make(tmp_path, side=True):
    clock = Clock()
    lr, sess, tracker, events = FakeLr(), FakeSession(), AdjustmentTracker(), []
    sess.clock, sess.spawned_at = clock, clock()
    state = tmp_path / "side.json" if side else None
    b = be.Backend(lr, sess, tracker, events.append, state_file=state, clock=clock, cleaner=lambda: events.append({"type": "cleaned"}))
    return b, lr, sess, tracker, events, clock, state


def write_side(path, connected, t=None):
    path.write_text(json.dumps({"connected": connected, "t": time.time() if t is None else t, "alive": True}), encoding="utf-8")


# ---------------------------------------------------------------- 状态判定
def test_evaluate_states():
    assert conn.evaluate(True, {"connected": True}, 0)["state"] == "connected"
    assert conn.evaluate(True, None, 0)["state"] == "connected"                       # 不使用助手通道检测
    s = conn.evaluate(False, {"connected": False}, 5)
    assert s["state"] == "connecting" and s["text"] == "Lightroom 正在连接"
    s = conn.evaluate(False, {"connected": False}, 60)
    assert s["state"] == "disconnected" and s["text"] == "Lightroom 未连接" and "LrMCP 插件" in s["hint"]
    assert "重载" not in s["hint"] and "重启" not in s["hint"].replace("无需重启软件", "")   # 不要求用户重载插件
    s = conn.evaluate(True, {"connected": False}, 60)
    assert s["state"] == "disconnected" and "重新建立" in s["hint"]                    # 窗口通了而助手通道没通：不怪插件


def test_read_side_state(tmp_path):
    p = tmp_path / "s.json"
    assert conn.read_side_state(None) is None
    assert conn.read_side_state(p)["stale"] is True                                    # 缺失
    write_side(p, True)
    assert conn.read_side_state(p)["connected"] is True
    write_side(p, True, t=time.time() - 60)
    assert conn.read_side_state(p)["connected"] is False                               # 过期
    p.write_text("坏数据", encoding="utf-8")
    assert conn.read_side_state(p)["connected"] is False


def test_status_goes_connecting_then_connected_then_disconnected(tmp_path):
    b, lr, sess, tracker, events, clock, state = make(tmp_path)
    assert b.status()["state"] == "connecting"
    clock.t += 30
    assert b.status()["state"] == "disconnected"
    lr.connected = True
    write_side(state, True)
    assert b.status()["state"] == "connected"
    lr.connected = False                                                               # 断开：先“正在连接”，满 25 秒才“未连接”
    assert b.status()["state"] == "connecting"
    clock.t += 30
    assert b.status()["state"] == "disconnected"


# ---------------------------------------------------------------- 自动恢复
def test_tick_restarts_dead_claude(tmp_path):
    b, lr, sess, *_ = make(tmp_path)
    sess.alive = False
    b.tick()
    assert sess.ensure_calls == 1 and "restart_claude" in b.events


def test_tick_rebuilds_side_channel_when_only_window_is_connected(tmp_path):
    b, lr, sess, tracker, events, clock, state = make(tmp_path)
    lr.connected = True
    write_side(state, False)
    clock.t += 10
    b.tick()
    assert sess.restarts == 0                                                          # 刚启动，先等
    clock.t += 15
    write_side(state, False)
    b.tick()
    assert sess.restarts == 1 and "restart_side" in b.events
    clock.t += 5
    b.tick()
    assert sess.restarts == 1                                                          # 刚重建，再给它时间
    for _ in range(4):                                                                 # 反复失败：有次数上限与冷却
        clock.t += 25
        write_side(state, False)
        b.tick()
    assert sess.restarts <= be.SIDE_MAX_ATTEMPTS + 0
    n = sess.restarts
    clock.t += 30
    b.tick()
    assert sess.restarts == n                                                          # 冷却期内不再重建


def test_tick_does_not_touch_session_while_busy(tmp_path):
    b, lr, sess, tracker, events, clock, state = make(tmp_path)
    lr.connected = True
    sess.busy = True
    write_side(state, False)
    clock.t += 60
    b.tick()
    assert sess.restarts == 0


def test_tick_reregisters_window_bridge_when_plugin_missing(tmp_path):
    b, lr, sess, tracker, events, clock, state = make(tmp_path)
    clock.t += 20
    b.tick()
    assert lr.restarts == 0
    clock.t += 20
    b.tick()
    assert lr.restarts == 1 and "restart_lr" in b.events
    clock.t += 10
    b.tick()
    assert lr.restarts == 1                                                            # 不会连续狂重启
    clock.t += 31
    b.tick()
    assert lr.restarts == 2


def test_tick_cleans_stale_announcements_periodically(tmp_path):
    b, lr, sess, tracker, events, clock, state = make(tmp_path)
    clock.t += be.CLEAN_SECONDS + 1
    b.tick()
    assert {"type": "cleaned"} in events


def test_status_event_pushed_only_on_change(tmp_path):
    b, lr, sess, tracker, events, clock, state = make(tmp_path)
    b.tick(); b.tick()
    assert [e for e in events if e.get("type") == "status"].__len__() == 1
    lr.connected = True
    write_side(state, True)
    b.tick()
    sts = [e for e in events if e.get("type") == "status"]
    assert len(sts) == 2 and sts[-1]["state"] == "connected"


# ---------------------------------------------------------------- 发送前等待连接
def test_wait_ready_waits_then_succeeds(tmp_path):
    b, lr, sess, tracker, events, clock, state = make(tmp_path)
    write_side(state, True)
    calls = []

    def fake_sleep(s):
        calls.append(s)
        clock.t += s
        if len(calls) == 3:
            lr.connected = True

    ok, why = b.wait_ready(timeout=25, sleep=fake_sleep)
    assert ok and why == "" and len(calls) == 3
    assert [e for e in events if e.get("type") == "connecting"][0]["message"].startswith("正在连接 Lightroom")


def test_wait_ready_gives_up_with_actionable_hint(tmp_path):
    b, lr, sess, tracker, events, clock, state = make(tmp_path)
    clock.t += 100

    def fake_sleep(s):
        clock.t += s

    ok, why = b.wait_ready(timeout=5, sleep=fake_sleep)
    assert not ok and "LrMCP 插件" in why


def test_wait_ready_starts_claude_if_dead(tmp_path):
    b, lr, sess, tracker, events, clock, state = make(tmp_path)
    sess.alive = False
    lr.connected = True
    write_side(state, True)
    ok, _ = b.wait_ready(timeout=5, sleep=lambda s: None)
    assert ok and sess.ensure_calls >= 1


# ---------------------------------------------------------------- 换照片
def test_photo_change_filters_adjustment_rows(tmp_path):
    b, lr, sess, tracker, events, clock, state = make(tmp_path)
    lr.connected = True
    write_side(state, True)
    b.tick()
    assert tracker.current_photo == "P1"
    tracker.observe({"type": "tool", "name": "lr_set_develop", "id": "T1", "input": {"changes": {"Exposure": 0.2}}})
    assert [r["photo"] for r in b.rows()] == ["P1"]
    lr.photo = {"id": "P2", "name": "B.ARW"}
    clock.t += be.PHOTO_POLL_SECONDS + 1
    events.clear()
    b.tick()
    assert b.rows() == []                                                              # 上一张的记录不混进来
    assert {"type": "photo", "id": "P2", "name": "B.ARW"} in events
    assert {"type": "adjust", "rows": []} in events
    lr.photo = {"id": "P1", "name": "A.ARW"}
    clock.t += be.PHOTO_POLL_SECONDS + 1
    b.tick()
    assert len(b.rows()) == 1                                                          # 切回来又能看到


# ---------------------------------------------------------------- 端口与公告
def test_port_order_prefers_least_recently_used(tmp_path):
    f = tmp_path / "usage.json"
    assert ports.port_order(f)[0] == 58771 and ports.port_order(f)[-1] == 58770
    ports.note_port_used(58771, f, now=100)
    ports.note_port_used(58772, f, now=200)
    order = ports.port_order(f)
    assert order[0] == 58773 and order.index(58771) > order.index(58789) and order.index(58772) > order.index(58771)
    assert sorted(order) == list(range(58770, 58790))                                  # 端口范围不变，仍在插件扫描范围内


def test_clean_stale_announcements_removes_only_dead(tmp_path):
    for p in (58771, 58772):
        (tmp_path / f"{p}.txt").write_text("x", encoding="ascii")
    (tmp_path / "notes.txt").write_text("x", encoding="ascii")
    removed = ports.clean_stale_announcements(tmp_path, listening=lambda p: p == 58772)
    assert removed == [58771] and (tmp_path / "58772.txt").exists() and (tmp_path / "notes.txt").exists()
