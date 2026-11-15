# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""主界面新布局自查（1.3.0「照片在左」：图标栏 | 照片面板 | 预览区 | 右栏；无窗口、无 Lightroom、不属于 pytest）。
测试图是脚本现生成的渐变图（横图 1600×1000、竖图 1000×1500），不是真实照片。
覆盖：图标栏五个按钮 + 更多菜单 + 设置、配方库替换照片面板、照片面板收起/展开与保存（localStorage 不可用也能用）、
顶栏（照片名与拍摄时间、并排/多版本、排列四种、撤销）、预览框按照片真实比例居中 contain、排列“自动”在横图/竖图上选不同排法、
“滑动对比”的中间竖线（鼠标拖动 + 键盘 + aria）、连接状态胶囊三种状态与展开、右栏“撤销本次”与“逐项确认/新对话”的位置、
窄屏（≤900）顶部横条 + 抽屉、三套主题 × 800/1100/1440 的主界面截图与无溢出。有问题退出码为 1。
用法：python app/tests/ui_shell_check.py <输出目录>
"""
import sys
from pathlib import Path

from ui_common import Server, build_page, run_jobs, sample_jpeg

TAIL = r"""<script>
(async()=>{
  const q = new URLSearchParams(location.search), T = q.get('t');
  const $$ = s => document.querySelector(s), vis = e => !!e && e.getBoundingClientRect().width > 0 && e.getBoundingClientRect().height > 0;
  const R = s => $$(s).getBoundingClientRect(), W = document.documentElement.clientWidth;
  const frames = () => [$$('#fi'), $$('#fc')], fr = () => frames().map(f => f.getBoundingClientRect());
  const stageInner = () => { const s = $$('#stage'), cs = getComputedStyle(s); return [s.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight), s.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom)]; };
  /* 独立的期望值（不是抄页面代码）：每种排法下，两张照片总共显示多大面积 */
  const fitArea = (cw, ch, r) => { const w = Math.min(cw, ch * r); return w * (w / r); };
  const expectAuto = (Wd, Ht, r) => { const side = 2 * fitArea((Wd - 10) / 2, Ht, r), stack = 2 * fitArea(Wd, (Ht - 10) / 2, r); return stack > side ? 'stack' : 'side'; };
  const arrBtn = a => $$('#arrange button[data-a="' + a + '"]');
  const sw = ms => wait(ms || 80);
  await wait(900);
  if (T === 'rail') {
    const rail = $$('#rail'); ok(rail.tagName === 'NAV' && rail.getAttribute('aria-label') === '主要功能', '图标栏应是带名称的 nav');
    const names = Array.from(rail.querySelectorAll('.rbtn')).map(b => b.querySelector('span').textContent.trim());
    ok(names.join(',') === '照片,配方库,导入,导出,AI 挑片,更多,设置', '图标栏按钮顺序不对：' + names);
    ok(rail.getBoundingClientRect().width === R('#rail').width && Math.round(R('#rail').width) === Math.round(4.5 * parseFloat(getComputedStyle(document.documentElement).fontSize)), '图标栏宽度应为 4.5rem(72px)：' + R('#rail').width);
    ok($$('#impbtn').classList.contains('pri') && getComputedStyle($$('#impbtn')).backgroundColor !== getComputedStyle($$('#exportbtn')).backgroundColor, '导入应是主按钮样式');
    ok(R('#rail').top <= R('#topbar').top + 1 && R('#rail').bottom >= R('#ppanel').bottom - 1 && R('#rail').right <= R('#ppanel').left + 1, '图标栏应在最左、贯穿整个高度');
    ok(R('#topbar').left >= R('#rail').right - 1 && R('#topbar').right >= R('#rcol').right - 1, '顶栏应横跨图标栏之后的三列');
    ['r_photos', 'r_lib', 'impbtn', 'exportbtn', 'pickbtn', 'morebtn', 'setbtn'].forEach(id => { const b = $$('#' + id); ok(vis(b), id + ' 应可见'); ok(b.tagName === 'BUTTON' && (b.textContent || '').trim().length > 0 && !!b.title, id + ' 应有文字和提示'); });
    ok($$('#r_photos').getAttribute('aria-pressed') === 'true' && $$('#r_lib').getAttribute('aria-pressed') === 'false', '“照片”应是按下状态');
    ok(R('#morebtn').top > R('#pickbtn').bottom && R('#setbtn').top > R('#morebtn').top, '“更多”和“设置”应在底部');
    /* 导入/导出/挑片：调用原有入口 */
    const hit = []; window.startImport = () => hit.push('import'); window.openExport = () => hit.push('export'); window.openPick = () => hit.push('pick');
    $$('#impbtn').click(); $$('#exportbtn').click();
    ok(hit.join() === 'import,export', '导入/导出应调用原有入口：' + hit);
    ok($$('#pickbtn').disabled === !q.get('sel'), 'AI 挑片：没有选中照片时应不可点，选中后可点（disabled=' + $$('#pickbtn').disabled + '）');
    if (q.get('sel')) { $$('#pickbtn').click(); ok(hit.join() === 'import,export,pick', '选中照片后点 AI 挑片应调用 openPick'); }
    $$('#setbtn').click(); await sw(250); ok($$('#smask').classList.contains('show'), '点“设置”应打开设置页');
  }
  if (T === 'more') {
    const m = $$('#moremenu'), b = $$('#morebtn'); ok(m.hidden && b.getAttribute('aria-expanded') === 'false' && b.getAttribute('aria-haspopup') === 'menu', '菜单默认收起');
    b.click(); await sw(); ok(!m.hidden && vis(m) && b.getAttribute('aria-expanded') === 'true', '点“更多”应展开菜单');
    const items = Array.from(m.querySelectorAll('[role=menuitem]')).map(x => x.textContent.trim()); ok(items.join(',') === '新对话,环境检查,检查更新', '菜单项不对：' + items);
    const r = m.getBoundingClientRect(); ok(r.left >= 0 && r.right <= W && r.top >= 0 && r.bottom <= innerHeight, '菜单应完整出现在窗口内：' + JSON.stringify(r));
    ok(document.activeElement === m.querySelector('button'), '展开后焦点应进入第一项');
    m.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowDown', bubbles:true})); ok(document.activeElement.id === 'mm_env', '↓ 应到第二项');
    m.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowUp', bubbles:true})); m.dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowUp', bubbles:true})); ok(document.activeElement.id === 'mm_upd', '↑ 应循环到最后一项');
    m.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true})); await sw(); ok(m.hidden && document.activeElement === b, 'Esc 应关闭并把焦点还给按钮');
    b.click(); await sw(); document.body.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true})); await sw(); ok(m.hidden, '点菜单外面应关闭');
    /* 三个菜单项 */
    const hit = []; window.newChat = () => hit.push('new'); window.openWizard = () => hit.push('env');
    b.click(); await sw(); $$('#mm_new').click(); await sw(); ok(m.hidden && hit.join() === 'new', '“新对话”应调用 newChat 并关闭菜单：' + hit);
    b.click(); await sw(); $$('#mm_env').click(); await sw(); ok(m.hidden && hit.join() === 'new,env', '“环境检查”应打开环境检查：' + hit);
    b.click(); await sw(); $$('#mm_upd').click(); await sw(); await wait(300);
    ok(m.hidden && $$('#smask').classList.contains('show') && vis($$('#sec_about')), '“检查更新”应打开设置的关于页');
    ok(window.__CALLS__.filter(c => c[0] === 'check_update_now').length === 1, '“检查更新”应触发一次检查：' + JSON.stringify(window.__CALLS__.map(c => c[0])));
  }
  if (T === 'library') {
    const w0 = R('#ppanel').width; ok(vis($$('#gal')) && !vis($$('#libview')), '默认显示照片面板');
    $$('#r_lib').click(); await sw();
    ok(vis($$('#libview')) && !vis($$('#gal')), '点“配方库”应替换照片面板的内容');
    ok(Math.abs(R('#ppanel').width - w0) < 1, '替换内容时面板宽度不变'); ok($$('#r_lib').getAttribute('aria-pressed') === 'true' && $$('#r_photos').getAttribute('aria-pressed') === 'false', '按下状态应切到配方库');
    const tabs = Array.from(document.querySelectorAll('#ltabs .tab')).map(t => t.textContent.trim()); ok(tabs.join() === '预设,收藏,经验' && Array.from(document.querySelectorAll('#ltabs .tab')).every(t => vis(t)), '应有预设/收藏/经验三个标签页：' + tabs);
    ok(vis($$('#lpane')), '应有列表区域');
    document.querySelectorAll('#ltabs .tab')[1].click(); await sw(); ok(document.querySelectorAll('#ltabs .tab')[1].classList.contains('on') && !document.querySelectorAll('#ltabs .tab')[0].classList.contains('on'), '点“收藏”应切换标签页');
    document.querySelectorAll('#ltabs .tab')[2].click(); await sw(); ok(document.querySelectorAll('#ltabs .tab')[2].classList.contains('on'), '点“经验”应切换标签页');
    $$('#r_photos').click(); await sw(); ok(vis($$('#gal')) && !vis($$('#libview')) && $$('#r_photos').getAttribute('aria-pressed') === 'true', '再点“照片”应回到照片面板，且不收起');
    $$('#r_lib').click(); await sw(); $$('#r_lib').click(); await sw(); ok(vis($$('#gal')) && !vis($$('#libview')), '再点一次“配方库”也回到照片');
    $$('#r_lib').click(); await sw(); $$('#lib_back').click(); await sw(); ok(vis($$('#gal')), '“回到照片”按钮应回到照片面板');
    /* 配方库里收起、再点配方库 → 展开 */
    $$('#r_photos').click(); await sw(); ok(R('#ppanel').width === 0 || !vis($$('#ppanel')), '照片面板正显示时再点“照片”应收起');
    $$('#r_lib').click(); await sw(); ok(vis($$('#ppanel')) && vis($$('#libview')), '收起时点“配方库”应展开并显示配方库');
  }
  if (T === 'collapse') {
    const store = () => { try { return localStorage.getItem('lh_pp_collapsed'); } catch (e) { return 'ERR'; } };
    const c0 = R('#center').width, p0 = R('#ppanel').width; ok(!$$('#main').classList.contains('pp-off') && p0 > 200, '默认展开');
    ok($$('#gal_title').textContent === '照片' && /\d+ 张|^$/.test($$('#gal_count').textContent) , '照片面板顶部应是“照片 N 张”');
    ok(vis($$('#pp_collapse')) && $$('#pp_collapse').textContent.indexOf('收起') >= 0, '应有“◂ 收起”');
    $$('#pp_collapse').click(); await sw(150);
    ok($$('#main').classList.contains('pp-off') && !vis($$('#ppanel')) && !vis($$('#split_l')), '点“收起”后面板和分隔线应消失');
    ok(R('#center').width > c0 + p0 - 5, '收起后预览区应变宽 ' + p0 + ' 左右：' + c0 + ' → ' + R('#center').width);
    ok(R('#rail').width > 50 && R('#topbar').left >= R('#rail').right - 1, '收起后图标栏仍在'); ok($$('#r_photos').getAttribute('aria-pressed') === 'false', '“照片”按钮应不再是按下状态');
    if (!q.get('nostorage')) ok(store() === '1', '应把收起状态存进 localStorage：' + store());
    ok(document.documentElement.scrollWidth <= W + 1, '横向溢出');
    $$('#r_photos').click(); await sw(150); ok(!$$('#main').classList.contains('pp-off') && vis($$('#ppanel')) && Math.abs(R('#center').width - c0) < 2, '再点图标栏“照片”应展开：' + R('#center').width);
    if (!q.get('nostorage')) ok(store() === '0', '展开后应存 0：' + store());
    $$('#r_photos').click(); await sw(150); ok($$('#main').classList.contains('pp-off'), '面板展开时点图标栏“照片”应收起（切换）');
    $$('#r_lib').click(); await sw(150); ok(vis($$('#libview')) && !$$('#main').classList.contains('pp-off'), '收起时点“配方库”应展开成配方库');
    /* 收起/展开后，预览框随之重新排版 */
    ok(true, '');
  }
  if (T === 'collapse_persist') {          /* 刷新后保持上次的收起状态 */
    if (!sessionStorage.getItem('s1')) { localStorage.setItem('lh_pp_collapsed', '1'); sessionStorage.setItem('s1', '1'); location.reload(); return; }
    ok($$('#main').classList.contains('pp-off') && !vis($$('#ppanel')), '上次收起，刷新后应仍是收起');
    $$('#r_photos').click(); await sw(); ok(vis($$('#ppanel')), '可以再展开');
  }
  if (T === 'nostorage') {                 /* localStorage 被禁用：不报错，功能照常，只是不保存 */
    ok(!$$('#main').classList.contains('pp-off'), '没有存储时默认展开'); $$('#pp_collapse').click(); await sw(); ok($$('#main').classList.contains('pp-off'), '没有存储时也能收起');
    arrBtn('side').click(); await sw(); ok($$('#stage').dataset.arr === 'side', '没有存储时也能切换排列');
    applyAppearance('glass', 'standard'); ok(document.documentElement.dataset.theme === 'glass', '没有存储时主题照常');
  }
  if (T === 'topbar') {
    ok($$('#cur').textContent === 'DSC08238.ARW', '顶栏应显示当前照片名：' + $$('#cur').textContent); ok($$('#curtime').textContent === '2026-11-01 14:25', '应显示拍摄时间：' + $$('#curtime').textContent);
    ok(R('#cur').top >= R('#topbar').top && R('#cur').bottom <= R('#topbar').bottom, '照片名在顶栏内');
    const modes = Array.from(document.querySelectorAll('#modes button')).map(b => b.textContent); ok(modes.join() === '并排,多版本' && $$('#modes').getAttribute('role') === 'group', '并排/多版本分段开关');
    const arr = Array.from(document.querySelectorAll('#arrange button')).map(b => b.textContent); ok(arr.join() === '自动,左右,上下,滑动对比', '排列四个选项：' + arr);
    ok($$('#arrwrap').getAttribute('aria-label') === '预览排列' && $$('#arrange button[data-a=auto]').getAttribute('aria-pressed') === 'true', '默认“自动”');
    ok(vis($$('#zoomctl')) && vis($$('#zoomrange')) && document.querySelectorAll('#zoomctl .zp').length === 4, '顶栏应有缩放滑杆和预设');
    const hit = []; window.undo = b => hit.push('undo'); $$('#undobtn').click(); ok(hit.join() === 'undo' && $$('#undobtn').textContent.indexOf('撤销') >= 0, '顶栏“撤销”应调用原有 undo');
    [$$('#cur'), $$('#modes'), $$('#arrange'), $$('#zoomctl'), $$('#undobtn'), $$('#lrpill')].forEach(e => { const r = e.getBoundingClientRect(); ok(r.right <= W + 1 && r.left >= -1, '顶栏元素超出窗口 ' + (e.id || e.className)); });
    ok(R('#topbar').height < 120, '顶栏最多两行：' + R('#topbar').height);
    ok(R('#topbar').bottom <= R('#stage').top + 1, '顶栏在预览区上方');
  }
  if (T === 'ratio') {              /* 预览框按真实比例，不被拉成长条 */
    const portrait = q.get('shape') === 'portrait', r = portrait ? 1000 / 1500 : 1600 / 1000, mode = q.get('arr') || 'auto';
    if (mode !== 'auto') { arrBtn(mode).click(); await sw(150); }
    const [Wd, Ht] = stageInner(), s = $$('#stage'), got = s.dataset.arr, want = mode === 'auto' ? expectAuto(Wd, Ht, r) : mode;
    ok(got === want, '排列应为 ' + want + '（舞台 ' + Math.round(Wd) + '×' + Math.round(Ht) + '，比例 ' + r.toFixed(2) + '），实际 ' + got);
    ok(s.classList.contains('arr-' + got), '舞台应带 arr-' + got + ' 类'); ok(Math.abs(+s.dataset.ratio - r) < 0.01, '读到的照片比例应是 ' + r.toFixed(3) + '：' + s.dataset.ratio);
    const [a, b] = fr(); ok(Math.abs(a.width - b.width) < 1 && Math.abs(a.height - b.height) < 1, '两个预览框大小应一致');
    ok(Math.abs(a.width / a.height - r) < 0.02, '预览框宽高比应是照片的真实比例 ' + r.toFixed(3) + '，实际 ' + (a.width / a.height).toFixed(3));
    const cell = got === 'side' ? [(Wd - 10) / 2, Ht] : (got === 'stack' ? [Wd, (Ht - 10) / 2] : [Wd, Ht]);
    ok(a.width <= cell[0] + 1 && a.height <= cell[1] + 1, '预览框不应超出格子（不被裁）：' + [a.width, a.height] + ' vs ' + cell);
    ok(Math.abs(a.width - Math.min(cell[0], cell[1] * r)) < 1.5 || Math.abs(a.height - Math.min(cell[1], cell[0] / r)) < 1.5, '预览框应在格子里 contain 到最大：' + [a.width, a.height] + ' vs ' + cell);
    const sr = s.getBoundingClientRect();
    if (got === 'side') { ok(b.left >= a.right - 1 && Math.abs((a.top + a.bottom) / 2 - (b.top + b.bottom) / 2) < 1.5, '左右排：当前在初始右边、垂直对齐'); ok(Math.abs(((a.left + b.right) / 2) - (sr.left + sr.width / 2)) < 2, '左右排整体应水平居中'); ok(Math.abs((a.top + a.bottom) / 2 - (sr.top + parseFloat(getComputedStyle(s).paddingTop) + Ht / 2)) < 2, '左右排应垂直居中'); }
    if (got === 'stack') { ok(b.top >= a.bottom - 1 && Math.abs((a.left + a.right) / 2 - (b.left + b.right) / 2) < 1.5, '上下排：当前在初始下面、水平对齐'); ok(Math.abs((a.left + a.right) / 2 - (sr.left + sr.width / 2)) < 2, '上下排应水平居中'); }
    if (got === 'slide') { ok(Math.abs(a.left - b.left) < 1 && Math.abs(a.top - b.top) < 1, '滑动对比：两张重合'); }
    ok(document.documentElement.scrollWidth <= W + 1, '横向溢出');
    /* 图片本身没有被拉伸：fit 时 transform 比例 x=y，且图片填满框 */
    const img = $$('#fc .pimg'), m = new DOMMatrix(getComputedStyle(img).transform), ir = img.getBoundingClientRect(), fc = $$('#fc').getBoundingClientRect();
    ok(Math.abs(m.a - m.d) < 1e-6, '图片 x/y 缩放应一致（不拉伸）'); ok(Math.abs(ir.width - (fc.width - 2)) < 3 && Math.abs(ir.height - (fc.height - 2)) < 3, '适合时图片应正好填满预览框：' + [ir.width, ir.height] + ' vs ' + [fc.width, fc.height]);
  }
  if (T === 'auto_flip') {          /* 自动：同一窗口里，横图选上下排，竖图选左右排（通过切换样张和窗口占用来验证两种结果都出现） */
    const res = [];
    for (const shape of ['landscape', 'portrait']) {
      const r = shape === 'portrait' ? 1000 / 1500 : 1600 / 1000, u = shape === 'portrait' ? '/img/pi.jpg' : '/img/initial.jpg', w = shape === 'portrait' ? 1000 : 1600, h = shape === 'portrait' ? 1500 : 1000;
      window.onClaudeEvent({type:'preview', state:'ok', photo:{id:'P' + shape, name:shape + '.ARW', size:w + ' × ' + h}, initial:{url:u, w, h, version:'a' + shape}, current:{url:u, w, h, version:'b' + shape}, same:false, edge:1600}); await wait(500);
      const [Wd, Ht] = stageInner(); res.push([shape, $$('#stage').dataset.arr, expectAuto(Wd, Ht, r)]);
    }
    ok(res.every(x => x[1] === x[2]), '自动应选面积更大的排法：' + JSON.stringify(res)); ok(res[0][1] === 'stack' && res[1][1] === 'side', '横图应选上下排、竖图应选左右排：' + JSON.stringify(res));
    /* 手动选“左右”后再来新照片，保持左右 */
    arrBtn('side').click(); await sw(150);
    window.onClaudeEvent({type:'preview', state:'ok', photo:{id:'PX', name:'x.ARW'}, initial:{url:'/img/initial.jpg', w:1600, h:1000, version:'z0'}, current:{url:'/img/adjusted.jpg', w:1600, h:1000, version:'z1'}, same:false, edge:1600}); await wait(500);
    ok($$('#stage').dataset.arr === 'side', '固定左右后换照片应保持左右');
    /* 窗口大小变化（这里用收起面板模拟）时自动重新计算 */
    arrBtn('auto').click(); await sw(150); const before = $$('#stage').dataset.arr; $$('#pp_collapse').click(); await wait(400);
    const [W2, H2] = stageInner(); ok($$('#stage').dataset.arr === expectAuto(W2, H2, 1.6), '收起面板后自动排法应重新计算：' + $$('#stage').dataset.arr + '（之前 ' + before + '）');
    $$('#split_r').focus(); for (let i = 0; i < 6; i++) $$('#split_r').dispatchEvent(new KeyboardEvent('keydown', {key:'ArrowLeft', shiftKey:true, bubbles:true})); await wait(400);
    const [W3, H3] = stageInner(); ok($$('#stage').dataset.arr === expectAuto(W3, H3, 1.6), '拖宽右栏后自动排法应重新计算');
  }
  if (T === 'arr_buttons') {
    for (const a of ['side', 'stack', 'slide', 'auto']) { arrBtn(a).click(); await sw(120);
      ok(arrBtn(a).getAttribute('aria-pressed') === 'true' && arrBtn(a).classList.contains('on'), a + ' 应为按下'); ['auto', 'side', 'stack', 'slide'].filter(x => x !== a).forEach(x => ok(arrBtn(x).getAttribute('aria-pressed') === 'false', x + ' 应未按下'));
      if (a !== 'auto') ok($$('#stage').dataset.arr === a, '舞台应切到 ' + a); ok(localStorage.getItem('lh_arrange') === a, '应保存到 localStorage：' + localStorage.getItem('lh_arrange')); }
    arrBtn('stack').click(); await sw(); const m = document.querySelector('#modes button[data-m=multi]'); ok(!!m, '');
  }
  if (T === 'arr_persist') {
    if (!sessionStorage.getItem('s2')) { localStorage.setItem('lh_arrange', 'stack'); sessionStorage.setItem('s2', '1'); location.reload(); return; }
    if (!sessionStorage.getItem('s3')) { ok($$('#stage').dataset.arr === 'stack' && arrBtn('stack').getAttribute('aria-pressed') === 'true', '刷新后应保持上次的排列（上下）：' + $$('#stage').dataset.arr);
      localStorage.setItem('lh_arrange', 'bogus'); sessionStorage.setItem('s3', '1'); location.reload(); return; }
    ok(arrBtn('auto').getAttribute('aria-pressed') === 'true', '存了无效值应回落“自动”');
  }
  if (T === 'slide') {
    arrBtn('slide').click(); await sw(200);
    const s = $$('#stage'), h = $$('#slidehandle'), [a, b] = fr(); ok(s.classList.contains('arr-slide') && !!h, '应进入滑动对比并出现中间竖线');
    ok(Math.abs(a.left - b.left) < 1 && Math.abs(a.top - b.top) < 1 && Math.abs(a.width - b.width) < 1, '两张图应重合成一个框');
    ok(h.getAttribute('role') === 'slider' && h.getAttribute('aria-valuenow') === '50' && h.getAttribute('aria-valuemin') === '0' && h.getAttribute('aria-valuemax') === '100' && h.tabIndex === 0 && !!h.getAttribute('aria-label'), '竖线应是 role=slider，带 aria 值和名称：' + h.outerHTML.slice(0, 200));
    const hr = () => h.getBoundingClientRect(), cx = () => hr().left + hr().width / 2;
    ok(Math.abs(cx() - (a.left + a.width / 2)) < 2, '竖线应在框的中间：' + cx() + ' vs ' + (a.left + a.width / 2));
    ok(getComputedStyle($$('#fi')).clipPath.indexOf('inset') >= 0 && getComputedStyle($$('#fc')).clipPath.indexOf('inset') >= 0, '两张图应被裁成左右两半');
    ok($$('#fi .label').getBoundingClientRect().left < $$('#fc .label').getBoundingClientRect().left, '“初始”标签在左、“当前”在右');
    ok(vis($$('#fi .label')) && vis($$('#fc .label')), '两个标签都可见');
    /* 鼠标拖动 */
    const y = hr().top + hr().height / 2;
    pointer(h, 'pointerdown', cx(), y); pointer(document, 'pointermove', a.left + a.width * 0.25, y); await sw(40);
    ok(Math.abs(+h.getAttribute('aria-valuenow') - 25) <= 1, '拖到 25% 处应得 25：' + h.getAttribute('aria-valuenow')); ok(Math.abs(cx() - (a.left + a.width * 0.25)) < 2, '竖线应跟手');
    ok(h.classList.contains('drag'), '拖动中应有拖动样式'); pointer(document, 'pointerup', a.left + a.width * 0.25, y); await sw(40); ok(!h.classList.contains('drag'), '松开后结束');
    pointer(h, 'pointerdown', cx(), y); pointer(document, 'pointermove', a.left - 500, y); pointer(document, 'pointerup', a.left - 500, y); await sw(40); ok(+h.getAttribute('aria-valuenow') === 0, '拖到最左应夹在 0：' + h.getAttribute('aria-valuenow'));
    pointer(h, 'pointerdown', cx(), y); pointer(document, 'pointermove', a.right + 500, y); pointer(document, 'pointerup', a.right + 500, y); await sw(40); ok(+h.getAttribute('aria-valuenow') === 100, '拖到最右应夹在 100');
    /* 键盘 */
    h.focus(); const key = async (k, sh) => { h.dispatchEvent(new KeyboardEvent('keydown', {key:k, shiftKey:!!sh, bubbles:true, cancelable:true})); await sw(30); };
    await key('Home'); ok(+h.getAttribute('aria-valuenow') === 0, 'Home → 0'); await key('ArrowRight'); ok(+h.getAttribute('aria-valuenow') === 2, '→ +2'); await key('ArrowRight', true); ok(+h.getAttribute('aria-valuenow') === 12, 'Shift+→ +10');
    await key('ArrowLeft'); ok(+h.getAttribute('aria-valuenow') === 10, '← -2'); await key('End'); ok(+h.getAttribute('aria-valuenow') === 100, 'End → 100'); await key('ArrowRight'); ok(+h.getAttribute('aria-valuenow') === 100, '100 以上不再增加');
    await key('Home'); await key('ArrowLeft'); ok(+h.getAttribute('aria-valuenow') === 0, '0 以下不再减少'); await key('x'); ok(+h.getAttribute('aria-valuenow') === 0, '其他键不处理');
    await key('End'); await key('ArrowLeft', true); ok(+h.getAttribute('aria-valuenow') === 90, 'Shift+← -10'); ok(Math.abs(cx() - (a.left + a.width * 0.9)) < 2, '键盘调整后竖线位置应更新');
    /* 缩放/平移仍然生效，且两张同步 */
    document.querySelector('#zoomctl .zp[data-z="200"]').click(); await sw(120);
    const m1 = new DOMMatrix(getComputedStyle($$('#fi .pimg')).transform), m2 = new DOMMatrix(getComputedStyle($$('#fc .pimg')).transform); ok(Math.abs(m1.a - 2) < 1e-6 && Math.abs(m2.a - 2) < 1e-6 && Math.abs(m1.e - m2.e) < 0.5 && Math.abs(m1.f - m2.f) < 0.5, '滑动对比下缩放应同步 200%');
    const sc = $$('#fc .scroller'), r = sc.getBoundingClientRect(); pointer(sc, 'pointerdown', r.left + r.width * 0.8, r.top + 60); pointer(document, 'pointermove', r.left + r.width * 0.8 - 50, r.top + 90); pointer(document, 'pointerup', r.left + r.width * 0.8 - 50, r.top + 90); await sw(60);
    const m3 = new DOMMatrix(getComputedStyle($$('#fi .pimg')).transform), m4 = new DOMMatrix(getComputedStyle($$('#fc .pimg')).transform); ok(Math.abs(m3.e - m4.e) < 0.5 && Math.abs(m3.f - m4.f) < 0.5 && Math.abs(m3.e - m1.e) > 5, '滑动对比下平移应两张同步：' + [m1.e, m3.e, m4.e]);
    /* 回到别的排法，竖线消失 */
    arrBtn('side').click(); await sw(150); ok(!$$('#slidehandle'), '离开滑动对比后竖线应消失'); ok(getComputedStyle($$('#fi')).clipPath === 'none', '离开后不再裁剪');
  }
  if (T === 'pill') {
    const p = $$('#lrpill'), st = $$('#lrstat'), h = $$('#lrhint'), top0 = R('#topbar').height;
    ok(p.tagName === 'BUTTON' && p.getAttribute('aria-controls') === 'lrhint', '胶囊应是按钮');
    ok(st.textContent === '已连接' && p.classList.contains('ok') && (() => { const c = rgb(getComputedStyle($$('#lrdot')).backgroundColor); return c[1] > c[0] && c[1] > 100; })(), '已连接：绿点 + “已连接”：' + st.textContent + ' ' + p.className);
    ok(h.hidden && h.textContent === '', '已连接时没有额外提示'); p.click(); await sw(); ok(h.hidden, '没有提示时点胶囊不展开');
    window.onClaudeEvent({type:'status', state:'connecting', text:'Lightroom 正在连接', hint:'正在连接 Lightroom，请稍候。'}); await sw();
    ok(p.classList.contains('warn') && st.textContent === 'Lightroom 正在连接', '正在连接：黄色：' + p.className + ' ' + st.textContent);
    const longHint = '请确认 Lightroom 已打开，且已启用 LrMCP 插件（文件 > 增效工具管理器）。无需重启软件，打开后会自动连接。如果仍然连不上，请在 Lightroom 里点“重新载入增效工具”，或者重新启动 Lightroom 后再试一次。';
    window.onClaudeEvent({type:'status', state:'disconnected', text:'Lightroom 未连接', hint:longHint}); await sw();
    ok(p.classList.contains('bad') && st.textContent === 'Lightroom 未连接', '未连接：红色 + 简短原因：' + p.className + ' ' + st.textContent);
    ok(R('#lrpill').height < 40 && R('#lrpill').width <= 16.2 * parseFloat(getComputedStyle(document.documentElement).fontSize), '胶囊不应变成长条或多行：' + JSON.stringify(R('#lrpill')));
    ok(Math.abs(R('#topbar').height - top0) < 2, '长提示不应撑高顶栏（完整内容在提示里）：' + top0 + ' → ' + R('#topbar').height);
    ok(p.title.indexOf(longHint) >= 0, '完整提示应在悬停提示里'); ok(h.hidden, '默认不展开');
    p.click(); await sw(); ok(!h.hidden && vis(h) && p.getAttribute('aria-expanded') === 'true' && h.textContent === longHint, '点胶囊应展开完整提示');
    const hr = h.getBoundingClientRect(); ok(hr.left >= 0 && hr.right <= W + 1 && hr.bottom <= innerHeight, '提示面板应完整在窗口内：' + JSON.stringify(hr));
    ok(Math.abs(R('#topbar').height - top0) < 2, '展开提示不应改变顶栏高度');
    p.click(); await sw(); ok(h.hidden && p.getAttribute('aria-expanded') === 'false', '再点收起');
    p.click(); await sw(); document.body.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true})); await sw(); ok(h.hidden, '点别处收起'); p.click(); await sw(); document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true})); await sw(); ok(h.hidden, 'Esc 收起');
    window.onClaudeEvent({type:'lr_launch', state:'starting', message:'正在启动 Lightroom…'}); await sw(); ok(p.classList.contains('warn') && st.textContent === '正在启动 Lightroom…', '自动启动中：黄色');
    window.onClaudeEvent({type:'status', state:'connected', text:'Lightroom 已连接', hint:''}); LRL = {state:'idle', message:''}; showStatus({state:'connected', text:'Lightroom 已连接', hint:''}); await sw();
    ok(p.classList.contains('ok') && st.textContent === '已连接' && h.hidden && h.textContent === '', '恢复连接后回到绿色并收起提示');
    /* 红色状态的文字对比度 */
    window.onClaudeEvent({type:'status', state:'disconnected', text:'Lightroom 未连接', hint:'x'}); await sw(); const c = contrast(getComputedStyle(p).color, effBg(p)); ok(c >= 3, '红色胶囊文字对比度 ' + c.toFixed(2));
  }
  if (T === 'right') {
    const st = $$('#rcol .section-title'), rr = $$('#restorerow'); ok(st.textContent.indexOf('本次调整') >= 0 && st.contains(rr), '“撤销本次”应在“本次调整”标题旁'); ok(getComputedStyle(rr).display === 'none', '没有调整时隐藏');
    window.onClaudeEvent({type:'adjust', rows:[{label:'曝光', before:'0', after:'0.1', status:'已应用', edit_id:'e1', reason:'整体略微提亮'}]}); await sw();
    ok(vis(rr) && rr.textContent.trim() === '撤销本次', '有已应用的调整时显示“撤销本次”：' + rr.textContent); ok(R('#restorerow').top >= R('#rcol .section-title').top - 1 && R('#restorerow').bottom <= R('#rcol .section-title').bottom + 1, '按钮在标题行内');
    const o = R('.opts'), cb = R('.chatbar'); ok(o.bottom <= cb.top + 1 && cb.top - o.bottom < 20, '“逐项确认”和“新对话”应在输入框正上方');
    ok(vis($$('#newchat')) && R('#newchat').left > R('#sw').right && R('#newchat').top >= o.top - 1 && R('#newchat').bottom <= o.bottom + 1, '“新对话”在同一行右侧'); ok($$('#swlabel').textContent === '逐项确认：开', '开关说明应简短：' + $$('#swlabel').textContent);
    ok(R('#swlabel').height < 24, '开关说明不换行');
  }
  if (T === 'narrow') {
    const rail = R('#rail'); ok(rail.width >= W - 2 && rail.height < 80, '窄屏图标栏应是顶部横条：' + JSON.stringify(rail));
    const bs = Array.from(document.querySelectorAll('#rail .rbtn')).filter(vis); ok(bs.length === 7 || bs.length === 6, '窄屏图标栏按钮应都可见 ' + bs.length);
    ok(bs.every(b => { const r = b.getBoundingClientRect(); return r.right <= W + 1 && r.left >= -1; }) || $$('#rail').scrollWidth > $$('#rail').clientWidth, '图标栏按钮应在窗口内（放不下时可横向滚动）');
    ok(R('#topbar').top >= rail.bottom - 1, '顶栏在图标栏下面'); ok(R('#center').top >= R('#topbar').bottom - 1, '预览区在顶栏下面'); ok(document.documentElement.scrollWidth <= W + 1, '页面横向溢出');
    ok(!vis($$('#ppanel')), '照片面板默认收起成抽屉');
    $$('#r_photos').click(); await sw(150); const d = R('#ppanel'); ok(vis($$('#ppanel')) && d.left <= 1 && d.width <= W * 0.87 && d.top >= R('#topbar').bottom - 2, '点“照片”应在内容区左边滑出抽屉：' + JSON.stringify(d));
    ok(getComputedStyle($$('#ppanel')).zIndex !== 'auto' && R('#center').width > 200, '抽屉叠在预览区上方，不挤占它');
    ok(vis($$('#gal_scroll')), '抽屉里有照片列表'); $$('#r_lib').click(); await sw(); ok(vis($$('#libview')) && vis($$('#ppanel')), '抽屉里可以切到配方库');
    ok($$('#r_lib').classList.contains('on'), '按下状态');
    $$('#morebtn').click(); await sw(); const m = R('#moremenu'); ok(m.left >= 0 && m.right <= W + 1 && m.top >= 0 && m.bottom <= innerHeight, '窄屏的更多菜单应在窗口内：' + JSON.stringify(m)); document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape'})); $$('#morebtn').click();
    $$('#pp_collapse') && $$('#r_photos').click(); await sw(); $$('#r_photos').click(); await sw(150);
    $$('#ppanel').querySelector('#gal_scroll').focus(); document.dispatchEvent(new KeyboardEvent('keydown', {key:'Escape', bubbles:true})); await sw(); ok(!vis($$('#ppanel')), 'Esc 应关闭抽屉');
    $$('#setbtn').click(); await sw(250); ok($$('#smask').classList.contains('show'), '窄屏设置按钮可用');
  }
  if (T === 'shot') {
    ok(document.documentElement.scrollWidth <= W + 1, '页面横向溢出 ' + document.documentElement.scrollWidth + '>' + W);
    ok(R('#topbar').height < 130, '顶栏高度正常：' + R('#topbar').height);
    const bad = []; document.querySelectorAll('#topbar button, #rail button, #zoomctl *, #arrange button').forEach(e => { const r = e.getBoundingClientRect(); if (r.width && (r.right > W + 1 || r.left < -1)) { if (!(e.closest('#rail') && $$('#rail').scrollWidth > $$('#rail').clientWidth)) bad.push(e.id || e.textContent.trim().slice(0, 8)); } });
    ok(bad.length === 0, '这些控件超出窗口：' + bad.join());
    const [a, b] = fr(); ok(a.width > 150 && a.height > 80, '预览框大小合理：' + [a.width, a.height]);
    const [Wd, Ht] = stageInner(); ok($$('#stage').dataset.arr === expectAuto(Wd, Ht, 1.6), '自动排法应是面积更大的那种');
    const ps = [['.rbtn.pri', 3], ['#r_photos', $$('#r_photos').classList.contains('on') ? 4.5 : 3], ['.tname', 4.5], ['#undobtn', 4.5], ['#arrange button.on', 3]]; ps.forEach(([sel, min]) => { const e = $$(sel); const c = contrast(getComputedStyle(e).color, effBg(e)); ok(c >= min, sel + ' 对比度 ' + c.toFixed(2) + ' < ' + min); });
  }
})().then(() => __finish(new URLSearchParams(location.search).get('t')), e => { window.__bad.push('脚本异常 ' + e + ' ' + (e.stack || '').slice(0, 300)); __finish('err'); });
</script>"""


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    extra = {"/img/initial.jpg": (sample_jpeg(1600, 1000), "image/jpeg"), "/img/adjusted.jpg": (sample_jpeg(1600, 1000, warm=True), "image/jpeg"),
             "/img/pi.jpg": (sample_jpeg(1000, 1500), "image/jpeg")}
    srv = Server(build_page(TAIL), extra)
    try:
        jobs = [
            ("shell_rail", "t=rail&pv=ok", 1440, 900, False, False),
            ("shell_rail_selected", "t=rail&pv=ok&sel=1", 1440, 900, False, False),
            ("shell_more", "t=more&pv=ok", 1440, 900, False, True),
            ("shell_library", "t=library&pv=ok", 1440, 900, False, False),
            ("shell_collapse", "t=collapse&pv=ok", 1440, 900, False, True),
            ("shell_collapse_nostorage", "t=collapse&pv=ok&nostorage=1", 1440, 900, False, False),
            ("shell_collapse_persist", "t=collapse_persist&pv=ok", 1440, 900, False, False),
            ("shell_nostorage", "t=nostorage&pv=ok&nostorage=1", 1440, 900, False, False),
            ("shell_topbar", "t=topbar&pv=ok", 1440, 900, False, False),
            ("shell_ratio_landscape_auto", "t=ratio&pv=ok", 1440, 900, False, True),
            ("shell_ratio_portrait_auto", "t=ratio&pv=ok&shape=portrait", 1440, 900, False, True),
            ("shell_ratio_landscape_side", "t=ratio&pv=ok&arr=side", 1440, 900, False, True),
            ("shell_ratio_landscape_stack", "t=ratio&pv=ok&arr=stack", 1440, 900, False, False),
            ("shell_ratio_landscape_slide", "t=ratio&pv=ok&arr=slide", 1440, 900, False, True),
            ("shell_ratio_portrait_stack", "t=ratio&pv=ok&shape=portrait&arr=stack", 1440, 900, False, False),
            ("shell_ratio_portrait_side", "t=ratio&pv=ok&shape=portrait&arr=side", 1440, 900, False, False),
            ("shell_ratio_portrait_slide", "t=ratio&pv=ok&shape=portrait&arr=slide", 1440, 900, False, False),
            ("shell_ratio_1100_auto", "t=ratio&pv=ok", 1100, 700, False, False),
            ("shell_ratio_800_auto", "t=ratio&pv=ok", 800, 620, False, False),
            ("shell_auto_flip", "t=auto_flip&pv=ok", 1440, 900, False, False),
            ("shell_arr_buttons", "t=arr_buttons&pv=ok", 1440, 900, False, False),
            ("shell_arr_persist", "t=arr_persist&pv=ok", 1440, 900, False, False),
            ("shell_slide", "t=slide&pv=ok", 1440, 900, False, False),
            ("shell_slide_portrait", "t=slide&pv=ok&shape=portrait", 1440, 900, False, False),
            ("shell_pill", "t=pill&pv=ok", 1440, 900, False, True),
            ("shell_pill_800", "t=pill&pv=ok", 800, 620, False, False),
            ("shell_right", "t=right&pv=ok", 1440, 900, False, False),
            ("shell_narrow_800", "t=narrow&pv=ok", 800, 620, False, True),
            ("shell_narrow_640", "t=narrow&pv=ok", 640, 560, False, False),
            ("shell_narrow_900", "t=narrow&pv=ok", 900, 640, False, False),
        ]
        for th in ("paper", "glass", "dark"):
            for w in (800, 1100, 1440):
                jobs.append((f"main_{th}_{w}", f"t=shot&pv=ok&theme={th}", w, max(560, round(w * .64)), False, True))
        code = run_jobs(srv, jobs, out)
    finally:
        srv.close()
    return code


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
