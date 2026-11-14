# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""导入界面自查（无窗口、无 Lightroom、不调用模型，不属于 pytest）。
临时本机静态服务加载 index.html（注入假的 pywebview.api），用无头 Edge 截图各场景，并用 --dump-dom 读出断言结果（CHK）。
截图只含测试内容，路径用示例值。有断言失败时退出码为 1。
用法：python app/tests/ui_import_check.py <截图输出目录>
"""
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
from web_source import inject_stub, serve_static  # noqa: E402
WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"

STUB = r"""<script>
(function(){
  const q = new URLSearchParams(location.search).get('s') || 'confirm';
  const found = {n:4, raw:2, jpeg:2, other:0, total_size:63000000, size_text:'60.08 MB', truncated:false, skipped_links:0};
  const base = {ok:true, can_start:true, errors:{}, found, source:'F:\\DCIM\\100MSDCF', base:'D:\\ceshi\\app_library_test', base_exists:true,
    base_is_default:false, free:200000000000, free_text:'186.26 GB', needed_text:'60.08 MB', shortfall:0, lr_connected:true,
    date_summary:[{day:'2026-11-12', count:1},{day:'2026-11-13', count:1},{day:'2026-11-14', count:2}], date_more:0, duplicates:{count:1, bytes_text:'6.1 MB'}, to_copy:{count:3, bytes_text:'53.9 MB'}};
  const manyDays = Array.from({length:30}, (_, i)=>({day:'2026-10-'+String(i+1).padStart(2,'0'), count:i%7+1}));
  const prep = {
    confirm: base,
    dates_many: Object.assign({}, base, {found:Object.assign({}, found, {n:130, raw:70, jpeg:60}), date_summary:manyDays, date_more:12, duplicates:{count:0, bytes_text:'0 B'}, to_copy:{count:130, bytes_text:'1.9 GB'}}),
    nodates: (()=>{ const o = Object.assign({}, base); delete o.date_summary; delete o.date_more; delete o.duplicates; delete o.to_copy; return o; })(),
    alldup: Object.assign({}, base, {date_summary:[{day:'2026-11-14', count:4}], duplicates:{count:4, bytes_text:'60.0 MB'}, to_copy:{count:0, bytes_text:'0 B'}}),
    space: Object.assign({}, base, {ok:false, can_start:false, free:30000000, free_text:'28.6 MB', shortfall:96000000, errors:{space:'目标磁盘剩余空间不足，还差 91.6 MB。请清理磁盘或在设置中更换照片工作文件夹。'}}),
    overlap: Object.assign({}, base, {ok:false, can_start:false, errors:{base:'来源文件夹与照片工作文件夹不能相同或互相包含。请选择相机存储卡上的文件夹，并确认照片工作文件夹在其他位置。'}}),
    disc: Object.assign({}, base, {lr_connected:false, base_exists:false, base_is_default:true, base:'C:\\Users\\示例用户\\Pictures\\修图助手'}),
  }[q] || base;
  window.__CALLS__ = [];
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
    import_prepare: function(){ window.__CALLS__.push(['import_prepare'].concat(Array.from(arguments))); return Promise.resolve(prep); }, import_start: function(){ window.__CALLS__.push(['import_start'].concat(Array.from(arguments))); return Promise.resolve({ok:true}); }, import_cancel: ()=>Promise.resolve({ok:true}),
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
  if (['confirm','dates_many','nodates','alldup','space','overlap','disc'].includes(q)) {
    ev({type:'import_scan', state:'done', info:{}}); await wait(200);
    return;
  }
  if (q === 'progress') { IM.stage='copying'; ev({type:'import_progress', state:'running', i:2, n:4, name:'DSC08238.ARW', elapsed:7.4, counts:C({copied:2,lr_ok:2}), mode:'import'}); return; }
  if (q === 'ok') ev({type:'import_done', state:'done', i:4, n:4, name:'', elapsed:12.8, counts:C({copied:4,lr_ok:4}), skipped_dup:0, cancelled:false, problems:[], problems_more:0, pending_retry:0});
  if (q === 'problems') ev({type:'import_done', state:'done', i:4, n:4, name:'', elapsed:15.1, counts:C({copied:2,skipped:1,failed:1,lr_ok:2,lr_uncertain:1}), skipped_dup:1, cancelled:false, pending_retry:0, problems_more:0,
    problems:[{name:'DSC08240.ARW', copy:'failed', lr:'none', reason:'复制失败：目标磁盘空间不足。'},{name:'DSC08238.JPG', copy:'copied', lr:'uncertain', reason:'Lightroom 未在规定时间内响应，请在 Lightroom 中确认该照片是否已加入。'}]});
  if (q === 'pending') ev({type:'import_done', state:'done', i:4, n:4, name:'', elapsed:9.2, counts:C({copied:4,lr_pending:4}), cancelled:false, problems_more:0, pending_retry:4,
    problems:[1,2,3,4].map(i=>({name:'DSC0824'+i+'.ARW', copy:'copied', lr:'pending', reason:'Lightroom 未连接，尚未加入。'}))});
  if (q === 'cancelled') ev({type:'import_done', state:'done', i:2, n:4, name:'', elapsed:5.0, counts:C({copied:2,lr_ok:2}), cancelled:true, problems:[], problems_more:0, pending_retry:0});
  if (q === 'start') { ev({type:'import_scan', state:'done', info:{}}); await wait(200); document.getElementById('im_go').click(); await wait(300); }
})();
/* 断言：只在导入弹窗相关场景里检查 */
(async()=>{
  await wait(2500);
  const bad = [], body = document.getElementById('im_body') ? document.getElementById('im_body').innerText : '';
  const has = (t, why) => { if (body.indexOf(t) < 0) bad.push('缺少「' + t + '」' + (why || '')); };
  const hasnt = t => { if (body.indexOf(t) >= 0) bad.push('不该出现「' + t + '」'); };
  if (q !== 'library' && q !== 'empty') {
    ['分类', 'undefined', 'NaN', 'null', '换目录'].forEach(hasnt);
    if (document.getElementById('im_cat')) bad.push('还有分类输入框');
  }
  if (['confirm', 'dates_many', 'nodates', 'alldup', 'space', 'overlap', 'disc'].includes(q)) { has('年\\年-月-日'); has('照片库'); }
  if (q === 'confirm') { has('2026\\2026-11-14'); has('2 张'); has('重复，将跳过'); has('1 张（6.1 MB）'); has('需要复制'); has('3 张（53.9 MB）');
    if (document.querySelectorAll('.imdays tr').length !== 3) bad.push('日期行数不是 3'); }
  if (q === 'dates_many') { if (document.querySelectorAll('.imdays tr').length !== 30) bad.push('日期行数不是 30'); has('另有 12 个日期未列出'); has('1.9 GB'); }
  if (q === 'nodates') { if (document.querySelector('.imdays')) bad.push('后端没给日期汇总却显示了表格'); hasnt('重复，将跳过'); hasnt('需要复制'); }
  if (q === 'alldup') { has('4 张（60.0 MB）'); has('0 张（0 B）'); const go = document.getElementById('im_go'); if (!go || go.disabled) bad.push('开始导入按钮应可点'); }
  if (q === 'space' || q === 'overlap') { const go = document.getElementById('im_go'); if (!go || !go.disabled) bad.push('开始导入按钮应置灰'); }
  if (q === 'ok') { has('已复制 4　重复跳过 0　失败 0'); has('Lightroom：已加入 4'); has('全部完成'); }
  if (q === 'problems') { has('已复制 2　重复跳过 1　失败 1'); has('Lightroom：已加入 2　需确认 1'); }
  if (q === 'pending') { has('Lightroom：已加入 0　尚未加入 4'); if ((document.getElementById('im_foot').innerText || '').indexOf('重新尝试加入 Lightroom') < 0) bad.push('缺少重试按钮'); }
  if (q === 'progress') { has('已复制 2　重复跳过 0　失败 0'); has('Lightroom：已加入 2'); }
  if (q === 'start') {
    const c = (window.__CALLS__ || []).filter(x => x[0] === 'import_start');
    if (c.length !== 1 || c[0].length !== 2 || c[0][1] !== false) bad.push('import_start 参数应为 [false]，实际 ' + JSON.stringify(c));
    const pr = (window.__CALLS__ || []).filter(x => x[0] === 'import_prepare');
    if (!pr.length || pr.some(x => x.length !== 1)) bad.push('import_prepare 不应带参数，实际 ' + JSON.stringify(pr));
  }
  const W = document.documentElement.clientWidth, H = document.documentElement.clientHeight;
  if (document.documentElement.scrollWidth > W + 1) bad.push('页面横向溢出');
  const dlg = document.querySelector('.mask.show .dialog'); if (dlg) { const r = dlg.getBoundingClientRect(); if (r.right > W + 1 || r.left < -1 || r.bottom > H + 1 || r.top < -1) bad.push('对话框超出窗口'); }
  const pre = document.createElement('pre'); pre.id = 'chk'; pre.style.cssText = 'position:fixed;left:-9999px;top:0';
  pre.textContent = 'CHK[' + q + ']:' + (bad.length ? bad.join(' | ') : 'OK'); document.body.appendChild(pre);
})();
</script>"""


def main(out: Path) -> None:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    html = WEB.read_text(encoding="utf-8")
    html = inject_stub(html, STUB)
    html = html.replace("</body>", TAIL + "</body>")
    page = html.encode("utf-8")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if serve_static(self):
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    failed = False
    try:
        for name in ("confirm", "dates_many", "nodates", "alldup", "space", "overlap", "disc", "scanning", "progress", "ok", "problems", "pending",
                     "cancelled", "readonly", "library", "empty", "start"):
            target = out / f"import_{name}.png"
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1440,900",
                            "--virtual-time-budget=5000", f"--screenshot={target}",
                            f"http://127.0.0.1:{httpd.server_address[1]}/?s={name}"], check=True, timeout=60, capture_output=True)
            print("截图", target)
            dom = subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--window-size=1464,924", "--virtual-time-budget=5000", "--dump-dom",
                                  f"http://127.0.0.1:{httpd.server_address[1]}/?s={name}"], check=True, timeout=60, capture_output=True).stdout.decode("utf-8", "replace")
            m = re.search(r'<pre id="chk"[^>]*>(CHK[^<]*)', dom)
            res = m.group(1) if m else "没有检查结果"
            failed |= not res.endswith(":OK")
            print("  ", res)
    finally:
        httpd.shutdown()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
