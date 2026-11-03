"""一轮对话各阶段的计时（只记事件名与时间，不含对话内容、参数值、口令）。

用法：t = TurnTimer("per_turn"); t.mark("spawn"); t.observe(事件) ...; t.summary() / t.write()
阶段（相对“发起”的毫秒）：spawn 进程已启动 -> init 收到 system/init -> first_tool 首个工具调用 ->
每个工具的往返（tool_start -> tool_end）-> first_text 首个文字 -> done 结束。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

TIMING_LOG = Path.home() / "LrMcp" / "app_timing.jsonl"


class TurnTimer:
    def __init__(self, mode: str, clock=time.monotonic):
        self.mode = mode
        self._clock = clock
        self._t0 = clock()
        self.marks: list[tuple[str, float]] = []      # (名称, 相对毫秒)
        self._tool_start: dict[str, tuple[str, float]] = {}
        self.tools: list[dict] = []                   # [{"name", "ms"}]
        self._seen: set[str] = set()

    def now_ms(self) -> float:
        return (self._clock() - self._t0) * 1000

    def mark(self, name: str, once: bool = False) -> None:
        if once and name in self._seen:
            return
        self._seen.add(name)
        self.marks.append((name, round(self.now_ms(), 1)))

    def at(self, name: str) -> float | None:
        return next((t for n, t in self.marks if n == name), None)

    def observe(self, ev: dict) -> None:
        """从界面事件里提取阶段；不记录任何文字内容。"""
        kind = ev.get("type")
        if kind == "session":
            self.mark("init", once=True)
        elif kind == "text":
            self.mark("first_text", once=True)
        elif kind == "tool":
            self.mark("first_tool", once=True)
            self._tool_start[ev.get("id") or ""] = (ev.get("name", "?"), self.now_ms())
        elif kind == "tool_result":
            name, start = self._tool_start.pop(ev.get("id") or "", ("?", self.now_ms()))
            self.tools.append({"name": name, "ms": round(self.now_ms() - start, 1)})
        elif kind == "done":
            self.mark("done", once=True)

    def summary(self) -> dict:
        total = self.at("done") if self.at("done") is not None else round(self.now_ms(), 1)
        init = self.at("init")
        tools_ms = round(sum(t["ms"] for t in self.tools), 1)
        out = {
            "mode": self.mode, "total_ms": total, "marks": dict(self.marks),
            "tools": self.tools, "tools_ms": tools_ms,
        }
        if init is not None:
            # 软件开销 = 发起到 init（进程与 MCP 服务启动）；模型时间 = 其余扣除工具往返
            out["startup_ms"] = init
            out["model_ms"] = round(max(total - init - tools_ms, 0), 1)
        else:
            out["model_ms"] = round(max(total - tools_ms, 0), 1)
        return out

    def write(self, path: Path = TIMING_LOG) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            row = {"t": time.strftime("%Y-%m-%d %H:%M:%S"), **self.summary()}
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass
