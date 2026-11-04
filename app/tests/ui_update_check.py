# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""检查更新界面自查（无窗口、不联网、不打开浏览器，不属于 pytest）。
临时本机静态服务加载 index.html（注入假的 pywebview.api），用无头 Edge 截图各状态。截图只含假数据。
用法：python app/tests/ui_update_check.py <截图输出目录>
"""
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"

STUB = """<script>
(function(){
  const scen = new URLSearchParams(location.search).get('s') || 'available';
  const U = {
    available: {state:'available', current:'0.15.0', latest:'1.0.0', message:'有新版本 1.0.0', enabled:true},
    latest: {state:'latest', current:'0.15.0', latest:'', message:'已是最新版本', enabled:true},
    unavailable: {state:'unavailable', current:'0.15.0', latest:'', message:'暂时无法检查（可能没联网）', enabled:true},
    checking: {state:'checking', current:'0.15.0', latest:'', message:'检查中…', enabled:true},
  };
  const final = U[scen] || U.available;
  /* available：启动时缓存里就有结果；其余场景从 idle 开始，点“检查更新”后才出结果 */
  let cur = scen === 'available' ? final : {state:'idle', current:'0.15.0', latest:'', message:'', enabled:true};
  const claude = {available:true, state:'ready', reason:'已安装并已登录。', next_step:''};
  const providers = [Object.assign({id:'claude', name:'Claude Code 命令行', selectable:true}, claude)];
  const settings = {schema:1, base_folder:'D:\\示例\\修图助手', provider:'claude', confirm_default:true, preview_edge:1024, check_updates:true};
  window.__CALLS__ = [];
  window.pywebview = {api: {
    send: ()=>Promise.resolve({ok:true}), stop(){}, reset(){}, answer(){}, undo(){}, restore_original(){},
    status: ()=>Promise.resolve({state:'connected', text:'Lightroom 已连接', hint:'', photo:{id:'P', name:'DSC08238.ARW'}}),
    preview_state: ()=>Promise.resolve({type:'preview', state:'none', message:'Lightroom 中未选中照片'}), set_preview_edge: ()=>Promise.resolve({ok:true}),
    autolaunch_state: ()=>Promise.resolve({state:'idle', message:''}),
    get_settings: ()=>Promise.resolve({settings, lightroom_detected:'', providers, current_provider:'claude', edges:[768,1024,1536,2048],
      about:{app_version:'0.15.0', lightroom_version:'15.0.0', plugin_version:'0.15.0', data_dir:'~/LrMcp', project_url:'https://github.com/Denvolatos/lightroom-mcp-win'}}),
    update_state: ()=>Promise.resolve(JSON.parse(JSON.stringify(cur))),
    check_update_now: ()=>{ window.__CALLS__.push('check_update_now'); setTimeout(()=>{ cur = final; }, 800); cur = U.checking; return Promise.resolve(JSON.parse(JSON.stringify(cur))); },
    open_update_page: ()=>{ window.__CALLS__.push('open_update_page'); return Promise.resolve({ok:true}); },
  }};
})();
</script>"""
TAIL = """<script>
window.dispatchEvent(new Event('pywebviewready'));
const q = new URLSearchParams(location.search).get('s') || 'available';
const wait = ms => new Promise(r => setTimeout(r, ms));
(async()=>{
  await wait(400);
  if (q === 'available') { document.body.dataset.shot = 'topbar'; return; }
  await openSettings(); await wait(300);
  if (q !== 'checking') { document.getElementById('a_updcheck').click(); await wait(1800); }
  else { document.getElementById('a_updcheck').click(); await wait(200); }
  document.querySelector('#smask .body').scrollTop = 99999;
})();
</script>"""

SCENES = (("available", 1440, 420), ("latest", 1440, 900), ("unavailable", 1440, 900), ("checking", 1440, 900))


def main(out: Path) -> None:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    html = WEB.read_text(encoding="utf-8")
    html = html.replace("<script>", STUB + "\n<script>", 1)
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
        for name, w, h in SCENES:
            target = out / f"update_{name}.png"
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={w},{h}",
                            "--virtual-time-budget=6000", f"--screenshot={target}",
                            f"http://127.0.0.1:{httpd.server_address[1]}/?s={name}"], check=True, timeout=60, capture_output=True)
            print("截图", target)
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
