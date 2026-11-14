# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""预览无级缩放自查（1.3.0；无窗口、无 Lightroom、不属于 pytest）。图片是脚本现生成的渐变测试图，不是真实照片。
覆盖：滑杆 10%–400%（min/max/step、夹紧）、预设“适合/50%/100%/200%”与按下状态、数字显示、两个预览窗同步缩放与平移、
Ctrl+滚轮以鼠标为中心缩放（不带 Ctrl 不处理）、双击在“适合”和 100% 之间切换、放大后拖动平移（含边界夹紧、适合时不可平移）、
preview_zoom 防抖保存（"fit" 或整数）、从设置读回（含非法值）、预览错误/加载中提示、窄屏不溢出、无障碍名称。有问题退出码为 1。
用法：python app/tests/ui_zoom_check.py <输出目录>
"""
import sys
from pathlib import Path

from ui_common import Server, build_page, run_jobs, sample_jpeg

TAIL = r"""<script>
(async()=>{
  const q = new URLSearchParams(location.search), T = q.get('t');
  const $$ = s => document.querySelector(s), vis = e => !!e && e.getBoundingClientRect().width > 0;
  const mat = el => new DOMMatrix(getComputedStyle(el).transform);
  const imgs = () => [$$('#fi .pimg'), $$('#fc .pimg')];
  const scales = () => imgs().map(i => +mat(i).a.toFixed(3)), pos = () => imgs().map(i => [mat(i).e, mat(i).f]);
  const frame = () => $$('#fc'), rectOf = f => f.getBoundingClientRect();
  const saves = () => (window.__SAVED__ || []).filter(c => 'preview_zoom' in c).map(c => c.preview_zoom);
  const btn = z => $$('#zoomctl .zp[data-z="' + z + '"]');
  const setRange = v => { const r = $$('#zoomrange'); r.value = String(v); r.dispatchEvent(new Event('input', {bubbles:true})); };
  await wait(900);
  const W = document.documentElement.clientWidth;
  if (T === 'ok') {
    ok(vis($$('#zoomctl')) && $$('#zoomctl').getAttribute('role') === 'group' && $$('#zoomctl').getAttribute('aria-label') === '预览缩放', '应有缩放控件组');
    ok(!$$('#zoom'), '旧的“适合窗口/100%”切换按钮应已取消');
    const r = $$('#zoomrange'); ok(r.min === '10' && r.max === '400' && r.step === '1' && r.type === 'range', '滑杆应是 10–400 step 1');
    ok((r.getAttribute('aria-label') || '').indexOf('缩放') >= 0, '滑杆应有名称');
    ['fit', '50', '100', '200'].forEach(z => ok(!!btn(z), '缺少预设按钮 ' + z)); ok(Array.from(document.querySelectorAll('#zoomctl .zp')).map(b => b.textContent).join(',') === '适合,50%,100%,200%', '预设按钮文字不对');
    ok(btn('fit').getAttribute('aria-pressed') === 'true' && btn('100').getAttribute('aria-pressed') === 'false', '初始应是“适合”按下');
    const f0 = scales(); ok(f0[0] === f0[1] && f0[0] > 0 && f0[0] < 1, '适合时两个预览窗缩放应相同且 <1：' + f0);
    ok($$('#zoomtxt').textContent.indexOf('适合') === 0 && /\d+%/.test($$('#zoomtxt').textContent), '数字显示应为“适合 · NN%”：' + $$('#zoomtxt').textContent);
    ok(Math.abs(+r.value - Math.round(f0[0] * 100)) <= 1, '适合时滑杆应指向当前实际比例 ' + r.value + ' vs ' + f0[0] * 100);
    /* 预设 */
    for (const [z, s] of [['50', .5], ['100', 1], ['200', 2]]) { btn(z).click(); await wait(60);
      ok(scales().every(x => x === s), '点 ' + z + '% 后两个预览窗都应是 ' + s + '：' + scales());
      ok($$('#zoomtxt').textContent === z + '%', '数字显示应为 ' + z + '%：' + $$('#zoomtxt').textContent);
      ok(btn(z).getAttribute('aria-pressed') === 'true' && btn('fit').getAttribute('aria-pressed') === 'false', z + '% 应为按下状态'); ok(+r.value === +z, '滑杆应同步 ' + r.value); }
    /* 滑杆 */
    setRange(37); await wait(40); ok(scales().every(x => x === .37) && $$('#zoomtxt').textContent === '37%', '滑杆 37 应得 37%：' + scales() + ' ' + $$('#zoomtxt').textContent);
    ok(['fit', '50', '100', '200'].every(z => btn(z).getAttribute('aria-pressed') === 'false'), '非预设值时预设都不应按下');
    setRange(400); await wait(40); ok(scales().every(x => x === 4), '400% 应放大 4 倍'); setRange(10); await wait(40); ok(scales().every(x => x === .1), '10% 应缩小到 0.1');
    setRange(1000); await wait(40); ok(scales().every(x => x === 4), '超过 400 应夹紧到 400：' + scales()); setRange(-5); await wait(40); ok(scales().every(x => x === .1), '低于 10 应夹紧到 10');
    btn('fit').click(); await wait(50); ok(scales()[0] === f0[0] && $$('#zoomtxt').textContent.indexOf('适合') === 0, '点“适合”应回到适合');
    /* 信息栏 */
    btn('200').click(); await wait(40); ok($$('#infobar').textContent.indexOf('200% 显示') >= 0, '信息栏应写出当前缩放：' + $$('#infobar').textContent);
    /* 保存防抖：连续改很多次只应保存最后一次 */
    window.__SAVED__.length = 0; for (let i = 20; i <= 60; i += 10) { setRange(i); await wait(30); } await wait(900);
    ok(saves().length === 1 && saves()[0] === 60, '防抖后应只保存最后一次 60，实际 ' + JSON.stringify(saves()));
    btn('fit').click(); await wait(900); ok(saves().slice(-1)[0] === 'fit', '“适合”应保存为 "fit"：' + JSON.stringify(saves()));
    btn('100').click(); await wait(900); ok(saves().slice(-1)[0] === 100 && typeof saves().slice(-1)[0] === 'number', '100% 应保存为整数 100');
  }
  if (T === 'wheel') {
    const f = frame(), r = rectOf(f), cx = r.left + r.width * 0.3, cy = r.top + r.height * 0.6;
    /* 先放大到 200%，平移一下，再测滚轮缩放时鼠标下的点不动 */
    btn('200').click(); await wait(50);
    const under = (img, x, y) => { const m = mat(img), s = m.a, rr = img.parentElement.getBoundingClientRect(); return [(x - rr.left - m.e) / s, (y - rr.top - m.f) / s]; };
    const p0 = under(imgs()[1], cx, cy);
    const ev0 = new WheelEvent('wheel', {ctrlKey:false, deltaY:-100, clientX:cx, clientY:cy, bubbles:true, cancelable:true}); f.dispatchEvent(ev0);
    ok(!ev0.defaultPrevented && scales().every(x => x === 2), '不带 Ctrl 的滚轮不应处理');
    const ev = new WheelEvent('wheel', {ctrlKey:true, deltaY:-100, clientX:cx, clientY:cy, bubbles:true, cancelable:true}); f.dispatchEvent(ev); await wait(50);
    ok(ev.defaultPrevented, 'Ctrl+滚轮应阻止页面自己的缩放');
    ok(scales().every(x => x > 2 && x < 2.4) && scales()[0] === scales()[1], '向上滚一格应放大约 10%：' + scales());
    const p1 = under(imgs()[1], cx, cy); ok(Math.abs(p1[0] - p0[0]) < 1.5 && Math.abs(p1[1] - p0[1]) < 1.5, '放大后鼠标下的点应保持不动：' + p0 + ' → ' + p1);
    const s1 = scales()[0]; f.dispatchEvent(new WheelEvent('wheel', {ctrlKey:true, deltaY:100, clientX:cx, clientY:cy, bubbles:true, cancelable:true})); await wait(50);
    ok(scales()[0] < s1, '向下滚应缩小');
    for (let i = 0; i < 60; i++) f.dispatchEvent(new WheelEvent('wheel', {ctrlKey:true, deltaY:-100, clientX:cx, clientY:cy, bubbles:true, cancelable:true}));
    await wait(50); ok(scales()[0] === 4, '连续放大应夹紧在 400%：' + scales());
    for (let i = 0; i < 80; i++) f.dispatchEvent(new WheelEvent('wheel', {ctrlKey:true, deltaY:100, clientX:cx, clientY:cy, bubbles:true, cancelable:true}));
    await wait(50); ok(scales()[0] === .1, '连续缩小应夹紧在 10%：' + scales());
    /* 从“适合”开始滚一格也要真的变化 */
    btn('fit').click(); await wait(50); const fit = scales()[0]; f.dispatchEvent(new WheelEvent('wheel', {ctrlKey:true, deltaY:-100, clientX:cx, clientY:cy, bubbles:true, cancelable:true})); await wait(50);
    ok(scales()[0] > fit, '从适合放大一格应变大：' + fit + ' → ' + scales()[0]);
  }
  if (T === 'dbl') {
    const f = frame(), r = rectOf(f), dbl = () => f.dispatchEvent(new MouseEvent('dblclick', {bubbles:true, cancelable:true, clientX:r.left + r.width / 2, clientY:r.top + r.height / 2}));
    dbl(); await wait(60); ok(scales().every(x => x === 1) && $$('#zoomtxt').textContent === '100%', '双击应从“适合”到 100%：' + scales());
    dbl(); await wait(60); ok(scales()[0] < 1 && $$('#zoomtxt').textContent.indexOf('适合') === 0, '再双击应回到“适合”：' + scales());
    btn('200').click(); await wait(40); dbl(); await wait(60); ok($$('#zoomtxt').textContent.indexOf('适合') === 0, '在 200% 时双击也回到“适合”');
    const fi = $$('#fi'), ri = rectOf(fi); fi.dispatchEvent(new MouseEvent('dblclick', {bubbles:true, cancelable:true, clientX:ri.left + 30, clientY:ri.top + 30})); await wait(60);
    ok(scales().every(x => x === 1), '在“初始”窗口里双击两个窗口也一起变 100%');
    ok(frame().getBoundingClientRect().width > 0 && W > 0, '');
  }
  if (T === 'pan') {
    const f = frame(), sc = f.querySelector('.scroller'), r = sc.getBoundingClientRect();
    /* 适合时不可平移 */
    const p0 = pos(); pointer(sc, 'pointerdown', r.left + 50, r.top + 50); pointer(document, 'pointermove', r.left + 150, r.top + 120); pointer(document, 'pointerup', r.left + 150, r.top + 120); await wait(40);
    ok(JSON.stringify(pos()) === JSON.stringify(p0), '适合时拖动不应移动图片');
    btn('200').click(); await wait(60);
    ok($$('#stage').classList.contains('zoomed') && getComputedStyle(sc).cursor === 'grab', '放大后应显示抓手光标');
    const a = pos()[1], ma = mat(imgs()[1]), w = 1600 * 2, h = 1000 * 2, fw = sc.clientWidth, fh = sc.clientHeight;
    pointer(sc, 'pointerdown', r.left + 100, r.top + 100); ok(true, '');
    pointer(document, 'pointermove', r.left + 160, r.top + 130); await wait(30);
    ok($$('#stage').classList.contains('panning') && getComputedStyle(sc).cursor === 'grabbing', '拖动时应是抓紧光标');
    const b = pos()[1]; ok(Math.abs((b[0] - a[0]) - 60) < 1.5 && Math.abs((b[1] - a[1]) - 30) < 1.5, '拖动 (60,30) 图片应跟着移动 (60,30)：' + a + ' → ' + b);
    ok(JSON.stringify(pos()[0]) === JSON.stringify(pos()[1]), '两个预览窗应同步平移：' + JSON.stringify(pos()));
    pointer(document, 'pointerup', r.left + 160, r.top + 130); await wait(30); ok(!$$('#stage').classList.contains('panning'), '松开后应结束拖动');
    /* 边界夹紧：图片边缘不会被拖进窗口里 */
    pointer(sc, 'pointerdown', r.left + 100, r.top + 100); pointer(document, 'pointermove', r.left + 5000, r.top + 5000); pointer(document, 'pointerup', r.left + 5000, r.top + 5000); await wait(40);
    let q1 = pos()[1]; ok(q1[0] <= 0.5 && q1[1] <= 0.5, '向右下拖到头，图片左上角不应进入窗口：' + q1);
    pointer(sc, 'pointerdown', r.left + 100, r.top + 100); pointer(document, 'pointermove', r.left - 5000, r.top - 5000); pointer(document, 'pointerup', r.left - 5000, r.top - 5000); await wait(40);
    q1 = pos()[1]; ok(Math.abs(q1[0] - (fw - w)) < 1.5 && Math.abs(q1[1] - (fh - h)) < 1.5, '向左上拖到头，图片右下角应贴住窗口：' + q1 + ' 期望 ' + (fw - w) + ',' + (fh - h));
    /* 拖动之后继续反向拖，应立刻跟手（没有“攒”出的隐形位移） */
    const c0 = pos()[1]; pointer(sc, 'pointerdown', r.left + 100, r.top + 100); pointer(document, 'pointermove', r.left + 130, r.top + 100); pointer(document, 'pointerup', r.left + 130, r.top + 100); await wait(40);
    ok(Math.abs(pos()[1][0] - c0[0] - 30) < 1.5, '到头后反向拖应立刻跟手：' + c0 + ' → ' + pos()[1]);
    /* 缩放时中心保持 */
    btn('100').click(); await wait(40); ok(scales().every(x => x === 1), '');
    /* 平移不写进设置 */
    ok(window.__SAVED__.every(c => !('cx' in c) && Object.keys(c).every(k => k === 'preview_zoom')), '只应保存 preview_zoom');
    /* 点击（没有移动）不应触发平移 */
    const e0 = JSON.stringify(pos()); pointer(sc, 'pointerdown', r.left + 100, r.top + 100); pointer(document, 'pointerup', r.left + 100, r.top + 100); await wait(30); ok(JSON.stringify(pos()) === e0, '单击不应移动图片');
  }
  if (T === 'init') {
    const z = q.get('zoom'), want = ({'150': 1.5, '400': 4, '10': .1})[z];
    if (want) { ok(scales().every(x => x === want) && $$('#zoomtxt').textContent === z + '%', '从设置读回 ' + z + '% 失败：' + scales() + ' ' + $$('#zoomtxt').textContent); ok(btn('fit').getAttribute('aria-pressed') === 'false', '“适合”不应按下'); }
    else { ok($$('#zoomtxt').textContent.indexOf('适合') === 0 && scales()[0] < 1, '没有/非法的 preview_zoom（' + z + '）应是“适合”：' + $$('#zoomtxt').textContent); }
    ok(window.__SAVED__.length === 0, '读回设置本身不应触发保存：' + JSON.stringify(window.__SAVED__));
  }
  if (T === 'states') {
    const pv = q.get('pv');
    if (pv === 'error') { ok($$('#fc .ph').textContent.indexOf('无法读取预览') >= 0 && $$('#fi .ph').textContent.indexOf('无法读取预览') >= 0, '应显示预览错误提示'); ok(!$$('#fc').classList.contains('has'), '错误时不应显示图片'); }
    if (pv === 'loading') ok($$('#fc .ph').textContent.indexOf('正在读取预览') >= 0, '应显示正在读取');
    if (!pv) ok($$('#fc .ph').textContent.indexOf('未选中照片') >= 0, '没选中照片应有提示');
    ok(vis($$('#zoomctl')), '缩放控件在没有图片时也应存在且可见'); btn('100').click(); await wait(40); ok($$('#zoomtxt').textContent === '100%', '没有图片时点预设不应报错');
    ok(document.documentElement.scrollWidth <= W + 1, '横向溢出');
  }
  if (T === 'layout') {
    ok(document.documentElement.scrollWidth <= W + 1, '页面横向溢出 ' + document.documentElement.scrollWidth + '>' + W);
    const z = $$('#zoomctl').getBoundingClientRect(), c = $$('.center').getBoundingClientRect(); ok(z.right <= c.right + 1 && z.left >= c.left - 1, '缩放控件应在中栏内：' + JSON.stringify([z.left, z.right, c.left, c.right]));
    btn('200').click(); await wait(60); document.querySelectorAll('#pvctl button, #pvctl input, #pvctl select').forEach(e => { const r = e.getBoundingClientRect(); if (r.width) ok(r.right <= W + 1 && r.left >= -1, '控件超出窗口 ' + (e.id || e.textContent)); });
  }
})().then(() => __finish(new URLSearchParams(location.search).get('t')), e => { window.__bad.push('脚本异常 ' + e + ' ' + (e.stack || '').slice(0, 200)); __finish('err'); });
</script>"""


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    extra = {"/img/initial.jpg": (sample_jpeg(1600, 1000), "image/jpeg"), "/img/adjusted.jpg": (sample_jpeg(1600, 1000, warm=True), "image/jpeg")}
    srv = Server(build_page(TAIL), extra)
    try:
        jobs = [
            ("zoom_ok", "t=ok&pv=ok", 1440, 860, False, True),
            ("zoom_ok_dark", "t=ok&pv=ok&theme=dark", 1440, 860, False, True),
            ("zoom_wheel", "t=wheel&pv=ok", 1440, 860, False, False),
            ("zoom_dblclick", "t=dbl&pv=ok", 1440, 860, False, False),
            ("zoom_pan", "t=pan&pv=ok", 1440, 860, False, False),
            ("zoom_init_150", "t=init&pv=ok&zoom=150", 1440, 860, False, True),
            ("zoom_init_400", "t=init&pv=ok&zoom=400", 1440, 860, False, False),
            ("zoom_init_10", "t=init&pv=ok&zoom=10", 1440, 860, False, False),
            ("zoom_init_fit", "t=init&pv=ok&zoom=fit", 1440, 860, False, False),
            ("zoom_init_invalid", "t=init&pv=ok&zoom=abc", 1440, 860, False, False),
            ("zoom_state_error", "t=states&pv=error", 1440, 860, False, True),
            ("zoom_state_loading", "t=states&pv=loading", 1440, 860, False, False),
            ("zoom_state_none", "t=states", 1440, 860, False, False),
        ]
        for w in (800, 960, 1100, 1440):
            jobs.append((f"zoom_layout_{w}", "t=layout&pv=ok", w, max(560, round(w * .64)), False, w == 800))
        code = run_jobs(srv, jobs, out)
    finally:
        srv.close()
    return code


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
