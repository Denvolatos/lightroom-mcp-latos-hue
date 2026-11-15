/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- files ---- */
let SEL = {count:0, photos:[], active_id:null};      // Lightroom 当前选中的照片（最多前 20 张）；AI 挑片按钮与预设套用用它判断是否有选中
function selSig(){ return SEL.count+'|'+SEL.active_id+'|'+SEL.photos.map(p=>p.id).join(','); }
function renderFiles(){ if (REAL()) { updatePickBtn(); return; } loadGallery(); }     // 真实模式的图库由 loadGallery 与图库事件驱动

/* ---- center ---- */
function nApplied(){ return REAL() ? rows.filter(r=>r.status==='已应用').length : steps.length; }
const DEMO = location.hash === '#demo';
let pv = null, noBackend = false;   // pv = 后端推送的最近一次预览内容
let viewMode='pair', versionPhoto='', versionRows=[], versionImage='', versionUndo='', versionDifference=null, versionBusy=false;
function versionButtons(){
  const has = versionRows.length>0;
  $('#versionpick').style.display = has ? '' : 'none';
  $('#versionapply').disabled = !has || versionBusy; $('#versionsave').disabled = versionBusy;
  $('#versionundo').style.display = versionUndo ? '' : 'none'; $('#versionundo').disabled = versionBusy;
}
async function loadVersions(){
  if (!REAL() || viewMode!=='multi') return;
  const r=await window.pywebview.api.versions_state();
  if (!r.ok){ versionRows=[]; versionPhoto=''; versionButtons(); renderStage(); $('#infobar').textContent=r.message||'无法读取版本'; return; }
  if (versionPhoto!==r.result.photo_id) versionUndo='';         // 换了照片：上一张的“撤销应用”不再显示（仍可在“本次调整”里撤销）
  versionPhoto=r.result.photo_id; versionRows=r.result.versions||[];
  const select=$('#versionpick'), old=select.value;
  select.innerHTML=versionRows.map(v=>`<option value="${esc(v.name)}">${esc(v.name)} · ${esc(v.created||'')}</option>`).join('');
  if (versionRows.some(v=>v.name===old)) select.value=old;
  versionButtons();
  await loadVersionPicture();
}
async function loadVersionPicture(){
  versionImage=''; versionDifference=null;
  const name=$('#versionpick').value;
  if (name && versionRows.length){
    try {
      const picture=await window.pywebview.api.version_preview(name);
      const plan=await window.pywebview.api.version_plan(name);
      if (name!==$('#versionpick').value) return;
      if (picture.ok && picture.result.photo_id===versionPhoto) versionImage=picture.result.url;
      if (plan.ok && plan.result.photo_id===versionPhoto) versionDifference=plan.result;
    } catch(e){
      if (name!==$('#versionpick').value) return;
      versionImage=''; versionDifference=null; renderStage(); $('#infobar').textContent='无法读取这个版本，请检查与 Lightroom 的连接后再选一次。'; return;
    }
  }
  renderStage();
}
$('#modes').onclick=e=>{
  const mode=e.target.dataset.m;
  if (!mode || (mode==='multi' && !REAL())) return;
  viewMode=mode;
  $('#modes').querySelectorAll('button').forEach(b=>b.classList.toggle('on',b.dataset.m===mode));
  $('#versiontools').style.display=mode==='multi'?'flex':'none';
  versionButtons();
  renderStage(); if(mode==='multi') loadVersions().catch(()=>{ $('#infobar').textContent='无法读取版本'; });
};
$('#versionpick').onchange=()=>loadVersionPicture();
/* 命名输入框：与 askDialog 同一风格；回车确认、Esc 取消；返回去掉首尾空格的文字，取消返回 null */
function inputDialog(title, text, placeholder, okLabel, maxLen){ return new Promise(res=>{
  const mk=document.createElement('div'); mk.className='mask show';
  mk.innerHTML=`<div class="dialog small" role="dialog" aria-label="${esc(title)}"><h3>${esc(title)}</h3><p>${esc(text)}</p><input class="name-input" type="text" maxlength="${Number(maxLen)||40}" placeholder="${esc(placeholder||'')}" autocomplete="off"><div class="ferr2"></div><div class="row"><button class="btn">取消</button><button class="btn primary">${esc(okLabel)}</button></div></div>`;
  document.body.appendChild(mk);
  const inp=mk.querySelector('input'), err=mk.querySelector('.ferr2'), [c,o]=mk.querySelectorAll('button');
  const done=v=>{ mk.remove(); res(v); };
  const ok=()=>{ const v=inp.value.trim(); if(!v){ err.textContent='请先写一个名字。'; inp.focus(); return; } done(v); };
  c.onclick=()=>done(null); o.onclick=ok;
  inp.onkeydown=e=>{ if(e.key==='Enter') ok(); else if(e.key==='Escape') done(null); };
  inp.oninput=()=>{ err.textContent=''; };
  setTimeout(()=>inp.focus(), 0); }); }
