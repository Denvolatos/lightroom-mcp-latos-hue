/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- 设置对话框（1.3.0：左侧分栏导航 + 右侧卡片）----
   保存方式不变：改了字段后点“保存”，一次提交（save_settings）。外观（主题、字号）选了立刻预览生效；“保存”才写入，“取消”恢复原样。
   只读模式、清理缓存、生成诊断包、恢复默认设置是“立即动作”：点了就执行，不依赖“保存”。 */
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
  $('#s_pnote').textContent = chosen ? '保存后点击顶部“新对话”，开始使用所选来源。' : '还没有选择 AI 来源。请点“常规”里的“打开环境检查”，在那里选择要使用的 AI。';
  $('#s_pnote').style.display = (!chosen || (p.selectable && p.id !== SET.current_provider)) ? '' : 'none';
  if (!chosen){ st.className='sub'; st.textContent=''; }
  const ex = $('#s_pexp'), pv = $('#s_ppriv');
  ex.textContent = p.experimental ? (p.experimental_notice || '') : ''; ex.style.display = ex.textContent ? '' : 'none';
  pv.textContent = p.privacy_notice || ''; pv.style.display = pv.textContent ? '' : 'none';
}
$('#s_provider').onchange=showProviderState;

/* ---- 分栏导航：左侧竖排（窄屏变顶部横排）；方向键/Home/End 在标签间移动 ---- */
const SET_TABS = ['general','lightroom','ai','safety','maint','about'];
function selectSettingsTab(sec, focus){
  if (SET_TABS.indexOf(sec) < 0) sec = 'general';
  SET_TABS.forEach(k=>{
    const t = $('#tab_'+k), p = $('#sec_'+k), on = k===sec;
    t.classList.toggle('on', on); t.setAttribute('aria-selected', on ? 'true' : 'false'); t.tabIndex = on ? 0 : -1;
    p.classList.toggle('on', on); p.hidden = !on;
  });
  $('#smask .spanels').scrollTop = 0;
  if (focus) $('#tab_'+sec).focus();
  if (sec==='about') loadAbout();
}
$('#snav').onclick=e=>{ const b = e.target.closest('[data-sec]'); if (b) selectSettingsTab(b.dataset.sec, false); };
$('#snav').onkeydown=e=>{
  const cur = SET_TABS.findIndex(k=>$('#tab_'+k).classList.contains('on')); let n = -1;
  if (e.key==='ArrowDown' || e.key==='ArrowRight') n = (cur+1) % SET_TABS.length;
  else if (e.key==='ArrowUp' || e.key==='ArrowLeft') n = (cur+SET_TABS.length-1) % SET_TABS.length;
  else if (e.key==='Home') n = 0; else if (e.key==='End') n = SET_TABS.length-1;
  if (n >= 0){ e.preventDefault(); selectSettingsTab(SET_TABS[n], true); }
};

/* ---- 外观：选了立刻生效；取消时恢复到打开设置时的样子 ---- */
let APP_SAVED = {theme:'system', font_size:'standard'}, setSaved = false;
function appearanceFromUI(){ return {theme: $('#s_theme').value, font_size: $('#s_fsize').value}; }
$('#s_theme').onchange=$('#s_fsize').onchange=()=>{ const a = appearanceFromUI(); applyAppearance(a.theme, a.font_size); };

/* ---- 只读模式：立即生效 ---- */
let setReadonly = false, roBusy = false;
function setReadonlyUI(v){ setReadonly=!!v; $('#s_readonly').classList.toggle('on', setReadonly); $('#s_readonly_t').textContent = setReadonly ? '开' : '关'; }
function setRoMsg(t, bad){ const m=$('#s_ro_msg'); m.textContent=t||''; m.className='sub mres'+(bad?' bad':(t?' ok':'')); }
$('#s_readonly').onclick=async()=>{
  if (roBusy || $('#s_readonly').disabled) return;
  roBusy = true; $('#s_readonly').disabled = true; const want = !setReadonly; setRoMsg('正在切换…');
  try {
    const r = await window.pywebview.api.set_readonly(want);
    if (r && r.ok){ setReadonlyUI(r.readonly !== undefined ? r.readonly : want); setRoMsg(r.message || (setReadonly ? '只读模式已开启。' : '只读模式已关闭。')); }
    else { if (r && r.readonly !== undefined) setReadonlyUI(r.readonly); setRoMsg((r && r.message) || '没能切换只读模式，请重试。', true); }
  } catch(e){ setRoMsg('没能切换只读模式，请重试。', true); }
  finally { roBusy = false; $('#s_readonly').disabled = false; }
};

