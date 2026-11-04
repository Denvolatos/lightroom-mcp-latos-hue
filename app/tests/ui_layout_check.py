# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""窄窗口/多宽度布局自查（无窗口、无 Lightroom、不调用模型，不属于 pytest）。
临时本机静态服务加载 index.html（注入假的 pywebview.api，只含示例数据），用无头 Edge 按多个宽度截图主界面和几个对话框，
并用 --dump-dom 检查：页面不横向溢出、按钮文字没被挤成多行、对话框没超出窗口。
用法：python app/tests/ui_layout_check.py <截图输出目录>    （截图文件名 layout_<宽度>.png 等；有问题时退出码为 1）
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
  const settings = {schema:1, base_folder:'D:\\示例\\修图助手', provider:'claude', confirm_default:true, preview_edge:1024};
  const it = (id, title, state, text, hint, action, label)=>({id, title, state, text, hint:hint||'', action:action||'', action_label:label||''});
  const wz = {wizard_done:false, mark_done:false, message:'', ready:false, checking:false, auto_open:false, items:[
    it('folder','照片工作文件夹','todo','还没有选择照片工作文件夹。','导入的照片会复制到这个文件夹里，原片不会被移动或删除。请选一个空间够用的位置。','choose_folder','选择文件夹'),
    it('lightroom','Lightroom','todo','已找到 Lightroom 程序，但它还没有打开。','请先打开 Lightroom。设置里有“自动启动 Lightroom”开关，打开后，以后启动本软件时会自动在后台打开它。'),
    it('plugin','Lightroom 插件','wait','等待 Lightroom。','Lightroom 打开之后才能检查插件。'),
    it('ai','AI 助手','todo','Claude Code 命令行：已安装，但尚未登录。','请在终端运行 claude，输入 /login 完成登录。')]};
  const providers = [{id:'claude', name:'Claude Code 命令行', selectable:true, available:true, state:'ready', reason:'已安装并已登录。', next_step:''}];
  const expState = {stage:'idle', options:{format:'jpeg', size:2048, quality:92, bit_depth:16, metadata:'minimal'}, connected:true,
    photo:{name:'DSC08206.ARW', camera:'Sony ILCE-7M3', format:'RAW', size:'6000 × 4000', iso:100}, folder:'D:\\示例\\导出', folder_message:'', can_export:true, reason:''};
  window.pywebview = {api: {
    send: ()=>Promise.resolve({ok:true}), stop(){}, reset(){}, answer(){}, undo(){}, restore_original(){},
    status: ()=>Promise.resolve({state:'disconnected', text:'Lightroom 未连接', hint:'请确认 Lightroom 已打开，且已启用 LrMCP 插件（文件 > 增效工具管理器）。无需重启软件，打开后会自动连接。', photo:null}),
    preview_state: ()=>Promise.resolve({type:'preview', state:'none', message:'无法读取预览：请确认 Lightroom 已打开并选中了照片'}), set_preview_edge: ()=>Promise.resolve({ok:true}),
    autolaunch_state: ()=>Promise.resolve({state:'idle', message:''}),
    get_settings: ()=>Promise.resolve({settings, lightroom_detected:'', providers, current_provider:'claude', edges:[768,1024,1536,2048],
      about:{app_version:'0.17.1', lightroom_version:'15.0.0', plugin_version:'0.15.0', data_dir:'~/LrMcp', project_url:'https://github.com/Denvolatos/lightroom-mcp-latos-hue'}}),
    wizard_state: ()=>Promise.resolve(JSON.parse(JSON.stringify(wz))), wizard_done: ()=>Promise.resolve({ok:true}),
    wizard_pick_folder: ()=>Promise.resolve({ok:true}), wizard_pick_lightroom: ()=>Promise.resolve({ok:true}),
    import_state: ()=>Promise.resolve({stage:'idle'}), library_list: ()=>Promise.resolve({exists:false, total:0, groups:[], shown:0, more:0, base:'D:\\示例'}),
    choose_source_folder: ()=>Promise.resolve({ok:true, path:'F:\DCIM\100MSDCF'}), import_cancel: ()=>Promise.resolve({ok:true}), import_start: ()=>Promise.resolve({ok:true}),
    import_prepare: ()=>Promise.resolve({ok:true, can_start:true, errors:{}, found:{n:4, raw:2, jpeg:2, other:0, total_size:63000000, size_text:'60.08 MB', truncated:false, skipped_links:0},
      source:'F:\DCIM\100MSDCF', base:'D:\示例\修图助手', base_exists:true, base_is_default:false, category:'', target:'D:\示例\修图助手', free:200000000000, free_text:'186.26 GB', needed_text:'60.08 MB', shortfall:0, lr_connected:true}),
    export_state: ()=>Promise.resolve({stage:'idle'}), export_dialog_state: ()=>Promise.resolve(expState),
    choose_export_folder: ()=>Promise.resolve({ok:true, folder:'D:\\示例\\导出'}), export_close: ()=>Promise.resolve({ok:true}),
  }};
  const A = window.pywebview.api;      /* 没写到的接口一律返回空结果，避免启动流程半路中断 */
  window.pywebview.api = new Proxy(A, {get: (t, k) => (k in t) ? t[k] : (() => Promise.resolve({}))});
})();
</script>"""
TAIL = r"""<script>
window.dispatchEvent(new Event('pywebviewready'));
const q = new URLSearchParams(location.search).get('s') || 'main';
const wait = ms => new Promise(r => setTimeout(r, ms));
(async()=>{
  await wait(400);
  try {
    if (q === 'settings') await openSettings();
    if (q === 'wizard') openWizard();
    if (q === 'export') await openExport();
    if (q === 'import') { await startImport(); await wait(100); window.onClaudeEvent({type:'import_scan', state:'done', info:{}}); await wait(300); }
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
  document.querySelectorAll('.dialog').forEach(d => { const r = d.getBoundingClientRect(); if (r.width && (r.right > W + 1 || r.left < -1 || r.bottom > H + 1)) bad.push('对话框超出窗口'); });
  const pre = document.createElement('pre'); pre.id = 'chk'; pre.style.cssText = 'position:fixed;left:-9999px;top:0'; pre.textContent = 'CHK[' + W + 'x' + H + ' ' + q + ']:' + (bad.length ? bad.join(' | ') : 'OK') + errNote; document.body.appendChild(pre);
})();
</script>"""

MAIN_WIDTHS = (640, 800, 960, 1100, 1280, 1440, 1920)
DIALOGS = ("settings", "wizard", "export", "import")


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
    jobs = [("main", w, max(560, round(w * 0.64)), f"layout_{w}.png") for w in MAIN_WIDTHS]
    jobs += [(s, 1100, 690, f"layout_1100_{s}.png") for s in DIALOGS] + [(s, 800, 620, f"layout_800_{s}.png") for s in DIALOGS]
    failed = False
    try:
        for scene, w, h, name in jobs:
            common = [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--virtual-time-budget=4000"]
            url = f"{base}?s={scene}"
            subprocess.run(common + [f"--window-size={w},{h}", f"--screenshot={out / name}", url], check=True, timeout=60, capture_output=True)
            # --dump-dom 的窗口比截图的小一圈（窗口边框），多给 24 像素让两者页面尺寸一致
            dom = subprocess.run(common + [f"--window-size={w + 24},{h + 24}", "--dump-dom", url], check=True, timeout=60, capture_output=True).stdout.decode("utf-8", "replace")
            m = re.search(r'<pre id="chk"[^>]*>(CHK[^<]*)', dom)
            res = m.group(1) if m else "没有检查结果"
            failed |= not "OK" == res.split(":",1)[-1].strip()
            print(name, res)
    finally:
        httpd.shutdown()
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
