# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""设置对话框界面自查（无窗口、无 Lightroom、不调用模型，不属于 pytest）。
临时本机静态服务加载 index.html（注入假的 pywebview.api），用无头 Edge 截图各场景。截图不含个人信息（路径用示例值）。
用法：python app/tests/ui_settings_check.py <截图输出目录>
"""
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
WEB = Path(__file__).resolve().parent.parent / "web" / "index.html"

STUB = """<script>
(function(){
  const scen = new URLSearchParams(location.search).get('s') || 'main';
  const claude = {
    ok: {available:true, state:'ready', reason:'已安装并已登录。', next_step:''},
    nologin: {available:false, state:'not_logged_in', reason:'已安装，但尚未登录。', next_step:'请在终端运行 claude，输入 /login 完成登录。'},
    missing: {available:false, state:'not_installed', reason:'未安装 Claude Code 命令行。', next_step:'请安装 Claude Code，并在终端运行 claude，输入 /login 完成登录。'}
  }[scen === 'nologin' ? 'nologin' : scen === 'missing' ? 'missing' : 'ok'];
  const providers = [
    Object.assign({id:'claude', name:'Claude Code 命令行', selectable:true}, claude),
    {id:'codex', name:'Codex 命令行', available:true, state:'ready', reason:'已安装并已登录。', next_step:'', selectable:true, experimental:true,
     experimental_notice:'该来源由外部贡献者接入，尚未在真实 Codex 与 Lightroom 上完成验收，请在测试照片上使用。',
     privacy_notice:'使用 Codex 时，选中照片的预览会发送至所选的 Codex 服务。'},
    {id:'api', name:'API 密钥', available:false, state:'unavailable', reason:'API 密钥（兼容 OpenAI 接口的各家，含 DeepSeek 等）——后续提供。', next_step:'', selectable:false}];
  const settings = {schema:1, base_folder:'C:\\\\Users\\\\示例用户\\\\Pictures\\\\修图助手', provider:'claude', confirm_default:true, preview_edge:1024};
  window.__CALLS__ = [];
  window.pywebview = {api: {
    send: ()=>Promise.resolve({ok:true}), stop(){}, reset(){}, answer(){}, undo(){}, restore_original(){},
    status: ()=>Promise.resolve({state:'connected', text:'Lightroom 已连接', hint:'', photo:{id:'P', name:'DSC08238.ARW'}}),
    preview_state: ()=>Promise.resolve({type:'preview', state:'none', message:'Lightroom 中未选中照片'}), set_preview_edge: ()=>Promise.resolve({ok:true}),
    autolaunch_state: ()=>Promise.resolve({state:'idle', message:''}),
    choose_lightroom_path: ()=>Promise.resolve({ok:true, path:'D:\\\\Adobe\\\\Lightroom Classic\\\\Lightroom.exe'}),
    get_settings: ()=>Promise.resolve({settings: Object.assign({auto_launch_lightroom: scen.indexOf('autolr')===0, lightroom_path: scen==='autolr_set'?'D:\\\\Adobe\\\\Lightroom Classic\\\\Lightroom.exe':''}, settings),
      lightroom_detected: scen==='autolr_none' ? '' : 'C:\\\\Program Files\\\\Adobe\\\\Adobe Lightroom Classic\\\\Lightroom.exe', providers, current_provider:'claude', edges:[768,1024,1536,2048],
      about:{app_version:'0.7.0', lightroom_version:'15.0.0', plugin_version:'0.15.0', data_dir:'~/LrMcp', project_url:'https://github.com/Denvolatos/lightroom-mcp-latos-hue'}}),
    choose_folder: ()=>Promise.resolve({ok:true, path:'D:\\\\修图素材'}),
    check_folder: p=>Promise.resolve(p.indexOf('Windows')>=0 ? {ok:false, message:'不能使用系统或程序目录，请选择其他位置。'} : {ok:true, exists:true}),
    save_settings: (c, create)=>{ window.__CALLS__.push(c);
      if (c.base_folder.indexOf('Windows')>=0) return Promise.resolve({ok:false, errors:{base_folder:'不能使用系统或程序目录，请选择其他位置。'}, needs_create:false});
      if (c.base_folder.indexOf('新建')>=0 && !create) return Promise.resolve({ok:false, errors:{base_folder:'该文件夹尚不存在。'}, needs_create:true});
      return Promise.resolve({ok:true, errors:{}, settings:Object.assign({}, settings, c)}); }
  }};
})();
</script>"""
TAIL = """<script>
window.dispatchEvent(new Event('pywebviewready'));
const q = new URLSearchParams(location.search).get('s') || 'main';
const wait = ms => new Promise(r => setTimeout(r, ms));
(async()=>{
  await wait(80);
  if (q.indexOf('lr_') === 0) {   /* 主界面顶栏：自动启动 Lightroom 的进度提示 */
    const st = {state:'connecting', text:'Lightroom 正在连接', hint:'正在连接 Lightroom，请稍候。'};
    window.onClaudeEvent({type:'status', ...st});
    const m = {lr_starting:['starting','正在启动 Lightroom…'], lr_notfound:['not_found','没找到 Lightroom，请手动打开。也可以在设置里选择 Lightroom 的位置。'],
               lr_timeout:['timeout','Lightroom 已经打开，但插件还没连上。请在 Lightroom 的 文件 → 增效工具管理器 里确认 LrMCP 显示“已安装并正在运行”，必要时点“重新载入增效工具”。']}[q];
    window.onClaudeEvent({type:'lr_launch', state:m[0], message:m[1]});
    return;
  }
  if (q === 'main') return;
  await openSettings(); await wait(80);
  if (q === 'error') { document.getElementById('s_folder').value = 'C:\\\\Windows\\\\System32'; document.getElementById('s_save').click(); }
  if (q === 'create') { document.getElementById('s_folder').value = 'D:\\\\新建图库'; document.getElementById('s_save').click(); }
  if (q === 'saved') { document.getElementById('s_save').click(); }
  if (q.indexOf('autolr') === 0) { /* 设置里的自动启动开关与位置 */ }
  if (q === 'autolr_set') { document.getElementById('s_lrpick').click(); }
  if (q === 'codex') { const sel = document.getElementById('s_provider'); sel.value = 'codex'; sel.onchange(); }
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
        for name in ("main", "ok", "nologin", "missing", "error", "create", "saved", "codex",
                     "autolr", "autolr_set", "autolr_none", "lr_starting", "lr_notfound", "lr_timeout"):
            target = out / f"settings_{name}.png"
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--window-size=1440,900",
                            "--virtual-time-budget=4000", f"--screenshot={target}",
                            f"http://127.0.0.1:{httpd.server_address[1]}/?s={name}"], check=True, timeout=60, capture_output=True)
            print("截图", target)
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
