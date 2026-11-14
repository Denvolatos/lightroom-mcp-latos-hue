/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- left tabs ---- */
let ltab = 'preset';
function renderLeftDemo(){
  const p = $('#lpane'); p.innerHTML = '';
  if (ltab==='preset') PRESETS.forEach(x=>{
    const d=document.createElement('div'); d.className='list-item';
    d.innerHTML=`<span class="name">${x}</span><span class="star ${favP.has(x)?'on':''}">★</span>`;
    d.querySelector('.star').onclick=e=>{e.stopPropagation(); favP.has(x)?favP.delete(x):favP.add(x); renderLeft();};
    d.onclick=()=>toast('应用预设「'+x+'」：功能开发中'); p.appendChild(d); });
  if (ltab==='fav'){ const l=[...PHOTOS.filter((_,i)=>fav.has(i)).map(x=>'照片 · '+x.n), ...[...favP].map(x=>'预设 · '+x)];
    if(!l.length) p.innerHTML='<div class="empty">暂无收藏。点击 ★ 添加收藏。</div>';
    l.forEach(x=>{const d=document.createElement('div'); d.className='list-item'; d.innerHTML=`<span class="name">${x}</span>`; p.appendChild(d);}); }
  if (ltab==='exp') { EXPERIENCE.forEach(x=>{const d=document.createElement('div'); d.className='list-item'; d.innerHTML=`<span class="name">${x}</span>`; p.appendChild(d);});
    p.insertAdjacentHTML('beforeend','<div class="empty">经验仅保存在本机，由 AI 记录。</div>'); }
}
$('#ltabs').onclick = e => { const t=e.target.closest('.tab'); if(!t) return;
  document.querySelectorAll('#ltabs .tab').forEach(x=>x.classList.toggle('on',x===t)); ltab=t.dataset.t;
  if (REAL() && ltab==='preset' && LB.sub==='lr' && !LB.lr) loadLr(); renderLeft(); };
/* ---- 预设 / 收藏 / 经验（真实模式；演示模式仍用上面的示例数据）---- */
const LB = {sub:'mine', presets:null, sel:null, strength:100, lrq:'', lr:null, lrSel:null, notes:null, nq:'', ntag:'', nsel:null, fav:null, err:'',
  lrDraft:null, nqDraft:null, lrSeq:0, nSeq:0};    // lrDraft/nqDraft：搜索框里打了但还没按回车的字，重绘左栏时保留
const lapi = () => window.pywebview.api;
async function loadLib(which){
  if (!REAL()) return;
  try {
    if (!which || which==='p') LB.presets = await lapi().lib_presets();
    if (!which || which==='n'){ const seq = ++LB.nSeq; const n = await lapi().lib_notes(LB.nq, LB.ntag); if (seq===LB.nSeq) LB.notes = n; }   // 只接受最新一次搜索的结果
    if (!which || which==='f') LB.fav = await lapi().lib_favs();
    LB.err = '';
  } catch(e){ LB.err = '无法读取预设、经验或收藏，请重试。'; }
  renderLeft(); renderFiles();
}
function lbOpen(title){ $('#lb_title').textContent = title; $('#lmask').classList.add('show'); }
function lbClose(){ $('#lmask').classList.remove('show'); }
function lbSet(body, buttons){
  $('#lb_body').innerHTML = body; const f = $('#lb_foot'); f.innerHTML = '';
  (buttons||[]).forEach(b=>{ const e=document.createElement('button'); e.className='btn '+(b.cls||''); e.textContent=b.label; e.disabled=!!b.disabled; if(b.id) e.id=b.id; e.onclick=b.onclick; f.appendChild(e); });
}
function promptDialog(title, label, value, maxlen, multi){
  return new Promise(res=>{
    lbOpen(title);
    lbSet(`<div class="prow"><span class="lab">${esc(label)}</span><div>${multi ? `<textarea id="pd_in" maxlength="${maxlen}" rows="4"></textarea>` : `<input type="text" id="pd_in" maxlength="${maxlen}">`}
      <div class="mute">不超过 ${maxlen} 个字。</div></div></div>`,
      [{label:'取消', onclick:()=>{ lbClose(); res(null); }}, {label:'确定', cls:'primary', onclick:()=>{ const v=$('#pd_in').value; lbClose(); res(v); }}]);
    $('#pd_in').value = value||''; $('#pd_in').focus();
  });
}
const GROUP_NAMES = {tone:'色调', color:'色彩', detail:'细节与效果', curve:'曲线', wb:'白平衡', crop:'裁剪与拉直'};
const photoReady = () => !!(photoName || (SEL && SEL.count>0));

