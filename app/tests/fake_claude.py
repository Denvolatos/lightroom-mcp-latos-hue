# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""假的 claude 常驻进程（测试用）：从标准输入读 stream-json 消息，按消息内容演不同剧情。
剧情由用户消息文字决定：hello 正常（含一次工具调用）；slow 一直输出直到收到 interrupt；stubborn 忽略 interrupt；
silent 不回应；die 直接退出。"""
import json
import os
import sys
import time

sys.stdin.reconfigure(encoding="utf-8")
sys.stdout.reconfigure(encoding="utf-8")


def out(obj):
    print(json.dumps(obj, ensure_ascii=False), flush=True)


def result(is_error=False, text="完成"):
    out({"type": "result", "is_error": is_error, "result": text, "session_id": "SESS-1", "total_cost_usd": 0.01,
         "usage": {"input_tokens": 1, "output_tokens": 2}})


def delta(text):
    out({"type": "stream_event", "event": {"type": "content_block_delta",
                                           "delta": {"type": "text_delta", "text": text}}})


import queue
import threading

interrupted = False
inbox = queue.Queue()


def reader():
    global interrupted
    for raw in sys.stdin:
        msg = json.loads(raw)
        if msg.get("type") == "control_request":
            if msg["request"]["subtype"] == "interrupt":
                interrupted = True
                out({"type": "control_response", "response": {"subtype": "success", "request_id": msg["request_id"]}})
        else:
            inbox.put(msg)
    inbox.put(None)


threading.Thread(target=reader, daemon=True).start()
while True:
    msg = inbox.get()
    if msg is None:
        break
    text = msg["message"]["content"][0]["text"]
    out({"type": "system", "subtype": "init", "session_id": "SESS-1"})
    if text == "die":
        sys.exit(1)
    if text == "hello":
        delta(f"pid={os.getpid()}")
        out({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "T1", "name": "mcp__lightroom_mcp__lr_status", "input": {}}]}})
        out({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "T1", "content": "ok"}]}})
        delta("完成")
        result()
    elif text in ("slow", "stubborn"):
        interrupted = False
        delta("开始")
        for _ in range(300):
            time.sleep(0.05)
            if interrupted and text == "slow":
                result(is_error=True, text="Request was aborted")
                break
        else:
            result()
    elif text == "silent":
        time.sleep(30)
