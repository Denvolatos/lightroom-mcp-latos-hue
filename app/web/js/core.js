/* SPDX-License-Identifier: AGPL-3.0-only */
/* Copyright (C) 2026 Denvolatos and contributors */
const PHOTOS = [
  {n:'DSC08205.JPG', f:'雪山', c:'#6f93b8'}, {n:'DSC08206.JPG', f:'雪山', c:'#8aa5bd'},
  {n:'DSC08211.JPG', f:'雪山', c:'#5d7f9e'}, {n:'IMG_0412.JPG', f:'街拍', c:'#b08968'},
  {n:'IMG_0415.JPG', f:'街拍', c:'#9c7a5b'}, {n:'IMG_0420.JPG', f:'未分类', c:'#7a8f6a'}
];
const PRESETS = ['清爽风光', '电影感', '黑白高对比', '日系低饱和'];
const EXPERIENCE = ['天空发灰：先降低高光，再提高蓝色饱和度', '逆光人像：阴影 +40，曝光小幅降低'];
let sel = 0, fav = new Set([0]), favP = new Set(['电影感']), steps = [], history = [], mode = 'pair', ask = true;

const $ = s => document.querySelector(s);
function toast(t){ const b=$('#toastbox'); b.textContent=t; clearTimeout(toast.t); toast.t=setTimeout(()=>b.textContent='',6000); }
/* 调用后端：Python 抛异常时 promise 会失败。这里接住它，提示一句、把按钮恢复可点，返回 null（调用处见到 null 就停下）。
   btn 可以是按钮元素或选择器；按钮已经不在页面上时不管它。 */
async function safeCall(fn, btn, msg){
  try { const r = await fn(); return r==null ? {} : r; }
  catch(e){
    const b = typeof btn==='string' ? $(btn) : btn;
    if (b && b.isConnected) b.disabled = false;
    toast(msg || '操作没有完成，请重试。'); return null;
  }
}