function subSeg(opts, cur, attr){ return `<div class="subseg">${opts.map(o=>`<button data-${attr}="${o[0]}" class="${cur===o[0]?'on':''}">${o[1]}</button>`).join('')}</div>`; }
function starHtml(on, attrs){ return `<span class="star ${on?'on':''}" ${attrs} title="${on?'取消收藏':'收藏'}">★</span>`; }

function renderLeft(){
  const p = $('#lpane');
  if (!REAL()) return renderLeftDemo();
  let h = '';
  if (LB.err) h += `<div class="empty bad">${esc(LB.err)}</div>`;
  if (ltab==='preset') h += presetTabHtml(); else if (ltab==='fav') h += favTabHtml(); else h += noteTabHtml();
  const ae = document.activeElement, fid = ae && p.contains(ae) && ae.id ? ae.id : null;   // 重绘前记下焦点和光标位置
  let ss = null; try { if (fid && ae.selectionStart!=null) ss = [ae.selectionStart, ae.selectionEnd]; } catch(e){}
  p.innerHTML = h; p.dataset.k = '';
  bindLeft(p);
  const f = fid && p.querySelector('#'+fid);
  if (f){ f.focus({preventScroll:true}); if (ss) try { f.setSelectionRange(ss[0], ss[1]); } catch(e){} }
}
function presetTabHtml(){
  let h = subSeg([['mine','我的预设'],['lr','Lightroom 预设']], LB.sub, 'sub');
  if (LB.sub==='mine'){
    const L = LB.presets;
    h += `<div class="tools"><button class="btn small primary" id="pr_save" title="把当前照片的调整保存为预设，仅保存在本机">保存当前照片的调整为预设</button><button class="btn small" id="pr_imp">导入</button></div>`;
    if (!L) return h + '<div class="empty">正在读取…</div>';
    if (!L.presets.length) return h + '<div class="empty">还没有预设。调整好一张照片后，点击“保存当前照片的调整为预设”。预设只保存在本机，软件不预装任何预设。</div>';
    L.presets.forEach(x=>{ h += `<div class="list-item${LB.sel===x.id?' sel':''}" data-pid="${esc(x.id)}"><span class="name">${esc(x.name)}</span>${starHtml(x.fav, `data-fav="preset" data-key="${esc(x.name)}"`)}</div>`; });
    const s = L.presets.find(x=>x.id===LB.sel);
    if (s) h += `<div class="detail"><div class="dn">${esc(s.name)}</div><div class="dm">分组：${esc(s.groups.join('、'))}　·　${s.count} 项参数</div>${s.note?`<div class="dm">${esc(s.note)}</div>`:''}
      <div class="dm"><label>强度 <input type="range" id="pr_str" min="1" max="100" value="${LB.strength}"> <span id="pr_strv">${LB.strength}%</span></label></div>
      <div class="tools"><button class="btn small primary" id="pr_apply" ${photoReady()?'':'disabled title="请先在 Lightroom 中选择照片"'}>套用到当前照片</button>
      <button class="btn small" id="pr_ren">重命名</button><button class="btn small" id="pr_note">编辑备注</button><button class="btn small" id="pr_exp">导出</button><button class="btn small" id="pr_del">删除</button></div></div>`;
    return h;
  }
  h += `<div class="tools"><input type="text" id="lr_q" placeholder="搜索名称或分组（一个词）" value="${esc(LB.lrDraft!=null?LB.lrDraft:LB.lrq)}"><button class="btn small" id="lr_go">搜索</button></div>`;
  if (!LB.lr) return h + '<div class="empty">正在读取 Lightroom 预设…</div>';
  if (!LB.lr.ok) return h + `<div class="empty bad">${esc(LB.lr.message)}</div>`;
  const hidden = Number(LB.lr.hidden_masks)||0;      // 后端默认过滤掉含蒙版的预设，并告诉我们过滤了几个；没有这个字段就不显示
  if (hidden>0) h += `<div class="dm pad">已隐藏 ${hidden} 个含蒙版的预设（本软件用不了）</div>`;
  if (LB.lr.note) h += `<div class="dm pad">${esc(LB.lr.note)}</div>`;
  LB.lr.groups.forEach(g=>{ h += `<div class="folder">${esc(g.folder)}</div>`;
    g.presets.forEach(x=>{ h += `<div class="list-item${LB.lrSel===x.id?' sel':''}" data-lid="${esc(x.id)}"><span class="name${x.masks?' dim':''}">${esc(x.name)}${x.masks?'（含蒙版）':''}</span>${starHtml(x.fav, `data-fav="lr_preset" data-key="${esc(x.key)}" data-label="${esc(x.name)}"`)}</div>`; }); });
  let sel = null; LB.lr.groups.forEach(g=>g.presets.forEach(x=>{ if (x.id===LB.lrSel) sel = x; }));
  if (sel) h += `<div class="detail"><div class="dn">${esc(sel.name)}</div>${sel.masks?'<div class="dm bad">该预设包含蒙版（局部调整），无法套用。</div>':'<div class="dm">套用前会显示确认清单；改前保存完整快照，可撤销。</div>'}
    <div class="tools"><button class="btn small primary" id="lr_apply" ${(sel.masks||!photoReady())?'disabled':''}>套用到当前照片</button></div></div>`;
  return h;
}
function favTabHtml(){
  const F = LB.fav; if (!F) return '<div class="empty">正在读取…</div>';
  let h = `<div class="tools"><button class="btn small" id="fv_photo" ${photoReady()?'':'disabled'}>${F.photo_fav?'取消收藏当前照片':'收藏当前照片'}</button></div>`;
  if (!F.total) return h + '<div class="empty">暂无收藏。可在预设、经验列表或当前照片旁点击 ★ 添加收藏。</div>';
  const sec = (title, arr, kind)=>{ if (!arr.length) return ''; let s = `<div class="folder">${title}（${arr.length}）</div>`;
    arr.forEach(x=>{ s += `<div class="list-item" data-fk="${kind}" data-key="${esc(x.key)}"><span class="name">${esc(x.label)}</span>${starHtml(true, `data-fav="${kind}" data-key="${esc(x.key)}"`)}</div>`; }); return s; };
  h += sec('我的预设', F.groups.preset, 'preset') + sec('Lightroom 预设', F.groups.lr_preset, 'lr_preset') + sec('经验', F.groups.note, 'note') + sec('照片', F.groups.photo, 'photo');
  h += '<div class="dm pad" id="fv_info"></div>';
  return h;
}
function noteTabHtml(){
  const N = LB.notes; 
  let h = `<div class="tools"><button class="btn small primary" id="nt_new">新建经验</button><button class="btn small" id="nt_imp">导入</button><button class="btn small" id="nt_exp">导出</button></div>`;
  if (!N) return h + '<div class="empty">正在读取…</div>';
  h += `<div class="tools"><input type="text" id="nt_q" placeholder="搜索标题、正文、标签" value="${esc(LB.nqDraft!=null?LB.nqDraft:LB.nq)}"><select id="nt_tag"><option value="">全部标签</option>${N.tags.map(t=>`<option value="${esc(t)}" ${LB.ntag===t?'selected':''}>${esc(t)}</option>`).join('')}</select></div>`;
  if (!N.notes.length) h += (LB.nq||LB.ntag) ? '<div class="empty">没有符合条件的经验。</div>' : '<div class="empty">还没有经验。点击“新建经验”记录你自己的调色心得，或在 AI 完成一次调整后点击“把这次做法记成经验”。经验只保存在本机，软件不预装任何经验。</div>';
  N.notes.forEach(n=>{ h += `<div class="list-item" data-nid="${esc(n.id)}"><span class="name">${esc(n.title)}<span class="sub2">${esc([n.scene, ...n.tags].filter(Boolean).join(' · '))}${n.use_in_chat?'':' · 不参与对话'}</span></span>${starHtml(n.fav, `data-fav="note" data-key="${esc(n.id)}"`)}</div>`; });
  h += `<div class="dm pad">${N.context.eligible ? `开启“让 AI 参考我的经验库”时，新对话将提供最近的 ${N.context.used} 条（共 ${N.context.eligible} 条参与对话${N.context.truncated?'，超出长度上限的已舍弃':''}）。` : '没有“参与对话”的经验，AI 不会收到经验资料。'}</div>`;
  return h;
}