/* 确认清单：标题 + 一句说明 + “项目 / 现在 / 改成”表格；所有文字都经 esc 转义 */
function planDialog(title, intro, items, okLabel, more){ return new Promise(res=>{
  const mk=document.createElement('div'); mk.className='mask show';
  const rowsHtml=items.map(i=>`<tr><td>${esc(i.label)}</td><td class="num">${esc(i.before)}</td><td class="num">${esc(i.after)}</td></tr>`).join('');
  mk.innerHTML=`<div class="dialog exp" role="dialog" aria-label="${esc(title)}"><h3>${esc(title)}</h3><div class="plan-intro">${esc(intro)}</div><div class="plan-list body"><table><tr><th>项目</th><th>现在</th><th>改成</th></tr>${rowsHtml}</table></div>${more?`<div class="plan-more">${esc(more)}</div>`:''}<div class="row"><button class="btn">取消</button><button class="btn primary">${esc(okLabel)}</button></div></div>`;
  document.body.appendChild(mk); const [c,o]=mk.querySelectorAll('.row button');
  c.onclick=()=>{ mk.remove(); res(false); }; o.onclick=()=>{ mk.remove(); res(true); }; }); }
$('#versionsave').onclick=async()=>{
  if (versionBusy) return;
  const name=await inputDialog('保存当前版本','给这张照片现在的样子起个名字（最多 40 个字）。保存的是当前的调整参数，照片本身不会被改动；以后可以随时回到这个版本。','例如：暖色调','保存',40);
  if (name===null) return;
  versionBusy=true; versionButtons();
  try {
    const r=await window.pywebview.api.version_save(name);
    if (!r.ok) return toast(r.message||'保存失败');
    toast('版本已保存'); await loadVersions(); $('#versionpick').value=name; await loadVersionPicture();
  } catch(e){ toast('保存没有完成，请检查与 Lightroom 的连接后再试。'); }
  finally { versionBusy=false; versionButtons(); }
};
$('#versionapply').onclick=async()=>{
  if (versionBusy) return;
  const name=$('#versionpick').value; if(!name) return toast('请先选择版本');
  versionBusy=true; versionButtons();
  try {
    const plan=await window.pywebview.api.version_plan(name);
    if(!plan.ok) return toast(plan.message||'无法读取版本');
    const d=plan.result;
    if(d.photo_id!==versionPhoto){ toast('选中的照片已改变，已为你重新读取版本。'); await loadVersions(); return; }
    if(!d.count) return toast('当前照片已经是这个版本的样子，不需要应用。');
    const shown=d.items.slice(0,40), more=d.count>shown.length?`另有 ${d.count-shown.length} 项没有列出，也会一起改。`:'';
    if(!await planDialog(`应用版本“${name}”`, `将把当前照片改回这个版本保存时的样子，共 ${d.count} 项调整。改之前会自动备份，应用后可以点“撤销应用”或在“本次调整”里撤销。`, shown, '应用', more)) return;
    const r=await window.pywebview.api.version_apply(d.token);
    if(!r.ok){ toast(r.message||'应用失败'); if(r.stale) await loadVersions(); return; }
    versionUndo=r.result.edit_id||'';
    toast(versionUndo?'版本已应用':'当前照片已经是这个版本的样子，没有改动。'); await loadVersionPicture();
  } catch(e){ toast('应用没有完成，请检查与 Lightroom 的连接，并在 Lightroom 里确认这张照片的状态。'); }
  finally { versionBusy=false; versionButtons(); }
};
$('#versionundo').onclick=async()=>{
  if(!versionUndo || versionBusy) return;
  versionBusy=true; versionButtons();
  try {
    const r=await window.pywebview.api.undo(versionUndo);
    if(!r.ok) return toast(r.message||'撤销失败');
    versionUndo=''; toast('已撤销版本应用'); await loadVersionPicture();
  } catch(e){ toast('撤销没有完成，请稍后在“本次调整”里再试。'); }
  finally { versionBusy=false; versionButtons(); }
};
const PH_INITIAL = '初始（首次打开时）';
const PH_INITIAL_TIP = '软件第一次读取该照片时的状态。若照片此前已在 Lightroom 中调整过，则不等同于原片。';
function fmtInfo(p){ return [p.name,p.camera,p.iso,p.aperture,p.shutter,p.focal,p.format,p.size].filter(x=>x).join('  ·  '); }
function frameHTML(id, label, tip){ return `<div class="frame" id="${id}"><div class="scroller"><img class="pimg" alt=""></div><div class="ph"></div><span class="label" ${tip?`title="${esc(tip)}"`:''}>${label}</span><span class="chip">正在读取预览</span><span class="note"></span></div>`; }
function setFrame(id, o){   // o: {url, text, note, busy}
  const f=$('#'+id), img=f.querySelector('.pimg');
  if (o.url){ if (img.getAttribute('src')!==o.url) img.src=o.url; f.classList.add('has'); img.onload=()=>zoomLayout(); }
  else { img.removeAttribute('src'); f.classList.remove('has'); f.querySelector('.ph').textContent=o.text||''; }
  f.classList.toggle('busy', !!o.busy); f.querySelector('.note').textContent=o.note||'';
}
function renderStage(){
  $('#curtime').textContent = ((pv && pv.photo) || {}).captured || '';
  const s=$('#stage'), real=REAL(), kind = real ? 'real' : (DEMO ? 'demo' : 'none');
  if(real && viewMode==='multi'){
    if(s.dataset.kind!=='multi'){
      s.dataset.kind='multi';
      s.innerHTML=frameHTML('fi','已保存版本')+frameHTML('fc','当前');
      s.ondblclick=toggleZoom;
    }
    const p=pv||{}, same=versionPhoto && versionPhoto===(p.photo||{}).id;
    setFrame('fi',{url:same?versionImage:'',text:versionRows.length?'这个版本没有预览图（参数仍然可以应用）':'这张照片还没有保存过版本。点上方“保存当前”，把现在的样子存下来。'});
    setFrame('fc',{url:same && p.state==='ok'?p.current.url:'',text:p.state==='ok'?'正在读取当前照片':(p.message||'正在读取当前照片')});
    const v=versionRows.find(x=>x.name===$('#versionpick').value);
    const diff=versionDifference && versionDifference.name===$('#versionpick').value ? versionDifference : null;
    const examples=diff ? diff.items.slice(0,5).map(i=>`${i.label} ${i.before} → ${i.after}`).join('；') : '';
    $('#infobar').textContent=v?`版本：${v.name} · ${v.created||''}${v.note?' · '+v.note:''}。${diff?(diff.count?`与当前相差 ${diff.count} 项${examples?'：'+examples:''}${diff.count>5?' 等':''}`:'与当前完全相同'):'正在读取参数差异…'}`:'这张照片还没有保存过版本。';
    $('#cur').textContent=(p.photo||{}).name||photoName||'';
    showSwitching();
    pvctlShow(true); zoomLayout(); return;
  }
  zoomTrackPhoto();
  if (s.dataset.kind!==kind){
    s.dataset.kind=kind;
    if (kind==='demo') s.innerHTML=`<div class="frame has"><div class="scene"></div><span class="label">初始（示例）</span></div><div class="frame has"><div class="scene"></div><span class="label">当前（示例）</span><span class="note"></span></div>`;
    else { s.innerHTML=frameHTML('fi',PH_INITIAL,PH_INITIAL_TIP)+frameHTML('fc','当前'); s.ondblclick=toggleZoom; }
  }
  if (real) pvctlShow(false); else $('#pvctl').style.display = 'none';
  if (real) updatePickBtn();
  if (kind==='demo'){ $('#cur').textContent='界面演示 · 示例画面，非真实照片';
    zoomLayout(); s.children[1].querySelector('.scene').classList.toggle('after', !!nApplied());
    s.children[1].querySelector('.note').textContent = nApplied()?'已调整 '+nApplied()+' 项':'暂无调整'; $('#infobar').innerHTML=''; return; }
  if (kind==='none'){ $('#cur').textContent='';
    const t = noBackend ? '当前为静态页面，无预览（地址后加 #demo 可查看界面演示）' : '正在读取预览';
    setFrame('fi',{text:t}); setFrame('fc',{text:t}); $('#infobar').innerHTML=''; return; }
  const p = pv || {state:'loading', message:'正在读取预览'}, ph = p.photo || {};
  $('#cur').textContent = ph.name || photoName || '';
  showSwitching();
  if (p.state==='ok'){
    const n = nApplied(), pi = p.current;
    setFrame('fi',{url:p.initial.url});
    setFrame('fc',{url:p.current.url, busy:!!p.loading, note: p.same ? (n?'':'与初始一致') : (n?'已调整 '+n+' 项':'')});
    $('#infobar').innerHTML = `<div class="line">${esc(fmtInfo(ph))}</div><div>预览 ${pi.w&&pi.h?pi.w+' × '+pi.h+' 像素':''}${zoomNote()}。“初始”指软件首次读取该照片时的状态；若此前已在 Lightroom 中调整过，则不等同于原片。</div>`;
    zoomLayout();
  } else {
    const t = p.message || '正在读取预览';
    setFrame('fi',{text:t}); setFrame('fc',{text:t});
    $('#infobar').innerHTML = ph.name ? `<div class="line">${esc(fmtInfo(ph))}</div>` : '';
  }
}
/* 图库里点了另一张照片：Lightroom 回复、新预览送到之前，中栏先写“正在切换到 …”，大图变淡，由 preview 事件覆盖 */
let SWITCH = null;
function showSwitching(){
  const s=$('#stage'); s.classList.toggle('switching', !!SWITCH);
  if (SWITCH) $('#cur').textContent = '正在切换到 '+SWITCH.name+'…';
}
function markSwitching(id){
  const p = id && G.byId[id]; clearTimeout(markSwitching.t);
  const ph = (pv && pv.photo) || {};
  if (!p || !REAL() || ph.id===id){ if (SWITCH){ SWITCH=null; renderStage(); } return; }
  SWITCH = {id, name:p.name};
  markSwitching.t = setTimeout(()=>{ if (SWITCH){ SWITCH=null; renderStage(); } }, 15000);   // 保底：太久没有新预览就恢复原样
  renderStage();
}
function previewArrived(ev){
  const ph = ev.photo || {};
  if (SWITCH && (ph.id===SWITCH.id || ph.name===SWITCH.name || (ev.state!=='ok' && ev.state!=='loading'))){ SWITCH=null; clearTimeout(markSwitching.t); }
}
/* ---- 预览排列（1.3.0）：自动 / 左右 / 上下 / 滑动对比 ----
   每个预览框按“所显示照片的宽高比”（读不到时 3:2）在可用空间内 contain 缩放、居中：框的大小就是照片显示出来的大小，不拉伸、不被裁。
   自动：在“左右并排”和“上下排”里，选能让照片显示面积更大的那种（横图常选上下排，竖图自然选左右）；窗口大小/照片变化时重新算。
   滑动对比：只显示一张图，中间竖线（role=slider）可用鼠标/触摸拖动、左右方向键调整；左边“初始”右边“当前”。排列选择存 localStorage（键 lh_arrange）。 */