/* ---- 维护：清理缓存 / 生成诊断包 / 恢复默认设置（都显示中文结果；按钮不会一直灰） ---- */
function fmtBytes(n){ n = Number(n)||0; const u=['B','KB','MB','GB']; let i=0; while (n>=1024 && i<u.length-1){ n/=1024; i++; } return (i? n.toFixed(1) : String(Math.round(n))) + ' ' + u[i]; }
function maintMsg(id, t, bad){ const m=$('#'+id); m.textContent=t||''; m.className='sub mres'+(bad?' bad':(t?' ok':'')); }
async function maintRun(btnId, msgId, work, failText){
  const b = $('#'+btnId); if (b.disabled) return;
  b.disabled = true; maintMsg(msgId, '处理中…');
  try { await work(); }
  catch(e){ maintMsg(msgId, failText, true); }
  finally { b.disabled = false; }
}
$('#m_cache').onclick=()=>maintRun('m_cache', 'm_cache_msg', async()=>{
  const r = await window.pywebview.api.clear_cache();
  if (!r || !r.ok){ maintMsg('m_cache_msg', (r && r.message) || '清理缓存没有完成，请重试。', true); return; }
  const parts = (r.items||[]).filter(i=>i && i.name).map(i=>i.name + ' ' + fmtBytes(i.bytes)).join('、');
  maintMsg('m_cache_msg', (r.message || ('已清理缓存' + (r.freed_text ? '，释放 ' + r.freed_text : '') + '。')) + (parts ? '（' + parts + '）' : ''));
}, '清理缓存没有完成，请重试。');
$('#m_diag').onclick=()=>maintRun('m_diag', 'm_diag_msg', async()=>{
  const r = await window.pywebview.api.make_diagnostics();
  if (r && r.cancelled){ maintMsg('m_diag_msg', '已取消，没有生成诊断包。'); return; }
  if (!r || !r.ok){ maintMsg('m_diag_msg', (r && r.message) || '生成诊断包没有完成，请重试。', true); return; }
  maintMsg('m_diag_msg', (r.message || '诊断包已生成。') + (r.path ? ' 保存位置：' + r.path : '') + (r.bytes ? '（' + fmtBytes(r.bytes) + '）' : ''));
}, '生成诊断包没有完成，请重试。');
$('#m_reset').onclick=async()=>{
  if ($('#m_reset').disabled) return;
  if (!await askDialog('恢复默认设置', '将把设置恢复成初始值，包括外观、预览清晰度、逐项确认、经验库、自动启动 Lightroom、面板宽度等。\n\n照片库位置和 AI 来源会保留，不会改变；照片不会被删除。\n\n是否继续？', '恢复默认')) return;
  await maintRun('m_reset', 'm_reset_msg', async()=>{
    const r = await window.pywebview.api.reset_settings();
    if (!r || !r.ok){ maintMsg('m_reset_msg', (r && r.message) || '恢复默认设置没有完成，请重试。', true); return; }
    let fresh = null; try { fresh = await window.pywebview.api.get_settings(true); } catch(e){}
    if (fresh && fresh.settings){ fillSettings(fresh); afterSettingsChanged(fresh.settings); }
    maintMsg('m_reset_msg', r.message || '已恢复默认设置。');
  }, '恢复默认设置没有完成，请重试。');
};

/* 设置读回或改变后，把相关的界面状态同步一遍（外观、逐项确认默认值、预览清晰度、面板宽度、预览缩放） */
function afterSettingsChanged(s){
  if (!s) return;
  if (s.confirm_default !== undefined){ confirmDefault = s.confirm_default; }
  if (s.preview_edge !== undefined) $('#edge').value = String(s.preview_edge);
  applyAppearance(s.theme, s.font_size); APP_SAVED = appearanceNow();
  if (typeof layoutFromSettings === 'function') layoutFromSettings(s);
  if (typeof zoomFromSettings === 'function') zoomFromSettings(s);
}

/* ---- “关于”分栏（1.3.0）：about_info() 取不到时用设置里已有的信息兜底，不会出现 undefined ----
   链接只传固定的 key（homepage / denvolatos / galio1991）给 open_link，页面绝不自己传网址。 */
