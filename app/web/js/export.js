/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- export dialog ---- */
let EX = {st:null, o:null, stage:null, tok:0};
const EX_SIZES = [0, 4096, 2048, 1024];
function exOpen(){ $('#mask').classList.add('show'); }
function exClose(){ $('#mask').classList.remove('show'); EX.stage=null; }
function exSet(body, buttons){
  $('#ex_body').innerHTML=body; const f=$('#ex_foot'); f.innerHTML='';
  (buttons||[]).forEach(b=>{ const e=document.createElement('button'); e.className='btn '+(b.cls||''); e.textContent=b.label; e.disabled=!!b.disabled; if(b.id) e.id=b.id; e.onclick=b.onclick; f.appendChild(e); });
}
async function openExport(){
  if (!REAL()) return toast('界面演示中，导出不可用');
  const tok = ++EX.tok;
  exOpen(); EX.stage='load';
  exSet('<div class="mute"><span class="spin"></span>正在读取 Lightroom 中选中的照片…</div>', [{label:'取消', onclick:exClose}]);
  const stale = ()=> tok!==EX.tok || EX.stage!=='load';      // 读取期间点了取消、又重新打开，或结果已经显示
  let cur = null;
  try { cur = await window.pywebview.api.export_state(); } catch(e){}
  if (stale()) return;
  if (cur && cur.stage==='running'){ EX.stage='run'; exRunning(); return; }
  if (cur && cur.stage==='done' && cur.result){ exResult(cur.result); return; }
  let st;
  try { st = await window.pywebview.api.export_dialog_state(); }
  catch(e){ if (!stale()) exSet('<div class="bad">无法读取导出信息，请重试。</div>', [{label:'关闭', onclick:exClose}]); return; }
  if (stale()) return;
  EX.st = st; EX.o = Object.assign({}, EX.st.options); EX.stage='form'; exForm();
}
function exInfoLine(p){ return [p.camera, p.format, p.size].filter(Boolean).join(' · ') || '—'; }
function exForm(){
  const st=EX.st, o=EX.o, p=st.photo;
  const photoHtml = p
    ? `<div class="kvl"><span>文件名</span><span>${esc(p.name||'—')}</span><span>基本信息</span><span>${esc(exInfoLine(p))}</span></div>
       <div class="mute">导出内容为该照片的当前状态（含已做的调整）。本版一次导出一张。</div>`
    : `<div class="bad">${esc(st.reason||'没有可导出的照片。')}</div>`;
  const sizeSel = EX_SIZES.includes(o.size) ? String(o.size) : 'custom';
  exSet(`${photoHtml}<div class="sep"></div>
    <div class="erow"><span class="lab">保存位置</span>
      <span class="inline"><input type="text" id="ex_dir" readonly placeholder="尚未选择文件夹" value="${esc(st.folder||'')}"><button class="btn small" id="ex_pick">选择文件夹</button></span>
      <span class="sub" id="ex_dirmsg"></span></div>
    <div class="erow"><label class="lab" for="ex_fmt">格式</label><select id="ex_fmt"><option value="jpeg">JPEG</option><option value="tiff">TIFF</option></select></div>
    <div class="erow" id="ex_qrow"><label class="lab" for="ex_q">质量</label><span class="inline"><input type="range" id="ex_q" min="40" max="100" step="1"><span id="ex_qv" style="width:28px;text-align:right"></span></span>
      <span class="sub">数值越大画质越好，文件越大。</span></div>
    <div class="erow" id="ex_brow"><span class="lab">位深</span><span><label class="radio"><input type="radio" name="ex_bd" value="16"> 16 位</label><label class="radio"><input type="radio" name="ex_bd" value="8"> 8 位</label></span>
      <span class="sub">无损压缩，文件较大。</span></div>
    <div class="erow"><label class="lab" for="ex_size">大小</label>
      <span class="inline"><select id="ex_size"><option value="0">原始尺寸</option><option value="4096">长边 4096 像素</option><option value="2048">长边 2048 像素</option><option value="1024">长边 1024 像素</option><option value="custom">自定义</option></select>
        <span id="ex_cwrap" class="inline">长边 <input type="number" id="ex_custom" min="256" max="20000" step="1"> 像素</span></span>
      <span class="sub" id="ex_csub">自定义范围：256–20000 的整数。</span><span class="warn" id="ex_big"></span></div>
    <div class="erow"><label class="lab" for="ex_md">元数据</label><select id="ex_md"><option value="minimal">仅必要信息（默认）</option><option value="all">包含全部元数据</option></select>
      <span class="sub" id="ex_mdsub"></span></div>
    <div class="sep"></div>
    <div class="erow"><span class="lab">文件名</span><span class="fname" id="ex_name"></span><span class="sub">若同名文件已存在，将自动改名（_2、_3…），不会覆盖。</span></div>
    <div class="bad" id="ex_err"></div>`,
    [{label:'取消', onclick:exClose}, {label:'导出', cls:'primary', id:'ex_go', onclick:exStart}]);
  $('#ex_fmt').value=o.format; $('#ex_q').value=o.quality; $('#ex_md').value=o.metadata; $('#ex_size').value=sizeSel;
  $('#ex_custom').value = sizeSel==='custom' ? o.size : '';
  document.querySelectorAll('input[name=ex_bd]').forEach(r=>{ r.checked = Number(r.value)===o.bit_depth; r.onchange=()=>{ o.bit_depth=Number(r.value); exUpdate(); }; });
  $('#ex_fmt').onchange=()=>{ o.format=$('#ex_fmt').value; exUpdate(); };
  $('#ex_q').oninput=()=>{ o.quality=Number($('#ex_q').value); exUpdate(); };
  $('#ex_md').onchange=()=>{ o.metadata=$('#ex_md').value; exUpdate(); };
  $('#ex_size').onchange=()=>{ const v=$('#ex_size').value;
    if (v==='custom'){ const t=$('#ex_custom').value.trim(); o.size = /^\d+$/.test(t) ? Number(t) : -1; } else { o.size=Number(v); } exUpdate(); };
  $('#ex_custom').oninput=()=>{ const t=$('#ex_custom').value.trim(); o.size = /^\d+$/.test(t) ? Number(t) : -1; exUpdate(); };
  $('#ex_pick').onclick=exPick;
  exUpdate();
}
function exSizeOk(o){ return o.size===0 || (Number.isInteger(o.size) && o.size>=256 && o.size<=20000); }
function exName(){
  if (!EX.st.photo) return '—';
  const nm = (EX.st.photo && EX.st.photo.name) || 'photo', o=EX.o;
  const stem = nm.replace(/\\/g,'/').split('/').pop().replace(/\.[^.]*$/,'').replace(/[^A-Za-z0-9\-_]/g,'_') || 'photo';
  return stem+'_LrMCP_'+(o.size>0 && exSizeOk(o) ? o.size+'px' : 'full')+'.'+(o.format==='tiff'?'tif':'jpg');
}
function exUpdate(){
  const st=EX.st, o=EX.o, tiff=o.format==='tiff', custom=$('#ex_size').value==='custom';
  $('#ex_qrow').style.display = tiff?'none':''; $('#ex_brow').style.display = tiff?'':'none';
  $('#ex_qv').textContent=o.quality; $('#ex_cwrap').style.display = custom?'':'none'; $('#ex_csub').style.display = custom?'':'none';
  const bad = !exSizeOk(o);
  $('#ex_csub').style.color = bad ? 'var(--bad)' : '';
  $('#ex_big').textContent = (tiff && o.bit_depth===16 && o.size===0) ? '文件可能超过 100 MB。' : '';
  $('#ex_mdsub').textContent = o.metadata==='all' ? '包含拍摄信息，可能含拍摄位置；分享前请留意。' : '仅保留色彩与方向等必要信息，不含拍摄位置。';
  $('#ex_name').textContent = exName();
  $('#ex_dirmsg').textContent = st.folder ? '' : (st.folder_message || '请选择保存位置。');
  $('#ex_dirmsg').style.color = '';
  $('#ex_err').textContent = '';
  $('#ex_go').disabled = !(st.photo && st.folder && !bad);
}
async function exPick(){
  const r = await safeCall(()=>window.pywebview.api.choose_export_folder()); if (!r) return;
  if (r.ok){ EX.st.folder=r.folder; EX.st.folder_message=''; $('#ex_dir').value=r.folder; }
  exUpdate();
  if (!r.ok && r.message){ $('#ex_dirmsg').textContent=r.message; $('#ex_dirmsg').style.color='var(--bad)'; }
}
async function exStart(){
  const o=EX.o;
  const payload = {format:o.format, size:o.size, quality:o.quality, bit_depth:o.bit_depth, metadata:o.metadata};
  $('#ex_go').disabled=true;
  EX.stage='starting';           // 先记下阶段：导出很快失败时，完成事件可能比接口返回先到
  const r = await safeCall(()=>window.pywebview.api.export_current_photo(payload), $('#ex_go'));
  if (EX.stage!=='starting') return;               // 结果已经显示，或弹窗已关
  if (!r){ EX.stage='form'; return; }
  if (!r.ok){ EX.stage='form'; exUpdate(); $('#ex_err').textContent=r.message||'无法导出。'; if (r.changed) $('#ex_go').disabled=true; return; }
  EX.stage='run'; exRunning();
}
function exRunning(){
  exOpen(); exSet('<div class="big"><span class="spin"></span>正在导出…</div><div class="mute">Lightroom 导出通常需要数秒到数十秒，请稍候。导出期间请勿关闭软件。点“隐藏”后导出会继续，结束后再点“导出”可查看结果。</div>',
    [{label:'隐藏', onclick:exClose}, {label:'导出', cls:'primary', disabled:true}]);
}
function exResult(ev){
  EX.stage='done'; exOpen();
  const close = {label:'关闭', cls:'primary', onclick:async()=>{ try { await window.pywebview.api.export_close(); } catch(e){} exClose(); }};
  if (ev.status==='exported'){
    const bd = ev.format==='tiff' && ev.bit_depth ? `（${ev.bit_depth} 位）` : '';
    exSet(`<div class="big okmsg">导出完成。</div>
      <div class="kvl"><span>文件名</span><span>${esc(ev.file)}</span><span>格式</span><span>${esc(ev.format_label)}${bd}</span>
        <span>尺寸</span><span>${esc(ev.dimensions||'—')}</span><span>文件大小</span><span>${esc(ev.size_text)}</span>
        <span>保存位置</span><span>${esc(ev.folder)}</span></div>`,
      [{label:'在资源管理器中显示', onclick:async()=>{ const r=await window.pywebview.api.reveal_last_export(); if(!r.ok) toast(r.message); }}, close]);
  } else if (ev.status==='uncertain'){
    exSet(`<div class="big">状态不确定</div><div class="warn" style="color:var(--warn)">${esc(ev.message)}</div><div class="kvl"><span>保存位置</span><span>${esc(ev.folder)}</span></div>`, [close]);
  } else {
    exSet(`<div class="big">导出失败</div><div class="bad">${esc(ev.message)}</div>`,
      [{label:'返回修改', onclick:async()=>{ try { await window.pywebview.api.export_close(); } catch(e){} openExport(); }}, close]);
  }
}
function onExportEvent(ev){
  if (ev.type==='export_done'){ if ($('#mask').classList.contains('show')) exResult(ev); else toast('导出已结束，请点击“导出”查看结果。'); }
  else if (ev.type==='export_progress' && $('#mask').classList.contains('show') && (EX.stage==='run' || EX.stage==='starting')){ EX.stage='run'; exRunning(); }
}
$('#mask').onclick=e=>{ if(e.target.id==='mask' && (EX.stage==='form'||EX.stage==='load')) exClose(); };
