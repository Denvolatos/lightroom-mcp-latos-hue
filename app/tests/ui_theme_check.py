# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""主题 / 字号 / 风格自查（1.3.0；无窗口、无 Lightroom、不属于 pytest）。
覆盖：浅色、深色、跟随系统（系统浅/深）、设置缺字段、localStorage 缓存先于设置读回、4 档字号（根字号与不溢出）、
文字对比度、预览区始终深色、CSS 里没有写死的颜色。有问题退出码为 1。
用法：python app/tests/ui_theme_check.py <输出目录>
"""
import re
import sys
from pathlib import Path

from ui_common import Server, build_page, run_jobs

CSS = Path(__file__).resolve().parent.parent / "web" / "css" / "app.css"

TAIL = r"""<script>
(async()=>{
  const q = new URLSearchParams(location.search), t = q.get('t');
  await wait(500);
  const root = document.documentElement, cs = getComputedStyle(root), body = getComputedStyle(document.body);
  const W = root.clientWidth;
  if (t === 'cache') {
    /* 第一次进来：写缓存后刷新；第二次进来设置还没读回（delay），此时页面应已用缓存的深色 */
    if (!sessionStorage.getItem('step')) { localStorage.setItem('lh_theme', 'dark'); localStorage.setItem('lh_font_size', 'xlarge'); sessionStorage.setItem('step', '1'); location.reload(); return; }
    ok(root.dataset.theme === 'dark', '设置读回前应使用缓存的深色，实际 ' + root.dataset.theme);
    ok(getComputedStyle(root).fontSize === '20px', '设置读回前应使用缓存的特大字号，实际 ' + getComputedStyle(root).fontSize);
    await wait(2500);
    ok(root.dataset.theme === 'light', '设置读回后应以设置为准（浅色），实际 ' + root.dataset.theme);
    ok(getComputedStyle(root).fontSize === '16px', '设置读回后字号应为标准，实际 ' + getComputedStyle(root).fontSize);
    ok(localStorage.getItem('lh_theme') === 'light', '读回后应更新缓存');
    __finish(t); return;
  }
  if (t === 'flip') {
    ok(root.dataset.theme === 'dark', '系统深色时应为深色'); __setSysDark(false); await wait(100);
    ok(root.dataset.theme === 'light', '系统切回浅色后应跟着变浅色，实际 ' + root.dataset.theme);
    applyAppearance('dark', 'standard'); __setSysDark(true); __setSysDark(false); await wait(50);
    ok(root.dataset.theme === 'dark', '固定深色时不应被系统变化影响');
    applyAppearance('system', 'standard'); await wait(50);
    ok(root.dataset.theme === 'light', '改回跟随系统后应随系统（浅色）');
    __finish(t); return;
  }
  const want = {light:'light', dark:'dark'}[q.get('theme')];
  const sys = q.get('sysdark') === '1' ? 'dark' : 'light';
  const expectTheme = want || sys;        /* theme=system 或缺字段：跟随系统 */
  ok(root.dataset.theme === expectTheme, '主题应为 ' + expectTheme + '，实际 ' + root.dataset.theme);
  const bg = rgb(body.backgroundColor).join(',');
  ok(bg === (expectTheme === 'dark' ? '23,24,26' : '239,236,230'), '页面底色不对 ' + bg);
  const size = {small:14.4, standard:16, large:17.92, xlarge:20}[q.get('font') || 'standard'];
  ok(Math.abs(parseFloat(cs.fontSize) - size) < 0.05, '根字号应为 ' + size + ' 实际 ' + cs.fontSize);
  ok(document.documentElement.scrollWidth <= W + 1, '页面横向溢出 ' + document.documentElement.scrollWidth + '>' + W);
  /* 对比度 */
  const panel = getComputedStyle(document.querySelector('.col.left')).backgroundColor;
  ok(contrast(body.color, bg_(body.backgroundColor)) >= 7, '正文对比度不足');
  const mut = getComputedStyle(document.querySelector('.status')).color;
  ok(contrast(mut, panel) >= (expectTheme === 'dark' ? 4.5 : 4.0), '次要文字对比度不足 ' + contrast(mut, panel).toFixed(2));
  const pb = getComputedStyle(document.querySelector('#send')), onacc = contrast(pb.color, pb.backgroundColor);
  ok(onacc >= 4.0, '强调色按钮文字对比度不足 ' + onacc.toFixed(2));
  /* 顶栏与三栏的底色互相区分 */
  ok(rgb(panel).join() !== rgb(body.backgroundColor).join(), '面板与页面底色相同');
  /* 预览区始终深色 */
  const fr = document.querySelector('.frame'); const sceneBg = fr ? getComputedStyle(fr).backgroundColor : null;
  if (sceneBg) ok(lum(sceneBg) < 0.05, '预览区应始终为深色 ' + sceneBg);
  /* 变量：按钮圆角 10px */
  ok(getComputedStyle(document.querySelector('.btn')).borderRadius === '10px', '按钮圆角应为 10px');
  __finish(t || 'main', 'theme=' + root.dataset.theme + ' font=' + cs.fontSize + ' contrast(accent)=' + onacc.toFixed(2) + ' ' + pb.color + ' on ' + pb.backgroundColor);
  function bg_(c){ return c; }
})();
</script>"""


def css_hardcoded_colors() -> list[str]:
    """app.css 里除“变量定义块”和演示用示例画面外，不允许出现写死的颜色。"""
    text = CSS.read_text(encoding="utf-8")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r":root\s*\{.*?\n\}", "", text, flags=re.S)                 # 变量定义块（以行首 } 结束）
    text = re.sub(r':root\[data-theme="dark"\]\s*\{.*?\n\}', "", text, flags=re.S)
    text = re.sub(r"\.scene \{.*?\}", "", text, flags=re.S)                      # 仅演示用的示例画面
    return re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|hsla?\([^)]*\)", text)


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    bad = css_hardcoded_colors()
    print("CSS 写死颜色:", "OK" if not bad else "有 " + ", ".join(bad[:8]))
    srv = Server(build_page(TAIL))
    try:
        jobs = []
        for theme in ("light", "dark"):
            jobs.append((f"theme_{theme}_1440", f"theme={theme}&t=main", 1440, 900, False, True))
        jobs += [
            ("theme_system_light", "theme=system&t=main", 1100, 700, False, False),
            ("theme_system_dark", "theme=system&t=main&sysdark=1", 1100, 700, False, True),
            ("theme_system_flip", "theme=system&t=flip&sysdark=1", 1100, 700, False, False),
            ("theme_missing_fields_dark_system", "nofields=1&t=main&sysdark=1", 1100, 700, False, False),
            ("theme_missing_fields_light_system", "nofields=1&t=main", 1100, 700, False, False),
            ("theme_cache_first_paint", "theme=light&font=standard&delay=1&t=cache", 1100, 700, False, False),
        ]
        for font in ("small", "standard", "large", "xlarge"):
            for theme in ("light", "dark"):
                for w in (800, 1100, 1440):
                    jobs.append((f"font_{font}_{theme}_{w}", f"theme={theme}&font={font}&t=main", w, max(560, round(w * .64)), False, w == 1100 and theme == "light"))
        code = run_jobs(srv, jobs, out)
    finally:
        srv.close()
    return 1 if (bad or code) else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
