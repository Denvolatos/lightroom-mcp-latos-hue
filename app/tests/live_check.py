# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""真实小测试（会消耗订阅额度，不属于 pytest）：python app/tests/live_check.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from claude_bridge import ClaudeSession  # noqa: E402

s = ClaudeSession()
log = []
for q in ["现在 Lightroom 连上了吗？请调用 lr_status 告诉我", "我上一句问了你什么？一句话回答，不要调用工具"]:
    ev = []
    s.send(q, ev.append)
    log.append({"q": q, "session": s.session_id, "events": ev})
out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("live_check_result.json")
out.write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
for t in log:
    print(t["q"], "|", [e["type"] + (":" + e["name"] if e["type"] == "tool" else "") for e in t["events"] if e["type"] != "text"])
    print("  回答:", "".join(e["text"] for e in t["events"] if e["type"] == "text")[:300].encode("gbk", "replace").decode("gbk"))
    d = [e for e in t["events"] if e["type"] == "done"][-1]
    print("  tokens", d["tokens"], "cost", d["cost"], "error", d["is_error"])
