# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""主题 / 字号 / 风格自查（1.3.0；无窗口、无 Lightroom、不属于 pytest）。
三套主题：paper 浅色纸感、glass 夜蓝玻璃、dark 暗室，外加 system 跟随系统（系统浅色→paper，系统深色→dark）。
覆盖：三套主题的底色/圆角/强调色、跟随系统与监听系统变化、旧值 light 兼容为 paper、未知值回落 system、设置缺字段、
localStorage 缓存先于设置读回、4 档字号（根字号与不溢出）、文字对比度（正文≥4.5:1、次要文字≥3:1，半透明面板按叠加后的底色算）、
按钮/输入/表格/徽标/提示条/缩略图选中框等组件、预览区始终深色、玻璃主题的 backdrop-filter 与降级变量、CSS 里没有写死的颜色（三套都查）。
每套主题各截主界面 / 设置 / 关于一张。有问题退出码为 1。
用法：python app/tests/ui_theme_check.py <输出目录>
"""
import re
import sys
from pathlib import Path

from ui_common import Server, build_page, run_jobs

CSS = Path(__file__).resolve().parent.parent / "web" / "css" / "app.css"
THEMES = {  # 主题: (页面底色 rgb, 按钮圆角, 强调色 rgb)
    "paper": ("239,236,230", "10px", "31,138,130"),
    "glass": ("11,16,32", "12px", "123,140,255"),
    "dark": ("15,15,16", "6px", "232,163,61"),
}

TAIL = r"""<script>
(async()=>{
  const q = new URLSearchParams(location.search), t = q.get('t'), root = document.documentElement;
  const TH = %THEMES%;
  const $$ = s => document.querySelector(s);
  await wait(500);
  const W = root.clientWidth;
  if (t === 'cache') {
    /* 第一次进来：写缓存后刷新；第二次进来设置还没读回（delay），此时页面应已用缓存的主题和字号 */
    if (!sessionStorage.getItem('step')) { localStorage.setItem('lh_theme', 'glass'); localStorage.setItem('lh_font_size', 'xlarge'); sessionStorage.setItem('step', '1'); location.reload(); return; }
    ok(root.dataset.theme === 'glass', '设置读回前应使用缓存的主题，实际 ' + root.dataset.theme);
    ok(getComputedStyle(root).fontSize === '20px', '设置读回前应使用缓存的特大字号，实际 ' + getComputedStyle(root).fontSize);
    await wait(2500);
    ok(root.dataset.theme === 'paper', '设置读回后应以设置为准（paper），实际 ' + root.dataset.theme);
    ok(getComputedStyle(root).fontSize === '16px', '设置读回后字号应为标准，实际 ' + getComputedStyle(root).fontSize);
    ok(localStorage.getItem('lh_theme') === 'paper', '读回后应更新缓存');
    __finish(t); return;
  }
  if (t === 'legacy') {          /* 设置里是旧值 light：当作 paper；未知值回落 system */
    ok(root.dataset.theme === 'paper' && root.dataset.themePref === 'paper', 'light 应兼容成 paper，实际 ' + root.dataset.theme + '/' + root.dataset.themePref);
    ok(localStorage.getItem('lh_theme') === 'paper', '缓存里应存成 paper，实际 ' + localStorage.getItem('lh_theme'));
    applyAppearance('light', 'standard'); ok(root.dataset.theme === 'paper' && localStorage.getItem('lh_theme') === 'paper', 'applyAppearance(light) 应存成 paper');
    applyAppearance('purple', 'standard'); ok(root.dataset.themePref === 'system', '未知主题应回落 system，实际 ' + root.dataset.themePref);
    applyAppearance(undefined, 'huge'); ok(root.dataset.themePref === 'system' && root.dataset.fontSize === 'standard', '缺值应回落 system/standard');
    localStorage.setItem('lh_theme', 'light'); ok(themeNormalize(localStorage.getItem('lh_theme')) === 'paper', '缓存里的旧值 light 应读成 paper');
    __finish(t); return;
  }
  if (t === 'flip') {
    ok(root.dataset.theme === 'dark', '系统深色时应为 dark（暗室），实际 ' + root.dataset.theme);
    __setSysDark(false); await wait(100);
    ok(root.dataset.theme === 'paper', '系统切回浅色后应变 paper，实际 ' + root.dataset.theme);
    applyAppearance('glass', 'standard'); __setSysDark(true); __setSysDark(false); await wait(50);
    ok(root.dataset.theme === 'glass', '固定玻璃主题时不应被系统变化影响');
    applyAppearance('system', 'standard'); await wait(50);
    ok(root.dataset.theme === 'paper', '改回跟随系统后应随系统（浅色→paper）');
    __setSysDark(true); await wait(50); ok(root.dataset.theme === 'dark', '系统再变深色应为 dark');
    __finish(t); return;
  }
  if (t === 'settingsshot' || t === 'aboutshot') { await openSettings(t === 'aboutshot' ? 'about' : 'general'); await wait(250); }
  const want = q.get('theme'), known = ['paper', 'glass', 'dark'].indexOf(want) >= 0;
  const sysTheme = q.get('sysdark') === '1' ? 'dark' : 'paper';
  const expectTheme = known ? want : sysTheme;        /* system、缺字段、未知值：跟随系统 */
  ok(root.dataset.theme === expectTheme, '主题应为 ' + expectTheme + '，实际 ' + root.dataset.theme);
  ok(root.dataset.themePref === (known ? want : 'system'), 'data-theme-pref 不对：' + root.dataset.themePref);
  const [bgWant, radWant, accWant] = TH[expectTheme], body = getComputedStyle(document.body);
  ok(rgb(body.backgroundColor).join(',') === bgWant, '页面底色不对 ' + rgb(body.backgroundColor).join(','));
  const size = {small:14.4, standard:16, large:17.92, xlarge:20}[q.get('font') || 'standard'];
  ok(Math.abs(parseFloat(getComputedStyle(root).fontSize) - size) < 0.05, '根字号应为 ' + size + ' 实际 ' + getComputedStyle(root).fontSize);
  ok(document.documentElement.scrollWidth <= W + 1, '页面横向溢出 ' + document.documentElement.scrollWidth + '>' + W);
  ok(getComputedStyle($$('.btn')).borderRadius === radWant, '按钮圆角应为 ' + radWant + ' 实际 ' + getComputedStyle($$('.btn')).borderRadius);
  const pbS = getComputedStyle($$('#send'));
  ok(rgb(pbS.backgroundColor).join(',') === accWant, '主按钮应为该主题的强调色 ' + accWant + ' 实际 ' + rgb(pbS.backgroundColor).join(','));
  /* 预览区始终深色 */
  const fr = $$('.frame'); if (fr) ok(lum(getComputedStyle(fr).backgroundColor) < 0.06, '预览区应始终为深色 ' + getComputedStyle(fr).backgroundColor);
  /* 玻璃主题：用了 backdrop-filter；其他主题没有 */
  const bf = getComputedStyle($$('.topbar')).backdropFilter || '';
  if (expectTheme === 'glass') ok(bf.indexOf('blur') >= 0, '玻璃主题应使用 backdrop-filter 模糊，实际 ' + bf); else ok(bf === 'none' || bf === '', '非玻璃主题不应有模糊 ' + bf);
  /* 对比度：正文 >= 4.5，次要文字 >= 3；半透明面板按叠加后的底色算 */
  const probes = [];
  const add = (sel, min, what, bgSel) => { const e = $$(sel); if (!e) { probes.push('缺少 ' + sel); return; } const fg = getComputedStyle(e).color, bg = effBg(bgSel ? $$(bgSel) : e), c = contrast(fg, bg);
    if (c < min) probes.push(what + ' 对比度 ' + c.toFixed(2) + ' < ' + min + '（' + fg + ' 在 ' + bg + '）'); };
  add('.col.left .tab.on', 4.5, '标签页（选中）'); add('.col.left .tab:not(.on)', 3, '标签页（未选中）');
  add('.msg.ai', 4.5, '对话气泡'); add('.status', 3, '顶栏状态文字'); add('.brand', 4.5, '品牌名');
  add('#inp', 4.5, '输入框文字'); add('#send', 3, '主按钮文字'); add('.topbar .btn', 4.5, '普通按钮文字');
  add('th', 3, '表格表头'); add('.galscope', 3, '图库说明文字'); add('#swlabel', 3, '开关说明');
  const pr = document.createElement('div'); pr.id = 'probe'; pr.style.cssText = 'position:fixed;left:0;top:0;width:1px;height:1px;overflow:hidden';
  pr.innerHTML = '<div class="col" id="pp"><span class="badge" id="pbadge">徽标</span><span class="st-ok" id="pok">ok</span><span class="st-bad" id="pbad">bad</span><span class="st-wait" id="pwait">wait</span>'
    + '<span class="up" id="pup">up</span><span class="down" id="pdown">down</span><div class="msg err" id="perr">err</div><div class="ask" id="pask">ask</div><div class="ferr" id="pferr">ferr</div><div class="sub" id="psub">sub</div>'
    + '<div class="cell sel" id="psel"><div class="cname" id="pcname">name</div></div><div class="ghead"><span class="gn" id="pgn">g</span></div><button class="btn primary" id="pprim">主</button><div class="seg"><button class="on" id="pseg">on</button></div></div>';
  document.body.appendChild(pr);
  add('#pbadge', 3, '徽标'); add('#pok', 3, '成功色', '#pp'); add('#pbad', 3, '危险色', '#pp'); add('#pwait', 3, '等待色', '#pp'); add('#pup', 3, '上升色', '#pp'); add('#pdown', 3, '下降色', '#pp');
  add('#perr', 4.5, '错误气泡'); add('#pask', 4.5, '确认条'); add('#pferr', 3, '错误文字', '#pp'); add('#psub', 3, '说明文字', '#pp'); add('#pcname', 4.5, '缩略图名称（选中框）'); add('#pprim', 3, '主按钮');
  add('#pseg', 3, '分段按钮（选中）');
  const sel = getComputedStyle($$('#psel')); ok(rgb(sel.borderTopColor).join(',') === accWant, '缩略图选中框边框应是强调色 ' + sel.borderTopColor);
  probes.forEach(p => ok(false, p));
  if (t === 'settingsshot' || t === 'aboutshot') {
    const sub = $$('#smask .sub'), grp = $$('#smask .sgroup'); if (sub) { const c = contrast(getComputedStyle(sub).color, effBg(grp)); ok(c >= 3, '设置里说明文字对比度 ' + c.toFixed(2)); }
    const h4 = $$('#smask .sgroup h4'); if (h4) { const c = contrast(getComputedStyle(h4).color, effBg(grp)); ok(c >= 3, '卡片标题对比度 ' + c.toFixed(2)); }
    const dlg = $$('.dialog.settings'); ok(getComputedStyle(dlg).borderTopLeftRadius === ({paper:'16px', glass:'20px', dark:'10px'})[expectTheme], '对话框圆角不对 ' + getComputedStyle(dlg).borderTopLeftRadius);
    const on = $$('#snav .on'); if (on) { const c = contrast(getComputedStyle(on).color, effBg(on)); ok(c >= 4.5, '导航选中项对比度 ' + c.toFixed(2)); }
    const lk = $$('#ab_authors .linkbtn'); if (lk && t === 'aboutshot') { const c = contrast(getComputedStyle(lk).color, effBg(lk)); ok(c >= 4.5, '作者链接对比度 ' + c.toFixed(2)); }
    const sv = $$('#s_save'); { const c = contrast(getComputedStyle(sv).color, effBg(sv)); ok(c >= 3, '保存按钮对比度 ' + c.toFixed(2)); }
  }
  pr.remove();
  __finish(t || 'main', 'theme=' + root.dataset.theme + ' font=' + getComputedStyle(root).fontSize);
})();
</script>"""


def css_hardcoded_colors() -> list[str]:
    """app.css 里除“主题变量定义块（三套）”和演示用示例画面外，不允许出现写死的颜色。"""
    text = CSS.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r":root[^{]*\{.*?\n\}", "", text, flags=re.S)                  # 变量定义块（以行首 } 结束），含 @supports 里的降级块
    text = re.sub(r"\.scene \{.*?\}", "", text, flags=re.S)                      # 仅演示用的示例画面
    return re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)", text)


def css_theme_blocks() -> list[str]:
    text = CSS.read_text(encoding="utf-8")
    return sorted(set(re.findall(r':root\[data-theme="(\w+)"\]', text)))


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    bad = css_hardcoded_colors()
    print("CSS 写死颜色:", "OK" if not bad else "有 " + ", ".join(bad[:8]))
    blocks = css_theme_blocks()
    print("CSS 主题块:", blocks, "OK" if blocks == ["dark", "glass"] else "不对")
    tail = TAIL.replace("%THEMES%", "{" + ",".join(f"{k}:['{v[0]}','{v[1]}','{v[2]}']" for k, v in THEMES.items()) + "}")
    srv = Server(build_page(tail))
    try:
        jobs = []
        for th in THEMES:
            jobs.append((f"theme_{th}_main", f"theme={th}&t=main", 1440, 900, False, True))
            jobs.append((f"theme_{th}_settings", f"theme={th}&t=settingsshot", 1440, 900, False, True))
            jobs.append((f"theme_{th}_about", f"theme={th}&t=aboutshot", 1440, 900, False, True))
        jobs += [
            ("theme_system_paper", "theme=system&t=main", 1100, 700, False, False),
            ("theme_system_dark", "theme=system&t=main&sysdark=1", 1100, 700, False, False),
            ("theme_system_flip", "theme=system&t=flip&sysdark=1", 1100, 700, False, False),
            ("theme_missing_fields_dark_system", "nofields=1&t=main&sysdark=1", 1100, 700, False, False),
            ("theme_missing_fields_paper_system", "nofields=1&t=main", 1100, 700, False, False),
            ("theme_unknown_value_falls_back_to_system", "theme=purple&t=main", 1100, 700, False, False),
            ("theme_legacy_light_is_paper", "theme=light&t=legacy", 1100, 700, False, False),
            ("theme_cache_first_paint", "theme=paper&font=standard&delay=1&t=cache", 1100, 700, False, False),
        ]
        for font in ("small", "standard", "large", "xlarge"):
            for theme in THEMES:
                for w in (800, 1100, 1440):
                    jobs.append((f"font_{font}_{theme}_{w}", f"theme={theme}&font={font}&t=main", w, max(560, round(w * .64)), False, False))
        code = run_jobs(srv, jobs, out)
    finally:
        srv.close()
    return 1 if (bad or code or blocks != ["dark", "glass"]) else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
