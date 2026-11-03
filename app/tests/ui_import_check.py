"""导入界面自查（无窗口、无 Lightroom、不调用模型，不属于 pytest）。
临时本机静态服务加载 index.html（注入假的 pywebview.api），用无头 Edge 截图各场景。截图只含测试内容，路径用示例值。
用法：python app/tests/ui_import_check.py <截图输出目录>
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
  const q = new URLSearchParams(location.search).get('s') || 'confirm';
  const found = {n:4, raw:2, jpeg:2, other:0, total_size:63000000, size_text:'60.08 MB', truncated:false, skipped_links:0};
  const base = {ok:true, can_start:true, errors:{}, found, source:'F:\\DCIM\\100MSDCF', base:'D:\\ceshi\\app_library_test', base_exists:true,
    base_is_default:false, category:'', target:'D:\\ceshi\\app_library_test', free:200000000000, free_text:'186.26 GB', needed_text:'60.08 MB', shortfall:0, lr_connected:true};
  const prep = {
    confirm: base,
    category: Object.assign({}, base, {ok:false, can_start:false, errors:{category:'分类文件夹名不能包含 \\ / : * ? " < > | 等字符，也不能包含路径。'}, target:'D:\\ceshi\\app_library_test'}),
    space: Object.assign({}, base, {ok:false, can_start:false, free:30000000, free_text:'28.6 MB', shortfall:96000000, errors:{space:'目标磁盘剩余空间不足，还差 91.6 MB。请清理磁盘或在设置中更换软件文件夹。'}}),
    overlap: Object.assign({}, base, {ok:false, can_start:false, errors:{base:'来源文件夹与软件文件夹不能相同或互相包含。请选择相机存储卡上的文件夹，并确认软件文件夹在其他位置。'}}),
    disc: Object.assign({}, base, {lr_connected:false, base_exists:false, base_is_default:true, base:'C:\\Users\\示例用户\\Pictures\\修图助手', target:'C:\\Users\\示例用户\\Pictures\\修图助手'}),
  }[q] || base;
  const tree = {exists:true, total:5, shown:5, more:0, base:'D:\\ceshi\\app_library_test', groups:[
    {name:'（未分类）', count:1, files:[{name:'DSC08151.JPG', size:6384615}]},
    {name:'雪山', count:4, files:[{name:'DSC08151.ARW', size:17620992},{name:'DSC08151_2.JPG', size:6384615},{name:'DSC08238.ARW', size:18710528},{name:'DSC08238.JPG', size:8563581}]}]};
  window.__CALLS__ = [];
  window.pywebview = {api: {
    send: ()=>Promise.resolve({ok:true}), stop(){}, reset(){}, answer(){}, undo(){}, restore_original(){},
    status: ()=>Promise.resolve({state:'connected', text:'Lightroom 已连接', hint:'', photo:{id:'P', name:'DSC08238.ARW'}}),
    preview_state: ()=>Promise.resolve({type:'preview', state:'none', message:'Lightroom 中未选中照片'}), set_preview_edge: ()=>Promise.resolve({ok:true}),
    get_settings: ()=>Promise.resolve({settings:{schema:1, base_folder:'D:\\ceshi\\app_library_test', provider:'claude', confirm_default:true, preview_edge:1024}, providers:[], current_provider:'claude', edges:[1024], about:{}}),
    choose_source_folder: ()=> q==='readonly' ? Promise.resolve({ok:false, message:'只读模式已开启，无法导入照片。请先关闭只读模式（删除只读开关文件）后再试。'}) : Promise.resolve({ok:true, path:'F:\\DCIM\\100MSDCF'}),
    import_prepare: ()=>Promise.resolve(prep), import_start: ()=>Promise.resolve({ok:true}), import_cancel: ()=>Promise.resolve({ok:true}),
    import_close: ()=>Promise.resolve({ok:true}), import_retry_lr: ()=>Promise.resolve({ok:true}), import_state: ()=>Promise.resolve({stage:'idle'}),
    library_list: ()=>Promise.resolve(q==='empty' ? {exists:false, total:0, groups:[], shown:0, more:0, base:'D:\\ceshi\\app_library_test'} : tree),
    open_library: ()=>Promise.resolve({ok:true})
  }};
})();
</script>"""
TAIL = r"""<script>
window.dispatchEvent(new Event('pywebviewready'));
const q = new URLSearchParams(location.search).get('s') || 'confirm';
const wait = ms => new Promise(r => setTimeout(r, ms));
const C = (o)=>Object.assign({copied:0,skipped:0,failed:0,lr_ok:0,lr_uncertain:0,lr_pending:0,lr_failed:0}, o);
(async()=>{
  await wait(150);
  if (q === 'library' || q === 'empty') { if (q==='library') { document.querySelector('.libfile[data-n="DSC08238.ARW"]').click(); } return; }
  await startImport(); await wait(100);
  const ev = window.onClaudeEvent;
  if (q === 'scanning') { ev({type:'import_scan', state:'scanning', found:1342}); return; }
  if (q === 'readonly') return;
  if (['confirm','category','space','overlap','disc'].includes(q)) {
    ev({type:'import_scan', state:'done', info:{}}); await wait(200);
    if (q === 'category') { const i = document.getElementById('im_cat'); i.value = 'a/b'; i.dispatchEvent(new Event('input')); await wait(700); }
    return;
  }
  if (q === 'progress') { IM.stage='copying'; ev({type:'import_progress', state:'running', i:2, n:4, name:'DSC08238.ARW', elapsed:7.4, counts:C({copied:2,lr_ok:2}), mode:'import'}); return; }
  if (q === 'ok') ev({type:'import_done', state:'done', i:4, n:4, name:'', elapsed:12.8, counts:C({copied:4,lr_ok:4}), cancelled:false, problems:[], problems_more:0, pending_retry:0});
  if (q === 'problems') ev({type:'import_done', state:'done', i:4, n:4, name:'', elapsed:15.1, counts:C({copied:2,skipped:1,failed:1,lr_ok:2,lr_uncertain:1}), cancelled:false, pending_retry:0, problems_more:0,
    problems:[{name:'DSC08240.ARW', copy:'failed', lr:'none', reason:'复制失败：目标磁盘空间不足。'},{name:'DSC08238.JPG', copy:'copied', lr:'uncertain', reason:'Lightroom 未在规定时间内响应，请在 Lightroom 中确认该照片是否已加入。'}]});
  if (q === 'pending') ev({type:'import_done', state:'done', i:4, n:4, name:'', elapsed:9.2, counts:C({copied:4,lr_pending:4}), cancelled:false, problems_more:0, pending_retry:4,
    problems:[1,2,3,4].map(i=>({name:'DSC0824'+i+'.ARW', copy:'copied', lr:'pending', reason:'Lightroom 未连接，尚未加入。'}))});
  if (q === 'cancelled') ev({type:'import_done', state:'done', i:2, n:4, name:'', elapsed:5.0, counts:C({copied:2,lr_ok:2}), cancelled:true, problems:[], problems_more:0, pending_retry:0});
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
        for name in ("confirm", "category", "space", "overlap", "disc", "scanning", "progress", "ok", "problems", "pending",
                     "cancelled", "readonly", "library", "empty"):
            target = out / f"import_{name}.png"
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1440,900",
                            "--virtual-time-budget=5000", f"--screenshot={target}",
                            f"http://127.0.0.1:{httpd.server_address[1]}/?s={name}"], check=True, timeout=60, capture_output=True)
            print("截图", target)
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
