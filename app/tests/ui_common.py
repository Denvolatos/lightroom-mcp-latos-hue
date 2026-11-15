# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""1.3.0 界面自查脚本共用的小工具（无窗口、无 Lightroom、不调用模型；不属于 pytest）。

- FAKE_API：注入页面的假 pywebview.api（只含示例数据；没写到的接口一律返回空对象，避免启动流程半路中断）。
  场景由地址里的查询参数控制：?theme=dark&font=large&sys=dark ... 见各脚本。
- serve(page_html)：临时本机静态服务（127.0.0.1，随机端口）；/css /js /assets 从 app/web 提供。
- edge(...)：用无头 Edge 截图或 --dump-dom；--dump-dom 里读 <pre id="chk">。
用法（PowerShell 里跑；Bash 沙箱里 Edge 无输出）：python app/tests/ui_xxx_check.py <输出目录>
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from web_source import inject_stub, serve_static

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"

FAKE_API = r"""<script>
(function(){
  const q = new URLSearchParams(location.search);
  const S = {schema:1, base_folder:'D:\\示例\\照片库', provider:'claude', confirm_default:true, ai_use_notes:true, preview_edge:1024,
    auto_launch_lightroom:q.get('autolr')==='1', lightroom_path:q.get('lrpath')?'D:\\Adobe\\Lightroom Classic\\Lightroom.exe':'', check_updates:true,
    theme:q.get('theme')||'system', font_size:q.get('font')||'standard', panel_widths:{left:300, right:320}, preview_zoom:'fit'};
  if (q.get('nofields')) { delete S.theme; delete S.font_size; delete S.panel_widths; delete S.preview_zoom; }
  if (q.get('zoom')) S.preview_zoom = q.get('zoom')==='fit' ? 'fit' : parseInt(q.get('zoom'),10);
  if (q.get('pw')) { const a=q.get('pw').split(','); S.panel_widths={left:+a[0], right:+a[1]}; }
  /* sysdark=1：假装系统是深色（无头 Edge 的 prefers-color-scheme 不好控制）；window.__setSysDark(false) 模拟系统切回浅色并通知监听者 */
  window.__sysDark = q.get('sysdark')==='1'; window.__mqL = [];
  const realMM = window.matchMedia.bind(window);
  window.matchMedia = m => /prefers-color-scheme:\s*dark/.test(m) ? ({get matches(){ return window.__sysDark; }, media:m, addEventListener(t,f){ window.__mqL.push(f); }, removeEventListener(){}, addListener(f){ window.__mqL.push(f); }, removeListener(){}}) : realMM(m);
  window.__setSysDark = v => { window.__sysDark = v; window.__mqL.forEach(f => f({matches:v})); };
  /* nostorage=1：localStorage 不可用（隐私模式/被禁用），页面必须照常工作 */
  if (q.get('nostorage')) { try { Object.defineProperty(window, 'localStorage', {get(){ throw new Error('denied'); }}); } catch(e){} }
  let readonly = q.get('ro')==='1';
  const prov = q.get('prov') || 'ok';
  const claude = {ok:{available:true, state:'ready', reason:'已安装并已登录。', next_step:''},
    nologin:{available:false, state:'not_logged_in', reason:'已安装，但尚未登录。', next_step:'请在终端运行 claude，输入 /login 完成登录。'},
    missing:{available:false, state:'not_installed', reason:'未安装 Claude Code 命令行。', next_step:'请安装 Claude Code，并在终端运行 claude，输入 /login 完成登录。'}}[prov] || {};
  const providers = [
    Object.assign({id:'claude', name:'Claude Code 命令行', selectable:true}, claude),
    {id:'codex', name:'Codex 命令行', selectable:true, available:true, state:'ready', reason:'已安装并已登录。', next_step:'', experimental:true,
     experimental_notice:'该来源由外部贡献者接入，尚未在真实 Codex 与 Lightroom 上完成验收，请在测试照片上使用。', privacy_notice:'使用 Codex 时，选中照片的预览会发送至所选的 Codex 服务。'},
    {id:'api', name:'API 密钥', selectable:false, available:false, state:'unavailable', reason:'后续提供。', next_step:''}];
  window.__CALLS__ = []; window.__SAVED__ = [];
  const rec = (n, a) => { window.__CALLS__.push([n].concat(Array.prototype.slice.call(a||[]))); };
  const full = () => Object.assign({}, S, {});
  const A = {
    send: ()=>Promise.resolve({ok:true}), stop(){}, reset(){}, answer(){}, undo(){}, restore_original(){},
    status: ()=>Promise.resolve({state:'connected', text:'Lightroom 已连接', hint:'', photo:{id:'P', name:'DSC08238.ARW'}}),
    preview_state: ()=>Promise.resolve(({
      ok: {type:'preview', state:'ok', photo:{id:'P', name:'DSC08238.ARW', camera:'Sony ILCE-7CM2', iso:'ISO 100', aperture:'ƒ / 8.0', shutter:'1/800 秒', focal:'20 mm', format:'RAW', size:'1600 × 1000', captured:'2026-11-01 14:25'},
           initial:{url: q.get('shape')==='portrait' ? '/img/pi.jpg' : '/img/initial.jpg', w: q.get('shape')==='portrait' ? 1000 : 1600, h: q.get('shape')==='portrait' ? 1500 : 1000, version:'v0'},
           current:{url: q.get('shape')==='portrait' ? '/img/pi.jpg' : '/img/adjusted.jpg', w: q.get('shape')==='portrait' ? 1000 : 1600, h: q.get('shape')==='portrait' ? 1500 : 1000, version:'v1'}, same:false, edge:1600},
      error: {type:'preview', state:'error', message:'无法读取预览：请确认 Lightroom 已打开并选中了照片'},
      loading: {type:'preview', state:'loading', message:'正在读取预览', photo:{id:'P', name:'DSC08238.ARW'}}
    })[q.get('pv')] || {type:'preview', state:'none', message:'Lightroom 中未选中照片'}), set_preview_edge: ()=>Promise.resolve({ok:true}),
    autolaunch_state: ()=>Promise.resolve({state:'idle', message:''}),
    get_settings: ()=>(q.get('delay') ? new Promise(r=>setTimeout(r, 1500)) : Promise.resolve()).then(()=>({settings: full(), readonly, lightroom_detected:q.get('lrnone')?'':'C:\\Program Files\\Adobe\\Lightroom.exe', providers, current_provider:'claude', edges:[768,1024,1536,2048],
      about:{app_version:'1.3.0', lightroom_version:'15.0.0', plugin_version:'1.3.0', data_dir:'~/LrMcp', project_url:'https://github.com/Denvolatos/lightroom-mcp-latos-hue'}})),
    save_settings: (c, create)=>{ rec('save_settings', [c]); window.__SAVED__.push(c);
      if (c.base_folder && c.base_folder.indexOf('Windows')>=0) return Promise.resolve({ok:false, errors:{base_folder:'不能使用系统或程序目录，请选择其他位置。'}, needs_create:false});
      if (c.base_folder && c.base_folder.indexOf('新建')>=0 && !create) return Promise.resolve({ok:false, errors:{base_folder:'该文件夹尚不存在。'}, needs_create:true});
      Object.assign(S, c); delete S.lightroom_path_choice; return Promise.resolve({ok:true, errors:{}, settings:full()}); },
    choose_folder: ()=>Promise.resolve({ok:true, path:'D:\\修图素材'}), check_folder: p=>Promise.resolve(p.indexOf('Windows')>=0 ? {ok:false, message:'不能使用系统或程序目录，请选择其他位置。'} : {ok:true, exists:p.indexOf('新建')<0}),
    choose_lightroom_path: ()=>Promise.resolve({ok:true, path:'D:\\Adobe\\Lightroom Classic\\Lightroom.exe'}),
    set_readonly: on=>{ rec('set_readonly',[on]); if (q.get('rofail')) return Promise.resolve({ok:false, readonly, message:'没能切换只读模式：无法写入标记文件。'});
      readonly = !!on; return Promise.resolve({ok:true, readonly, message: readonly?'只读模式已开启。':'只读模式已关闭。'}); },
    clear_cache: ()=>{ rec('clear_cache'); if (q.get('cachefail')==='throw') return Promise.reject(new Error('boom'));
      if (q.get('cachefail')) return Promise.resolve({ok:false, message:'清理缓存失败：文件正在使用。'});
      return Promise.resolve({ok:true, freed_text:'12.5 MB', items:[{name:'缩略图', bytes:10000000},{name:'预览', bytes:3100000}], message:'已清理缓存，释放 12.5 MB。'}); },
    make_diagnostics: ()=>{ rec('make_diagnostics'); if (q.get('diag')==='cancel') return Promise.resolve({ok:false, cancelled:true});
      if (q.get('diag')==='fail') return Promise.resolve({ok:false, message:'生成诊断包失败：无法写入目标位置。'});
      return Promise.resolve({ok:true, path:'D:\\示例\\latoshue-diagnostics.zip', bytes:20480, message:'诊断包已生成。'}); },
    reset_settings: ()=>{ rec('reset_settings'); Object.assign(S, {confirm_default:true, ai_use_notes:true, preview_edge:1024, auto_launch_lightroom:false, check_updates:true, theme:'system', font_size:'standard', panel_widths:{left:300,right:320}, preview_zoom:'fit'});
      return Promise.resolve({ok:true, message:'已恢复默认设置，照片库位置和 AI 来源保持不变。'}); },
    about_info: ()=>{ rec('about_info'); if (q.get('noabout')) return Promise.reject(new Error('x'));
      return Promise.resolve({name:'Latos Hue 修图助手', version:'1.3.0', plugin_version:'1.3.0', license:'AGPL-3.0-only', homepage:'https://github.com/Denvolatos/lightroom-mcp-latos-hue',
        authors:[{name:'Denvolatos', role:'发起与主要开发', key:'denvolatos', url:'https://github.com/Denvolatos'},{name:'Galio1991', role:'共同开发', key:'galio1991', url:'https://github.com/Galio1991'}],
        disclaimer:'本软件不含任何 Adobe 软件，也不是 Adobe 官方产品。', tagline:'让 AI 帮你在一个窗口里挑片、修图、导出'}); },
    open_link: k=>{ rec('open_link',[k]); if (q.get('linkfail')==='msg') return Promise.resolve({ok:false, message:'无法打开：系统没有默认浏览器。'}); if (q.get('linkfail')) return Promise.resolve({ok:false}); return Promise.resolve({ok:true, message:''}); },
    update_state: ()=>Promise.resolve({state:'idle', latest:'', enabled:true}),
    wizard_state: ()=>Promise.resolve({wizard_done:true, mark_done:false, auto_open:false, ready:true, checking:false, items:[
      {id:'folder', title:'照片工作文件夹', state:'ready', text:'D:\\示例\\照片库', hint:'', action:'', action_label:''},
      {id:'lightroom', title:'Lightroom', state:'todo', text:'已找到 Lightroom 程序，但它还没有打开。', hint:'请先打开 Lightroom。', action:'', action_label:''},
      {id:'plugin', title:'Lightroom 插件', state:'wait', text:'等待 Lightroom。', hint:'', action:'', action_label:''}]}),
    wizard_done: ()=>Promise.resolve({ok:true}),
    import_state: ()=>Promise.resolve({stage:'idle'}),
    selection_state: ()=>Promise.resolve(q.get('sel') ? {count:2, photos:[{id:'A', name:'a.ARW'},{id:'B', name:'b.ARW'}], active_id:'A'} : {count:0, photos:[], active_id:null}),
    lib_presets: ()=>Promise.resolve({ok:true, max:200, presets:[{id:'p-000000000001', name:'示例预设一', note:'示例备注', groups:['色调','色彩'], count:14, modified:'2026-11-03 20:00:00', fav:true}]}),
    lib_notes: ()=>Promise.resolve({ok:true, notes:[{id:'n-000000000001', title:'示例经验一：天空发灰', scene:'示例场景', tags:['风光'], body:'示例正文', use_in_chat:true, fav:true, modified:'2026-11-03 20:00:00'}], tags:['风光'], max:300, context:{used:1, eligible:1, truncated:false}}),
    lib_favs: ()=>Promise.resolve({ok:true, total:1, photo_fav:false, groups:{preset:[{type:'preset', key:'示例预设一', label:'示例预设一'}], lr_preset:[], note:[], photo:[]}}),
    lib_lr_presets: ()=>Promise.resolve({ok:true, hidden_masks:0, note:'共 1 个预设', groups:[{folder:'示例分组', presets:[{id:'11111111-aaaa', name:'示例 Lightroom 预设', masks:false, key:'示例分组/示例 Lightroom 预设', fav:false}]}]}),
    check_update_now: ()=>{ rec('check_update_now'); return Promise.resolve({state:'latest', latest:'1.3.0', enabled:true}); },
    export_dialog_state: ()=>Promise.resolve({stage:'idle', options:{format:'jpeg', size:2048, quality:92, bit_depth:16, metadata:'minimal'}, connected:true,
      photo:{name:'DSC08206.ARW', camera:'Sony ILCE-7M3', format:'RAW', size:'6000 × 4000', iso:100}, folder:'D:\\示例\\导出', folder_message:'', can_export:true, reason:''}),
  };
  window.pywebview = {api: new Proxy(A, {get: (t, k) => (k in t) ? t[k] : (() => Promise.resolve({}))})};
})();
</script>"""

