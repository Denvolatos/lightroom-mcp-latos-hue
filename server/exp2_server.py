"""Experiment 2: tiny local HTTP server to test LrHttp from the Lightroom plug-in.

Standard library only. Binds 127.0.0.1 only, checks Host / Origin / Bearer token.
Writes a random token to ~/LrMcp/token and logs every request to
~/LrMcp/server.log (the token itself is never logged).
Stops by itself after LIFETIME seconds.
"""
import hmac
import json
import os
import secrets
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 58770
LIFETIME = 1200
# Not under AppData: Claude Desktop is an MSIX app and silently redirects the
# AppData of its child processes, so Lightroom would not see these files.
DIR = Path.home() / "LrMcp"
TOKEN = secrets.token_urlsafe(32)
_log_lock = threading.Lock()


def write_atomic(path: Path, text: str) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="ascii")
    os.replace(tmp, path)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format, *args):
        pass

    def _log(self, status: int) -> None:
        names = ",".join(self.headers.keys())
        line = (
            f"{time.strftime('%H:%M:%S')} {self.command} {self.path} -> {status} | "
            f"Host={self.headers.get('Host')} Origin={self.headers.get('Origin')} "
            f"UA={self.headers.get('User-Agent')} "
            f"CT={self.headers.get('Content-Type')} headers=[{names}]\n"
        )
        with _log_lock, open(DIR / "server.log", "a", encoding="utf-8") as f:
            f.write(line)

    def _reply(self, status: int, obj: dict) -> None:
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self._log(status)

    def do_GET(self):
        if self.headers.get("Host") != f"{HOST}:{PORT}":
            return self._reply(400, {"error": "bad host"})
        if self.headers.get("Origin") is not None:
            return self._reply(403, {"error": "origin not allowed"})
        got = self.headers.get("Authorization", "").encode("utf-8")
        if not hmac.compare_digest(got, f"Bearer {TOKEN}".encode("utf-8")):
            return self._reply(401, {"error": "unauthorized"})

        url = urllib.parse.urlparse(self.path)
        if url.path == "/ping":
            return self._reply(200, {"ok": True, "t": time.time()})
        if url.path == "/slow":
            secs = float(urllib.parse.parse_qs(url.query).get("s", ["1"])[0])
            time.sleep(max(0.0, min(secs, 10.0)))
            return self._reply(200, {"ok": True, "slept": secs})
        return self._reply(404, {"error": "not found"})


def main() -> int:
    DIR.mkdir(parents=True, exist_ok=True)
    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError as e:
        print(f"cannot bind {HOST}:{PORT}: {e}", file=sys.stderr)
        return 1
    write_atomic(DIR / "token", TOKEN)
    write_atomic(DIR / "port", str(PORT))
    threading.Timer(LIFETIME, server.shutdown).start()
    try:
        server.serve_forever()
    finally:
        for name in ("token", "port"):
            try:
                (DIR / name).unlink()
            except FileNotFoundError:
                pass
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
