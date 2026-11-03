"""AI 挑片写入：确认清单、逐张取消、只改星级与旗标、成功/失败/不确定/只读、撤销（假 Lightroom，不碰真实照片）。"""
import inspect
import threading
import time

import pytest

import pick_apply as pa
import lr_service


def wait(cond, t=3.0):
    end = time.monotonic() + t
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return cond()


class ReadOnlyError(RuntimeError):
    pass


class PluginNotConnected(RuntimeError):
    pass


class BridgeTimeout(RuntimeError):
    pass


class FakeLr:
    def __init__(self):
        self.connected = True
        self.ro = None
        self.meta = {"P1": (2, "none"), "P2": (0, "reject"), "P3": (4, "pick")}
        self.calls = []                # (photo, rating, flag, reason)
        self.undo_calls = []
        self.fail = {}                 # photo -> Exception
        self.verified = {}
        self.unreadable = set()
        self.undo_result = {}          # edit_id -> dict
        self.n = 0
        self.latest = {}

    def readonly_error(self):
        return self.ro

    def metadata_of(self, pid):
        if pid in self.unreadable:
            raise RuntimeError("读取失败")
        r, f = self.meta[pid]
        return {"photo": {"id": pid}, "metadata": {"rating": r, "flag": f, "keywords": ["旅行"], "title": "T"}}

    def set_rating_flag(self, pid, rating, flag, reason=""):
        self.calls.append((pid, rating, flag, reason))
        if pid in self.fail:
            raise self.fail[pid]
        self.n += 1
        r, f = self.meta[pid]
        self.meta[pid] = (r if rating is None else rating, f if flag is None else flag)
        return {"edit_id": f"E{self.n}", "verified": self.verified.get(pid, True)}

    def latest_meta_edit(self, pid):
        return self.latest.get(pid)

    def undo(self, edit_id, force=False):
        self.undo_calls.append((edit_id, force))
        return self.undo_result.get(edit_id, {"ok": True, "conflict": False, "message": ""})


RANKING = [
    {"rank": 1, "photo_id": "P1", "name": "A.ARW", "stars": 5, "flag": "pick", "score": 9, "reason": "x"},
    {"rank": 2, "photo_id": "P2", "name": "B.ARW", "stars": 3, "flag": "none", "score": 7, "reason": "x"},
    {"rank": 3, "photo_id": "P3", "name": "C.ARW", "stars": 4, "flag": "pick", "score": 6, "reason": "x"},     # 与现有一致
]


@pytest.fixture
def env():
    lr, events = FakeLr(), []
    ranking = [dict(r) for r in RANKING]
    svc = pa.ApplyService(lr, lambda: [dict(r) for r in ranking], events.append)
    svc.lr_, svc.events, svc.ranking = lr, events, ranking
    return svc


def finish(svc):
    assert wait(lambda: svc.state_public()["stage"] == "done")
    return svc.state_public()


# ---------------------------------------------------------------- 确认清单
def test_prepare_builds_checklist_with_old_and_new(env):
    r = env.prepare()
    assert r["ok"]
    by = {i["photo_id"]: i for i in r["items"]}
    assert by["P1"]["old_text"] == "2 星 / 无旗标" and by["P1"]["new_text"] == "5 星 / 留用" and by["P1"]["changed"]
    assert by["P2"]["old_text"] == "无星级 / 排除" and by["P2"]["new_text"] == "3 星 / 无旗标" and by["P2"]["changed"]
    assert by["P3"]["changed"] is False                          # 与现有一致：无变化，不可勾选
    assert env.lr_.calls == []                                    # 清单阶段不写入任何东西


def test_prepare_refusals(env):
    env.ranking.clear()
    assert "没有可写入" in env.prepare()["message"]
    env.ranking.extend(dict(r) for r in RANKING)
    env.lr_.connected = False
    assert "未连接" in env.prepare()["message"]
    env.lr_.connected = True
    env.lr_.ro = "只读模式已开启"
    r = env.prepare()
    assert not r["ok"] and r["readonly"] and "只读" in r["message"]
    assert env.lr_.calls == []


