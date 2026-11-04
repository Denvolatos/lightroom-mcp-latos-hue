# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""Experiment 3: Python client for the plug-in's two LrSocket servers.

Waits for ~/LrMcp/sock_ports (written by the plug-in), connects to both ports, then runs:
auth (wrong / before-auth / right), 20 ping round trips, a message without newline,
a 64 KB message, and "done". Also records which address the ports listen on (netstat).
Results go to ~/LrMcp/exp3_result.txt. Standard library only.
"""
import secrets
import socket
import subprocess
import sys
import time
from pathlib import Path

DIR = Path.home() / "LrMcp"
OUT = DIR / "exp3_result.txt"
TOKEN = secrets.token_urlsafe(32)


def note(text: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {text}"
    print(line, flush=True)
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(line + "\n")


class Line:
    """Newline-delimited reader over a socket with a timeout."""

    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.buf = b""

    def read(self, timeout: float = 5.0):
        end = time.monotonic() + timeout
        while b"\n" not in self.buf:
            left = end - time.monotonic()
            if left <= 0:
                return None
            self.sock.settimeout(left)
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                return None
            if not chunk:
                return ""
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return line.decode("utf-8", "replace").strip("\r")


def connect(port: int) -> socket.socket:
    for host in ("127.0.0.1", "::1"):
        family = socket.AF_INET if host == "127.0.0.1" else socket.AF_INET6
        s = socket.socket(family, socket.SOCK_STREAM)
        s.settimeout(3)
        try:
            s.connect((host, port))
            note(f"connected to port {port} via {host}")
            return s
        except OSError as e:
            note(f"connect {host}:{port} failed: {e}")
            s.close()
    raise SystemExit(f"cannot connect to port {port}")


def main() -> int:
    DIR.mkdir(parents=True, exist_ok=True)
    OUT.write_text("", encoding="utf-8")
    for name in ("sock_ports",):
        (DIR / name).unlink(missing_ok=True)
    (DIR / "token").write_text(TOKEN, encoding="ascii")
    note("token written; waiting for plug-in (click the menu item in Lightroom)")

    ports_file = DIR / "sock_ports"
    end = time.monotonic() + 180
    while not ports_file.exists():
        if time.monotonic() > end:
            note("timeout waiting for sock_ports")
            return 1
        time.sleep(0.2)
    time.sleep(0.3)
    ports = dict(line.split("=") for line in ports_file.read_text().split() if "=" in line)
    recv_port, send_port = int(ports["recv"]), int(ports["send"])
    note(f"plug-in ports: receive={recv_port} send={send_port}")

    out = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        if "LISTENING" in line and any(f":{p} " in line for p in (recv_port, send_port)):
            note("netstat: " + " ".join(line.split()))
    out6 = subprocess.run(["netstat", "-ano", "-p", "tcpv6"], capture_output=True, text=True).stdout
    for line in out6.splitlines():
        if "LISTENING" in line and any(f":{p} " in line for p in (recv_port, send_port)):
            note("netstat(v6): " + " ".join(line.split()))

    to_plugin = connect(recv_port)      # plug-in "receive" socket: we write here
    from_plugin = connect(send_port)    # plug-in "send" socket: we read here
    reader = Line(from_plugin)

    def ask(text: str, wait: float = 5.0):
        t0 = time.perf_counter()
        to_plugin.sendall(text.encode() + b"\n")
        got = reader.read(wait)
        return got, (time.perf_counter() - t0) * 1000

    first = reader.read(1.0)
    note(f"unsolicited line after connect: {first!r}")

    note(f"before auth: ping -> {ask('ping 0')[0]!r}")
    note(f"wrong token -> {ask('auth wrong')[0]!r}")
    got, ms = ask(f"auth {TOKEN}")
    note(f"right token -> {got!r} ({ms:.1f} ms)")

    times = []
    bad = 0
    for i in range(20):
        got, ms = ask(f"ping {i}")
        if got != f"pong {i}":
            bad += 1
        times.append(ms)
    note(f"20 pings: bad={bad} avg={sum(times)/len(times):.1f} ms worst={max(times):.1f} ms")

    to_plugin.sendall(b"ping 99")        # no newline
    got = reader.read(2.0)
    note(f"no-newline ping, waited 2s -> {got!r}")
    to_plugin.sendall(b"\n")
    got = reader.read(3.0)
    note(f"then sent just newline -> {got!r}")

    big = "big " + "x" * (64 * 1024)
    got, ms = ask(big, 8.0)
    note(f"64KB message -> {got!r} ({ms:.1f} ms; expect 'len {len(big)}')")

    to_plugin.sendall(b"done\n")
    after = reader.read(5.0)
    note(f"after 'done', send socket read -> {after!r} ('' means closed by plug-in, None means still open)")

    to_plugin.close()
    from_plugin.close()
    (DIR / "token").unlink(missing_ok=True)
    ports_file.unlink(missing_ok=True)
    note("finished")
    return 0


if __name__ == "__main__":
    sys.exit(main())
