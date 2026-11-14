/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
/* ---- update check (0.15.0)：只提示，点了才在浏览器里打开发布页；页面不传任何地址 ---- */
let UPD = {state:'idle', latest:'', message:''};
function updRender(u){ UPD = u || UPD;
  const avail = UPD.state==='available';
  $('#updnote').style.display = avail ? '' : 'none'; $('#updtxt').textContent = avail ? '有新版本 ' + UPD.latest : '';
  const msg = {available:'有新版本 ' + UPD.latest, latest:'已是最新版本', unavailable:'暂时无法检查（可能没联网）', checking:'检查中…'}[UPD.state] || '';
  $('#a_updtxt').textContent = msg; $('#a_updopen').style.display = avail ? '' : 'none'; $('#a_updcheck').disabled = UPD.state==='checking'; }
async function updPoll(tries, ms){          // 取一次状态；还在检查中（或启动时后台还没查完）就隔一会儿再取
  for (let i=0; i<tries; i++){
    let u; try { u = await window.pywebview.api.update_state(); } catch(e){ return; }
    updRender(u);
    if (u.state!=='checking' && !(u.state==='idle' && u.enabled && i<4)) return;
    await new Promise(x=>setTimeout(x, ms));
  }
}
async function updOpen(){ try { await window.pywebview.api.open_update_page(); } catch(e){} }
$('#updopen').onclick=updOpen; $('#a_updopen').onclick=updOpen;
$('#a_updcheck').onclick=async()=>{
  try { updRender(await window.pywebview.api.check_update_now()); } catch(e){ updRender({state:'unavailable'}); return; }
  updPoll(40, 500);
};
