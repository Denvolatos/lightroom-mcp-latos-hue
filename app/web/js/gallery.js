/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- 图库（软件内浏览与选择照片；Lightroom 只是后台引擎）---- */
const GAL_MAX_SEL = 50;
const G = {st:null, byId:{}, thumbs:{}, failed:{}, sel:[], active:null, anchor:null, q:'', sort:'name', filter:'all', collapsed:{},
  order:[], cells:new Map(), cellSig:new Map(), sig:null, qTimer:null, vis:new Set(), busySel:false, wantSel:null, io:null, reqTimer:null, loadTimer:null, demo:false};
const gapi = () => window.pywebview.api;
function gmsg(t, bad){ const m=$('#gal_msg'); m.textContent=t||''; m.classList.toggle('bad', !!bad); }
function galDemoState(){
  const stars=[3,0,1,0,2,0], flags=['pick','none','none','reject','none','none'];
  return {ok:true, state:'ready', message:'', base:'示例', base_exists:true, in_catalog:true, lr_connected:true, total:PHOTOS.length, limit:2000, truncated:false,
    not_added:0, missing:0, thumbs:{}, failed:{}, selection:{ids:[], active:null}, add:null,
    photos:PHOTOS.map((p,i)=>({id:'demo-'+i, name:p.n, group:p.f, format:'JPG', rating:stars[i], flag:flags[i], captured:'2026-01-0'+(i+1), w:6000, h:4000, vc:false, added:true, missing:false, color:p.c}))};
}
async function loadGallery(){
  if (!REAL()){ G.demo=true; G.st=galDemoState(); afterState(); return; }
  G.demo=false;
  let st; try { st = await gapi().library_state(); } catch(e){ st = {ok:true, state:'error', message:'无法读取图库，请点击“刷新”重试。', photos:[], thumbs:{}, failed:{}, selection:{ids:[],active:null}, add:null, total:0}; }
  G.st = st; G.thumbs = Object.assign({}, st.thumbs||{}); G.failed = Object.assign({}, st.failed||{});
  if (!G.busySel){ G.sel = (st.selection&&st.selection.ids)||[]; G.active = (st.selection&&st.selection.active)||null; }
  afterState();
}
function afterState(){
  G.byId = {}; (G.st.photos||[]).forEach(p=>G.byId[p.id]=p);
  G.sel = G.sel.filter(i=>G.byId[i]); if (!G.byId[G.active]) G.active = G.sel.length ? G.sel[G.sel.length-1] : null;
  buildGallery();
}
function galVisible(){
  const q = G.q.trim().toLowerCase(), f = G.filter;
  return (G.st.photos||[]).filter(p=> (!q || p.name.toLowerCase().indexOf(q)>=0) &&
    (f==='all' || (f==='rated' && (p.rating||0)>=1) || (f==='pick' && p.flag==='pick') || (f==='new' && !p.added)));
}
function galCmp(a,b){
  const k = p => G.sort==='time' ? [p.captured?0:1, String(p.captured||''), p.name.toLowerCase()] : [p.name.toLowerCase()];
  const x=k(a), y=k(b); for (let i=0;i<x.length;i++){ if (x[i]<y[i]) return -1; if (x[i]>y[i]) return 1; } return 0;
}
function galGroups(list){
  const g = {}; list.forEach(p=>{ (g[p.group]=g[p.group]||[]).push(p); });
  const root = '（未分类）';
  return Object.keys(g).sort((a,b)=> ((a===root?0:1)-(b===root?0:1)) || a.toLowerCase().localeCompare(b.toLowerCase()))
    .map(n=>({name:n, photos:g[n].sort(galCmp)}));
}
function timgState(p){
  const url = G.thumbs[p.id], bad = G.failed[p.id];
  if (G.demo) return {cls:'timg', style:` style="background:linear-gradient(160deg,${esc(p.color||'#667')},#2b3138)"`, inner:''};
  if (url) return {cls:'timg', style:'', inner:`<img src="${esc(url)}" alt="" draggable="false" onerror="galImgErr(this)">`};
  if (!p.added) return {cls:'timg na', style:'', inner:`<span class="ph2">${esc(p.format)}</span>`};
  if (bad) return {cls:'timg fail', style:'', inner:`<span class="ph2" title="${esc(bad)}">读取失败</span><button class="retry" data-id="${esc(p.id)}">重试</button>`};
  return {cls:'timg load', style:'', inner:''};
}
function cellInner(p){
  const t = timgState(p);
  const meta = ((p.rating||0)>0 ? `<span class="stars" title="${p.rating} 星">${'★'.repeat(Math.min(5,p.rating))}</span>` : '') +
    (p.flag==='pick' ? '<span class="flag pick" title="留用">留用</span>' : (p.flag==='reject' ? '<span class="flag reject" title="排除">排除</span>' : ''));
  const tag = !p.added ? '<span class="tag" title="照片在软件文件夹里，但还没有加入 Lightroom 目录">尚未加入</span>'
    : (p.missing ? '<span class="tag bad" title="目录里有记录，但磁盘上找不到该文件">文件缺失</span>' : '');
  return `<div class="${t.cls}"${t.style}>${t.inner}<span class="fmt">${esc(p.format)}</span>${p.vc?'<span class="vc">副本</span>':''}${tag}${meta?`<span class="meta">${meta}</span>`:''}</div><div class="cname">${esc(p.name)}</div>`;
}
function galImgErr(img){ const c=img.closest('.cell'); if (!c) return; const id=c.dataset.id; delete G.thumbs[id]; G.failed[id]='缩略图无法显示'; refreshCell(id); }
function cellHtml(p){
  return `<div class="cell${p.added?'':' na'}" data-id="${esc(p.id)}" title="${esc(p.name)}${p.captured?'　'+esc(p.captured):''}">${cellInner(p)}</div>`;
}
function refreshCell(id){ const el=G.cells.get(id), p=G.byId[id]; if (!el||!p) return; el.className='cell'+(p.added?'':' na'); el.innerHTML=cellInner(p); applySelClass(el,id); G.cellSig.set(id, cellHtml(p)); }
function applySelClass(el,id){ el.classList.toggle('sel', G.sel.indexOf(id)>=0); el.classList.toggle('act', id===G.active); }
function applySelClasses(){ G.cells.forEach((el,id)=>applySelClass(el,id)); }
function buildGallery(){
  const box=$('#gal_scroll'), st=G.st, top=box.scrollTop;
  $('#gal_title').textContent = '浏览照片' + (st.total ? `（${st.total} 张）` : '') + (st.state==='loading' && st.total ? '　正在刷新…' : '');
  $('#gal_scope').textContent = st.base ? `当前浏览：${st.base}（含子文件夹；导入位置在设置中单独选择）` : '选择照片文件夹后，可浏览其中及子文件夹的照片';
  const listMode = !(st.state==='idle' || (st.state==='loading' && !(st.photos||[]).length)) && st.state!=='error' && !!st.base && !!st.total;
  const groups = listMode ? galGroups(galVisible()) : null;
  const sig = listMode ? 'L|'+groups.map(g=>g.name+':'+(G.collapsed[g.name]?1:0)+':'+g.photos.map(p=>p.id+(p.added?'+':'-')).join(',')).join('|') : null;
  /* 照片 id、分组、折叠都没变（例如刷新只是把“正在读取”变成“就绪”）：不重建格子，只更新内容有变化的那几格 */
  if (sig && sig===G.sig && G.cells.size){
    let changed = 0;
    groups.forEach(g=>g.photos.forEach(p=>{ const el=G.cells.get(p.id);
      if (el && G.cellSig.get(p.id)!==cellHtml(p)){ el.title = p.name+(p.captured?'　'+p.captured:''); refreshCell(p.id); changed++; } }));
    if (changed) scheduleThumbs();          // 有格子变回“读取中”时，补要一次可见格子的缩略图
    applySelClasses(); renderBar(); return;
  }
  G.sig = sig;
  if (G.io){ G.io.disconnect(); } G.cells.clear(); G.cellSig.clear(); G.vis.clear(); G.order=[];
  let h='';
  if (st.state==='idle' || (st.state==='loading' && !(st.photos||[]).length)){ h = `<div class="gempty"><span class="spin"></span>正在读取图库…</div>`; }
  else if (st.state==='error'){ h = `<div class="gempty" style="color:var(--bad)">${esc(st.message||'无法读取图库。')}</div>`; }
  else if (!st.base){ h = `<div class="gempty">选择已有照片的文件夹，即可浏览其中的照片。导入副本保存到哪里，请在“设置”中选择。<br><button class="btn small" id="gal_choose">选择照片文件夹</button></div>`; }
  else if (!st.total){
    h = `<div class="gempty">此文件夹中还没有照片。点击“换目录”可浏览已有照片；导入的照片会存到设置中的照片工作文件夹。手动放入照片后请点击“刷新”，再选择“加入 Lightroom”。` +
      (st.base_exists ? '' : `<br>软件文件夹尚不存在，完成一次导入后会自动创建。`) +
      `<div class="gpath">${esc(st.base)}</div><button class="btn small" id="gal_open2">在资源管理器中打开</button></div>`;
  } else {
    if (!groups.length) h = `<div class="gempty">没有符合条件的照片。</div>`;
    groups.forEach(g=>{
      const closed = !!G.collapsed[g.name];
      h += `<div class="ghead" data-g="${esc(g.name)}"><span>${closed?'▸':'▾'}</span><span class="gn">${esc(g.name)}</span><span class="gc">${g.photos.length}</span></div>`;
      h += `<div class="ggrid${closed?' hide':''}">` + g.photos.map(cellHtml).join('') + `</div>`;
      if (!closed) g.photos.forEach(p=>G.order.push(p.id));
    });
  }
  box.innerHTML = h; box.scrollTop = top;
  box.querySelectorAll('.cell').forEach(el=>{ const id=el.dataset.id; G.cells.set(id, el); if (G.byId[id]) G.cellSig.set(id, cellHtml(G.byId[id])); applySelClass(el, id); });
  const o2=$('#gal_open2'); if (o2) o2.onclick=openBaseFolder;
  const choose=$('#gal_choose'); if (choose) choose.onclick=changeGalleryFolder;
  if (!G.demo && 'IntersectionObserver' in window){
    G.io = new IntersectionObserver(es=>{ es.forEach(e=>{ const id=e.target.dataset.id; if (e.isIntersecting) G.vis.add(id); else G.vis.delete(id); }); scheduleThumbs(); },
      {root:box, rootMargin:'240px'});
    G.cells.forEach((el,id)=>{ if (!el.parentElement.classList.contains('hide')) G.io.observe(el); });
  }
  renderBar();
}
function scheduleThumbs(){ clearTimeout(G.reqTimer); G.reqTimer=setTimeout(()=>requestThumbs(false), 80); }
async function requestThumbs(retry){
  if (G.demo || !REAL()) return;
  const ids=[...G.vis].filter(i=>G.byId[i] && G.byId[i].added).slice(0,120); if (!ids.length) return;
  let r; try { r = await gapi().library_thumbnails(ids, !!retry); } catch(e){ return; }
  if (!r || !r.ok){ if (r && r.message) gmsg(r.message, true); return; }
  applyThumbs(Object.entries(r.thumbs||{}).map(([id,v])=>Object.assign({id}, v)));
}
function applyThumbs(items){
  items.forEach(it=>{ if (!G.byId[it.id]) return;
    if (it.url){ if (G.thumbs[it.id]!==it.url){ G.thumbs[it.id]=it.url; delete G.failed[it.id]; refreshCell(it.id); } }
    else if (it.error && it.error.indexOf('尚未加入')<0){ if (G.failed[it.id]!==it.error){ delete G.thumbs[it.id]; G.failed[it.id]=it.error; refreshCell(it.id); } } });
}
/* ---- 顶部：已选、清除、加入 Lightroom ---- */
function renderBar(){
  const st=G.st, bar=$('#gal_bar'); if (!st || st.state==='error' || st.state==='idle' || !(st.photos||[]).length){ bar.innerHTML=''; return; }
  const n=G.sel.length;
  let h = `<div class="gline"><span class="gsel">已选 ${n} 张</span><button class="btn small" id="gal_clear" ${n?'':'disabled'}>清除选择</button></div>`;
  const add=st.add, na=st.not_added||0;
  if (add && add.state==='running'){
    const pct=add.n?Math.round(100*add.i/add.n):0;
    h += `<div class="gbox"><div>正在加入 Lightroom：第 ${Math.min(add.i+1,add.n)}/${add.n} 张　${esc(add.name||'')}</div><div class="bar"><i style="width:${pct}%"></i></div><button class="btn small" id="gal_addcancel">取消</button></div>`;
  } else if (add && add.state==='done'){
    const c=add.counts||{}; const parts=[`已加入 ${c.added||0} 张`]; if (c.uncertain) parts.push(`需确认 ${c.uncertain} 张`); if (c.failed) parts.push(`失败 ${c.failed} 张`);
    if (c.pending) parts.push(`尚未加入 ${c.pending} 张（Lightroom 未连接）`); if (add.cancelled) parts.push('已取消');
    const probs=(add.problems||[]).slice(0,5).map(p=>`<div>${esc(p.name)}：${esc(p.reason)}</div>`).join('');
    h += `<div class="gbox"><div>${esc(parts.join('　'))}</div>${probs}${(add.problems||[]).length>5?`<div>另有 ${add.problems.length-5} 项未列出。</div>`:''}<div style="margin-top:4px"><button class="btn small" id="gal_addclose">知道了</button></div></div>`;
  } else if (na>0){
    h += `<div class="gline"><span class="gwarn">${na} 张尚未加入 Lightroom</span><button class="btn small primary" id="gal_add">加入 Lightroom</button></div>`;
  }
  if (st.truncated) h += `<div class="gwarn">${esc(st.truncated_message||'仅显示前 2000 张。')}</div>`;
  if ((st.missing||0)>0) h += `<div>${st.missing} 张照片的文件缺失（目录里有记录，磁盘上找不到）。</div>`;
  bar.innerHTML=h;
  const b=(id,fn)=>{ const e=$('#'+id); if (e) e.onclick=fn; };
  b('gal_clear', clearSel); b('gal_add', addToLr); b('gal_addcancel', ()=>gapi().library_cancel_add());
  b('gal_addclose', async()=>{ await gapi().library_close_add(); if (G.st) G.st.add=null; renderBar(); });
}
/* ---- 点选：单击 / Ctrl 增减 / Shift 区间 / Ctrl+A 全选；选中同步到 Lightroom，以 Lightroom 实际选区为准 ---- */
function limitSel(ids, active){
  if (ids.length>GAL_MAX_SEL){ gmsg(`一次最多选择 ${GAL_MAX_SEL} 张，已选择前 ${GAL_MAX_SEL} 张。`); ids=ids.slice(0,GAL_MAX_SEL); if (ids.indexOf(active)<0) active=ids[ids.length-1]; }
  return {ids, active};
}
function cellClick(id, e){
  const p=G.byId[id]; if (!p) return;
  if (!p.added){ gmsg('该照片尚未加入 Lightroom，请先点击“加入 Lightroom”。'); return; }
  let ids, active=id;
  if (e.shiftKey && G.anchor && G.order.indexOf(G.anchor)>=0 && G.order.indexOf(id)>=0){
    const a=G.order.indexOf(G.anchor), b=G.order.indexOf(id), seg=G.order.slice(Math.min(a,b), Math.max(a,b)+1).filter(i=>G.byId[i].added);
    ids = a<=b ? seg : seg.reverse();
  } else if (e.ctrlKey || e.metaKey){
    const had=G.sel.indexOf(id)>=0; ids = had ? G.sel.filter(i=>i!==id) : G.sel.concat([id]);
    G.anchor=id; if (had) active = ids.length ? ids[ids.length-1] : null;
  } else { ids=[id]; G.anchor=id; }
  if (!ids.length){ clearSel(); return; }
  gmsg('');
  const r=limitSel(ids, active); G.sel=r.ids; G.active=r.active; applySelClasses(); renderBar();
  markSwitching(r.active); sendSel();
}
function selectAllShown(){
  const ids=G.order.filter(i=>G.byId[i] && G.byId[i].added); if (!ids.length) return;
  gmsg(''); const r=limitSel(ids, ids[0]); G.sel=r.ids; G.active=r.ids[0]; G.anchor=r.ids[0]; applySelClasses(); renderBar(); sendSel();
}
async function sendSel(){
  if (G.demo || !REAL()) return;
  if (G.busySel){ G.wantSel={ids:[...G.sel], active:G.active}; return; }
  G.busySel=true; let want={ids:[...G.sel], active:G.active}, last=null;
  while (want){
    G.wantSel=null;
    try { last = await gapi().library_select(want.ids, want.active); } catch(e){ last = {ok:false, message:'选择失败，请重试。', selected:G.sel, active:G.active}; }
    if (G.wantSel){ want=G.wantSel; continue; }          // 等待期间又点选了：只处理最后一次
    want=null;
  }
  G.busySel=false;
  if (last){
    G.sel=(last.selected||[]).filter(i=>G.byId[i]); G.active=last.active||(G.sel.length?G.sel[G.sel.length-1]:null);
    if (last.message) gmsg(last.message, !last.ok); else if (!last.ok) gmsg('选择未生效。', true);
    if (!last.ok || !G.active) markSwitching(null); else if (SWITCH && SWITCH.id!==G.active) markSwitching(G.active);
  }
  applySelClasses(); renderBar();
}
async function clearSel(){
  G.sel=[]; G.active=null; G.anchor=null; applySelClasses(); renderBar();
  if (G.demo || !REAL()) return;
  try { const r=await gapi().library_clear_selection(); if (r && r.message) gmsg(r.message); } catch(e){}
}
async function addToLr(){
  const r=await safeCall(()=>gapi().library_add_missing()); if (!r) return; if (!r.ok) gmsg(r.message||'无法加入。', true); else gmsg('');
}
async function openBaseFolder(){ if (!REAL()) return; const r=await gapi().open_library(); if (!r.ok) toast(r.message); }
async function changeGalleryFolder(){
  if (!REAL()) return;
  const r=await gapi().gallery_pick_folder();
  if (!r.ok){ if (r.message) gmsg(r.message, true); return; }
  G.collapsed={}; G.q=''; $('#gal_q').value=''; gmsg(''); loadGallery();
}
function onLibraryEvent(ev){
  if (ev.type==='library_changed'){ clearTimeout(G.loadTimer); G.loadTimer=setTimeout(loadGallery, 40); }
  else if (ev.type==='library_thumbs'){ applyThumbs(ev.items||[]); }
  else if (ev.type==='library_selection'){ if (!G.busySel){ G.sel=(ev.ids||[]).filter(i=>G.byId[i]); G.active=ev.active||null; applySelClasses(); renderBar(); } }
  else if (ev.type==='library_meta'){ (ev.items||[]).forEach(it=>{ const p=G.byId[it.id]; if (p){ p.rating=it.rating; p.flag=it.flag; refreshCell(it.id); } }); }
  else if (ev.type==='library_add'){ if (G.st){ G.st.add = ev; renderBar(); } }
}
$('#gal_scroll').addEventListener('click', e=>{
  const rt=e.target.closest('.retry'); if (rt){ e.stopPropagation(); delete G.failed[rt.dataset.id]; refreshCell(rt.dataset.id); G.vis.add(rt.dataset.id); requestThumbs(true); return; }
  const hd=e.target.closest('.ghead'); if (hd){ G.collapsed[hd.dataset.g]=!G.collapsed[hd.dataset.g]; buildGallery(); return; }
  $('#gal_scroll').focus({preventScroll:true});
  const c=e.target.closest('.cell'); if (c) cellClick(c.dataset.id, e);          // 点空白处不清除选择
});
$('#gal').addEventListener('keydown', e=>{
  const tag=(document.activeElement&&document.activeElement.tagName)||'';
  if ((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='a' && tag!=='INPUT' && tag!=='SELECT'){ e.preventDefault(); selectAllShown(); }
});
$('#gal_q').oninput=()=>{ clearTimeout(G.qTimer); G.qTimer=setTimeout(()=>{ G.q=$('#gal_q').value; if (G.st) buildGallery(); }, 200); };   // 停顿 0.2 秒再筛选，打字时不卡
$('#gal_sort').onchange=()=>{ G.sort=$('#gal_sort').value; if (G.st) buildGallery(); };
$('#gal_filter').onchange=()=>{ G.filter=$('#gal_filter').value; if (G.st) buildGallery(); };
$('#gal_refresh').onclick=async()=>{ if (G.demo||!REAL()) return; gmsg(''); G.st=Object.assign({}, G.st, {state:'loading'}); buildGallery(); try { await gapi().library_refresh(); } catch(e){} };
$('#gal_open').onclick=openBaseFolder;
$('#gal_change').onclick=changeGalleryFolder;
