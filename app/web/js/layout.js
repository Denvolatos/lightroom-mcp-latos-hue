/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- 可拖动面板与可拖动对话框（1.3.0）----
   1) 左/右栏与中间区之间的分隔线（role="separator"）：鼠标拖动、键盘左右方向键调整；双击恢复默认；松开后防抖保存到 panel_widths。
      限制：左栏 200–480 px，右栏 240–520 px（同时给中间区至少留 320 px）；窄屏（≤900px）单列布局不显示分隔线，也不使用保存的宽度。
   2) 对话框（.mask 里的 .dialog）可按住标题栏拖动，不会拖出窗口；关闭后再打开恢复居中。 */
const PANEL_LIM = {left:[200, 480], right:[240, 520]}, PANEL_DEF = {left:260, right:300}, PANEL_MIN_CENTER = 320;
let PANEL = {left:PANEL_DEF.left, right:PANEL_DEF.right}, panelSaveT = null;
const PANEL_SIDE = {split_l:'left', split_r:'right'};
function panelMainWidth(){ const m = document.getElementById('main'); return m ? m.clientWidth : innerWidth; }
function panelRoom(side){      // 这一栏最多能有多宽：总宽 − 图标栏 − 另一栏 − 中间区最小宽度
  const m = document.getElementById('main'), rail = document.getElementById('rail');
  const railW = (innerWidth > 900 && rail) ? rail.offsetWidth : 0, leftOff = !!(m && m.classList.contains('pp-off'));
  const other = side === 'left' ? PANEL.right : (leftOff ? 0 : PANEL.left);
  return panelMainWidth() - railW - other - PANEL_MIN_CENTER;
}
function panelClamp(side, w){
  const lim = PANEL_LIM[side];
  return Math.round(Math.max(lim[0], Math.min(lim[1], panelRoom(side), Number(w) || lim[0])));
}
/* 把保存的宽度（可能比窗口放得下的大）换成当前窗口里实际使用的宽度；窗口变宽后会自动恢复到保存的值 */
function panelEffective(side){ return panelClamp(side, PANEL[side]); }
function panelApply(){
  const m = document.querySelector('.main'); if (!m) return;
  m.style.setProperty('--lw-user', panelEffective('left') + 'px'); m.style.setProperty('--rw-user', panelEffective('right') + 'px');
  Object.keys(PANEL_SIDE).forEach(id=>{
    const side = PANEL_SIDE[id], el = document.getElementById(id), lim = PANEL_LIM[side], now = panelEffective(side);
    el.setAttribute('aria-valuemin', String(lim[0])); el.setAttribute('aria-valuemax', String(Math.max(lim[0], Math.min(lim[1], panelRoom(side)))));
    el.setAttribute('aria-valuenow', String(now)); el.setAttribute('aria-valuetext', (side === 'left' ? '左栏宽度 ' : '右栏宽度 ') + now + ' 像素');
  });
}
function panelSaveSoon(){
  clearTimeout(panelSaveT);
  panelSaveT = setTimeout(async()=>{
    if (typeof REAL === 'function' && !REAL()) return;
    const w = {left:panelEffective('left'), right:panelEffective('right')};
    try { await window.pywebview.api.save_settings({panel_widths:w}, false); } catch(e){ console.warn('保存面板宽度失败', e); }
  }, 500);
}
function layoutFromSettings(s){
  const w = (s && s.panel_widths) || {}, ok = (v, lim) => typeof v === 'number' && isFinite(v) && v >= lim[0] && v <= lim[1];
  PANEL.left = ok(w.left, PANEL_LIM.left) ? Math.round(w.left) : PANEL_DEF.left;
  PANEL.right = ok(w.right, PANEL_LIM.right) ? Math.round(w.right) : PANEL_DEF.right;
  panelApply();
}
let SPLIT = null;
function splitDown(e){
  if (e.pointerType === 'mouse' && e.button !== 0) return;
  const el = e.currentTarget, side = PANEL_SIDE[el.id];
  SPLIT = {el, side, x:e.clientX, w:panelEffective(side), id:e.pointerId};
  el.classList.add('drag'); document.body.classList.add('resizing');
  try { el.setPointerCapture(e.pointerId); } catch(err){}       // 合成事件没有“活动指针”，捕获会失败，不影响拖动（下面也监听 document）
  e.preventDefault();
}
function splitMove(e){
  if (!SPLIT) return;
  const dx = e.clientX - SPLIT.x;
  PANEL[SPLIT.side] = panelClamp(SPLIT.side, SPLIT.w + (SPLIT.side === 'left' ? dx : -dx)); panelApply();
}
function splitUp(){
  if (!SPLIT) return;
  SPLIT.el.classList.remove('drag'); document.body.classList.remove('resizing'); SPLIT = null; panelSaveSoon();
}
document.addEventListener('pointermove', splitMove); document.addEventListener('pointerup', splitUp); document.addEventListener('pointercancel', splitUp);
Object.keys(PANEL_SIDE).forEach(id=>{
  const el = document.getElementById(id), side = PANEL_SIDE[id];
  el.addEventListener('pointerdown', splitDown);
  el.addEventListener('dblclick', ()=>{ PANEL[side] = PANEL_DEF[side]; panelApply(); panelSaveSoon(); });
  el.addEventListener('keydown', e=>{
    const step = e.shiftKey ? 48 : 16; let w = null;
    if (e.key === 'ArrowLeft') w = PANEL[side] + (side === 'left' ? -step : step);
    else if (e.key === 'ArrowRight') w = PANEL[side] + (side === 'left' ? step : -step);
    else if (e.key === 'Home') w = PANEL_LIM[side][0]; else if (e.key === 'End') w = PANEL_LIM[side][1];
    else if (e.key === 'Enter') w = PANEL_DEF[side];
    if (w === null) return;
    e.preventDefault(); PANEL[side] = panelClamp(side, Math.max(PANEL_LIM[side][0], Math.min(PANEL_LIM[side][1], w))); panelApply(); panelSaveSoon();
  });
});
window.addEventListener('resize', panelApply);
panelApply();

