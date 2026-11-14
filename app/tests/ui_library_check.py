# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""预设 / 收藏 / 经验界面自查（无窗口、无 Lightroom、不调用模型，不属于 pytest）。
临时本机静态服务加载 index.html（注入假的 pywebview.api 与示例数据），用无头 Edge 截图各场景。示例数据只存在于本脚本里，不属于软件。
用法：python app/tests/ui_library_check.py <截图输出目录>      截图命名 library_<场景>.png
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
  const S = new URLSearchParams(location.search).get('s') || 'preset_empty';
  const empty = /empty/.test(S);
  const presets = empty ? [] : [
    {id:'p-000000000001', name:'示例预设一', note:'示例备注：高光压低、饱和度略升。', groups:['色调','色彩','曲线'], count:14, modified:'2026-11-03 20:00:00', fav:true},
    {id:'p-000000000002', name:'示例预设二', note:'', groups:['色调','色彩','细节与效果','曲线'], count:31, modified:'2026-11-03 20:10:00', fav:false},
    {id:'p-000000000003', name:'示例预设三（名称较长时在列表中完整换行显示）', note:'', groups:['色调'], count:6, modified:'2026-11-03 20:20:00', fav:false}];
  const notes = empty ? [] : [
    {id:'n-000000000001', title:'示例经验一：天空发灰', scene:'示例场景', tags:['风光','天空'], body:'示例正文：先降低高光 20，再把蓝色饱和度提高 10。', use_in_chat:true, fav:true, modified:'2026-11-03 20:00:00'},
    {id:'n-000000000002', title:'示例经验二：逆光人像', scene:'', tags:['人像'], body:'示例正文：阴影 +40。', use_in_chat:false, fav:false, modified:'2026-11-03 20:05:00'}];
  const lr = {ok:true, hidden_masks:2, note:'共 6 个预设，显示 6 个。', groups:[
    {folder:'示例分组一', presets:[{id:'11111111-aaaa', name:'示例 Lightroom 预设', masks:false, key:'示例分组一/示例 Lightroom 预设', fav:false}, {id:'22222222-bbbb', name:'示例带蒙版预设', masks:true, key:'示例分组一/示例带蒙版预设', fav:false}]},
    {folder:'示例分组二', presets:[{id:'33333333-cccc', name:'示例用户预设', masks:false, key:'示例分组二/示例用户预设', fav:true}]}]};
  const favs = empty ? {ok:true, groups:{preset:[],lr_preset:[],note:[],photo:[]}, total:0, photo_fav:false} :
    {ok:true, total:5, photo_fav:true, groups:{preset:[{type:'preset',key:'示例预设一',label:'示例预设一'}], lr_preset:[{type:'lr_preset',key:'示例分组二/示例用户预设',label:'示例用户预设'}],
      note:[{type:'note',key:'n-000000000001',label:'示例经验一：天空发灰'}], photo:[{type:'photo',key:'P',label:'DSC08238.ARW',time:'2026-11-03 20:00:00'}]}};
  const plan = {ok:true, token:'tok', kind:'mine', title:'套用预设“示例预设一”（强度 50%）', photo:'DSC08238.ARW', skipped:['色温'], clipped:1, unchanged:3,
    items:[{label:'曝光', current:'0.2', new:'0.6', clipped:false}, {label:'高光', current:'0', new:'-20', clipped:false}, {label:'饱和度', current:'5', new:'12.5', clipped:false},
           {label:'亮度曲线', current:'曲线(2 点)', new:'曲线(3 点)', clipped:false}, {label:'暗角数量', current:'-100', new:'-100', clipped:true}]};
  const draft = {title:'示例草稿：雪山天空', scene:'雪山', tags:['风光','天空'], body:'示例正文：高光 -20，饱和度 +10。依据：天空高光过曝。效果：云层层次更清楚。', use_in_chat:true};
  const A = {ok:true};
  window.pywebview = {api: {
    send: ()=>Promise.resolve({ok:true}), stop(){}, reset(){}, answer(){}, undo(){}, restore_original(){},
    status: ()=>Promise.resolve({state:'connected', text:'Lightroom 已连接', hint:'', photo:{id:'P', name:'DSC08238.ARW'}}),
    preview_state: ()=>Promise.resolve({type:'preview', state:'none', message:'Lightroom 中未选中照片'}), set_preview_edge: ()=>Promise.resolve({ok:true}),
    selection_state: ()=>Promise.resolve({count:1, active_id:'P', photos:[{id:'P', name:'DSC08238.ARW'}]}),
    import_state: ()=>Promise.resolve({stage:'idle'}), library_list: ()=>Promise.resolve({ok:true, exists:false, base:'示例', groups:[], total:0, more:0, shown:0}),
    get_settings: ()=>Promise.resolve({settings:{schema:1, base_folder:'C:\\\\示例', provider:'claude', confirm_default:true, preview_edge:1024, ai_use_notes:true},
      providers:[{id:'claude', name:'Claude Code 命令行', selectable:true, available:true, state:'ready', reason:'已安装并已登录。', next_step:''}], current_provider:'claude', edges:[768,1024,1536,2048],
      about:{app_version:'0.10.0', lightroom_version:'15.2.0', plugin_version:'0.15.0', data_dir:'~/LrMcp', project_url:'https://github.com/Denvolatos/lightroom-mcp-latos-hue'}}),
    lib_presets: ()=>Promise.resolve({ok:true, presets, max:200}),
    lib_notes: (q,t)=>Promise.resolve({ok:true, notes: notes.filter(n=>(!q||(n.title+n.body).indexOf(q)>=0)&&(!t||n.tags.indexOf(t)>=0)), tags:empty?[]:['风光','天空','人像'], max:300, context:{used:empty?0:1, eligible:empty?0:1, truncated:false}}),
    lib_favs: ()=>Promise.resolve(favs),
    lib_lr_presets: ()=>Promise.resolve(lr),
    lib_preset_options: ()=>Promise.resolve({groups:[{id:'tone',label:'色调',default:true},{id:'color',label:'色彩',default:true},{id:'detail',label:'细节与效果',default:true},{id:'curve',label:'曲线',default:true},{id:'wb',label:'白平衡',default:false},{id:'crop',label:'裁剪与拉直',default:false}], limits:{name:40, note:200}}),
    lib_preset_save: (n,no,g,o)=> /重复/.test(n) && !o ? Promise.resolve({ok:false, exists:true, message:'已有名为“'+n+'”的预设。是否覆盖？'}) : (/错/.test(n) ? Promise.resolve({ok:false, message:'名称不超过 40 个字（当前 41 个字）。'}) : Promise.resolve({ok:true, id:'p-000000000001', message:'已保存预设“'+n+'”（14 项参数）。'})),
    lib_apply_prepare: (k,r,s)=> S==='apply_readonly' ? Promise.resolve({ok:false, readonly:true, message:'只读模式已开启，不允许修改照片。要套用，请先关闭只读模式。'}) :
       (k==='lr' ? Promise.resolve({ok:true, token:'tok2', kind:'lr', title:'套用 Lightroom 预设“示例 Lightroom 预设”', photo:'DSC08238.ARW', items:[], note:'将套用 Lightroom 预设“示例 Lightroom 预设”。预设可能一次改动许多参数；改前会保存这张照片的完整快照，可在“本次调整”中撤销。'}) : Promise.resolve(plan)),
    lib_apply_confirm: ()=> S==='apply_error' ? Promise.resolve({ok:false, message:'这张照片已经有蒙版/局部调整，套预设可能影响它们且无法安全还原，已取消。'}) : Promise.resolve({ok:true, message:'已套用预设“示例预设一” 50%，共改动 4 项。可在“本次调整”中撤销。'}),
    lib_apply_cancel: ()=>Promise.resolve(A),
    lib_note_save: (id,f)=> f.title==='错' ? Promise.resolve({ok:false, message:'标题不超过 60 个字（当前 61 个字）。'}) : Promise.resolve({ok:true, id:'n-000000000009'}),
    lib_note_delete: ()=>Promise.resolve(A), lib_notes_import: ()=>Promise.resolve({ok:false, message:'第 2 条不合规：标题不超过 60 个字（当前 61 个字）。已整体拒绝导入。'}),
    lib_preset_import: ()=>Promise.resolve({ok:false, message:'文件含有不允许的参数“Look”。'}),
    lib_notes_export: ()=>Promise.resolve({ok:true}), lib_fav_toggle: ()=>Promise.resolve({ok:true, on:true}),
    lib_record_start: ()=>Promise.resolve(A), lib_record_stop: ()=>Promise.resolve(A), lib_record_close: ()=>Promise.resolve(A),
    __draft: draft
  }};
})();
</script>"""

TAIL = """<script>
window.dispatchEvent(new Event('pywebviewready'));
const S = new URLSearchParams(location.search).get('s') || 'preset_empty';
const wait = ms => new Promise(r => setTimeout(r, ms));
const click = sel => { const e = document.querySelector(sel); if (e) e.click(); };
const tab = t => click('#ltabs .tab[data-t="' + t + '"]');
const sendEv = ev => window.onClaudeEvent(ev);
(async()=>{
  await wait(200);
  if (/^preset/.test(S)) tab('preset');
  if (S === 'preset_list' || S === 'preset_confirm' || S === 'preset_save_error' || S === 'apply_readonly' || S === 'apply_error') { await wait(100); click('[data-pid="p-000000000001"]'); }
  if (S === 'preset_save' || S === 'preset_save_error' || S === 'preset_save_dup') { await wait(100); click('#pr_save'); await wait(150);
    document.getElementById('sp_name').value = S === 'preset_save_error' ? '错' : (S === 'preset_save_dup' ? '重复的名称' : '示例新预设');
    document.getElementById('sp_note').value = '示例备注';
    if (S === 'preset_save_error' || S === 'preset_save_dup') { click('#sp_ok'); await wait(150); } }
  if (S === 'preset_confirm' || S === 'apply_readonly' || S === 'apply_error') { await wait(100); const r = document.getElementById('pr_str'); r.value = 50; r.oninput(); click('#pr_apply'); await wait(150); if (S === 'apply_error') { click('#ap_ok'); await wait(150); } }
  if (S === 'lr_list' || S === 'lr_confirm') { await wait(100); click('[data-sub="lr"]'); await wait(200); click('[data-lid="11111111-aaaa"]'); if (S === 'lr_confirm') { await wait(100); click('#lr_apply'); await wait(150); } }
  if (S === 'lr_masks') { await wait(100); click('[data-sub="lr"]'); await wait(200); click('[data-lid="22222222-bbbb"]'); }
  if (S === 'preset_import_error') { await wait(100); click('#pr_imp'); await wait(150); }
  if (S === 'fav' || S === 'fav_empty' || S === 'fav_photo') { tab('fav'); await wait(150); if (S === 'fav_photo') { click('[data-fk="photo"]'); } }
  if (/^exp/.test(S) || S === 'notes_import_error') { tab('exp'); await wait(150); }
  if (S === 'exp_edit') { click('[data-nid="n-000000000001"]'); }
  if (S === 'exp_new_error') { click('#nt_new'); await wait(100); document.getElementById('ne_title').value = '错'; document.getElementById('ne_body').value = '示例正文'; click('#ne_ok'); await wait(150); }
  if (S === 'notes_import_error') { click('#nt_imp'); await wait(150); }
  if (S === 'exp_filter') { const t = document.getElementById('nt_tag'); t.value = '人像'; t.onchange(); await wait(150); }
  if (/^record/.test(S)) {
    rows = [{rid:'a', edit_id:'E1', key:'Highlights2012', label:'高光', before:'0', after:'-20', reason:'示例', photo:'P', status:'已应用'}]; renderParams();
    sendEv({type:'done', text:'', tokens:100, cost:0.01}); await wait(100);
    document.querySelector('.recbtn button').click(); await wait(150);
    if (S === 'record_draft') sendEv({type:'record_done', ok:true, draft:window.pywebview.api.__draft, elapsed:9.8, tokens:21000, cost:0.03});
    if (S === 'record_fail') sendEv({type:'record_done', ok:false, message:'AI 返回的内容不合规：标题不超过 60 个字（当前 71 个字）。', raw:'{"title": "示例过长标题…", "scene": "", "tags": [], "body": "…"}', elapsed:8.1, tokens:19000, cost:0.02});
  }
  if (S === 'context_note') { sendEv({type:'notes_context', used:3, eligible:5, truncated:true}); }
  if (S === 'settings') { await openSettings(); }
})();
</script>"""

SCENES = ["preset_empty", "preset_list", "preset_save", "preset_save_dup", "preset_save_error", "preset_confirm", "apply_readonly", "apply_error",
          "lr_list", "lr_confirm", "lr_masks", "preset_import_error", "fav", "fav_photo", "fav_empty", "exp_empty", "exp_list", "exp_filter", "exp_edit",
          "exp_new_error", "notes_import_error", "record_running", "record_draft", "record_fail", "context_note", "settings"]


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
        for name in (sys.argv[2:] or SCENES):
            target = out / f"library_{name}.png"
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1440,900",
                            "--virtual-time-budget=5000", f"--screenshot={target}",
                            f"http://127.0.0.1:{httpd.server_address[1]}/?s={name}"], check=True, timeout=60, capture_output=True)
            print("截图", target)
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
