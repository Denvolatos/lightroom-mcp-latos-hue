# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""界面截图自查（无窗口、无 Lightroom、不调用模型，不属于 pytest）。
用 live_preview_check.py 存下的测试照片预览（initial.jpg / adjusted.jpg）放进真实的 PreviewServer，
临时本机静态服务加载 index.html（注入假的 pywebview.api），再用无头 Edge 截图。用完全部关闭。
用法：python app/tests/ui_preview_check.py <预览目录> <截图输出目录>
"""
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from preview import PreviewServer, PreviewStore  # noqa: E402

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"

STUB = """<script>
(function(){
  const q = new URLSearchParams(location.search), S = window.__SCEN__;
  const scen = q.get('s') || 'ok';
  window.pywebview = {api: {
    send: ()=>Promise.resolve({ok:true}), stop(){}, reset(){}, answer(){}, undo(){}, restore_original(){},
    status: ()=>Promise.resolve({state:'connected', text:'Lightroom 已连接', hint:'', photo:{id:'P', name:'DSC08238.ARW'}}),
    preview_state: ()=>Promise.resolve(S[scen]), set_preview_edge: ()=>Promise.resolve({ok:true})
  }};
})();
</script>"""
TAIL = """<script>
window.dispatchEvent(new Event('pywebviewready'));
setTimeout(()=>{
  const S = window.__SCEN__, scen = new URLSearchParams(location.search).get('s') || 'ok';
  if (scen === 'ok' || scen === 'zoom') {
    window.onClaudeEvent({type:'adjust', rows:[{label:'曝光', before:'0', after:'0.1', status:'已应用', edit_id:'e1', reason:'整体略微提亮'}]});
    window.onClaudeEvent({type:'status', state:'connected', text:'Lightroom 已连接', hint:''});
  }
  if (scen === 'zoom') document.getElementById('zoom').click();
  if (scen === 'busy') window.onClaudeEvent(Object.assign({loading:true}, S.ok));
}, 50);
</script>"""


def main(src: Path, out: Path) -> None:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    store = PreviewStore()
    server = PreviewServer(store)
    server.start()
    e0 = store.put("P", 1024, "v0", (src / "initial.jpg").read_bytes(), (1024, 683))
    e1 = store.put("P", 1024, "v1", (src / "adjusted.jpg").read_bytes(), (1024, 683))
    photo = {"id": "P", "name": "DSC08238.ARW", "camera": "Sony ILCE-7CM2", "iso": "ISO 100", "aperture": "ƒ / 8.0",
             "shutter": "1/800 秒", "focal": "20 mm", "format": "RAW", "size": "3504 × 2336"}
    img = lambda e: {"url": server.url_for(e), "w": 1024, "h": 683, "version": e["version"]}
    scen = {
        "ok": {"type": "preview", "state": "ok", "photo": photo, "initial": img(e0), "current": img(e1), "same": False, "edge": 1024},
        "same": {"type": "preview", "state": "ok", "photo": photo, "initial": img(e0), "current": img(e0), "same": True, "edge": 1024},
        "error": {"type": "preview", "state": "error", "message": "无法读取预览：请确认 Lightroom 已打开并选中了照片"},
        "loading": {"type": "preview", "state": "loading", "message": "正在读取预览", "photo": photo},
        "none": {"type": "preview", "state": "none", "message": "Lightroom 中未选中照片"},
    }
    scen["zoom"] = scen["busy"] = scen["ok"]
    html = WEB.read_text(encoding="utf-8")
    html = html.replace("<script>", "<script>window.__SCEN__=" + json.dumps(scen, ensure_ascii=False) + ";</script>" + STUB + "\n<script>", 1)
    html = html.replace("</body>", TAIL + "</body>")
    page = html.encode("utf-8")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        for name in ("ok", "same", "error", "loading", "none", "zoom", "busy"):
            target = out / f"preview_{name}.png"
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1440,860",
                            "--virtual-time-budget=4000", f"--screenshot={target}", f"http://127.0.0.1:{httpd.server_address[1]}/?s={name}"],
                           check=True, timeout=60, capture_output=True)
            print("截图", target)
    finally:
        httpd.shutdown()
        server.stop()


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
