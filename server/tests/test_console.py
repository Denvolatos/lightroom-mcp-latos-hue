# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
import io

from lightroom_mcp.__main__ import out


def stream(encoding):
    return io.TextIOWrapper(io.BytesIO(), encoding=encoding, write_through=True)


def test_gbk_console_does_not_crash_on_check_marks():
    s = stream("gbk")
    out("✅ 正常\n❌ 有问题\n   → 处理办法\nℹ️ 提示", s)  # used to raise UnicodeEncodeError on a Chinese Windows console
    text = s.buffer.getvalue().decode("gbk")
    assert "[OK] 正常" in text and "[X] 有问题" in text and "-> 处理办法" in text and "[i] 提示" in text


def test_utf8_console_keeps_the_marks():
    s = stream("utf-8")
    out("✅ 正常", s)
    assert "✅ 正常" in s.buffer.getvalue().decode("utf-8")
