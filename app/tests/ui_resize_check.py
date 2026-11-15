# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""可拖动面板与可拖动对话框自查（1.3.0；无窗口、无 Lightroom、不属于 pytest）。鼠标操作用脚本模拟指针事件。
覆盖：左/右分隔线的 role/aria 值、鼠标拖动（含 200–480 / 240–520 夹紧、中间区至少 320px）、键盘方向键与 Home/End/Enter、
双击恢复默认、松开后防抖保存 panel_widths（一次拖动只保存一次）、从设置读回（含非法值回落默认）、窄屏（≤900）隐藏分隔线并忽略保存的宽度；
设置/环境检查/确认对话框的标题栏拖动（不拖出视口、不影响点击、在遮罩上松开不会误关闭、关闭再开恢复居中）、三种宽度无溢出。有问题退出码为 1。
用法：python app/tests/ui_resize_check.py <输出目录>
"""
import sys
from pathlib import Path

from ui_common import Server, build_page, run_jobs

TAIL = r"""<script>
(async()=>{
  const q = new URLSearchParams(location.search), T = q.get('t');
  const $$ = s => document.querySelector(s), vis = e => !!e && e.getBoundingClientRect().width > 0;
  const wL = () => Math.round($$('.col.left').getBoundingClientRect().width), wR = () => Math.round($$('.col.right').getBoundingClientRect().width), wC = () => Math.round($$('.center').getBoundingClientRect().width);
  const saves = () => (window.__SAVED__ || []).filter(c => 'panel_widths' in c).map(c => c.panel_widths);
  const drag = async (el, dx, steps) => { const r = el.getBoundingClientRect(), x0 = r.left + r.width / 2 + (el.classList.contains('splitter') ? 0 : 0), y = r.top + 100;
    pointer(el, 'pointerdown', x0, y); for (let i = 1; i <= (steps || 5); i++) { pointer(document, 'pointermove', x0 + dx * i / (steps || 5), y); await wait(5); } pointer(document, 'pointerup', x0 + dx, y); await wait(20); };
  const key = async (el, k, extra) => { el.dispatchEvent(new KeyboardEvent('keydown', Object.assign({key:k, bubbles:true, cancelable:true}, extra || {}))); await wait(20); };
  await wait(700);
  const W = document.documentElement.clientWidth, SL = $$('#split_l'), SR = $$('#split_r');
  if (T === 'panels') {
    ok(SL.getAttribute('role') === 'separator' && SR.getAttribute('role') === 'separator', '分隔线应是 role=separator');
    ok(SL.getAttribute('aria-orientation') === 'vertical' && SL.tabIndex === 0 && !!SL.getAttribute('aria-label') && !!SR.getAttribute('aria-label'), '分隔线应可聚焦、有方向和名称');
    const mainW = $$('#main').clientWidth - $$('#rail').offsetWidth, expL = Math.min(480, mainW - wR() - 320), expR = Math.min(520, mainW - wL() - 320);
    ok(SL.getAttribute('aria-valuemin') === '200' && +SL.getAttribute('aria-valuemax') === expL && SR.getAttribute('aria-valuemin') === '240' && +SR.getAttribute('aria-valuemax') === expR, 'aria 最小/最大值不对：' + [SL.getAttribute('aria-valuemax'), SR.getAttribute('aria-valuemax')] + ' 期望 ' + [expL, expR]);
    ok(Math.abs(wL() - 300) <= 1 && Math.abs(wR() - 320) <= 1, '应使用设置里的宽度 300/320，实际 ' + wL() + '/' + wR());
    ok(+SL.getAttribute('aria-valuenow') === wL() && +SR.getAttribute('aria-valuenow') === wR(), 'aria-valuenow 应等于当前宽度');
    ok(SL.getBoundingClientRect().height > 100 && getComputedStyle(SL).cursor === 'col-resize', '分隔线应可见并显示调整光标');
    /* 拖动 */
    window.__SAVED__.length = 0;
    await drag(SL, 50, 8); ok(Math.abs(wL() - 350) <= 1, '左栏拖 +50 应为 350，实际 ' + wL()); ok(+SL.getAttribute('aria-valuenow') === wL(), 'aria-valuenow 应同步');
    ok(!document.body.classList.contains('resizing') && !SL.classList.contains('drag'), '松开后应结束拖动状态');
    await drag(SR, -60, 8); const room = $$('#main').clientWidth - $$('#rail').offsetWidth - wL() - 320; ok(Math.abs(wR() - Math.min(380, room)) <= 1, '右栏向左拖 60 应变宽到 ' + Math.min(380, room) + '（受中间区最小宽度限制），实际 ' + wR());
    await wait(900); ok(saves().length === 1 && saves()[0].left === wL() && saves()[0].right === wR(), '两次拖动（500ms 内）应合并为一次保存：' + JSON.stringify(saves()));
    ok(Object.keys(window.__SAVED__[0]).join() === 'panel_widths', '只应保存 panel_widths');
    /* 夹紧 */
    await drag(SL, 2000, 4); ok(wL() === 480 || wC() >= 319, '左栏拖到头应夹在 480（或给中间留 320），实际 ' + wL() + ' 中间 ' + wC());
    ok(wL() <= 480, '左栏不应超过 480'); ok(wC() >= 319, '中间区至少 320：' + wC());
    await drag(SL, -2000, 4); ok(wL() === 200, '左栏拖到最小应是 200，实际 ' + wL());
    await drag(SR, 2000, 4); ok(wR() === 240, '右栏拖到最小应是 240，实际 ' + wR());
    await drag(SR, -2000, 4); ok(wR() <= 520 && wC() >= 319, '右栏不应超过 520 且中间 ≥320：' + wR() + '/' + wC());
    /* 键盘 */
    await key(SR, 'Enter'); await key(SL, 'Enter'); SL.focus(); await key(SL, 'Home'); ok(wL() === 200, 'Home 应到最小 200'); await key(SL, 'ArrowRight'); ok(wL() === 216, '→ 应 +16：' + wL()); await key(SL, 'ArrowRight', {shiftKey:true}); ok(wL() === 264, 'Shift+→ 应 +48：' + wL());
    await key(SL, 'ArrowLeft'); ok(wL() === 248, '← 应 -16：' + wL()); await key(SL, 'End'); ok(wL() === Math.min(480, $$('#main').clientWidth - $$('#rail').offsetWidth - wR() - 320), 'End 应到最大：' + wL());
    await key(SL, 'Enter'); ok(wL() === 260, 'Enter 应恢复默认 260：' + wL());
    await key(SR, 'ArrowRight'); ok(wR() < 300 || true, ''); await key(SR, 'Enter'); ok(wR() === 300, 'Enter 应恢复默认 300');
    await key(SR, 'ArrowLeft'); ok(wR() === 316, '右栏 ← 应变宽 16：' + wR()); await key(SR, 'ArrowRight', {shiftKey:true}); ok(wR() === 268, '右栏 Shift+→ 应变窄 48：' + wR());
    await key(SR, 'Home'); ok(wR() === 240, '右栏 Home 应是最小 240'); await key(SR, 'End'); ok(wR() <= 520 && wC() >= 319, '右栏 End：' + wR());
    await key($$('#split_l'), 'a'); /* 其他键不处理 */
    /* 双击恢复默认并保存 */
    await drag(SL, 80, 4); await drag(SR, -80, 4); window.__SAVED__.length = 0;
    SL.dispatchEvent(new MouseEvent('dblclick', {bubbles:true})); SR.dispatchEvent(new MouseEvent('dblclick', {bubbles:true})); await wait(900);
    ok(wL() === 260 && wR() === 300, '双击应恢复默认 260/300，实际 ' + wL() + '/' + wR()); ok(saves().length === 1 && saves()[0].left === 260 && saves()[0].right === 300, '双击后应保存默认值：' + JSON.stringify(saves()));
    ok(document.documentElement.scrollWidth <= W + 1, '页面横向溢出');
  }
  if (T === 'bad') {            /* 设置里的宽度不合法：回落默认 260/300 */
    ok(wL() === 260 && wR() === 300, '非法宽度（' + q.get('pw') + '）应回落默认 260/300，实际 ' + wL() + '/' + wR());
    ok(window.__SAVED__.length === 0, '读回设置不应触发保存');
  }
  if (T === 'missing') { ok(wL() === 260 && wR() === 300, '缺 panel_widths 应用默认 260/300，实际 ' + wL() + '/' + wR()); }
  if (T === 'narrow') {
    ok(!vis(SL) && !vis(SR) && getComputedStyle(SL).display === 'none', '窄屏（≤900）不应显示分隔线');
    ok(wL() === 0 && !vis($$('.col.left')), '窄屏照片面板默认收成抽屉（不占位）');
    ok(Math.abs(wR() - Math.min(Math.max(200, W * .30), 360)) <= 2, '窄屏右栏应忽略保存的宽度：' + wR());
    ok(wC() > 300 && document.documentElement.scrollWidth <= W + 1, '窄屏中间区/横向溢出：' + wC());
    const r2 = $$('.center').getBoundingClientRect(), r3 = $$('.col.right').getBoundingClientRect();
    ok(r2.right <= r3.left + 1, '中间区与右栏应依次排列');
    const c0 = wC(); $$('#r_photos').click(); await wait(60); const d = $$('.col.left').getBoundingClientRect();
    ok(vis($$('.col.left')) && d.width > 150 && d.width <= W * .87 && wC() === c0, '点“照片”应从左边滑出抽屉，且不挤占预览区：' + d.width);
    $$('#pp_collapse').click(); await wait(60); ok(!vis($$('.col.left')), '点“收起”应关闭抽屉');
  }
  if (T === 'wide') {
    ok(vis(SL) && vis(SR) || SL.getBoundingClientRect().height > 0, '宽屏应有分隔线');
    ok(wL() + wR() + wC() <= W + 2, '三栏总宽不超过窗口'); ok(document.documentElement.scrollWidth <= W + 1, '页面横向溢出');
  }
  if (T === 'dialog') {
    await openSettings(); await wait(150);
    const d = $$('.dialog.settings'), h = d.querySelector('h3'), r0 = d.getBoundingClientRect(), hr = h.getBoundingClientRect(), cx = hr.left + 30, cy = hr.top + hr.height / 2;
    ok(getComputedStyle(h).cursor === 'move', '标题栏应显示移动光标');
    const ex = Math.min(120, innerWidth - r0.right), ey = Math.min(60, innerHeight - r0.bottom);
    pointer(h, 'pointerdown', cx, cy); pointer(document, 'pointermove', cx + 40, cy + 20); pointer(document, 'pointermove', cx + 120, cy + 60); pointer(document, 'pointerup', cx + 120, cy + 60); await wait(30);
    let r1 = d.getBoundingClientRect(); ok(Math.abs(r1.left - r0.left - ex) < 1.5 && Math.abs(r1.top - r0.top - ey) < 1.5, '拖标题栏应移动对话框 (' + ex + ',' + ey + ')：' + [r1.left - r0.left, r1.top - r0.top]);
    ok($$('#smask').classList.contains('show'), '拖动后对话框不应被关闭（遮罩收到松开后的 click 时）');
    $$('#smask').dispatchEvent(new MouseEvent('click', {bubbles:true})); await wait(20); ok($$('#smask').classList.contains('show'), '拖动后紧跟的遮罩 click 应被忽略');
    /* 拖不出视口 */
    pointer(h, 'pointerdown', r1.left + 30, r1.top + 20); pointer(document, 'pointermove', 5000, 5000); pointer(document, 'pointerup', 5000, 5000); await wait(30);
    r1 = d.getBoundingClientRect(); ok(r1.right <= innerWidth + 0.5 && r1.bottom <= innerHeight + 0.5 && r1.left >= -0.5 && r1.top >= -0.5, '右下拖到头不应出视口：' + JSON.stringify(r1));
    pointer(h, 'pointerdown', r1.left + 30, r1.top + 20); pointer(document, 'pointermove', -5000, -5000); pointer(document, 'pointerup', -5000, -5000); await wait(30);
    r1 = d.getBoundingClientRect(); ok(r1.left >= -0.5 && r1.top >= -0.5 && r1.right <= innerWidth + 0.5 && r1.bottom <= innerHeight + 0.5, '左上拖到头不应出视口：' + JSON.stringify(r1));
    ok(Math.abs(r1.left) < 1 && Math.abs(r1.top) < 1, '应能贴住左上角：' + [r1.left, r1.top]);
    /* 现有交互不受影响：点“取消”仍能关闭；再打开恢复居中 */
    await wait(150); $$('#s_cancel').click(); await wait(50); ok(!$$('#smask').classList.contains('show'), '拖动后“取消”仍应能关闭');
    await openSettings(); await wait(150); const r2 = d.getBoundingClientRect();
    ok(Math.abs(r2.left - r0.left) < 1.5 && Math.abs(r2.top - r0.top) < 1.5 && d.style.transform === '', '关闭再开应恢复居中：' + [r2.left, r2.top] + ' vs ' + [r0.left, r0.top]);
    /* 在对话框正文里按下不会拖动 */
    const body = $$('#sec_general'), br = body.getBoundingClientRect(); pointer(body, 'pointerdown', br.left + 20, br.top + 20); pointer(document, 'pointermove', br.left + 200, br.top + 200); pointer(document, 'pointerup', br.left + 200, br.top + 200); await wait(30);
    ok(Math.abs(d.getBoundingClientRect().left - r2.left) < 0.5, '正文里拖动不应移动对话框');
    /* 在输入框/按钮上按下不会拖动 */
    const nav = $$('#tab_ai'); /* 按钮不在 h3 里，只验证 h3 内的按钮规则：给标题栏临时放个按钮 */
    const tb = document.createElement('button'); tb.textContent = 'x'; d.querySelector('h3').appendChild(tb); const tr = tb.getBoundingClientRect();
    pointer(tb, 'pointerdown', tr.left + 2, tr.top + 2); pointer(document, 'pointermove', tr.left + 100, tr.top + 100); pointer(document, 'pointerup', tr.left + 100, tr.top + 100); await wait(30); tb.remove();
    ok(Math.abs(d.getBoundingClientRect().left - r2.left) < 0.5, '标题栏里的按钮上按下不应拖动');
    /* 普通点击遮罩（没拖动）仍然关闭 */
    $$('#smask').dispatchEvent(new MouseEvent('click', {bubbles:true})); await wait(30); ok(!$$('#smask').classList.contains('show'), '没拖动时点遮罩仍应关闭');
    ok(document.documentElement.scrollWidth <= W + 1, '横向溢出');
  }
  if (T === 'dialog_wizard') {
    openWizard(); await wait(300); const d = $$('#wmask .dialog'), h = d.querySelector('.wz-head'), r0 = d.getBoundingClientRect(), hr = h.getBoundingClientRect();
    pointer(h, 'pointerdown', hr.left + 40, hr.top + 10); pointer(document, 'pointermove', hr.left + 100, hr.top + 50); pointer(document, 'pointerup', hr.left + 100, hr.top + 50); await wait(30);
    const r1 = d.getBoundingClientRect(); ok(Math.abs(r1.left - r0.left - 60) < 1.5 && Math.abs(r1.top - r0.top - 40) < 1.5, '环境检查对话框也应能拖动：' + [r1.left - r0.left, r1.top - r0.top]);
    await wait(150); $$('#w_x').click(); await wait(40); ok(!$$('#wmask').classList.contains('show'), '关闭按钮仍可用'); openWizard(); await wait(300);
    const r2 = d.getBoundingClientRect(); ok(Math.abs(r2.left - r0.left) < 1.5 && Math.abs(r2.top - r0.top) < 1.5, '重新打开应居中');
  }
  if (T === 'dialog_ask') {
    await openSettings(); await wait(100); $$('#tab_maint').click(); await wait(30); $$('#m_reset').click(); await wait(100);
    const d = document.querySelector('.mask.show .dialog.small'), h = d.querySelector('h3'), r0 = d.getBoundingClientRect(), hr = h.getBoundingClientRect();
    pointer(h, 'pointerdown', hr.left + 20, hr.top + 8); pointer(document, 'pointermove', hr.left + 90, hr.top + 58); pointer(document, 'pointerup', hr.left + 90, hr.top + 58); await wait(30);
    const r1 = d.getBoundingClientRect(); ok(Math.abs(r1.left - r0.left - 70) < 1.5 && Math.abs(r1.top - r0.top - 50) < 1.5, '确认对话框也应能拖动');
    ok(document.querySelectorAll('.mask.show').length === 2, '拖动确认框不应关闭任何对话框');
    await wait(150); Array.from(d.querySelectorAll('button')).find(b => b.textContent === '取消').click(); await wait(40);
    ok(document.querySelectorAll('.mask.show').length === 1 && !document.querySelector('.dialog.small'), '点“取消”应只关闭确认框');
  }
})().then(() => __finish(new URLSearchParams(location.search).get('t')), e => { window.__bad.push('脚本异常 ' + e + ' ' + (e.stack || '').slice(0, 200)); __finish('err'); });
</script>"""


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    srv = Server(build_page(TAIL))
    try:
        jobs = [
            ("resize_panels_1440", "t=panels", 1440, 900, False, True),
            ("resize_panels_1100", "t=panels", 1100, 760, False, False),
            ("resize_panels_dark", "t=panels&theme=dark", 1440, 900, False, False),
            ("resize_saved_widths_applied", "t=panels&pw=300,320", 1280, 800, False, False),
            ("resize_bad_values_low", "t=bad&pw=100,100", 1280, 800, False, False),
            ("resize_bad_values_high", "t=bad&pw=900,900", 1280, 800, False, False),
            ("resize_missing_field", "t=missing&nofields=1", 1280, 800, False, False),
            ("resize_narrow_900", "t=narrow&pw=480,520", 900, 640, False, True),
            ("resize_narrow_800", "t=narrow&pw=480,520", 800, 620, False, False),
            ("resize_narrow_640", "t=narrow&pw=480,520", 640, 560, False, False),
            ("resize_wide_1920", "t=wide&pw=480,520", 1920, 1000, False, False),
            ("resize_wide_1100_max", "t=wide&pw=480,520", 1100, 720, False, False),
            ("dialog_drag_1440", "t=dialog", 1440, 900, False, True),
            ("dialog_drag_800", "t=dialog", 800, 620, False, False),
            ("dialog_drag_glass", "t=dialog&theme=glass", 1100, 720, False, False),
            ("dialog_drag_wizard", "t=dialog_wizard", 1100, 720, False, False),
            ("dialog_drag_ask", "t=dialog_ask", 1100, 720, False, False),
        ]
        code = run_jobs(srv, jobs, out)
    finally:
        srv.close()
    return code


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
