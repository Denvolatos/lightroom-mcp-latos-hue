/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- import ---- */
let IM = {cat:'', stage:null, pstage:null, seq:0};
const fmtSize = n => n>=1073741824 ? (n/1073741824).toFixed(2)+' GB' : n>=1048576 ? (n/1048576).toFixed(1)+' MB' : n>=1024 ? (n/1024).toFixed(1)+' KB' : n+' B';
const fmtTime = s => { s=Math.round(s||0); return String(Math.floor(s/60)).padStart(2,'0')+':'+String(s%60).padStart(2,'0'); };
function imOpen(title){ $('#im_title').textContent=title; $('#imask').classList.add('show'); }
function imClose(){ $('#imask').classList.remove('show'); IM.stage=null; IM.pstage=null; }
function imSet(body, buttons){   // buttons: [{label, cls, onclick, disabled, id}]
  $('#im_body').innerHTML=body; const f=$('#im_foot'); f.innerHTML='';
  (buttons||[]).forEach(b=>{ const e=document.createElement('button'); e.className='btn '+(b.cls||''); e.textContent=b.label; e.disabled=!!b.disabled; if(b.id) e.id=b.id; e.onclick=b.onclick; f.appendChild(e); });
}
function infoDialog(title, text){ return askDialog(title, text, '知道了'); }
async function startImport(){
  if (!REAL()) return toast('界面演示中，导入不可用');
  if (IM.stage) { $('#imask').classList.add('show'); return; }
  IM.cat=''; IM.stage='scanning';      // 先置状态：扫描很快结束时，完成事件可能先于本函数返回
  const r = await safeCall(()=>window.pywebview.api.choose_source_folder());
  if (!r){ IM.stage=null; return; }    // 出错时一定要清掉阶段，否则以后点“导入”都打不开选择文件夹
  if (!r.ok){ IM.stage=null; if (r.message) await infoDialog('无法导入', r.message); return; }
  if (IM.stage==='scanning') imScanning(0);
}
function imScanning(n){
  imOpen('导入照片');
  imSet(`<div class="big">正在扫描来源文件夹</div><div class="mute">已找到 ${n} 张照片。扫描只读取文件名，不会改动存储卡上的任何内容。</div>`,
    [{label:'取消', onclick:async()=>{ try { await window.pywebview.api.import_cancel(); } catch(e){} imClose(); }}]);
}
async function imConfirm(){
  IM.stage='confirm'; imOpen('导入照片');
  const cur = $('#im_cat') ? $('#im_cat').value : IM.cat, seq = ++IM.seq;
  let p; try { p = await window.pywebview.api.import_prepare(cur); } catch(e){ p = {errors:{_:'无法读取导入信息，请关闭后重试。'}}; }
  if (seq!==IM.seq || IM.stage!=='confirm') return;       // 更新的一次已经发出，或弹窗已关
  /* 等待期间用户可能又打了字：用输入框现在的内容重建，并放回焦点和光标，不吞字 */
  const live = $('#im_cat'), typed = live ? live.value : cur, hadFocus = !!live && document.activeElement===live;
  let ss = null; if (hadFocus) try { ss = [live.selectionStart, live.selectionEnd]; } catch(e){}
  if (!p.found){ imSet(`<div class="bad">${esc((p.errors&&p.errors._)||'没有可导入的内容。')}</div>`, [{label:'关闭', onclick:async()=>{ try { await window.pywebview.api.import_close(); } catch(e){} imClose(); }}]); return; }
  const f=p.found, errs=Object.entries(p.errors||{});
  const errHTML = errs.filter(([k])=>k!=='category').map(([,m])=>`<div class="bad">${esc(m)}</div>`).join('');
  const catErr = (p.errors&&p.errors.category) ? `<div class="bad">${esc(p.errors.category)}</div>` : '';
  const notes = [];
  notes.push('<div class="mute">原片仅被读取，不会移动、删除或修改；照片复制到软件文件夹后再加入 Lightroom 目录。同名文件只有内容校验一致才跳过，不同内容会自动改名；复制后会再次校验，不会覆盖已有文件。</div>');
  if (!p.lr_connected) notes.push('<div class="warn">Lightroom 当前未连接：将只复制照片，稍后可在结果页选择“重新尝试加入 Lightroom”。</div>');
  if (!p.base_exists && !(p.errors&&p.errors.base)) notes.push('<div class="warn">软件文件夹尚不存在，开始导入时将询问是否创建。</div>');
  if (f.skipped_links) notes.push(`<div class="mute">已忽略 ${f.skipped_links} 个快捷方式或链接。</div>`);
  imSet(`<div class="big">找到 ${f.n} 张（RAW ${f.raw}、JPEG ${f.jpeg}、其他 ${f.other}），共 ${esc(f.size_text)}</div>
    <div class="kvl"><span>来源文件夹</span><span>${esc(p.source)}</span>
      <span>软件文件夹</span><span>${esc(p.base)}${p.base_is_default?'（默认位置，可在设置中更换）':''}</span>
      <span>分类文件夹名</span><span><input type="text" id="im_cat" maxlength="60" placeholder="可选，留空则直接放入软件文件夹" value="${esc(typed)}"></span>
      <span>保存到</span><span>${esc(p.target)}</span>
      <span>磁盘剩余空间</span><span>${esc(p.free_text)}（本次需要约 ${esc(p.needed_text)}）</span></div>${catErr}${errHTML}${notes.join('')}`,
    [{label:'取消', onclick:async()=>{ try { await window.pywebview.api.import_cancel(); } catch(e){} imClose(); }},
     {label:'开始导入', cls:'primary', id:'im_go', disabled:!p.can_start, onclick:imBegin}]);
  const inp=$('#im_cat'); let t=null;
  if (hadFocus){ inp.focus(); if (ss) try { inp.setSelectionRange(ss[0], ss[1]); } catch(e){} }
  if (typed!==cur){ IM.cat=typed; t=setTimeout(()=>imConfirm(), 350); }       // 等待期间打的字也要重新计算“保存到”
  inp.oninput=()=>{ clearTimeout(t); t=setTimeout(()=>{ IM.cat=inp.value; imConfirm(); },350); };
}
async function imBegin(){
  const cat=$('#im_cat').value; IM.cat=cat;
  $('#im_go').disabled = true;
  let r = await safeCall(()=>window.pywebview.api.import_start(cat, false), $('#im_go'));
  if (!r) return;
  if (r.needs_create){
    if (!await askDialog('创建文件夹', '软件文件夹不存在：\n'+r.base+'\n是否创建？', '创建')){ const g=$('#im_go'); if (g) g.disabled=false; return; }
    r = await safeCall(()=>window.pywebview.api.import_start(cat, true), $('#im_go'));
    if (!r) return;
  }
  if (!r.ok){ await infoDialog('无法开始导入', r.message||'无法开始导入。'); imConfirm(); return; }
  IM.stage='copying'; IM.pstage=null;
  imProgress({i:0,n:0,name:'',elapsed:0,counts:{copied:0,skipped:0,failed:0,lr_ok:0,lr_uncertain:0,lr_pending:0,lr_failed:0}});
}
function countsLine(c){ return `已复制 ${c.copied}　跳过 ${c.skipped}　失败 ${c.failed}　已加入 Lightroom ${c.lr_ok}`+(c.lr_uncertain?`　需确认 ${c.lr_uncertain}`:'')+(c.lr_pending?`　尚未加入 ${c.lr_pending}`:'')+(c.lr_failed?`　加入失败 ${c.lr_failed}`:''); }
function imProgress(ev){
  if (IM.stage!=='copying' && IM.stage!=='retry') IM.stage='copying';
  imOpen(ev.mode==='retry'?'重新加入 Lightroom':'正在导入');
  const n=ev.n||0, i=Math.min(ev.i+1,n), pct = n? Math.round(ev.i/n*100):0;
  if ($('#im_bar') && IM.pstage==='on'){ $('#im_bar').style.width=pct+'%'; $('#im_line').textContent = n?`第 ${i}/${n} 个　${ev.name||''}`:'准备中'; $('#im_time').textContent='已用时 '+fmtTime(ev.elapsed); $('#im_counts').textContent=countsLine(ev.counts); return; }
  IM.pstage='on';
  imSet(`<div class="big" id="im_line">${n?`第 ${i}/${n} 个　${esc(ev.name||'')}`:'准备中'}</div><div class="bar"><i id="im_bar" style="width:${pct}%"></i></div>
    <div class="mute" id="im_time">已用时 ${fmtTime(ev.elapsed)}</div><div class="mute" id="im_counts">${esc(countsLine(ev.counts))}</div>
    <div class="mute">取消后将在当前照片处理完成后停止，已完成的保留。</div>`,
    [{label:'取消导入', onclick:async(e)=>{ e.target.disabled=true; e.target.textContent='正在停止'; await window.pywebview.api.import_cancel(); }}]);
}
function imResult(ev){
  IM.stage='done'; IM.pstage=null; imOpen('导入结果'); const c=ev.counts;
  const rows = (ev.problems||[]).map(p=>{ const what = p.copy==='failed' ? '复制' : '加入 Lightroom';
    return `<tr><td>${esc(p.name)}</td><td>${what}</td><td>${p.lr==='uncertain'?'请在 Lightroom 中确认：':''}${esc(p.reason||'')}</td></tr>`; }).join('');
  const lines = [];
  if (ev.cancelled) lines.push('<div class="warn">已取消。已完成的照片保留，未处理的没有复制。</div>');
  if (c.lr_pending) lines.push(`<div class="warn">有 ${c.lr_pending} 张已复制但尚未加入 Lightroom。</div>`);
  if (c.lr_uncertain) lines.push(`<div class="warn">有 ${c.lr_uncertain} 张需要在 Lightroom 中确认是否已加入（软件不会自动重试，以免重复添加）。</div>`);
  if (!ev.cancelled && !c.failed && !c.lr_pending && !c.lr_uncertain && !c.lr_failed) lines.push('<div class="okmsg">全部完成。</div>');
  imSet(`<div class="big">${esc(countsLine(c))}</div><div class="mute">共 ${ev.n} 张，用时 ${fmtTime(ev.elapsed)}。</div>${lines.join('')}
    ${rows?`<div class="plist"><table><thead><tr><th>文件</th><th>环节</th><th>原因</th></tr></thead><tbody>${rows}</tbody></table>${ev.problems_more?`<div class="mute">另有 ${ev.problems_more} 项未列出。</div>`:''}</div>`:''}`,
    [ev.pending_retry?{label:'重新尝试加入 Lightroom', onclick:async()=>{ const r=await safeCall(()=>window.pywebview.api.import_retry_lr()); if (!r) return; if(!r.ok) await infoDialog('无法重新加入', r.message); else { IM.stage='retry'; IM.pstage=null; } }}:null,
     {label:'关闭', cls:'primary', onclick:async()=>{ try { await window.pywebview.api.import_close(); } catch(e){} imClose(); }}].filter(Boolean));
}
function onImportEvent(ev){
  if (ev.type==='import_scan'){
    if (ev.state==='scanning'){ if(IM.stage==='scanning'){ imScanning(ev.found||0); } }
    else if (ev.state==='done'){ if (ev.error){ imOpen('导入照片'); imSet(`<div class="bad">${esc(ev.error)}</div>`, [{label:'关闭', onclick:async()=>{ try { await window.pywebview.api.import_close(); } catch(e){} imClose(); }}]); } else imConfirm(); }
    else if (ev.state==='cancelled'){ imClose(); }
  } else if (ev.type==='import_progress'){ imProgress(ev); }
  else if (ev.type==='import_done'){ imResult(ev); }
}
