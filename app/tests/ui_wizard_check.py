# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""环境检查向导界面自查（无窗口、无 Lightroom、不调用模型，不属于 pytest）。
临时本机静态服务加载 index.html（注入假的 pywebview.api），用无头 Edge 截图各状态。截图只含假数据（路径用示例值）。
用法：python app/tests/ui_wizard_check.py <截图输出目录>
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
  const scen = new URLSearchParams(location.search).get('s') || 'todo';
  const it = (id, title, state, text, hint, action, label)=>({id, title, state, text, hint:hint||'', action:action||'', action_label:label||''});
  const FOLDER_TODO = it('folder','照片工作文件夹','todo','还没有选择照片工作文件夹。','导入的照片会复制到这个文件夹里，原片不会被移动或删除。请选一个空间够用的位置。','choose_folder','选择文件夹');
  const FOLDER_OK = it('folder','照片工作文件夹','ready','已选择：D:\\\\示例\\\\修图助手');
  const LR_TODO = it('lightroom','Lightroom','todo','没有找到 Lightroom 程序，它也没有在运行。','如果已经安装，请点“选择 Lightroom 程序”，找到安装目录里的 Lightroom.exe；也可以直接手动打开 Lightroom。','choose_lightroom','选择 Lightroom 程序');
  const LR_OPEN = it('lightroom','Lightroom','todo','已找到 Lightroom 程序，但它还没有打开。','请先打开 Lightroom。设置里有“自动启动 Lightroom”开关，打开后，以后启动本软件时会自动在后台打开它。这里不会替你打开。');
  const LR_OK = it('lightroom','Lightroom','ready','Lightroom 正在运行。');
  const PL_WAIT = it('plugin','Lightroom 插件','wait','等待 Lightroom。','Lightroom 打开之后才能检查插件。');
  const PL_TODO = it('plugin','Lightroom 插件','todo','Lightroom 已经打开，但插件还没连上。','请在 Lightroom 的 文件 → 增效工具管理器 里确认 LrMCP 显示“已安装并正在运行”；如果不是，点“重新载入增效工具”，等几秒再点下面的“重新检查”。');
  const PL_OK = it('plugin','Lightroom 插件','ready','插件已连接（版本 0.15.0）。');
  const AI_TODO = it('ai','AI 助手','todo','Claude Code 命令行：已安装，但尚未登录。','请在终端运行 claude，输入 /login 完成登录。');
  const AI_OK = it('ai','AI 助手','ready','Claude Code 命令行：已安装并已登录。');
  const sets = {
    todo: {items:[FOLDER_TODO, LR_TODO, PL_WAIT, AI_TODO], ready:false, checking:false, auto_open:true},
    partial: {items:[FOLDER_OK, LR_OK, PL_TODO, AI_OK], ready:false, checking:false, auto_open:false},
    ready: {items:[FOLDER_OK, LR_OK, PL_OK, AI_OK], ready:true, checking:false, auto_open:false},
    checking: {items:[FOLDER_OK, LR_OPEN, PL_WAIT, AI_TODO], ready:false, checking:true, auto_open:false},
    narrow: {items:[FOLDER_TODO, LR_OPEN, PL_WAIT, AI_TODO], ready:false, checking:false, auto_open:false},
  };
  const base = scen === 'settings' ? sets.ready : (sets[scen] || sets.todo);
  const wz = Object.assign({wizard_done:false, mark_done:false, message: base.ready ? '都准备好了，可以开始修图。' : ''}, base);
  const claude = {available:true, state:'ready', reason:'已安装并已登录。', next_step:''};
  const providers = [Object.assign({id:'claude', name:'Claude Code 命令行', selectable:true}, claude)];
  const settings = {schema:1, base_folder:'D:\\\\示例\\\\修图助手', provider:'claude', confirm_default:true, preview_edge:1024};
  window.__CALLS__ = [];
  window.pywebview = {api: {
    send: ()=>Promise.resolve({ok:true}), stop(){}, reset(){}, answer(){}, undo(){}, restore_original(){},
    status: ()=>Promise.resolve({state:'connected', text:'Lightroom 已连接', hint:'', photo:{id:'P', name:'DSC08238.ARW'}}),
    preview_state: ()=>Promise.resolve({type:'preview', state:'none', message:'Lightroom 中未选中照片'}), set_preview_edge: ()=>Promise.resolve({ok:true}),
    autolaunch_state: ()=>Promise.resolve({state:'idle', message:''}),
    get_settings: ()=>Promise.resolve({settings, lightroom_detected:'', providers, current_provider:'claude', edges:[768,1024,1536,2048],
      about:{app_version:'0.14.0', lightroom_version:'15.0.0', plugin_version:'0.15.0', data_dir:'~/LrMcp', project_url:'https://github.com/Denvolatos/lightroom-mcp-win'}}),
    wizard_state: refresh=>{ window.__CALLS__.push('wizard_state:'+refresh); return Promise.resolve(JSON.parse(JSON.stringify(wz))); },
    wizard_done: f=>{ window.__CALLS__.push('wizard_done:'+f); return Promise.resolve({ok:true}); },
    wizard_pick_folder: ()=>Promise.resolve({ok:true}), wizard_pick_lightroom: ()=>Promise.resolve({ok:true}),
  }};
})();
</script>"""
TAIL = """<script>
window.dispatchEvent(new Event('pywebviewready'));
const q = new URLSearchParams(location.search).get('s') || 'todo';
const wait = ms => new Promise(r => setTimeout(r, ms));
(async()=>{
  await wait(300);
  if (q === 'settings') { await openSettings(); return; }
  if (q !== 'todo') openWizard();      /* todo 场景靠启动时自动弹出（auto_open 为真） */
})();
</script>"""

SCENES = (("todo", 1440, 900), ("partial", 1440, 900), ("ready", 1440, 900), ("checking", 1440, 900),
          ("narrow", 520, 800), ("settings", 1440, 900))


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
        for name, w, h in SCENES:
            target = out / f"wizard_{name}.png"
            subprocess.run([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars", f"--window-size={w},{h}",
                            "--virtual-time-budget=4000", f"--screenshot={target}",
                            f"http://127.0.0.1:{httpd.server_address[1]}/?s={name}"], check=True, timeout=60, capture_output=True)
            print("截图", target)
    finally:
        httpd.shutdown()


if __name__ == "__main__":
    main(Path(sys.argv[1]))
