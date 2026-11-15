/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* 真实模式：隐藏演示标记，显示 Lightroom 连接状态 */
if (location.hash !== '#demo') window.addEventListener('pywebviewready', ()=>{
  $('#demobadge').style.display='none';
  $('#newchat').style.display=''; $('#setbtn').style.display='';
  const ready=()=>{ try { window.pywebview.api.ui_ready(); } catch(e){} };   // 告诉软件主界面已准备好：关闭启动界面、显示主窗口
  window.pywebview.api.get_settings(false).then(r=>{ confirmDefault=r.settings.confirm_default; setAsk(confirmDefault); applyAppearance(r.settings.theme, r.settings.font_size); layoutFromSettings(r.settings); zoomFromSettings(r.settings);
    $('#edge').value=String(r.settings.preview_edge); ready(); wizardStartup(); updPoll(8, 2500); }).catch(ready);
  const poll=()=>window.pywebview.api.status().then(s=>{ showStatus(s); if (s.photo && s.photo.name && s.photo.name!==photoName){ photoName=s.photo.name; renderStage(); } }).catch(()=>{});
  window.pywebview.api.autolaunch_state().then(r=>{ if (r && r.state!=='idle') onLrLaunch(r); }).catch(()=>{});
  window.pywebview.api.preview_state().then(r=>{ pv=r; renderStage(); }).catch(()=>{});
  window.pywebview.api.selection_state().then(r=>{ SEL = r; updatePickBtn(); }).catch(()=>{});
  poll(); setInterval(poll, 3000); renderParams(); renderStage(); loadGallery(); loadLib();
  window.pywebview.api.import_state().then(st=>{   // 页面重新加载时接续导入界面
    if (st.stage==='scanning'){ IM.stage='scanning'; imScanning(0); }
    else if (st.stage==='ready'){ imConfirm(); }
    else if (st.stage==='copying'&&st.progress){ IM.stage='copying'; imProgress(st.progress); }
    else if (st.stage==='done'&&st.result){ imResult(st.result); } }).catch(()=>{}); });
function renderAll(){ renderLeft(); renderFiles(); renderStage(); renderParams(); }
renderAll();
/* 截图用：地址后加 #demo 会自动演示一轮 */
if (location.hash === '#demo') {
  say('提高天空通透度，增强整体层次感', 'me');
  say('已收到需求，正在分析照片并制定调整方案。（演示回复）');
  runPlan(0);
}
