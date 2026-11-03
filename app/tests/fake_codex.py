"""Small JSONL Codex CLI stand-in for provider contract tests."""
import json
import sys
import time


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


prompt = sys.argv[-1]
emit({"type": "thread.started", "thread_id": "TEST-THREAD"})
emit({"type": "turn.started"})
if prompt.endswith("boom"):
    emit({"type": "turn.failed", "error": {"message": "failed"}})
    sys.exit(1)
if prompt.endswith("slow"):
    emit({"type": "item.completed", "item": {"id": "text1", "type": "agent_message", "text": "开始"}})
    time.sleep(30)
    sys.exit(0)
emit({"type": "item.completed", "item": {"id": "text1", "type": "agent_message", "text": "好的"}})
emit({"type": "item.started", "item": {"id": "tool1", "type": "mcp_tool_call", "server": "lightroom_mcp",
                                     "tool": "lr_status", "arguments": {}, "status": "in_progress"}})
emit({"type": "item.completed", "item": {"id": "tool1", "type": "mcp_tool_call", "server": "lightroom_mcp",
                                       "tool": "lr_status", "arguments": {}, "status": "completed",
                                       "result": {"content": [{"type": "text", "text": "ok"}]}}})
emit({"type": "item.completed", "item": {"id": "text2", "type": "agent_message", "text": "完成"}})
emit({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 2}})
