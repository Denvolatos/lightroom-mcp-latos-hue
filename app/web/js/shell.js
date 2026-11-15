/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- 主界面外壳（1.3.0 新布局）：图标栏、照片面板（可收起；配方库替换它）、“更多”菜单、连接状态胶囊 ----
   照片面板收起状态存在 localStorage（键 lh_pp_collapsed；后端设置里目前没有 photo_panel_collapsed）。
   窄屏（≤900px）：图标栏是顶部横条，照片面板是点“照片/配方库”才滑出来的抽屉（不保存）。 */
const PP_KEY = 'lh_pp_collapsed';
let PP = {view:'photos', collapsed:false, drawer:false};
try { PP.collapsed = window.localStorage.getItem(PP_KEY) === '1'; } catch(e){}
function ppNarrow(){ return window.innerWidth <= 900; }
function ppHidden(){ return ppNarrow() ? !PP.drawer : PP.collapsed; }
function ppSave(){ try { window.localStorage.setItem(PP_KEY, PP.collapsed ? '1' : '0'); } catch(e){} }
function ppApply(){
  const hidden = ppHidden();
  $('#main').classList.toggle('pp-off', hidden);
  $('#libview').hidden = PP.view !== 'lib'; $('#gal').hidden = PP.view !== 'photos';
  const onP = !hidden && PP.view === 'photos', onL = !hidden && PP.view === 'lib';
  $('#r_photos').classList.toggle('on', onP); $('#r_photos').setAttribute('aria-pressed', onP ? 'true' : 'false');
  $('#r_lib').classList.toggle('on', onL); $('#r_lib').setAttribute('aria-pressed', onL ? 'true' : 'false');
  $('#ppanel').setAttribute('aria-hidden', hidden ? 'true' : 'false');
  if (typeof panelApply === 'function') panelApply();
  if (PP.view === 'lib' && !hidden && typeof renderLeft === 'function') renderLeft();
}
/* 点图标栏的“照片”：面板正显示照片 → 收起；否则 → 回到照片面板（并展开） */
$('#r_photos').onclick = ()=>{
  if (ppNarrow()){ if (PP.drawer && PP.view === 'photos') PP.drawer = false; else { PP.view = 'photos'; PP.drawer = true; } }
  else { if (PP.view === 'photos' && !PP.collapsed) PP.collapsed = true; else { PP.view = 'photos'; PP.collapsed = false; } ppSave(); }
  ppApply();
};
/* 点“配方库”：用预设/收藏/经验替换照片面板的内容；再点一次（或点“照片”）回到照片 */
$('#r_lib').onclick = ()=>{
  if (ppNarrow()){ if (PP.drawer && PP.view === 'lib'){ PP.view = 'photos'; PP.drawer = false; } else { PP.view = 'lib'; PP.drawer = true; } }
  else { if (PP.view === 'lib' && !PP.collapsed) PP.view = 'photos'; else { PP.view = 'lib'; PP.collapsed = false; ppSave(); } }
  ppApply();
};
$('#pp_collapse').onclick = ()=>{ if (ppNarrow()) PP.drawer = false; else { PP.collapsed = true; ppSave(); } ppApply(); };
$('#lib_back').onclick = ()=>{ PP.view = 'photos'; ppApply(); };
window.addEventListener('resize', ppApply);
document.addEventListener('keydown', e=>{ if (e.key === 'Escape' && ppNarrow() && PP.drawer && $('#ppanel').contains(document.activeElement)){ PP.drawer = false; ppApply(); $('#r_photos').focus(); } });
ppApply();

/* ---- “更多”菜单：新对话、环境检查、检查更新 ---- */
function moreClose(focusBtn){ const m = $('#moremenu'); if (m.hidden) return; m.hidden = true; $('#morebtn').setAttribute('aria-expanded', 'false'); if (focusBtn) $('#morebtn').focus(); }
function moreOpen(){
  const m = $('#moremenu'), b = $('#morebtn'); m.hidden = false; b.setAttribute('aria-expanded', 'true');
  const r = b.getBoundingClientRect(), mw = m.offsetWidth, mh = m.offsetHeight;      // 菜单用 fixed 定位，贴着“更多”按钮：宽屏在按钮右侧、窄屏（横条）在按钮下方，并保证完整在窗口内
  let x, y;
  if (ppNarrow()){ x = r.right - mw; y = r.bottom + 6; } else { x = r.right + 6; y = r.bottom - mh; }
  x = Math.max(6, Math.min(window.innerWidth - mw - 6, x)); y = Math.max(6, Math.min(window.innerHeight - mh - 6, y));
  m.style.left = x + 'px'; m.style.top = y + 'px';
  const f = m.querySelector('button'); if (f) f.focus(); }
$('#morebtn').onclick = e=>{ e.stopPropagation(); if ($('#moremenu').hidden) moreOpen(); else moreClose(false); };
$('#moremenu').onkeydown = e=>{
  const items = Array.prototype.slice.call($('#moremenu').querySelectorAll('button')), i = items.indexOf(document.activeElement);
  if (e.key === 'ArrowDown'){ e.preventDefault(); items[(i + 1) % items.length].focus(); }
  else if (e.key === 'ArrowUp'){ e.preventDefault(); items[(i + items.length - 1) % items.length].focus(); }
  else if (e.key === 'Escape'){ e.preventDefault(); moreClose(true); }
  else if (e.key === 'Tab') moreClose(false);
};
document.addEventListener('pointerdown', e=>{ if (!$('#moremenu').hidden && !e.target.closest('.morewrap') && !e.target.closest('#moremenu')) moreClose(false); });
$('#mm_new').onclick = ()=>{ moreClose(false); if (!REAL()) return toast('界面演示中，没有对话可以重新开始'); if (busy) return toast('AI 正在处理，结束后才能开始新对话'); newChat(); };
$('#mm_env').onclick = ()=>{ moreClose(false); if (!REAL()) return toast('界面演示中，环境检查不可用'); openWizard(); };
$('#mm_upd').onclick = async()=>{
  moreClose(false); if (!REAL()) return toast('界面演示中，检查更新不可用');
  await openSettings('about'); const b = $('#a_updcheck'); if (b && !b.disabled) b.click();
};

/* ---- 连接状态胶囊：已连接（绿点）/ 正在连接（黄）/ 未连接或出问题（红，显示简短原因）；完整提示在悬停提示里，点胶囊展开 ---- */
function pillClose(){ const h = $('#lrhint'); if (h.hidden) return; h.hidden = true; $('#lrpill').setAttribute('aria-expanded', 'false'); }
$('#lrpill').onclick = e=>{
  e.stopPropagation(); const h = $('#lrhint');
  if (!h.hidden){ pillClose(); return; }
  if (!h.textContent.trim()) return;                    // 没有额外提示（已连接）：不展开
  h.hidden = false; $('#lrpill').setAttribute('aria-expanded', 'true');
  h.style.left = 'auto'; h.style.right = '0';                         // 默认右对齐；胶囊在窗口左边时会超出，就改成左对齐，保证完整在窗口内
  const hr = h.getBoundingClientRect(); if (hr.left < 6){ h.style.right = 'auto'; h.style.left = '0'; }
  const hr2 = h.getBoundingClientRect(); if (hr2.right > window.innerWidth - 6){ h.style.left = 'auto'; h.style.right = '0'; }
};
document.addEventListener('pointerdown', e=>{ if (!$('#lrhint').hidden && !e.target.closest('.pillwrap')) pillClose(); });
document.addEventListener('keydown', e=>{ if (e.key === 'Escape') pillClose(); });