# 页面里的小断言工具：window.__bad.push('…')；window.__finish(name) 把结果写进 <pre id="chk">
HELPERS = r"""<script>
window.__bad = []; (function(){ const st = document.createElement('style'); st.textContent = '*,*::before,*::after{transition:none!important;animation:none!important}'; document.head.appendChild(st); })();
window.wait = ms => new Promise(r => setTimeout(r, ms));
window.ok = (c, m) => { if (!c) window.__bad.push(m); };
window.rgb = c => { const m = String(c).match(/[\d.]+/g) || []; return m.slice(0,3).map(Number); };
window.lum = c => { const [r,g,b] = rgb(c).map(v => { v/=255; return v<=0.03928 ? v/12.92 : Math.pow((v+0.055)/1.055, 2.4); }); return 0.2126*r+0.7152*g+0.0722*b; };
window.contrast = (a, b) => { const x = lum(a), y = lum(b); return (Math.max(x,y)+0.05)/(Math.min(x,y)+0.05); };
/* 元素的“实际底色”：从元素往上叠加半透明背景，直到遇到不透明的，最后叠在 body 底色上（渐变背景图不计，按底色算） */
window.effBg = el => { const layers = []; let opaque = false;
  for (let e = el; e && e.nodeType === 1 && !opaque; e = e.parentElement) { const m = (getComputedStyle(e).backgroundColor.match(/[\d.]+/g) || []).map(Number); if (m.length < 3) continue;
    const a = m.length > 3 ? m[3] : 1; if (a > 0) layers.push([m[0], m[1], m[2], a]); if (a >= 1) opaque = true; }
  let base = opaque ? layers.pop().slice(0, 3) : rgb(getComputedStyle(document.body).backgroundColor);
  layers.reverse().forEach(l => { base = [0,1,2].map(i => Math.round(l[i] * l[3] + base[i] * (1 - l[3]))); });
  return 'rgb(' + base.join(',') + ')'; };
window.pointer = (el, type, x, y, extra) => el.dispatchEvent(new PointerEvent(type, Object.assign({bubbles:true, cancelable:true, clientX:x, clientY:y, pointerId:1, pointerType:'mouse', isPrimary:true, button:0, buttons:type==='pointerup'?0:1}, extra||{})));
window.__finish = (name, extra) => { const pre = document.createElement('pre'); pre.id = 'chk'; pre.style.cssText = 'position:fixed;left:-9999px;top:0';
  pre.textContent = 'CHK[' + name + ']:' + (window.__bad.length ? window.__bad.join(' | ') : 'OK') + (extra ? ' ' + extra : ''); document.body.appendChild(pre); };
window.addEventListener('error', e => window.__bad.push('脚本错误 ' + e.message));
</script>"""


