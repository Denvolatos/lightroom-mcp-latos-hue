/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- right ---- */
let rows = [];   // 真实模式下的“本次调整”（由后端推送）
const STCLS = {'已应用':'st-ok','失败':'st-bad','已拒绝':'st-bad','待确认':'st-wait','处理中':'st-wait','已撤销':'st-mute'};
function esc(t){ return String(t==null?'':t).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function renderParams(){
  const tb=$('#ptable tbody'); tb.innerHTML='';
  if (REAL()){
    const reusable=new Set();
    rows.forEach(r=>{ const can = r.status==='已应用' && r.edit_id;
      const reuse=can && !String(r.rid||'').startsWith('lib:') && !reusable.has(r.edit_id); if(reuse) reusable.add(r.edit_id);
      tb.insertAdjacentHTML('beforeend',
        `<tr><td>${esc(r.label)}<div class="why">${esc(r.reason)}</div></td><td class="num">${esc(r.before)}</td><td class="num">${esc(r.after)}</td><td class="${STCLS[r.status]||''}">${esc(r.status)}</td><td>${can?`<button class="btn small" data-eid="${esc(r.edit_id)}">撤销</button>`:''}${reuse?`<button class="btn small" data-reuse="${esc(r.edit_id)}" title="将这次滑块调整应用到其他选中照片">复用</button>`:''}</td></tr>`); });
    tb.querySelectorAll('button[data-eid]').forEach(b=>{ b.disabled = undoBusy; b.onclick=()=>undoRow(b.dataset.eid, b); });
    tb.querySelectorAll('button[data-reuse]').forEach(b=>b.onclick=()=>reuseEdit(b.dataset.reuse));
    $('#pempty').style.display = rows.length?'none':'block';
    $('#restorerow').style.display = rows.some(r=>r.status==='已应用')?'block':'none';
    return;
  }
  steps.forEach(s=>{ tb.insertAdjacentHTML('beforeend',
    `<tr><td>${s.k}<div class="why">${s.why}</div></td><td class="num">${s.a}</td><td class="num ${s.b>s.a?'up':'down'}">${s.b}</td><td class="st-ok">已应用</td><td><button class="btn small" onclick="undoOne('${s.k}')">撤销</button></td></tr>`); });
  $('#pempty').style.display = steps.length?'none':'block';
}
function say(t, who='ai'){ const m=document.createElement('div'); m.className='msg '+who; m.textContent=t; $('#msgs').appendChild(m); m.scrollIntoView(); return m; }

const PLAN = [
  {k:'高光', a:0, b:-35, why:'天空高光区域过亮，降低以保留云层层次'},
  {k:'蓝色饱和度', a:0, b:18, why:'增强天空蓝色'},
  {k:'清晰度', a:0, b:12, why:'提升山体轮廓清晰度'}
];
function apply(s){ steps.push(s); renderParams(); renderStage(); }
function runPlan(i=0){
  if(i>=PLAN.length){ say('调整已完成。可在「本次调整」中逐项撤销。'); return; }
  const s=PLAN[i];
  if(!ask){ apply(s); setTimeout(()=>runPlan(i+1),500); return; }
  const m=document.createElement('div'); m.className='ask';
  m.innerHTML=`拟调整：${s.k} ${s.a} → ${s.b}<div class="why">依据：${s.why}</div><div class="row"><button class="btn primary small">同意</button><button class="btn small">拒绝</button></div>`;
  $('#msgs').appendChild(m); m.scrollIntoView();
  const [ok,no]=m.querySelectorAll('button');
  ok.onclick=()=>{ m.querySelector('.row').remove(); apply(s); runPlan(i+1); };
  no.onclick=()=>{ m.querySelector('.row').remove(); m.append('已拒绝'); runPlan(i+1); };
}
const REAL = () => !!(window.pywebview && window.pywebview.api && window.pywebview.api.send);
let cur = null, busy = false;
let confirmDefault = true;   // 设置里的“逐项确认默认值”，新对话开始时套用   // cur = 正在流式显示的那条 AI 消息
let photoName = null;           // 真实模式：Lightroom 当前选中的照片
const DOTCLR = {connected:'var(--ok)', connecting:'var(--warn)', disconnected:'var(--bad)'};
let LRL = {state:'idle', message:''}, LASTST = null;   // LRL：软件自动启动 Lightroom 的进度（lr_launch 事件）
function showStatus(s){ LASTST = s;
  let text = s.text, hint = s.state==='connected' ? '' : s.hint, dot = DOTCLR[s.state]||'var(--bad)';
  if (s.state!=='connected' && ['starting','already_running','not_found','failed','timeout'].indexOf(LRL.state)>=0){
    hint = LRL.message;
    if (LRL.state==='starting'){ text = '正在启动 Lightroom…'; dot = 'var(--warn)'; hint = '请稍候，Lightroom 启动需要一会儿。'; } }
  $('#lrstat').textContent = text; $('#lrdot').style.background = dot;
  $('#lrhint').textContent = hint; $('#lrhint').title = hint; }
function onLrLaunch(ev){ LRL = ev; if (LASTST) showStatus(LASTST); else { $('#lrstat').textContent = ev.state==='starting' ? '正在启动 Lightroom…' : $('#lrstat').textContent; $('#lrhint').textContent = ev.message; } }
function setBusy(b){ busy=b; $('#send').disabled=b; $('#inp').disabled=b; $('#stop').style.display=b?'':'none'; $('#newchat').disabled=b;
  $('#sw').disabled=b; $('#sw').title = b ? 'AI 正在处理这一轮，结束后才能切换' : '开启后，每项调整需先经确认才会执行'; }   // 这一轮用的是发送时的设置，处理中切换不会生效
async function newChat(){
  if (!REAL() || busy) return;
  if (!await askDialog('新对话', '将清空当前对话与「本次调整」表格并重置助手会话。照片上已应用的调整不会被撤销，仍可用「还原到原始状态」还原。是否继续？', '新对话')) return;
  await window.pywebview.api.reset();
  $('#msgs').innerHTML=''; rows=[]; cur=null; setAsk(confirmDefault); say('请选择照片并输入期望的修图效果。'); renderParams(); renderStage(); toast('已开始新对话');
}
function note(t){ const n=document.createElement('div'); n.className='note'; n.textContent=t; $('#msgs').appendChild(n); n.scrollIntoView(); return n; }
function fmtCost(c){ return (c==null) ? '' : '，估算费用 $'+Number(c).toFixed(3); }
/* 后端（Python）把每个事件推到这里 */
function showConfirm(ev){
  const m=document.createElement('div'); m.className='ask'; m.id='cf_'+ev.id;
  const items = ev.items.length ? ev.items.map(i=>`<div>${esc(i.label)}：${esc(i.from)} → ${esc(i.to)}</div>`).join('') : '';
  m.innerHTML=`${esc(ev.title)}${items?'':'：'+esc(ev.reason)}<div class="items">${items}</div>${items&&ev.reason?`<div class="why">依据：${esc(ev.reason)}</div>`:''}<div class="row"><button class="btn primary small">同意</button><button class="btn small">拒绝</button></div>`;
  $('#msgs').appendChild(m); m.scrollIntoView();
  const [ok,no]=m.querySelectorAll('button');
  ok.onclick=()=>{ m.querySelector('.row').innerHTML='已提交：同意'; window.pywebview.api.answer(ev.id,true); };
  no.onclick=()=>{ m.querySelector('.row').innerHTML='已提交：拒绝'; window.pywebview.api.answer(ev.id,false); };
}
function closeConfirm(ev){ const m=document.getElementById('cf_'+ev.id); if(!m) return; m.classList.add('done');
  m.querySelector('.row').innerHTML = ev.allow ? '已同意' : (ev.message && ev.message.indexOf('超过')>=0 ? '确认超时，已视为拒绝' : '已拒绝'); }
window.onClaudeEvent = function(ev){
  if (ev.type==='text'){ if(!cur) cur=say('', 'ai'); cur.textContent+=ev.text; cur.scrollIntoView(); }
  else if (ev.type==='tool'){ cur=null; note(ev.label); }
  else if (ev.type==='error'){ cur=null; say(ev.message,'err'); }
  else if (ev.type==='adjust'){ rows=ev.rows; renderParams(); renderStage(); }
  else if (ev.type==='status'){ showStatus(ev); }
  else if (ev.type==='lr_launch'){ onLrLaunch(ev); }
  else if (ev.type==='photo'){ photoName=ev.name; renderStage(); if(viewMode==='multi') loadVersions().catch(()=>{}); loadLib('f'); }
  else if (ev.type==='preview'){ pv=ev; previewArrived(ev); renderStage(); }
  else if (ev.type==='connecting'){ cur=null; note(ev.message); }
  else if (ev.type==='confirm'){ cur=null; showConfirm(ev); }
  else if (ev.type==='confirm_done'){ closeConfirm(ev); }
  else if (ev.type==='stopped'){ cur=null; note('已停止'); }
  else if (ev.type && ev.type.indexOf('import_')===0){ onImportEvent(ev); }
  else if (ev.type && ev.type.indexOf('export_')===0){ onExportEvent(ev); }
  else if (ev.type==='selection'){ SEL = {count:ev.count, photos:ev.photos||[], active_id:ev.active_id}; updatePickBtn(); }
  else if (ev.type && ev.type.indexOf('library_')===0){ onLibraryEvent(ev); }
  else if (ev.type && ev.type.indexOf('pick_')===0){ onPickEvent(ev); }
  else if (ev.type==='record_done'){ onRecordDone(ev); }
  else if (ev.type==='notes_context'){ cur=null; note('已将 '+ev.used+' 条经验作为参考资料提供给 AI'+(ev.truncated?'（共 '+ev.eligible+' 条参与对话，已选取最近修改的 '+ev.used+' 条）':'')+'。'); }
  else if (ev.type==='done'){
    if (!cur && ev.text && !ev.is_error && !$('#msgs').lastChild.classList.contains('ai')) say(ev.text,'ai');
    cur=null; setBusy(false);
    offerRecord();
    if (ev.tokens) note('本次用量约 '+ev.tokens.toLocaleString()+' token'+fmtCost(ev.cost)+'（估算值，非实际账单）');
  }
};
function send(){ const v=$('#inp').value.trim(); if(!v || busy) return; $('#inp').value=''; say(v,'me');
  if (REAL()){
    setBusy(true); cur=null; note('正在处理请求');
    window.pywebview.api.send(v, ask).then(r=>{ if(r && !r.ok){ say(r.message,'err'); setBusy(false); if(r.need_ai_choice) openWizard(); } })
      .catch(()=>{ say('无法连接后台，请重新启动程序。','err'); setBusy(false); });
    return;
  }
  setTimeout(()=>{ say('已收到需求，正在分析照片并制定调整方案。（演示回复）'); setTimeout(()=>runPlan(0),500); },400); }
$('#stop').onclick=()=>{ if(REAL()) window.pywebview.api.stop(); };
$('#send').onclick=send; $('#inp').onkeydown=e=>{ if(e.key==='Enter') send(); };
function setAsk(v){ ask=!!v; $('#sw').classList.toggle('on',ask);
  $('#swlabel').textContent= ask?'逐项确认：开（每项调整需先确认）':'逐项确认：关（自动执行）'; }
$('#sw').onclick=()=>setAsk(!ask);

/* 弹窗：返回 Promise<boolean> */
function askDialog(title, text, okLabel){ return new Promise(res=>{
  const mk=document.createElement('div'); mk.className='mask show';
  mk.innerHTML=`<div class="dialog small"><h3>${esc(title)}</h3><p>${esc(text)}</p><div class="row"><button class="btn">取消</button><button class="btn primary">${esc(okLabel)}</button></div></div>`;
  document.body.appendChild(mk); const [c,o]=mk.querySelectorAll('button');
  c.onclick=()=>{ mk.remove(); res(false); }; o.onclick=()=>{ mk.remove(); res(true); }; }); }
let batchBusy=false;
function confirmBatch(plan){ return new Promise(resolve=>{
  const mk=document.createElement('div'); mk.className='mask show';
  const deltas=(plan.delta_items||[]).map(d=>`${d.label} ${d.delta}`).join('、');
  let h='';
  for(const p of plan.photos||[]){
    h+=`<tr class="photo${p.will_change?'':' skip'}"><td colspan="3">${esc(p.photo||'（未命名照片）')}　${p.will_change?'将修改':'跳过'}</td></tr>`;
    if(p.will_change) for(const c of p.changes||[]) h+=`<tr><td>${esc(c.label||c.parameter)}</td><td class="num">${esc(c.before_text)}</td><td class="num">${esc(c.after_text)}</td></tr>`;
    else h+=`<tr class="skip"><td colspan="3">${esc(p.reason_skipped||'这张照片不适用。')}</td></tr>`;
  }
  const skipped=(plan.skipped_labels||[]).length?`这些项目不能批量复用，不会带过去：${plan.skipped_labels.join('、')}。`:'';
  mk.innerHTML=`<div class="dialog exp" role="dialog" aria-label="复用到其他选中照片"><h3>复用到其他选中照片</h3><div class="plan-intro">把“${esc(plan.source_photo||'当前照片')}”上的这次调整（${esc(deltas||'滑块改动')}）用到其他选中的照片上：每张照片在自己现在的数值上加减同样的量。将修改 ${Number(plan.will_change)||0} 张，跳过 ${Number(plan.skipped)||0} 张。现在还没有改任何东西；确认后才会写入，之后可以整批还原。</div><div class="plan-list body"><table><tr><th>项目</th><th>现在</th><th>改成</th></tr>${h}</table></div>${skipped?`<div class="plan-more">${esc(skipped)}</div>`:''}<div class="row"><button class="btn">取消</button><button class="btn primary">确认应用</button></div></div>`;
  document.body.appendChild(mk);
  const [cancel,ok]=mk.querySelectorAll('.row button');
  cancel.onclick=()=>{mk.remove(); resolve(false);};
  ok.onclick=()=>{mk.remove(); resolve(true);};
}); }
async function reuseEdit(editId){
  if(batchBusy || !REAL()) return;
  batchBusy=true;
  try{
    const planned=await window.pywebview.api.batch_plan_from_edit(editId);
    if(!planned.ok) return toast(planned.message||'无法预演批量修改');
    const plan=planned.result;
    if(!plan.plan_id || !plan.will_change) return toast('其他选中照片没有可复用的调整');
    if(!await confirmBatch(plan)) return;
    const applied=await window.pywebview.api.batch_apply(plan.plan_id);
    if(!applied.ok) return toast(applied.message||'批量修改失败');
    const result=applied.result;
    const failed=(result.results||[]).find(x=>x.error);
    const summary=say(`批量复用：已修改 ${result.changed} 张${result.stopped_early_at?'；在“'+result.stopped_early_at+'”这张停下了，后面的 '+(result.not_done||0)+' 张没有改':''}${failed?'。原因：'+failed.error:''}。`);
    if(result.batch_id && result.changed){
      const undo=document.createElement('button'); undo.className='btn small'; undo.textContent='还原这批照片';
      undo.onclick=async()=>{
        if(!await askDialog('还原整批调整','将尝试还原这批照片的改动。若某张照片后来又被修改，冲突会保留并报告。','还原')) return;
        const r=await window.pywebview.api.batch_undo(result.batch_id);
        if(!r.ok) return toast(r.message||'还原失败');
        const problems=(r.result||{}).problems||[];
        if(problems.length) return toast(`已还原部分照片，${problems.length} 张未还原；请检查原因后重试。`);
        undo.disabled=true; undo.textContent='已还原'; toast('整批已还原');
      };
      summary.appendChild(undo);
    }
  }catch(e){ toast('批量操作未完成，请检查连接并重新预演。'); }
  finally{ batchBusy=false; }
}
/* 撤销 / 还原：一次只做一个。点击后按钮立刻变灰并显示“正在…”，Lightroom 回复前再点不会重复发送 */
let undoBusy = false;
async function undoGuard(btn, text, fn){
  if (undoBusy) return toast('正在处理上一次撤销，请稍候。');
  undoBusy = true; const old = btn ? btn.textContent : '';
  document.querySelectorAll('#ptable button[data-eid], #restorerow button').forEach(b=>b.disabled=true);
  if (btn){ btn.disabled = true; btn.textContent = text; }
  try { await fn(); }
  finally {
    undoBusy = false;
    if (btn && btn.isConnected){ btn.disabled = false; btn.textContent = old; }
    document.querySelectorAll('#ptable button[data-eid], #restorerow button').forEach(b=>b.disabled=false);
  }
}
function undoRow(eid, btn){
  return undoGuard(btn, '正在撤销…', async()=>{
    for (let force=false;;){
      const r = await safeCall(()=>window.pywebview.api.undo(eid, force), null, '撤销没有完成，请重试。'); if (!r) return;
      if (r.ok) return toast('已撤销');
      if (r.conflict && !force){
        if (!await askDialog('参数在调整后又发生变化', r.message+'\n\n强制撤销将覆盖这些后续改动。', '强制撤销')) return;
        force = true; continue;
      }
      return toast('撤销失败：'+(r.message||''));
    }
  });
}
async function restoreOriginal(btn){
  if (undoBusy) return toast('正在处理上一次撤销，请稍候。');
  if (!await askDialog('还原到原始状态', '将当前照片还原到首次调整之前的状态，已应用的调整均会被撤销。是否继续？', '还原')) return;
  return undoGuard(btn, '正在还原…', async()=>{
    for (let force=false;;){
      const r = await safeCall(()=>window.pywebview.api.restore_original(force), null, '还原没有完成，请重试。'); if (!r) return;
      if (r.ok) return toast('已还原到原始状态');
      if (r.conflict && !force){
        if (!await askDialog('参数在调整后又发生变化', r.message+'\n\n强制还原将覆盖这些后续改动。', '强制还原')) return;
        force = true; continue;
      }
      return toast('还原失败：'+(r.message||''));
    }
  });
}
function undoOne(k){ steps=steps.filter(s=>s.k!==k); renderParams(); renderStage(); toast('已撤销「'+k+'」'); }
function undo(btn){
  if (REAL()){ const last=[...rows].reverse().find(r=>r.status==='已应用'&&r.edit_id); if(!last) return toast('没有可撤销的调整'); return undoRow(last.edit_id, btn); }
  if(!steps.length) return toast('没有可撤销的调整'); const s=steps.pop(); renderParams(); renderStage(); toast('已撤销「'+s.k+'」'); }
