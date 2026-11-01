"""Development bridge (NOT part of the shipped product).

Lets the developer run Lua test scripts inside Lightroom without clicking menus:
  dev_run.py --POST /submit--> this server <--GET /poll-- plug-in (DevLoop.lua) --POST /result--> this server
Only a script NAME travels through the bridge. Binds 127.0.0.1 only; every request needs the random token
(~/LrMcp/token), a correct Host header and no Origin header. The plug-in additionally only runs files from its own
devscripts/ folder, refuses anything outside the 'ceshi' test setup in the scripts themselves, and only runs while
~/LrMcp/dev_enabled exists (created by this server, removed when it stops).
Standard library only. Stops by itself after LIFETIME seconds.
"""
import hmac
import itertools
import os
import queue
import secrets
import socket
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORTS = range(58770, 58790)   # same range as the real server; the first free port is used
PORT = PORTS[0]              # set in main()
LIFETIME = 6 * 3600
POLL_HOLD = 10
# Not under AppData: Claude Desktop is an MSIX app and redirects the AppData of its child processes.
DIR = Path.home() / "LrMcp"
TOKEN = secrets.token_urlsafe(32)

jobs: "queue.Queue[tuple[int, str]]" = queue.Queue()
events: dict[int, threading.Event] = {}
results: dict[int, str] = {}
ids = itertools.count(1)
state = {"latest_gen": 0.0, "last_seen": 0.0}
lock = threading.Lock()


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="ascii")
    os.replace(tmp, path)


class ExclusiveServer(ThreadingHTTPServer):
    """No SO_REUSEADDR on Windows: two programs must never share a port."""

    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def _reply(self, status: int, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _authorized(self) -> bool:
        if self.headers.get("Host") != f"{HOST}:{PORT}":
            self._reply(400, "bad host")
            return False
        if self.headers.get("Origin") is not None:
            self._reply(403, "origin not allowed")
            return False
        got = self.headers.get("Authorization", "").encode("utf-8")
        if not hmac.compare_digest(got, f"Bearer {TOKEN}".encode("utf-8")):
            self._reply(401, "unauthorized")
            return False
        return True

    def _body(self) -> str:
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode("utf-8", "replace") if n else ""

    def do_GET(self):
        if not self._authorized():
            return
        url = urllib.parse.urlparse(self.path)
        if url.path == "/poll":
            try:
                gen = float(self.headers.get("X-Gen") or 0)
            except ValueError:
                gen = 0.0
            with lock:
                state["last_seen"] = time.time()
                if gen < state["latest_gen"]:
                    return self._reply(200, "stop")  # an older plug-in instance must exit
                state["latest_gen"] = gen
            try:
                job_id, path = jobs.get(timeout=POLL_HOLD)
            except queue.Empty:
                return self._reply(200, "none")
            return self._reply(200, f"run {job_id} {path}")
        if url.path == "/status":
            age = time.time() - state["last_seen"] if state["last_seen"] else -1
            return self._reply(200, f"plugin_last_poll_age_s={age:.1f} queued={jobs.qsize()}")
        return self._reply(404, "not found")

    def do_POST(self):
        if not self._authorized():
            return
        url = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(url.query)
        body = self._body()
        if url.path == "/submit":
            timeout = float(query.get("t", ["120"])[0])
            age = time.time() - state["last_seen"] if state["last_seen"] else 1e9
            if age > 40:
                return self._reply(503, "PLUGIN NOT POLLING (reload the plug-in in Lightroom once)")
            job_id = next(ids)
            events[job_id] = threading.Event()
            jobs.put((job_id, body.strip()))
            if not events[job_id].wait(timeout):
                return self._reply(504, f"TIMEOUT waiting for job {job_id}")
            return self._reply(200, results.pop(job_id, ""))
        if url.path == "/result":
            job_id = int(query.get("id", ["0"])[0])
            results[job_id] = body
            ev = events.pop(job_id, None)
            if ev:
                ev.set()
            return self._reply(200, "ok")
        return self._reply(404, "not found")


def main() -> int:
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "scripts").mkdir(exist_ok=True)
    global PORT
    (DIR / "servers").mkdir(exist_ok=True)
    server = None
    for candidate in PORTS:
        try:
            server = ExclusiveServer((HOST, candidate), Handler)
            PORT = candidate
            break
        except OSError:
            continue
    if server is None:
        print(f"no free port in {PORTS[0]}-{PORTS[-1]}", file=sys.stderr)
        return 1
    # announce ourselves like a real server does, so the plug-in polls us; dev_run.py reads dev_server.txt
    info = f"port={PORT}\ntoken={TOKEN}\npid={os.getpid()}\nversion=dev\n"
    announce = DIR / "servers" / f"{PORT}.txt"
    write_atomic(announce, info)
    write_atomic(DIR / "dev_server.txt", info)
    write_atomic(DIR / "dev_enabled", "1")
    threading.Timer(LIFETIME, server.shutdown).start()
    try:
        server.serve_forever()
    finally:
        for path in (announce, DIR / "dev_server.txt", DIR / "dev_enabled"):
            path.unlink(missing_ok=True)
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
