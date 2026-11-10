# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""1.1.0 新界面自查（无窗口、无 Lightroom、不调用模型，不属于 pytest）：多版本页、版本应用确认、命名输入、
批量复用预演、图库换目录后的提示条、环境检查里“请选择 AI”的各种状态，以及它们在 1100 宽窗口下是否溢出。
临时本机静态服务加载 index.html（注入假的 pywebview.api，只含示例数据），用无头 Edge 截图，并用 --dump-dom 检查
页面不横向溢出、按钮文字没被挤成多行、对话框没超出窗口。
用法：python app/tests/ui_versions_check.py <截图输出目录>    （有问题时退出码为 1）
"""
import re
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"

STUB = r"""<script>
(function(){
  const S = new URLSearchParams(location.search).get('s') || 'versions';
  const svg = (a, b, t) => 'data:image/svg+xml;utf8,' + encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="900" height="600"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${a}"/><stop offset="1" stop-color="${b}"/></linearGradient></defs><rect width="900" height="600" fill="url(#g)"/><text x="450" y="310" font-size="34" fill="#ffffffaa" text-anchor="middle" font-family="sans-serif">${t}</text></svg>`);
  const CUR = svg('#4f7396', '#c9b28a', '示例画面（当前）'), SAVED = svg('#8a5a3c', '#e2b36a', '示例画面（已保存版本）');
  const photo = {id:'11111111-aaaa-bbbb-cccc-000000000001', name:'DSC08238.ARW', camera:'Sony ILCE-7M3', iso:'ISO 100', aperture:'f / 8', shutter:'1/800', focal:'20 mm', format:'RAW', size:'6000 × 4000'};
  const pvOk = {type:'preview', state:'ok', photo, initial:{url:CUR, w:1024, h:683, version:'a'}, current:{url:CUR, w:1024, h:683, version:'b'}, same:false, edge:1024};
  const versions = S.startsWith('versions_empty') ? [] : [
    {name:'暖色调', note:'', created:'2026-11-08 21:14:03', settings:68, has_preview_picture:true},
    {name:'黑白高对比（发朋友圈用的那一版，名字故意写长一点）', note:'', created:'2026-11-08 21:30:47', settings:68, has_preview_picture:true},
    {name:'<b>原始</b>&"引号"', note:'', created:'2026-11-07 09:02:11', settings:68, has_preview_picture:false}];
  const items = [
    {label:'曝光', before:'0.35', after:'0.1'}, {label:'对比度', before:'12', after:'20'}, {label:'高光', before:'-40', after:'-65'},
    {label:'阴影', before:'25', after:'40'}, {label:'色温', before:'5600', after:'6100'}, {label:'色调', before:'4', after:'9'},
    {label:'自然饱和度', before:'10', after:'22'}, {label:'橙色饱和度', before:'0', after:'-8'}, {label:'亮度曲线', before:'曲线(2 点)', after:'曲线(4 点)'},
    {label:'<img src=x onerror=alert(1)>', before:'0', after:'1'}];
  const batchPlan = {dry_run:true, plan_id:'a1b2c3d4e5f6', will_change:2, skipped:1, source_photo:'DSC08238.ARW', source_edit_id:'20261109-120000-ab12',
    delta_items:[{label:'曝光', delta:'+0.1'}, {label:'对比度', delta:'+8'}], skipped_labels:['拉直角度', '亮度曲线'],
    photos:[
      {photo:'DSC08239.ARW', photo_id:'p2', will_change:true, changes:[{parameter:'Exposure2012', label:'曝光', before_text:'0.2', after_text:'0.3'}, {parameter:'Contrast2012', label:'对比度', before_text:'5', after_text:'13'}]},
      {photo:'DSC08240.ARW', photo_id:'p3', will_change:true, changes:[{parameter:'Exposure2012', label:'曝光', before_text:'-0.15', after_text:'-0.05'}, {parameter:'Contrast2012', label:'对比度', before_text:'0', after_text:'8'}]},
      {photo:'DSC08241_<i>长文件名</i>_用于检查换行与转义_abcdefghijklmnopqrstuvwxyz.ARW', photo_id:'p4', will_change:false, reason_skipped:'对比度 改完会是 104，超出允许范围（-100 到 100）。'}]};
  /* 环境检查：四项里只有 AI 一项在变 */
  const it = (id, title, state, text, hint, action, label)=>({id, title, state, text, hint:hint||'', action:action||'', action_label:label||''});
  const FOLDER_OK = it('folder','照片工作文件夹','ready','已选择：D:\\示例\\修图助手');
  const LR_OK = it('lightroom','Lightroom','ready','Lightroom 正在运行。');
  const PL_OK = it('plugin','Lightroom 插件','ready','插件已连接（版本 1.1.0）。');
  const PRIV = '使用 Codex 时，选中照片的预览会发送至所选的 Codex 服务。';
  const choice = (id, short, name, ok, status) => ({id, label:'使用 ' + short, name, ok, status, privacy: id==='codex' ? PRIV : ''});
  const C = 'Claude Code 命令行', X = 'Codex 命令行';
  const combos = {
    a: [choice('claude','Claude',C,true,'已安装并已登录。'), choice('codex','Codex',X,false,'未安装 Codex 命令行。')],
    b: [choice('claude','Claude',C,false,'已安装，但尚未登录。'), choice('codex','Codex',X,true,'已安装并已登录。')],
    c: [choice('claude','Claude',C,false,'未安装 Claude Code 命令行。'), choice('codex','Codex',X,false,'未安装 Codex 命令行。')],
    d: [choice('claude','Claude',C,true,'已安装，登录状态无法判断。'), choice('codex','Codex',X,false,'已安装，但尚未登录。')]};
  const m = S.match(/^choose_([a-d])/);
  const AI_CHOOSE = Object.assign(it('ai','AI 助手','todo','请选择要使用的 AI。','软件用的是你电脑上已经安装并登录的 AI 命令行，不保存你的账号。点下面的按钮选一个；还没安装的也可以先选，选了之后这里会告诉你下一步怎么装、怎么登录。以后可以在“设置”里更换。'),
    {need_choice:true, choices: combos[m ? m[1] : 'a']});
  const AI_OK = it('ai','AI 助手','ready','Claude Code 命令行：已安装并已登录。','','choose_ai','更换 AI 来源');
  const AI_TODO = it('ai','AI 助手','todo','Codex 命令行：未安装 Codex 命令行。','请安装 Codex CLI 后重试。','choose_ai','更换 AI 来源');
  const unchosen = S.startsWith('choose_') || S.startsWith('settings_unchosen') || S.startsWith('send_unchosen');
  const aiItem = unchosen ? AI_CHOOSE : (S.startsWith('chosen_todo') ? AI_TODO : AI_OK);
  const wz = {items:[FOLDER_OK, LR_OK, PL_OK, aiItem], ready: aiItem === AI_OK, checking:false, auto_open: !!aiItem.need_choice,
    wizard_done:true, mark_done:false, message:''};
  const providers = [
    {id:'claude', name:C, selectable:true, available:true, state:'ready', reason:'已安装并已登录。', next_step:'', privacy_notice:''},
    {id:'codex', name:X, selectable:true, available:false, state:'not_installed', reason:'未安装 Codex 命令行。', next_step:'请安装 Codex CLI 后重试。', privacy_notice:PRIV},
    {id:'api', name:'API 密钥', selectable:false, available:false, state:'unavailable', reason:'API 密钥（兼容 OpenAI 接口的各家，含 DeepSeek 等）——后续提供。', next_step:'', privacy_notice:''}];
  const settings = {schema:1, base_folder:'D:\\示例\\修图助手', gallery_folder: S.startsWith('gallery') ? 'E:\\示例\\2026 旅行\\原片（很长的文件夹名字用来检查换行）' : '',
    provider:'claude', provider_chosen: !unchosen, confirm_default:true, preview_edge:1024, ai_use_notes:true};
  /* 图库（换目录后）：示例照片 */
  const names = ['DSC08151.ARW','DSC08152.ARW','DSC08205.JPG','DSC08206.ARW','DSC08238.ARW','DSC08244.JPG'];
  const gphotos = names.map((n,i)=>({id:String(101+i), name:n, group: i<3 ? '第一天' : '第二天', format:n.endsWith('ARW')?'ARW':'JPG', rating:[3,null,1,0,5,null][i], flag:'none',
    captured:'2026-10-0'+(i+1)+' 10:02', w:6000, h:4000, vc:false, added: i!==1, missing:false}));
  const gallery = {ok:true, state:'ready', message:'', base: settings.gallery_folder || settings.base_folder, base_exists:true, in_catalog:true, lr_connected:true,
    total:gphotos.length, limit:2000, truncated:false, truncated_message:'', not_added:1, missing:0, photos:gphotos, thumbs:{}, failed:{}, selection:{ids:[], active:null}, add:null, max_select:50};
  const thumbs = ids => { const o = {}; ids.forEach((i,k)=>{ o[i] = {url: svg(['#5d7fa3','#a37d5d','#6b9a78','#8d6aa8'][k%4], '#22262c', '')}; }); return o; };
  window.__CALLS__ = [];
  const log = (n, a) => { window.__CALLS__.push([n].concat(a||[])); };
  window.pywebview = {api: {
    send: ()=>Promise.resolve(unchosen ? {ok:false, need_ai_choice:true, message:'请先在“环境检查”里选择要使用的 AI。'} : {ok:true}),
    stop(){}, reset(){}, answer(){}, restore_original(){},
    undo: id=>{ log('undo',[id]); return Promise.resolve({ok:true}); },
    status: ()=>Promise.resolve({state:'connected', text:'Lightroom 已连接', hint:'', photo:{id:photo.id, name:photo.name}}),
    preview_state: ()=>Promise.resolve(pvOk), set_preview_edge: ()=>Promise.resolve({ok:true}),
    autolaunch_state: ()=>Promise.resolve({state:'idle', message:''}),
    selection_state: ()=>Promise.resolve({count:4, active_id:photo.id, photos:[]}), import_state: ()=>Promise.resolve({stage:'idle'}),
    get_settings: ()=>Promise.resolve({settings, lightroom_detected:'', providers, current_provider: unchosen ? '' : 'claude', edges:[768,1024,1536,2048],
      about:{app_version:'1.1.0', lightroom_version:'15.0.0', plugin_version:'1.1.0', data_dir:'~/LrMcp', project_url:'https://github.com/Denvolatos/lightroom-mcp-latos-hue'}}),
    wizard_state: ()=>Promise.resolve(JSON.parse(JSON.stringify(wz))), wizard_done: ()=>Promise.resolve({ok:true}),
    wizard_choose_ai: id=>{ log('wizard_choose_ai',[id]); return Promise.resolve({ok:true, message:''}); },
    versions_state: ()=>Promise.resolve({ok:true, result:{photo:photo.name, photo_id:photo.id, count:versions.length, versions}}),
    version_preview: name=>Promise.resolve(name.indexOf('原始')>=0 ? {ok:false, message:'这个版本没有预览图。'} : {ok:true, result:{photo_id:photo.id, url:SAVED}}),
    version_plan: name=>Promise.resolve({ok:true, result:{photo_id:photo.id, name, count:items.length + (S.startsWith('versions_apply') ? 35 : 0),
      items: S.startsWith('versions_apply') ? items.concat(Array.from({length:35}, (_, i)=>({label:'示例参数 ' + (i+1), before:String(i), after:String(i+1)}))) : items, token:'tok-123'}}),
    version_save: name=>{ log('version_save',[name]); return Promise.resolve({ok:true, result:{version:name}}); },
    version_apply: function(){ log('version_apply', Array.from(arguments)); return Promise.resolve({ok:true, result:{edit_id:'20261109-120000-ab12', photo_id:photo.id, changes:[]}}); },
    batch_plan_from_edit: id=>{ log('batch_plan_from_edit',[id]); return Promise.resolve({ok:true, result:JSON.parse(JSON.stringify(batchPlan))}); },
    batch_apply: id=>{ log('batch_apply',[id]); return Promise.resolve({ok:true, result:{batch_id:'20261109-120500-cd34', changed:2, results:[], stopped_early_at:null, not_done:0}}); },
    batch_undo: id=>{ log('batch_undo',[id]); return Promise.resolve({ok:true, result:{problems:[]}}); },
    lib_presets: ()=>Promise.resolve({ok:true, presets:[], max:200}), lib_notes: ()=>Promise.resolve({ok:true, notes:[], tags:[], max:300, context:{used:0, eligible:0, truncated:false}}),
    lib_favs: ()=>Promise.resolve({ok:true, groups:{preset:[],lr_preset:[],note:[],photo:[]}, total:0, photo_fav:false}), lib_lr_presets: ()=>Promise.resolve({ok:true, groups:[]}),
    library_state: ()=>Promise.resolve(JSON.parse(JSON.stringify(gallery))), library_refresh: ()=>Promise.resolve({ok:true}),
    library_thumbnails: ids=>Promise.resolve({ok:true, thumbs:thumbs(ids), pending:[]}),
    gallery_pick_folder: ()=>{ log('gallery_pick_folder'); return Promise.resolve({ok:true}); },
  }};
  const A = window.pywebview.api;      /* 没写到的接口一律返回空结果，避免启动流程半路中断 */
  window.pywebview.api = new Proxy(A, {get: (t, k) => (k in t) ? t[k] : (() => Promise.resolve({}))});
})();
</script>"""

TAIL = r"""<script>
window.dispatchEvent(new Event('pywebviewready'));
const q = new URLSearchParams(location.search).get('s') || 'versions';
const wait = ms => new Promise(r => setTimeout(r, ms));
const ROWS = [
  {rid:'r1', edit_id:'20261109-120000-ab12', label:'曝光', reason:'整体偏暗，提亮一点', before:'0', after:'0.1', status:'已应用', photo:'p1'},
  {rid:'r2', edit_id:'20261109-120000-ab12', label:'对比度', reason:'增加层次', before:'4', after:'12', status:'已应用', photo:'p1'},
  {rid:'lib:1', edit_id:'20261109-121000-ef56', label:'预设“暖色调” 80%', reason:'', before:'—', after:'—', status:'已应用', photo:'p1'}];
(async()=>{
  await wait(500);
  const notes = [];
  try {
    if (q.startsWith('versions') || q.startsWith('batch')) window.onClaudeEvent({type:'adjust', rows:ROWS});
    if (q.startsWith('versions')) { document.querySelector('#modes button[data-m="multi"]').click(); await wait(500); }
    if (q.startsWith('versions_apply')) { document.getElementById('versionapply').click(); await wait(500); }
    if (q.startsWith('versions_name') && !q.startsWith('versions_nameerr')) { document.getElementById('versionsave').click(); await wait(300);
      const inp = document.querySelector('.name-input'); inp.value = '暖色调 · 第二版'; }
    if (q.startsWith('versions_nameerr')) { document.getElementById('versionsave').click(); await wait(300);
      document.querySelector('.name-input').value = '   '; document.querySelectorAll('.mask.show .row .btn.primary')[0].click(); await wait(100); }
    if (q.startsWith('versions_applied')) { document.getElementById('versionapply').click(); await wait(400);
      const ok = Array.from(document.querySelectorAll('.mask.show .row .btn.primary')).pop(); ok.click(); await wait(500);
      const call = window.__CALLS__.find(c => c[0] === 'version_apply');
      notes.push('version_apply 参数=' + JSON.stringify(call ? call.slice(1) : null)); }
    if (q.startsWith('batch')) { document.querySelector('button[data-reuse]').click(); await wait(500); }
    if (q.startsWith('batch_done')) { Array.from(document.querySelectorAll('.mask.show .row .btn.primary')).pop().click(); await wait(500); }
    if (q.startsWith('chosen') ) { openWizard(); await wait(400); }
    if (q.startsWith('settings_unchosen')) { document.getElementById('w_x').click(); await openSettings(); await wait(300); }
    if (q.startsWith('send_unchosen')) { document.getElementById('w_x').click(); await wait(100); document.getElementById('inp').value = '提亮一点';
      document.getElementById('send').click(); await wait(500); }
    if (q.startsWith('choose_a_click')) { document.querySelector('.wz-choice .btn').click(); await wait(300);
      notes.push('调用=' + JSON.stringify(window.__CALLS__.filter(c => c[0] === 'wizard_choose_ai'))); }
  } catch (e) { window.__ERR__ = String(e); }
  const errNote = window.__ERR__ ? ' 脚本错误:' + window.__ERR__ : '';
  await wait(400);
  const bad = [];
  const W = document.documentElement.clientWidth, H = document.documentElement.clientHeight;
  if (document.documentElement.scrollWidth > W + 1) bad.push('页面横向溢出 ' + document.documentElement.scrollWidth + '>' + W);
  document.querySelectorAll('button, .tab, .badge, .status, label, select, h3').forEach(e => {
    const r = e.getBoundingClientRect(); if (!r.width) return;
    const cs = getComputedStyle(e); const lh = parseFloat(cs.lineHeight) || 18;
    const lineH = r.height - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
    const label = (e.textContent || '').trim().slice(0, 12) || e.id;
    if (e.tagName === 'BUTTON' && lineH > lh * 1.6 && label) bad.push('按钮换行 ' + label);
    if (r.right > W + 1 || r.left < -1) bad.push('超出窗口 ' + label);
  });
  document.querySelectorAll('.dialog').forEach(d => { const r = d.getBoundingClientRect(); if (r.width && (r.right > W + 1 || r.left < -1 || r.bottom > H + 1 || r.top < -1)) bad.push('对话框超出窗口'); });
  /* 假数据里放了 <b>、<i>、<img onerror>：它们只能以文字出现，不能变成真的元素 */
  if (document.querySelector('.dialog b, .dialog i, .dialog img, #versionpick b, #infobar b, #infobar img')) bad.push('动态文字没有转义');
  const pre = document.createElement('pre'); pre.id = 'chk'; pre.style.cssText = 'position:fixed;left:-9999px;top:0';
  pre.textContent = 'CHK[' + W + 'x' + H + ' ' + q + ']:' + (bad.length ? bad.join(' | ') : 'OK') + errNote + (notes.length ? ' 〔' + notes.join('；') + '〕' : '');
  document.body.appendChild(pre);
})();
</script>"""

WIDE, NARROW = (1440, 900), (1100, 690)
SCENES = (
    ("versions", WIDE, "versions_list.png"), ("versions_empty", WIDE, "versions_empty.png"),
    ("versions_apply", WIDE, "versions_apply_confirm.png"), ("versions_applied", WIDE, "versions_applied.png"),
    ("versions_name", WIDE, "versions_name_input.png"), ("versions_nameerr", WIDE, "versions_name_error.png"),
    ("batch", WIDE, "batch_plan.png"), ("batch_done", WIDE, "batch_done.png"),
    ("gallery", WIDE, "gallery_browse_folder.png"),
    ("choose_a", WIDE, "wizard_choose_ai_claude_ready.png"), ("choose_b", WIDE, "wizard_choose_ai_codex_ready.png"),
    ("choose_c", WIDE, "wizard_choose_ai_none_installed.png"), ("choose_d", WIDE, "wizard_choose_ai_unknown_login.png"),
    ("choose_a_click", WIDE, "wizard_choose_ai_clicked.png"),
    ("chosen_ready", WIDE, "wizard_ai_chosen_ready.png"), ("chosen_todo", WIDE, "wizard_ai_chosen_todo.png"),
    ("settings_unchosen", WIDE, "settings_ai_not_chosen.png"), ("send_unchosen", WIDE, "send_ai_not_chosen.png"),
    ("versions", NARROW, "layout_1100_versions.png"), ("versions_empty", NARROW, "layout_1100_versions_empty.png"),
    ("versions_apply", NARROW, "layout_1100_versions_apply.png"), ("versions_name", NARROW, "layout_1100_versions_name.png"),
    ("batch", NARROW, "layout_1100_batch_plan.png"), ("gallery", NARROW, "layout_1100_gallery_browse.png"),
    ("choose_a", NARROW, "layout_1100_wizard_choose_ai.png"), ("choose_c", NARROW, "layout_1100_wizard_choose_ai_none.png"),
)


def main(out: Path) -> None:
    out = out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    html = WEB.read_text(encoding="utf-8")
    html = html.replace("<script>", STUB + "\n<script>", 1).replace("</body>", TAIL + "</body>")
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
    base = f"http://127.0.0.1:{httpd.server_address[1]}/"
    failed = False
    try:
        for scene, (w, h), name in SCENES:
            common = [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--virtual-time-budget=6000"]
            url = f"{base}?s={scene}"
            subprocess.run(common + [f"--window-size={w},{h}", f"--screenshot={out / name}", url], check=True, timeout=60, capture_output=True)
            # --dump-dom 的窗口比截图的小一圈（窗口边框），多给 24 像素让两者页面尺寸一致
            dom = subprocess.run(common + [f"--window-size={w + 24},{h + 24}", "--dump-dom", url], check=True, timeout=60,
                                 capture_output=True).stdout.decode("utf-8", "replace")
            m = re.search(r'<pre id="chk"[^>]*>(CHK[^<]*)', dom)
            res = m.group(1) if m else "没有检查结果"
            verdict = res.split(":", 1)[-1].strip()
            failed |= not (verdict == "OK" or verdict.startswith("OK 〔"))
            print(name, res)
    finally:
        httpd.shutdown()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
