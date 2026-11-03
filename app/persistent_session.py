"""常驻的 claude 会话（--input-format stream-json）。

软件启动时预热一次：claude 进程、lightroom_mcp 服务、确认服务、插件连接都只在启动（或重建）时建立一次，
之后每条消息零启动开销。命令参数、事件解析、错误翻译沿用 claude_bridge.py。
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

import claude_bridge as cb
from ports import clean_stale_announcements
from timing import TurnTimer

INTERRUPT_GRACE = 6          # 发出中断后，等多少秒还没结束就强制重启进程


def kill_tree(proc) -> None:
    """结束 claude 及其启动的 MCP 子进程（Windows 用 taskkill /T，避免遗留孤儿服务与失效公告）。"""
    if proc is None or proc.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            proc.kill()
    except (OSError, subprocess.SubprocessError):
        try:
            proc.kill()
        except OSError:
            pass


class _Turn:
    def __init__(self, emit):
        self.emit = emit
        self.done = threading.Event()
        self.timer = TurnTimer("persistent")
        self.stopped = False
        self.timed_out = False
        self.got_done = False


class PersistentSession:
    """- send(): 把消息写入标准输入，阻塞到本轮 result 到达（界面里应放在后台线程）。
    - stop(): 发 control_request/interrupt 中断当前轮，进程与对话保留；超过 INTERRUPT_GRACE 秒无结果则结束进程并用 --resume 重建。
    - reset(): 结束进程并重新预热一个全新的对话（新对话）。
    - 进程意外退出：下一次 send() 或后台巡检（ensure_running）会用 --resume 重建，对话上下文保留。
    """

    def __init__(self, workdir: Path = cb.WORKDIR, popen=subprocess.Popen, state_file: Path | None = None):
        self.workdir = workdir
        self._popen = popen
        self.state_file = state_file
        self.session_id: str | None = None
        self.last_timing: dict | None = None
        self.last_error: str | None = None
        self.extra_env: dict = {}
        self.spawned_at: float | None = None      # time.monotonic()
        self.generation = 0                         # 每次启动 +1
        self.restart_count = 0
        self._proc = None
        self._turn: _Turn | None = None
        self._lock = threading.RLock()
        self._parse_state: dict = {}
        self._err_tail: list[str] = []
        self._closed = False

    # ---- 状态 ------------------------------------------------------
    @property
    def alive(self) -> bool:
        p = self._proc
        return bool(p is not None and p.poll() is None)

    @property
    def busy(self) -> bool:
        return self._turn is not None

    # ---- 进程管理 --------------------------------------------------
    def start(self, extra_env: dict | None = None, resume: bool = True) -> bool:
        """启动（预热）进程。已在运行则什么也不做。"""
        with self._lock:
            if extra_env is not None:
                self.extra_env = dict(extra_env)
            if self.alive:
                return True
            claude = cb.find_claude()
            if not claude:
                self.last_error = cb.MSG_NO_CLAUDE
                return False
            self.workdir.mkdir(parents=True, exist_ok=True)
            if self.state_file is not None:
                try:
                    self.state_file.unlink(missing_ok=True)      # 防止读到上一个进程留下的状态
                except OSError:
                    pass
            cmd = cb.build_command(None, cb.write_mcp_config(state_file=self.state_file),
                                   self.session_id if resume else None, claude, True, persistent=True)
            try:
                proc = self._popen(
                    cmd, cwd=str(self.workdir), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, env={**os.environ, **self.extra_env}, encoding="utf-8", errors="replace",
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except OSError:
                self.last_error = cb.MSG_NO_CLAUDE
                return False
            self._proc = proc
            self._parse_state = {}
            self._err_tail = []
            self.generation += 1
            self.spawned_at = time.monotonic()
            self.last_error = None
            threading.Thread(target=self._read_stdout, args=(proc, self.generation), daemon=True).start()
            threading.Thread(target=self._read_stderr, args=(proc,), daemon=True).start()
            return True

    def ensure_running(self) -> bool:
        """进程已退出则用 --resume 重建（巡检与 send 共用）。"""
        with self._lock:
            if self.alive or self._closed:
                return self.alive
            if self._proc is not None:
                self.restart_count += 1
            return self.start()

    def restart(self, resume: bool = True) -> bool:
        with self._lock:
            self._kill()
            self.restart_count += 1
            return self.start(resume=resume)

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        kill_tree(proc)
        if proc is not None:
            try:
                proc.stdin.close()
            except Exception:
                pass
            try:
                clean_stale_announcements()                  # 被强制结束的服务不会自己删除公告，这里代为清理
            except Exception:
                pass

    def shutdown(self) -> None:
        """退出软件时：先关闭输入让 claude 自己清理（会删除服务公告），超时再强制结束。"""
        with self._lock:
            self._closed = True
            proc = self._proc
            if proc is not None:
                try:
                    proc.stdin.close()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=3)
                except Exception:
                    pass
            self._kill()

    # ---- 读取输出 --------------------------------------------------
    def _read_stderr(self, proc) -> None:
        try:
            for line in proc.stderr:
                self._err_tail = (self._err_tail + [line])[-20:]
        except Exception:
            pass

    def _read_stdout(self, proc, gen: int) -> None:
        try:
            for line in proc.stdout:
                for ev in cb.parse_line(line, self._parse_state):
                    self._dispatch(ev)
        except Exception:
            pass
        with self._lock:                                  # 输出结束：进程已退出
            if gen != self.generation:
                return                                    # 已被新进程取代（主动重建）
            turn = self._turn
        if turn is not None and not turn.got_done:
            self._finish_turn_abnormal(turn)

    def _dispatch(self, ev: dict) -> None:
        if ev["type"] == "session":
            self.session_id = ev["id"] or self.session_id
        with self._lock:
            turn = self._turn
        if turn is None:
            return
        if ev["type"] == "done":
            self.session_id = ev.get("session_id") or self.session_id
        if turn.stopped and ev["type"] in ("error", "done"):
            if ev["type"] == "done":                      # 中断后收到的结果：改成“已停止”
                turn.got_done = True
                turn.timer.observe(ev)
                self._end_turn(turn, [{"type": "stopped"},
                                      {"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True}])
            return                                        # 中断产生的“错误”不展示
        turn.timer.observe(ev)
        if ev["type"] == "done":
            turn.got_done = True
            self._end_turn(turn, [ev])
        else:
            turn.emit(ev)

    def _end_turn(self, turn: _Turn, events: list[dict]) -> None:
        with self._lock:
            if self._turn is turn:
                self._turn = None
            elif turn.done.is_set():
                return
        for ev in events:
            turn.emit(ev)
        self.last_timing = turn.timer.summary()
        turn.timer.write()
        turn.done.set()

    def _finish_turn_abnormal(self, turn: _Turn) -> None:
        if turn.done.is_set():
            return
        if turn.stopped:
            events = [{"type": "stopped"}]
        elif turn.timed_out:
            events = [{"type": "error", "message": cb.MSG_TIMEOUT}]
        else:
            events = [{"type": "error", "message": cb.friendly_error("".join(self._err_tail) or "命令行意外退出")}]
        events.append({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
        self._end_turn(turn, events)

    # ---- 发送、中断、重置 ------------------------------------------
    def _write(self, obj: dict) -> bool:
        proc = self._proc
        if proc is None or proc.poll() is not None or proc.stdin is None:
            return False
        try:
            proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            proc.stdin.flush()
            return True
        except (OSError, ValueError):
            return False

    def send(self, prompt: str, emit, timeout: float | None = None) -> None:
        timeout = cb.TIMEOUT_SECONDS if timeout is None else timeout
        turn = _Turn(emit)
        err = None
        with self._lock:
            if self._turn is not None:
                err = "上一条请求仍在处理，请稍候。"
            elif not self.ensure_running():
                err = self.last_error or cb.MSG_NO_CLAUDE
            else:
                self._turn = turn
                turn.timer.mark("send")
                msg = {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}}
                if not self._write(msg):                  # 进程恰好退出：重建后重发一次
                    self._kill()
                    self.restart_count += 1
                    if not (self.start() and self._write(msg)):
                        self._turn = None
                        err = cb.friendly_error("".join(self._err_tail) or "命令行未能启动")
        if err:
            emit({"type": "error", "message": err})
            emit({"type": "done", "tokens": 0, "cost": None, "text": "", "is_error": True})
            return
        if not turn.done.wait(timeout):
            turn.timed_out = True
            with self._lock:
                self._kill()                              # 超时：结束进程，稍后用 --resume 重建
            self._finish_turn_abnormal(turn)
            threading.Thread(target=self.ensure_running, daemon=True).start()

    def stop(self) -> None:
        """中断当前轮（进程与对话保留）。"""
        with self._lock:
            turn = self._turn
            if turn is None:
                return
            turn.stopped = True
            self._write({"type": "control_request", "request_id": f"stop-{int(time.time() * 1000)}",
                         "request": {"subtype": "interrupt"}})
        threading.Thread(target=self._interrupt_watchdog, args=(turn,), daemon=True).start()

    def _interrupt_watchdog(self, turn: _Turn) -> None:
        if turn.done.wait(INTERRUPT_GRACE):
            return
        with self._lock:                                  # 中断无效：强制结束进程，对话用 --resume 保留
            self._kill()
        self._finish_turn_abnormal(turn)
        self.ensure_running()

    def reset(self) -> None:
        """新对话：结束进程与上下文，立即预热一个全新的会话。"""
        with self._lock:
            turn = self._turn
            if turn is not None:
                turn.stopped = True
            self._kill()
            self.session_id = None
            self.generation += 1                          # 让旧读取线程知道自己已被取代
        if turn is not None:
            self._finish_turn_abnormal(turn)
        with self._lock:
            if not self._closed:
                self.start(resume=False)
