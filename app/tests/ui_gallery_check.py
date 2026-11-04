# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""软件内图库界面自查（无窗口、无 Lightroom、不调用模型，不属于 pytest）。
临时本机静态服务加载 index.html（注入假的 pywebview.api 与假数据），用无头 Edge 截图各状态。
缩略图用测试照片的缩略图 JPEG（--thumbs 指定目录，默认取脚本参数 2），照片名是测试照片的文件名，不含个人信息。数据只存在于本脚本里。
用法：python app/tests/ui_gallery_check.py <截图输出目录> <缩略图 JPEG 目录> [场景名 ...]      截图命名 gallery_<场景>.png
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
  const S = new URLSearchParams(location.search).get('s') || 'groups';
  const names = ['DSC08151.ARW','DSC08151.JPG','DSC08205.JPG','DSC08206.ARW','DSC08238.JPG','DSC08244.JPG','DSC08245.ARW'];
  const caps = ['2026-10-01 10:02','2026-10-01 10:03','2026-10-02 09:15','2026-10-02 09:40','2026-10-03 18:20','2026-10-03 18:21','2026-10-04 07:55'];
  const rating = [3, null, 1, 0, 5, null, 2], flag = ['pick','none','none','reject','pick','none','none'];
  const fmtOf = n => n.endsWith('ARW') ? 'ARW' : 'JPG';
  let photos = [];
  names.forEach((n,i)=>photos.push({id:String(101+i), name:n, group:'（未分类）', format:fmtOf(n), rating:rating[i], flag:flag[i], captured:caps[i], w:6000, h:4000, vc:false, added:true, missing:false}));
  names.forEach((n,i)=>photos.push({id:String(201+i), name:n, group:'test_batch', format:fmtOf(n), rating:rating[(i+3)%7], flag:flag[(i+2)%7], captured:caps[(i+2)%7], w:6000, h:4000, vc:false, added:true, missing:false}));
  if (S === 'notadded') { ['IMG_0001.JPG','IMG_0002.ARW','IMG_0003.JPG'].forEach((n,i)=>photos.push({id:'n-0000000000000'+i, name:n, group:'new_test', format:fmtOf(n), rating:null, flag:'none', captured:null, w:null, h:null, vc:false, added:false, missing:false})); }
  if (S === 'missing') { photos[2].missing = true; photos[9].missing = true; }
  if (S === 'truncated') { }
  const thumbsOf = ids => { const o = {}; ids.forEach(i => { o[i] = {url: '/t/' + (parseInt(i.replace(/\\D/g,'')) % 5) + '.jpg'}; }); return o; };
  let state = {ok:true, state:'ready', message:'', base:'D:\\\\ceshi\\\\app_library_test', base_exists:true, in_catalog:true, lr_connected:true, total:photos.length, limit:2000,
    truncated: S==='truncated', truncated_message:'仅显示前 2000 张。', not_added: photos.filter(p=>!p.added).length, missing: photos.filter(p=>p.missing).length,
    photos, thumbs:{}, failed:{}, selection:{ids:[], active:null}, add:null, max_select:50};
  if (S === 'empty') state = Object.assign(state, {photos:[], total:0, not_added:0, missing:0});
  if (S === 'empty_nofolder') state = Object.assign(state, {photos:[], total:0, not_added:0, missing:0, base_exists:false});
  if (S === 'offline') state = Object.assign(state, {state:'error', message:'Lightroom 未连接，无法显示照片信息', photos:[], total:0, lr_connected:false});
  if (S === 'loading_state') state = Object.assign(state, {state:'loading', photos:[], total:0});
  if (S === 'add_running') state.add = {state:'running', i:1, n:3, name:'IMG_0002.ARW', counts:{added:1, uncertain:0, failed:0, pending:0}, problems:[], cancelled:false};
  if (S === 'add_done') state.add = {state:'done', i:3, n:3, name:'', counts:{added:2, uncertain:1, failed:0, pending:0}, problems:[{name:'IMG_0003.JPG', lr:'uncertain', reason:'Lightroom 未在规定时间内响应，请在 Lightroom 中确认该照片是否已加入。'}], cancelled:false};
  if (S === 'add_running' || S === 'add_done') { ['IMG_0001.JPG','IMG_0002.ARW','IMG_0003.JPG'].forEach((n,i)=>photos.push({id:'n-0000000000000'+i, name:n, group:'new_test', format:fmtOf(n), rating:null, flag:'none', captured:null, w:null, h:null, vc:false, added:i>0, missing:false})); state.total = photos.length; state.not_added = 1; }
  const A = {ok:true};
  window.pywebview = {api: {
    send: ()=>Promise.resolve(A), stop(){}, reset(){}, answer(){}, undo(){}, restore_original(){},
    status: ()=>Promise.resolve({state:'connected', text:'Lightroom 已连接', hint:'', photo:{id:'101', name:'DSC08151.ARW'}}),
    preview_state: ()=>Promise.resolve({type:'preview', state:'none', message:'Lightroom 中未选中照片'}), set_preview_edge: ()=>Promise.resolve(A),
    selection_state: ()=>Promise.resolve({count:0, active_id:null, photos:[]}), import_state: ()=>Promise.resolve({stage:'idle'}),
    get_settings: ()=>Promise.resolve({settings:{schema:1, base_folder:'D:\\\\ceshi\\\\app_library_test', provider:'claude', confirm_default:true, preview_edge:1024, ai_use_notes:true}, providers:[], current_provider:'claude', edges:[768,1024,1536,2048], about:{}}),
    lib_presets: ()=>Promise.resolve({ok:true, presets:[], max:200}), lib_notes: ()=>Promise.resolve({ok:true, notes:[], tags:[], max:300, context:{used:0, eligible:0, truncated:false}}),
    lib_favs: ()=>Promise.resolve({ok:true, groups:{preset:[],lr_preset:[],note:[],photo:[]}, total:0, photo_fav:false}), lib_lr_presets: ()=>Promise.resolve({ok:true, groups:[]}),
    open_library: ()=>Promise.resolve(A),
    library_state: ()=>Promise.resolve(JSON.parse(JSON.stringify(state))),
    library_refresh: ()=>Promise.resolve(A),
    library_thumbnails: (ids, retry)=>{
      if (S === 'loading') return Promise.resolve({ok:true, thumbs:{}, pending:ids});
      if (S === 'mixed') { const o = thumbsOf(ids); ids.forEach((i,k)=>{ if (k%4===1) delete o[i]; if (k===3 && !retry) o[i] = {error:'读取缩略图超时'}; }); return Promise.resolve({ok:true, thumbs:o, pending:ids.filter((i,k)=>k%4===1)}); }
      if (S === 'fail') { const o = {}; ids.forEach((i,k)=>{ o[i] = (k%3===0 && !retry) ? {error:'读取缩略图超时'} : thumbsOf([i])[i]; }); return Promise.resolve({ok:true, thumbs:o, pending:[]}); }
      return Promise.resolve({ok:true, thumbs:thumbsOf(ids), pending:[]});
    },
    library_select: (ids, active)=> (S === 'select_partial' && ids.length > 1) ? Promise.resolve({ok:false, status:'partial', message:'Lightroom 未能选中其中 1 张照片。有照片没有被选中：它们可能不在 Lightroom 当前显示的文件夹或集合里。', selected:ids.slice(0, ids.length-1), active:ids[0], not_selected:[ids[ids.length-1]]})
        : Promise.resolve({ok:true, status:'selected', message:'', selected:ids, active:active, not_selected:[]}),
    library_clear_selection: ()=>Promise.resolve({ok:true, message:'已清除图库中的选择标记。Lightroom 里的选区不变，AI 挑片、导出仍按 Lightroom 当前选区进行。'}),
    library_add_missing: ()=>Promise.resolve(A), library_cancel_add: ()=>Promise.resolve(A), library_close_add: ()=>Promise.resolve(A)
  }};
})();
</script>"""

TAIL = """<script>
window.dispatchEvent(new Event('pywebviewready'));
const S = new URLSearchParams(location.search).get('s') || 'groups';
const wait = ms => new Promise(r => setTimeout(r, ms));
const cell = id => document.querySelector('.cell[data-id="' + id + '"]');
const clickCell = (id, o) => cell(id).dispatchEvent(new MouseEvent('click', Object.assign({bubbles: true}, o || {})));
(async()=>{
  await wait(1500);
  if (S === 'select_one') { clickCell('103'); await wait(1200); }
  if (S === 'select_ctrl') { clickCell('102'); await wait(1200); clickCell('104', {ctrlKey: true}); await wait(1200); clickCell('106', {ctrlKey: true}); await wait(1200); }
  if (S === 'select_range') { clickCell('202'); await wait(1200); clickCell('205', {shiftKey: true}); await wait(1200); }
  if (S === 'select_all') { clickCell('101'); await wait(1200); document.getElementById('gal_scroll').dispatchEvent(new KeyboardEvent('keydown', {key: 'a', ctrlKey: true, bubbles: true})); await wait(1200); }
  if (S === 'select_partial') { clickCell('101'); await wait(100); clickCell('203', {ctrlKey: true}); await wait(1200); }
  if (S === 'notadded') { clickCell('n-00000000000000'); await wait(1200); }
  if (S === 'search') { const q = document.getElementById('gal_q'); q.value = '0823'; q.oninput(); await wait(1200); }
  if (S === 'filter_rated') { const f = document.getElementById('gal_filter'); f.value = 'rated'; f.onchange(); await wait(1200); }
  if (S === 'filter_pick') { const f = document.getElementById('gal_filter'); f.value = 'pick'; f.onchange(); await wait(1200); }
  if (S === 'sort_time') { const f = document.getElementById('gal_sort'); f.value = 'time'; f.onchange(); await wait(1200); }
  if (S === 'collapsed') { document.querySelector('.ghead[data-g="test_batch"]').click(); await wait(1200); }
  if (S === 'meta_update') { window.onClaudeEvent({type:'library_meta', items:[{id:'102', rating:4, flag:'pick'}, {id:'104', rating:0, flag:'none'}]}); await wait(1200); }
  if (S === 'lr_select') { window.onClaudeEvent({type:'library_selection', ids:['101','103','205'], active:'103'}); await wait(1200); }
})();
</script>"""

SCENES = ["groups", "select_one", "select_ctrl", "select_range", "select_all", "select_partial", "lr_select", "loading", "mixed", "fail",
          "notadded", "missing", "empty", "empty_nofolder", "offline", "loading_state", "add_running", "add_done", "search", "filter_rated",
          "filter_pick", "sort_time", "collapsed", "meta_update", "truncated"]


def main(out: Path, thumbs: Path) -> None:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    jpgs = sorted(thumbs.glob("*.jpg"))
    assert jpgs, "缩略图目录里没有 JPEG"
    html = WEB.read_text(encoding="utf-8")
    html = html.replace("<script>", STUB + "\n<script>", 1)
    html = html.replace("</body>", TAIL + "</body>")
    page = html.encode("utf-8")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.startswith("/t/"):
                data = jpgs[int(self.path[3:].split(".")[0]) % len(jpgs)].read_bytes()
                ctype = "image/jpeg"
            else:
                data, ctype = page, "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        for name in (sys.argv[3:] or SCENES):
            target = out / f"gallery_{name}.png"
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1440,900",
                            "--virtual-time-budget=9000", f"--screenshot={target}",
                            f"http://127.0.0.1:{httpd.server_address[1]}/?s={name}"], check=True, timeout=60, capture_output=True)
            print("截图", target)
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
