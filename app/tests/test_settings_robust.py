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
