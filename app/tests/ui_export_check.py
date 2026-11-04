# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""导出对话框界面自查（无窗口、无 Lightroom、不调用模型，不属于 pytest）。
临时本机静态服务加载 index.html（注入假的 pywebview.api），用无头 Edge 截图各状态。截图只含示例内容。
用法：python app/tests/ui_export_check.py <截图输出目录>
"""
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"

STUB = r"""<script>
(function(){
  const q = new URLSearchParams(location.search).get('s') || 'default';
  const photo = {name:'DSC08206.ARW', camera:'Sony ILCE-7M3', format:'RAW', size:'6000 × 4000', iso:100};
  const base = {stage:'idle', options:{format:'jpeg', size:2048, quality:92, bit_depth:16, metadata:'minimal'}, connected:true, photo,
    folder:'D:\\示例\\导出', folder_message:'', can_export:true, reason:''};
  const states = {
    default: base,
    tiff: Object.assign({}, base, {options:{format:'tiff', size:0, quality:92, bit_depth:16, metadata:'minimal'}}),
    tiff8: Object.assign({}, base, {options:{format:'tiff', size:1024, quality:92, bit_depth:8, metadata:'all'}}),
    custom: Object.assign({}, base, {options:{format:'jpeg', size:3000, quality:80, bit_depth:16, metadata:'minimal'}}),
    badcustom: Object.assign({}, base, {options:{format:'jpeg', size:3000, quality:80, bit_depth:16, metadata:'minimal'}}),
    nophoto: Object.assign({}, base, {photo:null, can_export:false, reason:'Lightroom 中没有选中照片。请先选择一张照片。'}),
    disconnected: Object.assign({}, base, {photo:null, connected:false, can_export:false, reason:'Lightroom 未连接。请确认 Lightroom 已打开且插件已启用。'}),
    nofolder: Object.assign({}, base, {folder:'', folder_message:'请选择保存位置。', can_export:false}),
    stale: Object.assign({}, base, {folder:'', folder_message:'之前选择的文件夹已不可用（所选文件夹不存在，请重新选择），请重新选择。', can_export:false}),
  };
  window.__CALLS__ = [];
  window.pywebview = {api: {
    send: ()=>Promise.resolve({ok:true}), stop(){}, reset(){}, answer(){}, undo(){}, restore_original(){},
    status: ()=>Promise.resolve({state:'connected', text:'Lightroom 已连接', hint:'', photo:{id:'P', name:'DSC08206.ARW'}}),
    preview_state: ()=>Promise.resolve({type:'preview', state:'none', message:'Lightroom 中未选中照片'}), set_preview_edge: ()=>Promise.resolve({ok:true}),
    get_settings: ()=>Promise.resolve({settings:{schema:1, base_folder:'D:\\示例', provider:'claude', confirm_default:true, preview_edge:1024}, providers:[], current_provider:'claude', edges:[1024], about:{}}),
    import_state: ()=>Promise.resolve({stage:'idle'}), library_list: ()=>Promise.resolve({exists:false, total:0, groups:[], shown:0, more:0, base:'D:\\示例'}),
    export_state: ()=>Promise.resolve({stage:'idle'}),
    export_dialog_state: ()=>Promise.resolve(states[q] || base),
    choose_export_folder: ()=>Promise.resolve({ok:true, folder:'D:\\示例\\导出'}),
    export_current_photo: (o)=>{ window.__CALLS__.push(o); return Promise.resolve({ok:true}); },
    export_close: ()=>Promise.resolve({ok:true}), reveal_last_export: ()=>Promise.resolve({ok:true})
  }};
})();
</script>"""
TAIL = r"""<script>
window.dispatchEvent(new Event('pywebviewready'));
const q = new URLSearchParams(location.search).get('s') || 'default';
const wait = ms => new Promise(r => setTimeout(r, ms));
(async()=>{
  await wait(150);
  await openExport(); await wait(100);
  const ev = window.onClaudeEvent;
  if (q === 'badcustom') { const i = document.getElementById('ex_custom'); i.value = '100'; i.dispatchEvent(new Event('input')); }
  if (q === 'running') { document.getElementById('ex_go').click(); await wait(100); }
  if (q === 'ok') ev({type:'export_done', status:'exported', format:'jpeg', format_label:'JPEG', folder:'D:\\示例\\导出', photo_name:'DSC08206.ARW',
    file:'DSC08206_LrMCP_2048px.jpg', bytes:1250000, size_text:'1.2 MB', width:2048, height:1365, dimensions:'2048 × 1365', quality:92, bit_depth:null, elapsed:3.4, message:''});
  if (q === 'oktiff') ev({type:'export_done', status:'exported', format:'tiff', format_label:'TIFF', folder:'D:\\示例\\导出', photo_name:'DSC08206.ARW',
    file:'DSC08206_LrMCP_1024px.tif', bytes:3570000, size_text:'3.4 MB', width:1024, height:683, dimensions:'1024 × 683', quality:null, bit_depth:16, elapsed:5.1, message:''});
  if (q === 'failed') ev({type:'export_done', status:'failed', format:'jpeg', format_label:'JPEG', folder:'D:\\示例\\导出', message:'Lightroom 没有生成导出文件（可能被导出设置、磁盘空间或权限拦截）。'});
  if (q === 'uncertain') ev({type:'export_done', status:'uncertain', format:'tiff', format_label:'TIFF', folder:'D:\\示例\\导出',
    message:'Lightroom 没有在时限内回复，不确定是否已导出成功。请到所选文件夹确认是否有新文件，确认前请勿重复导出。'});
})();
</script>"""


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
        for name in ("default", "tiff", "tiff8", "custom", "badcustom", "running", "ok", "oktiff", "failed", "uncertain",
                     "nophoto", "disconnected", "nofolder", "stale"):
            target = out / f"export_{name}.png"
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1440,900",
                            "--virtual-time-budget=5000", f"--screenshot={target}",
                            f"http://127.0.0.1:{httpd.server_address[1]}/?s={name}"], check=True, timeout=60, capture_output=True)
            print("截图", target)
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
