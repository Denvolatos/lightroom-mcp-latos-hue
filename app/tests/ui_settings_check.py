# SPDX-License-Identifier: AGPL-3.0-only
# Copyright (C) 2026 Denvolatos and contributors
"""设置对话框界面自查（1.3.0：分栏 + 卡片；无窗口、无 Lightroom、不调用模型，不属于 pytest）。
临时本机静态服务加载 index.html（注入假的 pywebview.api，路径用示例值），用无头 Edge 在页面里跑断言（--dump-dom 读 CHK），
并截图。覆盖：分栏导航与键盘、校验/错误提示（含自动切到出错分栏）、创建文件夹确认、保存内容（含 theme/font_size）、
AI 来源各状态、自动启动 Lightroom、外观即时生效与取消恢复、只读模式、维护三项（成功/失败/取消/二次确认）、
“关于”页（作者链接只传 key、无“待本人确认”、兜底）、窄屏横向标签、无障碍名称、顶栏 Lightroom 启动提示。有问题退出码为 1。
用法：python app/tests/ui_settings_check.py <输出目录>
"""
import sys
from pathlib import Path

from ui_common import Server, build_page, run_jobs

TAIL = r"""<script>
const q = new URLSearchParams(location.search), T = q.get('t');
const $$ = s => document.querySelector(s), vis = e => !!e && e.getBoundingClientRect().width > 0 && e.getBoundingClientRect().height > 0;
const calls = n => window.__CALLS__.filter(c => c[0] === n);
const click = s => $$(s).click();
const dialogText = () => Array.from(document.querySelectorAll('.mask.show .dialog')).map(d => d.innerText).join('\n');
const tabs = ['general','lightroom','ai','safety','maint','about'];
async function openAt(tab){ await openSettings(tab); await wait(120); }
async function key(el, k){ el.dispatchEvent(new KeyboardEvent('keydown', {key:k, bubbles:true, cancelable:true})); await wait(30); }
async function run(){
  await wait(300);
  if (T.indexOf('lr_') === 0) {
    window.onClaudeEvent({type:'status', state:'connecting', text:'Lightroom 正在连接', hint:'正在连接 Lightroom，请稍候。'});
    const m = {lr_starting:['starting','正在启动 Lightroom…'], lr_notfound:['not_found','没找到 Lightroom，请手动打开。也可以在设置里选择 Lightroom 的位置。'],
               lr_timeout:['timeout','Lightroom 已经打开，但插件还没连上。请在 Lightroom 的 文件 → 增效工具管理器 里确认 LrMCP 显示“已安装并正在运行”，必要时点“重新载入增效工具”。']}[T];
    window.onClaudeEvent({type:'lr_launch', state:m[0], message:m[1]}); await wait(150);
    const h = $$('#lrhint'); const probe = T === 'lr_starting' ? '稍候' : m[1].slice(0, 6); ok(h.textContent.indexOf(probe) >= 0 || (h.title || '').indexOf(probe) >= 0, '顶栏没有显示启动提示：' + h.textContent);
    ok(document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1, '页面横向溢出');
    return;
  }
  if (T === 'general') {
    await openAt();
    const nav = $$('#snav'); ok(nav.getAttribute('role') === 'tablist', '导航应为 tablist');
    const tb = document.querySelectorAll('#snav [role=tab]'); ok(tb.length === 6, '应有 6 个分栏，实际 ' + tb.length);
    ok(Array.from(tb).map(b => b.textContent.trim()).join(',') === '常规,Lightroom,AI 来源,安全,维护,关于', '分栏名称/顺序不对');
    tabs.forEach((k, i) => { const t = $$('#tab_' + k), p = $$('#sec_' + k);
      ok(t.getAttribute('aria-controls') === 'sec_' + k && p.getAttribute('aria-labelledby') === 'tab_' + k && p.getAttribute('role') === 'tabpanel', k + ' 的 aria 关联不对');
      ok((t.getAttribute('aria-selected') === 'true') === (i === 0), k + ' aria-selected 不对'); ok(vis(p) === (i === 0), k + ' 面板可见性不对'); });
    ok($$('#s_folder').value === 'D:\\示例\\照片库', '照片库位置没填：' + $$('#s_folder').value);
    ok($$('#s_edge').options.length === 4 && $$('#s_edge').value === '1024', '预览清晰度不对');
    ok($$('#s_theme').value === (q.get('theme') || 'system') && $$('#s_fsize').value === 'standard', '外观默认值不对');
    ok(vis($$('#s_wizard')) && vis($$('#s_upd')), '常规里应有环境检查入口和检查更新开关');
    const all = $$('#smask').innerText + Array.from($$('#smask').querySelectorAll('[title],[aria-label]')).map(e => (e.title||'') + (e.getAttribute('aria-label')||'')).join('');
    ['托盘', '开机自启', '开机启动', '关闭窗口', '最小化到'].forEach(w => ok(all.indexOf(w) < 0, '设置里不应出现“' + w + '”'));
    document.querySelectorAll('#smask .sgroup').forEach(g => ok(parseFloat(getComputedStyle(g).borderTopLeftRadius) === 16, '卡片圆角应为 16px'));
  }
  if (T === 'tabs') {
    await openAt();
    for (const k of tabs) { click('#tab_' + k); await wait(30);
      tabs.forEach(o => ok(vis($$('#sec_' + o)) === (o === k), '点 ' + k + ' 后面板 ' + o + ' 可见性不对'));
      ok($$('#tab_' + k).getAttribute('aria-selected') === 'true' && $$('#tab_' + k).tabIndex === 0, k + ' 选中状态不对'); }
    click('#tab_general'); $$('#tab_general').focus();
    await key($$('#snav'), 'ArrowDown'); ok($$('#tab_lightroom').classList.contains('on') && document.activeElement.id === 'tab_lightroom', '↓ 应到 Lightroom');
    await key($$('#snav'), 'ArrowUp'); await key($$('#snav'), 'ArrowUp'); ok($$('#tab_about').classList.contains('on'), '常规再 ↑ 应循环到关于');
    await key($$('#snav'), 'Home'); ok($$('#tab_general').classList.contains('on'), 'Home 应到常规');
    await key($$('#snav'), 'End'); ok($$('#tab_about').classList.contains('on'), 'End 应到关于');
    await openSettings('safety'); await wait(100); ok(vis($$('#sec_safety')), 'openSettings("safety") 应直接显示安全分栏');
    closeSettings(); await openAt(); ok(vis($$('#sec_general')), '重新打开应回到常规');
  }
  if (T === 'error' || T === 'create' || T === 'saved') {
    await openAt();
    if (T === 'error') {
      click('#tab_lightroom'); $$('#s_folder').value = 'C:\\Windows\\System32'; click('#s_save'); await wait(200);
      ok(vis($$('#sec_general')), '出错的项在“常规”，应自动切到常规分栏');
      ok($$('#e_folder').textContent.indexOf('不能使用系统') >= 0, '没有显示文件夹错误：' + $$('#e_folder').textContent);
      ok($$('#s_msg').textContent.indexOf('设置未保存') >= 0 && $$('#s_msg').classList.contains('bad'), '底部应提示设置未保存');
      ok($$('#smask').classList.contains('show'), '出错时对话框应保持打开'); ok(!$$('#s_save').disabled, '出错后“保存”不应一直灰');
      ok(getComputedStyle($$('#e_folder')).color !== getComputedStyle($$('#s_folder')).color, '错误文字应为红色');
    }
    if (T === 'create') {
      $$('#s_folder').value = 'D:\\新建图库'; click('#s_save'); await wait(200);
      ok(dialogText().indexOf('文件夹不存在') >= 0, '应询问是否创建文件夹'); const b = Array.from(document.querySelectorAll('.mask.show .dialog.small button')).find(x => x.textContent === '创建');
      ok(!!b, '应有“创建”按钮'); if (b) b.click(); await wait(300);
      ok(calls('save_settings').length === 2, '确认创建后应再保存一次，实际 ' + calls('save_settings').length);
      ok(!$$('#smask').classList.contains('show'), '创建并保存后应关闭设置'); ok($$('#toastbox').textContent.indexOf('设置已保存') >= 0, '应提示设置已保存');
    }
    if (T === 'saved') {
      click('#s_save'); await wait(200);
      ok(!$$('#smask').classList.contains('show'), '保存后应关闭'); ok($$('#toastbox').textContent === '设置已保存', '应提示设置已保存');
      const c = window.__SAVED__[0] || {}; ok(c.theme === 'system' && c.font_size === 'standard' && c.preview_edge === 1024 && c.provider === 'claude' && c.base_folder === 'D:\\示例\\照片库', '保存内容不对 ' + JSON.stringify(c));
      ok(!('panel_widths' in c) && !('preview_zoom' in c), '设置页保存不应带面板宽度/缩放');
    }
  }
  if (T === 'provider') {
    await openAt('ai'); const p = $$('#s_pstate').textContent, prov = q.get('prov') || 'ok';
    if (prov === 'ok') ok(p.indexOf('已安装并已登录') >= 0 && $$('#s_pstate').classList.contains('ok'), '应显示已登录（绿色）');
    if (prov === 'nologin') ok(p.indexOf('尚未登录') >= 0 && p.indexOf('/login') >= 0 && $$('#s_pstate').classList.contains('bad'), '应提示未登录和下一步：' + p);
    if (prov === 'missing') ok(p.indexOf('未安装') >= 0 && $$('#s_pstate').classList.contains('bad'), '应提示未安装：' + p);
    const sel = $$('#s_provider'); ok(sel.options.length === 3 && sel.options[2].disabled, 'API 密钥选项应不可选');
    ok(!vis($$('#s_pexp')) && !vis($$('#s_ppriv')), '默认来源不应显示实验性/隐私提示');
    sel.value = 'codex'; sel.onchange(); await wait(50);
    ok(vis($$('#s_pexp')) && $$('#s_pexp').textContent.indexOf('外部贡献者') >= 0, '选 Codex 应显示实验性提示');
    ok(vis($$('#s_ppriv')) && $$('#s_ppriv').textContent.indexOf('发送至所选') >= 0, '选 Codex 应显示隐私提示');
    ok(vis($$('#s_pnote')), '换来源应提示点“新对话”');
    click('#s_save'); await wait(150); ok((window.__SAVED__[0] || {}).provider === 'codex', '应保存所选来源 codex');
  }
  if (T === 'autolr') {
    await openAt('lightroom'); const on = q.get('autolr') === '1';
    ok($$('#s_autolr').classList.contains('on') === on && $$('#s_autolr_t').textContent === (on ? '开' : '关'), '自动启动开关状态不对');
    if (q.get('lrnone')) ok($$('#s_lrnote').textContent.indexOf('没有自动找到') >= 0, '没找到时应提示手动选择');
    else if (q.get('lrpath')) ok($$('#s_lrpath').value.indexOf('Lightroom.exe') >= 0 && $$('#s_lrnote').textContent.indexOf('已指定') >= 0, '已指定路径应显示');
    else ok($$('#s_lrnote').textContent.indexOf('已自动找到') >= 0, '应显示自动找到的路径');
    click('#s_autolr'); await wait(30); ok($$('#s_autolr').classList.contains('on') === !on, '点击应切换');
    click('#s_lrpick'); await wait(150); ok($$('#s_lrpath').value.indexOf('Lightroom Classic') >= 0 && $$('#s_lrnote').textContent.indexOf('已指定') >= 0, '选择文件后应显示新路径');
    click('#s_lrclear'); await wait(30); ok($$('#s_lrpath').value === '', '“自动查找”应清空路径');
    click('#s_save'); await wait(150); const c = window.__SAVED__[0] || {};
    ok(c.auto_launch_lightroom === !on && c.lightroom_path_choice === 'clear', '保存内容不对 ' + JSON.stringify(c));
  }
  if (T === 'appearance') {
    const root = document.documentElement; const t0 = root.dataset.theme;
    await openAt(); const th = $$('#s_theme'), fs = $$('#s_fsize');
    th.value = 'dark'; th.onchange(); await wait(50); ok(root.dataset.theme === 'dark', '选深色应立即生效');
    fs.value = 'large'; fs.onchange(); await wait(50); ok(getComputedStyle(root).fontSize === '17.92px', '选“大”应立即生效');
    ok(document.querySelector('.dialog.settings').getBoundingClientRect().bottom <= innerHeight + 1, '改字号后设置框不应超出窗口');
    click('#s_cancel'); await wait(80);
    ok(root.dataset.theme === t0 && getComputedStyle(root).fontSize === '16px', '取消后外观应恢复：' + root.dataset.theme + ' ' + getComputedStyle(root).fontSize);
    ok(calls('save_settings').length === 0, '取消不应保存');
    await openAt(); ok($$('#s_theme').value === 'system', '重新打开时主题应是已保存的值');
    $$('#s_theme').value = 'dark'; $$('#s_theme').onchange(); $$('#s_fsize').value = 'xlarge'; $$('#s_fsize').onchange(); click('#s_save'); await wait(200);
    const c = window.__SAVED__[0] || {}; ok(c.theme === 'dark' && c.font_size === 'xlarge', '保存应带 theme/font_size ' + JSON.stringify(c));
    ok(root.dataset.theme === 'dark' && getComputedStyle(root).fontSize === '20px', '保存后外观应保持');
    ok(localStorage.getItem('lh_theme') === 'dark' && localStorage.getItem('lh_font_size') === 'xlarge', '保存后应更新本地缓存');
    await openAt(); $$('#s_theme').value = 'light'; $$('#s_theme').onchange(); closeSettings(); await wait(50);
    ok(root.dataset.theme === 'dark', '点遮罩/关闭取消后也应恢复为已保存的深色');
  }
  if (T === 'readonly') {
    await openAt('safety'); const sw = $$('#s_readonly'), fail = !!q.get('rofail'), start = q.get('ro') === '1';
    ok(sw.getAttribute('aria-label').indexOf('只读') >= 0, '只读开关应有名称'); ok(sw.classList.contains('on') === start, '初始状态应与 readonly 字段一致');
    sw.click(); await wait(120);
    ok(calls('set_readonly').length === 1 && calls('set_readonly')[0][1] === !start, '应以布尔值调用 set_readonly(' + !start + ')');
    ok(!sw.disabled, '处理完按钮不应一直灰');
    if (fail) { ok(sw.classList.contains('on') === start, '失败时开关应保持原状'); ok($$('#s_ro_msg').classList.contains('bad') && $$('#s_ro_msg').textContent.indexOf('无法写入') >= 0, '失败应显示中文原因：' + $$('#s_ro_msg').textContent); }
    else { ok(sw.classList.contains('on') === !start, '成功时开关应切换'); ok($$('#s_ro_msg').textContent.indexOf('只读模式已') >= 0, '成功应显示结果：' + $$('#s_ro_msg').textContent); }
    ok(calls('save_settings').length === 0, '切换只读不应触发“保存”');
    ok(document.querySelector('#s_confirm') && vis($$('#s_confirm')), '安全分栏里应有逐项确认默认值');
    sw.click(); await wait(100); ok(calls('set_readonly').length === 2, '可以再次切换');
  }
  if (T === 'maint') {
    await openAt('maint'); const cf = q.get('cachefail'), dg = q.get('diag');
    click('#m_cache'); ok($$('#m_cache').disabled, '处理中按钮应暂时变灰'); await wait(150);
    const cm = $$('#m_cache_msg'); ok(!$$('#m_cache').disabled, '清理缓存结束后按钮必须恢复');
    if (!cf) ok(cm.textContent.indexOf('已清理缓存') >= 0 && cm.textContent.indexOf('12.5 MB') >= 0 && cm.textContent.indexOf('缩略图') >= 0 && cm.classList.contains('ok'), '清理成功信息不对：' + cm.textContent);
    else if (cf === 'throw') ok(cm.classList.contains('bad') && cm.textContent.indexOf('清理缓存没有完成') >= 0, '异常时应有中文提示：' + cm.textContent);
    else ok(cm.classList.contains('bad') && cm.textContent.indexOf('文件正在使用') >= 0, '失败应显示后端原因：' + cm.textContent);
    click('#m_diag'); await wait(150); const dm = $$('#m_diag_msg'); ok(!$$('#m_diag').disabled, '生成诊断包结束后按钮必须恢复');
    if (dg === 'cancel') ok(dm.textContent.indexOf('已取消') >= 0 && !dm.classList.contains('bad'), '取消应提示已取消：' + dm.textContent);
    else if (dg === 'fail') ok(dm.classList.contains('bad') && dm.textContent.indexOf('无法写入') >= 0, '失败应显示原因：' + dm.textContent);
    else ok(dm.textContent.indexOf('诊断包已生成') >= 0 && dm.textContent.indexOf('latoshue-diagnostics.zip') >= 0 && dm.textContent.indexOf('20.0 KB') >= 0, '成功信息不对：' + dm.textContent);
    if (!cf && !dg) {
      applyAppearance('dark', 'large');
      click('#m_reset'); await wait(150);
      const dt = dialogText(); ok(dt.indexOf('恢复默认设置') >= 0 && dt.indexOf('照片库位置和 AI 来源会保留') >= 0, '二次确认应说明会保留照片库位置和 AI 选择：' + dt);
      ok(calls('reset_settings').length === 0, '确认之前不应恢复');
      const cancel = Array.from(document.querySelectorAll('.mask.show .dialog.small button')).find(x => x.textContent === '取消'); cancel.click(); await wait(100);
      ok(calls('reset_settings').length === 0, '取消后不应恢复'); ok(!$$('#m_reset').disabled, '取消后按钮应可用');
      click('#m_reset'); await wait(120);
      const go = Array.from(document.querySelectorAll('.mask.show .dialog.small button')).find(x => x.textContent === '恢复默认'); go.click(); await wait(300);
      ok(calls('reset_settings').length === 1, '确认后应调用一次 reset_settings'); ok(!$$('#m_reset').disabled, '恢复结束后按钮必须恢复');
      ok($$('#m_reset_msg').textContent.indexOf('已恢复默认设置') >= 0, '应显示结果：' + $$('#m_reset_msg').textContent);
      ok($$('#s_theme').value === 'system' && document.documentElement.dataset.theme === 'light' && getComputedStyle(document.documentElement).fontSize === '16px', '恢复后外观应回到默认');
    }
  }
  if (T === 'about') {
    await openAt('about'); await wait(100);
    ok(vis($$('#sec_about')), '应显示关于分栏'); ok($$('#ab_name').textContent === 'Latos Hue 修图助手', '软件名不对');
    ok($$('#ab_tag').textContent.indexOf('挑片、修图、导出') >= 0, '应有一句话介绍'); ok($$('#ab_ver').textContent.indexOf('版本 1.3.0') >= 0 && $$('#ab_ver').textContent.indexOf('插件 1.3.0') >= 0, '版本行不对：' + $$('#ab_ver').textContent);
    ok($$('#a_app').textContent === '1.3.0' && $$('#a_plugin').textContent === '1.3.0' && $$('#a_lr').textContent === '15.0.0', '版本表不对');
    ok($$('#ab_what').textContent.length > 20, '应有“它是什么”');
    ok($$('#ab_license').textContent === 'AGPL-3.0-only', '许可证不对'); ok($$('#a_url').textContent === 'https://github.com/Denvolatos/lightroom-mcp-latos-hue', '项目主页不对');
    ok($$('#ab_disc').textContent.indexOf('不是 Adobe 官方产品') >= 0, '应有声明');
    const ppl = document.querySelectorAll('#ab_authors .person'); ok(ppl.length === 2, '应有两张作者卡片');
    ok(ppl[0].innerText.indexOf('Denvolatos') >= 0 && ppl[0].innerText.indexOf('发起与主要开发') >= 0 && ppl[1].innerText.indexOf('Galio1991') >= 0 && ppl[1].innerText.indexOf('共同开发') >= 0, '作者卡片内容不对');
    const links = document.querySelectorAll('#ab_authors .linkbtn'); ok(links.length === 2, '两个名字都应是链接按钮');
    links.forEach(l => { ok(l.tagName === 'BUTTON' && l.tabIndex >= 0, '链接应可键盘聚焦'); ok(l.title === '在浏览器中打开 GitHub 主页', 'title 不对：' + l.title); ok((l.getAttribute('aria-label') || '').indexOf('在浏览器中打开') >= 0 && l.getAttribute('aria-label').indexOf('GitHub 主页') >= 0, 'aria-label 不对'); });
    ok(getComputedStyle(links[0]).textDecorationLine.indexOf('underline') >= 0 && getComputedStyle(links[0]).cursor === 'pointer', '链接样式不对');
    links[0].focus(); ok(document.activeElement === links[0], '应可聚焦');
    const all = $$('#sec_about').innerText + $$('#sec_about').innerHTML;
    ok(all.indexOf('待本人确认') < 0 && all.indexOf('confirmed') < 0, '不应出现“待本人确认”/confirmed'); ok(all.indexOf('致谢') < 0, '不应有致谢板块');
    ok(all.indexOf('undefined') < 0 && all.indexOf('null') < 0 && all.indexOf('NaN') < 0, '不应出现 undefined/null/NaN');
    links[0].click(); await wait(80); links[1].click(); await wait(80);
    const ol = calls('open_link'); ok(ol.length === 2 && ol[0][1] === 'denvolatos' && ol[1][1] === 'galio1991', '点名字应各调用一次 open_link(key)：' + JSON.stringify(ol));
    ok($$('#ab_linkmsg').textContent.indexOf('已在浏览器中打开') >= 0, '成功应提示');
    click('#ab_open'); await wait(80); ok(calls('open_link').length === 3 && calls('open_link')[2][1] === 'homepage', '项目主页应调用 open_link("homepage")');
    ok(calls('open_link').every(c => c.length === 2 && /^[a-z0-9]+$/.test(c[1])), '页面只应传 key，不传网址');
    click('#ab_copy'); await wait(150); ok($$('#ab_linkmsg').textContent.length > 0, '复制应有结果提示');
    ok(calls('about_info').length >= 1, '应调用 about_info');
  }
  if (T === 'about_linkfail' || T === 'about_linkmsg') {
    await openAt('about'); await wait(100);
    document.querySelectorAll('#ab_authors .linkbtn')[0].click(); await wait(80);
    if (T === 'about_linkfail') ok($$('#ab_linkmsg').textContent === '无法打开，请手动访问：https://github.com/Denvolatos', '没有 message 时应显示手动访问提示：' + $$('#ab_linkmsg').textContent);
    else ok($$('#ab_linkmsg').textContent === '无法打开：系统没有默认浏览器。', '应显示后端 message：' + $$('#ab_linkmsg').textContent);
    ok($$('#ab_linkmsg').classList.contains('bad'), '失败提示应为红色');
    click('#ab_open'); await wait(80);
    if (T === 'about_linkfail') ok($$('#ab_linkmsg').textContent === '无法打开，请手动访问：https://github.com/Denvolatos/lightroom-mcp-latos-hue', '主页失败应显示主页地址：' + $$('#ab_linkmsg').textContent);
  }
  if (T === 'about_fallback') {
    await openAt('about'); await wait(100);
    ok($$('#ab_name').textContent.length > 0 && $$('#a_app').textContent === '1.3.0', 'about_info 失败时应用设置里的信息兜底');
    ok(document.querySelectorAll('#ab_authors .person').length === 2, '兜底也应显示两位作者'); ok($$('#sec_about').innerText.indexOf('undefined') < 0, '不应出现 undefined');
    ok($$('#ab_license').textContent === '—', '没有许可证信息时显示破折号');
  }
  if (T === 'layout') {
    await openAt(); const W = innerWidth, d = document.querySelector('.dialog.settings').getBoundingClientRect();
    ok(d.left >= -1 && d.right <= W + 1 && d.top >= -1 && d.bottom <= innerHeight + 1, '设置框超出窗口 ' + JSON.stringify(d));
    ok(document.documentElement.scrollWidth <= W + 1, '页面横向溢出');
    const nav = $$('#snav').getBoundingClientRect(), pan = $$('.spanels').getBoundingClientRect();
    if (W <= 900) ok(nav.bottom <= pan.top + 1 && nav.width > pan.width * 0.5, '窄屏分栏应变成顶部横排'); else ok(nav.right <= pan.left + 1 && nav.width < 240, '宽屏分栏应在左侧竖排');
    for (const k of tabs) { click('#tab_' + k); await wait(30); const p = $$('#sec_' + k);
      ok(p.scrollWidth <= p.clientWidth + 1, k + ' 分栏出现横向溢出 ' + p.scrollWidth + '>' + p.clientWidth);
      p.querySelectorAll('button, select, input').forEach(e => { const r = e.getBoundingClientRect(); if (r.width && (r.right > W + 1 || r.left < -1)) ok(false, k + ' 里有控件超出窗口：' + (e.id || e.textContent)); }); }
    const f = $$('.sfoot').getBoundingClientRect(); ok(f.bottom <= innerHeight + 1 && vis($$('#s_save')), '底部保存按钮应始终可见');
  }
  if (T === 'a11y') {
    await openAt();
    for (const k of tabs) { click('#tab_' + k); await wait(30);
      $$('#sec_' + k).querySelectorAll('button, input, select').forEach(e => {
        const name = (e.getAttribute('aria-label') || '').trim() || (e.textContent || '').trim() || (e.id && document.querySelector('label[for="' + e.id + '"]') ? 'label' : '') || (e.closest('.srow') && e.closest('.srow').querySelector('.lab') ? 'lab' : '');
        ok(!!name, k + ' 里有控件没有可访问名称：' + e.outerHTML.slice(0, 90)); }); }
    ok($$('.dialog.settings').getAttribute('aria-label') === '设置' && $$('.dialog.settings').getAttribute('role') === 'dialog', '对话框应有 role 与名称');
  }
}
run().then(() => __finish(T), e => { window.__bad.push('脚本异常 ' + e + (e && e.stack ? e.stack.slice(0, 200) : '')); __finish(T); });
</script>"""


