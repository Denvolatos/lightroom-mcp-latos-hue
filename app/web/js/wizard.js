/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- environment wizard (0.14.0)：四项只读检查；页面只能取状态、点按钮，不传路径 ---- */
const WZ = {st:null, timer:null, busy:false, fresh:false};
const WZ_ICON = {ready:'✓', todo:'!', wait:'…'}, WZ_TAG = {ready:'已就绪', todo:'需要处理', wait:'等待'};
const WZ_ACTIONS = {choose_folder:'wizard_pick_folder', choose_lightroom:'wizard_pick_lightroom', choose_ai:'open_settings', stop_old_servers:'wizard_stop_old_servers'};
function wzMsg(t, bad){ const m=$('#w_msg'); m.textContent=t||''; m.className='msg-line'+(bad?' bad':''); }
function wzRender(){
  const st = WZ.st; if (!st) return;
  const box = $('#w_list'); box.innerHTML=''; box.classList.toggle('checking', !!st.checking);
  st.items.forEach(it=>{
    const row=document.createElement('div'); row.className='wz-item '+it.state;
    const ic=document.createElement('span'); ic.className='wz-ic'; ic.textContent=WZ_ICON[it.state]||'';
    const head=document.createElement('div'); const tt=document.createElement('span'); tt.className='wz-title'; tt.textContent=it.title;
    const tag=document.createElement('span'); tag.className='wz-tag'; tag.textContent=WZ_TAG[it.state]||''; head.append(tt, tag);
    row.append(ic, head);
    const tx=document.createElement('div'); tx.className='wz-text'; tx.textContent=it.text; row.append(tx);
    if (it.hint){ const h=document.createElement('div'); h.className='wz-hint'; h.textContent=it.hint; row.append(h); }
    if (it.need_choice && (it.choices||[]).length){
      const box2=document.createElement('div'); box2.className='wz-choices';
      it.choices.forEach(c=>{
        const line=document.createElement('div'); line.className='wz-choice';
        const b=document.createElement('button'); b.className='btn small primary'; b.textContent=c.label; b.disabled=WZ.busy;
        b.onclick=()=>wzChooseAi(c.id);
        const cs=document.createElement('span'); cs.className='cs '+(c.ok?'ok':'bad'); cs.textContent=c.name+'：'+c.status;
        line.append(b, cs);
        if (c.privacy){ const cp=document.createElement('span'); cp.className='cp'; cp.textContent=c.privacy; line.append(cp); }
        box2.append(line); });
      row.append(box2); }
    if (it.action && WZ_ACTIONS[it.action]){
      const b=document.createElement('button'); b.className='btn small wz-act'; b.textContent=it.action_label; b.disabled=WZ.busy;
      b.onclick=()=>wzAct(it.action); row.append(b); }
    box.append(row);
  });
  $('#w_all').style.display = (st.ready && !st.checking) ? '' : 'none';
  $('#w_done').style.display = (st.ready && !st.checking) ? '' : 'none';
  $('#w_re').disabled = !!st.checking || WZ.busy; $('#w_re').textContent = st.checking ? '检查中…' : '重新检查';
  if (WZ.fresh){ WZ.fresh=false; $('#w_never').checked = !!st.wizard_done; }
}
async function wzLoad(refresh){
  clearTimeout(WZ.timer);
  try { WZ.st = await window.pywebview.api.wizard_state(!!refresh); }
  catch(e){ wzMsg('暂时无法检查，请点“重新检查”。', true); return; }
  wzRender();
  if (WZ.st.checking && $('#wmask').classList.contains('show')) WZ.timer = setTimeout(()=>wzLoad(false), 600);
}
function openWizard(){
  if (!REAL()) return;
  wzMsg(''); WZ.fresh = true; $('#wmask').classList.add('show'); wzLoad(true);
}
function closeWizard(){
  clearTimeout(WZ.timer); $('#wmask').classList.remove('show');
  if ($('#w_never').checked && !(WZ.st && WZ.st.wizard_done)) window.pywebview.api.wizard_done(true).catch(()=>{});
}
async function wzChooseAi(id){
  if (WZ.busy) return; WZ.busy=true; wzMsg(''); wzRender();
  try {
    const r = await window.pywebview.api.wizard_choose_ai(id);
    if (r && r.message) wzMsg(r.message, true);
  } catch(e){ wzMsg('没能保存选择，请再试一次。', true); }
  WZ.busy=false; wzLoad(true);
}
async function wzAct(action){
  if (WZ.busy) return; WZ.busy=true; wzMsg(''); wzRender();
  if (action==='choose_ai'){
    WZ.busy=false; closeWizard(); await openSettings('ai'); $('#s_provider').focus(); return;
  }
  try {
    const r = await window.pywebview.api[WZ_ACTIONS[action]]();
    if (r && r.message) wzMsg(r.message, true);
    else if (r && r.ok && action==='choose_folder') loadGallery();
  } catch(e){ wzMsg('没能完成选择，请再试一次。', true); }
  WZ.busy=false; wzLoad(true);
}
$('#w_x').onclick=closeWizard;
$('#wmask').onclick=e=>{ if(e.target.id==='wmask') closeWizard(); };
$('#w_re').onclick=()=>{ wzMsg(''); wzLoad(true); };
$('#w_done').onclick=()=>{ $('#w_never').checked=true; closeWizard(); };
$('#s_wizard').onclick=openWizard;
/* 启动时：没选工作文件夹必弹；第一次打开且有项目需要处理才弹；全部就绪就静默记为已完成。
   “等待”（Lightroom 正在自动启动、插件正在连接）不算需要处理，所以隔几秒再看，最多约 50 秒。 */
async function wizardStartup(){
  for (let i=0; i<17; i++){
    if ($('#wmask').classList.contains('show')) return;
    let r; try { r = await window.pywebview.api.wizard_state(false); } catch(e){ return; }
    if (!r.checking){
      if (r.auto_open){ openWizard(); return; }
      if (r.mark_done){ window.pywebview.api.wizard_done(true).catch(()=>{}); return; }
      if (r.wizard_done || !r.items.some(x=>x.state==='wait')) return;
    }
    await new Promise(x=>setTimeout(x, r.checking ? 500 : 3000));
  }
}