let ABOUT = null;
function aboutText(v, d){ return (v === undefined || v === null || v === '') ? (d||'') : String(v); }
function personCard(a){
  const d = document.createElement('div'); d.className = 'person';
  const name = aboutText(a.name, '（未署名）');
  if (a.key){
    const b = document.createElement('button'); b.type = 'button'; b.className = 'linkbtn'; b.textContent = name; b.dataset.key = a.key;
    b.title = '在浏览器中打开 GitHub 主页'; b.setAttribute('aria-label', '在浏览器中打开 ' + name + ' 的 GitHub 主页');
    b.onclick = ()=>openLink(a.key, 'ab_linkmsg', a.url); d.appendChild(b);
  } else { const b = document.createElement('b'); b.textContent = name; d.appendChild(b); }
  const role = document.createElement('div'); role.className = 'ab-role'; role.textContent = aboutText(a.role); d.appendChild(role);
  return d;
}
function renderAbout(info){
  const a = (SET && SET.about) || {};
  const i = info || {};
  $('#ab_name').textContent = aboutText(i.name, 'Latos Hue 修图助手');
  $('#ab_tag').textContent = aboutText(i.tagline);
  const ver = aboutText(i.version, a.app_version), plug = aboutText(i.plugin_version, a.plugin_version);
  $('#ab_ver').textContent = ver ? '版本 ' + ver + (plug ? ' · 插件 ' + plug : '') : '';
  if (ver) $('#a_app').textContent = ver;
  if (plug) $('#a_plugin').textContent = plug;
  $('#ab_license').textContent = aboutText(i.license, '—');
  $('#a_url').textContent = aboutText(i.homepage, a.project_url);
  $('#ab_disc').textContent = aboutText(i.disclaimer, '—');
  const list = Array.isArray(i.authors) && i.authors.length ? i.authors : [{name:'Denvolatos', key:'denvolatos'}, {name:'Galio1991', key:'galio1991'}];
  const box = $('#ab_authors'); box.innerHTML = ''; list.forEach(x=>box.appendChild(personCard(x || {})));
}
async function loadAbout(){
  renderAbout(ABOUT);                                  // 先用已有的信息显示，about_info 回来后再更新
  let info = null;
  try { info = await window.pywebview.api.about_info(); } catch(e){}
  if (info && (info.name || info.version)){ ABOUT = info; }
  renderAbout(ABOUT);
}
async function openLink(key, msgId, urlText){
  const m = $('#'+msgId); m.textContent = '';
  let r = null;
  try { r = await window.pywebview.api.open_link(key); } catch(e){}
  const shown = aboutText(urlText, $('#a_url').textContent);
  m.textContent = (r && r.ok) ? '已在浏览器中打开。' : ((r && r.message) || ('无法打开，请手动访问：' + shown));
  m.className = 'ab-note' + ((r && r.ok) ? ' ok' : ' bad');
}
async function copyText(t){
  try { await navigator.clipboard.writeText(t); return true; } catch(e){}
  try { const ta = document.createElement('textarea'); ta.value = t; ta.style.cssText = 'position:fixed;left:-9999px'; document.body.appendChild(ta); ta.select(); const ok = document.execCommand('copy'); ta.remove(); return !!ok; } catch(e){ return false; }
}
$('#ab_open').onclick=()=>openLink('homepage', 'ab_linkmsg');
$('#ab_copy').onclick=async()=>{
  const m = $('#ab_linkmsg'), ok = await copyText($('#a_url').textContent);
  m.textContent = ok ? '已复制。' : '复制没有成功，请手动选中文字复制。'; m.className = 'ab-note' + (ok ? ' ok' : ' bad');
};

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
  setReadonlyUI(r.readonly === true); setRoMsg('');
  const th = themeNormalize(s.theme);
  const fs = ['small','standard','large','xlarge'].indexOf(s.font_size) >= 0 ? s.font_size : 'standard';
  $('#s_theme').value = th; $('#s_fsize').value = fs; applyAppearance(th, fs); APP_SAVED = appearanceNow();
  const a = r.about || {};
  $('#a_app').textContent = aboutText(a.app_version); $('#a_lr').textContent = a.lightroom_version || '未连接，无法读取';
  $('#a_plugin').textContent = a.plugin_version || '未连接，无法读取'; $('#a_data').textContent = aboutText(a.data_dir); $('#a_url').textContent = aboutText(a.project_url);
  renderAbout(ABOUT);
}
function clearSettingsErrors(){ ['folder','provider','edge','lrpath'].forEach(k=>{ $('#e_'+k).textContent=''; }); $('#s_msg').textContent=''; $('#s_msg').className='msg-line';
  ['m_cache_msg','m_diag_msg','m_reset_msg'].forEach(k=>maintMsg(k, '')); $('#ab_linkmsg').textContent=''; }