const ARR_KEY = 'lh_arrange', ARR_OK = ['auto', 'side', 'stack', 'slide'], ARR_GAP = 10, ARR_DEFAULT_RATIO = 1.5;
let ARR = 'auto', SLIDE = 50, ARR_NOW = 'side', SLIDE_DRAG = null;
try { const v = window.localStorage.getItem(ARR_KEY); if (ARR_OK.indexOf(v) >= 0) ARR = v; } catch(e){}
function arrRatio(){
  const imgs = document.querySelectorAll('#stage .pimg');
  for (const i of imgs){ if (i.naturalWidth > 0 && i.naturalHeight > 0 && i.closest('.frame.has')) return i.naturalWidth / i.naturalHeight; }
  const c = pv && pv.current; if (c && c.w > 0 && c.h > 0) return c.w / c.h;
  return ARR_DEFAULT_RATIO;
}
function arrFit(cw, ch, r){ const w = Math.max(0, Math.min(cw, ch * r)); return {w, h: w / r}; }
/* 每种排法下两张照片一共显示多大的面积（越大越好） */
function arrArea(mode, W, H, r){
  if (mode === 'slide'){ const f = arrFit(W, H, r); return f.w * f.h; }
  const cw = mode === 'side' ? (W - ARR_GAP) / 2 : W, ch = mode === 'side' ? H : (H - ARR_GAP) / 2, f = arrFit(cw, ch, r);
  return 2 * f.w * f.h;
}
function arrChoose(W, H, r){ return arrArea('stack', W, H, r) > arrArea('side', W, H, r) ? 'stack' : 'side'; }     // 面积相同时用左右并排
function arrangeLayout(){
  const s = $('#stage'); if (!s) return;
  const cs = getComputedStyle(s), W = s.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight), H = s.clientHeight - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom);
  const frames = Array.prototype.slice.call(s.querySelectorAll(':scope > .frame'));
  if (!frames.length || W <= 0 || H <= 0) return;
  const r = arrRatio(); ARR_NOW = ARR === 'auto' ? arrChoose(W, H, r) : ARR;
  ['arr-side', 'arr-stack', 'arr-slide'].forEach(c => s.classList.remove(c)); s.classList.add('arr-' + ARR_NOW); s.dataset.arr = ARR_NOW; s.dataset.ratio = r.toFixed(4);
  let cw = W, ch = H;
  if (ARR_NOW === 'side') cw = (W - ARR_GAP) / 2; else if (ARR_NOW === 'stack') ch = (H - ARR_GAP) / 2;
  const f = arrFit(cw, ch, r);
  frames.forEach(e => { e.style.width = f.w.toFixed(1) + 'px'; e.style.height = f.h.toFixed(1) + 'px'; });
  slideLayout();
}
/* 滑动对比的中间竖线 */
function slideLayout(){
  const s = $('#stage'); let h = $('#slidehandle');
  if (ARR_NOW !== 'slide' || !s.querySelector(':scope > .frame')){ if (h) h.remove(); s.style.removeProperty('--slide'); return; }
  if (!h){
    h = document.createElement('div'); h.id = 'slidehandle'; h.className = 'slidehandle'; h.tabIndex = 0; h.setAttribute('role', 'slider');
    h.setAttribute('aria-label', '初始与当前的对比位置'); h.setAttribute('aria-orientation', 'horizontal'); h.setAttribute('aria-valuemin', '0'); h.setAttribute('aria-valuemax', '100');
    h.title = '拖动或按左右方向键，对比初始（左）和当前（右）'; h.innerHTML = '<span class="knob" aria-hidden="true">⇆</span>';
    h.addEventListener('pointerdown', slideDown); h.addEventListener('keydown', slideKey); s.appendChild(h);
  }
  const fr = s.querySelector(':scope > .frame'), left = fr.offsetLeft, top = fr.offsetTop;
  s.style.setProperty('--slide', SLIDE + '%'); h.style.left = (left + fr.offsetWidth * SLIDE / 100) + 'px'; h.style.top = top + 'px'; h.style.height = fr.offsetHeight + 'px'; h.style.bottom = 'auto';
  h.setAttribute('aria-valuenow', String(Math.round(SLIDE))); h.setAttribute('aria-valuetext', '初始 ' + Math.round(SLIDE) + '%，当前 ' + (100 - Math.round(SLIDE)) + '%');
}
function slideSet(v){ SLIDE = Math.max(0, Math.min(100, v)); slideLayout(); }
function slideDown(e){
  if (e.pointerType === 'mouse' && e.button !== 0) return;
  SLIDE_DRAG = {id: e.pointerId}; $('#slidehandle').classList.add('drag'); try { e.currentTarget.setPointerCapture(e.pointerId); } catch(err){}
  e.preventDefault(); e.stopPropagation();
}
function slideKey(e){
  const step = e.shiftKey ? 10 : 2; let v = null;
  if (e.key === 'ArrowLeft') v = SLIDE - step; else if (e.key === 'ArrowRight') v = SLIDE + step; else if (e.key === 'Home') v = 0; else if (e.key === 'End') v = 100;
  if (v === null) return; e.preventDefault(); slideSet(v);
}
document.addEventListener('pointermove', e=>{
  if (!SLIDE_DRAG) return;
  const fr = document.querySelector('#stage > .frame'); if (!fr) return; const r = fr.getBoundingClientRect();
  if (r.width > 0) slideSet((e.clientX - r.left) / r.width * 100);
});
function slideUp(){ if (!SLIDE_DRAG) return; SLIDE_DRAG = null; const h = $('#slidehandle'); if (h) h.classList.remove('drag'); }
document.addEventListener('pointerup', slideUp); document.addEventListener('pointercancel', slideUp);
function arrUI(){ document.querySelectorAll('#arrange button').forEach(b => { const on = b.dataset.a === ARR; b.classList.toggle('on', on); b.setAttribute('aria-pressed', on ? 'true' : 'false'); }); }
$('#arrange').onclick = e => {
  const b = e.target.closest('button[data-a]'); if (!b) return; ARR = b.dataset.a;
  try { window.localStorage.setItem(ARR_KEY, ARR); } catch(err){}
  arrUI(); zoomLayout();
};
arrUI();

