import json
import time

from lightroom_mcp import update
from lightroom_mcp.update import UpdateChecker, is_newer


def test_version_compare():
    assert is_newer("v0.3.1", "0.3.0") and is_newer("v1.0.0", "0.9.9")
    assert not is_newer("v0.3.0", "0.3.0") and not is_newer("v0.2.9", "0.3.0")
    assert not is_newer("latest", "0.3.0") and not is_newer("", "0.3.0")


def test_notice_when_newer(tmp_path):
    c = UpdateChecker(tmp_path, fetch=lambda: "v0.4.0", current="0.3.0")
    c.check_now()
    assert "0.4.0" in c.notice() and "不会自动更新" in c.notice()


def test_no_notice_when_current(tmp_path):
    c = UpdateChecker(tmp_path, fetch=lambda: "v0.3.0", current="0.3.0")
    c.check_now()
    assert c.notice() is None


def test_asks_only_once_a_day(tmp_path):
    calls = []
    c = UpdateChecker(tmp_path, fetch=lambda: calls.append(1) or "v0.4.0", current="0.3.0")
    c.check_now()
    c.check_now()
    assert len(calls) == 1
    (tmp_path / "update_check.json").write_text(json.dumps({"checked_at": time.time() - 90000, "latest": "v0.4.0"}))
    c.check_now()
    assert len(calls) == 2


def test_offline_is_silent(tmp_path):
    def boom():
        raise OSError("offline")
    c = UpdateChecker(tmp_path, fetch=boom, current="0.3.0")
    c.check_now()
    assert c.notice() is None


def test_opt_out_file_and_env(tmp_path, monkeypatch):
    calls = []
    c = UpdateChecker(tmp_path, fetch=lambda: calls.append(1) or "v9.9.9", current="0.3.0")
    (tmp_path / "no_update_check").write_text("")
    c.check_now()
    assert not calls and c.notice() is None
    (tmp_path / "no_update_check").unlink()
    monkeypatch.setenv("LRMCP_NO_UPDATE_CHECK", "1")
    c.check_now()
    assert not calls and c.notice() is None
    assert update.disabled(tmp_path)
