# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""图库排序自查（无窗口、无 Lightroom、不调用模型，不属于 pytest）。
临时本机静态服务加载 index.html（注入假的 pywebview.api，只含示例数据），用无头 Edge 截图，并用 --dump-dom 读出断言结果（CHK）：
  sorts    10 种排序 x 升/降序 的顺序逐项断言（数据里故意放了同值、缺值和大小写不同的名字）；每次改选项或点方向按钮都要调用 gallery_set_sort；
           下拉与方向按钮的无障碍名称；加载时不调用 gallery_set_sort
  groups   日期分组顺序随升/降序翻转，“（未分类）”始终在最前
  restore  后端 state 里带的 sort/order 要被采用（选项和按钮都对应）
  savefail gallery_set_sort 失败时不报错、排序照常
同一批场景在 1440 宽和 800 宽各跑一遍；800 宽额外检查页面和排序控件不横向溢出、按钮文字不换行。
期望顺序在本脚本里用 Python 手写（不是从页面代码抄来的），规则见 app/DEV_NOTES.md“1.2.0 照片库（界面）”。
用法：python app/tests/ui_sort_check.py <截图输出目录>      截图命名 sort_<场景>_<宽度>.png；有断言失败时退出码为 1
"""
import json
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
from web_source import inject_stub, serve_static  # noqa: E402
WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"

# id, 名称, 格式, 拍摄时间, 导入时间, 大小, 修改时间, 颜色标签, 星级, 旗标, 是否修过
DATA = [
    ("p1", "b.JPG", "JPG", "2026-11-03 10:00", "2026-11-14T09:00:00", 300, 50, "red", 3, "pick", True),
    ("p2", "A.ARW", "ARW", "2026-11-01 10:00", "2026-11-14T11:00:00", 100, None, None, None, "none", False),
    ("p3", "c.ARW", "ARW", None, None, None, 70, "blue", 1, "reject", None),
    ("p4", "D.jpg", "JPG", "2026-11-02 08:00", "2026-11-14T10:00:00", 200, 60, "green", 3, "none", True),
    ("p5", "e.PNG", "PNG", "2026-11-02 08:00", "2026-11-14T10:00:00", 200, None, "red", 0, "pick", False),
]
# 期望顺序（手工推出，规则：缺值始终排最后；同值按文件名升序、不分大小写）
EXPECT = {
    ("captured", "desc"): "p1 p4 p5 p2 p3", ("captured", "asc"): "p2 p4 p5 p1 p3",
    ("imported", "desc"): "p2 p4 p5 p1 p3", ("imported", "asc"): "p1 p4 p5 p2 p3",
    ("name", "asc"): "p2 p1 p3 p4 p5", ("name", "desc"): "p5 p4 p3 p1 p2",
    ("size", "desc"): "p1 p4 p5 p2 p3", ("size", "asc"): "p2 p4 p5 p1 p3",
    ("rating", "desc"): "p1 p4 p3 p2 p5", ("rating", "asc"): "p2 p5 p3 p1 p4",
    ("flag", "desc"): "p1 p5 p2 p4 p3", ("flag", "asc"): "p3 p2 p4 p1 p5",
    ("label", "asc"): "p3 p4 p1 p5 p2", ("label", "desc"): "p1 p5 p4 p3 p2",
    ("modified", "desc"): "p3 p4 p1 p2 p5", ("modified", "asc"): "p1 p4 p3 p2 p5",
    ("edited", "desc"): "p1 p4 p2 p3 p5", ("edited", "asc"): "p2 p3 p5 p1 p4",
    ("type", "asc"): "p2 p3 p1 p4 p5", ("type", "desc"): "p5 p1 p4 p2 p3",
}
OPTIONS = [("captured", "拍摄时间"), ("imported", "导入时间"), ("name", "名称"), ("size", "大小"), ("rating", "星级"), ("flag", "旗标"),
           ("label", "颜色标签"), ("modified", "最后修改"), ("edited", "是否修过"), ("type", "类型")]
GROUPS = ["（未分类）", "2026/2026-11-12", "2026/2026-11-14", "2026/2026-11-13"]

STUB = r"""<script>
(function(){
  const S = new URLSearchParams(location.search).get('s') || 'sorts';
  const DATA = __DATA__;
  const GROUPS = __GROUPS__;
  const mk = (r, group) => ({id:r[0], name:r[1], group, format:r[2], rating:r[8], flag:r[9], captured:r[3], w:6000, h:4000, vc:false, added:true, missing:false,
    size:r[5], mtime:r[6], label:r[7], edited:r[10], added_at:r[4]});
  let photos = [];
  if (S === 'groups') GROUPS.forEach((g, gi) => DATA.slice(0, 2).forEach((r, i) => photos.push(mk([r[0] + 'g' + gi].concat(r.slice(1)), g))));
  else DATA.forEach(r => photos.push(mk(r, '2026/2026-11-14')));
  const state = {ok:true, state:'ready', message:'', base:'D:\\示例\\照片库', base_exists:true, in_catalog:true, lr_connected:true, total:photos.length, limit:2000,
    truncated:false, not_added:0, missing:0, photos, thumbs:{}, failed:{}, selection:{ids:[], active:null}, add:null, max_select:50,
    sort: S === 'restore' ? 'size' : 'captured', order: S === 'restore' ? 'asc' : 'desc'};
  window.__SORTS__ = []; window.__ERRS__ = [];
  window.addEventListener('error', e => window.__ERRS__.push(String(e.message)));
  window.addEventListener('unhandledrejection', e => window.__ERRS__.push('未处理的 Promise 错误：' + String(e.reason)));
  const A = {ok:true};
  window.pywebview = {api: {
    send: ()=>Promise.resolve(A), stop(){}, reset(){}, answer(){}, undo(){}, restore_original(){},
    status: ()=>Promise.resolve({state:'connected', text:'Lightroom 已连接', hint:'', photo:{id:'p1', name:'b.JPG'}}),
    preview_state: ()=>Promise.resolve({type:'preview', state:'none', message:'Lightroom 中未选中照片'}), set_preview_edge: ()=>Promise.resolve(A),
    selection_state: ()=>Promise.resolve({count:0, active_id:null, photos:[]}), import_state: ()=>Promise.resolve({stage:'idle'}),
    get_settings: ()=>Promise.resolve({settings:{schema:1, base_folder:'D:\\示例\\照片库', provider:'claude', confirm_default:true, preview_edge:1024, ai_use_notes:true}, providers:[], current_provider:'claude', edges:[768,1024,1536,2048], about:{}}),
    lib_presets: ()=>Promise.resolve({ok:true, presets:[], max:200}), lib_notes: ()=>Promise.resolve({ok:true, notes:[], tags:[], max:300, context:{used:0, eligible:0, truncated:false}}),
    lib_favs: ()=>Promise.resolve({ok:true, groups:{preset:[],lr_preset:[],note:[],photo:[]}, total:0, photo_fav:false}), lib_lr_presets: ()=>Promise.resolve({ok:true, groups:[]}),
    open_library: ()=>Promise.resolve(A), autolaunch_state: ()=>Promise.resolve({state:'idle', message:''}),
    wizard_state: ()=>Promise.resolve({items:[], ready:true, checking:false, auto_open:false, wizard_done:true, mark_done:false, message:''}),
    library_state: ()=>Promise.resolve(JSON.parse(JSON.stringify(state))), library_refresh: ()=>Promise.resolve(A),
    library_thumbnails: ()=>Promise.resolve({ok:true, thumbs:{}, pending:[]}),
    library_select: (ids, active)=>Promise.resolve({ok:true, status:'selected', message:'', selected:ids, active:active, not_selected:[]}),
    library_clear_selection: ()=>Promise.resolve({ok:true, message:''}),
    gallery_set_sort: (k, o)=>{ window.__SORTS__.push([k, o]); return S === 'savefail' ? Promise.reject(new Error('保存失败（假的）')) : Promise.resolve({ok:true, sort:k, order:o}); }
  }};
  const P = window.pywebview.api;      /* 没写到的接口一律返回空结果，避免启动流程半路中断 */
  window.pywebview.api = new Proxy(P, {get: (t, k) => (k in t) ? t[k] : (() => Promise.resolve({}))});
})();
</script>"""

TAIL = r"""<script>
window.dispatchEvent(new Event('pywebviewready'));
const S = new URLSearchParams(location.search).get('s') || 'sorts';
const wait = ms => new Promise(r => setTimeout(r, ms));
const EXPECT = __EXPECT__, OPTIONS = __OPTIONS__;
const selE = () => document.getElementById('gal_sort'), btnE = () => document.getElementById('gal_dir');
const ordNow = () => Array.from(document.querySelectorAll('#gal_scroll .cell')).map(c => c.dataset.id).join(' ');
const headsNow = () => Array.from(document.querySelectorAll('#gal_scroll .ghead .gn')).map(e => e.textContent).join(' | ');
const dirNow = () => { const a = btnE().getAttribute('aria-label') || ''; return a.indexOf('排序方向：升序') === 0 ? 'asc' : a.indexOf('排序方向：降序') === 0 ? 'desc' : '?'; };
async function setSort(key, dir) {
  let changed = false;
  if (selE().value !== key) { selE().value = key; selE().dispatchEvent(new Event('change')); changed = true; }
  if (dirNow() !== dir) { changed = true; btnE().click(); }
  await wait(600);                       // 保存是防抖的：等它发出去
  return changed;
}
(async()=>{
  const bad = [];
  await wait(1500);
  const W = document.documentElement.clientWidth;
  /* 无障碍名称、选项 */
  const o = Array.from(selE().options).map(x => x.value + ':' + x.textContent).join(',');
  if (o !== OPTIONS.map(x => x[0] + ':' + x[1]).join(',')) bad.push('排序选项不对：' + o);
  if (!(selE().getAttribute('aria-label') || '').trim() || !(selE().title || '').trim()) bad.push('排序下拉缺少 aria-label/title');
  if (!(btnE().getAttribute('aria-label') || '').startsWith('排序方向：') || !(btnE().title || '').trim() || !btnE().textContent.trim()) bad.push('方向按钮缺少 aria-label/title/文字');
  if (btnE().tagName !== 'BUTTON' || btnE().type !== 'button') bad.push('方向控件应是 type=button 的 button');
  if (document.getElementById('gal_change') || document.body.innerText.indexOf('换目录') >= 0) bad.push('还有“换目录”');
  if (window.__SORTS__.length) bad.push('加载时就调用了 gallery_set_sort：' + JSON.stringify(window.__SORTS__));
  if (S === 'sorts' || S === 'savefail') {
    if (selE().value !== 'captured' || dirNow() !== 'desc') bad.push('默认应是 拍摄时间+降序，实际 ' + selE().value + '/' + dirNow());
    if (ordNow() !== EXPECT['captured,desc']) bad.push('默认顺序不对：' + ordNow());
    const before = btnE().getAttribute('aria-label'), t0 = btnE().title;
    btnE().click(); await wait(600);
    if (btnE().getAttribute('aria-label') === before || btnE().title === t0) bad.push('点切换后按钮名称没变');
    if (dirNow() !== 'asc') bad.push('点一次后应是升序');
    const last = window.__SORTS__[window.__SORTS__.length - 1];
    if (!last || last[0] !== 'captured' || last[1] !== 'asc') bad.push('点方向按钮没有正确调用 gallery_set_sort：' + JSON.stringify(window.__SORTS__));
    if (S === 'sorts') {
      for (const [k] of OPTIONS) for (const d of ['asc', 'desc']) {
        window.__SORTS__.length = 0;
        const changed = await setSort(k, d);
        const got = ordNow(), want = EXPECT[k + ',' + d];
        if (got !== want) bad.push(k + '/' + d + ' 顺序 ' + got + ' 应为 ' + want);
        const l = window.__SORTS__[window.__SORTS__.length - 1];
        if (changed && (!l || l[0] !== k || l[1] !== d)) bad.push(k + '/' + d + ' 没有保存：' + JSON.stringify(window.__SORTS__));
        if (!changed && l) bad.push(k + '/' + d + ' 没改动却保存了');
      }
      const nCells = document.querySelectorAll('#gal_scroll .cell').length; if (nCells !== 5) bad.push('格子数不是 5');
    } else {
      await setSort('size', 'desc');
      if (ordNow() !== EXPECT['size,desc']) bad.push('保存失败后排序应照常，实际 ' + ordNow());
    }
  }
  if (S === 'groups') {
    const U = '（未分类）';
    const want = d => d === 'desc' ? [U, '2026/2026-11-14', '2026/2026-11-13', '2026/2026-11-12'] : [U, '2026/2026-11-12', '2026/2026-11-13', '2026/2026-11-14'];
    for (const [k, d] of [['captured', 'desc'], ['captured', 'asc'], ['name', 'asc'], ['name', 'desc'], ['size', 'desc'], ['size', 'asc']]) {
      await setSort(k, d);
      if (headsNow() !== want(d).join(' | ')) bad.push(k + '/' + d + ' 分组顺序 ' + headsNow());
    }
    document.querySelector('.ghead[data-g="2026/2026-11-13"]').click(); await wait(200);   // 折叠后顺序不变
    if (headsNow() !== want('asc').join(' | ')) bad.push('折叠后分组顺序变了：' + headsNow());
  }
  if (S === 'restore') {
    if (selE().value !== 'size' || dirNow() !== 'asc') bad.push('没有采用后端保存的排序：' + selE().value + '/' + dirNow());
    if (ordNow() !== EXPECT['size,asc']) bad.push('恢复后的顺序不对：' + ordNow());
  }
  /* 溢出（窄屏重点） */
  if (document.documentElement.scrollWidth > W + 1) bad.push('页面横向溢出 ' + document.documentElement.scrollWidth + '>' + W);
  const tools = document.querySelector('.galtools'), gal = document.getElementById('gal');
  const gr = gal.getBoundingClientRect();
  document.querySelectorAll('.galhead button, .galtools input, .galtools select, .galtools button').forEach(e => { const r = e.getBoundingClientRect();
    if (!r.width) bad.push('控件不可见 ' + (e.id || e.tagName));
    if (r.right > gr.right + 1 || r.left < gr.left - 1) bad.push('控件超出图库面板 ' + (e.id || e.tagName)); });
  if (tools.scrollWidth > tools.clientWidth + 1) bad.push('排序工具条内部溢出');
  const bb = btnE(), cs = getComputedStyle(bb), lineH = bb.getBoundingClientRect().height - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
  if (lineH > (parseFloat(cs.lineHeight) || 18) * 1.6) bad.push('方向按钮文字换行');
  if (window.__ERRS__.length) bad.push('脚本错误：' + window.__ERRS__.join(' / '));
  const pre = document.createElement('pre'); pre.id = 'chk'; pre.style.cssText = 'position:fixed;left:-9999px;top:0';
  pre.textContent = 'CHK[' + W + ' ' + S + ']:' + (bad.length ? bad.join(' | ') : 'OK'); document.body.appendChild(pre);
})();
</script>"""

SCENES = ("sorts", "groups", "restore", "savefail")
SIZES = ((1440, 900), (800, 700))


def main(out: Path) -> None:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    stub = STUB.replace("__DATA__", json.dumps(DATA, ensure_ascii=False)).replace("__GROUPS__", json.dumps(GROUPS, ensure_ascii=False))
    tail = (TAIL.replace("__EXPECT__", json.dumps({f"{k},{d}": v for (k, d), v in EXPECT.items()}, ensure_ascii=False))
            .replace("__OPTIONS__", json.dumps(OPTIONS, ensure_ascii=False)))
    # groups 场景的期望里没用 EXPECT；restore 用 size,asc
    page = inject_stub(WEB.read_text(encoding="utf-8"), stub).replace("</body>", tail + "</body>").encode("utf-8")

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
    base = f"http://127.0.0.1:{httpd.server_address[1]}/"
    failed = False
    try:
        for scene in SCENES:
            for w, h in SIZES:
                common = [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--virtual-time-budget=40000"]
                url = f"{base}?s={scene}"
                target = out / f"sort_{scene}_{w}.png"
                subprocess.run(common + [f"--window-size={w},{h}", f"--screenshot={target}", url], check=True, timeout=120, capture_output=True)
                # --dump-dom 的窗口比截图的小一圈（窗口边框），多给 24 像素让两者页面尺寸一致
                dom = subprocess.run(common + [f"--window-size={w + 24},{h + 24}", "--dump-dom", url], check=True, timeout=120,
                                     capture_output=True).stdout.decode("utf-8", "replace")
                m = re.search(r'<pre id="chk"[^>]*>(CHK[^<]*)', dom)
                res = m.group(1) if m else "没有检查结果"
                failed |= not res.endswith(":OK")
                print(target.name, res)
    finally:
        httpd.shutdown()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
