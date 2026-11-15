/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- 图库（软件内浏览与选择照片；Lightroom 只是后台引擎）---- */
const GAL_MAX_SEL = 50;
const G = {st:null, byId:{}, thumbs:{}, failed:{}, sel:[], active:null, anchor:null, q:'', sort:'captured', dir:'desc', sortTouched:false, sortTimer:null, filter:'all', collapsed:{},
  order:[], cells:new Map(), cellSig:new Map(), sig:null, qTimer:null, vis:new Set(), busySel:false, wantSel:null, io:null, reqTimer:null, loadTimer:null, demo:false};
const gapi = () => window.pywebview.api;
const GAL_SORTS = ['captured','imported','name','size','rating','flag','label','modified','edited','type'];
function gmsg(t, bad){ const m=$('#gal_msg'); m.textContent=t||''; m.classList.toggle('bad', !!bad); }
function galDemoState(){
  const stars=[3,0,1,0,2,0], flags=['pick','none','none','reject','none','none'];
  return {ok:true, state:'ready', message:'', base:'示例', base_exists:true, in_catalog:true, lr_connected:true, total:PHOTOS.length, limit:2000, truncated:false,
    not_added:0, missing:0, thumbs:{}, failed:{}, selection:{ids:[], active:null}, add:null,
    photos:PHOTOS.map((p,i)=>({id:'demo-'+i, name:p.n, group:p.f, format:'JPG', rating:stars[i], flag:flags[i], captured:'2026-01-0'+(i+1), w:6000, h:4000, vc:false, added:true, missing:false, color:p.c, size:4000000+i*1000, mtime:1760000000+i*86400, label:null, edited:i%2===0, added_at:'2026-01-0'+(i+1)+'T10:00:00'}))};
}
async function loadGallery(){
  if (!REAL()){ G.demo=true; G.st=galDemoState(); afterState(); return; }
  G.demo=false;
  let st; try { st = await gapi().library_state(); } catch(e){ st = {ok:true, state:'error', message:'无法读取图库，请点击“刷新”重试。', photos:[], thumbs:{}, failed:{}, selection:{ids:[],active:null}, add:null, total:0}; }
  G.st = st; G.thumbs = Object.assign({}, st.thumbs||{}); G.failed = Object.assign({}, st.failed||{});
  if (!G.busySel){ G.sel = (st.selection&&st.selection.ids)||[]; G.active = (st.selection&&st.selection.active)||null; }
  afterState();
}
function galSyncSortCtl(){
  const sel=$('#gal_sort'), btn=$('#gal_dir'), asc=G.dir==='asc';
  if (sel) sel.value=G.sort;
  if (btn){ btn.textContent = asc ? '↑ 升序' : '↓ 降序';
    const t = (asc?'升序':'降序')+'（点击切换为'+(asc?'降序':'升序')+'）';
    btn.title=t; btn.setAttribute('aria-label','排序方向：'+(asc?'升序':'降序')+'，点击切换为'+(asc?'降序':'升序')); }
}
function galSaveSort(){
  if (G.demo || !REAL()) return;
  clearTimeout(G.sortTimer);
  G.sortTimer=setTimeout(async()=>{ try { const r=await gapi().gallery_set_sort(G.sort, G.dir); if (r && r.ok===false) console.warn('保存排序失败', r.message||''); }
    catch(e){ console.warn('保存排序失败', e); } }, 400);
}
function afterState(){
  /* 用户本次还没动过排序时，以后端保存的选择为准；动过之后以界面为准，不被刷新覆盖 */
  const ss=G.st&&G.st.sort, so=G.st&&G.st.order;
  if (!G.sortTouched && GAL_SORTS.indexOf(ss)>=0){ G.sort=ss; if (so==='asc'||so==='desc') G.dir=so; }
  galSyncSortCtl();
  G.byId = {}; (G.st.photos||[]).forEach(p=>G.byId[p.id]=p);
  G.sel = G.sel.filter(i=>G.byId[i]); if (!G.byId[G.active]) G.active = G.sel.length ? G.sel[G.sel.length-1] : null;
  buildGallery();
}
function galVisible(){
  const q = G.q.trim().toLowerCase(), f = G.filter;
  return (G.st.photos||[]).filter(p=> (!q || p.name.toLowerCase().indexOf(q)>=0) &&
    (f==='all' || (f==='rated' && (p.rating||0)>=1) || (f==='pick' && p.flag==='pick') || (f==='new' && !p.added)));
}
/* 排序全部在这里做。每个键给出“排序值”：null 表示没有这项数据，不论升降序都排在最后；同值再按文件名（不分大小写，始终升序） */
const galNameKey = p => String(p.name||'').toLowerCase();
const galStr = v => (v===null||v===undefined||v==='') ? null : String(v).toLowerCase();
const galNum = v => (typeof v==='number' && isFinite(v)) ? v : null;
const GAL_KEY = {
  captured: p=>(p.captured ? String(p.captured) : null),
  imported: p=>(p.added_at ? String(p.added_at) : null),
  name:     p=>galNameKey(p),
  size:     p=>galNum(p.size),
  rating:   p=>(galNum(p.rating)||0),
  flag:     p=>(p.flag==='pick' ? 2 : p.flag==='reject' ? 0 : 1),
  label:    p=>galStr(p.label),
  modified: p=>galNum(p.mtime),
  edited:   p=>(p.edited===true ? 1 : 0),
  type:     p=>galStr(p.format)
};
function galCmp(a,b){
  const f = GAL_KEY[G.sort] || GAL_KEY.name, x=f(a), y=f(b), sign = G.dir==='asc' ? 1 : -1;
  if (x===null && y!==null) return 1;
  if (y===null && x!==null) return -1;
  if (x!==null && y!==null && x!==y) return (x<y ? -1 : 1) * sign;
  const nx=galNameKey(a), ny=galNameKey(b);
  return nx<ny ? -1 : nx>ny ? 1 : (a.id<b.id ? -1 : a.id>b.id ? 1 : 0);
}
function galGroups(list){
  const g = {}; list.forEach(p=>{ (g[p.group]=g[p.group]||[]).push(p); });
  const root = '（未分类）', sign = G.dir==='asc' ? 1 : -1;
  return Object.keys(g).sort((a,b)=>{
    if (a===root || b===root) return (a===root?0:1)-(b===root?0:1);      // “（未分类）”始终在最前
    const x=a.toLowerCase(), y=b.toLowerCase(); return (x<y ? -1 : x>y ? 1 : 0) * sign; })
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
  const tag = !p.added ? '<span class="tag" title="照片已在照片库里，但还没有同步到 Lightroom，暂时不能选中或修图">未同步</span>'
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
  $('#gal_title').textContent = '照片'; $('#gal_count').textContent = (st.total ? st.total + ' 张' : '') + (st.state==='loading' && st.total ? ' · 正在刷新…' : '');
  $('#gal_scope').textContent = st.base ? `照片库：${st.base}（含子文件夹；导入的照片按拍摄日期放进来）` : '还没有选择照片工作文件夹，请先在“设置”里选择。';
  const listMode = !(st.state==='idle' || (st.state==='loading' && !(st.photos||[]).length)) && st.state!=='error' && !!st.base && !!st.total;
  const groups = listMode ? galGroups(galVisible()) : null;
  const sig = listMode ? 'L|'+G.sort+G.dir+'|'+groups.map(g=>g.name+':'+(G.collapsed[g.name]?1:0)+':'+g.photos.map(p=>p.id+(p.added?'+':'-')).join(',')).join('|') : null;
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
  else if (!st.base){ h = `<div class="gempty">还没有选择照片工作文件夹。请先在“设置”里选择它，这里就是你的照片库。<br><button class="btn small" id="gal_settings">打开设置</button></div>`; }
  else if (!st.total){
    h = `<div class="gempty">还没有照片。点“导入”，从存储卡或文件夹把照片放进来。<br><button class="btn small primary" id="gal_import">导入</button>` +
      (st.base_exists ? '' : `<br>照片工作文件夹尚不存在，完成一次导入后会自动创建。`) +
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
  const imp=$('#gal_import'); if (imp) imp.onclick=()=>startImport();
  const gs=$('#gal_settings'); if (gs) gs.onclick=()=>{ if (typeof openSettings==='function') openSettings(); };
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
/* ---- 顶部：已选、清除、同步到 Lightroom ---- */
function renderBar(){
  const st=G.st, bar=$('#gal_bar'); if (!st || st.state==='error' || st.state==='idle' || !(st.photos||[]).length){ bar.innerHTML=''; return; }
  const n=G.sel.length;
  let h = `<div class="gline"><span class="gsel">已选 ${n} 张</span><button class="btn small" id="gal_clear" ${n?'':'disabled'}>清除选择</button></div>`;
  const add=st.add, na=st.not_added||0;
  if (add && add.state==='running'){
    const pct=add.n?Math.round(100*add.i/add.n):0;
    h += `<div class="gbox"><div>正在同步到 Lightroom：第 ${Math.min(add.i+1,add.n)}/${add.n} 张　${esc(add.name||'')}</div><div class="bar"><i style="width:${pct}%"></i></div><button class="btn small" id="gal_addcancel">取消</button></div>`;
  } else if (add && add.state==='done'){
    const c=add.counts||{}; const parts=[`已同步 ${c.added||0} 张`]; if (c.uncertain) parts.push(`需确认 ${c.uncertain} 张`); if (c.failed) parts.push(`失败 ${c.failed} 张`);
    if (c.pending) parts.push(`未同步 ${c.pending} 张（Lightroom 未连接）`); if (add.cancelled) parts.push('已取消');
    const probs=(add.problems||[]).slice(0,5).map(p=>`<div>${esc(p.name)}：${esc(p.reason)}</div>`).join('');
    h += `<div class="gbox"><div>${esc(parts.join('　'))}</div>${probs}${(add.problems||[]).length>5?`<div>另有 ${add.problems.length-5} 项未列出。</div>`:''}<div style="margin-top:4px"><button class="btn small" id="gal_addclose">知道了</button></div></div>`;
  } else if (na>0){
    h += `<div class="gline"><span class="gwarn">${na} 张照片还没同步到 Lightroom，同步后才能选中和修图</span><button class="btn small primary" id="gal_add">同步到 Lightroom</button></div>`;
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
  if (!p.added){ gmsg('这张照片还没同步到 Lightroom，暂时不能选中。点上方“同步到 Lightroom”即可。'); return; }
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
  const r=await safeCall(()=>gapi().library_add_missing()); if (!r) return; if (!r.ok) gmsg(r.message||'无法同步。', true); else gmsg('');
}
async function openBaseFolder(){ if (!REAL()) return; const r=await gapi().open_library(); if (!r.ok) toast(r.message); }
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
$('#gal_sort').onchange=()=>{ G.sort=$('#gal_sort').value; G.sortTouched=true; galSyncSortCtl(); galSaveSort(); if (G.st) buildGallery(); };
$('#gal_dir').onclick=()=>{ G.dir = G.dir==='asc' ? 'desc' : 'asc'; G.sortTouched=true; galSyncSortCtl(); galSaveSort(); if (G.st) buildGallery(); };
$('#gal_filter').onchange=()=>{ G.filter=$('#gal_filter').value; if (G.st) buildGallery(); };
$('#gal_refresh').onclick=async()=>{ if (G.demo||!REAL()) return; gmsg(''); G.st=Object.assign({}, G.st, {state:'loading'}); buildGallery(); try { await gapi().library_refresh(); } catch(e){} };
$('#gal_open').onclick=openBaseFolder;
galSyncSortCtl();