function bindLeft(p){
  p.querySelectorAll('[data-sub]').forEach(b=>b.onclick=()=>{ LB.sub = b.dataset.sub; if (LB.sub==='lr' && !LB.lr) loadLr(); renderLeft(); });
  p.querySelectorAll('.star[data-fav]').forEach(s=>s.onclick=async e=>{ e.stopPropagation();
    const r = await lapi().lib_fav_toggle(s.dataset.fav, s.dataset.key, s.dataset.label||''); if (!r.ok) return toast(r.message||'无法收藏');
    await loadLib(); if (s.dataset.fav==='lr_preset') loadLr(true); });
  p.querySelectorAll('[data-pid]').forEach(d=>d.onclick=()=>{ LB.sel = LB.sel===d.dataset.pid ? null : d.dataset.pid; renderLeft(); });
  p.querySelectorAll('[data-lid]').forEach(d=>d.onclick=()=>{ LB.lrSel = LB.lrSel===d.dataset.lid ? null : d.dataset.lid; renderLeft(); });
  p.querySelectorAll('[data-nid]').forEach(d=>d.onclick=()=>openNote(d.dataset.nid));
  p.querySelectorAll('[data-fk]').forEach(d=>d.onclick=()=>favClick(d.dataset.fk, d.dataset.key));
  const on = (id, fn)=>{ const e = p.querySelector('#'+id); if (e) e.onclick = fn; };
  on('pr_save', openSavePreset); on('pr_imp', importPreset); on('pr_apply', ()=>applyMine()); on('pr_ren', renamePreset); on('pr_note', notePreset);
  on('pr_exp', exportPreset); on('pr_del', deletePreset); on('lr_go', ()=>{ LB.lrq = p.querySelector('#lr_q').value; LB.lrDraft = null; loadLr(); }); on('lr_apply', ()=>applyLr());
  on('nt_new', ()=>openNote(null)); on('nt_imp', importNotes); on('nt_exp', exportNotes);
  on('fv_photo', async()=>{ const r = await lapi().lib_fav_toggle('photo','',''); if (!r.ok) toast(r.message||'无法收藏'); loadLib('f'); });
  const str = p.querySelector('#pr_str'); if (str) str.oninput = ()=>{ LB.strength = parseInt(str.value,10); p.querySelector('#pr_strv').textContent = LB.strength+'%'; };
  const q = p.querySelector('#lr_q'); if (q){ q.oninput = ()=>{ LB.lrDraft = q.value; }; q.onkeydown = e=>{ if (e.key==='Enter'){ LB.lrq = q.value; LB.lrDraft = null; loadLr(); } }; }
  const nq = p.querySelector('#nt_q'); if (nq){ nq.oninput = ()=>{ LB.nqDraft = nq.value; }; nq.onkeydown = e=>{ if (e.key==='Enter'){ LB.nq = nq.value; LB.nqDraft = null; loadLib('n'); } }; }
  const nt = p.querySelector('#nt_tag'); if (nt) nt.onchange = ()=>{ LB.ntag = nt.value; LB.nq = p.querySelector('#nt_q').value; LB.nqDraft = null; loadLib('n'); };
}
async function loadLr(keep){
  const seq = ++LB.lrSeq;                 // 连按搜索时只接受最新一次的结果，先发出的慢请求不会覆盖
  if (!keep) LB.lr = null; renderLeft();
  let r; try { r = await lapi().lib_lr_presets(LB.lrq); } catch(e){ r = {ok:false, message:'无法读取 Lightroom 预设。'}; }
  if (seq!==LB.lrSeq) return;
  LB.lr = r; renderLeft();
}
function favClick(kind, key){
  if (kind==='preset'){ const x = (LB.presets&&LB.presets.presets||[]).find(p=>p.name===key); ltab='preset'; LB.sub='mine'; if (x) LB.sel = x.id; tabsOn(); renderLeft(); }
  else if (kind==='note'){ openNote(key); }
  else if (kind==='lr_preset'){ ltab='preset'; LB.sub='lr'; LB.lrq=''; LB.lrDraft=null; tabsOn(); loadLr(); }
  else { const i = $('#fv_info'); if (i) i.textContent = '照片收藏仅记录名称与收藏时间。软件暂时不能在 Lightroom 中自动选中该照片，请在 Lightroom 中自行选择。'; }
}
function tabsOn(){ document.querySelectorAll('#ltabs .tab').forEach(x=>x.classList.toggle('on', x.dataset.t===ltab)); }