/* ---- 对话框拖动 ---- */
let DRAG = null, dragSuppressClick = false;
function dlgPlace(dlg, x, y){ dlg._pos = {x, y}; dlg.style.transform = (x || y) ? 'translate(' + x + 'px,' + y + 'px)' : ''; }
document.addEventListener('pointerdown', e=>{
  if (e.pointerType === 'mouse' && e.button !== 0) return;
  const t = e.target; if (!t || !t.closest) return;
  const h = t.closest('.dialog > h3, .dialog .wz-head'); if (!h || t.closest('button, input, select, textarea, a')) return;
  const dlg = h.closest('.dialog'); if (!dlg || !dlg.closest('.mask')) return;
  const pos = dlg._pos || {x:0, y:0};
  DRAG = {dlg, sx:e.clientX, sy:e.clientY, ox:pos.x, oy:pos.y, rect:dlg.getBoundingClientRect(), moved:false};
  dlg.classList.add('dragging');
});
document.addEventListener('pointermove', e=>{
  if (!DRAG) return;
  const dx = e.clientX - DRAG.sx, dy = e.clientY - DRAG.sy;
  if (!DRAG.moved && Math.abs(dx) < 3 && Math.abs(dy) < 3) return;
  DRAG.moved = true;
  const r = DRAG.rect, cx = Math.max(-r.left, Math.min(innerWidth - r.right, dx)), cy = Math.max(-r.top, Math.min(innerHeight - r.bottom, dy));
  dlgPlace(DRAG.dlg, DRAG.ox + cx, DRAG.oy + cy);
});
function dlgDrop(){
  if (!DRAG) return;
  DRAG.dlg.classList.remove('dragging');
  if (DRAG.moved){ dragSuppressClick = true; setTimeout(()=>{ dragSuppressClick = false; }, 80); }      // 在遮罩上松开鼠标会触发遮罩的 click（关闭对话框），这里吞掉
  DRAG = null;
}
document.addEventListener('pointerup', dlgDrop); document.addEventListener('pointercancel', dlgDrop);
window.addEventListener('click', e=>{ if (dragSuppressClick){ e.stopPropagation(); e.preventDefault(); dragSuppressClick = false; } }, true);
/* 窗口变小：把被拖偏的对话框拉回窗口内 */
window.addEventListener('resize', ()=>{
  document.querySelectorAll('.mask.show .dialog').forEach(d=>{
    if (!d._pos) return; const r = d.getBoundingClientRect();
    const dx = r.left < 0 ? -r.left : (r.right > innerWidth ? innerWidth - r.right : 0), dy = r.top < 0 ? -r.top : (r.bottom > innerHeight ? innerHeight - r.bottom : 0);
    if (dx || dy) dlgPlace(d, d._pos.x + dx, d._pos.y + dy);
  });
});
/* 对话框关闭（.mask 去掉 show）后恢复居中 */
(function(){
  const reset = m => { const d = m.querySelector('.dialog'); if (d && d._pos && !m.classList.contains('show')) dlgPlace(d, 0, 0); };
  const mo = new MutationObserver(list => list.forEach(r => reset(r.target)));
  document.querySelectorAll('.mask').forEach(m => mo.observe(m, {attributes:true, attributeFilter:['class']}));
})();
