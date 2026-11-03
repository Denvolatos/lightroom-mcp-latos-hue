"""真实计时（会消耗订阅额度，不属于 pytest）。
用法：python app/tests/live_timing.py per_turn|persistent <序列数> [输出json]
每个序列 2 轮（第 1 轮=冷启动首轮，第 2 轮=后续轮），问题为只读问题。结果只含时间与工具名。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import time  # noqa: E402
from claude_bridge import ClaudeSession  # noqa: E402
from persistent_session import PersistentSession  # noqa: E402

QUESTIONS = ["读取当前照片的曝光和高光值，只回答两个数字。", "再读取色温和色调，只回答两个数字。"]
mode, n = sys.argv[1], int(sys.argv[2])
out = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("live_timing_result.json")
env = {"LRAPP_PORT": "1", "LRAPP_TOKEN": "x"}
rows = []
if mode == "persistent":
    st = Path.home() / "LrMcp" / "app_state" / "claude_side.json"
    ps = PersistentSession(state_file=st)
    for seq in range(n):
        t0 = time.monotonic()
        ps.start(env) if seq == 0 else ps.reset()
        while time.monotonic() - t0 < 40:                       # 预热：等到插件连上
            try:
                if json.loads(st.read_text())["connected"]:
                    break
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(0.2)
        warm = round((time.monotonic() - t0) * 1000)
        print("seq", seq, "预热(启动->插件已连上) ms", warm, flush=True)
        rows.append({"seq": seq, "warmup_ms": warm})
        for i, q in enumerate(QUESTIONS):
            ev = []
            ps.send(q, ev.append)
            t = ps.last_timing
            d = [e for e in ev if e["type"] == "done"][-1]
            rows.append({"seq": seq, "turn": i + 1, **t, "tokens": d["tokens"], "error": d["is_error"]})
            print(seq, i + 1, "total", t["total_ms"], "marks", t["marks"], "tools", t["tools"], "model", t["model_ms"], flush=True)
    ps.shutdown()
    out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.exit(0)
for seq in range(n):
    s = ClaudeSession()
    for i, q in enumerate(QUESTIONS):
        ev = []
        s.send(q, ev.append, confirm=True, extra_env=env)
        t = s.last_timing
        d = [e for e in ev if e["type"] == "done"][-1]
        rows.append({"seq": seq, "turn": i + 1, **t, "tokens": d["tokens"], "error": d["is_error"]})
        print(seq, i + 1, "total", t["total_ms"], "startup", t.get("startup_ms"), "tools", t["tools"], "model", t["model_ms"], flush=True)
out.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