/* 保存为预设 */
async function openSavePreset(){
  if (!photoReady()) return infoDialog('无法保存', '请先在 Lightroom 中选择一张照片。');
  const o = await safeCall(()=>lapi().lib_preset_options()); if (!o || !o.limits) return;
  lbOpen('保存当前照片的调整为预设');
  lbSet(`<div class="prow"><span class="lab">名称</span><div><input type="text" id="sp_name" maxlength="${o.limits.name}" placeholder="不超过 ${o.limits.name} 个字"></div></div>
    <div class="prow"><span class="lab">备注</span><div><textarea id="sp_note" rows="3" maxlength="${o.limits.note}" placeholder="可选，不超过 ${o.limits.note} 个字"></textarea></div></div>
    <div class="prow"><span class="lab">包含的分组</span><div>${o.groups.map(g=>`<label class="radio"><input type="checkbox" class="sp_g" value="${g.id}" ${g.default?'checked':''}> ${esc(g.label)}</label>`).join('')}
      <div class="mute">默认不含裁剪与拉直；预设不含局部调整（蒙版）。仅保存本软件允许修改的参数，只保存在本机。</div></div></div>
    <div class="bad" id="sp_err"></div>`,
    [{label:'取消', onclick:lbClose}, {label:'保存', cls:'primary', id:'sp_ok', onclick:()=>doSavePreset(false)}]);
  $('#sp_name').focus();
}
async function doSavePreset(overwrite){
  const groups = [...document.querySelectorAll('.sp_g:checked')].map(c=>c.value);
  $('#sp_ok').disabled = true;
  const r = await safeCall(()=>lapi().lib_preset_save($('#sp_name').value, $('#sp_note').value, groups, overwrite), $('#sp_ok'));
  if (!r) return;
  if (r.exists){ $('#sp_ok').disabled = false; if (await askDialog('覆盖预设', r.message, '覆盖')) return doSavePreset(true); return; }
  if (!r.ok){ $('#sp_err').textContent = r.message||'无法保存。'; $('#sp_ok').disabled = false; return; }
  lbClose(); toast(r.message); LB.sel = r.id; ltab='preset'; LB.sub='mine'; tabsOn(); loadLib();
}
/* 套用：确认清单 */
async function applyMine(){
  const r = await safeCall(()=>lapi().lib_apply_prepare('mine', LB.sel, LB.strength));
  if (r) applyConfirmView(r);
}
async function applyLr(){ const r = await safeCall(()=>lapi().lib_apply_prepare('lr', LB.lrSel, 100)); if (r) applyConfirmView(r); }
function applyConfirmView(r){
  if (!r.ok) return infoDialog(r.nothing ? '无需套用' : '无法套用', r.message||'无法生成确认清单。');
  lbOpen('确认套用');
  const rows = r.items.map(i=>`<tr><td>${esc(i.label)}</td><td class="num">${esc(i.current)}</td><td class="num">→ ${esc(i.new)}${i.clipped?' <span class="st-wait">（已裁剪到范围）</span>':''}</td></tr>`).join('');
  lbSet(`<div class="big">${esc(r.title)}</div><div class="mute">目标照片：${esc(r.photo||'当前照片')}</div>
    ${r.items.length ? `<table><thead><tr><th>参数</th><th>当前</th><th>新值</th></tr></thead><tbody>${rows}</tbody></table>` : ''}
    ${r.note ? `<div class="sumbox">${esc(r.note)}</div>` : ''}
    ${r.skipped&&r.skipped.length ? `<div class="mute">这张照片没有以下参数，已跳过：${esc(r.skipped.join('、'))}。</div>` : ''}
    ${r.clipped ? `<div class="warn">有 ${r.clipped} 项超出允许范围，已裁剪到边界。</div>` : ''}
    <div class="mute">写入后可在右侧“本次调整”中撤销。</div><div class="bad" id="ap_err"></div>`,
    [{label:'取消', onclick:async()=>{ try { await lapi().lib_apply_cancel(); } catch(e){} lbClose(); }},
     {label:'确认套用', cls:'primary', id:'ap_ok', onclick:async()=>{ $('#ap_ok').disabled = true; const w = await safeCall(()=>lapi().lib_apply_confirm(r.token), $('#ap_ok'));
        if (!w) return;
        if (!w.ok){ $('#ap_err').textContent = w.message||'无法套用。'; $('#ap_ok').disabled = !!w.readonly; return; }
        lbClose(); toast(w.message); }}]);
}
async function renamePreset(){
  const x = LB.presets.presets.find(p=>p.id===LB.sel); const v = await promptDialog('重命名预设', '新名称', x.name, 40, false); if (v===null) return;
  const r = await lapi().lib_preset_rename(LB.sel, v); if (!r.ok) return infoDialog('无法重命名', r.message); LB.sel = r.id; loadLib();
}
async function notePreset(){
  const x = LB.presets.presets.find(p=>p.id===LB.sel); const v = await promptDialog('编辑备注', '备注', x.note, 200, true); if (v===null) return;
  const r = await lapi().lib_preset_note(LB.sel, v); if (!r.ok) return infoDialog('无法保存', r.message); loadLib('p');
}
async function deletePreset(){
  const x = LB.presets.presets.find(p=>p.id===LB.sel);
  if (!await askDialog('删除预设', `将删除预设“${x.name}”，此操作不能撤销（不影响已套用的照片）。是否继续？`, '删除')) return;
  const r = await lapi().lib_preset_delete(LB.sel); if (!r.ok) return infoDialog('无法删除', r.message); LB.sel = null; loadLib();
}
async function exportPreset(){ const r = await lapi().lib_preset_export(LB.sel); if (r.cancelled) return; toast(r.ok ? '已导出预设文件' : (r.message||'导出失败')); }
async function importPreset(){
  const r = await lapi().lib_preset_import(); if (r.cancelled) return;
  if (r.exists){ const yes = await askDialog('覆盖预设', r.message, '覆盖'); const c = await lapi().lib_preset_import_commit(yes); if (!yes) return; if (!c.ok) return infoDialog('无法导入', c.message); toast(c.message); return loadLib(); }
  if (!r.ok) return infoDialog('无法导入', r.message); toast(r.message); loadLib();
}

