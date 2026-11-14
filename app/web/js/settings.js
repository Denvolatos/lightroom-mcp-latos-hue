/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- settings dialog ---- */
let SET = null, setConfirm = true;
function setConfirmUI(v){ setConfirm=!!v; $('#s_confirm').classList.toggle('on', setConfirm); $('#s_confirm_t').textContent = setConfirm ? '开' : '关'; }
$('#s_confirm').onclick=()=>setConfirmUI(!setConfirm);
let setNotes = true;
function setNotesUI(v){ setNotes=!!v; $('#s_notes').classList.toggle('on', setNotes); $('#s_notes_t').textContent = setNotes ? '开' : '关'; }
$('#s_notes').onclick=()=>setNotesUI(!setNotes);
let setAutoLr = false, lrChoice = null;     // lrChoice：null 不变 / 'pending' 用刚选的文件 / 'clear' 改回自动查找
function setAutoLrUI(v){ setAutoLr=!!v; $('#s_autolr').classList.toggle('on', setAutoLr); $('#s_autolr_t').textContent = setAutoLr ? '开' : '关'; }
$('#s_autolr').onclick=()=>setAutoLrUI(!setAutoLr);
let setUpd = true;                          // 设置：启动时检查新版本（默认开）
function setUpdUI(v){ setUpd=!!v; $('#s_upd').classList.toggle('on', setUpd); $('#s_upd_t').textContent = setUpd ? '开' : '关'; }
$('#s_upd').onclick=()=>setUpdUI(!setUpd);
function showLrPath(picked){
  const saved = (SET && SET.settings.lightroom_path) || '', det = (SET && SET.lightroom_detected) || '';
  const shown = lrChoice==='clear' ? '' : (picked || saved);
  $('#s_lrpath').value = shown; $('#s_lrpath').placeholder = '自动查找';
  $('#s_lrnote').textContent = shown ? '已指定上面这个 Lightroom 程序。' :
    (det ? '已自动找到：' + det : '没有自动找到 Lightroom。你可以点“选择文件”，选中 Lightroom 安装目录里的 Lightroom.exe；找不到时，打开软件后请手动打开 Lightroom。');
}
$('#s_lrpick').onclick=async()=>{
  $('#e_lrpath').textContent='';
  const r = await window.pywebview.api.choose_lightroom_path();
  if (r.ok){ lrChoice='pending'; showLrPath(r.path); } else if (r.message){ $('#e_lrpath').textContent = r.message; $('#e_lrpath').style.color=''; }
};
$('#s_lrclear').onclick=()=>{ lrChoice='clear'; showLrPath(''); };
function showProviderState(){
  const p = SET.providers.find(x=>x.id===$('#s_provider').value) || SET.providers[0];
  const st = $('#s_pstate'); st.className = 'sub ' + (p.selectable ? (p.available ? 'ok' : 'bad') : '');
  st.textContent = p.selectable ? p.reason + (p.next_step ? ' ' + p.next_step : '') : p.reason;
  const chosen = SET.settings.provider_chosen !== false;
  $('#s_provider').disabled = !chosen;
  $('#s_pnote').textContent = chosen ? '保存后点击顶部“新对话”，开始使用所选来源。' : '还没有选择 AI 来源。请点上面的“打开环境检查”，在那里选择要使用的 AI。';
  $('#s_pnote').style.display = (!chosen || (p.selectable && p.id !== SET.current_provider)) ? '' : 'none';
  if (!chosen){ st.className='sub'; st.textContent=''; }
  const ex = $('#s_pexp'), pv = $('#s_ppriv');
  ex.textContent = p.experimental ? (p.experimental_notice || '') : ''; ex.style.display = ex.textContent ? '' : 'none';
  pv.textContent = p.privacy_notice || ''; pv.style.display = pv.textContent ? '' : 'none';
}
$('#s_provider').onchange=showProviderState;
function fillSettings(r){
  SET = r; const s = r.settings;
  $('#s_folder').value = s.base_folder;
  const sel = $('#s_provider'); sel.innerHTML='';
  r.providers.forEach(p=>{ const o=document.createElement('option'); o.value=p.id; o.textContent=p.name + (p.experimental?'（实验性，未经真机验证）':'') + (p.selectable?'':'（后续提供）'); o.disabled=!p.selectable; sel.appendChild(o); });
  if (s.provider_chosen === false){ const o=document.createElement('option'); o.value=''; o.textContent='尚未选择'; sel.insertBefore(o, sel.firstChild); sel.value=''; }
  else sel.value = s.provider;
  const ed = $('#s_edge'); ed.innerHTML=''; r.edges.forEach(e=>{ const o=document.createElement('option'); o.value=e; o.textContent='长边 '+e+' px'; ed.appendChild(o); }); ed.value = s.preview_edge;
  setConfirmUI(s.confirm_default); setNotesUI(s.ai_use_notes!==false); showProviderState();
  setAutoLrUI(s.auto_launch_lightroom===true); lrChoice=null; showLrPath('');
  setUpdUI(s.check_updates!==false); updRender(UPD);
  const a = r.about;
  $('#a_app').textContent = a.app_version; $('#a_lr').textContent = a.lightroom_version || '未连接，无法读取';
  $('#a_plugin').textContent = a.plugin_version || '未连接，无法读取'; $('#a_data').textContent = a.data_dir; $('#a_url').textContent = a.project_url;
}
function clearSettingsErrors(){ ['folder','provider','edge','lrpath'].forEach(k=>{ $('#e_'+k).textContent=''; }); $('#s_msg').textContent=''; $('#s_msg').className='msg-line'; }
/* 读取设置期间：字段和“保存”都变灰，避免改了又被读回来的值冲掉，或把旧值存回去 */
let SETLOAD = 0;
function settingsLock(on){
  document.querySelectorAll('#smask .body button, #smask .body input, #smask .body select, #s_save').forEach(e=>{ e.disabled = !!on; });
}
async function openSettings(){
  if (!REAL()) return;
  const tok = ++SETLOAD;
  clearSettingsErrors(); $('#smask').classList.add('show');
  $('#s_msg').textContent = '正在读取设置…'; settingsLock(true);
  let r = null;
  try { r = await window.pywebview.api.get_settings(true); } catch(e){}
  if (tok!==SETLOAD) return;                       // 期间又打开了一次：以后一次为准
  if (!r || !r.settings){ $('#s_msg').textContent='无法读取设置，请关闭后重试。'; $('#s_msg').className='msg-line bad'; return; }   // 读不到时不能保存
  settingsLock(false);
  fillSettings(r); $('#s_msg').textContent = SET.settings.base_folder ? '' : '请先选择照片工作文件夹。';
}
function closeSettings(){ $('#smask').classList.remove('show'); SETLOAD++; }
$('#s_cancel').onclick=closeSettings;
$('#smask').onclick=e=>{ if(e.target.id==='smask') closeSettings(); };
$('#s_pick').onclick=async()=>{
  const r = await window.pywebview.api.choose_folder($('#s_folder').value);
  if (!r.ok) return;
  $('#s_folder').value = r.path; const v = await window.pywebview.api.check_folder(r.path);
  $('#e_folder').textContent = v.ok ? (v.exists ? '' : '该文件夹尚不存在，保存时将询问是否创建。') : v.message;
  $('#e_folder').style.color = v.ok ? 'var(--muted)' : '';
};
const FIELD_KEYS = {base_folder:'folder', provider:'provider', preview_edge:'edge', lightroom_path:'lrpath'};
async function saveSettings(createMissing=false){
  clearSettingsErrors();
  const changes = {base_folder: $('#s_folder').value, provider: $('#s_provider').value,
                   confirm_default: setConfirm, ai_use_notes: setNotes, preview_edge: parseInt($('#s_edge').value,10),
                   auto_launch_lightroom: setAutoLr, check_updates: setUpd};
  if (lrChoice) changes.lightroom_path_choice = lrChoice;
  $('#s_save').disabled = true;
  const r = await safeCall(()=>window.pywebview.api.save_settings(changes, createMissing), $('#s_save'), '设置没有保存，请重试。');
  if (!r) return;
  $('#s_save').disabled = false;
  if (r.ok){
    SET.settings = r.settings; confirmDefault = r.settings.confirm_default;
    $('#edge').value = String(r.settings.preview_edge);
    closeSettings(); toast('设置已保存'); return;
  }
  if (r.needs_create){
    if (await askDialog('创建文件夹', '文件夹不存在：\n' + $('#s_folder').value + '\n是否创建？', '创建')) return saveSettings(true);
    $('#e_folder').textContent = '文件夹尚未创建，设置未保存。'; return;
  }
  let shown = false;
  Object.entries(r.errors||{}).forEach(([k,m])=>{ const el = $('#e_'+(FIELD_KEYS[k]||'')); if (el){ el.textContent=m; el.style.color=''; shown=true; } });
  const m = $('#s_msg'); m.className='msg-line bad';
  m.textContent = (r.errors && r.errors._) ? r.errors._ : (shown ? '设置未保存，请修正标红项。' : '设置未保存。');
}
$('#s_save').onclick=()=>{ if (!SET || $('#s_save').disabled) return; saveSettings(false); };