/* 读取设置期间：字段和“保存”都变灰，避免改了又被读回来的值冲掉，或把旧值存回去 */
let SETLOAD = 0;
function settingsLock(on){
  document.querySelectorAll('#smask .body button, #smask .body input, #smask .body select, #s_save').forEach(e=>{ e.disabled = !!on; });
}
async function openSettings(tab){
  if (!REAL()) return;
  const tok = ++SETLOAD;
  APP_SAVED = appearanceNow(); setSaved = false;
  clearSettingsErrors(); selectSettingsTab(typeof tab === 'string' ? tab : 'general', false); $('#smask').classList.add('show');
  $('#s_msg').textContent = '正在读取设置…'; settingsLock(true);
  let r = null;
  try { r = await window.pywebview.api.get_settings(true); } catch(e){}
  if (tok!==SETLOAD) return;                       // 期间又打开了一次：以后一次为准
  if (!r || !r.settings){ $('#s_msg').textContent='无法读取设置，请关闭后重试。'; $('#s_msg').className='msg-line bad'; return; }   // 读不到时不能保存
  settingsLock(false);
  fillSettings(r); $('#s_msg').textContent = SET.settings.base_folder ? '' : '请先选择照片工作文件夹。';
}
function closeSettings(){
  if (!setSaved){ applyAppearance(APP_SAVED.theme, APP_SAVED.font_size); }     // 没保存：外观恢复成打开设置时的样子
  $('#smask').classList.remove('show'); SETLOAD++;
}
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
const FIELD_TABS = {folder:'general', edge:'general', lrpath:'lightroom', provider:'ai'};
async function saveSettings(createMissing=false){
  clearSettingsErrors();
  const ap = appearanceFromUI();
  const changes = {base_folder: $('#s_folder').value, provider: $('#s_provider').value,
                   confirm_default: setConfirm, ai_use_notes: setNotes, preview_edge: parseInt($('#s_edge').value,10),
                   auto_launch_lightroom: setAutoLr, check_updates: setUpd, theme: ap.theme, font_size: ap.font_size};
  if (lrChoice) changes.lightroom_path_choice = lrChoice;
  $('#s_save').disabled = true;
  const r = await safeCall(()=>window.pywebview.api.save_settings(changes, createMissing), $('#s_save'), '设置没有保存，请重试。');
  if (!r) return;
  $('#s_save').disabled = false;
  if (r.ok){
    SET.settings = r.settings; confirmDefault = r.settings.confirm_default;
    $('#edge').value = String(r.settings.preview_edge);
    applyAppearance(r.settings.theme !== undefined ? r.settings.theme : ap.theme, r.settings.font_size !== undefined ? r.settings.font_size : ap.font_size);
    setSaved = true; closeSettings(); toast('设置已保存'); return;
  }
  if (r.needs_create){
    selectSettingsTab('general', false);
    if (await askDialog('创建文件夹', '文件夹不存在：\n' + $('#s_folder').value + '\n是否创建？', '创建')) return saveSettings(true);
    $('#e_folder').textContent = '文件夹尚未创建，设置未保存。'; return;
  }
  let shown = false, firstTab = null;
  Object.entries(r.errors||{}).forEach(([k,m])=>{ const el = $('#e_'+(FIELD_KEYS[k]||'')); if (el){ el.textContent=m; el.style.color=''; shown=true; if (!firstTab) firstTab = FIELD_TABS[FIELD_KEYS[k]]; } });
  if (firstTab) selectSettingsTab(firstTab, false);                // 出错的项在哪个分栏，就切过去让用户看到红字
  const m = $('#s_msg'); m.className='msg-line bad';
  m.textContent = (r.errors && r.errors._) ? r.errors._ : (shown ? '设置未保存，请修正标红项。' : '设置未保存。');
}
$('#s_save').onclick=()=>{ if (!SET || $('#s_save').disabled) return; saveSettings(false); };