/* 经验：查看 / 编辑 / 新建 */
function openNote(id){
  const n = id ? (LB.notes&&LB.notes.notes||[]).find(x=>x.id===id) : null;
  if (id && !n) return;
  noteEditor(n || {title:'', scene:'', tags:[], body:'', use_in_chat:true}, id||'', '');
}
function noteEditor(n, id, banner, back){
  lbOpen(id ? '编辑经验' : '新建经验');
  lbSet(`${banner||''}<div class="prow"><span class="lab">标题</span><div><input type="text" id="ne_title" maxlength="60" placeholder="不超过 60 字"></div></div>
    <div class="prow"><span class="lab">场景</span><div><input type="text" id="ne_scene" maxlength="30" placeholder="可选，不超过 30 字，例如：雪山、逆光人像"></div></div>
    <div class="prow"><span class="lab">标签</span><div><input type="text" id="ne_tags" placeholder="最多 5 个，每个不超过 16 字，用逗号分隔"></div></div>
    <div class="prow"><span class="lab">正文</span><div><textarea id="ne_body" rows="9" maxlength="2000" placeholder="不超过 2000 字。建议写明具体参数、依据与效果。"></textarea><div class="mute" id="ne_cnt"></div></div></div>
    <div class="prow"><span class="lab">参与对话</span><div><label class="radio"><input type="checkbox" id="ne_use"> 新对话开始时可作为 AI 的参考资料</label></div></div>
    <div class="bad" id="ne_err"></div>`,
    [id ? {label:'删除', onclick:async()=>{ if (!await askDialog('删除经验', `将删除经验“${n.title}”，此操作不能撤销。是否继续？`, '删除')) return;
        const r = await lapi().lib_note_delete(id); if (!r.ok) return infoDialog('无法删除', r.message); lbClose(); loadLib(); }} : null,
     {label:'取消', onclick:lbClose}, {label:'保存', cls:'primary', id:'ne_ok', onclick:()=>saveNote(id)}].filter(Boolean));
  $('#ne_title').value = n.title||''; $('#ne_scene').value = n.scene||''; $('#ne_tags').value = (n.tags||[]).join('，'); $('#ne_body').value = n.body||''; $('#ne_use').checked = n.use_in_chat!==false;
  const cnt = ()=>{ $('#ne_cnt').textContent = $('#ne_body').value.length+' / 2000'; }; $('#ne_body').oninput = cnt; cnt();
}
async function saveNote(id){
  const tags = $('#ne_tags').value.split(/[,，、;；]+/).map(s=>s.trim()).filter(Boolean);
  $('#ne_ok').disabled = true;
  const r = await safeCall(()=>lapi().lib_note_save(id, {title:$('#ne_title').value, scene:$('#ne_scene').value, tags, body:$('#ne_body').value, use_in_chat:$('#ne_use').checked}), $('#ne_ok'));
  if (!r) return;
  if (!r.ok){ $('#ne_err').textContent = r.message||'无法保存。'; $('#ne_ok').disabled = false; return; }
  lbClose(); toast('经验已保存'); ltab='exp'; tabsOn(); loadLib();
}
async function importNotes(){
  const r = await lapi().lib_notes_import(); if (r.cancelled) return;
  if (!r.ok) return infoDialog('无法导入', r.message); toast(r.message); loadLib();
}
async function exportNotes(){ const r = await lapi().lib_notes_export(); if (r.cancelled) return; if (!r.ok) return infoDialog('无法导出', r.message); toast('已导出经验库'); }