def test_prepare_unreadable_photo_is_listed_but_not_writable(env):
    env.lr_.unreadable.add("P2")
    items = {i["photo_id"]: i for i in env.prepare()["items"]}
    assert items["P2"]["changed"] is False and "无法读取" in items["P2"]["error"]
    assert env.confirm(["P2"])["ok"] is False


# ---------------------------------------------------------------- 写入
def test_confirm_writes_only_checked_and_only_rating_flag(env):
    env.prepare()
    assert env.confirm(["P2"])["ok"]
    st = finish(env)
    assert [c[0] for c in env.lr_.calls] == ["P2"]                # P1 被取消勾选：不写
    pid, rating, flag, reason = env.lr_.calls[0]
    assert (rating, flag) == (3, "none") and "AI 挑片" in reason
    assert st["summary"] == {"n": 1, "ok": 1, "failed": 0, "uncertain": 0} and st["results"][0]["status"] == "ok"
    assert env.lr_.meta["P1"] == (2, "none")                      # 未勾选的照片没被改


def test_only_changed_fields_are_sent(env):
    env.lr_.meta["P1"] = (2, "pick")                              # 旗标已是 pick，只差星级
    env.prepare()
    env.confirm(["P1"])
    finish(env)
    assert env.lr_.calls[0][1:3] == (5, None)
    env.lr_.meta["P2"] = (3, "reject")                            # 星级已是 3，只差旗标
    env.lr_.calls.clear()
    env.prepare()
    env.confirm(["P2"])
    finish(env)
    assert env.lr_.calls[0][1:3] == (None, "none")


def test_rating_zero_is_written_as_zero_not_skipped(env):
    env.ranking[0].update(stars=0, flag="none")
    env.prepare()
    env.confirm(["P1"])
    finish(env)
    assert env.lr_.calls[0][1] == 0


def test_set_rating_flag_signature_cannot_touch_keywords():
    params = list(inspect.signature(lr_service.LrService.set_rating_flag).parameters)
    assert params == ["self", "photo_id", "rating", "flag", "reason"]
    src = inspect.getsource(lr_service.LrService.set_rating_flag)
    for word in ("keywords", "title", "caption", "color_label"):
        assert word not in src.replace("不传关键词、标题、说明等其他字段", "")


def test_page_cannot_add_photos_or_change_values(env):
    env.prepare()
    assert not env.confirm(["P9"])["ok"]                          # 不在清单里
    assert not env.confirm(["P1", "P3"])["ok"]                    # P3 无变化，不可写
    assert not env.confirm("P1")["ok"] and not env.confirm([1])["ok"] and not env.confirm(None)["ok"]
    assert not env.confirm([])["ok"] and "至少勾选" in env.confirm([])["message"]
    assert env.lr_.calls == []
    assert list(inspect.signature(env.confirm).parameters) == ["photo_ids"]     # 页面只能回传勾选的 id，没有任何新值参数


def test_confirm_requires_a_prepared_checklist(env):
    assert "已失效" in env.confirm(["P1"])["message"]
    env.prepare()
    assert env.cancel()["ok"]
    assert "已失效" in env.confirm(["P1"])["message"]


def test_readonly_after_checklist_refuses_whole_batch(env):
    env.prepare()
    env.lr_.ro = "只读模式已开启"
    r = env.confirm(["P1", "P2"])
    assert not r["ok"] and r["readonly"] and env.lr_.calls == []
    assert env.state_public()["stage"] == "confirm"               # 清单还在，关掉只读后可重试
    env.lr_.ro = None
    assert env.confirm(["P1", "P2"])["ok"]
    finish(env)


def test_readonly_turns_on_mid_write_stops_the_rest(env):
    env.prepare()
    env.lr_.fail["P1"] = ReadOnlyError("只读")
    env.confirm(["P1", "P2"])
    st = finish(env)
    assert [r["status"] for r in st["results"]] == ["failed", "failed"] and "只读" in st["results"][1]["message"]
    assert [c[0] for c in env.lr_.calls] == ["P1"]                # 第二张没有再尝试


def test_per_photo_failure_does_not_stop_others(env):
    env.prepare()
    env.lr_.fail["P1"] = RuntimeError("这张照片已不在目录中")
    env.confirm(["P1", "P2"])
    st = finish(env)
    assert [r["status"] for r in st["results"]] == ["failed", "ok"]
    assert "不在目录" in st["results"][0]["message"] and st["summary"] == {"n": 2, "ok": 1, "failed": 1, "uncertain": 0}