def main(out: Path) -> int:
    out.mkdir(parents=True, exist_ok=True)
    srv = Server(build_page(TAIL))
    try:
        jobs = [
            ("settings_general_light", "theme=light&t=general", 1440, 900, False, True),
            ("settings_general_dark", "theme=dark&t=general", 1440, 900, False, True),
            ("settings_tabs", "t=tabs", 1100, 700, False, False),
            ("settings_error", "t=error", 1440, 900, False, True),
            ("settings_create", "t=create", 1100, 700, False, False),
            ("settings_saved", "t=saved", 1100, 700, False, False),
            ("settings_provider_ok", "t=provider", 1440, 900, False, False),
            ("settings_provider_nologin", "t=provider&prov=nologin", 1440, 900, False, True),
            ("settings_provider_missing", "t=provider&prov=missing", 1440, 900, False, False),
            ("settings_autolr_off", "t=autolr", 1100, 700, False, False),
            ("settings_autolr_on", "t=autolr&autolr=1", 1100, 700, False, False),
            ("settings_autolr_set", "t=autolr&lrpath=1", 1100, 700, False, False),
            ("settings_autolr_none", "t=autolr&lrnone=1", 1100, 700, False, False),
            ("settings_appearance", "t=appearance", 1100, 700, False, False),
            ("settings_readonly", "t=readonly", 1100, 700, False, False),
            ("settings_readonly_on", "t=readonly&ro=1", 1100, 700, False, False),
            ("settings_readonly_fail", "t=readonly&rofail=1", 1100, 700, False, False),
            ("settings_maint", "t=maint", 1100, 700, False, False),
            ("settings_maint_cachefail", "t=maint&cachefail=1", 1100, 700, False, False),
            ("settings_maint_cachethrow", "t=maint&cachefail=throw", 1100, 700, False, False),
            ("settings_maint_diag_cancel", "t=maint&diag=cancel", 1100, 700, False, False),
            ("settings_maint_diag_fail", "t=maint&diag=fail", 1100, 700, False, False),
            ("settings_about_light", "theme=light&t=about", 1440, 900, False, True),
            ("settings_about_dark", "theme=dark&t=about", 1440, 900, False, True),
            ("settings_about_linkfail", "t=about_linkfail&linkfail=1", 1100, 700, False, False),
            ("settings_about_linkmsg", "t=about_linkmsg&linkfail=msg", 1100, 700, False, False),
            ("settings_about_fallback", "t=about_fallback&noabout=1", 1100, 700, False, False),
            ("settings_a11y", "t=a11y", 1100, 700, False, False),
            ("settings_lr_starting", "t=lr_starting", 1440, 900, False, True),
            ("settings_lr_notfound", "t=lr_notfound", 1440, 900, False, False),
            ("settings_lr_timeout", "t=lr_timeout", 1440, 900, False, False),
        ]
        for f in ("small", "standard", "large", "xlarge"):
            for th in ("light", "dark"):
                for w in (800, 1100, 1440):
                    jobs.append((f"settings_layout_{f}_{th}_{w}", f"t=layout&font={f}&theme={th}", w, 700 if w < 1440 else 860, False, f == "large" and w == 800 and th == "light"))
        code = run_jobs(srv, jobs, out)
    finally:
        srv.close()
    return code


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