/* 记成经验 */
function offerRecord(){
  document.querySelectorAll('.recbtn').forEach(e=>e.remove());
  if (!REAL() || !rows.some(r=>r.status==='已应用')) return;
  const d = document.createElement('div'); d.className = 'note recbtn'; d.innerHTML = '<button class="btn small">把这次做法记成经验</button>';
  $('#msgs').appendChild(d); d.scrollIntoView(); d.querySelector('button').onclick = startRecord;
}
let REC = null;     // 正在起草的经验：'starting' 请求还没返回 / 'run' 已开始；完成事件到了就清掉
function recCloseNow(){ REC = null; try { lapi().lib_record_close(); } catch(e){} lbClose(); }
async function startRecord(){
  REC = 'starting';            // 先打开转圈页再请求：完成事件比接口返回先到时也能正常显示结果
  lbOpen('把这次做法记成经验');
  lbSet(`<div class="big"><span class="spin"></span>正在请 AI 起草经验…</div><div class="mute">只总结已确认并已应用的调整。AI 不会直接写入经验库；生成后你可以编辑，点击“保存”才会写入。</div>`,
        [{label:'停止', onclick:async(e)=>{ e.target.disabled = true; try { await lapi().lib_record_stop(); } catch(e2){ return recCloseNow(); }
            setTimeout(()=>{ if (REC) lbSet('<div class="big">已停止</div><div class="mute">没有收到 AI 的结果，可以关闭后重试。</div>', [{label:'关闭', onclick:recCloseNow}]); }, 4000); }}]);
  const r = await safeCall(()=>lapi().lib_record_start());
  if (REC!=='starting') return;                    // 结果已经显示了
  if (!r){ REC = null; lbClose(); return; }
  if (!r.ok){ REC = null; lbClose(); return infoDialog('无法生成草稿', r.message); }
  REC = 'run';
}
function onRecordDone(ev){
  if (!REC || !$('#lmask').classList.contains('show')) return;
  REC = null;
  const usage = `<div class="mute">用时 ${ev.elapsed} 秒${ev.tokens?'，约 '+Number(ev.tokens).toLocaleString()+' token':''}${ev.cost!=null?'，估算费用 $'+Number(ev.cost).toFixed(3):''}（估算值，非实际账单）。</div>`;
  lapi().lib_record_close();
  if (ev.ok){
    noteEditor(ev.draft, '', `<div class="sumbox">这是 AI 起草的经验草稿，尚未保存。请核对内容，可直接修改；点击“保存”后才会写入经验库。</div>${usage}`);
    return;
  }
  lbSet(`<div class="big">未能生成经验草稿</div><div class="warn">${esc(ev.message)}</div>${ev.raw?`<div class="rawbox">${esc(ev.raw)}</div>`:''}${usage}`,
    [{label:'关闭', onclick:lbClose}, {label:'手动新建', cls:'primary', onclick:()=>noteEditor({title:'', scene:'', tags:[], body:'', use_in_chat:true}, '', '')}]);
}
