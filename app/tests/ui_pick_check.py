# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""AI 挑片界面自查（无窗口、无 Lightroom、不调用模型，不属于 pytest）。
临时本机静态服务加载 index.html（注入假的 pywebview.api），用无头 Edge 截图各状态。
缩略图用测试照片（DSC08151.ARW、DSC08205.JPG、DSC08206.ARW 的 256 像素预览），不含个人信息。
用法：python app/tests/ui_pick_check.py <截图输出目录> <缩略图目录> <真机挑片结果 json>
"""
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"

STUB = r"""<script>
(function(){
  const q = new URLSearchParams(location.search).get('s') || 'form';
  const REAL = __REAL__;
  const IDS = {'DSC08151.ARW':'1E85641C-2D3B-42CA-82B0-C6B4597A2120', 'DSC08205.JPG':'D567B727-F81B-441A-919B-7F62661F1477', 'DSC08206.ARW':'D227E9E0-107F-4D26-8F27-D14ADE51D4FC'};
  const NAMES = Object.keys(IDS);
  const T = {}; NAMES.forEach(n => T[IDS[n]] = '/t/' + n + '.jpg');
  const photos3 = NAMES.map(n => ({id: IDS[n], name: n, rating: 0, flag: 'none'}));
  const many = []; for (let i = 0; i < 28; i++) many.push({id: 'X' + i, name: 'DSC0' + (8300 + i) + '.ARW'});
  const sel = {count: 3, active_id: photos3[0].id, photos: photos3.map(p => ({id: p.id, name: p.name}))};
  const SELS = {list: {count: 28, active_id: 'X0', photos: many.slice(0, 28)}, many: {count: 11, active_id: 'X0', photos: many.slice(0, 11)},
                none: {count: 0, active_id: null, photos: []}, one: {count: 1, active_id: photos3[1].id, photos: [{id: photos3[1].id, name: photos3[1].name}]}};
  const mySel = SELS[q] || sel;
  const res = JSON.parse(JSON.stringify(REAL));
  const variants = {
    partial: r => { r.status = 'partial'; r.dropped = ['已忽略第 3 项：照片编号不在本次选中的照片中。', '已忽略第 4 项：reason 超过 40 字。']; r.ranking = r.ranking.slice(0, 2); return r; },
    unstructured: r => { r.status = 'unstructured'; r.ranking = []; r.summary = ''; r.dropped = []; r.message = '未能得到结构化结果。以下为 AI 的原文，仅供参考，无法据此写入星级和旗标。';
      r.raw = '三张照片里，我认为第二张最好。<script>alert(1)</scr' + 'ipt> <img src=x onerror=alert(2)>\n（以上为测试用的不可信文本，界面应当原样显示为文字。）'; return r; },
    failed: r => { r.status = 'failed'; r.ranking = []; r.message = 'Claude 命令行尚未登录。请在终端运行 claude，输入 /login 完成登录后重试。'; return r; },
    timeout: r => { r.status = 'timeout'; r.ranking = []; r.message = '等待超过 180 秒仍无结果，已停止。请减少照片数量后重试。'; return r; },
    stopped: r => { r.status = 'stopped'; r.ranking = []; r.message = '已停止。'; return r; },
    top1: r => { r.count = 'top1'; r.count_label = '最好的 1 张'; r.ranking = r.ranking.slice(0, 1); r.extra = 2; return r; },
  };
  const result = (variants[q] || (r => r))(res);
  const items = [
    {photo_id: IDS['DSC08205.JPG'], name: 'DSC08205.JPG', rank: 1, old_rating: 0, old_flag: 'none', new_rating: 4, new_flag: 'pick', changed: true, error: '', old_text: '无星级 / 无旗标', new_text: '4 星 / 留用'},
    {photo_id: IDS['DSC08206.ARW'], name: 'DSC08206.ARW', rank: 2, old_rating: 3, old_flag: 'none', new_rating: 3, new_flag: 'none', changed: false, error: '', old_text: '3 星 / 无旗标', new_text: '3 星 / 无旗标'},
    {photo_id: IDS['DSC08151.ARW'], name: 'DSC08151.ARW', rank: 3, old_rating: 1, old_flag: 'reject', new_rating: 2, new_flag: 'none', changed: true, error: '', old_text: '1 星 / 排除', new_text: '2 星 / 无旗标'},
  ];
  const applyRes = (st3) => ({stage: 'done', summary: {n: 2, ok: st3[0] === 'ok' ? 2 : 0, failed: st3.filter(x => x === 'failed').length, uncertain: st3.filter(x => x === 'uncertain').length}, results: [
    {photo_id: IDS['DSC08205.JPG'], name: 'DSC08205.JPG', new_rating: 4, new_flag: 'pick', undone: false, status: st3[0], message: st3[0] === 'failed' ? '这张照片已不在目录中。' : '', has_edit: st3[0] !== 'failed'},
    {photo_id: IDS['DSC08151.ARW'], name: 'DSC08151.ARW', new_rating: 2, new_flag: 'none', undone: false, status: st3[1], message: st3[1] === 'uncertain' ? 'Lightroom 没有在时限内回复，不确定是否已写入。请在 Lightroom 中确认这张照片的星级和旗标。' : '', has_edit: true}]});
  const err = {disc: 'Lightroom 未连接。请确认 Lightroom 已打开且插件已启用。', none: 'Lightroom 中没有选中照片。请先在 Lightroom 中选择要比较的照片。', many: '已选中 11 张照片，请减少到 10 张以内。'};
  const stageOf = {running: 'running', applied: 'done'};
  const hasResult = ['result', 'partial', 'unstructured', 'failed', 'timeout', 'stopped', 'top1', 'confirm', 'confirm_ro', 'zoom', 'applied', 'applied_mixed', 'undone'].includes(q);
  window.__CALLS__ = [];
  window.pywebview = {api: {
    send: ()=>Promise.resolve({ok:true}), stop(){}, reset(){}, answer(){}, undo(){}, restore_original(){},
    status: ()=>Promise.resolve({state:'connected', text:'Lightroom 已连接', hint:'', photo:{id: photos3[0].id, name: photos3[0].name}}),
    preview_state: ()=>Promise.resolve({type:'preview', state:'ok', photo:{id: photos3[0].id, name: photos3[0].name, camera:'Sony ILCE-7M3', format:'RAW', size:'6000 × 4000'},
      initial:{url:'/t/DSC08151.ARW.jpg', w:256, h:171}, current:{url:'/t/DSC08151.ARW.jpg', w:256, h:171}, same:true, edge:1024}),
    set_preview_edge: ()=>Promise.resolve({ok:true}),
    selection_state: ()=>Promise.resolve(mySel),
    get_settings: ()=>Promise.resolve({settings:{schema:1, base_folder:'D:\\示例', provider:'claude', confirm_default:true, preview_edge:1024}, providers:[], current_provider:'claude', edges:[1024], about:{}}),
    import_state: ()=>Promise.resolve({stage:'idle'}), library_list: ()=>Promise.resolve({exists:false, total:0, groups:[], shown:0, more:0, base:'D:\\示例'}),
    export_state: ()=>Promise.resolve({stage:'idle'}),
    pick_state: ()=>Promise.resolve({stage: q === 'running' ? 'running' : (hasResult && !['applied','applied_mixed','undone'].includes(q) ? 'done' : (['applied','applied_mixed','undone'].includes(q) ? 'done' : 'idle')), n: 3, result: hasResult ? result : undefined, thumbs: T}),
    pick_apply_state: ()=>Promise.resolve(q === 'applied' || q === 'undone' ? applyRes(['ok','ok']) : (q === 'applied_mixed' ? applyRes(['failed','uncertain']) : {stage:'idle', results:[], summary:null})),
    pick_prepare: ()=>Promise.resolve(err[q] ? {ok:false, message: err[q], too_many: q === 'many'} :
      {ok:true, stage:'idle', count: q === 'one' ? 1 : 3, limit: 10, photos: q === 'one' ? [photos3[1]] : photos3, thumbs: T}),
    pick_start: (o)=>{ window.__CALLS__.push(o); return Promise.resolve(q === 'login' ? {ok:false, message:'已安装，但尚未登录。 请在终端运行 claude，输入 /login 完成登录。'} : {ok:true}); },
    pick_stop: ()=>Promise.resolve({ok:true}), pick_close: ()=>Promise.resolve({ok:true}), pick_apply_close: ()=>Promise.resolve({ok:true}),
    pick_preview: (id)=>Promise.resolve({ok:true, url: T[id].replace('/t/', '/b/')}),
    pick_apply_prepare: ()=>Promise.resolve(q === 'confirm_ro' ? {ok:false, readonly:true, message:'只读模式已开启，不允许修改照片。要写入星级和旗标，请先关闭只读模式。'} : {ok:true, items}),
    pick_apply_confirm: ()=>Promise.resolve({ok:true}), pick_apply_cancel: ()=>Promise.resolve({ok:true}),
    pick_apply_undo: ()=>Promise.resolve({ok:false, partial:true, conflict:true, message:'', results:[
      {photo_id: IDS['DSC08205.JPG'], name:'DSC08205.JPG', status:'undone', message:''},
      {photo_id: IDS['DSC08151.ARW'], name:'DSC08151.ARW', status:'conflict', message:'这张照片的星级或旗标在写入之后又被改动过，直接还原会覆盖这些改动。'}]}),
  }};
})();
</script>"""

TAIL = r"""<script>
window.dispatchEvent(new Event('pywebviewready'));
const q = new URLSearchParams(location.search).get('s') || 'form';
const wait = ms => new Promise(r => setTimeout(r, ms));
(async()=>{
  await wait(250);
  if (q === 'list') return;
  await openPick(); await wait(200);
  if (q === 'form_custom') { document.querySelector('input[name=pk_c][value=custom]').click(); const i=document.getElementById('pk_custom'); i.value='更看重人物表情与光线氛围'; i.dispatchEvent(new Event('input')); document.querySelector('input[name=pk_n][value=top1]').click(); }
  if (q === 'form_toolong') { document.querySelector('input[name=pk_c][value=custom]').click(); const i=document.getElementById('pk_custom'); i.removeAttribute('maxlength'); i.value='光'.repeat(130); i.dispatchEvent(new Event('input')); }
  if (q === 'login') { document.getElementById('pk_go').click(); await wait(200); }
  if (q === 'running') { onClaudeEvent({type:'pick_progress', state:'running', n:3, label:'正在逐张读取选中的照片'}); await wait(1200); }
  if (q === 'confirm' || q === 'confirm_ro') { await pkApply(); await wait(200); }
  if (q === 'confirm') { document.querySelector('#pk_body input[type=checkbox]:checked').click(); document.querySelector('#pk_body input[type=checkbox]').click(); }
  if (q === 'zoom') { await pkZoom(document.querySelector('[data-zoom]').dataset.zoom); await wait(300); }
  if (q === 'undone') { await pkUndo(false); }
  if (q === 'applying') { pkApplying({i:1, n:2, name:'DSC08151.ARW'}); }
})();
</script>"""


def main(out: Path, thumbs: Path, result_json: Path) -> None:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    real = json.loads(result_json.read_text(encoding="utf-8"))["pick"]
    html = WEB.read_text(encoding="utf-8")
    html = html.replace("<script>", STUB.replace("__REAL__", json.dumps(real, ensure_ascii=False)) + "\n<script>", 1)
    html = html.replace("</body>", TAIL + "</body>")
    page = html.encode("utf-8")

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            path = self.path.split("?")[0]
            if path.startswith(("/t/", "/b/")):
                f = thumbs / path.split("/", 2)[2]
                data = f.read_bytes() if f.is_file() else b""
                ctype = "image/jpeg"
            else:
                data, ctype = page, "text/html; charset=utf-8"
            self.send_response(200 if data else 404)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    scenes = ("list", "none", "many", "disc", "form", "one", "form_custom", "form_toolong", "login", "running", "result", "top1", "partial",
              "unstructured", "failed", "timeout", "stopped", "zoom", "confirm", "confirm_ro", "applying", "applied", "applied_mixed", "undone")
    try:
        for name in scenes:
            target = out / f"pick_{name}.png"
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1440,900",
                            "--virtual-time-budget=6000", f"--screenshot={target}",
                            f"http://127.0.0.1:{httpd.server_address[1]}/?s={name}"], check=True, timeout=60, capture_output=True)
            print("截图", target)
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