/* ---- 预览无级缩放（1.3.0）：滑杆 10%–400%（step 1）+ 预设“适合 / 50% / 100% / 200%” + 数字显示 ----
   ZOOM.mode：'fit'（适合窗口）或 'pct'（固定百分比；100% = 预览图的原始像素）。两个预览窗（初始/当前）共用同一个缩放和平移位置
   （平移位置用 0–1 的归一化中心 cx/cy 表示），所以同步。Ctrl+滚轮以鼠标位置为中心缩放；放大后按住鼠标拖动平移；
   双击在“适合”和 100% 之间切换。值写入设置 preview_zoom（"fit" 或整数），防抖保存；平移位置不保存。 */
const ZOOM_MIN = 10, ZOOM_MAX = 400;
let ZOOM = {mode:'fit', pct:100, cx:0.5, cy:0.5, photo:null}, zoomSaveT = null, PAN = null, zoomSuppressClick = false;
function pvctlShow(multi){ $('#pvctl').style.display = 'flex'; $('#edgebox').style.display = multi ? 'none' : ''; }
function zoomFrames(){ return Array.prototype.slice.call(document.querySelectorAll('#stage .frame.has')); }
function zoomGeom(f){
  const img = f.querySelector('.pimg'), sc = f.querySelector('.scroller'); if (!img || !sc) return null;
  const nw = img.naturalWidth, nh = img.naturalHeight, fw = sc.clientWidth, fh = sc.clientHeight;
  if (!nw || !nh || !fw || !fh) return null;
  const fit = Math.min(fw / nw, fh / nh), s = ZOOM.mode === 'fit' ? fit : ZOOM.pct / 100, w = nw * s, h = nh * s;
  let left = w <= fw ? (fw - w) / 2 : Math.min(0, Math.max(fw - w, fw / 2 - ZOOM.cx * w));
  let top = h <= fh ? (fh - h) / 2 : Math.min(0, Math.max(fh - h, fh / 2 - ZOOM.cy * h));
  return {img, nw, nh, fw, fh, fit, s, w, h, left, top};
}
function zoomLayout(){ arrangeLayout(); zoomApply(); }
function zoomApply(){
  const fr = zoomFrames(); let first = true;
  fr.forEach(f=>{
    const g = zoomGeom(f); if (!g) return;
    g.img.style.width = g.nw + 'px'; g.img.style.height = g.nh + 'px';
    g.img.style.transform = 'translate(' + g.left.toFixed(2) + 'px,' + g.top.toFixed(2) + 'px) scale(' + g.s + ')';
    if (first){ first = false;
      if (g.w > g.fw) ZOOM.cx = (g.fw / 2 - g.left) / g.w; else ZOOM.cx = 0.5;      // 把越界的中心收回到范围内，避免平移时“攒”出隐形位移
      if (g.h > g.fh) ZOOM.cy = (g.fh / 2 - g.top) / g.h; else ZOOM.cy = 0.5;
      ZOOM.shownPct = g.s * 100; ZOOM.canPan = g.w > g.fw + 0.5 || g.h > g.fh + 0.5; }
  });
  const st = $('#stage'); if (st){ st.classList.toggle('zoomed', !!ZOOM.canPan); }
  zoomUI();
}
function zoomNote(){ return ZOOM.mode === 'fit' ? '' : '（' + ZOOM.pct + '% 显示）'; }
function zoomUI(){
  const shown = Math.round(ZOOM.shownPct || (ZOOM.mode === 'fit' ? 100 : ZOOM.pct));
  const r = $('#zoomrange'); r.value = String(Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, ZOOM.mode === 'fit' ? shown : ZOOM.pct)));
  $('#zoomtxt').textContent = ZOOM.mode === 'fit' ? '适合 · ' + shown + '%' : ZOOM.pct + '%';
  document.querySelectorAll('#zoomctl .zp').forEach(b=>{
    const z = b.dataset.z, on = z === 'fit' ? ZOOM.mode === 'fit' : (ZOOM.mode === 'pct' && ZOOM.pct === Number(z));
    b.setAttribute('aria-pressed', on ? 'true' : 'false'); b.classList.toggle('on', on); });
}
function zoomSaveSoon(){
  clearTimeout(zoomSaveT);
  zoomSaveT = setTimeout(async()=>{
    if (!REAL()) return;
    try { await window.pywebview.api.save_settings({preview_zoom: ZOOM.mode === 'fit' ? 'fit' : ZOOM.pct}, false); } catch(e){ console.warn('保存预览缩放失败', e); }
  }, 600);
}
function zoomClampPct(v){ v = Math.round(Number(v)); return isNaN(v) ? 100 : Math.max(ZOOM_MIN, Math.min(ZOOM_MAX, v)); }
/* 设成固定百分比；anchor = {frame, x, y}（窗口坐标）时，保持鼠标下的那一点不动 */
function zoomSetPct(pct, anchor){
  pct = zoomClampPct(pct);
  let u = null, g0 = null;
  if (anchor){ g0 = zoomGeom(anchor.frame); if (g0){ const r = anchor.frame.querySelector('.scroller').getBoundingClientRect();
    u = {x:(anchor.x - r.left - g0.left) / g0.w, y:(anchor.y - r.top - g0.top) / g0.h, fx:anchor.x - r.left, fy:anchor.y - r.top}; } }
  ZOOM.mode = 'pct'; ZOOM.pct = pct;
  if (u && g0){ const w1 = g0.nw * pct / 100, h1 = g0.nh * pct / 100;
    ZOOM.cx = u.x + (g0.fw / 2 - u.fx) / w1; ZOOM.cy = u.y + (g0.fh / 2 - u.fy) / h1; }
  zoomLayout(); zoomSaveSoon(); renderZoomInfo();
}
function zoomSetFit(){ ZOOM.mode = 'fit'; ZOOM.cx = ZOOM.cy = 0.5; zoomLayout(); zoomSaveSoon(); renderZoomInfo(); }
function renderZoomInfo(){ const el = document.querySelector('#infobar div:nth-child(2)'); if (el && pv && pv.state === 'ok' && el.textContent.indexOf('预览 ') === 0){
  const pi = pv.current || {}; el.childNodes[0].textContent = '预览 ' + (pi.w && pi.h ? pi.w + ' × ' + pi.h + ' 像素' : '') + zoomNote() + '。“初始”指软件首次读取该照片时的状态；若此前已在 Lightroom 中调整过，则不等同于原片。'; } }
