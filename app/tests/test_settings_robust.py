# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""1.1.1 设置容错：文件夹暂时不在时不清空、空工作文件夹也能保存其他设置、坏文件留档、并发保存。"""
import json

import settings as st


def _store(path):
    return st.SettingsStore(path, restrict=lambda p: None)


# ---------------------------------------------------------------- 文件夹暂时不在时保留原值
def test_offline_work_folder_is_kept_on_load_and_not_written_back(tmp_path):
    gone = "Z:\\移动硬盘\\照片工作"                      # 盘符不存在（移动硬盘没接上）
    export_gone = "Z:\\移动硬盘\\导出"
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"base_folder": gone, "export_last_folder": export_gone, "provider_chosen": True}),
                 encoding="utf-8")
    s = _store(p)
    assert s.data["base_folder"] == gone and s.data["export_last_folder"] == export_gone
    assert s.update({"wizard_done": True})["ok"]          # 之后任何一次保存都不能把空值写回
    saved = json.loads(p.read_text(encoding="utf-8"))
    assert saved["base_folder"] == gone and saved["export_last_folder"] == export_gone


def test_load_still_rejects_bad_folder_formats(tmp_path):
    p = tmp_path / "s.json"
    for bad in ("relative/path", "\\\\server\\share\\x", "C:\\", "C:\\Windows\\x"):
        p.write_text(json.dumps({"base_folder": bad, "export_last_folder": bad}), encoding="utf-8")
        d = _store(p).data
        assert d["base_folder"] == "" and d["export_last_folder"] == "", bad


def test_wizard_reports_missing_folder_branch_after_load(tmp_path):
    import wizard
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"base_folder": "Z:\\不在了"}), encoding="utf-8")
    s = _store(p)
    w = wizard.WizardChecker(lambda: s.data, find_lightroom=lambda c: None, is_running=lambda: False,
                             get_connection=lambda: {}, get_provider=lambda: {}, spawn=lambda fn: fn())
    folder = w.check()[0]
    assert folder["state"] == wizard.TODO and "找不到了" in folder["text"]


# ---------------------------------------------------------------- 工作文件夹为空 / 不变时也能保存其他设置
def test_empty_work_folder_does_not_block_other_settings(tmp_path):
    s = _store(tmp_path / "s.json")
    assert s.data["base_folder"] == ""
    r = s.update({"base_folder": "", "check_updates": False, "confirm_default": False})
    assert r["ok"] and s.data["check_updates"] is False and s.data["confirm_default"] is False


def test_unchanged_offline_work_folder_is_not_revalidated(tmp_path):
    p = tmp_path / "s.json"
    gone = r"Z:\移动硬盘\照片工作"
    p.write_text(json.dumps({"base_folder": gone}), encoding="utf-8")
    s = _store(p)
    r = s.update({"base_folder": gone, "check_updates": False})
    assert r["ok"] and s.data["base_folder"] == gone and s.data["check_updates"] is False
    r = s.update({"base_folder": r"Z:\别的盘\新文件夹"})          # 真的换了：照常完整校验
    assert not r["ok"] and "base_folder" in r["errors"]


def test_work_folder_can_be_cleared(tmp_path):
    folder = tmp_path / "w"
    folder.mkdir()
    s = _store(tmp_path / "s.json")
    assert s.update({"base_folder": str(folder)})["ok"]
    assert s.update({"base_folder": ""})["ok"] and s.data["base_folder"] == ""


class _Spy:
    def __init__(self):
        self.calls = 0

    def __call__(self, *a, **k):
        self.calls += 1


def _fake_api(store):
    import main
    api = main.Api.__new__(main.Api)
    api._settings = store
    api._pending_lr_path = ""
    api._ai_chosen = lambda: True
    api._preview = type("P", (), {"set_edge": lambda self, e: e})()
    api._wizard = type("W", (), {})()
    api._wizard.invalidate = _Spy()
    api._photolib = type("L", (), {})()
    api._photolib.refresh = _Spy()
    return api


def test_save_settings_refreshes_gallery_and_wizard_when_folder_changes(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    s = _store(tmp_path / "s.json")
    api = _fake_api(s)
    assert api.save_settings({"check_updates": False})["ok"]
    assert api._photolib.refresh.calls == 0 and api._wizard.invalidate.calls == 0     # 没换文件夹：不刷新
    assert api.save_settings({"base_folder": str(a)})["ok"]
    assert api._photolib.refresh.calls == 1 and api._wizard.invalidate.calls == 1
    assert api.save_settings({"gallery_folder": str(b)})["ok"]
    assert api._photolib.refresh.calls == 2 and api._wizard.invalidate.calls == 2
    assert api.save_settings({"base_folder": str(a), "gallery_folder": str(b)})["ok"]   # 同样的值：不刷新
    assert api._photolib.refresh.calls == 2


# ---------------------------------------------------------------- 读失败不当成全新安装；并发保存
def test_missing_file_is_a_fresh_install(tmp_path):
    assert _store(tmp_path / "none.json").data["provider_chosen"] is False


def test_bom_file_is_read(tmp_path):
    p = tmp_path / "s.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"provider": "codex", "check_updates": False}).encode("utf-8"))
    d = _store(p).data
    assert d["provider"] == "codex" and d["check_updates"] is False and d["provider_chosen"] is True
    assert not list(tmp_path.glob("*.bad-*"))


def test_transient_read_failure_is_retried(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "READ_RETRY_SECONDS", 0)
    p = tmp_path / "s.json"
    p.write_text(json.dumps({"provider": "codex", "provider_chosen": True}), encoding="utf-8")
    real = type(p).read_text
    calls = []

    def flaky(self, *a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError(13, "被占用")
        return real(self, *a, **k)
    monkeypatch.setattr(type(p), "read_text", flaky)
    d = _store(p).data
    assert len(calls) == 2 and d["provider"] == "codex" and p.exists()


def test_unreadable_file_keeps_choice_and_is_backed_up(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "READ_RETRY_SECONDS", 0)
    p = tmp_path / "s.json"
    p.write_text("{坏了", encoding="utf-8")
    s = _store(p)
    assert s.data["provider_chosen"] is True
    backups = list(tmp_path.glob("s.json.bad-*"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "{坏了"


def test_concurrent_updates_do_not_lose_changes(tmp_path):
    import threading
    s = _store(tmp_path / "s.json")
    keys = ["confirm_default", "ai_use_notes", "auto_launch_lightroom", "wizard_done", "check_updates"]
    errors = []

    def worker(k):
        for _ in range(20):
            r = s.update({k: not st.defaults()[k]})
            if not r["ok"]:
                errors.append(r)
    ts = [threading.Thread(target=worker, args=(k,)) for k in keys]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    saved = json.loads((tmp_path / "s.json").read_text(encoding="utf-8"))
    assert not errors and all(saved[k] == (not st.defaults()[k]) for k in keys)
    assert not list(tmp_path.glob("*.tmp"))