def build_page(tail: str) -> bytes:
    html = WEB.read_text(encoding="utf-8")
    html = inject_stub(html, FAKE_API + HELPERS).replace("</body>", "<script>window.dispatchEvent(new Event('pywebviewready'));</script>" + tail + "</body>")
    return html.encode("utf-8")


class Server:
    def __init__(self, page: bytes, extra: dict | None = None):
        """extra: {"/img/a.jpg": (bytes, "image/jpeg")} 额外的静态响应（测试图片等）。"""
        extra = extra or {}

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if serve_static(self):
                    return
                hit = extra.get(self.path.split("?")[0])
                if hit:
                    self.send_response(200)
                    self.send_header("Content-Type", hit[1])
                    self.send_header("Content-Length", str(len(hit[0])))
                    self.end_headers()
                    self.wfile.write(hit[0])
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(page)))
                self.end_headers()
                self.wfile.write(page)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}/"

    def close(self):
        self.httpd.shutdown()


def edge(url: str, w: int, h: int, shot: Path | None = None, dump: bool = False, dark: bool = False, budget: int = 6000) -> str:
    """截图（shot）或返回 --dump-dom 的文本。dark=True 时让浏览器的 prefers-color-scheme 为 dark（用来测“跟随系统”）。"""
    cmd = [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--virtual-time-budget={budget}"]
    if dark:
        cmd.append("--blink-settings=preferredColorScheme=1")
    if dump:
        cmd += [f"--window-size={w + 24},{h + 24}", "--dump-dom", url]        # --dump-dom 的窗口比截图的小一圈，多给 24 像素
    else:
        cmd += [f"--window-size={w},{h}", f"--screenshot={shot}", url]
    r = subprocess.run(cmd, check=True, timeout=120, capture_output=True)
    return r.stdout.decode("utf-8", "replace") if dump else ""


def result(dom: str) -> str:
    m = re.search(r'<pre id="chk"[^>]*>([^<]*)', dom)
    return m.group(1).replace("&amp;", "&").replace("&gt;", ">").replace("&lt;", "<") if m else "没有检查结果"


def run_jobs(server: Server, jobs, out: Path) -> int:
    """jobs: (名称, 查询串, 宽, 高, 是否深色系统, 是否截图)。检查 CHK 结果；返回退出码。"""
    failed = 0
    for name, query, w, h, dark, shot in jobs:
        url = f"{server.base}?{query}"
        dom = edge(url, w, h, dump=True, dark=dark)
        res = result(dom)
        if not res.endswith(":OK") and ":OK " not in res:
            failed += 1
        print(name, res)
        if shot:
            edge(url, w, h, shot=out / f"{name}.png", dark=dark)
    return 1 if failed else 0


def dumps(o) -> str:
    return json.dumps(o, ensure_ascii=False)


def sample_jpeg(w: int, h: int, warm: bool = False) -> bytes:
    """测试用的渐变图（不是真实照片）：带网格线，方便肉眼确认缩放和平移。"""
    import io

    from PIL import Image, ImageDraw
    im = Image.new("RGB", (w, h))
    px = im.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (int(40 + 180 * x / w) + (25 if warm else 0), int(90 + 100 * y / h), int(200 - 120 * x / w)) if True else (0, 0, 0)
    d = ImageDraw.Draw(im)
    for gx in range(0, w, 100):
        d.line([(gx, 0), (gx, h)], fill=(255, 255, 255), width=1)
    for gy in range(0, h, 100):
        d.line([(0, gy), (w, gy)], fill=(255, 255, 255), width=1)
    d.rectangle([w // 2 - 40, h // 2 - 40, w // 2 + 40, h // 2 + 40], outline=(255, 220, 0), width=4)
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue()
