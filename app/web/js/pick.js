/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- AI 挑片 ---- */
let PK = {tok:0, stage:null, photos:[], thumbs:{}, o:{criterion:'overall', custom:'', count:'top3'}, res:null, ap:null, timer:null, t0:0, n:0};
const PK_CRIT = [['overall','综合观感'],['technical','技术质量（对焦、曝光、噪点）'],['composition','构图'],['custom','自定义']];
const PK_CNT = [['top1','挑出最好的 1 张'],['top3','前 3 张'],['all','全部排序']];
const PK_MAX = 10;
function updatePickBtn(){
  const b=$('#pickbtn'); if(!b) return; const n=SEL.count;
  b.disabled = REAL() && n===0;
  b.title = n===0 ? '请先在 Lightroom 中选择照片' : (n===1 ? '评估选中的这一张照片' : (n>PK_MAX ? '已选中 '+n+' 张，请减少到 '+PK_MAX+' 张以内' : '比较选中的 '+n+' 张照片并给出排名和建议'));
}
function pkOpen(title){ $('#pk_title').textContent = title||'AI 挑片'; $('#pmask').classList.add('show'); }
function pkClear(){ if (PK.timer){ clearInterval(PK.timer); PK.timer=null; } }
function pkClose(){ pkClear(); $('#pmask').classList.remove('show'); PK.stage=null; }
function pkSet(body, buttons){
  $('#pk_body').innerHTML=body; const f=$('#pk_foot'); f.innerHTML='';
  (buttons||[]).forEach(b=>{ const e=document.createElement('button'); e.className='btn '+(b.cls||''); e.textContent=b.label; e.disabled=!!b.disabled; if(b.id) e.id=b.id; if(b.title) e.title=b.title; e.onclick=b.onclick; f.appendChild(e); });
}
const pkStars = n => '★'.repeat(n)+'☆'.repeat(5-n);
const pkFlag = f => ({pick:'留用', none:'无旗标', reject:'排除'}[f] || '—');
const pkRating = r => r ? r+' 星' : '无星级';
function pkThumb(id){ const u=PK.thumbs[id]; return u ? `<img class="pt" src="${esc(u)}" alt="">` : `<div class="pt"></div>`; }
async function pkFinishClose(){ try{ await window.pywebview.api.pick_apply_close(); await window.pywebview.api.pick_close(); }catch(e){} pkClose(); }
async function openPick(){
  if (!REAL()) return toast('界面演示中，AI 挑片不可用');
  const api = window.pywebview.api, tok = ++PK.tok;
  pkOpen(); PK.stage='load';
  pkSet('<div class="mute"><span class="spin"></span>正在读取 Lightroom 中选中的照片…</div>', [{label:'取消', onclick:pkClose}]);
  const stale = ()=> tok!==PK.tok || PK.stage!=='load';      // 读取期间点了取消（或已显示结果）：回来后不再把弹窗打开
  let st=null, ap=null;
  try { st = await api.pick_state(); ap = await api.pick_apply_state(); } catch(e){}
  if (stale()) return;
  if (st && st.thumbs) Object.assign(PK.thumbs, st.thumbs);
  if (ap && ap.stage==='writing'){ PK.stage='applying'; pkApplying({i:0,n:0,name:''}); return; }
  if (ap && ap.stage==='done' && ap.results.length){ pkApplied(ap); return; }
  if (st && st.stage==='running'){ PK.n=st.n||0; PK.stage='run'; pkRunning(); return; }
  if (st && st.stage==='done' && st.result){ PK.res=st.result; pkResult(); return; }
  let r; try { r = await api.pick_prepare(); } catch(e){ r = {ok:false, message:'无法读取选中的照片，请重试。'}; }
  if (stale()) return;
  if (!r.ok){ PK.stage='error'; pkSet(`<div class="bad" style="font-size:13px">${esc(r.message||'无法开始。')}</div>`, [{label:'关闭', cls:'primary', onclick:pkClose}]); return; }
  if (r.stage==='running'){ PK.stage='run'; pkRunning(); return; }
  PK.photos = r.photos; Object.assign(PK.thumbs, r.thumbs||{}); PK.stage='form'; pkForm();
}
function pkForm(){
  const o=PK.o, n=PK.photos.length, one=n===1;
  const cells = PK.photos.map(p=>`<div class="pcell" data-id="${esc(p.id)}">${pkThumb(p.id)}<div class="pn" title="${esc(p.name||'')}">${esc(p.name||'（未命名）')}</div></div>`).join('');
  pkOpen(one ? '评估这一张' : 'AI 挑片');
  pkSet(`<div class="big">${one ? '将评估选中的这 1 张照片' : '将比较选中的 '+n+' 张照片'}</div>
    <div class="grid" id="pk_grid">${cells}</div>
    <div class="mute">开始后，这些照片的预览图会发送给当前使用的 AI 来源。AI 的结果先只显示在软件里，需要您确认后才会写入 Lightroom。</div>
    <div class="sep"></div>
    <div class="prow"><span class="lab">评判标准</span><span>${PK_CRIT.map(([v,t])=>`<label class="radio"><input type="radio" name="pk_c" value="${v}" ${o.criterion===v?'checked':''}> ${t}</label>`).join('')}
      <input type="text" id="pk_custom" maxlength="120" placeholder="例如：更看重人物表情与光线氛围（不超过 120 字）" value="${esc(o.custom)}"><span class="mute" id="pk_cn"></span></span></div>
    ${one ? '' : `<div class="prow"><span class="lab">结果数量</span><span>${PK_CNT.map(([v,t])=>`<label class="radio"><input type="radio" name="pk_n" value="${v}" ${o.count===v?'checked':''}> ${t}</label>`).join('')}</span></div>`}
    <div class="bad" id="pk_err"></div>`,
    [{label:'取消', onclick:pkFinishClose}, {label:'开始', cls:'primary', id:'pk_go', onclick:pkStart}]);
  document.querySelectorAll('input[name=pk_c]').forEach(r=>r.onchange=()=>{ o.criterion=r.value; pkFormUpdate(); });
  document.querySelectorAll('input[name=pk_n]').forEach(r=>r.onchange=()=>{ o.count=r.value; });
  $('#pk_custom').oninput=()=>{ o.custom=$('#pk_custom').value; pkFormUpdate(); };
  pkFormUpdate();
}
function pkFormUpdate(){
  const o=PK.o, custom=o.criterion==='custom', t=o.custom.replace(/\s+/g,' ').trim(), len=t.length;
  $('#pk_custom').style.display = custom ? '' : 'none'; $('#pk_cn').style.display = custom ? '' : 'none';
  $('#pk_cn').textContent = len+' / 120 字' + (len>120 ? '，超出长度' : '');
  $('#pk_cn').style.color = len>120 ? 'var(--bad)' : '';
  $('#pk_go').disabled = custom && (len===0 || len>120);
}
async function pkStart(){
  const o=PK.o; $('#pk_go').disabled=true; $('#pk_err').textContent='';
  PK.stage='starting';           // 先记下阶段：AI 很快失败时，完成事件可能比接口返回先到
  const r = await safeCall(()=>window.pywebview.api.pick_start({criterion:o.criterion, custom:o.criterion==='custom'?o.custom:'', count:o.count}), $('#pk_go'));
  if (PK.stage!=='starting') return;               // 结果已经显示，或弹窗已关
  if (!r){ PK.stage='form'; return; }
  if (!r.ok){ PK.stage='form'; $('#pk_err').textContent = r.message||'无法开始。'; if (!r.changed) pkFormUpdate(); return; }
  PK.n = PK.photos.length; PK.stage='run'; pkRunning();
}
function pkRunning(label){
  pkClear(); pkOpen('AI 挑片'); PK.t0 = Date.now();
  pkSet(`<div class="big"><span class="spin"></span>正在比较 ${PK.n||PK.photos.length} 张照片…</div>
    <div class="mute" id="pk_lab">${esc(label||'已发送请求，等待 AI 回复。')}</div><div class="mute" id="pk_time">已用时 00:00</div>
    <div class="mute">通常需要数十秒；最长等待 180 秒。可随时停止。</div>`,
    [{label:'隐藏', title:'AI 继续在后台比较，结束后再点“AI 挑片”查看结果', onclick:pkClose},
     {label:'停止', id:'pk_stop', onclick:async(e)=>{ e.target.disabled=true; e.target.textContent='正在停止'; try { await window.pywebview.api.pick_stop(); } catch(e2){ toast('没能停止，请稍后再试。'); e.target.disabled=false; e.target.textContent='停止'; } }}]);
  PK.timer = setInterval(()=>{ const t=$('#pk_time'); if(t) t.textContent='已用时 '+fmtTime((Date.now()-PK.t0)/1000); }, 1000);
}
function pkUsage(ev){
  const bits = ['用时 '+ev.elapsed+' 秒']; if (ev.tokens) bits.push('约 '+Number(ev.tokens).toLocaleString()+' token'); if (ev.cost!=null) bits.push('估算费用 $'+Number(ev.cost).toFixed(3));
  return `<div class="mute">${esc(bits.join('，'))}（估算值，非实际账单）。</div>`;
}
function pkResult(){
  pkClear(); const ev=PK.res; PK.stage='result'; pkOpen('AI 挑片');
  const again = {label:'重新比较', onclick:async()=>{ try { await window.pywebview.api.pick_close(); } catch(e){} PK.res=null; pkClose(); openPick(); }};
  const close = {label:'关闭', cls:'primary', onclick:pkFinishClose};
  const head = `<div class="mute">${esc(ev.n)} 张照片 · 评判标准：${esc(ev.criterion_label)} · 结果：${esc(ev.count_label)}</div>`;
  if (['failed','timeout','stopped'].includes(ev.status)){
    pkSet(`<div class="big">${ev.status==='stopped'?'已停止':(ev.status==='timeout'?'等待超时':'未能完成')}</div><div class="${ev.status==='stopped'?'mute':'bad'}" style="font-size:13px">${esc(ev.message)}</div>${head}`, [again, close]); return;
  }
  const dropped = (ev.dropped||[]).length ? `<div class="warn">${ev.dropped.map(esc).join('<br>')}</div>` : '';
  if (ev.status==='unstructured'){
    pkSet(`<div class="big">未能得到结构化结果</div><div class="warn">${esc(ev.message)}</div>${dropped}
      <div class="rawbox">${esc(ev.raw||'（AI 没有返回文字）')}</div>${head}${pkUsage(ev)}`, [again, close]); return;
  }
  const cards = ev.ranking.map(r=>`<div class="card"><div class="rk">${r.rank}</div>
      <div>${PK.thumbs[r.photo_id]?`<img src="${esc(PK.thumbs[r.photo_id])}" alt="" data-zoom="${esc(r.photo_id)}" title="点击放大">`:`<div class="noimg" data-zoom="${esc(r.photo_id)}"></div>`}</div>
      <div><div class="nm">${esc(r.name||'（未命名）')}</div>
        <div class="meta">评分 ${esc(r.score)} / 10　建议 <span class="stars">${pkStars(r.stars)}</span>（${pkRating(r.stars)}）· ${pkFlag(r.flag)}</div>
        <div class="why2">${esc(r.reason)}</div>
        <div class="old">Lightroom 中现有：${pkRating(r.old_rating||0)} / ${pkFlag(r.old_flag||'none')}</div></div></div>`).join('');
  pkSet(`${head}<div class="sumbox">${ev.summary ? esc(ev.summary) : '（AI 没有给出总评）'}</div>${dropped}${cards}
    ${ev.extra>0?`<div class="mute">AI 还给出了另外 ${ev.extra} 项，超出所选结果范围，未显示。</div>`:''}
    <div class="mute">星级和旗标只是 AI 的建议，尚未写入 Lightroom。点击缩略图可放大查看。</div>${pkUsage(ev)}`,
    [again, {label:'应用建议的星级和旗标', cls:'primary', onclick:pkApply}, close]);
  document.querySelectorAll('#pk_body [data-zoom]').forEach(e=>e.onclick=()=>pkZoom(e.dataset.zoom));
}
async function pkZoom(id){
  const r = await window.pywebview.api.pick_preview(id);
  if (!r.ok) return toast(r.message||'无法放大');
  const nm = ((PK.res&&PK.res.ranking||[]).find(x=>x.photo_id===id)||{}).name || '';
  const mk=document.createElement('div'); mk.className='mask show lbmask';
  mk.innerHTML=`<img src="${esc(r.url)}" alt=""><div class="lbn">${esc(nm)}　（点击任意处关闭）</div>`; mk.onclick=()=>mk.remove(); document.body.appendChild(mk);
}
/* 写入 Lightroom：确认清单 → 写入 → 结果 → 撤销 */
async function pkApply(){
  const r = await safeCall(()=>window.pywebview.api.pick_apply_prepare()); if (!r) return;
  if (!r.ok) return infoDialog('无法应用建议', r.message||'无法生成确认清单。');
  PK.ap = r.items; PK.stage='confirm'; pkConfirmView();
}
function pkConfirmView(){
  pkClear(); pkOpen('确认写入 Lightroom');
  const rows = PK.ap.map(i=>{
    const can = i.changed;
    return `<tr><td><input type="checkbox" data-id="${esc(i.photo_id)}" ${can?'checked':'disabled'}></td><td>${esc(i.name||'（未命名）')}</td>
      <td class="${can?'':'dim'}">${esc(i.old_text)}</td><td class="${can?'':'dim'}">${i.error?'<span class="st-bad">'+esc(i.error)+'</span>':(can?'→ '+esc(i.new_text):'无变化')}</td></tr>`; }).join('');
  pkSet(`<div class="big">将写入以下照片的星级和旗标</div>
    <table><thead><tr><th></th><th>照片</th><th>现有（星级 / 旗标）</th><th>写入后</th></tr></thead><tbody>${rows}</tbody></table>
    <div class="mute">只修改星级和旗标，不会改动关键词或其他信息。可取消勾选不想改的照片；写入后可撤销这次写入。</div>
    <div class="bad" id="pk_err"></div>`,
    [{label:'返回', onclick:async()=>{ try { await window.pywebview.api.pick_apply_cancel(); } catch(e){} pkResult(); }},
     {label:'确认写入', cls:'primary', id:'pk_ok', onclick:pkApplyGo}]);
  const upd=()=>{ const n=document.querySelectorAll('#pk_body input[type=checkbox]:checked').length; $('#pk_ok').disabled = n===0; $('#pk_ok').textContent = n ? '确认写入（'+n+' 张）' : '确认写入'; };
  document.querySelectorAll('#pk_body input[type=checkbox]').forEach(c=>c.onchange=upd); upd();
}
async function pkApplyGo(){
  const ids=[...document.querySelectorAll('#pk_body input[type=checkbox]:checked')].map(c=>c.dataset.id);
  const btns = [...document.querySelectorAll('#pk_foot button')]; btns.forEach(b=>b.disabled=true);
  PK.stage='apply_start';        // 先记下阶段：写入很快结束（或失败）时，完成事件可能比接口返回先到
  const r = await safeCall(()=>window.pywebview.api.pick_apply_confirm(ids));
  if (PK.stage!=='apply_start') return;            // 已收到进度或结果，或弹窗已关
  if (!r || !r.ok){ PK.stage='confirm'; btns.forEach(b=>b.disabled=false); if (r){ $('#pk_err').textContent = r.message||'无法写入。'; $('#pk_ok').disabled = !!r.readonly; } return; }
  PK.stage='applying'; pkApplying({i:0,n:ids.length,name:''});
}
function pkApplying(ev){
  pkOpen('正在写入'); pkSet(`<div class="big"><span class="spin"></span>正在写入${ev.n?'（'+Math.min(ev.i+1,ev.n)+' / '+ev.n+'）':''}…</div><div class="mute">${esc(ev.name||'')}</div>`, [{label:'隐藏', onclick:pkClose}]);
}
const AP_ST = {ok:['成功','st-ok'], failed:['失败','st-bad'], uncertain:['不确定','st-wait'], undone:['已还原','st-mute'], conflict:['未还原（又被改过）','st-bad']};
function pkApplied(ev, undoRes){
  PK.stage='applied'; pkClear(); pkOpen('写入结果');
  const ur = {}; (undoRes||[]).forEach(u=>ur[u.photo_id]=u);
  const rows = ev.results.map(r=>{ const u=ur[r.photo_id]; const st = u ? u.status : (r.undone ? 'undone' : r.status), m = AP_ST[st]||[st,''];
    const msg = u && u.message ? u.message : r.message;
    return `<tr><td>${esc(r.name||'（未命名）')}</td><td>${esc(pkRating(r.new_rating))} / ${pkFlag(r.new_flag)}</td><td class="${m[1]}">${m[0]}${msg?'<div class="why">'+esc(msg)+'</div>':''}</td></tr>`; }).join('');
  const s=ev.summary||{}, undone = ev.results.filter(r=>r.undone || (ur[r.photo_id]&&ur[r.photo_id].status==='undone')).length;
  const canUndo = ev.results.some(r=>r.has_edit && !r.undone && !(ur[r.photo_id]&&ur[r.photo_id].status==='undone'));
  pkSet(`<div class="big">${undone ? '已还原 '+undone+' 张' : `成功 ${s.ok||0} 张`+(s.failed?`，失败 ${s.failed} 张`:'')+(s.uncertain?`，不确定 ${s.uncertain} 张`:'')}</div>
    <table><thead><tr><th>照片</th><th>写入的星级 / 旗标</th><th>结果</th></tr></thead><tbody>${rows}</tbody></table>
    ${s.uncertain?'<div class="warn">标为“不确定”的照片，请在 Lightroom 中确认其星级和旗标。</div>':''}
    <div class="mute">${undone ? '撤销只还原本次写入的星级和旗标。' : '如需恢复原样，可点击“撤销这次写入”。'}</div><div class="bad" id="pk_err"></div>`,
    [canUndo?{label:'撤销这次写入', onclick:()=>pkUndo(false)}:null, {label:'关闭', cls:'primary', onclick:pkFinishClose}].filter(Boolean));
}
async function pkUndo(force){
  if (PK.undoBusy) return; PK.undoBusy = true;
  const b = [...document.querySelectorAll('#pk_foot button')].find(x=>x.textContent==='撤销这次写入');
  if (b){ b.disabled = true; b.textContent = '正在撤销…'; }
  let r; try { r = await safeCall(()=>window.pywebview.api.pick_apply_undo(force), b, '撤销没有完成，请重试。'); }
  finally { PK.undoBusy = false; }
  if (!r){ if (b && b.isConnected) b.textContent = '撤销这次写入'; return; }
  if (r.results){
    const st = await safeCall(()=>window.pywebview.api.pick_apply_state()); if (st && st.results) pkApplied(st, r.results);
    if (r.conflict && !force && await askDialog('这些照片在写入后又发生变化', (r.results.filter(x=>x.status==='conflict').map(x=>(x.name||'')+'：'+x.message).join('\n'))+'\n\n强制撤销将覆盖这些后续改动。', '强制撤销')) return pkUndo(true);
    return;
  }
  $('#pk_err').textContent = r.message||'无法撤销。';
  if (b && b.isConnected){ b.disabled = false; b.textContent = '撤销这次写入'; }
}
function onPickEvent(ev){
  const open = $('#pmask').classList.contains('show');
  if (ev.type==='pick_thumb'){ PK.thumbs[ev.id]=ev.url;
    if (open && PK.stage==='form'){ const c=document.querySelector(`#pk_grid .pcell[data-id="${CSS.escape(ev.id)}"]`); if(c){ const t=c.querySelector('.pt'); const im=document.createElement('img'); im.className='pt'; im.alt=''; im.src=ev.url; t.replaceWith(im); } } }
  else if (ev.type==='pick_progress'){ if (open && PK.stage==='run'){ const l=$('#pk_lab'); if(l) l.textContent=ev.label||''; } }
  else if (ev.type==='pick_done'){ PK.res=ev; if (open && ['run','starting','form','load'].includes(PK.stage)) pkResult(); else if (!open) toast('AI 挑片已结束，请点击“AI 挑片”查看结果。'); }
  else if (ev.type==='pick_apply_progress'){ if (open && (PK.stage==='applying' || PK.stage==='apply_start')){ PK.stage='applying'; pkApplying(ev); } }
  else if (ev.type==='pick_apply_done'){ if (open && (PK.stage==='applying' || PK.stage==='apply_start')) pkApplied(ev); else if (!open) toast('写入已结束，请点击“AI 挑片”查看结果。'); }
}
$('#pmask').onclick=e=>{ if(e.target.id==='pmask' && (PK.stage==='form'||PK.stage==='load'||PK.stage==='error')) pkFinishClose(); };