def test_timeout_is_uncertain_and_keeps_edit_id_when_found(env):
    env.prepare()
    env.lr_.fail["P1"] = BridgeTimeout("慢")
    env.lr_.latest["P1"] = "E-late"
    env.confirm(["P1", "P2"])
    st = finish(env)
    assert st["results"][0]["status"] == "uncertain" and "不确定" in st["results"][0]["message"] and st["results"][0]["has_edit"]
    assert st["results"][1]["status"] == "ok" and st["summary"]["uncertain"] == 1
    assert env.undo()["ok"]
    assert ("E-late", False) in env.lr_.undo_calls


def test_unverified_write_is_uncertain(env):
    env.prepare()
    env.lr_.verified["P2"] = False
    env.confirm(["P2"])
    st = finish(env)
    assert st["results"][0]["status"] == "uncertain" and "未能核对" in st["results"][0]["message"]


def test_plugin_disconnect_aborts_remaining(env):
    env.prepare()
    env.lr_.fail["P1"] = PluginNotConnected("x")
    env.confirm(["P1", "P2"])
    st = finish(env)
    assert [r["status"] for r in st["results"]] == ["failed", "failed"] and len(env.lr_.calls) == 1


def test_progress_and_done_events(env):
    env.prepare()
    env.confirm(["P1", "P2"])
    finish(env)
    kinds = [e["type"] for e in env.events]
    assert kinds[0] == "pick_apply_progress" and kinds[-1] == "pick_apply_done"
    assert "edit_id" not in str(env.events[-1])                   # 记录号不给页面


def test_double_confirm_and_busy_state(env):
    env.prepare()
    gate = threading.Event()
    orig = env.lr_.set_rating_flag

    def slow(*a, **k):
        gate.wait(2)
        return orig(*a, **k)
    env.lr_.set_rating_flag = slow
    assert env.confirm(["P1"])["ok"]
    assert not env.confirm(["P1"])["ok"]                          # 写入中：清单已失效
    assert not env.prepare()["ok"] and "正在写入" in env.prepare()["message"]
    gate.set()
    finish(env)


# ---------------------------------------------------------------- 撤销
def test_undo_restores_each_edit_and_marks_done(env):
    env.prepare()
    env.confirm(["P1", "P2"])
    finish(env)
    r = env.undo()
    assert r["ok"] and [x["status"] for x in r["results"]] == ["undone", "undone"]
    assert env.lr_.undo_calls == [("E1", False), ("E2", False)]   # 默认不强制
    assert all(x["undone"] for x in env.state_public()["results"])
    assert "没有可撤销" in env.undo()["message"]                   # 不能撤销两次


def test_undo_conflict_is_not_forced_by_default_then_force(env):
    env.prepare()
    env.confirm(["P1", "P2"])
    finish(env)
    env.lr_.undo_result["E1"] = {"ok": False, "conflict": True, "message": "这些目录信息在修改后又发生变化：rating"}
    r = env.undo()
    assert not r["ok"] and r["partial"] and r["conflict"]
    assert [x["status"] for x in r["results"]] == ["conflict", "undone"]
    env.lr_.undo_result["E1"] = {"ok": True, "conflict": False, "message": ""}
    r = env.undo(force=True)                                      # 用户明确同意后才强制，且只重试没还原的
    assert r["ok"] and env.lr_.undo_calls[-1] == ("E1", True) and len(env.lr_.undo_calls) == 3


def test_undo_failure_reported(env):
    env.prepare()
    env.confirm(["P2"])
    finish(env)
    env.lr_.undo_result["E1"] = {"ok": False, "conflict": False, "message": "只读模式已开启，无法还原。"}
    r = env.undo()
    assert not r["ok"] and r["results"][0]["status"] == "failed" and "只读" in r["results"][0]["message"]


def test_undo_without_a_write(env):
    assert not env.undo()["ok"]
    env.prepare()
    assert not env.undo()["ok"]


def test_close_resets(env):
    env.prepare()
    env.confirm(["P2"])
    finish(env)
    env.close()
    assert env.state_public() == {"stage": "idle", "summary": None, "results": []}