function zoomFromSettings(s){
  const z = s && s.preview_zoom;
  if (typeof z === 'number' && z >= ZOOM_MIN && z <= ZOOM_MAX && Math.round(z) === z){ ZOOM.mode = 'pct'; ZOOM.pct = z; }
  else { ZOOM.mode = 'fit'; }
  ZOOM.cx = ZOOM.cy = 0.5; zoomLayout();
}
function zoomTrackPhoto(){ const id = ((pv && pv.photo) || {}).id; if (id !== ZOOM.photo){ ZOOM.photo = id; ZOOM.cx = ZOOM.cy = 0.5; } }
function toggleZoom(e){
  if (!REAL()) return;
  if (ZOOM.mode === 'fit'){ const f = e && e.target && e.target.closest ? e.target.closest('.frame') : null;
    zoomSetPct(100, f ? {frame:f, x:e.clientX, y:e.clientY} : null); }
  else zoomSetFit();
}
document.querySelectorAll('#zoomctl .zp').forEach(b=>{ b.onclick = ()=>{ if (b.dataset.z === 'fit') zoomSetFit(); else zoomSetPct(Number(b.dataset.z), null); }; });
$('#zoomrange').addEventListener('input', ()=>zoomSetPct($('#zoomrange').value, null));
/* Ctrl+滚轮：以鼠标位置为中心缩放（不带 Ctrl 的滚轮不处理）；每格约 ±10% */
$('#stage').addEventListener('wheel', e=>{
  if (!e.ctrlKey || !REAL()) return;
  const f = e.target.closest ? e.target.closest('.frame.has') : null; if (!f) return;
  e.preventDefault();
  const g = zoomGeom(f); if (!g) return;
  const cur = ZOOM.mode === 'fit' ? g.fit * 100 : ZOOM.pct, factor = Math.pow(1.1, e.deltaY < 0 ? 1 : -1);
  let next = Math.round(cur * factor); if (next === Math.round(cur)) next += e.deltaY < 0 ? 1 : -1;
  zoomSetPct(next, {frame:f, x:e.clientX, y:e.clientY});
}, {passive:false});
/* 放大后按住鼠标拖动平移（两个预览窗一起动） */
$('#stage').addEventListener('pointerdown', e=>{
  if (e.button !== 0 || !ZOOM.canPan) return;
  const f = e.target.closest ? e.target.closest('.frame.has') : null; if (!f) return;
  const g = zoomGeom(f); if (!g) return;
  PAN = {x:e.clientX, y:e.clientY, w:g.w, h:g.h, moved:false}; e.preventDefault();
});
document.addEventListener('pointermove', e=>{
  if (!PAN) return;
  const dx = e.clientX - PAN.x, dy = e.clientY - PAN.y;
  if (!PAN.moved && Math.abs(dx) < 3 && Math.abs(dy) < 3) return;
  if (!PAN.moved){ PAN.moved = true; $('#stage').classList.add('panning'); }
  ZOOM.cx -= dx / PAN.w; ZOOM.cy -= dy / PAN.h; PAN.x = e.clientX; PAN.y = e.clientY; zoomLayout();
});
function panEnd(){ if (!PAN) return; if (PAN.moved){ zoomSuppressClick = true; setTimeout(()=>{ zoomSuppressClick = false; }, 80); } PAN = null; $('#stage').classList.remove('panning'); }
document.addEventListener('pointerup', panEnd); document.addEventListener('pointercancel', panEnd);
$('#stage').addEventListener('dblclick', e=>{ if (zoomSuppressClick) return; }, true);
window.addEventListener('resize', ()=>zoomLayout());
if (window.ResizeObserver){ new ResizeObserver(()=>zoomLayout()).observe($('#stage')); }
/* 顶栏的预览清晰度：立即生效并写进设置（只提交这一项），重启和保存设置时都不会被改回去 */
$('#edge').onchange=async()=>{
  if (!REAL()) return;
  const v = parseInt($('#edge').value,10), api = window.pywebview.api;
  let r = null;
  try { r = await api.save_settings({preview_edge: v}, false); } catch(e){}
  if (r && r.ok){ if (SET && SET.settings) SET.settings.preview_edge = r.settings.preview_edge; return; }
  try { await api.set_preview_edge(v); } catch(e){}      // 没能写进设置：至少这次先生效
  toast('预览清晰度已切换，但没能保存到设置，下次打开会恢复原值。');
};
setTimeout(()=>{ if(!REAL()){ noBackend=true; renderStage(); } }, 2500);
